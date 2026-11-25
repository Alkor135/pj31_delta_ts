"""Проверяет запуск графика из отдельной копии проекта."""

from pathlib import Path
from shutil import copytree, ignore_patterns
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


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
