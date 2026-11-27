r"""Проверяет сохранение и продолжение ручного бэктеста по JSON.

Использует временные журналы и детерминированные бары. Сверяет точный шаг,
сделки, защиту от параллельного открытия и восстановление CSV после сбоя.
Команда ниже запускается из корня проекта.
    .\.venv\Scripts\python.exe -m unittest tests.test_backtest_state -v
"""

from contextlib import ExitStack
import csv
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tests.test_manual_backtest import sample_bars


class BacktestStateTests(unittest.TestCase):
    """Проверяет границы диапазона, атомарную запись и восстановление прогона."""

    def setUp(self):
        """Создаёт временные пути для CSV и его JSON-состояния."""
        self.folder = Path(self.enterContext(TemporaryDirectory()))
        self.journal = self.folder / "RTS_semafor.csv"
        self.state_path = self.folder / "RTS_semafor.state.json"

    def new_session(self, resources):
        """Начинает прогон тестовых баров с ресурсами resources."""
        from finam_delta_bar_chart.src.backtest_state import ResumeSettings, SavedBacktest

        config = ResumeSettings(
            "RTS", self.folder, date(2026, 11, 10), date(2026, 11, 11), None, "fxi", 8,
            dict(depths=(3, 4, 0), deviation=5, backstep=3, point=1, ma_fast=2, ma_slow=3),
        )
        return SavedBacktest(sample_bars(), 0, config, resources, path=self.journal)

    def resume_session(self, resources, bars):
        """Возвращает прогон bars, указанный JSON, с ресурсами resources."""
        from finam_delta_bar_chart.src.backtest_state import SavedBacktest, read_saved_run

        saved = read_saved_run(self.state_path, resources)
        return SavedBacktest(bars, 0, saved.config, resources, saved=saved)

    def test_resume_restores_cursor_positions_and_rebuilds_csv(self):
        """Восстанавливает пустой шаг после выхода, цены, позиции и недостающий CSV."""
        with ExitStack() as first:
            session = self.new_session(first)
            session.open_position("BUY")
            session.open_position("SELL")
            session.forward()
            session.close_position(0)
            session.forward()
            expected_positions = session.positions
            expected_csv = self.journal.read_bytes()
            self.assertEqual(session.cursor, 2)
        self.journal.unlink()

        with ExitStack() as second:
            resumed = self.resume_session(second, sample_bars())
            self.assertEqual(resumed.cursor, 2)
            self.assertEqual(resumed.positions, expected_positions)
            self.assertEqual(resumed.realized_pnl, Decimal("2.3"))
            self.assertEqual(resumed.unrealized_pnl, Decimal("0.9"))
            self.assertEqual(self.journal.read_bytes(), expected_csv)
            self.assertEqual(resumed.config.settings["depths"], (3, 4, 0))
            resumed.back()
            resumed.back()
        with ExitStack() as third:
            rewound = self.resume_session(third, sample_bars())
            self.assertEqual(rewound.cursor, 0)
            self.assertTrue(all(position.exit_bar is None for position in rewound.positions))

    def test_state_survives_csv_failure_but_failed_json_does_not_apply_action(self):
        """Сверяет фиксацию сделки при блокировке CSV и отмену шага при сбое JSON."""
        with ExitStack() as first:
            session = self.new_session(first)
            with patch.object(session, "_write_csv", side_effect=PermissionError("CSV занят")):
                session.open_position("BUY")
            self.assertIn("CSV занят", session.journal_status)
            before = self.state_path.read_bytes()
            with patch.object(session, "_write_state", side_effect=OSError("JSON занят")):
                with self.assertRaisesRegex(OSError, "JSON занят"):
                    session.forward()
            self.assertEqual(session.cursor, 0)
            self.assertEqual(self.state_path.read_bytes(), before)

        with ExitStack() as second:
            resumed = self.resume_session(second, sample_bars())
            self.assertEqual((resumed.cursor, len(resumed.positions)), (0, 1))
            with self.journal.open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(next(csv.DictReader(stream))["entry_price"], "100.1")

    def test_resume_refuses_busy_run_and_changed_bars(self):
        """Запрещает второй одновременный запуск и изменение свечей для сохранённого шага."""
        with ExitStack() as first:
            self.new_session(first)
            with ExitStack() as busy, self.assertRaisesRegex(OSError, "уже открыт"):
                self.resume_session(busy, sample_bars())
        changed = sample_bars()
        changed[0]["high"] += 1
        with ExitStack() as second, self.assertRaisesRegex(ValueError, "Свечи.*изменились"):
            self.resume_session(second, changed)
