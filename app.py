"""
Дашборд Wildberries на Streamlit.
Заказы, выкупы, возвраты, реклама, остатки, динамика и история (PostgreSQL).
"""

import datetime as dt

import pandas as pd
import requests
import streamlit as st
import plotly.express as px

import wb_api as wb

st.set_page_config(page_title="WB Дашборд", page_icon="📦", layout="wide")


def fmt(n, suffix=""):
    return f"{n:,.0f}".replace(",", " ") + suffix


# ---- кэшированные обёртки (у WB строгий лимит частоты запросов) -------------
@st.cache_data(ttl=300, show_spinner=False)
def c_orders(date_from):
    return wb.get_orders(date_from)


@st.cache_data(ttl=300, show_spinner=False)
def c_sales(date_from):
    return wb.get_sales(date_from)


@st.cache_data(ttl=300, show_spinner=False)
def c_stocks(date_from):
    return wb.get_stocks(date_from)


@st.cache_data(ttl=1800, show_spinner=False)
def c_ad_campaigns():
    return wb.get_advert_campaigns()


@st.cache_data(ttl=1800, show_spinner=False)
def c_ad_stats(ids, begin, end):
    return wb.get_advert_fullstats(list(ids), begin, end)


# ---- проверка токена -------------------------------------------------------
st.title("📦 Дашборд Wildberries")

if not wb.token():
    st.error(
        "Не задан **WB_TOKEN**. В Railway: проект → сервис → вкладка **Variables** → "
        "добавьте `WB_TOKEN` со значением токена WB (категория «Статистика»)."
    )
    st.stop()

with st.sidebar:
    st.header("Настройки")
    days = st.slider("Период, дней назад", 1, 90, 14)
    date_from = wb.days_ago_iso(days)
    st.caption(f"Данные с {date_from}")
    if st.button("🔄 Обновить (сбросить кэш)"):
        st.cache_data.clear()
        st.rerun()

engine = wb.db_engine()

# ---- загрузка данных -------------------------------------------------------
try:
    orders = c_orders(date_from)
    sales = c_sales(date_from)
    stocks = c_stocks(date_from)
except requests.HTTPError as e:
    code = e.response.status_code if e.response is not None else "?"
    msg = {
        401: "WB вернул 401 — токен неверный или не той категории. Нужен токен «Статистика».",
        429: "WB вернул 429 — слишком частые запросы. Подождите минуту и обновите.",
    }.get(code, f"Ошибка запроса к WB API: {e}")
    st.error(msg)
    st.stop()

kpis = wb.compute_kpis(orders, sales)
buyouts, returns = wb.split_sales(sales)
o_amt = wb.order_amount_col(orders)

# снапшот в БД при каждом открытии (история копится)
try:
    wb.save_snapshot(engine, kpis, period_days=days)
except Exception as e:  # noqa: BLE001
    st.sidebar.warning(f"Снапшот в БД не записан: {e}")

# ---- KPI -------------------------------------------------------------------
r1 = st.columns(4)
r1[0].metric("Заказов", fmt(kpis["orders_cnt"]))
r1[1].metric("Сумма заказов, ₽", fmt(kpis["orders_sum"]))
r1[2].metric("Выкупов", fmt(kpis["buyouts_cnt"]))
r1[3].metric("К перечислению, ₽", fmt(kpis["buyouts_sum"]))

r2 = st.columns(4)
r2[0].metric("% выкупа", fmt(kpis["buyout_rate"], " %"))
r2[1].metric("Средний чек, ₽", fmt(kpis["avg_check"]))
r2[2].metric("Отмен", fmt(kpis["cancels_cnt"]))
r2[3].metric("Возвратов", fmt(kpis["returns_cnt"]))

tabs = st.tabs(["Обзор", "Заказы", "Выкупы и возвраты", "Реклама", "Остатки", "История"])

# ===========================================================================
# Обзор — динамика
# ===========================================================================
with tabs[0]:
    if orders.empty:
        st.info("Заказов за период нет.")
    else:
        o = orders.copy()
        o["date"] = pd.to_datetime(o["date"]).dt.date
        od = o.groupby("date").agg(заказов=(o_amt, "size"), сумма=(o_amt, "sum")).reset_index()

        if not sales.empty:
            s = buyouts.copy()
            s["date"] = pd.to_datetime(s["date"]).dt.date
            sd = s.groupby("date")["forPay"].sum().reset_index().rename(columns={"forPay": "выкуплено"})
            merged = od.merge(sd, on="date", how="left").fillna(0)
        else:
            merged = od.assign(выкуплено=0)

        st.plotly_chart(
            px.line(merged, x="date", y=["сумма", "выкуплено"], markers=True,
                    title="Динамика: заказы vs выкупы, ₽",
                    labels={"value": "₽", "variable": "показатель", "date": "дата"}),
            use_container_width=True,
        )
        st.plotly_chart(
            px.bar(od, x="date", y="заказов", title="Количество заказов по дням",
                   labels={"заказов": "шт", "date": "дата"}),
            use_container_width=True,
        )

# ===========================================================================
# Заказы
# ===========================================================================
with tabs[1]:
    if orders.empty:
        st.info("Заказов за период нет.")
    else:
        o = orders.copy()
        c1, c2 = st.columns(2)
        if "subject" in o:
            top = o.groupby("subject")[o_amt].sum().sort_values(ascending=False).head(15).reset_index()
            c1.plotly_chart(px.bar(top, x=o_amt, y="subject", orientation="h",
                                   title="Топ категорий по сумме, ₽"), use_container_width=True)
        if "brand" in o:
            tb = o.groupby("brand")[o_amt].sum().sort_values(ascending=False).head(15).reset_index()
            c2.plotly_chart(px.bar(tb, x=o_amt, y="brand", orientation="h",
                                   title="Топ брендов по сумме, ₽"), use_container_width=True)
        region_col = "oblastOkrugName" if "oblastOkrugName" in o else (
            "regionName" if "regionName" in o else None)
        if region_col:
            reg = o.groupby(region_col)[o_amt].sum().sort_values(ascending=False).head(15).reset_index()
            st.plotly_chart(px.bar(reg, x=o_amt, y=region_col, orientation="h",
                                   title="География заказов по сумме, ₽"), use_container_width=True)
        st.dataframe(o, use_container_width=True, height=320)

# ===========================================================================
# Выкупы и возвраты
# ===========================================================================
with tabs[2]:
    if sales.empty:
        st.info("Продаж за период нет.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Сумма выкупов, ₽", fmt(kpis["buyouts_sum"]))
        ret_sum = float(returns["forPay"].sum()) if ("forPay" in returns and not returns.empty) else 0.0
        c2.metric("Сумма возвратов, ₽", fmt(abs(ret_sum)))

        b = buyouts.copy()
        if not b.empty:
            b["date"] = pd.to_datetime(b["date"]).dt.date
            bd = b.groupby("date")["forPay"].sum().reset_index()
            st.plotly_chart(px.area(bd, x="date", y="forPay", title="Выкупы по дням (к перечислению), ₽",
                                    labels={"forPay": "₽", "date": "дата"}), use_container_width=True)
            if "warehouseName" in b:
                wh = b.groupby("warehouseName")["forPay"].sum().sort_values(ascending=False).head(15).reset_index()
                st.plotly_chart(px.bar(wh, x="forPay", y="warehouseName", orientation="h",
                                       title="Выкупы по складам, ₽"), use_container_width=True)
        st.dataframe(sales, use_container_width=True, height=320)

# ===========================================================================
# Реклама (требует токен с доступом «Продвижение»)
# ===========================================================================
with tabs[3]:
    st.caption("Данные рекламы тянутся отдельно (лимит WB). Нажмите кнопку, чтобы загрузить.")
    if st.button("📈 Загрузить данные рекламы"):
        st.session_state["load_ads"] = True
    if st.session_state.get("load_ads"):
        try:
            campaigns = c_ad_campaigns()
            ids = wb.flatten_campaign_ids(campaigns)
            st.write(f"Найдено кампаний: **{len(ids)}**")
            stats = c_ad_stats(tuple(ids), date_from, wb.today_iso()) if ids else []
            if stats:
                rows = []
                for s in stats:
                    rows.append({
                        "Кампания": s.get("advertId"),
                        "Показы": s.get("views", 0),
                        "Клики": s.get("clicks", 0),
                        "CTR, %": round(s.get("ctr", 0), 2),
                        "CPC, ₽": round(s.get("cpc", 0), 2),
                        "Расход, ₽": round(s.get("sum", 0), 2),
                        "Заказы": s.get("orders", 0),
                        "Сумма заказов, ₽": round(s.get("sum_price", 0), 2),
                    })
                ad = pd.DataFrame(rows)
                spend = ad["Расход, ₽"].sum()
                revenue = ad["Сумма заказов, ₽"].sum()
                drr = (spend / revenue * 100.0) if revenue else 0.0
                k = st.columns(4)
                k[0].metric("Расход на рекламу, ₽", fmt(spend))
                k[1].metric("Показы", fmt(ad["Показы"].sum()))
                k[2].metric("Клики", fmt(ad["Клики"].sum()))
                k[3].metric("ДРР, %", fmt(drr, " %"))
                st.dataframe(ad, use_container_width=True, height=320)
            else:
                st.info("Активных кампаний со статистикой за период не найдено.")
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            if code in (401, 403):
                st.warning("Токен без доступа к рекламе. Создайте в WB токен с категорией «Продвижение» "
                           "и используйте его (или добавьте доступ к текущему).")
            elif code == 429:
                st.warning("WB вернул 429 по рекламе — подождите минуту и попробуйте снова.")
            else:
                st.error(f"Ошибка рекламного API: {e}")

# ===========================================================================
# Остатки
# ===========================================================================
with tabs[4]:
    if stocks.empty:
        st.info("Данных по остаткам нет.")
    else:
        sdf = stocks.copy()
        qty = "quantityFull" if "quantityFull" in sdf else "quantity"
        c1, c2 = st.columns(2)
        c1.metric("Всего единиц на складах", fmt(int(sdf[qty].sum())) if qty in sdf else "—")
        if "inWayToClient" in sdf:
            c2.metric("В пути к клиенту", fmt(int(sdf["inWayToClient"].sum())))
        if "warehouseName" in sdf and qty in sdf:
            wh = sdf.groupby("warehouseName")[qty].sum().sort_values(ascending=False).reset_index()
            st.plotly_chart(px.bar(wh, x=qty, y="warehouseName", orientation="h",
                                   title="Остатки по складам, шт"), use_container_width=True)
        if "subject" in sdf and qty in sdf:
            sub = sdf.groupby("subject")[qty].sum().sort_values(ascending=False).head(15).reset_index()
            st.plotly_chart(px.bar(sub, x=qty, y="subject", orientation="h",
                                   title="Остатки по категориям, шт"), use_container_width=True)
        st.dataframe(sdf, use_container_width=True, height=320)

# ===========================================================================
# История (PostgreSQL)
# ===========================================================================
with tabs[5]:
    if engine is None:
        st.info("PostgreSQL не подключён — история недоступна.")
    else:
        hist = wb.load_history(engine)
        if hist.empty:
            st.info("История пока пустая — она копится с каждым открытием дашборда и ежедневным авто-снимком.")
        else:
            h = hist.copy()
            h["ts"] = pd.to_datetime(h["ts"])
            st.plotly_chart(px.line(h, x="ts", y=["orders_sum", "sales_sum"], markers=True,
                                    title="Динамика снимков: заказы vs выкупы, ₽"),
                            use_container_width=True)
            if "buyout_rate" in h:
                st.plotly_chart(px.line(h, x="ts", y="buyout_rate", markers=True,
                                        title="Динамика % выкупа"), use_container_width=True)
            st.dataframe(h, use_container_width=True, height=300)

st.caption("Данные кэшируются на 5 минут. WB ограничивает частоту запросов статистики.")
