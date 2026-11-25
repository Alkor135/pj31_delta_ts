r"""Проверяет пошаговый график, клавиши, индикаторы входа и выхода в CSV и оба вида PnL.

Использует бары с совпадающими временами и дробными ценами, временный CSV
и окно Qt без экрана. Сверяет все поля таблицы позиций с CSV и общую строку последнего бара и бара под
курсором, включая отклонение объёма от среднего. Запуск из корня проекта:
    .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_manual_backtest.py -v
"""

import csv
from datetime import date, timedelta
from decimal import Decimal
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from finam_delta_bar_chart import chart
from finam_delta_bar_chart.src import backtest
from tests.test_finam_delta_chart import write_session


def sample_bars():
    """Возвращает три бара с разными ценами и индикаторами и одинаковыми метками первых двух баров."""
    samples = [("2026-11-10", 100.1, 30, 21.5, 0, 1.75),
               ("2026-11-10", 102.4, 73, 56, 7, 2),
               ("2026-11-11", 99.2, 18, 11, 3, 1)]
    return [dict(start_time=day + " 10:00:00", end_time=day + " 10:00:00", open=price,
                 close=price + 1, high=price + 5, low=price - 2, daily_volume=volume,
                 mean_volume=mean, buy_rate=buy, sell_rate=sell, threshold=10, delta=10, is_complete=1)
            for day, price, volume, mean, buy, sell in samples]


class BacktestTests(unittest.TestCase):
    """Проверяет историю, сделки и согласованность состояния с файлом позиций."""

    def setUp(self):
        """Создаёт новый прогон и путь к его журналу во временной папке."""
        self.folder = self.enterContext(TemporaryDirectory())
        self.path = Path(self.folder) / "positions.csv"
        self.session = backtest.Backtest(sample_bars(), "RTS", self.path)

    def rows(self):
        """Читает сохранённые позиции из CSV текущего прогона."""
        with self.path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_only_open_is_visible_and_last_close_cannot_be_traded(self):
        """Проверяет видимые поля и границы, включая возврат с конца к открытию последнего бара."""
        session = self.session
        opening = {"start_time": "2026-11-10 10:00:00", "open": 100.1}
        self.assertEqual(session.bar_at(0), opening)
        session.open_position("BUY")
        session.back()
        session.back()
        session.open_position("SELL")
        self.assertIsNone(session.bar_at(0))
        self.assertIsNone(session.bar_at(-1))
        self.assertEqual(self.rows(), [])
        session.forward()
        self.assertIsNone(session.bar_at(1))
        self.assertIsNone(session.bar_at(-1))
        session.forward()
        self.assertEqual(session.bar_at(0)["high"], 105.1)
        self.assertNotIn("buy_rate", session.bar_at(1))
        session.back()
        self.assertEqual(session.bar_at(0), opening)
        for _ in range(3):
            session.forward()
        session.back()
        session.open_position("BUY")
        session.forward()
        session.forward()
        session.open_position("SELL")
        session.close_all()
        self.assertEqual(session.cursor, 3)
        self.assertEqual(session.bar_at(2)["buy_rate"], 3)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["exit_bar"], "")
        session.back()
        self.assertEqual(self.rows()[0]["entry_bar"], "3")
        self.assertNotIn("close", session.bar_at(2))

    def test_closed_pnl_and_undo_on_identical_timestamps(self):
        """Сверяет прибыль, убыток, общий PnL и восстановление после отката двух баров."""
        session = self.session
        session.open_position("BUY")
        session.open_position("BUY")
        session.open_position("SELL")
        session.forward()
        session.open_position("SELL")
        session.close_all()
        session.open_position("BUY")
        rows = self.rows()
        self.assertEqual([row["pnl_points"] for row in rows], ["2.3", "2.3", "-2.3", "0.0", ""])
        self.assertEqual(rows[0]["entry_time"], rows[0]["exit_time"])
        self.assertEqual((rows[0]["exit_bar"], rows[0]["exit_price"]), ("2", "102.4"))
        self.assertEqual(session.realized_pnl, Decimal("2.3"))
        session.forward()
        session.close_all()
        self.assertEqual(session.realized_pnl, Decimal("-0.9"))
        session.back()
        self.assertEqual(session.realized_pnl, Decimal("2.3"))
        session.back()
        self.assertEqual(len(self.rows()), 3)
        self.assertTrue(all(row["exit_time"] == row["pnl_points"] == "" for row in self.rows()))
        self.assertEqual(session.realized_pnl, 0)
        session.forward()
        self.assertEqual(len(self.rows()), 3)
        self.assertTrue(all(row["exit_bar"] == "" for row in self.rows()))

    def test_failed_save_leaves_trades_cursor_and_previous_file_intact(self):
        """Имитирует занятый CSV при откате и проверяет повтор операции после освобождения файла."""
        session = self.session
        session.forward()
        session.open_position("SELL")
        original = self.path.read_bytes()
        with patch("os.replace", side_effect=PermissionError("Файл занят")), self.assertRaises(OSError):
            session.back()
        self.assertEqual(session.cursor, 1)
        self.assertEqual(len(session.positions), 1)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        session.back()
        self.assertEqual(self.rows(), [])

    def test_csv_snapshots_last_revealed_indicators_in_same_session(self):
        """Проверяет четыре поля при входе, закрытии и откате, включая первый бар новой сессии."""
        fields = ("entry_daily_volume", "entry_mean_volume", "entry_buy_rate", "entry_sell_rate")
        session = self.session
        session.open_position("BUY")
        first = self.rows()[0]
        self.assertEqual(tuple(first)[-6:], (*fields, "close_buy_rate", "close_sell_rate"))
        self.assertEqual([first[key] for key in fields], [""] * 4)
        session.forward()
        session.open_position("SELL")
        expected = ["30", "21.5", "0", "1.75"]
        self.assertEqual([self.rows()[1][key] for key in fields], expected)
        session.forward()
        session.open_position("BUY")
        session.close_all()
        rows = self.rows()
        self.assertEqual([rows[1][key] for key in fields], expected)
        self.assertEqual([rows[2][key] for key in fields], [""] * 4)
        session.back()
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual([rows[1][key] for key in fields], expected)
        self.assertEqual(rows[1]["exit_price"], "")

    def test_csv_close_rates_follow_exit_and_rewind(self):
        """Сверяет интенсивности при общем выходе, его отмене и повторном закрытии в новой сессии."""
        session = self.session
        session.open_position("BUY")
        session.open_position("SELL")
        for row in self.rows():
            self.assertEqual((row["close_buy_rate"], row["close_sell_rate"]), ("", ""))
        session.forward()
        session.close_all()
        for row in self.rows():
            self.assertEqual((row["close_buy_rate"], row["close_sell_rate"]), ("0", "1.75"))
            self.assertEqual((row["entry_buy_rate"], row["entry_sell_rate"]), ("", ""))
        session.open_position("BUY")
        session.forward()
        session.close_all()
        first, second, third = self.rows()
        for row in (first, second):
            self.assertEqual((row["close_buy_rate"], row["close_sell_rate"]), ("0", "1.75"))
        self.assertEqual((third["exit_bar"], third["close_buy_rate"], third["close_sell_rate"]), ("3", "", ""))
        session.back()
        session.back()
        for row in self.rows():
            self.assertEqual((row["exit_bar"], row["close_buy_rate"], row["close_sell_rate"]), ("", "", ""))
        session.forward()
        session.forward()
        session.close_all()
        for row in self.rows():
            self.assertEqual((row["exit_bar"], row["close_buy_rate"], row["close_sell_rate"]), ("3", "", ""))

    def test_unrealized_pnl_uses_visible_open_and_final_close(self):
        """Сверяет переоценку покупки и продажи при смене цены, конце диапазона, закрытии и откате."""
        session = self.session
        session.back()
        self.assertIsNone(session.mark_price)
        self.assertEqual(session.unrealized_pnl, 0)
        session.forward()
        session.open_position("BUY")
        self.assertEqual(session.unrealized_pnl, 0)
        session.forward()
        session.open_position("SELL")
        session.open_position("SELL")
        original = self.path.read_bytes()
        self.assertEqual(session.unrealized_pnl, Decimal("2.3"))
        session.forward()
        self.assertEqual(session.unrealized_pnl, Decimal("5.5"))
        session.forward()
        self.assertEqual(session.mark_price, Decimal("100.2"))
        self.assertEqual(session.unrealized_pnl, Decimal("4.5"))
        self.assertEqual(session.realized_pnl, 0)
        self.assertEqual(self.path.read_bytes(), original)
        session.back()
        session.close_all()
        self.assertEqual(session.realized_pnl, Decimal("5.5"))
        self.assertEqual(session.unrealized_pnl, 0)
        session.back()
        self.assertEqual(session.realized_pnl, 0)
        self.assertEqual(session.unrealized_pnl, Decimal("2.3"))

    def test_preserves_existing_journal(self):
        """Проверяет защиту указанного файла и независимость автоматических имён двух прогонов."""
        self.session.open_position("SELL")
        with self.assertRaises(FileExistsError):
            backtest.Backtest(sample_bars(), "RTS", self.path)
        self.assertEqual(self.rows()[0]["side"], "SELL")
        with patch.object(backtest, "RESULTS_DIR", Path(self.folder)):
            first = backtest.Backtest(sample_bars(), "MIX")
            second = backtest.Backtest(sample_bars(), "MIX")
        self.assertNotEqual(first.path, second.path)
        self.assertTrue(first.path.is_file() and second.path.is_file())

    def test_script_entry_reaches_local_backtest(self):
        """Проверяет загрузку бэктеста из src при прямом и модульном запуске после расчёта ZIP."""
        root = Path(self.folder)
        folder = root / "data_finam_RTS_tick_zip"
        folder.mkdir()
        day = date(2026, 11, 11)
        for offset in range(35):
            past = day - timedelta(days=offset)
            if past.weekday() < 5:
                write_session(folder, past, [("10:00:00", 100, 1), ("10:01:00", 104, 1)])
        self.session.open_position("BUY")
        script = Path(chart.__file__).resolve()
        for entry, cwd in (([str(script)], root),
                           (["-m", "finam_delta_bar_chart.chart"], script.parents[1])):
            with self.subTest(entry=entry):
                result = subprocess.run(
                    [sys.executable, "-E", "-X", "utf8", *entry, "--backtest", "--date", str(day),
                     "--input-root", str(root), "--trades", str(self.path)],
                    cwd=cwd, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                    capture_output=True, encoding="utf-8", timeout=20,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("Файл позиций уже существует", result.stderr)
        self.assertEqual(self.rows()[0]["entry_price"], "100.1")

    def test_last_and_hovered_bar_share_one_row(self):
        """Проверяет однострочные показания при наведении, перемотке, раскрытии последнего бара и откате."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtCore import QEvent, QPointF, Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from finam_delta_bar_chart.src.backtest_window import BacktestWindow

        app = QApplication.instance() or QApplication([])
        bars = sample_bars()
        bars[1]["mean_volume"] = 80.25
        window = BacktestWindow(backtest.Backtest(bars, "RTS", Path(self.folder) / "readout.csv"))
        self.addCleanup(window.close)
        window.show()
        window.activateWindow()
        app.processEvents()
        chart = window.chart
        latest, hovered = chart.last_details, chart.hover_details
        self.assertNotIn("Δ", latest.text())
        initial_height = chart.price.height()
        QTest.keyClick(window, Qt.Key.Key_Right)
        QTest.keyClick(window, Qt.Key.Key_Right)
        self.assertIn("№2", latest.text())
        for value in ("2026-11-10 10:00:00 МСК", "Δ +10/10", "Пок. 7.00", "Прод. 2.00", "Объём − среднее −7.25"):
            self.assertIn(value, latest.text())
        for pane in (chart.price, chart.volume):
            point = pane.vb.mapViewToScene(QPointF(0, sum(pane.viewRange()[1]) / 2))
            chart.scene().sigMouseMoved.emit(point)
            self.assertIn("№1", hovered.text())
            self.assertIn("Объём − среднее +8.5", hovered.text())
            self.assertIn("№2", latest.text())
        app.processEvents()
        self.assertAlmostEqual(chart.price.height(), initial_height, delta=1)
        self.assertEqual(latest.mapToGlobal(latest.rect().topLeft()).y(),
                         hovered.mapToGlobal(hovered.rect().topLeft()).y())
        chart.scene().sigMouseMoved.emit(chart.price.vb.mapViewToScene(QPointF(2, 101)))
        self.assertIn("99.2", hovered.text())
        self.assertNotIn("Δ", hovered.text())
        QTest.keyClick(window, Qt.Key.Key_Right)
        self.assertIn("№3", latest.text())
        self.assertIn("+7", latest.text())
        QTest.keyClick(window, Qt.Key.Key_Left)
        self.assertIn("№2", latest.text())
        self.assertNotIn("Δ", hovered.text())
        QApplication.sendEvent(chart, QEvent(QEvent.Type.Leave))
        self.assertEqual(hovered.text(), "")
        self.assertIn("№2", latest.text())
        QTest.keyClick(window, Qt.Key.Key_Left)
        QTest.keyClick(window, Qt.Key.Key_Left)
        self.assertNotIn("Δ", latest.text())

    def test_position_table_matches_csv_on_entry_close_and_rewind(self):
        """Сверяет каждую ячейку журнала в окне с CSV при входе, общем закрытии и отмене выхода."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from finam_delta_bar_chart.src.backtest_window import BacktestWindow

        app = QApplication.instance() or QApplication([])
        session = self.session
        window = BacktestWindow(session)
        self.addCleanup(window.close)
        table = window.table
        window.buttons[2].click()
        window.execute(session.forward)
        window.buttons[3].click()
        for stage in ("вход", "закрытие", "откат"):
            if stage == "закрытие":
                window.execute(session.close_all)
            elif stage == "откат":
                window.execute(session.back)
            rows = self.rows()
            columns = {table.horizontalHeaderItem(i).toolTip(): i for i in range(table.columnCount())}
            self.assertEqual(table.columnCount(), len(rows[0]) + 1)
            self.assertEqual(table.rowCount(), len(rows))
            for row_number, record in enumerate(rows):
                for field, raw in record.items():
                    with self.subTest(stage=stage, row=row_number, field=field):
                        self.assertIn(field, columns)
                        shown = table.item(row_number, columns[field]).text()
                        if field == "side":
                            self.assertIn(raw, shown)
                        elif field == "pnl_points" and raw:
                            self.assertEqual(shown, f"{Decimal(raw):+f}")
                        else:
                            self.assertEqual(shown, raw or "—")

    def test_window_keys_update_plot_table_and_total(self):
        """Посылает клавиши окну и сверяет бары, индикаторы, открытый и закрытый PnL при перемотке."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from finam_delta_bar_chart.src.backtest_window import BacktestWindow

        app = QApplication.instance() or QApplication([])
        window = BacktestWindow(self.session)
        self.addCleanup(window.close)
        window.show()
        window.activateWindow()
        app.processEvents()
        key = Qt.Key
        self.assertEqual(len(window.chart.volume_bars[0].opts["x"]), 0)
        QTest.keyClick(window, key.Key_Up)
        QTest.keyClick(window, key.Key_Right)
        self.assertIn("Нереализованный PnL: +2.3", window.summary.text())
        headers = [window.table.horizontalHeaderItem(i).text() for i in range(window.table.columnCount())]
        open_col = headers.index("Открытый PnL, п.")
        closed_col = headers.index("Закрытый PnL, п.")
        self.assertEqual(window.table.item(0, open_col).text(), "+2.3")
        QTest.keyClick(window, key.Key_Down)
        QTest.keyClick(window, key.Key_Right)
        self.assertEqual(window.table.item(0, open_col).text(), "-0.9")
        self.assertEqual(window.table.item(1, open_col).text(), "+3.2")
        QTest.keyClick(window, key.Key_Left)
        QTest.keyClick(window, key.Key_C)
        self.assertEqual(window.table.item(0, open_col).text(), "—")
        self.assertIn("Нереализованный PnL: +0", window.summary.text())
        self.assertEqual(window.table.rowCount(), 2)
        self.assertIn("+2.3", window.summary.text())
        self.assertEqual(window.table.item(0, closed_col).text(), "+2.3")
        self.assertEqual(list(window.chart.volume_bars[0].opts["x"]), [0])
        self.assertEqual(list(window.chart.rate_lines[0].xData), [0])
        QTest.keyClick(window, key.Key_Left)
        self.assertEqual(window.table.rowCount(), 1)
        self.assertNotIn("+2.3", window.summary.text())
        self.assertEqual(len(window.chart.volume_bars[0].opts["x"]), 0)
        self.assertIsNone(window.chart.rate_lines[0].xData)
        self.assertEqual(self.rows()[0]["pnl_points"], "")
