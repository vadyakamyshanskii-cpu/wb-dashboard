"""
Ежедневный снимок показателей WB в PostgreSQL.
Запускается cron-сервисом Railway (например, каждый день в 03:00 UTC ≈ 06:00 МСК).

Берёт показатели за последние сутки (dateFrom = вчера) и пишет строку в wb_snapshots.
Читает WB_TOKEN и DATABASE_URL из переменных окружения.
"""

import sys
import traceback

import wb_api as wb

# окно снимка: последние сутки
PERIOD_DAYS = 1


def main() -> int:
    if not wb.token():
        print("WB_TOKEN не задан — снимок невозможен.", file=sys.stderr)
        return 1

    engine = wb.db_engine()
    if engine is None:
        print("DATABASE_URL не задан — некуда писать снимок.", file=sys.stderr)
        return 1

    date_from = wb.days_ago_iso(PERIOD_DAYS)
    print(f"Снимок за период с {date_from} (период {PERIOD_DAYS} дн.)")

    orders = wb.get_orders(date_from)
    sales = wb.get_sales(date_from)
    kpis = wb.compute_kpis(orders, sales)

    wb.save_snapshot(engine, kpis, period_days=PERIOD_DAYS)

    print(
        "Записано: заказов={orders_cnt} на {orders_sum:.0f} ₽, "
        "выкупов={buyouts_cnt} на {buyouts_sum:.0f} ₽, "
        "выкуп={buyout_rate:.1f}%".format(**kpis)
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
