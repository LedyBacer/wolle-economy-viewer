"""Оверлей банковских оплат: `loader → calc_* → attach_bank_status(df, mp)`.

Контракт — 7 полей + bank_amount_src:
bank_status/confirmed|likely|unpaid|no_data (+unknown_account на будущее),
bank_txn_id, bank_registry_ref, bank_match_type, bank_confidence, bank_amount, bank_date,
bank_amount_src ('report' — сумма за заказ из отчёта МП; 'pack' — зарезервировано
под сумму пачки 1:1; иначе NULL). `actual_profit` не трогаем.

Семантика bank_amount — сумма ЗА ЗАКАЗ из отчёта маркетплейса, только если пачка
подтверждена; иначе NULL (сумму пачки по строкам не делим, пропорции не выдумываем):
- YM: confirmed → sell_price − market_services из e_com.ya_order_margin_report.
- MM: confirmed → SUM(company_debt) − SUM(seller_debt) из e_com.mm_financial_report
  за shipment (один SQL с GROUP BY за все N разом).
- SM: likely (linked месяц) → total_to_seller из e_com.sm_price_reports.
- OZ/WB: позаказных данных нет → всегда NULL.
bank_date/bank_registry_ref/confidence — как были (уровень пачки).

Джойны (все чтения с WHERE NOT is_deleted, тем же engine):
- YM: строки ya_payments_reports для выплаты агрегатные (ya_orders_id/order_id NULL),
  прямой джойн payment→order невозможен. Статус paid по версии МП берём из
  payment_status ('Переведён'/'Переведён по графику выплат'); банковское
  подтверждение — уровня ВЫПЛАТЫ: bank.payout_links(marketplace yandex) →
  bank.transactions(op_date). Заказ paid + дата выплаты МП (last_payment_date,
  fallback tr_customer_payment_date/created_at) в окне ±7 дней от банковской
  выплаты → confirmed (match_type window, confidence 0.5; doc_id 1.0 — только
  для пары выплата↔банк). Paid без выплаты в окне → no_data; не paid → unpaid.
- MM: links(ref_type=registry, ref_id=МПБЛ-N)
  → e_com.mm_financial_report(filename ILIKE %N% → shipment_id) → df, conf 0.8.
  Фолбэк при дырках фида (registry-файлы за период не загружены, но проводки
  в выписке есть): MM-заказ без ship-ссылки + банковский провод ММ
  (bank.transactions payer ILIKE '%МАРКЕТПЛЕЙС%') в окне
  [delivered_at/created_at; +45 дней] → likely, window, 0.5; провода нет
  в окне → unpaid. Суммы в фолбэке NULL (нет отчёта за пачку).
- SM: пачка = первая ссылка (bank.payout_links marketplace sportmaster) с op_date
  ∈ [date_realization; +45 дней] → likely 0.5/window; нет — no_data (unpaid не
  ставим). Сумма за заказ — total_to_seller из e_com.sm_price_reports.
- OZ/WB: только month-window (месяц op_date = месяц created_at) → likely 0.5,
  иначе no_data (unpaid не ставим — осторожно); amount всегда NULL.
- YM/MM: нет совпадения + выписка есть = unpaid, выписки нет = no_data.
"""

from __future__ import annotations

import datetime
import logging
import re

import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)

BANK_COLUMNS: list[str] = [
    "bank_status",
    "bank_txn_id",
    "bank_registry_ref",
    "bank_match_type",
    "bank_confidence",
    "bank_amount",
    "bank_amount_src",
    "bank_date",
]

ORDER_KEY_BY_MP: dict[str, str] = {
    "ym": "ya_order_id",
    "mm": "mm_order_id",
    "sm": "sm_order_id",
    "wb": "wb_order_id",
    "oz": "oz_order_id",
}

# Код МП (loader) → название в bank.payout_links.marketplace (живые данные).
BANK_MARKETPLACE_NAMES: dict[str, str] = {
    "ym": "yandex",
    "mm": "megamarket",
    "sm": "sportmaster",
    "wb": "wildberries",
    "oz": "ozon",
}

WINDOW_MPS = frozenset({"sm", "wb", "oz"})

_MP_RE = re.compile(r"(\d+)")


def _blank_overlay(n: int, status: str = "no_data") -> dict[str, list]:
    return {
        "bank_status": [status] * n,
        "bank_txn_id": [None] * n,
        "bank_registry_ref": [None] * n,
        "bank_match_type": [None] * n,
        "bank_confidence": [None] * n,
        "bank_amount": [None] * n,
        "bank_amount_src": [None] * n,
        "bank_date": [None] * n,
    }


def _ensure_columns(df: pd.DataFrame, status: str = "no_data") -> pd.DataFrame:
    for col, vals in _blank_overlay(len(df), status).items():
        if col not in df.columns:
            df[col] = vals
    return df


def _numeric_amounts(df: pd.DataFrame) -> pd.DataFrame:
    """Streamlit NumberColumn калечит Decimal в object-колонке → приводим к float.

    NaN после coerce возвращаем в None поэлементно: контракт пустого
    bank_amount — NULL, не float("nan") (ломает `is None`-проверки).
    """
    import pandas as _pd
    for col in ("bank_amount", "bank_confidence"):
        if col in df.columns:
            s = _pd.to_numeric(df[col], errors="coerce")
            # dtype=object обязателен: pandas 3.0 перетранслирует список(None) в float64/NaN.
            df[col] = _pd.Series(
                [None if _pd.isna(v) else v for v in s], index=df.index, dtype=object
            )
    return df


def _tail(account: str | None) -> str | None:
    if not account:
        return None
    digits = re.sub(r"\D", "", str(account))
    return digits[-4:] if digits else None


def _fetch_scalar(conn, sql: str, params: dict | None = None):
    try:
        return conn.execute(text(sql), params or {}).scalar()
    except Exception:
        return None


def _has_any_statements(conn) -> bool:
    n = _fetch_scalar(
        conn, "SELECT COUNT(*) FROM bank.statement_files WHERE NOT is_deleted"
    )
    return bool(n)


# YM: paid по версии МП (payment_status из ya_order_margin_report).
# 'Удержан из платежей покупателей' = расчёт состоялся (delivered_unpaid
# в agentAnalytic исключает оба статуса из неоплаченных).
YM_PAID_STATUSES = frozenset(
    {"Переведён", "Переведён по графику выплат", "Удержан из платежей покупателей"}
)

# Окно подтверждения выплаты YM: |дата МП − дата банка| ≤ N дней.
YM_PAYOUT_WINDOW_DAYS = 7


def _fetch_ym_payouts(conn) -> list[dict]:
    """Выплаты YM уровня пачки: [{txn_id, registry_ref, amount, op_date}]."""
    for sql, params in (
        (
            "SELECT l.tx_id, l.ref_id, l.amount, t.op_date FROM bank.payout_links l"
            " JOIN bank.transactions t ON t.id = l.tx_id"
            " WHERE NOT l.is_deleted AND NOT t.is_deleted"
            " AND l.marketplace IN ('yandex', 'ym')"
        ),
        {},
    ), (
        (
            "SELECT l.tx_id, l.ref_id, l.amount, t.op_date FROM bank.payout_links l"
            " JOIN bank.transactions t ON t.id = l.tx_id"
            " WHERE NOT l.is_deleted AND NOT t.is_deleted"
            " AND l.ref_type = 'doc_id'"
        ),
        {},
    ):
        try:
            rows = conn.execute(text(sql), params).mappings().all()
            return [
                {"txn_id": r["tx_id"], "registry_ref": str(r["ref_id"]),
                 "amount": r["amount"], "op_date": r["op_date"]}
                for r in rows
            ]
        except Exception:
            continue
    logger.warning("bank schema недоступна (YM overlay → no_data/unpaid)", exc_info=True)
    return []


def _fetch_ym_nets(conn, order_ids: list[int]) -> dict[str, object]:
    """Per-order net YM: sell_price − market_services по ya_orders_id (один SQL)."""
    if not order_ids:
        return {}
    try:
        rows = conn.execute(
            text(
                "SELECT ya_orders_id,"
                " COALESCE(sell_price, 0) - COALESCE(market_services, 0) AS net"
                " FROM e_com.ya_order_margin_report"
                " WHERE ya_orders_id = ANY(:ids)"
            ),
            {"ids": order_ids},
        ).mappings().all()
    except Exception:
        logger.warning("ya_order_margin_report недоступен (YM amount → NULL)", exc_info=True)
        return {}
    return {str(r["ya_orders_id"]): r["net"] for r in rows}


def _as_date(value) -> object:
    try:
        d = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(d):
        return None
    return d.date()


def _apply_ym_payout_window(
    df: pd.DataFrame,
    payouts: list[dict],
    report_amounts: dict[str, object] | None = None,
) -> pd.DataFrame:
    """Чистая функция YM: paid + дата в ±7 днях от выплаты банка → confirmed/0.5.

    payouts — список {txn_id, registry_ref, amount, op_date} (уровень пачки).
    bank_amount — только per-order net из отчёта МП (report_amounts keyed by
    str(ya_order_id), src 'report'); иначе NULL. paid без выплаты в окне → no_data;
    не paid → unpaid.
    """
    df = df.copy()
    _ensure_columns(df, "no_data")
    report_amounts = report_amounts or {}
    order_ids = (
        df["ya_order_id"].astype(str) if "ya_order_id" in df.columns
        else pd.Series("", index=df.index)
    )
    paid = (
        df["payment_status"].isin(YM_PAID_STATUSES)
        if "payment_status" in df.columns
        else pd.Series(False, index=df.index)
    )
    df.loc[~paid.fillna(False).astype(bool).values, "bank_status"] = "unpaid"
    if not payouts:
        return df
    pay_dates: list[tuple] = []
    for p in payouts:
        d = _as_date(p.get("op_date"))
        if d is not None:
            pay_dates.append((d, p))
    if not pay_dates:
        return df
    date_cols = [c for c in ("last_payment_date", "tr_customer_payment_date", "created_at")
                 if c in df.columns]
    for idx in df.index[paid.fillna(False).astype(bool).values]:
        order_date = None
        for c in date_cols:
            order_date = _as_date(df.at[idx, c])
            if order_date is not None:
                break
        if order_date is None:
            continue  # paid, но даты нет → no_data
        best: tuple | None = None
        for d, p in pay_dates:
            delta = abs((order_date - d).days)
            if delta <= YM_PAYOUT_WINDOW_DAYS and (best is None or delta < best[0]):
                best = (delta, p, d)
        if best is None:
            continue  # paid без выплаты в окне → no_data
        _, p, _ = best
        df.at[idx, "bank_status"] = "confirmed"
        df.at[idx, "bank_txn_id"] = p.get("txn_id")
        df.at[idx, "bank_registry_ref"] = p.get("registry_ref")
        df.at[idx, "bank_match_type"] = "window"
        df.at[idx, "bank_confidence"] = 0.5
        net = report_amounts.get(str(order_ids.at[idx]).strip())
        df.at[idx, "bank_amount"] = net
        df.at[idx, "bank_amount_src"] = "report" if net is not None else None
        df.at[idx, "bank_date"] = p.get("op_date")
    return _numeric_amounts(df)


def _mm_token(ref_id: str) -> str | None:
    """Токен пачки MM для поиска в filename (без голых подстрок-чисел).

    МПБЛ-ссылки матчатся полным токеном 'МПБЛ-N' (регистронезависимо);
    иначе — trailing-номер с границами. Возвращает None, если номера нет.
    """
    s = str(ref_id or "").strip()
    m = re.search(r"МПБЛ-(\d+)\s*$", s, re.IGNORECASE)
    if m:
        return f"МПБЛ-{m.group(1)}"
    runs = re.findall(r"\d+", s)
    return runs[-1] if runs else None


def _token_in(text_: str, token: str) -> bool:
    prefix = "" if token.upper().startswith("МПБЛ-") else r"(?<!\d)"
    return re.search(prefix + re.escape(token) + r"(?!\d)", text_, re.IGNORECASE) is not None


def _fetch_mm_data(
    conn, ships: list[str] | None = None
) -> tuple[dict[str, dict], dict[str, object], bool]:
    """MM: (ship → link пачки, ship → per-shipment net, covered).

    Per-shipment net = SUM(company_debt) − SUM(seller_debt) из mm_financial_report
    (WHERE filename ILIKE %токен% AND shipment_id=<ship>) — один SQL с GROUP BY
    за все токены разом (сужаем до ships из df, если переданы).
    Токен — полный 'МПБЛ-N', не голое число (иначе '00' из 00ЦО-ссылок матчит всё).
    """
    try:
        rows = conn.execute(
            text(
                "SELECT l.ref_id, l.tx_id, l.amount, t.op_date, t.account"
                " FROM bank.payout_links l JOIN bank.transactions t ON t.id = l.tx_id"
                " WHERE NOT l.is_deleted AND NOT t.is_deleted"
                " AND l.ref_type = 'registry'"
                " AND (l.marketplace IN ('megamarket', 'mm') OR l.marketplace IS NULL)"
            )
        ).mappings().all()
    except Exception:
        logger.warning("bank schema недоступна (MM overlay → no_data)", exc_info=True)
        return {}, {}, False
    if not rows:
        return {}, {}, _has_any_statements(conn)
    links: dict[str, dict] = {}  # token -> link
    for r in rows:
        token = _mm_token(str(r["ref_id"]))
        if token:
            links.setdefault(
                token,
                {
                    "txn_id": r["tx_id"],
                    "registry_ref": str(r["ref_id"]),
                    "match_type": "registry",
                    "confidence": 0.8,
                    "amount": r["amount"],
                    "op_date": r["op_date"],
                    "account_tail": _tail(r.get("account")),
                },
            )
    if not links:
        return {}, {}, True
    pats = sorted(links)
    like = " OR ".join(f"filename ILIKE :p{i}" for i in range(len(pats)))
    params: dict[str, object] = {f"p{i}": f"%{p}%" for i, p in enumerate(pats)}
    if ships:
        params["ships"] = ships
        ship_filter = " AND shipment_id = ANY(:ships)"
    else:
        ship_filter = ""
    try:
        fr = conn.execute(
            text(
                "SELECT shipment_id, filename,"
                " SUM(COALESCE(company_debt, 0)) - SUM(COALESCE(seller_debt, 0)) AS net"
                " FROM e_com.mm_financial_report"
                f" WHERE shipment_id IS NOT NULL AND ({like}){ship_filter}"
                " GROUP BY shipment_id, filename"
            ),
            params,
        ).mappings().all()
    except Exception:
        logger.warning("mm_financial_report недоступен", exc_info=True)
        return {}, {}, True
    ship_to_link: dict[str, dict] = {}
    ship_to_net: dict[str, object] = {}
    for f in fr:
        if not f["shipment_id"]:
            continue
        ship = str(f["shipment_id"])
        for token, link in links.items():
            if _token_in(str(f["filename"] or ""), token):
                ship_to_link.setdefault(ship, link)
                ship_to_net[ship] = ship_to_net.get(ship, 0) + (f["net"] or 0)
    return ship_to_link, ship_to_net, True


# MM фолбэк при дырках фида: провод ММ в окне [дата заказа; +N дней] → likely.
MM_WIRE_WINDOW_DAYS = 45


def _fetch_mm_wire_dates(conn) -> list:
    """Даты банковских проводок ММ (связанных и несвязанных): payer ILIKE МАРКЕТПЛЕЙС."""
    try:
        rows = conn.execute(
            text(
                "SELECT op_date FROM bank.transactions"
                " WHERE NOT is_deleted AND payer ILIKE '%МАРКЕТПЛЕЙС%'"
            )
        ).all()
        return [r[0] for r in rows]
    except Exception:
        logger.warning("bank.transactions недоступен (MM fallback-окно выключен)", exc_info=True)
        return []


def _apply_mm(
    df: pd.DataFrame,
    ship_to_link: dict[str, dict],
    ship_to_net: dict[str, object] | None = None,
    *,
    covered: bool = False,
    mm_wire_dates: list | None = None,
) -> pd.DataFrame:
    """Чистая функция MM: shipment из пачки → confirmed/0.8 + per-shipment net.

    Порядок потоков: сперва registry-ссылки (0.8), затем фолбэк-окно по
    деревянным датам MM-выплат (likely/0.5, bank_amount NULL) — у заказов
    без ship-ссылки при covered (дуры фида, пачки есть в выписке). Окно пусто
    → остаётся unpaid. bank_amount — только net из отчёта (src 'report').
    """
    df = df.copy()
    _ensure_columns(df, "no_data")
    ship_to_net = ship_to_net or {}
    if "order_id" in df.columns and ship_to_link:
        for idx, ship in df["order_id"].astype(str).items():
            link = ship_to_link.get(str(ship).strip())
            if not link:
                continue
            df.at[idx, "bank_status"] = "confirmed"
            df.at[idx, "bank_txn_id"] = link["txn_id"]
            df.at[idx, "bank_registry_ref"] = link["registry_ref"]
            df.at[idx, "bank_match_type"] = "registry"
            df.at[idx, "bank_confidence"] = 0.8
            net = ship_to_net.get(str(ship).strip())
            df.at[idx, "bank_amount"] = net
            df.at[idx, "bank_amount_src"] = "report" if net is not None else None
            df.at[idx, "bank_date"] = link["op_date"]
            if "bank_account_tail" in df.columns:
                df.at[idx, "bank_account_tail"] = link.get("account_tail")
    if covered:
        no_link = (df["bank_status"] == "no_data").values
        # Даты проводов парсим один раз: в цикле по 20k строк _as_date per-date стоил ~90s.
        wire_dates = [d for d in (_as_date(w) for w in (mm_wire_dates or [])) if d is not None]
        if no_link.any() and wire_dates:
            horizon = datetime.timedelta(days=MM_WIRE_WINDOW_DAYS)
            for idx in df.index[no_link]:
                order_date = None
                for c in ("delivered_at", "created_at"):
                    if c in df.columns:
                        order_date = _as_date(df.at[idx, c])
                        if order_date is not None:
                            break
                if order_date is None:
                    continue
                wire = min(
                    (d for d in wire_dates if order_date <= d <= order_date + horizon),
                    default=None,
                )
                if wire is not None:
                    df.at[idx, "bank_status"] = "likely"
                    df.at[idx, "bank_match_type"] = "window"
                    df.at[idx, "bank_confidence"] = 0.5
                    df.at[idx, "bank_date"] = wire
        mask = df["bank_status"] == "no_data"
        df.loc[mask, "bank_status"] = "unpaid"
    return _numeric_amounts(df)


# Окно поиска пачки SM: первая ссылка с op_date ∈ [anchor; anchor+N дней].
# Спортмастер платит пачкой за отчётный период ПОСЛЕ date_realization,
# поэтому anchor — реализация, поиск только вперёд (месяц created_at — не якорь).
SM_WINDOW_DAYS = 45


def _fetch_sm_links(conn) -> list[dict]:
    """Ссылки SM уровня пачки: [{txn_id, registry_ref, amount, op_date}] по op_date ↑."""
    try:
        rows = conn.execute(
            text(
                "SELECT l.ref_id, l.tx_id, l.amount, t.op_date"
                " FROM bank.payout_links l JOIN bank.transactions t ON t.id = l.tx_id"
                " WHERE NOT l.is_deleted AND NOT t.is_deleted"
                " AND l.marketplace = ANY(:mps)"
                " ORDER BY t.op_date"
            ),
            {"mps": ["sm", BANK_MARKETPLACE_NAMES["sm"]]},
        ).mappings().all()
    except Exception:
        logger.warning("bank schema недоступна (SM overlay → no_data)", exc_info=True)
        return []
    return [
        {"txn_id": r["tx_id"], "registry_ref": str(r["ref_id"]),
         "amount": r["amount"], "op_date": r["op_date"]}
        for r in rows
    ]


def _apply_sm_window(
    df: pd.DataFrame,
    links: list[dict],
    *,
    report_amounts: dict[str, object] | None = None,
) -> pd.DataFrame:
    """SM: пачка = первая ссылка с op_date ∈ [anchor; anchor+SM_WINDOW_DAYS].

    anchor — date_realization (fallback created_at). Нашлась → likely/0.5/window,
    bank_amount из report_amounts (src 'report'). Не нашлась → no_data
    (unpaid не ставим — признака covered у SM в этом пути нет).
    """
    df = df.copy()
    _ensure_columns(df, "no_data")
    if not links:
        return df
    wire_dates: list[tuple] = []
    for p in links:
        d = _as_date(p.get("op_date"))
        if d is not None:
            wire_dates.append((d, p))
    if not wire_dates:
        return df
    report_amounts = report_amounts or {}
    order_ids = (
        df["sm_order_id"].astype(str) if "sm_order_id" in df.columns
        else pd.Series("", index=df.index)
    )
    anchor_col = next(
        (c for c in ("date_realization", "created_at") if c in df.columns), None
    )
    if anchor_col is None:
        return df
    for idx, value in df[anchor_col].items():
        anchor = _as_date(value)
        if anchor is None:
            continue
        best: tuple | None = None  # (op_date, link) — минимум op_date ≥ anchor
        for d, p in wire_dates:
            if anchor <= d <= anchor + datetime.timedelta(days=SM_WINDOW_DAYS):
                if best is None or d < best[0]:
                    best = (d, p)
        if best is None:
            continue  # no_data: пачки после реализации в окне нет
        d, p = best
        df.at[idx, "bank_status"] = "likely"
        df.at[idx, "bank_txn_id"] = p.get("txn_id")
        df.at[idx, "bank_registry_ref"] = p.get("registry_ref")
        df.at[idx, "bank_match_type"] = "window"
        df.at[idx, "bank_confidence"] = 0.5
        net = report_amounts.get(str(order_ids.at[idx]).strip())
        df.at[idx, "bank_amount"] = net
        df.at[idx, "bank_amount_src"] = "report" if net is not None else None
        df.at[idx, "bank_date"] = p.get("op_date")
    return _numeric_amounts(df)


def _fetch_sm_nets(conn, order_ids: list[int]) -> dict[str, object]:
    """Per-order SM: total_to_seller из sm_price_reports (один SQL)."""
    if not order_ids:
        return {}
    try:
        rows = conn.execute(
            text(
                "SELECT sm_orders_id, total_to_seller FROM e_com.sm_price_reports"
                " WHERE sm_orders_id = ANY(:ids)"
            ),
            {"ids": order_ids},
        ).mappings().all()
    except Exception:
        logger.warning("sm_price_reports недоступен (SM amount → NULL)", exc_info=True)
        return {}
    return {str(r["sm_orders_id"]): r["total_to_seller"] for r in rows}


def _fetch_window_map(conn, mp: str, months: set[str]) -> dict[str, dict]:
    """Month-window для SM/WB/OZ: {yyyy-mm: link} по последней транзакции месяца."""
    names = sorted({mp, BANK_MARKETPLACE_NAMES.get(mp, mp)})
    try:
        rows = conn.execute(
            text(
                "SELECT l.ref_id, l.tx_id, l.amount, t.op_date"
                " FROM bank.payout_links l JOIN bank.transactions t ON t.id = l.tx_id"
                " WHERE NOT l.is_deleted AND NOT t.is_deleted"
                " AND l.marketplace = ANY(:mps)"
            ),
            {"mps": names},
        ).mappings().all()
    except Exception:
        logger.warning("bank schema недоступна (%s overlay → no_data)", mp, exc_info=True)
        return {}
    out: dict[str, dict] = {}
    for r in rows:
        d = r["op_date"]
        try:
            key = d.strftime("%Y-%m") if hasattr(d, "strftime") else str(d)[:7]
        except Exception:
            continue
        if key in months and key not in out:
            out[key] = {
                "txn_id": r["tx_id"],
                "registry_ref": str(r.get("ref_id") or ""),
                "match_type": "window",
                "confidence": 0.5,
                "amount": r["amount"],
                "op_date": r["op_date"],
            }
    return out


def attach_bank_status(
    df: pd.DataFrame,
    mp: str,
    *,
    _link_map: dict | list | None = None,
    _has_coverage: bool | None = None,
    _report_amounts: dict[str, object] | None = None,
    _wire_dates: list | None = None,
) -> pd.DataFrame:
    """Оверлей банковских статусов. Без БД (или при ошибке) — все no_data."""
    mp = str(mp or "").strip().lower()
    if df is None or len(df) == 0:
        out = df.copy() if df is not None else pd.DataFrame()
        return _ensure_columns(out)
    if _link_map is not None:
        if mp == "ym":
            # Тестовый хук YM: список выплат пачки (dict значений — обратно
            # совместимо со старым форматом order_key → link).
            payouts = (
                list(_link_map)
                if isinstance(_link_map, (list, tuple))
                else list(_link_map.values())
            )
            return _apply_ym_payout_window(df, payouts, _report_amounts)
        if mp == "mm":
            # Тестовый хук MM: ship → link (+ ship → per-shipment net, + окно проводов).
            return _apply_mm(
                df, dict(_link_map), _report_amounts,
                covered=bool(_has_coverage),
                mm_wire_dates=_wire_dates,
            )
        if mp in WINDOW_MPS:
            if mp == "sm" and isinstance(_link_map, (list, tuple)):
                # Тестовый хук SM: список ссылок пачки → forward-window от реализации.
                return _apply_sm_window(df, list(_link_map), report_amounts=_report_amounts)
            return _apply_window(
                df, dict(_link_map),
                order_key=ORDER_KEY_BY_MP.get(mp),
                report_amounts=_report_amounts,
            )
        return _ensure_columns(df.copy())
    try:
        from wolle_economy.db.engine import get_engine

        engine = get_engine()
        with engine.connect() as conn:
            if mp == "ym":
                payouts = _fetch_ym_payouts(conn)
                paid_ids = _int_ids(df, "ya_order_id", "payment_status", YM_PAID_STATUSES)
                return _apply_ym_payout_window(
                    df, payouts, _fetch_ym_nets(conn, paid_ids)
                )
            if mp == "mm":
                ships = (
                    df["order_id"].astype(str).str.strip().unique().tolist()
                    if "order_id" in df.columns else None
                )
                ship_to_link, ship_to_net, covered = _fetch_mm_data(conn, ships)
                return _apply_mm(
                    df, ship_to_link, ship_to_net, covered=covered,
                    mm_wire_dates=_fetch_mm_wire_dates(conn),
                )
            if mp == "sm":
                # SM платит пачкой за отчётный период ПОСЛЕ date_realization,
                # поэтому matching по датам от реализации, не по месяцу created_at.
                nets = _fetch_sm_nets(conn, _int_ids(df, "sm_order_id"))
                return _apply_sm_window(df, _fetch_sm_links(conn), report_amounts=nets)
            if mp in WINDOW_MPS:
                months: set[str] = set()
                if "created_at" in df.columns:
                    try:
                        months = {
                            pd.to_datetime(v).strftime("%Y-%m")
                            for v in df["created_at"].dropna().unique()
                        }
                    except Exception:
                        months = set()
                link_map = _fetch_window_map(conn, mp, months)
                return _apply_window(
                    df, link_map,
                    order_key=ORDER_KEY_BY_MP.get(mp),
                )
            return _ensure_columns(df.copy())
    except Exception:
        logger.warning("bank overlay пропущен (%s) → no_data", mp, exc_info=True)
        return _ensure_columns(df.copy())


def _int_ids(
    df: pd.DataFrame,
    id_col: str,
    status_col: str | None = None,
    paid: frozenset | None = None,
) -> list[int]:
    """Целочисленные id строк (опционально только paid) для ANY(:ids)."""
    if id_col not in df.columns or len(df) == 0:
        return []
    frame = df
    if status_col and paid is not None and status_col in df.columns:
        frame = df[df[status_col].isin(paid)]
    ids: list[int] = []
    for v in frame[id_col].tolist():
        try:
            ids.append(int(v))
        except (TypeError, ValueError):
            continue
    return ids


def _apply_window(
    df: pd.DataFrame,
    month_map: dict[str, dict],
    order_key: str | None = None,
    report_amounts: dict[str, object] | None = None,
) -> pd.DataFrame:
    """Month-window: месяц op_date = месяц created_at → likely/0.5, иначе no_data.

    bank_amount — только per-order net из отчёта (src 'report'), иначе NULL:
    OZ/WB позаказных данных нет → всегда NULL.
    """
    df = df.copy()
    _ensure_columns(df, "no_data")
    if not month_map or "created_at" not in df.columns:
        return df
    try:
        keys = pd.to_datetime(df["created_at"]).dt.strftime("%Y-%m")
    except Exception:
        return df
    report_amounts = report_amounts or {}
    order_ids = (
        df[order_key].astype(str) if order_key and order_key in df.columns
        else pd.Series("", index=df.index)
    )
    for idx, key in keys.items():
        link = month_map.get(str(key))
        if link:
            df.at[idx, "bank_status"] = "likely"
            df.at[idx, "bank_txn_id"] = link.get("txn_id")
            df.at[idx, "bank_registry_ref"] = link.get("registry_ref")
            df.at[idx, "bank_match_type"] = "window"
            df.at[idx, "bank_confidence"] = 0.5
            net = report_amounts.get(str(order_ids.at[idx]).strip())
            df.at[idx, "bank_amount"] = net
            df.at[idx, "bank_amount_src"] = "report" if net is not None else None
            df.at[idx, "bank_date"] = link.get("op_date")
    return _numeric_amounts(df)


if __name__ == "__main__":  # мини self-check без БД
    import datetime

    ym = pd.DataFrame({
        "ya_order_id": [1, 2, 3, 4],
        "payment_status": ["Переведён", "Переведён", "Списание", "Переведён"],
        "last_payment_date": ["2024-01-15", "2024-01-15", "2024-01-15", None],
    })
    ym_payouts = [
        {"txn_id": 11, "registry_ref": "841445", "amount": 50000,
         "op_date": datetime.date(2024, 1, 18)},  # +3 дня от даты МП
        {"txn_id": 12, "registry_ref": "841400", "amount": 10000,
         "op_date": datetime.date(2023, 11, 1)},  # вне окна
    ]
    r = attach_bank_status(ym, "ym", _link_map=ym_payouts,
                           _report_amounts={"1": 1200.0, "2": 800.0})
    assert r.loc[0, "bank_status"] == "confirmed", r  # paid + выплата в окне
    assert r.loc[0, "bank_match_type"] == "window"
    assert r.loc[0, "bank_confidence"] == 0.5
    assert r.loc[0, "bank_amount"] == 1200.0  # per-order net, не пачка 50000
    assert r.loc[0, "bank_amount_src"] == "report", r
    assert r.loc[1, "bank_status"] == "confirmed", r  # та же пачка на все строки
    assert r.loc[1, "bank_amount"] == 800.0
    assert r.loc[2, "bank_status"] == "unpaid", r  # не paid по версии МП
    assert r.loc[3, "bank_status"] == "no_data", r  # paid, но даты выплаты МП нет
    assert r.loc[3, "bank_amount"] is None
    assert r.loc[3, "bank_amount_src"] is None

    mm = pd.DataFrame({"mm_order_id": [7, 8, 9],
                       "order_id": ["SHIP-1", "SHIP-2", "SHIP-1"]})
    mm_links = {"SHIP-1": {"txn_id": 21, "registry_ref": "МПБЛ-5",
                           "match_type": "registry", "confidence": 0.8,
                           "amount": 5000, "op_date": datetime.date(2024, 2, 1)}}
    r2 = attach_bank_status(mm, "mm", _link_map=mm_links,
                            _report_amounts={"SHIP-1": 73454.40}, _has_coverage=True)
    assert r2.loc[0, "bank_status"] == "confirmed", r2
    assert r2.loc[0, "bank_amount"] == 73454.40, r2  # per-shipment, не пачка 5000
    assert r2.loc[0, "bank_amount_src"] == "report", r2
    assert r2.loc[2, "bank_amount"] == 73454.40, r2  # та же пачка на все строки
    assert r2.loc[1, "bank_status"] == "unpaid", r2
    assert r2.loc[1, "bank_amount"] is None and r2.loc[1, "bank_amount_src"] is None

    # MM фолбэк: дырка фида, но провод ММ в окне [created_at; +45] → likely.
    mm2 = pd.DataFrame({
        "mm_order_id": [10, 11, 12],
        "order_id": ["SHIP-X", "SHIP-Y", "SHIP-X"],
        "created_at": [datetime.datetime(2026, 6, 10), datetime.datetime(2026, 1, 5),
                       datetime.datetime(2026, 6, 10)],
    })
    r2b = attach_bank_status(mm2, "mm", _link_map={}, _has_coverage=True,
                             _wire_dates=[datetime.date(2026, 6, 28),
                                          datetime.date(2026, 2, 20)])
    assert r2b.loc[0, "bank_status"] == "likely", r2b  # 28.06 в [10.06; +45]
    assert r2b.loc[0, "bank_match_type"] == "window" and r2b.loc[0, "bank_confidence"] == 0.5
    assert r2b.loc[0, "bank_amount"] is None and r2b.loc[0, "bank_amount_src"] is None
    assert r2b.loc[0, "bank_date"] == datetime.date(2026, 6, 28)
    assert r2b.loc[1, "bank_status"] == "unpaid", r2b  # провод 20.02 > 05.01+45
    assert r2b.loc[2, "bank_status"] == "likely", r2b  # fallback не сломал registry

    oz = pd.DataFrame({"oz_order_id": ["a", "b"],
                       "created_at": [datetime.datetime(2024, 3, 5), datetime.datetime(2024, 4, 5)]})
    r3 = attach_bank_status(oz, "oz", _link_map={
        "2024-03": {"txn_id": 31, "registry_ref": "pack", "match_type": "window",
                    "confidence": 0.5, "amount": 9000,
                    "op_date": datetime.date(2024, 3, 28)}})
    assert r3.loc[0, "bank_status"] == "likely" and r3.loc[1, "bank_status"] == "no_data", r3
    assert r3.loc[0, "bank_confidence"] == 0.5
    assert r3.loc[0, "bank_amount"] is None  # позаказных данных нет — не выдумываем
    assert r3.loc[0, "bank_amount_src"] is None
    print("bank_overlay self-check OK: per-order/report amounts, MM fallback, OZ NULL")
