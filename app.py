"""
Дашборд Wildberries на Streamlit — тёмная премиальная тема.
Слева календарь: выбор даты/периода → метрики (заказы ₽/шт, выкупы, отмены, возвраты),
динамика, реклама, остатки, история (PostgreSQL).
"""

import datetime as dt

import pandas as pd
import requests
import streamlit as st
import plotly.express as px
import plotly.io as pio

import wb_api as wb

st.set_page_config(page_title="WB Дашборд", page_icon="📦", layout="wide",
                   initial_sidebar_state="expanded")

# ---------------------------------------------------------------------------
# Тёмная премиальная тема (CSS + палитра графиков)
# ---------------------------------------------------------------------------
ACCENT = "#D4AF37"        # золото
ACCENT2 = "#7C9CF5"       # холодный синий
PALETTE = ["#D4AF37", "#7C9CF5", "#5AD1A5", "#E08F6A", "#B57EDC", "#6AD0E0", "#E0C56A"]

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');

      .stApp {
        background:
          radial-gradient(1100px 520px at 12% -8%, #1b2233 0%, rgba(15,17,23,0) 55%),
          radial-gradient(900px 500px at 100% 0%, #1a1726 0%, rgba(15,17,23,0) 50%),
          #0E1117;
        color: #E8EAED;
        font-family: 'Inter', sans-serif;
      }
      section[data-testid="stSidebar"] {
        background: #0A0C11;
        border-right: 1px solid #1c2230;
      }
      section[data-testid="stSidebar"] * { color: #cdd2db; }

      h1, h2, h3, h4 { color: #F3F4F6 !important; font-weight: 800 !important; letter-spacing:.2px; }

      /* Карточки метрик */
      div[data-testid="stMetric"] {
        background: linear-gradient(165deg, #1b2030 0%, #12151d 100%);
        border: 1px solid #262c3a;
        border-radius: 16px;
        padding: 16px 18px;
        box-shadow: 0 6px 22px rgba(0,0,0,.40);
        transition: transform .15s ease, border-color .15s ease;
      }
      div[data-testid="stMetric"]:hover { transform: translateY(-2px); border-color:#D4AF37; }
      div[data-testid="stMetricLabel"] p { color:#9aa2b1 !important; font-weight:600; font-size:.82rem; text-transform:uppercase; letter-spacing:.6px; }
      div[data-testid="stMetricValue"] { color:#F5F5F5 !important; font-weight:800 !important; }

      /* Вкладки */
      .stTabs [data-baseweb="tab-list"] { gap: 6px; border-bottom:1px solid #1f2533; }
      .stTabs [data-baseweb="tab"] { font-weight:600; color:#9aa2b1; padding:6px 14px; }
      .stTabs [aria-selected="true"] { color:#D4AF37 !important; }
      .stTabs [data-baseweb="tab-highlight"] { background:#D4AF37 !important; }

      /* Кнопки */
      .stButton > button {
        background: linear-gradient(180deg,#23283a,#171b26);
        color:#EDEFF3; border:1px solid #2c3445; border-radius:12px; font-weight:600;
      }
      .stButton > button:hover { border-color:#D4AF37; color:#fff; }

      /* Таблицы / контейнеры */
      .block-container { padding-top: 1.6rem; max-width: 1500px; }
      #MainMenu, footer, header { visibility:hidden; }

      /* Заголовок-герой */
      .hero { display:flex; align-items:center; gap:14px; margin-bottom:.2rem; }
      .hero .badge {
        font-size:.72rem; color:#0E1117; background:#D4AF37; padding:3px 10px;
        border-radius:999px; font-weight:800; letter-spacing:.4px;
      }
      .subtle { color:#8b93a2; font-size:.86rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

pio.templates.default = "plotly_dark"


def styled(fig):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#D7DBE2", family="Inter"),
        title_font=dict(color="#F3F4F6", size=16),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    fig.update_xaxes(gridcolor="#1e2430", zerolinecolor="#1e2430")
    fig.update_yaxes(gridcolor="#1e2430", zerolinecolor="#1e2430")
    return fig


def fmt(n, suffix=""):
    return f"{n:,.0f}".replace(",", " ") + suffix


# ---------------------------------------------------------------------------
# Кэшированные обёртки
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Шапка + проверка токена
# ---------------------------------------------------------------------------
st.markdown(
    '<div class="hero"><span style="font-size:30px">📦</span>'
    '<h1 style="margin:0">Дашборд Wildberries</h1>'
    '<span class="badge">PREMIUM</span></div>',
    unsafe_allow_html=True,
)

if not wb.token():
    st.error(
        "Не задан **WB_TOKEN**. В Railway: проект → сервис → вкладка **Variables** → "
        "добавьте `WB_TOKEN` со значением токена WB (категория «Статистика»)."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Сайдбар: КАЛЕНДАРЬ
# ---------------------------------------------------------------------------
today = dt.date.today()
with st.sidebar:
    st.markdown("### 📅 Календарь")
    st.caption("Выберите дату или период")
    sel = st.date_input(
        "Дата / период",
        value=(today - dt.timedelta(days=13), today),
        min_value=today - dt.timedelta(days=365),
        max_value=today,
        format="DD.MM.YYYY",
        label_visibility="collapsed",
    )
    # быстрые кнопки
    c1, c2 = st.columns(2)
    quick = None
    if c1.button("Сегодня", use_container_width=True):
        quick = (today, today)
    if c2.button("Вчера", use_container_width=True):
        quick = (today - dt.timedelta(days=1), today - dt.timedelta(days=1))

    if quick:
        start_d, end_d = quick
    elif isinstance(sel, (tuple, list)):
        start_d = sel[0]
        end_d = sel[1] if len(sel) > 1 else sel[0]
    else:
        start_d = end_d = sel

    one_day = start_d == end_d
    st.markdown(
        f"<div class='subtle'>Показаны данные за <b style='color:#D4AF37'>"
        f"{start_d.strftime('%d.%m.%Y')}</b>"
        + ("" if one_day else f" — <b style='color:#D4AF37'>{end_d.strftime('%d.%m.%Y')}</b>")
        + "</div>",
        unsafe_allow_html=True,
    )
    st.divider()
    if st.button("🔄 Обновить (сбросить кэш)", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

date_from = start_d.isoformat()
engine = wb.db_engine()


def in_range(df):
    """Фильтрует строки по полю date в выбранный период [start_d, end_d]."""
    if df.empty or "date" not in df.columns:
        return df
    d = pd.to_datetime(df["date"]).dt.date
    return df[(d >= start_d) & (d <= end_d)]


# ---------------------------------------------------------------------------
# Загрузка данных
# ---------------------------------------------------------------------------
try:
    orders = in_range(c_orders(date_from))
    sales = in_range(c_sales(date_from))
    stocks = c_stocks(date_from)  # остатки — текущий срез, не фильтруем по дате
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

try:
    wb.save_snapshot(engine, kpis, period_days=(end_d - start_d).days + 1)
except Exception as e:  # noqa: BLE001
    st.sidebar.warning(f"Снапшот в БД не записан: {e}")

period_label = (start_d.strftime("%d.%m.%Y") if one_day
                else f"{start_d.strftime('%d.%m.%Y')} — {end_d.strftime('%d.%m.%Y')}")
st.markdown(f"<div class='subtle'>📆 Период: <b>{period_label}</b></div>", unsafe_allow_html=True)
st.write("")

# ---------------------------------------------------------------------------
# KPI
# ---------------------------------------------------------------------------
r1 = st.columns(4)
r1[0].metric("Заказов, шт", fmt(kpis["orders_cnt"]))
r1[1].metric("Сумма заказов, ₽", fmt(kpis["orders_sum"]))
r1[2].metric("Выкупов, шт", fmt(kpis["buyouts_cnt"]))
r1[3].metric("К перечислению, ₽", fmt(kpis["buyouts_sum"]))

r2 = st.columns(4)
r2[0].metric("% выкупа", fmt(kpis["buyout_rate"], " %"))
r2[1].metric("Средний чек, ₽", fmt(kpis["avg_check"]))
r2[2].metric("Отмен, шт", fmt(kpis["cancels_cnt"]))
r2[3].metric("Возвратов, шт", fmt(kpis["returns_cnt"]))

tabs = st.tabs(["Обзор", "Заказы", "Выкупы и возвраты", "Реклама", "Остатки", "История"])

# ===========================================================================
# Обзор
# ===========================================================================
with tabs[0]:
    if orders.empty:
        st.info("За выбранную дату/период заказов нет.")
    else:
        o = orders.copy()
        o["date"] = pd.to_datetime(o["date"]).dt.date
        od = o.groupby("date").agg(заказов=(o_amt, "size"), сумма=(o_amt, "sum")).reset_index()

        if not buyouts.empty:
            s = buyouts.copy()
            s["date"] = pd.to_datetime(s["date"]).dt.date
            sd = s.groupby("date")["forPay"].sum().reset_index().rename(columns={"forPay": "выкуплено"})
            merged = od.merge(sd, on="date", how="left").fillna(0)
        else:
            merged = od.assign(выкуплено=0)

        st.plotly_chart(styled(px.line(
            merged, x="date", y=["сумма", "выкуплено"], markers=True,
            title="Динамика: заказы vs выкупы, ₽",
            labels={"value": "₽", "variable": "", "date": "дата"},
            color_discrete_sequence=PALETTE)), use_container_width=True)
        st.plotly_chart(styled(px.bar(
            od, x="date", y="заказов", title="Количество заказов по дням, шт",
            labels={"заказов": "шт", "date": "дата"},
            color_discrete_sequence=[ACCENT])), use_container_width=True)

# ===========================================================================
# Заказы
# ===========================================================================
with tabs[1]:
    if orders.empty:
        st.info("Заказов нет.")
    else:
        o = orders.copy()
        c1, c2 = st.columns(2)
        if "subject" in o:
            top = o.groupby("subject")[o_amt].sum().sort_values(ascending=False).head(15).reset_index()
            c1.plotly_chart(styled(px.bar(top, x=o_amt, y="subject", orientation="h",
                            title="Топ категорий по сумме, ₽",
                            color_discrete_sequence=[ACCENT])), use_container_width=True)
        if "brand" in o:
            tb = o.groupby("brand")[o_amt].sum().sort_values(ascending=False).head(15).reset_index()
            c2.plotly_chart(styled(px.bar(tb, x=o_amt, y="brand", orientation="h",
                            title="Топ брендов по сумме, ₽",
                            color_discrete_sequence=[ACCENT2])), use_container_width=True)
        region_col = "oblastOkrugName" if "oblastOkrugName" in o else (
            "regionName" if "regionName" in o else None)
        if region_col:
            reg = o.groupby(region_col)[o_amt].sum().sort_values(ascending=False).head(15).reset_index()
            st.plotly_chart(styled(px.bar(reg, x=o_amt, y=region_col, orientation="h",
                            title="География заказов по сумме, ₽",
                            color_discrete_sequence=PALETTE)), use_container_width=True)
        st.dataframe(o, use_container_width=True, height=320)

# ===========================================================================
# Выкупы и возвраты
# ===========================================================================
with tabs[2]:
    if sales.empty:
        st.info("Продаж нет.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Сумма выкупов, ₽", fmt(kpis["buyouts_sum"]))
        ret_sum = float(returns["forPay"].sum()) if ("forPay" in returns and not returns.empty) else 0.0
        c2.metric("Сумма возвратов, ₽", fmt(abs(ret_sum)))

        b = buyouts.copy()
        if not b.empty:
            b["date"] = pd.to_datetime(b["date"]).dt.date
            bd = b.groupby("date")["forPay"].sum().reset_index()
            st.plotly_chart(styled(px.area(bd, x="date", y="forPay",
                            title="Выкупы по дням (к перечислению), ₽",
                            labels={"forPay": "₽", "date": "дата"},
                            color_discrete_sequence=[ACCENT])), use_container_width=True)
            if "warehouseName" in b:
                wh = b.groupby("warehouseName")["forPay"].sum().sort_values(ascending=False).head(15).reset_index()
                st.plotly_chart(styled(px.bar(wh, x="forPay", y="warehouseName", orientation="h",
                                title="Выкупы по складам, ₽",
                                color_discrete_sequence=[ACCENT2])), use_container_width=True)
        st.dataframe(sales, use_container_width=True, height=320)

# ===========================================================================
# Реклама
# ===========================================================================
with tabs[3]:
    st.caption("Данные рекламы тянутся отдельно (лимит WB ~1 запрос/мин). Нажмите кнопку.")
    if st.button("📈 Загрузить данные рекламы"):
        st.session_state["load_ads"] = True
    if st.session_state.get("load_ads"):
        try:
            campaigns = c_ad_campaigns()
            ids = wb.flatten_campaign_ids(campaigns)
            st.write(f"Кампаний со статистикой: **{len(ids)}**")
            ad_begin = max(start_d, today - dt.timedelta(days=31)).isoformat()
            stats = c_ad_stats(tuple(ids), ad_begin, today.isoformat()) if ids else []
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
                st.info("Кампаний со статистикой за период не найдено (или WB лимитирует запрос).")
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            if code in (401, 403):
                st.warning("Токен без доступа к рекламе. Нужен токен с категорией «Продвижение».")
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
            st.plotly_chart(styled(px.bar(wh, x=qty, y="warehouseName", orientation="h",
                            title="Остатки по складам, шт",
                            color_discrete_sequence=[ACCENT])), use_container_width=True)
        if "subject" in sdf and qty in sdf:
            sub = sdf.groupby("subject")[qty].sum().sort_values(ascending=False).head(15).reset_index()
            st.plotly_chart(styled(px.bar(sub, x=qty, y="subject", orientation="h",
                            title="Остатки по категориям, шт",
                            color_discrete_sequence=[ACCENT2])), use_container_width=True)
        st.dataframe(sdf, use_container_width=True, height=320)

# ===========================================================================
# История
# ===========================================================================
with tabs[5]:
    if engine is None:
        st.info("PostgreSQL не подключён — история недоступна.")
    else:
        hist = wb.load_history(engine)
        if hist.empty:
            st.info("История пока пустая — копится с каждым открытием и ежедневным авто-снимком.")
        else:
            h = hist.copy()
            h["ts"] = pd.to_datetime(h["ts"])
            st.plotly_chart(styled(px.line(h, x="ts", y=["orders_sum", "sales_sum"], markers=True,
                            title="Динамика снимков: заказы vs выкупы, ₽",
                            color_discrete_sequence=PALETTE)), use_container_width=True)
            if "buyout_rate" in h:
                st.plotly_chart(styled(px.line(h, x="ts", y="buyout_rate", markers=True,
                                title="Динамика % выкупа",
                                color_discrete_sequence=[ACCENT])), use_container_width=True)
            st.dataframe(h, use_container_width=True, height=300)

st.markdown("<div class='subtle' style='margin-top:1rem'>Данные кэшируются на 5 минут. "
            "WB ограничивает частоту запросов статистики.</div>", unsafe_allow_html=True)
