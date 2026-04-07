import streamlit as st

st.set_page_config(
    page_title="Wolle — Юнит-экономика",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Юнит-экономика Яндекс Маркет")
st.info("Загрузите Excel-отчёты из Яндекс Маркета или подключитесь к базе данных, чтобы начать анализ.")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Excel-отчёты")
    uploaded = st.file_uploader(
        "Загрузить отчёт (.xlsx / .xls)",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
    )
    if uploaded:
        for f in uploaded:
            st.success(f"Загружен: {f.name}")

with col2:
    st.subheader("База данных")
    st.write("Настройте подключение в `.env` (см. `.env.example`).")
    if st.button("Проверить подключение к БД"):
        from db.connection import test_connection
        ok, msg = test_connection()
        if ok:
            st.success(msg)
        else:
            st.error(msg)
