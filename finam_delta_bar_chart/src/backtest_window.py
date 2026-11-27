r"""Показывает дельта-бары, индикаторы и позиции пошагового бэктеста в окне Qt.

По стрелкам меняет бар или открывает позицию, по C закрывает все позиции.
Окно показывает раскрытые данные, показатели последнего завершённого бара и
бара под курсором, позиции и два вида PnL. Обычный бэктест рисует разницу
объёмов знаковыми столбцами. Бэктест семафоров использует ценовую панель
с дополнительными индикаторами и кнопкой легенды.
Команды ниже запускаются из корня проекта.
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py --backtest --date 2026-11-11
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py --backtest --symbol MIX --trades mix.csv
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor_backtest --symbol RTS --date 2026-11-11
"""

from functools import partial
from math import ceil, floor

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PyQt6.QtWidgets import (QAbstractItemView, QGraphicsProxyWidget, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
                             QPushButton, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

from . import BUY_COLOR, SELL_COLOR, VOLUME_DIFF_LABEL, WINDOW, format_volume_diff
from .backtest import COLUMNS


class TimeAxis(pg.AxisItem):
    """Подписывает видимые бары московским временем, известным на текущем шаге."""

    def __init__(self, session):
        """Привязывает нижнюю ось к доступной истории session."""
        super().__init__("bottom")
        self.session = session

    def tickStrings(self, values, scale, spacing):
        """Возвращает подписи целых номеров из values при масштабе scale и шаге spacing."""
        labels = []
        for value in values:
            index = round(value)
            bar = self.session.bar_at(index) if abs(index - value) < 0.01 else None
            stamp = bar.get("end_time", bar["start_time"]) if bar else ""
            labels.append(stamp[8:10] + "." + stamp[5:7] + "\n" + stamp[11:19] if stamp else "")
        return labels


class BarReadout(QLabel):
    """Показывает показатели бара в одной строке выделенной ширины."""

    def paintEvent(self, event):
        """Рисует текст при событии event, при нехватке ширины сжимает его только по горизонтали."""
        rect = self.contentsRect()
        width = self.fontMetrics().horizontalAdvance(self.text()) + 2
        if width <= rect.width():
            super().paintEvent(event)
            return
        with QPainter(self) as painter:
            painter.setPen(QColor("#263a40"))
            painter.translate(rect.topLeft())
            painter.scale(rect.width() / width, 1)
            painter.drawText(QRectF(0, 0, width, rect.height()), self.alignment(), self.text())


class ReplayChart(pg.GraphicsLayoutWidget):
    """Рисует раскрытую историю, интенсивности и при необходимости разницу объёмов."""

    def __init__(self, session, *, show_volume_diff=True):
        """Создаёт панели прогона session и строку показаний. show_volume_diff включает разницу объёмов."""
        pg.setConfigOptions(background="w", foreground="#263a40")
        super().__init__()
        self.session = session
        self.time_axis = TimeAxis(session)
        self.price = self.addPlot(row=0, col=0, axisItems={} if show_volume_diff else {"bottom": self.time_axis})
        self.volume = None
        self.plots = (self.price,)
        if show_volume_diff:
            self.volume = self.addPlot(row=1, col=0, axisItems={"bottom": self.time_axis})
            self.plots = (self.price, self.volume)
            self.ci.layout.setRowStretchFactor(0, 3)
            self.ci.layout.setRowStretchFactor(1, 1)
            self.price.hideAxis("bottom")
            self.volume.setLabel("left", "Контракты")
            self.volume.showAxis("right")
            self.volume.getAxis("right").setStyle(showValues=False)
            self.volume.setXLink(self.price)
        self.price.setLabel("right", "Цена")
        self.price.setLabel("left", "Сделок/с")
        self.plots[-1].setLabel("bottom", "Московское время")
        self.time_axis.setHeight(60)
        for plot in self.plots:
            plot.getAxis("left").setWidth(82)
            plot.getAxis("right").setWidth(85)
            plot.setMouseEnabled(x=True, y=False)
            plot.disableAutoRange()
            plot.hideButtons()
            plot.showGrid(x=True, y=True, alpha=0.15)

        self.rates = pg.ViewBox(enableMenu=False)
        self.rates.setMouseEnabled(x=False, y=False)
        self.price.scene().addItem(self.rates)
        self.price.getAxis("left").linkToView(self.rates)
        self.rates.setXLink(self.price)
        self.price.vb.sigResized.connect(self._align_rates)
        self._align_rates()
        self.rate_lines = []
        self.volume_bars = []
        self.bodies = []
        self.wicks = []
        self.legend = self.price.addLegend(offset=(5, 4), brush="#ffffffda")
        if self.volume is not None:
            vol_legend = self.volume.addLegend(offset=(5, 4), brush="#ffffffda")
            self.volume.addItem(pg.InfiniteLine(0, angle=0, pen="#9aa7ac"), ignoreBounds=True)
        for color, name, vol_name in (
            (BUY_COLOR, "Покупки", "Выше среднего"),
            (SELL_COLOR, "Продажи", "Ниже среднего"),
        ):
            curve = pg.PlotDataItem(pen=pg.mkPen(color, width=1.4), symbol="o", symbolSize=3,
                                    symbolBrush=color, symbolPen=None)
            self.rates.addItem(curve)
            self.legend.addItem(curve, name)
            self.rate_lines.append(curve)
            if self.volume is not None:
                item = pg.BarGraphItem(x=[], y0=0, height=[], width=0.86, brush=color, pen=None)
                self.volume.addItem(item)
                vol_legend.addItem(item, f"{vol_name} за {WINDOW} будних сессий")
                self.volume_bars.append(item)
            body = pg.BarGraphItem(x=[], y0=[], y1=[], width=0.65, pen=color, brush=color)
            self.price.addItem(body)
            self.bodies.append(body)
            self.wicks.append(self.price.plot(pen=color, connect="pairs"))
        self.open_mark = self.price.plot(pen=pg.mkPen("#2457aa", width=3))
        self._setup_overlays()
        self.last_details, self.hover_details = BarReadout(), BarReadout()
        details = QWidget()
        details.setStyleSheet("background: white; color: #263a40; font-size: 9pt;")
        details.setFixedHeight(24)
        row = QHBoxLayout(details)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(12)
        for label in (self.last_details, self.hover_details):
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
            row.addWidget(label, 1)
        proxy = QGraphicsProxyWidget()
        proxy.setWidget(details)
        self.ci.addItem(proxy, row=len(self.plots), col=0)
        self.hover_point = None
        self.scene().sigMouseMoved.connect(self._hover)
        self.price.setXRange(-2, 25, padding=0)
        self.price.vb.sigXRangeChanged.connect(self.draw_visible)
        self.step()

    def _setup_overlays(self):
        """Создаёт дополнительные индикаторы ценовой панели в специализированном графике."""

    def _draw_overlays(self, first, stop):
        """Возвращает цены дополнительных индикаторов на интервале от first до stop исключительно."""
        return ()

    def _align_rates(self):
        """Совмещает область независимой шкалы интенсивности с областью ценовых свечей."""
        self.rates.setGeometry(self.price.vb.sceneBoundingRect())
        self.rates.linkedViewChanged(self.price.vb, pg.ViewBox.XAxis)

    def step(self):
        """Обновляет постоянные показания и прокручивает текущий бар в поле зрения, сохраняя масштаб."""
        self.time_axis.picture = None
        self.time_axis.update()
        cursor = self.session.cursor
        latest = self._bar_details(cursor - 1)
        self.last_details.setText(f"Последний {latest}" if latest else "Нет завершённых баров")
        left, right = self.price.viewRange()[0]
        if cursor >= 0 and not left + 0.5 <= cursor <= right - 1:
            width = max(8, right - left)
            right = max(width - 2, cursor + max(2, width * 0.10))
            self.price.setXRange(right - width, right, padding=0)
        self.draw_visible()

    def _hover(self, point):
        """Запоминает положение мыши point в координатах сцены и обновляет показания под ней."""
        self.hover_point = point
        self._update_hover()

    def leaveEvent(self, event):
        """Очищает показания курсора при событии выхода мыши event за пределы графика."""
        super().leaveEvent(event)
        self._hover(None)

    def _update_hover(self):
        """Находит бар под неподвижной или движущейся мышью с учётом текущего масштаба и шага."""
        info = ""
        if self.hover_point is not None:
            for plot in self.plots:
                if plot.vb.sceneBoundingRect().contains(self.hover_point):
                    index = round(plot.vb.mapSceneToView(self.hover_point).x())
                    info = self._bar_details(index)
                    break
        self.hover_details.setText(f"Курсор {info}" if info else "")

    def _bar_details(self, index):
        """Возвращает для номера index от нуля раскрытые показания или пустую строку для скрытого бара."""
        bar = self.session.bar_at(index)
        if not bar:
            return ""
        stamp = bar.get("end_time", bar["start_time"])
        if "." in stamp:
            stamp = stamp.rstrip("0").rstrip(".")
        prefix = f"№{index + 1} · {stamp} МСК"
        if "close" not in bar:
            return f"{prefix} · Открытие {bar['open']}"
        details = (f"{prefix} · Δ {bar['delta']:+}/{bar['threshold']} · "
                   f"Пок. {bar['buy_rate']:.2f} · Прод. {bar['sell_rate']:.2f} сд/с")
        if self.volume is not None:
            details += f" · {VOLUME_DIFF_LABEL} {format_volume_diff(bar['volume_diff'])}"
        return details

    def draw_visible(self):
        """Обновляет свечи, шкалы и показания под мышью по раскрытым данным видимого интервала X."""
        left, right = self.price.viewRange()[0]
        first = max(0, floor(left))
        stop = max(first, min(self.session.cursor, ceil(right) + 1))
        x = list(range(first, stop))
        bars = [self.session.bar_at(i) for i in x]
        for rising, body, wick in zip((True, False), self.bodies, self.wicks):
            group = [(i, b) for i, b in zip(x, bars) if (b["close"] >= b["open"]) == rising]
            body.setOpts(x=[i for i, _ in group], y0=[b["open"] for _, b in group],
                         y1=[b["close"] for _, b in group])
            wick.setData(np.repeat([i for i, _ in group], 2),
                         [b[key] for _, b in group for key in ("low", "high")], connect="pairs")
        # Линии интенсивности обрываются на смене московского дня.
        days = [b["end_time"][:10] for b in bars]
        connect = np.zeros(len(x), dtype=bool)
        connect[:-1] = [a == b for a, b in zip(days, days[1:])]
        for line, field in zip(self.rate_lines, ("buy_rate", "sell_rate")):
            line.setData(x, [b[field] for b in bars], connect=connect)
        cursor = self.session.cursor
        current = self.session.bar_at(cursor)
        prices = [b[field] for b in bars for field in ("low", "high")]
        if current and left - 0.5 <= cursor <= right + 0.5:
            price = current["open"]
            self.open_mark.setData([cursor - 0.36, cursor + 0.36], [price, price])
            prices.append(price)
        else:
            self.open_mark.setData([], [])
        prices.extend(self._draw_overlays(first, stop))
        if prices:
            low, high = min(prices), max(prices)
            pad = max((high - low) * 0.06, abs(high) * 0.0001, 0.000001)
            self.price.setYRange(low - pad, high + pad, padding=0)
        else:
            self.price.setYRange(0, 1, padding=0)
        peak_rate = max((max(b["buy_rate"], b["sell_rate"]) for b in bars), default=0)
        self.rates.setYRange(0, max(1, peak_rate * 1.45), padding=0)
        if self.volume is not None:
            differences = [b["volume_diff"] for b in bars]
            for sign, item in zip((1, -1), self.volume_bars):
                group = [(i, value) for i, value in zip(x, differences) if sign * value > 0]
                item.setOpts(x=[i for i, _ in group], height=[value for _, value in group])
            low = min(0, min(differences, default=0))
            high = max(0, max(differences, default=0))
            pad = max(0.05, (high - low) * 0.15) if high > low else 1
            self.volume.setYRange(low - pad, high + pad, padding=0)
        self._update_hover()


class BacktestWindow(QMainWindow):
    """Объединяет управление, график и таблицу с открытым и закрытым PnL в пунктах."""

    def __init__(self, session, *, chart_factory=ReplayChart, toggle_legend=False):
        """Создаёт окно для session с графиком chart_factory и кнопкой легенды при toggle_legend."""
        super().__init__()
        self.session = session
        self.setWindowTitle(f"{session.symbol} · Ручной бэктест")
        self.resize(1280, 830)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        commands = QHBoxLayout()
        layout.addLayout(commands)
        self.buttons = []
        key = Qt.Key
        for title, keys, action in (
            ("← Назад", [key.Key_Left], session.back),
            ("→ Вперёд", [key.Key_Right], session.forward),
            ("↑ Купить", [key.Key_Up], partial(session.open_position, "BUY")),
            ("↓ Продать", [key.Key_Down], partial(session.open_position, "SELL")),
            ("C Закрыть все", [key.Key_C, ord("С")], session.close_all),
        ):
            button = QPushButton(title)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            callback = partial(self.execute, action)
            button.clicked.connect(callback)
            commands.addWidget(button)
            self.buttons.append(button)
            for code in keys:
                shortcut = QShortcut(QKeySequence(code), self)
                shortcut.setAutoRepeat(False)
                shortcut.activated.connect(callback)
        self.chart = chart_factory(session)
        if toggle_legend:
            self.legend_button = QPushButton("Легенда")
            self.legend_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.legend_button.setCheckable(True)
            self.legend_button.setChecked(True)
            self.legend_button.toggled.connect(self.chart.legend.setVisible)
            commands.addWidget(self.legend_button)
        commands.addStretch()
        self.quote = QLabel()
        commands.addWidget(self.quote)
        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter)
        splitter.addWidget(self.chart)
        ledger = QWidget()
        ledger_layout = QVBoxLayout(ledger)
        self.summary = QLabel()
        ledger_layout.addWidget(self.summary)
        headers = {
            "position_id": "№", "symbol": "Инструмент", "side": "Позиция",
            "entry_bar": "Бар входа", "entry_time": "Время входа, МСК", "entry_price": "Цена входа",
            "exit_bar": "Бар выхода", "exit_time": "Время выхода, МСК", "exit_price": "Цена выхода",
            "open_pnl": "Открытый PnL, п.", "pnl_points": "Закрытый PnL, п.",
            "entry_volume_diff": f"{VOLUME_DIFF_LABEL} при входе, контр.",
            "entry_buy_rate": "Покупки при входе, сд/с", "entry_sell_rate": "Продажи при входе, сд/с",
            "close_buy_rate": "Покупки при выходе, сд/с", "close_sell_rate": "Продажи при выходе, сд/с",
        }
        self.table_fields = list(COLUMNS)
        if self.chart.volume is None:
            self.table_fields.remove("entry_volume_diff")
        self.open_pnl_column = self.table_fields.index("pnl_points")
        self.table_fields.insert(self.open_pnl_column, "open_pnl")
        self.table = QTableWidget(0, len(self.table_fields))
        for column, field in enumerate(self.table_fields):
            header = QTableWidgetItem(headers.get(field, field))
            header.setToolTip(field if field != "open_pnl" else "Текущий результат открытой позиции в пунктах")
            self.table.setHorizontalHeaderItem(column, header)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ledger_layout.addWidget(self.table)
        splitter.addWidget(ledger)
        splitter.setSizes([565, 190])
        self.statusBar().showMessage(str(session.path))
        self.refresh_positions()
        self.refresh_pnl()
        self.refresh_cursor()

    def execute(self, action):
        """Выполняет команду action и обновляет оценку позиций после сделки или перемещения курсора."""
        cursor, positions = self.session.cursor, self.session.positions
        try:
            action()
        except OSError as exc:
            self.statusBar().showMessage(f"Не удалось сохранить позиции: {exc}. Повторите действие.")
            return
        self.statusBar().showMessage(str(self.session.path))
        if self.session.positions is not positions:
            self.refresh_positions()
        if self.session.cursor != cursor:
            self.chart.step()
        self.refresh_pnl()
        self.refresh_cursor()

    def refresh_cursor(self):
        """Показывает время и цену доступного открытия и включает применимые команды."""
        session = self.session
        bar = session.bar_at(session.cursor)
        if bar:
            self.quote.setText(f"Бар {session.cursor + 1}  ·  {bar['start_time']} МСК  ·  Открытие {bar['open']}")
        else:
            self.quote.setText("Конец диапазона" if session.finished else "До первого бара")
        enabled = (session.cursor >= 0, not session.finished, bool(bar), bool(bar),
                   bool(bar) and any(p.exit_bar is None for p in session.positions))
        for button, available in zip(self.buttons, enabled):
            button.setEnabled(available)

    def refresh_positions(self):
        """Заполняет таблицу записями журнала, показывая направление по-русски и закрытый PnL со знаком."""
        positions = self.session.positions
        self.table.setRowCount(len(positions))
        for row, p in enumerate(positions):
            values = p.journal_record(row + 1, self.session.symbol)
            values["side"] = "Покупка (BUY)" if p.side == "BUY" else "Продажа (SELL)"
            if values["pnl_points"] is not None:
                values["pnl_points"] = f"{values['pnl_points']:+f}"
            values["open_pnl"] = None
            for column, field in enumerate(self.table_fields):
                value = values[field]
                self.table.setItem(row, column, QTableWidgetItem("—" if value is None else str(value)))
        self.table.scrollToBottom()

    def refresh_pnl(self):
        """Переоценивает открытые строки по видимой цене и выводит оба итога в пунктах."""
        session = self.session
        price = session.mark_price
        opened = 0
        for row, position in enumerate(session.positions):
            if position.exit_bar is None:
                opened += 1
                item = self.table.item(row, self.open_pnl_column)
                item.setText(f"{position.pnl_at(price):+f}" if price is not None else "—")
        self.summary.setText(f"Реализованный PnL: {session.realized_pnl:+f} п.     "
                             f"Нереализованный PnL: {session.unrealized_pnl:+f} п.     "
                             f"Закрыто: {len(session.positions) - opened}     Открыто: {opened}")


def show_backtest(session, *, chart_factory=ReplayChart, toggle_legend=False):
    """Открывает окно session с графиком chart_factory и кнопкой легенды при toggle_legend."""
    app = pg.mkQApp()
    window = BacktestWindow(session, chart_factory=chart_factory, toggle_legend=toggle_legend)
    window.show()
    app.exec()
