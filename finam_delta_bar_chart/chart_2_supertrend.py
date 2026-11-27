r"""Показывает адаптивные дельта-бары Finam с двумя линиями Supertrend.

Загружает свечи RTS или MIX через chart.load_chart с тем же дневным SQLite-кэшем.
Рисует младший и старший Supertrend ступенями на шкале цены, вместе с частотой
покупок и продаж и нижней панелью разницы объёмов. ATR рассчитывается в барах
с начала загруженного диапазона. Цвет каждой линии меняется с направлением тренда.
Общие панели рисует src.chart_view. Скрипт открывает окно или сохраняет PNG.

Команды ниже запускаются из корня проекта.
    .\.venv\Scripts\python.exe .\finam_delta_bar_chart\chart_2_supertrend.py --symbol RTS --date 2026-11-11
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_2_supertrend --symbol MIX --start 2026-11-09 --date 2026-11-11 --fast-period 8 --fast-multiplier 2 --slow-period 21 --slow-multiplier 4 --png MIX_supertrend.png
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_2_supertrend --symbol MIX --start 2026-09-01
    """

import argparse
from datetime import date
from math import isfinite
from pathlib import Path
import sqlite3
import sys
from zipfile import BadZipFile

if __package__:
    from .chart import ConsoleProgress, load_chart
    from .src.chart_view import show_delta_chart
    from .src.finam_archives import DEFAULT_ROOT
    from .src.supertrend import calculate_supertrend
else:
    from chart import ConsoleProgress, load_chart
    from src.chart_view import show_delta_chart
    from src.finam_archives import DEFAULT_ROOT
    from src.supertrend import calculate_supertrend

FAST_COLORS = ("#19a32a", "#e23c36")
SLOW_COLORS = ("#006331", "#951d22")


def plot_supertrend(fplt, axis, x, levels, colors, width):
    """Рисует на axis ступени levels по номерам x через модуль fplt.

    colors задаёт цвета роста и падения в этом порядке, width — толщину.
    Каждая ступень занимает ширину одного бара. При смене цвета линии разорваны.
    """
    edges = (x - 0.5).tolist()
    edges.append(edges[-1] + 1)
    for rising, color in zip((True, False), colors):
        values = [point[0] if point is not None and point[1] == rising else float("nan")
                  for point in levels]
        if not any(isfinite(value) for value in values):
            continue
        curve = fplt.plot(x, values, ax=axis, color=color, width=width)
        # У ряда из N уровней N + 1 граница. Прореживание разрушает это соответствие.
        curve.setClipToView(False)
        curve.setDownsampling(ds=1, auto=False)
        curve.setData(edges, values, stepMode="center", connect="finite")


def show_chart(bars, symbol, fast, slow, png=None):
    """Показывает bars инструмента symbol с Supertrend или сохраняет график в png.

    fast и slow содержат период ATR в барах и множитель младшего и старшего
    индикаторов соответственно. png задаёт путь экспорта вместо открытия окна.
    """
    fast_levels = calculate_supertrend(bars, *fast)
    slow_levels = calculate_supertrend(bars, *slow)

    def draw_overlay(fplt, axis, x):
        """Рисует через fplt обе линии на ценовой оси axis по номерам баров x."""
        plot_supertrend(fplt, axis, x, slow_levels, SLOW_COLORS, 1.8)
        plot_supertrend(fplt, axis, x, fast_levels, FAST_COLORS, 1.2)
        fplt.add_legend(f"Supertrend · младший {fast[0]} × {fast[1]:g} · старший {slow[0]} × {slow[1]:g}",
                        ax=axis)

    def read_overlay(index):
        """Возвращает оба уровня Supertrend для номера бара index, считая с нуля."""
        levels = [f"{point[0]:.2f}" if point is not None else "—"
                  for point in (fast_levels[index], slow_levels[index])]
        return f"Supertrend · младший {levels[0]} · старший {levels[1]}"

    show_delta_chart(bars, symbol, png, title="Дельта-бары и Supertrend",
                     draw_overlay=draw_overlay, read_overlay=read_overlay)


def main(argv=None):
    """Разбирает аргументы argv, строит график и возвращает код завершения."""
    parser = argparse.ArgumentParser(description="Адаптивные дельта-бары Finam с двумя Supertrend")
    parser.add_argument("--symbol", choices=("RTS", "MIX"), default="RTS", help="инструмент (по умолчанию RTS)")
    parser.add_argument("--date", type=date.fromisoformat, help="дата сессии ГГГГ-ММ-ДД (по умолчанию последняя с тиками)")
    parser.add_argument("--start", type=date.fromisoformat, help="начало многодневного графика включительно")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_ROOT, help=f"корень тиковых архивов ({DEFAULT_ROOT})")
    parser.add_argument("--png", type=Path, help="сохранить график в PNG")
    for name, label, period, multiplier in (("fast", "младшего", 10, 2), ("slow", "старшего", 21, 4)):
        parser.add_argument(f"--{name}-period", type=int, default=period,
                            help=f"период ATR {label} Supertrend в барах (по умолчанию {period})")
        parser.add_argument(f"--{name}-multiplier", type=float, default=multiplier,
                            help=f"множитель ATR {label} Supertrend (по умолчанию {multiplier})")
    args = parser.parse_args(argv)
    fast = args.fast_period, args.fast_multiplier
    slow = args.slow_period, args.slow_multiplier
    for name, (period, multiplier) in (("fast", fast), ("slow", slow)):
        if period < 1:
            parser.error(f"--{name}-period должен быть целым числом больше нуля")
        if not isfinite(multiplier) or multiplier <= 0:
            parser.error(f"--{name}-multiplier должен быть конечным числом больше нуля")

    try:
        print(f"{args.symbol} · Поиск архивов и проверка дневного кэша…", file=sys.stderr, flush=True)
        progress = ConsoleProgress(sys.stderr)
        try:
            bars = load_chart(args.input_root, args.symbol, args.date, args.start, progress=progress)
        finally:
            progress.finish_line()
        print(f"Построение графика · свечей {len(bars)}", file=sys.stderr, flush=True)
        show_chart(bars, args.symbol, fast, slow, args.png)
    except (ImportError, OSError, ValueError, BadZipFile, sqlite3.Error) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    if args.png:
        print(f"Сохранено {len(bars)} свечей: {args.png.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
