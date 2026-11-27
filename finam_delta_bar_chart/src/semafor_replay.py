r"""Рисует семафоры и острова SMA в ручном бэктесте раскрываемых дельта-баров.

При перемещении курсора рассчитывает индикаторы по скрытой предыстории
и завершённым свечам прогона. На ценовой панели показывает раскрытые метки,
острова и интенсивности. Крупные солнышки обведены синим кольцом.
Границы московских дат отмечены толстыми чёрными линиями.
Команда ниже запускается из корня проекта.
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor_backtest --symbol RTS --date 2026-11-11
"""

from itertools import chain

import numpy as np
import pyqtgraph as pg

from .backtest_window import ReplayChart
from .semafor import DEFAULT_MA_FAST, DEFAULT_MA_SLOW, calculate_semafor
from .semafor_style import (
    FXI_CENTER_COLOUR, ISLAND_COLOURS, LEVEL_STYLES, MARKER_SIDES, RING_COLOUR,
    SMA_COLOURS, marker_style, semafor_details, sun_symbol,
)


class SemaforReplayChart(ReplayChart):
    """Добавляет к ценовой панели бэктеста семафоры и острова SMA."""

    def __init__(self, session, history, *, settings, preset, offset):
        """Задаёт прогон session, предысторию history, настройки settings, пресет и отступ меток."""
        self.history = tuple(history)
        self.settings = settings
        self.preset = preset
        self.offset = offset
        self.completed_count = None
        super().__init__(session, show_volume_diff=False)

    def _setup_overlays(self):
        """Создаёт слои SMA, метки и легенду, подготавливает разделители дат."""
        self.sma_lines = {}
        self.islands = {}
        self.day_dividers = {}
        for direction, colour in ISLAND_COLOURS:
            fill = pg.BarGraphItem(x=[], y0=[], y1=[], width=1, pen=None, brush=pg.mkBrush(colour))
            fill.setZValue(-10)
            self.price.addItem(fill)
            self.islands[direction] = fill
        for name, colour in SMA_COLOURS:
            self.sma_lines[name] = self.price.plot(pen=pg.mkPen(colour, width=1), connect="finite")
        fast = self.settings.get("ma_fast", DEFAULT_MA_FAST)
        slow = self.settings.get("ma_slow", DEFAULT_MA_SLOW)
        self.legend.addItem(self.sma_lines["ma_fast"], f"Острова · SMA {fast}/{slow}")

        self.markers = []
        sun = sun_symbol()
        for level, (depth, (size, label)) in enumerate(zip(self.settings["depths"], LEVEL_STYLES), 1):
            if not depth:
                continue
            for side, _, colour, sign in MARKER_SIDES:
                shape, colour = marker_style(level, self.preset, colour, sun)
                mark = pg.ScatterPlotItem(symbol=shape, size=size, pen=pg.mkPen(colour, width=0.9),
                                          brush=pg.mkBrush(colour))
                mark.setZValue(19 + level)
                self.price.addItem(mark)
                if side == "low":
                    self.legend.addItem(mark, f"СФ {depth} · {label}")
                ring = center = None
                if level == 3:
                    ring = pg.ScatterPlotItem(symbol="o", size=size + 8, pen=pg.mkPen(RING_COLOUR, width=2),
                                              brush=None)
                    ring.setZValue(23)
                    self.price.addItem(ring, ignoreBounds=True)
                    if self.preset == "fxi":
                        center = pg.ScatterPlotItem(symbol="o", size=6, pen=None,
                                                    brush=pg.mkBrush(FXI_CENTER_COLOUR))
                        center.setZValue(24)
                        self.price.addItem(center, ignoreBounds=True)
                self.markers.append((f"sf{level}_{side}", sign, mark, ring, center))

    def step(self):
        """Обновляет индикаторы по завершённым свечам и вызывает обычное обновление графика."""
        count = max(0, self.session.cursor)
        if count != self.completed_count:
            visible = (self.session.bar_at(index) for index in range(count))
            points = calculate_semafor(chain(self.history, visible), **self.settings)
            self.points = points.iloc[len(self.history):].reset_index(drop=True)
            self.completed_count = count
        super().step()

    def _draw_overlays(self, first, stop):
        """Обновляет индикаторы и разделители в интервале first–stop. Возвращает цены для масштаба."""
        self._draw_day_dividers(first, stop)
        points = self.points.iloc[first:stop]
        x = np.arange(first, first + len(points))
        bounds = []
        for name, line in self.sma_lines.items():
            values = points[name].to_numpy()
            line.setData(x, values, connect="finite")
            bounds.extend(values[np.isfinite(values)])
        fast, slow = points.ma_fast.to_numpy(), points.ma_slow.to_numpy()
        directions = points.island_direction.to_numpy()
        for direction, island in self.islands.items():
            mask = directions == direction
            island.setOpts(x=x[mask], y0=slow[mask], y1=fast[mask])
        for field, sign, mark, ring, center in self.markers:
            values = points[field].to_numpy()
            mask = np.isfinite(values)
            positions = values[mask] + sign * self.offset
            mark.setData(x[mask], positions)
            if ring is not None:
                ring.setData(x[mask], positions)
            if center is not None:
                center.setData(x[mask], positions)
            bounds.extend(positions)
        return bounds

    def _draw_day_dividers(self, first, stop):
        """Рисует границы дат от first до stop, включая доступное открытие нового дня."""
        positions = set()
        previous = self.session.bar_at(first - 1)
        for index in range(first, stop + 1):
            bar = self.session.bar_at(index)
            if previous and bar and previous["start_time"][:10] != bar["start_time"][:10]:
                positions.add(index - 0.5)
            previous = bar

        for position in self.day_dividers.keys() - positions:
            self.price.removeItem(self.day_dividers.pop(position))
        for position in positions - self.day_dividers.keys():
            divider = pg.InfiniteLine(pos=position, angle=90, pen=pg.mkPen("#000000", width=3))
            divider.setZValue(25)
            self.price.addItem(divider, ignoreBounds=True)
            self.day_dividers[position] = divider

    def _bar_details(self, index):
        """Добавляет к показаниям завершённого бара index доступные значения SMA и семафоров."""
        details = super()._bar_details(index)
        if 0 <= index < self.completed_count:
            indicators = semafor_details(self.points, index, self.settings["depths"])
            if indicators:
                details += f" · {indicators}"
        return details
