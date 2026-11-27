r"""Задаёт общее окно истории, цвета и подписи для графика и бэктеста Finam.

Форматирует знаковую разницу объёмов для подсказок двух режимов.
Пакет загружает chart.py. Примеры из корня проекта:
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py --symbol MIX --date 2026-11-11
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py --backtest --symbol RTS
"""

WINDOW = 20
BUY_COLOR = "#188552"
SELL_COLOR = "#cf404d"
VOLUME_DIFF_LABEL = "Объём − среднее"


def format_volume_diff(value):
    """Возвращает значение value в контрактах со знаком и максимум двумя десятичными знаками."""
    if value == 0:
        return "0"
    return f"{value:+,.2f}".rstrip("0").rstrip(".").replace(",", " ").replace("-", "−")
