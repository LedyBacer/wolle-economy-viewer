import streamlit as st


def render_navigation() -> None:
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.markdown("### 📦 Заказы")
        st.markdown(
            "Детализированная таблица позиций заказов с фильтрами "
            "по магазину, периоду, статусам, поиском по товару и поставщику. "
            "Экспорт в CSV / Excel."
        )
        st.page_link("pages/1_Заказы.py", label="Открыть раздел →")
    with c2, st.container(border=True):
        st.markdown("### 📈 Аналитика")
        st.markdown(
            "KPI-дашборд, ABC-анализ ассортимента, возвраты и отмены, "
            "поставщики, ценообразование, денежный поток и тренды."
        )
        st.page_link("pages/2_Аналитика.py", label="Открыть раздел →")

