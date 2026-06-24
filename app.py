"""
Дашборд Wildberries (FBO/FBS) на Streamlit.
Тянет данные из WB Statistics API (заказы, продажи, остатки),
показывает KPI и графики, опционально кэширует историю в PostgreSQL.

Переменные окружения:
  WB_TOKEN      — API-токен Wildberries (категория "Статистика"). ОБЯЗАТЕЛЬНО.
  DATABASE_URL  — строка подключения PostgreSQL (Railway проставляет сам). Необязательно.
"""

import os
import datetime as dt

import pandas as pd
import requests
import streamlit as st
import plotly.express as px

WB_BASE = "https://statistics-api.wildberries.ru"
TIMEOUT = 60

st.set_page_config(page_title="WB Дашборд", page_icon="📦", layout="wide")


# ----------------------------------------------------------------------------
# WB API
# ----------------------------------------------------------------------------
def _token() -> str:
    return (os.environ.get("WB_TOKEN") or "").strip()


def _headers() -> dict:
    return {"Authorization": _token()}


@st.cache_data(ttl=300, show_spinner=False)
def wb_get(endpoint: str, date_from: str, flag: int = 0) -> pd.DataFrame:
    """Запрос к WB Statistics API. Кэш 5 минут (у WB строгий лимит ~1 запрос/мин)."""
    url = f"{WB_BASE}{endpoint}"
    params = {"dateFrom": date_from, "flag": flag}
    r = requests.get(url, headers=_headers(), params=params, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        return pd.DataFrame()
    return pd.DataFrame(data)


def get_orders(date_from: str) -> pd.DataFrame:
    return wb_get("/api/v1/supplier/orders", date_from)


def get_sales(date_from: str) -> pd.DataFrame:
    return wb_get("/api/v1/supplier/sales", date_from)


def get_stocks(date_from: str) -> pd.DataFrame:
    return wb_get("/api/v1/supplier/stocks", date_from)


# ----------------------------------------------------------------------------
# PostgreSQL (опционально)
# ----------------------------------------------------------------------------
def db_engine():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return None
    # SQLAlchemy ждёт postgresql:// вместо postgres://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    try:
        from sqlalchemy import create_engine
        return create_engine(url, pool_pre_ping=True)
    except Exception as e:  # noqa: BLE001
        st.sidebar.warning(f"PostgreSQL недоступен: {e}")
        return None


def save_snapshot(engine, orders_cnt: int, orders_sum: float, sales_cnt: int, sales_sum: float):
    if engine is None:
        return
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS wb_snapshots (
                    id SERIAL PRIMARY KEY,
                    ts TIMESTAMP DEFAULT NOW(),
                    orders_cnt INT,
                    orders_sum NUMERIC,
                    sales_cnt INT,
                    sales_sum NUMERIC
                )
                """
            ))
            conn.execute(text(
                "INSERT INTO wb_snapshots (orders_cnt, orders_sum, sales_cnt, sales_sum) "
                "VALUES (:oc, :os, :sc, :ss)"
            ), {"oc": orders_cnt, "os": orders_sum, "sc": sales_cnt, "ss": sales_sum})
    except Exception as e:  # noqa: BLE001
        st.sidebar.warning(f"Не записал снапшот в БД: {e}")


def load_history(engine) -> pd.DataFrame:
    if engine is None:
        return pd.DataFrame()
    try:
        return pd.read_sql("SELECT * FROM wb_snapshots ORDER BY ts", engine)
    except Exception:
        return pd.DataFrame()


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------
st.title("📦 Дашборд Wildberries")

if not _token():
    st.error(
        "Не задан **WB_TOKEN**. В Railway: проект → сервис → вкладка **Variables** → "
        "добавьте переменную `WB_TOKEN` со значением токена WB (категория «Статистика»)."
    )
    st.stop()

with st.sidebar:
    st.header("Настройки")
    days = st.slider("Период, дней назад", 1, 90, 14)
    date_from = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    st.caption(f"Данные с {date_from}")
    if st.button("🔄 Обновить (сбросить кэш)"):
        st.cache_data.clear()
        st.rerun()

engine = db_engine()

try:
    orders = get_orders(date_from)
    sales = get_sales(date_from)
    stocks = get_stocks(date_from)
except requests.HTTPError as e:
    code = e.response.status_code if e.response is not None else "?"
    if code == 401:
        st.error("WB вернул 401 — токен неверный или не той категории. Нужен токен «Статистика».")
    elif code == 429:
        st.error("WB вернул 429 — слишком частые запросы. Подождите минуту и обновите.")
    else:
        st.error(f"Ошибка запроса к WB API: {e}")
    st.stop()

# --- KPI ---
orders_cnt = len(orders)
orders_sum = float(orders["totalPrice"].sum()) if "totalPrice" in orders else 0.0
# реальные продажи (выкупы): isCancel == False / forPay
sales_cnt = len(sales)
sales_sum = float(sales["forPay"].sum()) if "forPay" in sales else 0.0

save_snapshot(engine, orders_cnt, orders_sum, sales_cnt, sales_sum)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Заказов", f"{orders_cnt:,}".replace(",", " "))
c2.metric("Сумма заказов, ₽", f"{orders_sum:,.0f}".replace(",", " "))
c3.metric("Продаж (выкупов)", f"{sales_cnt:,}".replace(",", " "))
c4.metric("К перечислению, ₽", f"{sales_sum:,.0f}".replace(",", " "))

tab_o, tab_s, tab_st, tab_h = st.tabs(["Заказы", "Продажи", "Остатки", "История"])

# --- Заказы ---
with tab_o:
    if orders.empty:
        st.info("Заказов за период нет.")
    else:
        o = orders.copy()
        o["date"] = pd.to_datetime(o["date"]).dt.date
        by_day = o.groupby("date").agg(
            заказов=("totalPrice", "size"),
            сумма=("totalPrice", "sum"),
        ).reset_index()
        st.plotly_chart(
            px.bar(by_day, x="date", y="сумма", title="Сумма заказов по дням, ₽"),
            use_container_width=True,
        )
        if "subject" in o:
            top = o.groupby("subject")["totalPrice"].sum().sort_values(ascending=False).head(15).reset_index()
            st.plotly_chart(
                px.bar(top, x="totalPrice", y="subject", orientation="h", title="Топ категорий по сумме, ₽"),
                use_container_width=True,
            )
        st.dataframe(o, use_container_width=True, height=300)

# --- Продажи ---
with tab_s:
    if sales.empty:
        st.info("Продаж за период нет.")
    else:
        s = sales.copy()
        s["date"] = pd.to_datetime(s["date"]).dt.date
        by_day = s.groupby("date")["forPay"].sum().reset_index()
        st.plotly_chart(
            px.line(by_day, x="date", y="forPay", markers=True, title="К перечислению по дням, ₽"),
            use_container_width=True,
        )
        if "warehouseName" in s:
            wh = s.groupby("warehouseName")["forPay"].sum().sort_values(ascending=False).head(15).reset_index()
            st.plotly_chart(
                px.bar(wh, x="forPay", y="warehouseName", orientation="h", title="По складам, ₽"),
                use_container_width=True,
            )
        st.dataframe(s, use_container_width=True, height=300)

# --- Остатки ---
with tab_st:
    if stocks.empty:
        st.info("Данных по остаткам нет.")
    else:
        st_df = stocks.copy()
        qty_col = "quantityFull" if "quantityFull" in st_df else "quantity"
        total_qty = int(st_df[qty_col].sum()) if qty_col in st_df else 0
        st.metric("Всего единиц на складах", f"{total_qty:,}".replace(",", " "))
        if "warehouseName" in st_df and qty_col in st_df:
            wh = st_df.groupby("warehouseName")[qty_col].sum().sort_values(ascending=False).reset_index()
            st.plotly_chart(
                px.bar(wh, x=qty_col, y="warehouseName", orientation="h", title="Остатки по складам, шт"),
                use_container_width=True,
            )
        st.dataframe(st_df, use_container_width=True, height=300)

# --- История (из PostgreSQL) ---
with tab_h:
    if engine is None:
        st.info("PostgreSQL не подключён — история снапшотов недоступна. "
                "Добавьте в проект Railway базу PostgreSQL, и переменная DATABASE_URL появится автоматически.")
    else:
        hist = load_history(engine)
        if hist.empty:
            st.info("История пока пустая — она копится с каждым открытием дашборда.")
        else:
            st.plotly_chart(
                px.line(hist, x="ts", y=["orders_sum", "sales_sum"], title="Динамика снапшотов, ₽"),
                use_container_width=True,
            )
            st.dataframe(hist, use_container_width=True, height=300)

st.caption("Данные кэшируются на 5 минут. WB ограничивает частоту запросов статистики.")
