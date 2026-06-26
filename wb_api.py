"""
Клиент WB API + помощники для PostgreSQL.
Используется и веб-дашбордом (app.py), и cron-скриптом (snapshot.py).

Переменные окружения:
  WB_TOKEN      — токен Wildberries (категории «Статистика», для рекламы — «Продвижение»).
  DATABASE_URL  — строка подключения PostgreSQL (Railway проставляет сам).
"""

import os
import datetime as dt

import pandas as pd
import requests

STAT_BASE = "https://statistics-api.wildberries.ru"
ADV_BASE = "https://advert-api.wildberries.ru"
TIMEOUT = 60


# ---------------------------------------------------------------------------
# Аутентификация
# ---------------------------------------------------------------------------
def token() -> str:
    return (os.environ.get("WB_TOKEN") or "").strip()


def _headers() -> dict:
    return {"Authorization": token()}


# ---------------------------------------------------------------------------
# Statistics API
# ---------------------------------------------------------------------------
def _stat_get(endpoint: str, date_from: str, flag: int = 0) -> pd.DataFrame:
    r = requests.get(
        f"{STAT_BASE}{endpoint}",
        headers=_headers(),
        params={"dateFrom": date_from, "flag": flag},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    return pd.DataFrame(data if isinstance(data, list) else [])


def get_orders(date_from: str) -> pd.DataFrame:
    return _stat_get("/api/v1/supplier/orders", date_from)


def get_sales(date_from: str) -> pd.DataFrame:
    return _stat_get("/api/v1/supplier/sales", date_from)


def get_stocks(date_from: str) -> pd.DataFrame:
    return _stat_get("/api/v1/supplier/stocks", date_from)


# ---------------------------------------------------------------------------
# Advertising API (нужен токен с доступом «Продвижение»)
# ---------------------------------------------------------------------------
def get_advert_campaigns() -> dict:
    """Список рекламных кампаний, сгруппированный по типам/статусам."""
    r = requests.get(f"{ADV_BASE}/adv/v1/promotion/count", headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_advert_fullstats(advert_ids: list, begin: str, end: str) -> list:
    """Полная статистика по кампаниям за период.
    Актуальный эндпоинт: GET /adv/v3/fullstats (params: ids, beginDate, endDate).
    Период максимум 31 день, до 100 кампаний за запрос.
    ids передаём одной строкой через запятую — так WB принимает стабильнее.
    Запрашиваем кампании пачками по 50, проблемные пачки пропускаем."""
    if not advert_ids:
        return []
    out = []
    ids = [int(i) for i in advert_ids]
    for k in range(0, min(len(ids), 100), 50):
        chunk = ids[k:k + 50]
        params = {"beginDate": begin, "endDate": end, "ids": ",".join(map(str, chunk))}
        try:
            r = requests.get(f"{ADV_BASE}/adv/v3/fullstats", headers=_headers(),
                             params=params, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                out.extend(data)
        except requests.HTTPError as e:
            # 400 по части кампаний (архивные/без статистики) — пропускаем пачку
            if e.response is not None and e.response.status_code in (400, 404):
                continue
            raise
    return out


def flatten_campaign_ids(campaigns: dict, statuses=(7, 9, 11)) -> list:
    """Достаёт advertId из ответа /adv/v1/promotion/count.
    По умолчанию берём кампании со статистикой: 9 (идут показы), 11 (пауза), 7 (завершена)."""
    ids = []
    for group in (campaigns or {}).get("adverts", []) or []:
        if statuses and group.get("status") not in statuses:
            continue
        for adv in group.get("advert_list", []) or []:
            if adv.get("advertId"):
                ids.append(adv["advertId"])
    return ids


# ---------------------------------------------------------------------------
# Производные метрики
# ---------------------------------------------------------------------------
def order_amount_col(df: pd.DataFrame) -> str:
    """Колонка с фактической ценой заказа (со скидкой)."""
    for c in ("priceWithDisc", "finishedPrice", "totalPrice"):
        if c in df.columns:
            return c
    return ""


def split_sales(sales: pd.DataFrame):
    """Делит записи sales на выкупы (S...) и возвраты (R...) по saleID."""
    if sales.empty or "saleID" not in sales.columns:
        return sales, sales.iloc[0:0]
    is_return = sales["saleID"].astype(str).str.startswith("R")
    return sales[~is_return], sales[is_return]


def compute_kpis(orders: pd.DataFrame, sales: pd.DataFrame) -> dict:
    """Сводные показатели за период."""
    buyouts, returns = split_sales(sales)

    o_amt = order_amount_col(orders)
    orders_cnt = int(len(orders))
    orders_sum = float(orders[o_amt].sum()) if o_amt else 0.0

    cancels_cnt = int(orders["isCancel"].sum()) if "isCancel" in orders.columns else 0

    buyouts_cnt = int(len(buyouts))
    buyouts_sum = float(buyouts["forPay"].sum()) if "forPay" in buyouts.columns else 0.0
    returns_cnt = int(len(returns))

    buyout_rate = (buyouts_cnt / orders_cnt * 100.0) if orders_cnt else 0.0
    avg_check = (orders_sum / orders_cnt) if orders_cnt else 0.0

    return {
        "orders_cnt": orders_cnt,
        "orders_sum": orders_sum,
        "buyouts_cnt": buyouts_cnt,
        "buyouts_sum": buyouts_sum,
        "returns_cnt": returns_cnt,
        "cancels_cnt": cancels_cnt,
        "buyout_rate": buyout_rate,
        "avg_check": avg_check,
    }


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------
def db_engine():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return None
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    from sqlalchemy import create_engine
    return create_engine(url, pool_pre_ping=True)


def ensure_schema(engine):
    if engine is None:
        return
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS wb_snapshots (
                id SERIAL PRIMARY KEY,
                ts TIMESTAMP DEFAULT NOW(),
                period_days INT,
                orders_cnt INT,
                orders_sum NUMERIC,
                sales_cnt INT,
                sales_sum NUMERIC
            )
            """
        ))
        # доращиваем недостающие колонки (на случай старой версии таблицы)
        for col, typ in [
            ("period_days", "INT"),
            ("buyouts_cnt", "INT"),
            ("buyouts_sum", "NUMERIC"),
            ("returns_cnt", "INT"),
            ("cancels_cnt", "INT"),
            ("buyout_rate", "NUMERIC"),
            ("avg_check", "NUMERIC"),
            ("ad_spend", "NUMERIC"),
        ]:
            conn.execute(text(
                f"ALTER TABLE wb_snapshots ADD COLUMN IF NOT EXISTS {col} {typ}"
            ))

def save_snapshot(engine, kpis: dict, period_days: int, ad_spend=None):
    if engine is None:
        return
    ensure_schema(engine)
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(
            """
            INSERT INTO wb_snapshots
                (period_days, orders_cnt, orders_sum, sales_cnt, sales_sum,
                 buyouts_cnt, buyouts_sum, returns_cnt, cancels_cnt,
                 buyout_rate, avg_check, ad_spend)
            VALUES
                (:period_days, :orders_cnt, :orders_sum, :buyouts_cnt, :buyouts_sum,
                 :buyouts_cnt, :buyouts_sum, :returns_cnt, :cancels_cnt,
                 :buyout_rate, :avg_check, :ad_spend)
            """
        ), {**kpis, "period_days": period_days, "ad_spend": ad_spend})


def load_history(engine):
    if engine is None:
        return pd.DataFrame()
    try:
        return pd.read_sql("SELECT * FROM wb_snapshots ORDER BY ts", engine)
    except Exception:
        return pd.DataFrame()


def today_iso() -> str:
    return dt.date.today().isoformat()


def days_ago_iso(days: int) -> str:
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# Feedbacks API — отзывы (нужен токен с доступом «Вопросы и отзывы»)
# ---------------------------------------------------------------------------
FEEDBACKS_BASE = "https://feedbacks-api.wildberries.ru"


def get_feedbacks(since_iso: str) -> pd.DataFrame:
    """Отзывы, созданные не раньше since_iso (YYYY-MM-DD).
    Возвращает DataFrame[createdDate, valuation]. Тянет отвеченные и неотвеченные
    постранично (order=dateDesc) и останавливается, пройдя since_iso."""
    rows = []
    for answered in ("true", "false"):
        skip = 0
        while True:
            r = requests.get(
                FEEDBACKS_BASE + "/api/v1/feedbacks",
                headers=_headers(),
                params={"isAnswered": answered, "take": 5000, "skip": skip, "order": "dateDesc"},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            fbs = ((r.json() or {}).get("data") or {}).get("feedbacks") or []
            if not fbs:
                break
            stop = False
            for f in fbs:
                cd = (f.get("createdDate") or "")[:10]
                rows.append({"createdDate": cd, "valuation": f.get("productValuation")})
                if cd and cd < since_iso:
                    stop = True
            if stop or len(fbs) < 5000:
                break
            skip += 5000
            if skip >= 200000:
                break
    return pd.DataFrame(rows)


def classify_feedbacks(df, a, b) -> dict:
    """Хорошие (4-5★) и плохие (1-3★) отзывы в диапазоне дат [a, b]."""
    empty = {"total": 0, "good": 0, "bad": 0, "avg": 0.0}
    if df is None or df.empty or "createdDate" not in df.columns:
        return empty
    d = pd.to_datetime(df["createdDate"], errors="coerce").dt.date
    sub = df[(d >= a) & (d <= b)]
    val = pd.to_numeric(sub["valuation"], errors="coerce")
    return {
        "total": int(len(sub)),
        "good": int((val >= 4).sum()),
        "bad": int((val <= 3).sum()),
        "avg": float(val.mean()) if val.notna().any() else 0.0,
    }
