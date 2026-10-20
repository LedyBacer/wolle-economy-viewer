"""Self-check оверлея банковских оплат (без БД, чистые функции)."""

import datetime

import pandas as pd

from wolle_economy.domain.bank_overlay import BANK_COLUMNS, attach_bank_status


def test_ym_paid_in_window_confirmed():
    """Paid + выплата банка в ±7 днях → confirmed/window/0.5 + per-order net."""
    df = pd.DataFrame({
        "ya_order_id": [1, 2],
        "payment_status": ["Переведён", "Переведён по графику выплат"],
        "last_payment_date": ["2024-01-15", "2024-01-15"],
    })
    payouts = [{"txn_id": 11, "registry_ref": "841445", "amount": 50000,
                "op_date": datetime.date(2024, 1, 18)}]
    out = attach_bank_status(df, "ym", _link_map=payouts,
                             _report_amounts={"1": 1200.0, "2": 800.0})
    for c in BANK_COLUMNS:
        assert c in out.columns
    assert set(out["bank_status"]) == {"confirmed"}
    assert set(out["bank_match_type"]) == {"window"}
    assert set(out["bank_confidence"]) == {0.5}
    # Per-order net из отчёта, а не сумма пачки 50000.
    assert set(out["bank_amount"]) == {1200.0, 800.0}
    assert set(out["bank_amount_src"]) == {"report"}


def test_ym_confirmed_without_report_row_amount_null():
    """Confirmed, но строки в margin_report нет → amount NULL, src NULL."""
    df = pd.DataFrame({
        "ya_order_id": [1],
        "payment_status": ["Переведён"],
        "last_payment_date": ["2024-01-15"],
    })
    payouts = [{"txn_id": 11, "registry_ref": "841445", "amount": 50000,
                "op_date": datetime.date(2024, 1, 18)}]
    out = attach_bank_status(df, "ym", _link_map=payouts, _report_amounts={})
    assert out.loc[0, "bank_status"] == "confirmed"
    assert out.loc[0, "bank_amount"] is None
    assert out.loc[0, "bank_amount_src"] is None


def test_ym_paid_outside_window_no_data_and_not_paid_unpaid():
    """Paid без выплаты в окне → no_data; не paid → unpaid."""
    df = pd.DataFrame({
        "ya_order_id": [1, 2, 3],
        "payment_status": ["Переведён", "Начисление", "Переведён"],
        "last_payment_date": ["2024-01-15", "2024-01-15", None],
    })
    payouts = [{"txn_id": 11, "registry_ref": "841400", "amount": 10000,
                "op_date": datetime.date(2023, 11, 1)}]
    out = attach_bank_status(df, "ym", _link_map=payouts)
    assert out.loc[0, "bank_status"] == "no_data"  # paid, но выплаты в окне нет
    assert out.loc[1, "bank_status"] == "unpaid"  # не paid по версии МП
    assert out.loc[2, "bank_status"] == "no_data"  # paid, но даты выплаты МП нет


def test_mm_fallback_window_likely():
    """Нет ship-ссылки, covered + провод ММ в окне [.order; +45] → likely/0.5/window."""
    df = pd.DataFrame({
        "mm_order_id": [10, 11],
        "order_id": ["SHIP-X", "SHIP-X"],
        "created_at": [datetime.datetime(2026, 6, 10), datetime.datetime(2026, 1, 5)],
    })
    out = attach_bank_status(
        df, "mm", _link_map={}, _has_coverage=True,
        _wire_dates=[datetime.date(2026, 6, 28), datetime.date(2026, 2, 20)],
    )
    assert out.loc[0, "bank_status"] == "likely"  # 28.06 в окне от 10.06
    assert out.loc[0, "bank_match_type"] == "window"
    assert out.loc[0, "bank_confidence"] == 0.5
    assert out.loc[0, "bank_date"] == datetime.date(2026, 6, 28)
    assert out.loc[0, "bank_amount"] is None  # суммы отчёта нет — не выдумываем
    assert out.loc[1, "bank_status"] == "unpaid"  # провод 20.02 вне окна от 05.01


def test_mm_fallback_no_wire_stays_unpaid():
    """Окно пусто (проводов нет вообще) → unpaid, как раньше."""
    df = pd.DataFrame({
        "mm_order_id": [10],
        "order_id": ["SHIP-X"],
        "created_at": [datetime.datetime(2026, 6, 10)],
    })
    out = attach_bank_status(df, "mm", _link_map={}, _has_coverage=True, _wire_dates=[])
    assert out.loc[0, "bank_status"] == "unpaid"
    assert out.loc[0, "bank_date"] is None


def test_mm_registry_confirmed():
    """Shipment из пачки → confirmed/registry/0.8 + per-shipment net (не пачка)."""
    df = pd.DataFrame({"mm_order_id": [7, 8, 9],
                       "order_id": ["SHIP-1", "SHIP-2", "SHIP-1"]})
    links = {"SHIP-1": {"txn_id": 21, "registry_ref": "МПБЛ-5",
                        "match_type": "registry", "confidence": 0.8,
                        "amount": 5000, "op_date": datetime.date(2024, 2, 1)}}
    out = attach_bank_status(df, "mm", _link_map=links,
                             _report_amounts={"SHIP-1": 73454.40},
                             _has_coverage=True)
    assert out.loc[0, "bank_status"] == "confirmed"
    assert out.loc[0, "bank_match_type"] == "registry"
    assert out.loc[0, "bank_amount"] == 73454.40
    assert out.loc[0, "bank_amount_src"] == "report"
    assert out.loc[2, "bank_amount"] == 73454.40  # та же пачка на все строки
    assert out.loc[1, "bank_status"] == "unpaid"
    assert out.loc[1, "bank_amount"] is None
    assert out.loc[1, "bank_amount_src"] is None


def test_sm_forward_window_from_realization():
    """Пачка = первая op_date ≥ date_realization в окне 45д; прошлое не матчим."""
    df = pd.DataFrame({
        "sm_order_id": [1, 2],
        "date_realization": [datetime.date(2026, 7, 5), datetime.date(2026, 7, 2)],
    })
    links = [
        {"txn_id": 71, "registry_ref": "00ЦО-005400", "amount": 245047.79,
         "op_date": datetime.date(2026, 6, 2)},   # до anchor — быть не может
        {"txn_id": 72, "registry_ref": "00ЦО-005674", "amount": 3111.11,
         "op_date": datetime.date(2026, 7, 21)},  # +16д от 05.07
    ]
    out = attach_bank_status(df, "sm", _link_map=links, _report_amounts={"1": 2262.7})
    for c in BANK_COLUMNS:
        assert c in out.columns
    # anchor 05.07: 02.06 в прошлом → матч только 21.07.
    assert out.loc[0, "bank_status"] == "likely"
    assert out.loc[0, "bank_registry_ref"] == "00ЦО-005674"
    assert out.loc[0, "bank_date"] == datetime.date(2026, 7, 21)
    assert out.loc[0, "bank_amount"] == 2262.7
    assert out.loc[0, "bank_amount_src"] == "report"
    # anchor 02.07: 21.07 (+19д) тоже в окне → same pack.
    assert out.loc[1, "bank_status"] == "likely"
    assert out.loc[1, "bank_date"] == datetime.date(2026, 7, 21)
    assert out.loc[1, "bank_amount"] is None  # нет строки в отчёте


def test_sm_no_future_pack_no_data():
    """Есть только пачка ДО anchor →Matchers no_data (не unpaid)."""
    df = pd.DataFrame({
        "sm_order_id": [1],
        "date_realization": [datetime.date(2026, 7, 2)],
    })
    links = [{"txn_id": 71, "registry_ref": "00ЦО-005400", "amount": 245047.79,
              "op_date": datetime.date(2026, 6, 30)}]  # до anchor
    out = attach_bank_status(df, "sm", _link_map=links)
    assert out.loc[0, "bank_status"] == "no_data"
    assert out.loc[0, "bank_amount"] is None


def test_sm_pack_beyond_window_no_data():
    """Пачка на 50 дней позже anchor — за окном → no_data."""
    df = pd.DataFrame({
        "sm_order_id": [1],
        "date_realization": [datetime.date(2026, 7, 5)],
    })
    links = [{"txn_id": 73, "registry_ref": "00ЦО-005999", "amount": 10.0,
              "op_date": datetime.date(2026, 8, 24)}]  # +50д
    out = attach_bank_status(df, "sm", _link_map=links)
    assert out.loc[0, "bank_status"] == "no_data"


def test_window_likely_only_month_match():
    df = pd.DataFrame({
        "oz_order_id": ["a", "b"],
        "created_at": [datetime.datetime(2024, 3, 5), datetime.datetime(2024, 4, 5)],
    })
    out = attach_bank_status(df, "oz", _link_map={
        "2024-03": {"txn_id": 31, "registry_ref": "pack", "match_type": "window",
                    "confidence": 0.5, "amount": 9000,
                    "op_date": datetime.date(2024, 3, 28)}})
    assert out.loc[0, "bank_status"] == "likely"
    assert out.loc[0, "bank_confidence"] == 0.5
    assert out.loc[1, "bank_status"] == "no_data"  # unpaid не ставим для window-МП
    # OZ: позаказных данных нет — amount всегда NULL, не выдумываем пропорции.
    assert out.loc[0, "bank_amount"] is None
    assert out.loc[0, "bank_amount_src"] is None


def test_empty_df_keeps_contract():
    out = attach_bank_status(pd.DataFrame({"ya_order_id": []}), "ym")
    for c in BANK_COLUMNS:
        assert c in out.columns
