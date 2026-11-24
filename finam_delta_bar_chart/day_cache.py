r"""Дневной кэш графика Finam. Хранит в SQLite свечи и индикаторы каждого дня.

Проверяет версию расчёта, ZIP текущего дня и состав будних архивов окна.
Каждый готовый день записывается отдельной транзакцией. Модуль вызывается
из chart.py. Примеры запуска из корня проекта:
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py --symbol RTS --date 2026-11-11
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py --symbol MIX --start 2026-11-09 --date 2026-11-11
"""

from bisect import bisect_left
from contextlib import closing, contextmanager
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from zipfile import ZipFile
import zlib


def csv_identity(path):
    """Возвращает размер и CRC содержимого CSV из каталога ZIP по пути path."""
    with ZipFile(path) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
            raise ValueError(f"{path}: ожидается ровно один CSV внутри ZIP")
        csv = members[0]
        return f"{csv.file_size}/{csv.CRC:08x}"


@contextmanager
def open_cache(input_root, symbol, archives, version):
    """Открывает базу инструмента symbol под input_root для архивов archives и версии version."""
    folder = Path(input_root) / f"delta_bar_finam_{symbol}"
    folder.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(folder / "chart.sqlite3", timeout=30)) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS chart_days (
            day TEXT PRIMARY KEY, history_start TEXT, signature TEXT NOT NULL, bars BLOB NOT NULL
        )""")
        yield DayCache(db, archives, version)


class DayCache:
    """Читает и записывает готовые дни одного инструмента, сверяя зависимости расчёта."""

    def __init__(self, db, archives, version):
        """Запоминает соединение db, соответствие дат путям archives и версию алгоритма version."""
        self.db = db
        self.archives = archives
        self.weekdays = sorted(day for day in archives if day.weekday() < 5)
        self.version = version
        self.identities = {}

    def _identity(self, day):
        """Возвращает идентификатор CSV дня day, читая каталог ZIP один раз за загрузку."""
        if day not in self.identities:
            self.identities[day] = csv_identity(self.archives[day])
        return self.identities[day]

    def read_ticks(self, day, reader):
        """Читает тики дня day функцией reader и проверяет, что источник соответствует подписи."""
        path = self.archives[day]
        expected = self._identity(day)
        ticks = reader(path, day)
        if csv_identity(path) != expected:
            raise ValueError(f"Архив изменился во время расчёта: {path}. Повторите запуск.")
        return ticks

    def _signature(self, day, first):
        """Возвращает подпись дня day и будних ZIP от первой сессии first до day исключительно."""
        digest = sha256(self.version.encode())
        if first is not None:
            left = bisect_left(self.weekdays, first)
            right = bisect_left(self.weekdays, day)
            # Пустой ZIP в этом интервале тоже может получить сделки после обновления.
            for past in self.weekdays[left:right]:
                digest.update(f"|{past}:{self._identity(past)}".encode())
        digest.update(f"|{day}:{self._identity(day)}".encode())
        return digest.hexdigest()

    def get(self, day):
        """Возвращает свечи дня day, пустой список для дня без сделок или None для пересчёта."""
        row = self.db.execute("SELECT history_start, signature, bars FROM chart_days WHERE day=?",
                              (day.isoformat(),)).fetchone()
        if row is None:
            return None
        first, signature, payload = row
        if self._signature(day, date.fromisoformat(first) if first else None) != signature:
            return None
        try:
            return json.loads(zlib.decompress(payload))
        except (ValueError, zlib.error):
            return None

    def save(self, day, first, bars):
        """Атомарно записывает список bars за day и начало окна first, равное None для пустого дня."""
        signature = self._signature(day, first)
        payload = zlib.compress(json.dumps(bars, separators=(",", ":"), allow_nan=False).encode(), level=1)
        with self.db:
            self.db.execute("""INSERT INTO chart_days(day, history_start, signature, bars) VALUES(?,?,?,?)
                ON CONFLICT(day) DO UPDATE SET history_start=excluded.history_start,
                    signature=excluded.signature, bars=excluded.bars""",
                            (day.isoformat(), first.isoformat() if first else None, signature, payload))
