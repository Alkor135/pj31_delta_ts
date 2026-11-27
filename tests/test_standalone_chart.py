r"""Проверяет автономный запуск графика, окно Qt и экспорт PNG при локали ru_RU.

Запускает график напрямую и как модуль. На временных ZIP проверяет, что
красные столбцы разницы находятся ниже зелёных на нижней панели PNG.
Запуск из корня проекта:
    .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_standalone_chart.py -v
"""

from datetime import date, timedelta
import os
from pathlib import Path
from shutil import copytree, ignore_patterns
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from finam_delta_bar_chart.src import BUY_COLOR, SELL_COLOR
from tests.test_finam_delta_chart import write_session


class StandaloneChartTests(unittest.TestCase):
    """Проверяет запуск без соседнего проекта и отображение знаковой разницы."""

    def test_entry_points_start_without_neighbor_project(self):
        """Проверяет доступность параметров при прямом и модульном запуске отдельной копии."""
        source = Path(__file__).resolve().parents[1] / "finam_delta_bar_chart"
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            chart_folder = root / "project" / source.name
            copytree(source, chart_folder, ignore=ignore_patterns("__pycache__", "*.png"))
            for entry, cwd in (([str(chart_folder / "chart.py")], root),
                               (["-m", "finam_delta_bar_chart.chart"], chart_folder.parent)):
                with self.subTest(entry=entry):
                    result = subprocess.run(
                        [sys.executable, "-E", "-X", "utf8", *entry, "--help"],
                        cwd=cwd, capture_output=True, encoding="utf-8", timeout=20,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("--input-root", result.stdout)

    def test_russian_locale_allows_window_and_png(self):
        """Проверяет окно и цвета знаковых столбцов в PNG при русской локали."""
        project = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            archives = root / "data_finam_RTS_tick_zip"
            archives.mkdir()
            day = date(2026, 11, 9)
            for offset in range(1, 29):
                previous = day - timedelta(days=offset)
                if previous.weekday() < 5:
                    write_session(archives, previous, [("10:00:00", 100, 3000), ("10:06:00", 101, 4)])
            write_session(archives, day, [("10:00:00", 100, 1), ("10:06:00", 101, 1000),
                                          ("10:10:00", 102, 1000), ("10:15:00", 99, 4000)])

            launch = '''
import locale
import sys
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from finam_delta_bar_chart.chart import main

def russian_locale():
    """Возвращает русскую локаль Windows для дочернего процесса."""
    return "ru_RU", "cp1251"

locale.getdefaultlocale = russian_locale
if "--png" not in sys.argv:
    app = QApplication([])

    def close_window():
        """Подтверждает, что окно RTS открыто, и завершает цикл Qt."""
        if any(window.isVisible() and "RTS" in window.windowTitle() for window in app.topLevelWidgets()):
            print("RTS window shown", flush=True)
        app.quit()

    QTimer.singleShot(0, close_window)

result = main(sys.argv[1:])
assert locale.getdefaultlocale is russian_locale
raise SystemExit(result)
'''
            png = root / "RTS.png"
            for options in ([], ["--png", str(png)]):
                with self.subTest(options=options):
                    result = subprocess.run(
                        [sys.executable, "-E", "-X", "utf8", "-c", launch, "--input-root", str(root),
                         "--date", str(day), *options],
                        cwd=project, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                        capture_output=True, encoding="utf-8", timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if options:
                        with png.open("rb") as stream:
                            self.assertEqual(stream.read(8), b"\x89PNG\r\n\x1a\n")
                        from PyQt6.QtGui import QColor, QImage

                        picture = QImage(str(png))
                        positive, negative = QColor(BUY_COLOR).rgb(), QColor(SELL_COLOR).rgb()
                        rows = {positive: set(), negative: set()}
                        for y in range(picture.height() * 2 // 3, picture.height() - 45, 3):
                            for x in range(40, picture.width() - 80, 4):
                                pixel = picture.pixel(x, y)
                                if pixel in rows:
                                    rows[pixel].add(y)
                        self.assertTrue(rows[positive])
                        self.assertTrue(rows[negative])
                        self.assertLessEqual(max(rows[positive]), min(rows[negative]))
                    else:
                        self.assertIn("RTS window shown", result.stdout)
