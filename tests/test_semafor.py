r"""Проверяет семафоры и острова SMA на дельта-барах Finam.

Сверяет известные экстремумы CountZZ, направление и прогрев SMA,
цвета меток FXi и синее кольцо в PNG на временных ZIP.
Команда ниже запускается из корня проекта.
    .\.venv\Scripts\python.exe -m unittest tests.test_semafor -v
"""

from datetime import date, timedelta
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from tests.test_finam_delta_chart import write_session


class SemaforTests(unittest.TestCase):
    """Проверяет перенос экстремумов, простые средние и оформление графика."""

    def test_reference_extrema_and_repainting(self):
        """Сверяет точные позиции вершин и впадин, перенос точки и выключенный уровень."""
        from finam_delta_bar_chart.src.semafor import calculate_semafor

        bars = [{"high": high, "low": high - 2, "close": high - 1}
                for high in (11, 13, 12, 15, 14, 12, 10, 13, 16, 15)]
        points = calculate_semafor(bars, depths=(3, 8, 0), deviation=0)
        self.assertEqual(points.sf1_high.dropna().to_dict(), {3: 15, 8: 16})
        self.assertEqual(points.sf1_low.dropna().to_dict(), {6: 8})
        self.assertEqual(points.sf2_high.dropna().to_dict(), {8: 16})
        self.assertTrue(points[["sf3_high", "sf3_low"]].isna().all().all())
        prefix = calculate_semafor(bars[:8], depths=(3, 8, 0), deviation=0)
        self.assertEqual(prefix.sf1_high.dropna().to_dict(), {3: 15, 7: 13})

    def test_deviation_is_scaled_by_point(self):
        """Сверяет влияние Point на допуск к экстремуму из скользящего окна."""
        from finam_delta_bar_chart.src.semafor import calculate_semafor

        bars = [{"high": low + 4, "low": low, "close": low + 2} for low in range(4)]
        options = dict(depths=(3, 0, 0), deviation=1, backstep=0)
        strict = calculate_semafor(bars, point=1, **options)
        loose = calculate_semafor(bars, point=2, **options)
        self.assertTrue(strict.sf1_low.isna().all())
        self.assertEqual(loose.sf1_low.dropna().to_dict(), {3: 1})

    def test_history_warms_points_without_displaying_earlier_bars(self):
        """Проверяет прогрев точки и SMA при скрытой истории и отсечении будущего архива."""
        from finam_delta_bar_chart.chart_semafor import load_semafor_bars

        day, earlier = date(2026, 11, 9), date(2026, 11, 6)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            archives = root / "data_finam_RTS_tick_zip"
            archives.mkdir()
            for offset in range(1, 33):
                previous = earlier - timedelta(days=offset)
                if previous.weekday() < 5:
                    write_session(archives, previous, [("10:00:00", 100, 4), ("10:06:00", 101, 4)])
            write_session(archives, earlier, [("10:00:00", 100, 4), ("10:00:01", 101, 4),
                                              ("10:00:02", 102, 4), ("10:00:03", 103, 4)])
            write_session(archives, day, [("10:00:00", 100, 1), ("10:00:01", 104, 20)])
            (archives / "20261110.zip").write_bytes(b"broken ZIP")
            settings = dict(depths=(3, 0, 0), deviation=0, ma_fast=2, ma_slow=3)
            bars, points = load_semafor_bars(root, "RTS", day, history_start=earlier, **settings)
            self.assertEqual([bar["close"] for bar in bars], [104])
            self.assertEqual(points.sf1_high.dropna().to_dict(), {0: 104})
            self.assertEqual(points.ma_fast.tolist(), [103.5])
            self.assertEqual(points.ma_slow.tolist(), [103])
            _, cold = load_semafor_bars(root, "RTS", day, **settings)
            self.assertTrue(cold.sf1_high.isna().all())
            self.assertTrue(cold.ma_slow.isna().all())

    def test_island_direction_depends_on_closing_price_averages(self):
        """Сверяет восходящий, совпадающий и нисходящий участки двух SMA."""
        from finam_delta_bar_chart.src.semafor import calculate_semafor

        bars = [{"high": close + 3, "low": close - 1, "close": close} for close in (10, 12, 12, 8)]
        result = calculate_semafor(bars, depths=(0, 0, 0), ma_fast=1, ma_slow=2)
        self.assertEqual(result.ma_fast.tolist(), [10, 12, 12, 8])
        self.assertEqual(result.ma_slow.dropna().tolist(), [11, 12, 10])
        self.assertEqual(result.island_direction.tolist(), [0, 1, 0, -1])

    def test_fxi_markers_and_islands_are_drawn_in_png(self):
        """Находит метки FXi, синий контур и обе заливки между линиями SMA."""
        from PyQt6.QtGui import QColor, QImage

        project = Path(__file__).resolve().parents[1]
        day = date(2026, 11, 9)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            archives = root / "data_finam_RTS_tick_zip"
            archives.mkdir()
            for offset in range(1, 29):
                previous = day - timedelta(days=offset)
                if previous.weekday() < 5:
                    write_session(archives, previous, [("10:00:00", 100, 4), ("10:06:00", 101, 4)])
            prices = list(range(100, 114)) + list(range(112, 89, -1)) + list(range(91, 106))
            write_session(archives, day, [
                (f"10:00:{i:02d}", price, 400) for i, price in enumerate(prices)
            ])
            png = root / "semafor.png"
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "finam_delta_bar_chart.chart_semafor",
                 "--date", str(day), "--input-root", str(root), "--png", str(png),
                 "--preset", "fxi", "--depths", "0", "3", "5", "--offset", "2",
                 "--ma-fast", "3", "--ma-slow", "8"],
                cwd=project, capture_output=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            image = QImage(str(png))
            self.assertFalse(image.isNull())
            # Последние два цвета получаются при наложении заливки на белый фон.
            missing = {QColor(color).rgb() for color in
                       ("#e5b400", "#ffe33d", "#2563eb", "#16803d", "#d54747", "#a3dbb7", "#f9b5b5")}
            for y in range(5, image.height() * 5 // 6):
                for x in range(40, image.width() - 85, 2):
                    missing.discard(image.pixel(x, y))
                if not missing:
                    break
            self.assertFalse(missing, f"В PNG отсутствуют цвета семафоров или островов — {missing}")
