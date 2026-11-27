r"""Показывает дельта-бары Finam и цену максимального объёма в каждом баре.

Загружает свечи RTS или MIX из основного дневного кэша, суммирует объёмы
исходных сделок по ценам в пределах бара и сохраняет максимумы рядом с кэшем
свечей. Рисует синие точки. При наведении показывает цену и объём в контрактах.
Открывает интерактивное окно или сохраняет PNG.

Команды ниже запускаются из корня проекта.
    .\.venv\Scripts\python.exe .\finam_delta_bar_chart\chart_claster_max_volume.py --symbol RTS --date 2026-11-11
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_claster_max_volume --symbol MIX --start 2026-11-09 --date 2026-11-11 --png MIX_clusters.png
"""

import argparse
from datetime import date
from pathlib import Path
import sqlite3
import sys
from zipfile import BadZipFile

if __package__:
    from .chart import ConsoleProgress, load_chart
    from .src.chart_view import show_delta_chart
    from .src.cluster_volume import load_clusters
    from .src.finam_archives import DEFAULT_ROOT
else:
    from chart import ConsoleProgress, load_chart
    from src.chart_view import show_delta_chart
    from src.cluster_volume import load_clusters
    from src.finam_archives import DEFAULT_ROOT


def show_chart(bars, symbol, clusters, png=None):
    """Показывает bars инструмента symbol с парами (цена, объём) из clusters или сохраняет png."""
    def draw_overlay(fplt, axis, x):
        """Рисует синие точки на ценовой оси axis по номерам баров x через fplt."""
        prices = [price for price, _ in clusters]
        fplt.plot(x, prices, ax=axis, style="o", color="#0000ff", width=0.8,
                  zoomscale=False, legend="Цена максимального объёма")

    def read_overlay(index):
        """Возвращает показания кластера для номера бара index, считая с нуля."""
        price, volume = clusters[index]
        return f"Макс. кластер · цена {price:.12g} · {volume} контр."

    show_delta_chart(bars, symbol, png, title="Дельта-бары и максимальный объём",
                     draw_overlay=draw_overlay, read_overlay=read_overlay)


def main(argv=None):
    """Разбирает аргументы argv, загружает бары и кластеры и возвращает код завершения."""
    parser = argparse.ArgumentParser(description="Адаптивные дельта-бары Finam с максимумами объёмов по ценам")
    parser.add_argument("--symbol", choices=("RTS", "MIX"), default="RTS", help="инструмент (по умолчанию RTS)")
    parser.add_argument("--date", type=date.fromisoformat, help="дата сессии ГГГГ-ММ-ДД (по умолчанию последняя с тиками)")
    parser.add_argument("--start", type=date.fromisoformat, help="начало многодневного графика включительно")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_ROOT, help=f"корень тиковых архивов ({DEFAULT_ROOT})")
    parser.add_argument("--png", type=Path, help="сохранить график в PNG")
    args = parser.parse_args(argv)

    try:
        print(f"{args.symbol} · Поиск архивов и проверка дневного кэша…", file=sys.stderr, flush=True)
        progress = ConsoleProgress(sys.stderr)
        try:
            bars = load_chart(args.input_root, args.symbol, args.date, args.start, progress=progress)
            clusters = load_clusters(args.input_root, args.symbol, bars, progress=progress)
        finally:
            progress.finish_line()
        print(f"Построение графика · свечей {len(bars)}", file=sys.stderr, flush=True)
        show_chart(bars, args.symbol, clusters, args.png)
    except (ImportError, OSError, ValueError, BadZipFile, sqlite3.Error) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    if args.png:
        print(f"Сохранено {len(bars)} свечей: {args.png.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
