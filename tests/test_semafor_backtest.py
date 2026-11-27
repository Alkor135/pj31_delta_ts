r"""Проверяет пошаговый бэктест с семафорами и островами SMA.

Запускает окно Qt без экрана и проверяет доступные индикаторы, откат
семафоров, закрытие отдельных позиций, журнал, легенду, границы дней и счётчик входов.
Также запускает новую точку входа с временными ZIP и скрытым прогревом.
Команда ниже запускается из корня проекта.
    .\.venv\Scripts\python.exe -m unittest tests.test_semafor_backtest -v
"""

import csv
from datetime import date, timedelta
from decimal import Decimal
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from finam_delta_bar_chart.src.backtest import Backtest
from tests.test_finam_delta_chart import write_session
from tests.test_manual_backtest import sample_bars


class SemaforBacktestTests(unittest.TestCase):
    """Проверяет шаги реального окна Qt и доступность индикаторов при торговле."""

    def setUp(self):
        """Подготавливает временный журнал и приложение Qt без экрана."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import pyqtgraph as pg

        self.app = pg.mkQApp()
        self.folder = Path(self.enterContext(TemporaryDirectory()))

    def open_window(self, bars, history=()):
        """Возвращает окно для bars и скрытой истории history, с короткими периодами SMA."""
        from finam_delta_bar_chart.src.backtest_window import BacktestWindow
        from finam_delta_bar_chart.src.semafor_replay import SemaforReplayChart

        session = Backtest(bars, "RTS", self.folder / "semafor.csv")
        def create_chart(active):
            """Создаёт график прогона active с младшим и старшим уровнями одинаковой глубины."""
            return SemaforReplayChart(active, history, settings=dict(
                depths=(3, 0, 3), deviation=0, ma_fast=2, ma_slow=3,
            ), preset="nuf", offset=1)

        window = BacktestWindow(session, chart_factory=create_chart, toggle_legend=True, individual_close=True)
        self.addCleanup(window.close)
        window.show()
        self.app.processEvents()
        return window

    def test_future_extreme_is_revealed_and_reverted_at_the_right_step(self):
        """Проверяет будущую вершину, перенос метки с кольцом и восстановление при откате."""
        template = sample_bars()[0]
        bars = [dict(template, high=high, low=high - 2, close=high - 1, open=high - 1)
                for high in (11, 13, 12, 15, 14, 12, 10, 13, 16, 15)]
        window = self.open_window(bars)
        self.assertTrue(window.chart.points.empty)
        for _ in range(8):
            window.buttons[1].click()
        self.assertEqual(window.chart.points.sf1_high.dropna().to_dict(), {3: 15, 7: 13})
        rings = [ring for field, _, _, ring, _ in window.chart.markers if field == "sf3_high"]
        self.assertEqual(rings[0].getData()[0].tolist(), [3, 7])
        self.assertNotIn("SMA", window.chart._bar_details(8))
        window.buttons[1].click()
        self.assertEqual(window.chart.points.sf1_high.dropna().to_dict(), {3: 15, 8: 16})
        self.assertEqual(rings[0].getData()[0].tolist(), [3, 8])
        window.buttons[0].click()
        self.assertEqual(window.chart.points.sf1_high.dropna().to_dict(), {3: 15, 7: 13})
        self.assertEqual(rings[0].getData()[0].tolist(), [3, 7])

    def test_legend_hides_independently_and_trades_use_existing_journal(self):
        """Скрывает легенду, сверяет график и выполняет покупку с закрытием и записью PnL."""
        history = sample_bars()[:2]
        window = self.open_window(sample_bars(), history)
        chart = window.chart
        self.assertIsNone(chart.volume)
        self.assertNotIn("entry_volume_diff", window.table_fields)
        self.assertTrue(chart.legend.isVisible())
        window.legend_button.click()
        self.assertFalse(chart.legend.isVisible())
        window.buttons[2].click()
        window.buttons[1].click()
        self.assertEqual(chart.points.ma_slow.notna().tolist(), [True])
        self.assertIn("SMA 2/3", chart.last_details.text())
        self.assertNotIn("Объём − среднее", chart.last_details.text())
        self.assertEqual(chart.sma_lines["ma_slow"].xData.tolist(), [0])
        self.assertFalse(chart.legend.isVisible())
        window.legend_button.click()
        self.assertTrue(chart.legend.isVisible())
        window.buttons[4].click()
        self.assertEqual(window.session.realized_pnl, Decimal("2.3"))
        with window.session.path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual((rows[0]["entry_bar"], rows[0]["exit_bar"]), ("1", "2"))
        self.assertEqual(rows[0]["pnl_points"], "2.3")

    def test_day_divider_appears_at_open_and_disappears_on_rewind(self):
        """Проверяет чёрную черту между датами даже до раскрытия первого бара нового дня."""
        from PyQt6.QtCore import Qt
        from pyqtgraph import InfiniteLine

        window = self.open_window(sample_bars())

        def dividers():
            """Возвращает вертикальные разделители в ценовой панели тестового окна."""
            return [item for item in window.chart.price.items if isinstance(item, InfiniteLine)]

        self.assertEqual(dividers(), [])
        window.buttons[1].click()
        self.assertEqual(dividers(), [])
        window.buttons[1].click()
        self.assertEqual(len(dividers()), 1)
        line = dividers()[0]
        self.assertEqual((line.angle, line.value()), (90, 1.5))
        self.assertEqual(line.pen.color().name(), "#000000")
        self.assertEqual(line.pen.widthF(), 3)
        self.assertEqual(line.pen.style(), Qt.PenStyle.SolidLine)
        window.buttons[1].click()
        self.assertEqual(dividers(), [line])
        window.buttons[0].click()
        window.buttons[0].click()
        self.assertEqual(dividers(), [])

    def test_row_button_closes_only_selected_position_and_rewinds(self):
        """Проверяет закрытие второй позиции, запись CSV и возврат кнопки при откате."""
        window = self.open_window(sample_bars())
        window.buttons[2].click()
        window.buttons[3].click()
        window.buttons[1].click()

        button = window.table.cellWidget(1, 0)
        self.assertEqual(button.text(), "Закрыть")
        self.assertTrue(button.isEnabled())
        button.click()

        purchase, sale = window.session.positions
        self.assertIsNone(purchase.exit_bar)
        self.assertEqual((sale.side, sale.exit_bar, sale.exit_price), ("SELL", 2, Decimal("102.4")))
        self.assertEqual(window.session.realized_pnl, Decimal("-2.3"))
        self.assertEqual(window.session.unrealized_pnl, Decimal("2.3"))
        self.assertTrue(window.table.cellWidget(0, 0).isEnabled())
        self.assertIsNone(window.table.cellWidget(1, 0))
        self.assertTrue(window.buttons[4].isEnabled())
        with window.session.path.open(encoding="utf-8-sig", newline="") as stream:
            first, second = list(csv.DictReader(stream))
        self.assertEqual((first["exit_bar"], second["exit_bar"], second["pnl_points"]), ("", "2", "-2.3"))
        self.assertEqual(second["close_sell_rate"], "1.75")

        window.buttons[0].click()
        self.assertIsNone(window.session.positions[1].exit_bar)
        self.assertTrue(window.table.cellWidget(1, 0).isEnabled())
        for _ in range(3):
            window.buttons[1].click()
        self.assertTrue(window.session.finished)
        self.assertFalse(window.table.cellWidget(0, 0).isEnabled())
        self.assertFalse(window.table.cellWidget(1, 0).isEnabled())

    def test_summary_counts_distinct_entry_days_until_entries_are_rewound(self):
        """Сверяет счётчик дат при повторных входах, закрытии и откате сделок."""
        window = self.open_window(sample_bars())
        self.assertIn("Торговых дней с входами: 0", window.summary.text())

        window.buttons[2].click()
        window.buttons[3].click()
        self.assertIn("Торговых дней с входами: 1", window.summary.text())
        window.buttons[1].click()
        window.buttons[4].click()
        self.assertIn("Закрыто: 2", window.summary.text())
        self.assertIn("Торговых дней с входами: 1", window.summary.text())

        window.buttons[1].click()
        self.assertIn("Торговых дней с входами: 1", window.summary.text())
        window.buttons[2].click()
        self.assertIn("Торговых дней с входами: 2", window.summary.text())
        window.buttons[0].click()
        self.assertIn("Торговых дней с входами: 1", window.summary.text())
        window.buttons[0].click()
        window.buttons[0].click()
        self.assertIn("Торговых дней с входами: 0", window.summary.text())

    def test_cli_runs_visible_session_with_hidden_warmup(self):
        """Запускает окно через main и проверяет торговый диапазон и прогретую SMA."""
        from PyQt6.QtCore import QTimer

        from finam_delta_bar_chart.chart_semafor_backtest import main
        from finam_delta_bar_chart.src.backtest_window import BacktestWindow

        day, earlier = date(2026, 11, 9), date(2026, 11, 6)
        archives = self.folder / "data_finam_RTS_tick_zip"
        archives.mkdir()
        for offset in range(1, 33):
            past = earlier - timedelta(days=offset)
            if past.weekday() < 5:
                write_session(archives, past, [("10:00:00", 100, 4), ("10:06:00", 101, 4)])
        write_session(archives, earlier, [("10:00:00", 100, 4), ("10:00:01", 101, 4),
                                          ("10:00:02", 102, 4), ("10:00:03", 103, 4)])
        write_session(archives, day, [("10:00:00", 100, 1), ("10:00:01", 104, 20)])
        journal = self.folder / "cli.csv"
        observed = []

        def inspect_window():
            """Собирает видимые данные и завершает цикл Qt запущенного скрипта."""
            try:
                for window in self.app.topLevelWidgets():
                    if isinstance(window, BacktestWindow) and window.isVisible():
                        opening = window.session.bar_at(0)
                        window.buttons[2].click()
                        close_button = window.table.cellWidget(0, 0)
                        button_text = close_button.text() if close_button else None
                        window.buttons[1].click()
                        observed.append((opening["start_time"][:10], window.session.finished,
                                         window.chart.points.ma_slow.tolist(), window.legend_button.text(),
                                         button_text))
                        break
            finally:
                self.app.quit()

        QTimer.singleShot(0, inspect_window)
        status = main(["--date", str(day), "--history-start", str(earlier),
                       "--input-root", str(self.folder), "--ma-fast", "2", "--ma-slow", "3",
                       "--trades", str(journal)])
        self.assertEqual(status, 0)
        self.assertEqual(observed, [(str(day), True, [103], "Легенда", "Закрыть")])
        with journal.open(encoding="utf-8-sig", newline="") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual((row["entry_bar"], row["entry_time"][:10]), ("1", str(day)))
