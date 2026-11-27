r"""Проверяет максимальные объёмы по ценам, их кэш и отображение на графике.

Создаёт временные ZIP Finam, сверяет уровень каждого бара, проверяет
инвалидацию SQLite и наличие синего маркера в экспортированном PNG.
Команда ниже запускается из корня проекта.
    .\.venv\Scripts\python.exe -m unittest tests.test_cluster_volume -v
"""

from datetime import date, timedelta
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from finam_delta_bar_chart.src.delta_core import build_bars, read_day
from tests.test_finam_delta_chart import write_session


class ClusterVolumeTests(unittest.TestCase):
    """Проверяет расчёт по строкам архива, повторное чтение и синие точки в PNG."""

    def test_uses_all_trades_at_each_price_within_bar(self):
        """Сверяет суммирование, одинаковые метки времени, остаток дня и равные объёмы."""
        from finam_delta_bar_chart.src.cluster_volume import calculate_clusters

        day = date(2026, 11, 9)
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            trades = [(100, 4), (101, 8), (100, 4), (100, 4), (100, 4),
                      (100, 6), (101, 10), (102, 5), (101, 5)]
            write_session(folder, day, [("10:00:00", price, volume) for price, volume in trades])
            ticks = read_day(folder / "20261109.zip", day)
            bars = build_bars(ticks, 10)
            self.assertEqual(calculate_clusters(ticks, bars), [(100, 22), (101, 10), (101, 5)])

    def test_cache_reuses_days_and_recalculates_changed_inputs(self):
        """Проверяет отдельную базу MIX и пересчёт при смене границ или данных ZIP."""
        from finam_delta_bar_chart.src.cluster_volume import load_clusters

        day = date(2026, 11, 9)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "data_finam_MIX_tick_zip"
            folder.mkdir()
            trades = [("10:00:00", 100, 3), ("10:00:01", 101, 4), ("10:00:02", 100, 2),
                      ("10:00:03", 100, 3), ("10:00:04", 102, 5)]
            write_session(folder, day, trades)
            archive = folder / "20261109.zip"
            ticks = read_day(archive, day)
            bars = build_bars(ticks, 4)
            expected = [(101, 4), (100, 5), (102, 5)]
            self.assertEqual(load_clusters(root, "MIX", bars), expected)
            self.assertTrue((root / "delta_bar_finam_MIX" / "clusters.sqlite3").is_file())
            with patch("finam_delta_bar_chart.src.cluster_volume.read_day",
                       side_effect=AssertionError("Тики уже рассчитанного дня прочитаны повторно")):
                self.assertEqual(load_clusters(root, "MIX", bars), expected)

            combined = build_bars(ticks, 6)
            self.assertEqual(load_clusters(root, "MIX", combined), [(100, 8)])
            trades[0] = ("10:00:00", 100, 7)
            write_session(folder, day, trades)
            updated = build_bars(read_day(archive, day), 6)
            self.assertEqual(load_clusters(root, "MIX", updated), [(100, 12)])

    def test_png_shows_blue_cluster_marker(self):
        """Запускает скрипт на тестовых архивах и ищет синюю точку на ценовой панели."""
        from PyQt6.QtGui import QColor, QImage

        project = Path(__file__).resolve().parents[1]
        day = date(2026, 11, 9)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "data_finam_RTS_tick_zip"
            folder.mkdir()
            for offset in range(1, 29):
                previous = day - timedelta(days=offset)
                if previous.weekday() < 5:
                    write_session(folder, previous, [("10:00:00", 100, 4), ("10:06:00", 101, 4)])
            write_session(folder, day, [("10:00:00", 100, 3), ("10:00:01", 101, 50),
                                        ("10:00:02", 100, 20), ("10:00:03", 102, 10)])
            png = root / "clusters.png"
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "finam_delta_bar_chart.chart_claster_max_volume",
                 "--date", str(day), "--input-root", str(root), "--png", str(png)],
                cwd=project, capture_output=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "delta_bar_finam_RTS" / "chart.sqlite3").is_file())
            self.assertTrue((root / "delta_bar_finam_RTS" / "clusters.sqlite3").is_file())
            image = QImage(str(png))
            self.assertFalse(image.isNull())
            blue = QColor("#0000ff").rgb()
            self.assertTrue(any(image.pixel(x, y) == blue
                                for y in range(100, image.height() * 5 // 6)
                                for x in range(110, image.width() - 90, 3)))
