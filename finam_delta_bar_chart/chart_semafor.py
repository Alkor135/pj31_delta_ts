r"""Показывает «Семафор» и острова SMA на дельта-барах Finam RTS или MIX.

Загружает бары через дневной SQLite-кэш. CountZZ и две SMA рассчитываются
по порядку свечей, включая выбранную предысторию. На ценовой панели показаны
острова SMA и метки NUF или FXi из pj24_delta_bars. Старшие солнышки обведены
синим кольцом. Скрипт открывает интерактивное окно или сохраняет PNG.
Параметры СФ/SMA и загрузка диапазона также используются в ручном бэктесте.

Команды ниже запускаются из корня проекта.
    .\.venv\Scripts\python.exe .\finam_delta_bar_chart\chart_semafor.py --symbol RTS --date 2026-11-11
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor --symbol MIX --start 2026-11-11 --history-start 2026-11-09 --date 2026-11-11 --ma-fast 3 --ma-slow 34 --png MIX_semafor.png
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor --symbol MIX --start 2026-09-01
"""

import argparse
from bisect import bisect_left
from datetime import date
from pathlib import Path
import sqlite3
import sys
from zipfile import BadZipFile

if __package__:
    from .chart import ConsoleProgress, load_chart
    from .src.chart_view import show_delta_chart
    from .src.finam_archives import DEFAULT_ROOT
    from .src.semafor import (
        DEFAULT_DEPTHS, DEFAULT_MA_FAST, DEFAULT_MA_SLOW, PRESETS, calculate_semafor, validate_settings,
    )
    from .src.semafor_style import (
        FXI_CENTER_COLOUR, ISLAND_COLOURS, LEVEL_STYLES, MARKER_SIDES, RING_COLOUR,
        SMA_COLOURS, marker_style, semafor_details, sun_symbol,
    )
else:
    from chart import ConsoleProgress, load_chart
    from src.chart_view import show_delta_chart
    from src.finam_archives import DEFAULT_ROOT
    from src.semafor import (
        DEFAULT_DEPTHS, DEFAULT_MA_FAST, DEFAULT_MA_SLOW, PRESETS, calculate_semafor, validate_settings,
    )
    from src.semafor_style import (
        FXI_CENTER_COLOUR, ISLAND_COLOURS, LEVEL_STYLES, MARKER_SIDES, RING_COLOUR,
        SMA_COLOURS, marker_style, semafor_details, sun_symbol,
    )

OFFSETS = {"RTS": 40.0, "MIX": 100.0}


def load_semafor_range(input_root, symbol, end=None, start=None, *, history_start=None, progress=None):
    """Возвращает бары symbol из input_root и индекс первого видимого бара.

    start и end задают видимый диапазон. history_start добавляет скрытые
    бары до него. progress получает ход загрузки Finam.
    """
    if history_start is not None and start is not None and history_start > start:
        raise ValueError("Начало предыстории должно быть не позже начала графика")
    bars = load_chart(input_root, symbol, end, history_start or start, progress=progress)
    visible_start = start.isoformat() if start else bars[-1]["end_time"][:10]
    first = bisect_left(bars, visible_start, key=lambda bar: bar["end_time"][:10])
    return bars, first


def load_semafor_bars(input_root, symbol, end=None, start=None, *, history_start=None,
                      progress=None, **settings):
    """Возвращает видимые бары symbol из input_root, метки СФ и значения SMA.

    start и end задают видимый диапазон, history_start — начало прогрева.
    progress получает ход загрузки, settings — настройки СФ и SMA.
    """
    bars, first = load_semafor_range(input_root, symbol, end, start,
                                     history_start=history_start, progress=progress)
    points = calculate_semafor(bars, **settings)
    return bars[first:], points.iloc[first:].reset_index(drop=True)


def plot_sma_islands(fplt, axis, x, points):
    """Рисует острова и границы SMA из points поверх оси axis на позициях x через fplt."""
    import pyqtgraph as pg

    x_values = x.to_numpy(dtype=float)
    fast, slow = points.ma_fast.to_numpy(), points.ma_slow.to_numpy()
    for direction, color in ISLAND_COLOURS:
        mask = points.island_direction.to_numpy() == direction
        if mask.any():
            # Каждому бару соответствует одна полоса между средними.
            fill = pg.BarGraphItem(x=x_values[mask], y0=slow[mask], y1=fast[mask],
                                   width=1, pen=None, brush=pg.mkBrush(color))
            fill.setZValue(-10)
            axis.addItem(fill)
    for name, color in SMA_COLOURS:
        values = points[name]
        if values.notna().any():
            line = fplt.plot(x, values, color=color, width=1, ax=axis)
            line.setDownsampling(auto=False)
    fplt.add_legend(f"Острова · SMA {points.attrs['ma_fast']}/{points.attrs['ma_slow']}", ax=axis)


def show_chart(bars, symbol, points, png=None, *, depths, preset, offset):
    """Показывает bars инструмента symbol с метками и SMA из points или сохраняет png.

    depths содержит глубины слоёв, preset задаёт внешний вид NUF или FXi,
    offset — декоративный отступ в единицах цены.
    """
    def draw_overlay(fplt, axis, x):
        """Рисует острова, метки и контуры на ценовой оси axis по номерам баров x через finplot."""
        import pyqtgraph as pg

        axis.vb.v_zoom_scale = 0.92
        sun = sun_symbol()
        plot_sma_islands(fplt, axis, x, points)
        fplt.add_legend(f"Семафор · {preset.upper()}", ax=axis)
        for level, (depth, (size, label)) in enumerate(zip(depths, LEVEL_STYLES), 1):
            if not depth:
                continue
            for side, _, color, sign in MARKER_SIDES:
                values = points[f"sf{level}_{side}"]
                if not values.notna().any():
                    continue
                shape, color = marker_style(level, preset, color, sun)
                positions = (values + sign * offset).rename(f"sf{level}_{side}_display")
                item = fplt.plot(x, positions, style="o", color=color, width=size / 7, ax=axis)
                item.setSymbol(shape)
                item.setSymbolPen(pg.mkPen(color, width=0.9))
                item.setDownsampling(auto=False)
                item.setZValue(19 + level)
                if level == 3:
                    ring = pg.ScatterPlotItem(x=item.xData, y=item.yData, size=size + 8,
                                              symbol="o", pen=pg.mkPen(RING_COLOUR, width=2),
                                              brush=None, pxMode=True)
                    ring.setZValue(23)
                    axis.addItem(ring, ignoreBounds=True)
                if preset == "fxi" and level == 3:
                    center = fplt.plot(x, positions.rename(f"sf{level}_{side}_center"),
                                       style="o", color=FXI_CENTER_COLOUR, width=6 / 7,
                                       ax=axis, zoomscale=False)
                    center.setDownsampling(auto=False)
                    center.setZValue(24)
            fplt.add_legend(f"СФ {depth} · {label}", ax=axis)

    def read_overlay(index):
        """Возвращает значения SMA и цены меток бара index без декоративного отступа."""
        return semafor_details(points, index, depths) or "Семафор · —"

    show_delta_chart(bars, symbol, png, title="Дельта-бары · Семафор и острова SMA",
                     draw_overlay=draw_overlay, read_overlay=read_overlay)


def semafor_parser(description):
    """Создаёт парсер с описанием description и общими аргументами графика и бэктеста."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--symbol", choices=("RTS", "MIX"), default="RTS", help="инструмент (по умолчанию RTS)")
    parser.add_argument("--date", "--end", dest="date", type=date.fromisoformat,
                        help="последний день графика ГГГГ-ММ-ДД (по умолчанию последняя сессия с тиками)")
    parser.add_argument("--start", type=date.fromisoformat, help="первый видимый день графика включительно")
    parser.add_argument("--history-start", type=date.fromisoformat, help="первый день расчёта с учётом скрытой предыстории")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_ROOT, help=f"корень тиковых архивов ({DEFAULT_ROOT})")
    parser.add_argument("--preset", choices=tuple(PRESETS), default="nuf", help="вариант семафора (по умолчанию nuf)")
    parser.add_argument("--depths", type=int, nargs=3, default=DEFAULT_DEPTHS, metavar=("МАЛ", "СРЕД", "СТАРШ"),
                        help="три глубины в барах (по умолчанию 5 12 34, 0 отключает уровень)")
    parser.add_argument("--deviation", type=int, help="допуск в единицах Point (1 у NUF, 5 у FXi)")
    parser.add_argument("--backstep", type=int, help="число прошлых баров для удаления кандидатов (1 у NUF, 3 у FXi)")
    parser.add_argument("--point", type=float, default=1, help="единица цены для Deviation (по умолчанию 1)")
    parser.add_argument("--offset", type=float, help="отступ меток в единицах цены (40 для RTS, 100 для MIX)")
    parser.add_argument("--ma-fast", type=int, default=DEFAULT_MA_FAST,
                        help=f"период быстрой SMA в барах (по умолчанию {DEFAULT_MA_FAST})")
    parser.add_argument("--ma-slow", type=int, default=DEFAULT_MA_SLOW,
                        help=f"период медленной SMA в барах (по умолчанию {DEFAULT_MA_SLOW})")
    return parser


def semafor_settings(parser, args):
    """Проверяет аргументы args через parser и возвращает настройки расчёта и отступ меток."""
    default_deviation, default_backstep = PRESETS[args.preset]
    offset = OFFSETS[args.symbol] if args.offset is None else args.offset
    try:
        settings = validate_settings(args.depths, default_deviation if args.deviation is None else args.deviation,
                                     default_backstep if args.backstep is None else args.backstep, args.point,
                                     args.ma_fast, args.ma_slow)
        if not 0 <= offset <= 100000:
            raise ValueError("Отступ должен быть числом от 0 до 100000")
        if args.history_start and args.history_start > (args.start or args.date or date.max):
            raise ValueError("Начало предыстории должно быть не позже начала графика")
        if args.start and args.date and args.start > args.date:
            raise ValueError("Начало графика позже конечной даты")
    except ValueError as exc:
        parser.error(str(exc))
    return settings, offset


def main(argv=None):
    """Разбирает аргументы argv, строит график и возвращает код завершения."""
    parser = semafor_parser("Дельта-бары Finam с Семафором и островами SMA")
    parser.add_argument("--png", type=Path, help="сохранить график в PNG")
    args = parser.parse_args(argv)
    settings, offset = semafor_settings(parser, args)
    try:
        print(f"{args.symbol} · Поиск архивов и проверка дневного кэша…", file=sys.stderr, flush=True)
        progress = ConsoleProgress(sys.stderr)
        try:
            bars, points = load_semafor_bars(args.input_root, args.symbol, args.date, args.start,
                                            history_start=args.history_start, progress=progress, **settings)
        finally:
            progress.finish_line()
        print(f"Построение графика · свечей {len(bars)}", file=sys.stderr, flush=True)
        show_chart(bars, args.symbol, points, args.png,
                   depths=settings["depths"], preset=args.preset, offset=offset)
    except (ImportError, OSError, ValueError, BadZipFile, sqlite3.Error) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    if args.png:
        print(f"Сохранено {len(bars)} свечей: {args.png.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
