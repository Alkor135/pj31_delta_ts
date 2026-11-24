"""Проверяет график Finam на дневных ZIP с известными сделками.

Проверяет общее окно из 20 будних сессий для среднего объёма и порога дельты.
Использует выходные, пустой день, одинаковые метки и сделки после времени
сравнения. Проверяет прогресс, повторное чтение из SQLite, продолжение после
остановки и обновление зависимых дней. Архивы и базы создаются во временной папке.
Запуск из корня проекта:
    python -m unittest discover -s tests -p test_finam_delta_chart.py -v
"""

from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import BadZipFile, ZipFile

from finam_delta_bar_chart import chart


def write_session(folder, day, trades):
    """Записывает в folder дневной ZIP за day из троек (время, цена, объём)."""
    content = ["datetime,last,volume"]
    content.extend(f"{day} {time},{price},{size}" for time, price, size in trades)
    with ZipFile(folder / f"{day:%Y%m%d}.zip", "w") as archive:
        archive.writestr("ticks.csv", "\n".join(content))


class ChartTests(unittest.TestCase):
    """Проверяет выбор истории, границы свечей и оба индикатора."""

    def test_tick_alignment_and_rolling_sessions(self):
        """Сверяет объём на закрытиях с историей по будням и проверяет сдвиг окна после понедельника."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "data_finam_RTS_tick_zip"
            folder.mkdir()
            day = date(2026, 11, 9)
            history_volumes = []
            for offset in range(35, 0, -1):
                past = day - timedelta(days=offset)
                trades = []
                if offset != 3:
                    trades = [("10:00:00", 100, offset), ("10:00:02", 101, 2),
                              ("10:00:02", 102, 3), ("10:10:00", 103, 200)]
                    if past.weekday() < 5:
                        history_volumes.append(offset)
                write_session(folder, past, trades)
            trades = [("09:59:59", 100, 3), ("10:00:02", 101, 1000),
                      ("10:00:02", 101, 1000), ("10:00:04", 99, 1)]
            write_session(folder, day, trades)
            tomorrow = day + timedelta(days=1)
            write_session(folder, tomorrow, [("10:00:02", 100, 7)])
            bars = chart.load_chart(root, "RTS", tomorrow, start=day)
            self.assertEqual([bar["daily_volume"] for bar in bars], [1003, 2003, 2004, 7])
            historical = [v + 5 for v in history_volumes[-20:]]
            self.assertEqual([bar["mean_volume"] for bar in bars[:3]], [sum(historical) / 20] * 3)
            self.assertEqual(bars[3]["mean_volume"], (sum(historical[1:]) + 2003) / 20)
            self.assertEqual(bars[0]["buy_rate"], 1 / 3)
            self.assertEqual(bars[1]["buy_rate"], 1)
            self.assertEqual(bars[2]["sell_rate"], 1)
            self.assertEqual(bars[3]["buy_rate"], 0)
            self.assertEqual(bars[3]["sell_rate"], 0)
            self.assertEqual([bar["is_complete"] for bar in bars], [1, 1, 0, 0])

    def test_weekend_bars_use_weekday_history(self):
        """Сверяет порог и среднее при переходе через две торговые выходные сессии."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "data_finam_MIX_tick_zip"
            folder.mkdir()
            day = date(2026, 11, 9)
            for offset in range(32, 0, -1):
                past = day - timedelta(days=offset)
                trades = [("10:00:00", 100, 1), ("10:06:00", 101, 4), ("10:06:01", 100, 1)]
                if past.weekday() >= 5:
                    trades = [("10:00:00", 100, 1)] + [
                        ("10:00:01", price, 100000) for price in (101, 100) * 4
                    ]
                write_session(folder, past, trades)
            write_session(folder, day, [("10:07:00", 100, 4000)])
            write_session(folder, day + timedelta(days=1), [])
            bars = chart.load_chart(root, "MIX", start=day - timedelta(days=2))
            self.assertEqual({bar["end_time"][:10] for bar in bars},
                             {"2026-11-07", "2026-11-08", "2026-11-09"})
            self.assertEqual({bar["threshold"] for bar in bars}, {2})
            # К моменту закрытия выходных баров в каждый будний день прошёл 1 контракт.
            self.assertEqual({bar["mean_volume"] for bar in bars[:-1]}, {1})
            # В 10:07 понедельника берётся полный объём каждого из 20 будних дней.
            self.assertEqual(bars[-1]["mean_volume"], 6)
            self.assertEqual(chart.load_chart(root, "MIX"), [bars[-1]])

    def test_requires_full_history(self):
        """Проверяет, что выходные с тиками не заменяют недостающую буднюю сессию."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "data_finam_RTS_tick_zip"
            folder.mkdir()
            day = date(2026, 11, 9)
            for offset in range(1, 29):
                trades = [] if offset == 3 else [("10:00:00", 100, 1)]
                write_session(folder, day - timedelta(days=offset), trades)
            write_session(folder, day, [("10:00:00", 100, 1)])
            with self.assertRaisesRegex(ValueError, "19 .*20"):
                chart.load_chart(root, "RTS", day)

    def test_progress_counts_sessions_and_archives(self):
        """Проверяет оба этапа на ZIP с выходными, пустым днём и пропущенной датой."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "data_finam_RTS_tick_zip"
            folder.mkdir()
            start = date(2026, 11, 9)
            trades = [("10:00:00", 100, 2)]
            for offset in range(35, 0, -1):
                write_session(folder, start - timedelta(days=offset), [] if offset == 3 else trades)
            end = start + timedelta(days=3)
            write_session(folder, start, trades)
            write_session(folder, start + timedelta(days=1), [])
            write_session(folder, end, trades)
            output = StringIO()
            with patch.object(output, "isatty", return_value=True):
                bars = chart.load_chart(root, "RTS", end, start, progress=chart.ConsoleProgress(output))
        lines = output.getvalue().splitlines()
        self.assertEqual(len(bars), 2)
        self.assertTrue(any("История" in line and "100%" in line and "20/20" in line for line in lines))
        self.assertTrue(any("Диапазон" in line and "0/3" in line and "чтение" in line for line in lines))
        self.assertTrue(any("Диапазон" in line and "2/3" in line and str(end) in line
                            and "расчёт" in line for line in lines))
        self.assertIn("3/3", lines[-1])
        self.assertIn("100%", lines[-1])

    def test_estimate_resets_between_stages(self):
        """Сверяет остаток времени после первой сессии и сброс прогноза при смене этапа."""
        output = StringIO()
        day = date(2026, 11, 9)
        with patch("finam_delta_bar_chart.chart.monotonic", side_effect=[100, 103, 112, 115]):
            progress = chart.ConsoleProgress(output)
            progress("История", 0, 4, day, "чтение")
            progress("История", 1, 4, day, "чтение")
            progress("История", 4, 4, day, "готово")
            progress("Диапазон", 0, 1, day, "расчёт")
        lines = output.getvalue().splitlines()
        self.assertIn("~00:00:09", lines[1])
        self.assertIn("00:00:00", lines[2])
        self.assertIn("--:--:--", lines[-1])


class DayCacheTests(unittest.TestCase):
    """Проверяет дневное сохранение через обычную загрузку графика."""

    def setUp(self):
        """Готовит временную историю RTS с пропущенной пятницей перед выбранным понедельником."""
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.folder = self.root / "data_finam_RTS_tick_zip"
        self.folder.mkdir()
        self.start = date(2026, 11, 9)
        self.end = self.start + timedelta(days=1)
        for offset in range(-35, 2):
            if offset != -3:
                write_session(self.folder, self.start + timedelta(days=offset), [("10:00:00", 100, 1)])

    def test_repeat_and_subset_skip_ticks_and_calibration(self):
        """Полный повтор и открытие одной ранее сохранённой даты возвращают те же поля свечей."""
        bars = chart.load_chart(self.root, "RTS", self.end, self.start)
        self.assertTrue((self.root / "delta_bar_finam_RTS" / "chart.sqlite3").is_file())
        with patch.object(chart, "read_day", side_effect=AssertionError("повторное чтение тиков")), \
             patch.object(chart, "session_bars", side_effect=AssertionError("повторный расчёт")):
            self.assertEqual(chart.load_chart(self.root, "RTS", self.end, self.start), bars)
            self.assertEqual(chart.load_chart(self.root, "RTS"), bars[-1:])

    def test_resume_after_interruption(self):
        """После остановки на второй сессии следующий запуск рассчитывает только её."""
        def interrupt(phase, done, total, day, action):
            """Прерывает расчёт на дате day второго дня диапазона по сообщению progress."""
            if phase == "Диапазон" and day == self.end and action == "расчёт":
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            chart.load_chart(self.root, "RTS", self.end, self.start, progress=interrupt)
        with patch.object(chart, "session_bars", wraps=chart.session_bars) as calculate:
            bars = chart.load_chart(self.root, "RTS", self.end, self.start)
        self.assertEqual([call.args[0].day for call in calculate.call_args_list], [self.end])
        self.assertEqual([b["end_time"][:10] for b in bars], [str(self.start), str(self.end)])

    def test_broken_final_archive_preserves_previous_day(self):
        """Ошибка чтения последнего ZIP диапазона оставляет первый день доступным в кэше."""
        (self.folder / f"{self.end:%Y%m%d}.zip").write_bytes(b"invalid zip")
        with self.assertRaises(BadZipFile):
            chart.load_chart(self.root, "RTS", self.end, self.start)
        with patch.object(chart, "read_day", side_effect=AssertionError("потерян первый день")):
            self.assertEqual(chart.load_chart(self.root, "RTS", self.start)[0]["daily_volume"], 1)

    def test_changes_to_archives_and_membership(self):
        """Изменения, добавление и удаление буднего ZIP обновляют окно, а выходной ZIP независим."""
        chart.load_chart(self.root, "RTS", self.end, self.start)
        friday = self.start - timedelta(days=3)
        write_session(self.folder, friday, [("10:00:00", 100, 21)])
        self.assertEqual(chart.load_chart(self.root, "RTS", self.start)[0]["mean_volume"], 2)
        write_session(self.folder, friday, [("10:00:00", 100, 41)])
        self.assertEqual(chart.load_chart(self.root, "RTS", self.start)[0]["mean_volume"], 3)
        (self.folder / f"{friday:%Y%m%d}.zip").unlink()
        self.assertEqual(chart.load_chart(self.root, "RTS", self.start)[0]["mean_volume"], 1)
        write_session(self.folder, self.start - timedelta(days=1), [("10:00:00", 100, 55)])
        with patch.object(chart, "read_day", side_effect=AssertionError("выходной сбросил кэш")):
            self.assertEqual(chart.load_chart(self.root, "RTS", self.start)[0]["mean_volume"], 1)
        write_session(self.folder, self.start, [("10:00:00", 100, 81)])
        bars = chart.load_chart(self.root, "RTS", self.end, self.start)
        self.assertEqual([b["daily_volume"] for b in bars], [81, 1])
        self.assertEqual([b["mean_volume"] for b in bars], [1, 5])


if __name__ == "__main__":
    unittest.main()
