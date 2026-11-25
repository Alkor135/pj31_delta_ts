"""Проверяет автономный запуск графика и построение при локали ru_RU."""

from datetime import date, timedelta
import os
from pathlib import Path
from shutil import copytree, ignore_patterns
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from tests.test_finam_delta_chart import write_session


class StandaloneChartTests(unittest.TestCase):
    def test_entry_points_start_without_neighbor_project(self):
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
        project = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            archives = root / "data_finam_RTS_tick_zip"
            archives.mkdir()
            day = date(2026, 11, 9)
            for offset in range(1, 29):
                previous = day - timedelta(days=offset)
                if previous.weekday() < 5:
                    write_session(archives, previous, [("10:00:00", 100, 1), ("10:06:00", 101, 4)])
            write_session(archives, day, [("10:00:00", 100, 1), ("10:06:00", 101, 1000),
                                          ("10:10:00", 102, 1000), ("10:15:00", 99, 1000)])

            launch = """
import locale
import sys
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from finam_delta_bar_chart.chart import main

def russian_locale():
    return "ru_RU", "cp1251"

locale.getdefaultlocale = russian_locale
if "--png" not in sys.argv:
    app = QApplication([])

    def close_window():
        if any(window.isVisible() and "RTS" in window.windowTitle() for window in app.topLevelWidgets()):
            print("RTS window shown", flush=True)
        app.quit()

    QTimer.singleShot(0, close_window)

result = main(sys.argv[1:])
assert locale.getdefaultlocale is russian_locale
raise SystemExit(result)
"""
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
                    else:
                        self.assertIn("RTS window shown", result.stdout)
