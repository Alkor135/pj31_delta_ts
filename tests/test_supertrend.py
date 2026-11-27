r"""Проверяет расчёт и отображение двух линий Supertrend на дельта-барах.

Сверяет уровни с ручным расчётом и запускает экспорт PNG на временных ZIP.
Команда ниже запускает проверку из корня проекта.
    .\.venv\Scripts\python.exe -m unittest tests.test_supertrend -v
"""

from datetime import date, timedelta
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from tests.test_finam_delta_chart import write_session


class SupertrendTests(unittest.TestCase):
    """Проверяет прогрев ATR, смену направления и вывод обеих линий на график."""

    def test_atr_and_trend_changes(self):
        """Сверяет семь баров с ручным расчётом ATR Уайлдера и границ Supertrend."""
        from finam_delta_bar_chart.src.supertrend import calculate_supertrend

        bars = [
            {"high": high, "low": low, "close": close}
            for high, low, close in [
                (11, 9, 10), (11, 9, 10), (14, 12, 14), (15, 13, 14),
                (16, 12, 13), (11, 8, 8), (10, 7, 8),
            ]
        ]
        self.assertEqual(
            calculate_supertrend(bars, 2, 1),
            [None, (12, False), (10, True), (11.5, True),
             (11.5, True), (13.625, False), (12.0625, False)],
        )

    def test_png_draws_both_directions_of_each_supertrend(self):
        """Проверяет четыре цвета линий на ценовой панели PNG из тестовых архивов."""
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
                (f"10:00:{index:02d}", price, 400) for index, price in enumerate(prices)
            ])
            png = root / "supertrend.png"
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "finam_delta_bar_chart.chart_2_supertrend",
                 "--date", str(day), "--input-root", str(root), "--png", str(png),
                 "--fast-period", "2", "--fast-multiplier", "1.5",
                 "--slow-period", "4", "--slow-multiplier", "3"],
                cwd=project, capture_output=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            image = QImage(str(png))
            self.assertFalse(image.isNull())
            missing = {QColor(color).rgb() for color in ("#19a32a", "#e23c36", "#006331", "#951d22")}
            for y in range(50, image.height() * 5 // 6):
                for x in range(70, image.width() - 85, 5):
                    missing.discard(image.pixel(x, y))
                if not missing:
                    break
            self.assertFalse(missing, f"Не найдены цвета линий: {missing}")
