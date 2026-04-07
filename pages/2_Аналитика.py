"""
Аналитика юнит-экономики: KPI-дашборд, ABC-анализ, возвраты, поставщики,
ценообразование, денежный поток, операционные метрики и тренды.
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from db.connection import get_engine
from db.queries import ORDER_ITEMS_SQL, PAYMENT_AGGREGATES_SQL
from economics import (
    calc_economics,
    merge_with_payments,
    CANCELLED_BEFORE_SHIP,
    RETURNED_STATUSES,
    CANCELLED_STATUSES,
)

# ---------------------------------------------------------------------------
# Загрузка данных (кэшируется)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner="Загрузка данных...")
def load_data() -> pd.DataFrame:
    engine = get_engine()
    with engine.connect() as conn:
        orders = pd.read_sql(ORDER_ITEMS_SQL, conn)
        payments = pd.read_sql(PAYMENT_AGGREGATES_SQL, conn)
    df = merge_with_payments(orders, payments)
    df = calc_economics(df)
    return df


# ---------------------------------------------------------------------------
# Фильтры
# ---------------------------------------------------------------------------
def sidebar_filters(df: pd.DataFrame) -> pd.DataFrame:
    with st.sidebar:
        st.header("Фильтры")

        sellers = sorted(df["seller_name"].dropna().unique())
        sel_sellers = st.multiselect("Магазин", sellers, default=sellers)

        dates = df["created_at"].dropna()
        if not dates.empty:
            d_min, d_max = dates.min().date(), dates.max().date()
            date_range = st.date_input("Период (дата заказа)", (d_min, d_max), d_min, d_max)
        else:
            date_range = None

        exclude_low_quality = st.checkbox(
            "Исключить магазины без margin_report",
            value=True,
            help="WolleBuy и ТехноПравда Гонконг — для них нет точных данных о выручке/комиссиях",
        )

    mask = df["seller_name"].isin(sel_sellers)
    if date_range and len(date_range) == 2:
        d_from = pd.Timestamp(date_range[0], tz="UTC")
        d_to = pd.Timestamp(date_range[1], tz="UTC") + pd.Timedelta(days=1)
        mask &= df["created_at"].between(d_from, d_to)

    if exclude_low_quality:
        mask &= ~df["seller_name"].isin({"WolleBuy", "ТехноПравда Гонконг"})

    return df[mask].copy()


def orders_dedup(df: pd.DataFrame) -> pd.DataFrame:
    """Дедуп по заказу — для агрегатов по полям уровня заказа."""
    return df.drop_duplicates(subset="ya_order_id")


def fmt_money(x: float) -> str:
    if pd.isna(x):
        return "—"
    return f"{x:,.0f} ₽".replace(",", " ")


def fmt_pct(x: float, digits: int = 1) -> str:
    if pd.isna(x):
        return "—"
    return f"{x:.{digits}f}%"


# ---------------------------------------------------------------------------
# Вкладка 1: KPI-дашборд
# ---------------------------------------------------------------------------
def tab_kpi(df: pd.DataFrame) -> None:
    st.subheader("Ключевые показатели")

    od = orders_dedup(df)
    delivered = od[~od["is_cancelled_any"]]

    # Денежные агрегаты
    revenue       = od["sell_price"].sum()
    payout        = od["expected_payout"].sum()
    commissions   = od["market_services"].sum()
    our_costs     = df["our_costs"].sum()
    profit        = df["profit"].sum()
    profit_no_pr  = df["profit_no_promo"].sum()
    promo         = df["promo_discounts"].sum()
    penalties     = (
        od.get("seller_cancel_penalty", pd.Series(dtype=float)).fillna(0).sum()
        + od.get("late_ship_penalty", pd.Series(dtype=float)).fillna(0).sum()
    )
    compensations = od.get("compensations", pd.Series(dtype=float)).fillna(0).sum()

    n_orders     = od["ya_order_id"].nunique()
    n_items      = df["quantity"].fillna(1).sum()
    n_delivered  = delivered["ya_order_id"].nunique()
    n_returned   = od[od["is_returned"]]["ya_order_id"].nunique()
    n_cancelled  = od[od["is_cancelled_before"]]["ya_order_id"].nunique()
    n_loss       = df.groupby("ya_order_id")["profit"].sum().lt(0).sum()

    aov          = revenue / n_orders if n_orders else np.nan
    aov_net      = payout / n_orders if n_orders else np.nan
    take_rate    = commissions / revenue * 100 if revenue else np.nan
    net_margin   = profit / revenue * 100 if revenue else np.nan
    contrib      = (payout - our_costs) / revenue * 100 if revenue else np.nan
    return_rate  = n_returned / n_orders * 100 if n_orders else np.nan
    cancel_rate  = n_cancelled / n_orders * 100 if n_orders else np.nan
    fulfill_rate = n_delivered / n_orders * 100 if n_orders else np.nan
    loss_share   = n_loss / n_orders * 100 if n_orders else np.nan
    items_per_o  = n_items / n_orders if n_orders else np.nan

    # ---- Деньги ----
    st.markdown("**Деньги**")
    c = st.columns(4)
    c[0].metric("Выручка (GMV)", fmt_money(revenue))
    c[1].metric("Выплата от ЯМ", fmt_money(payout))
    c[2].metric("Прибыль (с промо)", fmt_money(profit))
    c[3].metric("Прибыль без промо", fmt_money(profit_no_pr))

    c = st.columns(4)
    c[0].metric("Комиссии ЯМ", fmt_money(commissions))
    c[1].metric("Наши затраты", fmt_money(our_costs))
    c[2].metric("Промо-расходы", fmt_money(promo))
    c[3].metric("Штрафы / Компенсации", f"{fmt_money(penalties)} / {fmt_money(compensations)}")

    # ---- Маржинальность и тейк ----
    st.markdown("**Маржинальность**")
    c = st.columns(4)
    c[0].metric("Net Margin", fmt_pct(net_margin), help="Прибыль / GMV")
    c[1].metric("Contribution Margin", fmt_pct(contrib), help="(Выплата − затраты) / GMV")
    c[2].metric("Take Rate ЯМ", fmt_pct(take_rate), help="Комиссии ЯМ / GMV")
    c[3].metric("Доля убыточных заказов", fmt_pct(loss_share))

    # ---- Объёмы ----
    st.markdown("**Объёмы и средние чеки**")
    c = st.columns(4)
    c[0].metric("Заказов", f"{n_orders:,}".replace(",", " "))
    c[1].metric("Позиций / шт", f"{int(n_items):,}".replace(",", " "))
    c[2].metric("AOV (брутто)", fmt_money(aov), help="Средний чек по sell_price")
    c[3].metric("AOV (нетто, после комиссий)", fmt_money(aov_net))

    c = st.columns(4)
    c[0].metric("Позиций на заказ", f"{items_per_o:.2f}")
    c[1].metric("Fulfillment Rate", fmt_pct(fulfill_rate), help="Доставлено / всего")
    c[2].metric("Cancel Rate", fmt_pct(cancel_rate), help="Отменено до отгрузки / всего")
    c[3].metric("Return Rate", fmt_pct(return_rate), help="Возвраты+невыкупы / всего")

    st.divider()

    # ---- Водопад: выручка → прибыль ----
    st.markdown("**Декомпозиция прибыли (waterfall)**")
    fig = go.Figure(go.Waterfall(
        orientation="v",
        measure=["absolute", "relative", "relative", "relative", "total"],
        x=["Выручка (GMV)", "− Комиссии ЯМ", "− Наши затраты", "+ Промо (−)", "Прибыль"],
        y=[revenue, -commissions, -our_costs, promo, 0],
        textposition="outside",
        text=[fmt_money(v) for v in [revenue, -commissions, -our_costs, promo, profit]],
        connector={"line": {"color": "rgb(120,120,120)"}},
    ))
    fig.update_layout(height=420, margin=dict(l=20, r=20, t=20, b=20))
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Вкладка 2: ABC-анализ
# ---------------------------------------------------------------------------
def tab_abc(df: pd.DataFrame) -> None:
    st.subheader("ABC-анализ товаров (Парето)")
    st.caption(
        "A — товары, дающие 80% выручки; B — следующие 15%; C — последние 5%. "
        "Класс A — ядро ассортимента, требует контроля наличия и цен."
    )

    agg = df.groupby(["offer_id", "product_name"], observed=True).agg(
        выручка=("sell_price", "sum"),
        прибыль=("profit", "sum"),
        продаж=("quantity", "sum"),
        заказов=("ya_order_id", "nunique"),
    ).reset_index()
    agg = agg[agg["выручка"] > 0].sort_values("выручка", ascending=False)
    if agg.empty:
        st.info("Нет данных.")
        return

    agg["доля_%"]    = agg["выручка"] / agg["выручка"].sum() * 100
    agg["накоп_%"]   = agg["доля_%"].cumsum()
    agg["класс"]     = np.where(agg["накоп_%"] <= 80, "A",
                        np.where(agg["накоп_%"] <= 95, "B", "C"))
    agg["маржа_%"]   = (agg["прибыль"] / agg["выручка"] * 100).round(1)

    # Сводка по классам
    summary = agg.groupby("класс").agg(
        товаров=("offer_id", "count"),
        выручка=("выручка", "sum"),
        прибыль=("прибыль", "sum"),
    ).reset_index()
    summary["доля_выручки_%"] = (summary["выручка"] / summary["выручка"].sum() * 100).round(1)
    summary["маржа_%"] = (summary["прибыль"] / summary["выручка"] * 100).round(1)

    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("**Классы**")
        disp = summary.copy()
        disp["выручка"] = disp["выручка"].map(fmt_money)
        disp["прибыль"] = disp["прибыль"].map(fmt_money)
        disp["доля_выручки_%"] = disp["доля_выручки_%"].map(lambda x: f"{x:.1f}%")
        disp["маржа_%"] = disp["маржа_%"].map(lambda x: f"{x:.1f}%")
        st.dataframe(disp, hide_index=True, width="stretch")
    with c2:
        # Кривая Парето
        fig = px.line(
            agg.reset_index(drop=True).reset_index(),
            x="index", y="накоп_%",
            title="Кривая Парето",
            labels={"index": "Товары (отсортированы)", "накоп_%": "Накопленная доля выручки, %"},
        )
        fig.add_hline(y=80, line_dash="dot", line_color="green", annotation_text="A=80%")
        fig.add_hline(y=95, line_dash="dot", line_color="orange", annotation_text="B=95%")
        fig.update_layout(height=320, margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Полный список товаров**")
    show = agg.copy()
    for col in ["выручка", "прибыль"]:
        show[col] = show[col].map(fmt_money)
    show["доля_%"]  = show["доля_%"].round(2).astype(str) + "%"
    show["накоп_%"] = show["накоп_%"].round(1).astype(str) + "%"
    show["маржа_%"] = show["маржа_%"].astype(str) + "%"
    st.dataframe(
        show.rename(columns={
            "offer_id": "Offer ID",
            "product_name": "Товар",
            "продаж": "Шт",
            "заказов": "Заказов",
        }),
        hide_index=True, width="stretch", height=420,
    )

    st.markdown("**⚠ Убыточные «лидеры» — товары класса A/B с отрицательной маржой**")
    losers = agg[(agg["класс"].isin({"A", "B"})) & (agg["прибыль"] < 0)]
    if losers.empty:
        st.success("Все товары классов A и B прибыльны.")
    else:
        disp = losers.copy()
        for col in ["выручка", "прибыль"]:
            disp[col] = disp[col].map(fmt_money)
        st.dataframe(disp[["offer_id", "product_name", "класс", "выручка", "прибыль", "маржа_%"]],
                     hide_index=True, width="stretch")


# ---------------------------------------------------------------------------
# Вкладка 3: Возвраты и отмены
# ---------------------------------------------------------------------------
def tab_returns(df: pd.DataFrame) -> None:
    st.subheader("Возвраты и отмены")

    od = orders_dedup(df)
    by_seller = od.groupby("seller_name", observed=True).agg(
        заказов=("ya_order_id", "nunique"),
        возвратов=("is_returned", "sum"),
        отмен_до_отгрузки=("is_cancelled_before", "sum"),
    )
    by_seller["return_rate_%"] = (by_seller["возвратов"] / by_seller["заказов"] * 100).round(1)
    by_seller["cancel_rate_%"] = (by_seller["отмен_до_отгрузки"] / by_seller["заказов"] * 100).round(1)

    # Потерянная выручка и стоимость возврата (наши затраты на вернувшийся товар)
    lost_rev = od[od["is_cancelled_any"]].groupby("seller_name", observed=True)["sell_price"].sum()
    cost_of_returns = (
        df[df["is_returned"]]
        .groupby("seller_name", observed=True)["our_costs"].sum()
    )
    by_seller["потерянная_выручка"] = lost_rev
    by_seller["затраты_на_возвраты"] = cost_of_returns
    by_seller = by_seller.fillna(0).reset_index().rename(columns={"seller_name": "Магазин"})

    disp = by_seller.copy()
    for col in ["потерянная_выручка", "затраты_на_возвраты"]:
        disp[col] = disp[col].map(fmt_money)
    disp["return_rate_%"] = disp["return_rate_%"].map(lambda x: f"{x:.1f}%")
    disp["cancel_rate_%"] = disp["cancel_rate_%"].map(lambda x: f"{x:.1f}%")
    st.dataframe(disp, hide_index=True, width="stretch")

    st.markdown("**Топ товаров по возвратам**")
    by_prod = df.groupby(["offer_id", "product_name"], observed=True).agg(
        продано=("quantity", "sum"),
        возвратов=("is_returned", "sum"),
        потерянная_выручка=("sell_price", lambda s: s[df.loc[s.index, "is_returned"]].sum()),
    ).reset_index()
    by_prod = by_prod[by_prod["возвратов"] > 0].copy()
    by_prod["return_rate_%"] = (by_prod["возвратов"] / by_prod["продано"] * 100).round(1)
    by_prod = by_prod.sort_values("возвратов", ascending=False).head(30)
    by_prod["потерянная_выручка"] = by_prod["потерянная_выручка"].map(fmt_money)
    by_prod["return_rate_%"] = by_prod["return_rate_%"].map(lambda x: f"{x:.1f}%")
    st.dataframe(
        by_prod.rename(columns={"offer_id": "Offer ID", "product_name": "Товар"}),
        hide_index=True, width="stretch",
    )


# ---------------------------------------------------------------------------
# Вкладка 4: Поставщики
# ---------------------------------------------------------------------------
def tab_suppliers(df: pd.DataFrame) -> None:
    st.subheader("Аналитика по поставщикам")
    st.caption("Поставщик берётся из `ya_order_items.supplier_name` (откуда фактически отгружено).")

    has_sup = df[df["supplier_name"].notna() & (df["supplier_name"] != "")]
    if has_sup.empty:
        st.info("Нет данных по поставщикам.")
        return

    agg = has_sup.groupby("supplier_name", observed=True).agg(
        заказов=("ya_order_id", "nunique"),
        позиций=("item_id", "count"),
        шт=("quantity", "sum"),
        выручка=("sell_price", "sum"),
        наши_затраты=("our_costs", "sum"),
        прибыль=("profit", "sum"),
        возвратов=("is_returned", "sum"),
    ).reset_index()
    agg["маржа_%"] = (agg["прибыль"] / agg["выручка"].replace(0, np.nan) * 100).round(1)
    agg["return_rate_%"] = (agg["возвратов"] / agg["позиций"] * 100).round(1)
    agg = agg.sort_values("прибыль", ascending=False)

    disp = agg.copy()
    for col in ["выручка", "наши_затраты", "прибыль"]:
        disp[col] = disp[col].map(fmt_money)
    disp["маржа_%"] = disp["маржа_%"].fillna(0).map(lambda x: f"{x:.1f}%")
    disp["return_rate_%"] = disp["return_rate_%"].fillna(0).map(lambda x: f"{x:.1f}%")
    st.dataframe(
        disp.rename(columns={"supplier_name": "Поставщик"}),
        hide_index=True, width="stretch",
    )

    fig = px.bar(
        agg.head(15), x="supplier_name", y="прибыль",
        color="маржа_%", color_continuous_scale="RdYlGn",
        title="Топ-15 поставщиков по прибыли",
    )
    fig.update_layout(height=380, xaxis_title="", yaxis_title="Прибыль, ₽")
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Вкладка 5: Ценообразование
# ---------------------------------------------------------------------------
def tab_pricing(df: pd.DataFrame) -> None:
    st.subheader("Ценообразование")

    od = orders_dedup(df).copy()
    od = od[od["sell_price"].notna() & (od["sell_price"] > 0)]
    if od.empty:
        st.info("Нет данных.")
        return

    below_min = od[od["diff_from_min_price"] < 0]
    share_below = len(below_min) / len(od) * 100

    c = st.columns(3)
    c[0].metric("Заказов ниже мин. цены", f"{len(below_min):,}".replace(",", " "))
    c[1].metric("Доля ниже минимальной", fmt_pct(share_below))
    c[2].metric("Сумма недополучено vs мин.", fmt_money(below_min["diff_from_min_price"].sum()))

    st.markdown("**Распределение `diff_from_min_price` (sell_price − минимальная цена)**")
    fig = px.histogram(
        od, x="diff_from_min_price", nbins=60,
        labels={"diff_from_min_price": "Разница от мин. цены, ₽"},
    )
    fig.add_vline(x=0, line_dash="dash", line_color="red")
    fig.update_layout(height=320, margin=dict(l=20, r=20, t=10, b=20))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Распределение маржи на заказ (%)**")
    md = df.groupby("ya_order_id").agg(
        sell_price=("sell_price", "first"),
        profit=("profit", "sum"),
    )
    md = md[md["sell_price"] > 0]
    md["margin_pct"] = md["profit"] / md["sell_price"] * 100
    md = md[md["margin_pct"].between(-100, 100)]
    fig = px.histogram(md, x="margin_pct", nbins=60,
                       labels={"margin_pct": "Маржа на заказ, %"})
    fig.add_vline(x=0, line_dash="dash", line_color="red")
    fig.update_layout(height=320, margin=dict(l=20, r=20, t=10, b=20))
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Вкладка 6: Денежный поток
# ---------------------------------------------------------------------------
def tab_cashflow(df: pd.DataFrame) -> None:
    st.subheader("Денежный поток и выплаты")

    od = orders_dedup(df).copy()
    received = od[od["payment_status"].isin({"Переведён", "Удержан из платежей покупателей"})]
    pending  = od[~od.index.isin(received.index) & ~od["is_cancelled_any"]]

    c = st.columns(4)
    c[0].metric("Получено всего", fmt_money(received["expected_payout"].sum()))
    c[1].metric("Ожидается выплата", fmt_money(pending["expected_payout"].sum()))
    c[2].metric("Заказов в ожидании", f"{len(pending):,}".replace(",", " "))

    avg_lag = od["pay_lag_days"].dropna()
    avg_lag = avg_lag[(avg_lag >= 0) & (avg_lag < 180)]
    c[3].metric("Средний лаг выплаты", f"{avg_lag.mean():.1f} дн" if len(avg_lag) else "—")

    st.markdown("**Outstanding (ожидающие выплаты) по магазинам**")
    out = pending.groupby("seller_name", observed=True).agg(
        заказов=("ya_order_id", "nunique"),
        ожидается=("expected_payout", "sum"),
    ).reset_index().sort_values("ожидается", ascending=False)
    out["ожидается"] = out["ожидается"].map(fmt_money)
    st.dataframe(out.rename(columns={"seller_name": "Магазин"}),
                 hide_index=True, width="stretch")

    st.markdown("**Распределение лага выплаты (дни от заказа до денег)**")
    if len(avg_lag):
        fig = px.histogram(avg_lag, nbins=40,
                           labels={"value": "Дней до выплаты"})
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=10, b=20),
                          showlegend=False)
        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Вкладка 7: Операционные метрики
# ---------------------------------------------------------------------------
def tab_ops(df: pd.DataFrame) -> None:
    st.subheader("Операционные метрики")

    od = orders_dedup(df)

    ship = od["ship_lag_days"].dropna()
    ship = ship[(ship >= 0) & (ship < 60)]

    cancel_pen = od.get("seller_cancel_penalty", pd.Series(dtype=float)).fillna(0).sum()
    late_pen   = od.get("late_ship_penalty", pd.Series(dtype=float)).fillna(0).sum()
    comp       = od.get("compensations", pd.Series(dtype=float)).fillna(0).sum()

    c = st.columns(4)
    c[0].metric("Средний срок отгрузки",
                f"{ship.mean():.1f} дн" if len(ship) else "—")
    c[1].metric("Штрафы за отмену", fmt_money(cancel_pen))
    c[2].metric("Штрафы за позднюю отгрузку", fmt_money(late_pen))
    c[3].metric("Компенсации в нашу пользу", fmt_money(comp))

    if len(ship):
        st.markdown("**Распределение времени до отгрузки (дни)**")
        fig = px.histogram(ship, nbins=30, labels={"value": "Дней"})
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=10, b=20),
                          showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Воронка статусов**")
    funnel = od.groupby("fulfillment_status", observed=True)["ya_order_id"].nunique()
    funnel = funnel.sort_values(ascending=False).reset_index()
    funnel.columns = ["Статус", "Заказов"]
    fig = px.funnel(funnel, x="Заказов", y="Статус")
    fig.update_layout(height=400, margin=dict(l=20, r=20, t=10, b=20))
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Вкладка 8: Тренды
# ---------------------------------------------------------------------------
def tab_trends(df: pd.DataFrame) -> None:
    st.subheader("Тренды и динамика")

    if df["created_at"].isna().all():
        st.info("Нет дат заказов.")
        return

    granularity = st.radio("Гранулярность", ["День", "Неделя", "Месяц"],
                           horizontal=True, index=1)
    freq = {"День": "D", "Неделя": "W", "Месяц": "MS"}[granularity]

    od = orders_dedup(df).copy()
    od["период"] = od["created_at"].dt.tz_localize(None).dt.to_period(
        {"D": "D", "W": "W", "MS": "M"}[freq]
    ).dt.start_time

    items = df.copy()
    items["период"] = items["created_at"].dt.tz_localize(None).dt.to_period(
        {"D": "D", "W": "W", "MS": "M"}[freq]
    ).dt.start_time

    order_agg = od.groupby("период").agg(
        выручка=("sell_price", "sum"),
        заказов=("ya_order_id", "nunique"),
        выплата=("expected_payout", "sum"),
    )
    item_agg = items.groupby("период").agg(
        прибыль=("profit", "sum"),
        затраты=("our_costs", "sum"),
    )
    trend = order_agg.join(item_agg).reset_index()
    trend["AOV"] = trend["выручка"] / trend["заказов"]
    trend["маржа_%"] = (trend["прибыль"] / trend["выручка"] * 100).round(1)
    trend["MoM_выручка_%"] = (trend["выручка"].pct_change() * 100).round(1)

    fig = go.Figure()
    fig.add_bar(x=trend["период"], y=trend["выручка"], name="Выручка")
    fig.add_trace(go.Scatter(x=trend["период"], y=trend["прибыль"],
                             name="Прибыль", mode="lines+markers",
                             line=dict(color="green", width=3)))
    fig.update_layout(height=400, title="Выручка и прибыль",
                      margin=dict(l=20, r=20, t=40, b=20),
                      legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        fig = px.line(trend, x="период", y="AOV", title="AOV (средний чек)", markers=True)
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.line(trend, x="период", y="маржа_%",
                      title="Маржа, %", markers=True)
        fig.add_hline(y=0, line_dash="dash", line_color="red")
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Сводная таблица**")
    disp = trend.copy()
    for col in ["выручка", "выплата", "прибыль", "затраты", "AOV"]:
        disp[col] = disp[col].map(fmt_money)
    disp["маржа_%"] = disp["маржа_%"].astype(str) + "%"
    disp["MoM_выручка_%"] = disp["MoM_выручка_%"].fillna(0).astype(str) + "%"
    st.dataframe(disp, hide_index=True, width="stretch")

    # Heat-map: день недели × неделя
    st.markdown("**Heat-map: день недели × неделя (выручка)**")
    hm = od.copy()
    hm["неделя"] = hm["created_at"].dt.tz_localize(None).dt.to_period("W").dt.start_time
    hm["день_недели"] = hm["created_at"].dt.day_name()
    pivot = hm.pivot_table(index="день_недели", columns="неделя",
                           values="sell_price", aggfunc="sum", fill_value=0)
    days_order = ["Monday", "Tuesday", "Wednesday", "Thursday",
                  "Friday", "Saturday", "Sunday"]
    pivot = pivot.reindex([d for d in days_order if d in pivot.index])
    if not pivot.empty:
        fig = px.imshow(pivot, aspect="auto", color_continuous_scale="Viridis",
                        labels={"color": "Выручка, ₽"})
        fig.update_layout(height=320, margin=dict(l=20, r=20, t=10, b=20))
        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Вкладка 9: Распределение прибыли
# ---------------------------------------------------------------------------
def tab_distribution(df: pd.DataFrame) -> None:
    st.subheader("Распределение прибыли по заказам")

    by_order = df.groupby("ya_order_id").agg(
        profit=("profit", "sum"),
        sell_price=("sell_price", "first"),
        seller_name=("seller_name", "first"),
    ).reset_index()
    by_order = by_order[by_order["sell_price"].fillna(0) > 0]

    n_loss = (by_order["profit"] < 0).sum()
    n_total = len(by_order)
    avg_profit = by_order["profit"].mean()
    median_profit = by_order["profit"].median()

    c = st.columns(4)
    c[0].metric("Заказов всего", f"{n_total:,}".replace(",", " "))
    c[1].metric("Убыточных", f"{n_loss:,}".replace(",", " "))
    c[2].metric("Средняя прибыль/заказ", fmt_money(avg_profit))
    c[3].metric("Медианная прибыль/заказ", fmt_money(median_profit))

    fig = px.histogram(by_order, x="profit", nbins=80,
                       color="seller_name",
                       labels={"profit": "Прибыль за заказ, ₽",
                               "seller_name": "Магазин"})
    fig.add_vline(x=0, line_dash="dash", line_color="red")
    fig.update_layout(height=400, margin=dict(l=20, r=20, t=10, b=20))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Топ-20 самых убыточных заказов**")
    losers = by_order.nsmallest(20, "profit").copy()
    losers["profit"] = losers["profit"].map(fmt_money)
    losers["sell_price"] = losers["sell_price"].map(fmt_money)
    st.dataframe(
        losers.rename(columns={
            "ya_order_id": "ID заказа",
            "profit": "Прибыль",
            "sell_price": "Выручка",
            "seller_name": "Магазин",
        }),
        hide_index=True, width="stretch",
    )


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
def main():
    st.title("Аналитика юнит-экономики")
    st.caption("Все денежные показатели в рублях. Магазины без отчёта о марже Маркета по умолчанию исключены — переключите фильтр в боковой панели, чтобы включить их в выборку.")

    try:
        df = load_data()
    except Exception as e:
        st.error(f"Ошибка загрузки: {e}")
        st.stop()

    filtered = sidebar_filters(df)

    if filtered.empty:
        st.warning("Нет данных по выбранным фильтрам.")
        st.stop()

    tabs = st.tabs([
        "KPI",
        "ABC-анализ",
        "Возвраты и отмены",
        "Поставщики",
        "Ценообразование",
        "Денежный поток",
        "Операционные метрики",
        "Тренды",
        "Распределение прибыли",
    ])

    with tabs[0]: tab_kpi(filtered)
    with tabs[1]: tab_abc(filtered)
    with tabs[2]: tab_returns(filtered)
    with tabs[3]: tab_suppliers(filtered)
    with tabs[4]: tab_pricing(filtered)
    with tabs[5]: tab_cashflow(filtered)
    with tabs[6]: tab_ops(filtered)
    with tabs[7]: tab_trends(filtered)
    with tabs[8]: tab_distribution(filtered)


main()
