r"""Показывает три уровня «Семафора» на дельта-барах Finam RTS или MIX.

Загружает бары через дневной SQLite-кэш. CountZZ рассчитывается по порядку
свечей, включая выбранную предысторию. На ценовой панели показаны точки,
светики и солнышки в оформлении NUF или FXi из проекта pj24_delta_bars.
Скрипт открывает интерактивное окно или сохраняет PNG.

Команды ниже запускаются из корня проекта.
    .\.venv\Scripts\python.exe .\finam_delta_bar_chart\chart_semafor.py --symbol RTS --date 2026-11-11
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor --symbol MIX --start 2026-11-11 --history-start 2026-11-09 --date 2026-11-11 --preset fxi --depths 0 12 34 --png MIX_semafor.png
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor --symbol MIX --start 2026-09-01
"""

import argparse
from bisect import bisect_left
from datetime import date
from math import cos, isfinite, pi, sin
from pathlib import Path
import sqlite3
import sys
from zipfile import BadZipFile

if __package__:
    from .chart import ConsoleProgress, load_chart
    from .src.chart_view import show_delta_chart
    from .src.finam_archives import DEFAULT_ROOT
    from .src.semafor import DEFAULT_DEPTHS, PRESETS, calculate_semafor, validate_settings
else:
    from chart import ConsoleProgress, load_chart
    from src.chart_view import show_delta_chart
    from src.finam_archives import DEFAULT_ROOT
    from src.semafor import DEFAULT_DEPTHS, PRESETS, calculate_semafor, validate_settings

OFFSETS = {"RTS": 40.0, "MIX": 100.0}


def load_semafor_bars(input_root, symbol, end=None, start=None, *, history_start=None,
                      progress=None, **settings):
    """Возвращает видимые бары инструмента symbol и таблицу их меток.

    input_root — корень архивов Finam, start и end — даты видимого диапазона.
    history_start может расширить расчёт в прошлое. После расчёта скрытые
    бары отбрасываются. progress получает ход загрузки, settings — настройки СФ.
    """
    if history_start is not None and start is not None and history_start > start:
        raise ValueError("Начало предыстории должно быть не позже начала графика")
    bars = load_chart(input_root, symbol, end, history_start or start, progress=progress)
    points = calculate_semafor(bars, **settings)
    visible_start = start.isoformat() if start else bars[-1]["end_time"][:10]
    first = bisect_left(bars, visible_start, key=lambda bar: bar["end_time"][:10])
    return bars[first:], points.iloc[first:].reset_index(drop=True)


def sun_symbol():
    """Возвращает контур восьмилучевого солнышка для метки постоянного размера."""
    from PyQt6.QtGui import QPainterPath

    path = QPainterPath()
    path.moveTo(0.5, 0.0)
    for i in range(1, 16):
        angle = i * pi / 8
        radius = 0.5 if i % 2 == 0 else 0.25
        path.lineTo(radius * cos(angle), radius * sin(angle))
    path.closeSubpath()
    return path


def show_chart(bars, symbol, points, png=None, *, depths, preset, offset):
    """Показывает bars инструмента symbol с метками points или сохраняет PNG по пути png.

    depths содержит глубины слоёв, preset задаёт внешний вид NUF или FXi,
    offset — декоративный отступ в единицах цены.
    """
    def draw_overlay(fplt, axis, x):
        """Рисует метки на ценовой оси axis по номерам баров x через finplot."""
        import pyqtgraph as pg

        axis.vb.v_zoom_scale = 0.92
        sun = sun_symbol()
        fplt.add_legend(f"Семафор · {preset.upper()}", ax=axis)
        for level, (depth, size, label) in enumerate(zip(depths, (7, 12, 21), ("точки", "светики", "солнышки")), 1):
            if not depth:
                continue
            shape = sun if level == 3 or (preset == "nuf" and level == 2) else "o"
            for side, color, sign in (("low", "#008820", -1), ("high", "#df2525", 1)):
                values = points[f"sf{level}_{side}"]
                if not values.notna().any():
                    continue
                if preset == "fxi" and level == 2:
                    color = "#e5b400"
                positions = (values + sign * offset).rename(f"sf{level}_{side}_display")
                item = fplt.plot(x, positions, style="o", color=color, width=size / 7, ax=axis)
                item.setSymbol(shape)
                item.setSymbolPen(pg.mkPen(color, width=0.9))
                item.setDownsampling(auto=False)
                item.setZValue(19 + level)
                if preset == "fxi" and level == 3:
                    center = fplt.plot(x, positions.rename(f"sf{level}_{side}_center"),
                                       style="o", color="#ffe33d", width=6 / 7,
                                       ax=axis, zoomscale=False)
                    center.setDownsampling(auto=False)
                    center.setZValue(24)
            fplt.add_legend(f"СФ {depth} · {label}", ax=axis)

    def read_overlay(index):
        """Возвращает цены меток бара index для курсора, исключая декоративный отступ."""
        bar = points.iloc[index]
        labels = []
        for level, depth in enumerate(depths, 1):
            for side, label in (("low", "низ"), ("high", "верх")):
                value = bar[f"sf{level}_{side}"]
                if isfinite(value):
                    labels.append(f"СФ {depth} {label} {value:.12g}")
        return " · ".join(labels) if labels else "Семафор · —"

    show_delta_chart(bars, symbol, png, title="Дельта-бары и Семафор",
                     draw_overlay=draw_overlay, read_overlay=read_overlay)


def main(argv=None):
    """Разбирает аргументы argv, строит график и возвращает код завершения."""
    parser = argparse.ArgumentParser(description="Дельта-бары Finam с тремя уровнями Семафора")
    parser.add_argument("--symbol", choices=("RTS", "MIX"), default="RTS", help="инструмент (по умолчанию RTS)")
    parser.add_argument("--date", "--end", dest="date", type=date.fromisoformat,
                        help="последний день графика ГГГГ-ММ-ДД (по умолчанию последняя сессия с тиками)")
    parser.add_argument("--start", type=date.fromisoformat, help="первый видимый день графика включительно")
    parser.add_argument("--history-start", type=date.fromisoformat, help="первый день расчёта с учётом скрытой предыстории")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_ROOT, help=f"корень тиковых архивов ({DEFAULT_ROOT})")
    parser.add_argument("--png", type=Path, help="сохранить график в PNG")
    parser.add_argument("--preset", choices=tuple(PRESETS), default="nuf", help="вариант семафора (по умолчанию nuf)")
    parser.add_argument("--depths", type=int, nargs=3, default=DEFAULT_DEPTHS, metavar=("МАЛ", "СРЕД", "СТАРШ"),
                        help="три глубины в барах (по умолчанию 5 12 34, 0 отключает уровень)")
    parser.add_argument("--deviation", type=int, help="допуск в единицах Point (1 у NUF, 5 у FXi)")
    parser.add_argument("--backstep", type=int, help="число прошлых баров для удаления кандидатов (1 у NUF, 3 у FXi)")
    parser.add_argument("--point", type=float, default=1, help="единица цены для Deviation (по умолчанию 1)")
    parser.add_argument("--offset", type=float, help="отступ меток в единицах цены (40 для RTS, 100 для MIX)")
    args = parser.parse_args(argv)

    default_deviation, default_backstep = PRESETS[args.preset]
    offset = OFFSETS[args.symbol] if args.offset is None else args.offset
    try:
        settings = validate_settings(args.depths, default_deviation if args.deviation is None else args.deviation,
                                     default_backstep if args.backstep is None else args.backstep, args.point)
        if not 0 <= offset <= 100000:
            raise ValueError("Отступ должен быть числом от 0 до 100000")
        if args.history_start and args.history_start > (args.start or args.date or date.max):
            raise ValueError("Начало предыстории должно быть не позже начала графика")
        if args.start and args.date and args.start > args.date:
            raise ValueError("Начало графика позже конечной даты")
    except ValueError as exc:
        parser.error(str(exc))

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
