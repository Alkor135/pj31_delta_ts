r"""Строит окно дельта-баров с подключаемым индикатором на ценовой панели.

Рисует свечи, интенсивности сделок и разницу объёмов, добавляет индикатор
и его показания у курсора. Использует те же панели при сохранении PNG.
Команды ниже запускаются из корня проекта.
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_claster_max_volume --symbol RTS --date 2026-11-11
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_2_supertrend --symbol MIX --date 2026-11-11 --png MIX_supertrend.png
"""

import os
from pathlib import Path
import sys

from . import BUY_COLOR, SELL_COLOR, VOLUME_DIFF_LABEL, WINDOW, format_volume_diff
from .finplot_compat import load_finplot


def show_delta_chart(bars, symbol, png=None, *, title, draw_overlay, read_overlay):
    """Показывает bars инструмента symbol с заголовком title или сохраняет PNG по пути png.

    draw_overlay получает finplot, ценовую ось и порядковые номера баров.
    read_overlay возвращает строку показаний индикатора по номеру бара с нуля.
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
        """Дополняет подписи курсора xtext и ytext в точке (x, y) показаниями бара."""
        index = round(x)
        if 0 <= index < len(bars):
            bar = bars[index]
            remainder = " · остаток дня" if not bar["is_complete"] else ""
            xtext = (
                f"{closes[index]} МСК · Δ {bar['delta']:+} / {bar['threshold']}{remainder}\n"
                f"Покупки {bar['buy_rate']:.2f}, продажи {bar['sell_rate']:.2f} сд/с\n"
                f"{VOLUME_DIFF_LABEL} {format_volume_diff(bar['volume_diff'])} контр.\n"
                f"{read_overlay(index)}"
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

    price, volume = fplt.create_plot(f"{symbol} · {title} · {period}", rows=2)
    fplt.candlestick_ochl(data[["x", "open", "close", "high", "low"]], ax=price)
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
    draw_overlay(fplt, price, data.x)
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
