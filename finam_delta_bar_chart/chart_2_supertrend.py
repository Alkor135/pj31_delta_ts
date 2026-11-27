r"""Показывает адаптивные дельта-бары Finam с двумя линиями Supertrend.

Загружает свечи RTS или MIX через chart.load_chart с тем же дневным SQLite-кэшем.
Рисует младший и старший Supertrend ступенями на шкале цены, вместе с частотой
покупок и продаж и нижней панелью разницы объёмов. ATR рассчитывается в барах
с начала загруженного диапазона. Цвет каждой линии меняется с направлением тренда.
Открывает интерактивное окно или сохраняет PNG.

Команды ниже запускаются из корня проекта.
    .\.venv\Scripts\python.exe .\finam_delta_bar_chart\chart_2_supertrend.py --symbol RTS --date 2026-11-11
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_2_supertrend --symbol MIX --start 2026-11-09 --date 2026-11-11 --fast-period 8 --fast-multiplier 2 --slow-period 21 --slow-multiplier 4 --png MIX_supertrend.png
"""

import argparse
from datetime import date
from math import isfinite
import os
from pathlib import Path
import sqlite3
import sys
from zipfile import BadZipFile

if __package__:
    from .chart import ConsoleProgress, load_chart
    from .src import BUY_COLOR, SELL_COLOR, VOLUME_DIFF_LABEL, WINDOW, format_volume_diff
    from .src.finam_archives import DEFAULT_ROOT
    from .src.finplot_compat import load_finplot
    from .src.supertrend import calculate_supertrend
else:
    from chart import ConsoleProgress, load_chart
    from src import BUY_COLOR, SELL_COLOR, VOLUME_DIFF_LABEL, WINDOW, format_volume_diff
    from src.finam_archives import DEFAULT_ROOT
    from src.finplot_compat import load_finplot
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
    if png:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    fplt = load_finplot()
    import pandas as pd
    import pyqtgraph as pg
    from PyQt6.QtGui import QFont, QFontDatabase
    from PyQt6.QtWidgets import QApplication

    data = pd.DataFrame(bars)
    data["x"] = range(len(bars))
    closes = data["end_time"].tolist()
    days = data["end_time"].str[:10]
    ends = [i - 0.5 for i in range(1, len(bars)) if closes[i][:10] != closes[i - 1][:10]]
    period = days.iat[0]
    if days.iat[-1] != period:
        period += f" — {days.iat[-1]}"
    fast_levels = calculate_supertrend(bars, *fast)
    slow_levels = calculate_supertrend(bars, *slow)

    class MoscowTimeAxis(pg.AxisItem):
        """Подписывает номера свечей московским временем закрытия."""

        def tickStrings(self, values, scale, spacing):
            """Возвращает подписи делений values для масштаба scale и шага spacing."""
            labels = []
            for value in values:
                index = round(value)
                if 0 <= index < len(closes) and abs(value - index) < 0.01:
                    stamp = closes[index]
                    labels.append(f"{stamp[8:10]}.{stamp[5:7]}\n{stamp[11:19]}")
                else:
                    labels.append("")
            return labels

    def crosshair_info(x, y, xtext, ytext):
        """Возвращает подписи xtext и ytext для (x, y), дополняя время показаниями бара."""
        index = round(x)
        if 0 <= index < len(bars):
            bar = bars[index]
            levels = [f"{point[0]:.2f}" if point is not None else "—"
                      for point in (fast_levels[index], slow_levels[index])]
            remainder = " · остаток дня" if not bar["is_complete"] else ""
            xtext = (
                f"{closes[index]} МСК · Δ {bar['delta']:+} / {bar['threshold']}{remainder}\n"
                f"Покупки {bar['buy_rate']:.2f}, продажи {bar['sell_rate']:.2f} сд/с\n"
                f"{VOLUME_DIFF_LABEL} {format_volume_diff(bar['volume_diff'])} контр.\n"
                f"Supertrend · младший {levels[0]} · старший {levels[1]}"
            )
        return xtext, ytext

    def volume_colors(item, _datasrc, rows):
        """Возвращает группы положительных и отрицательных строк rows с цветами item.

        Параметр _datasrc требуется интерфейсом finplot.
        """
        difference = rows["volume_diff"]
        yield item.rowcolors("bull") + [rows.loc[difference > 0]]
        yield item.rowcolors("bear") + [rows.loc[difference < 0]]

    fplt.background = "#ffffff"
    fplt.odd_plot_background = "#fafbfb"
    fplt.foreground = fplt.legend_text_color = "#263a40"
    fplt.legend_fill_color = "#fffffff0"
    fplt.legend_border_color = "#d2dada"
    fplt.grid_alpha = 0.10
    fplt.candle_bull_color = fplt.candle_bull_body_color = "#19704c"
    fplt.candle_bear_color = fplt.candle_bear_body_color = "#ad313f"
    fplt.axis_height_factor = {0: 5}
    fplt.autoviewrestore(False)
    app = pg.mkQApp()
    if png and sys.platform == "win32":
        font = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf"
        if QFontDatabase.addApplicationFont(str(font)) >= 0:
            app.setFont(QFont("Segoe UI", 9))

    price, volume = fplt.create_plot(f"{symbol} · Дельта-бары и Supertrend · {period}", rows=2)
    fplt.candlestick_ochl(data[["x", "open", "close", "high", "low"]], ax=price)
    plot_supertrend(fplt, price, data.x, slow_levels, SLOW_COLORS, 1.8)
    plot_supertrend(fplt, price, data.x, fast_levels, FAST_COLORS, 1.2)

    rates = price.overlay(scale=0.70, yaxis="linear")
    rates.vb.v_zoom_baseline = 0
    next_in_session = days.eq(days.shift(-1)).to_numpy()
    for field, label, color in (("buy_rate", "Покупки", BUY_COLOR), ("sell_rate", "Продажи", SELL_COLOR)):
        curve = fplt.plot(data.x, data[field], ax=rates, color=color, width=1.3,
                          style="o" if len(bars) == 1 else None, legend=f"{label}, сделок/с")
        if len(bars) > 1:
            curve.setData(curve.xData, curve.yData, connect=next_in_session)
            curve.setFillLevel(0)
            curve.setBrush(pg.mkBrush(color + "24"))

    difference = data["volume_diff"]
    histogram = pd.DataFrame({"x": data.x, "zero": 0, "volume_diff": difference,
                              "bottom": difference.clip(upper=0), "top": difference.clip(lower=0)})
    item = fplt.volume_ocv(histogram, candle_width=0.68, ax=volume, colorfunc=volume_colors)
    item.colors.update(bull_frame=BUY_COLOR, bull_body=BUY_COLOR, bear_frame=SELL_COLOR, bear_body=SELL_COLOR)
    item.resamp = None
    volume.addItem(pg.InfiniteLine(0, angle=0, pen="#9aa7ac"), ignoreBounds=True)
    fplt.add_legend(f"{VOLUME_DIFF_LABEL} за {WINDOW} будних сессий · контракты", ax=volume)
    caption = f"{symbol} · {period}"
    if days.iat[0] == days.iat[-1]:
        caption += f" · порог Δ {bars[-1]['threshold']}"
    fplt.add_legend(caption, ax=price)
    fplt.add_legend(f"Supertrend · младший {fast[0]} × {fast[1]:g} · старший {slow[0]} × {slow[1]:g}", ax=price)
    volume.setAxisItems({"bottom": MoscowTimeAxis(orientation="bottom")})
    volume.getAxis("bottom").setHeight(45)
    for axis in (price, volume):
        axis.getAxis("right").setWidth(75)
        axis.set_visible(xgrid=True, ygrid=True)
        fplt.add_crosshair_info(crosshair_info, ax=axis)
        for x in ends:
            axis.addItem(pg.InfiniteLine(x, angle=90, pen="#9aa7ac"), ignoreBounds=True)

    if png:
        window = price.vb.win
        window.show_maximized = False
        window.resize(1500, 850)
        fplt.show(qt_exec=False)
        QApplication.processEvents()
        if not window.grab().save(str(png), "PNG"):
            raise OSError(f"Не удалось сохранить PNG: {png}")
        fplt.close()
    else:
        fplt.show()


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
