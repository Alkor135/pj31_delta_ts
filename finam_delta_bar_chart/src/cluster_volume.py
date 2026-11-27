r"""Рассчитывает и кэширует максимальный объём по цене каждого дельта-бара.

Суммирует объём сделок по ценам между начальной и конечной строками бара.
Цена максимального объёма и число контрактов сохраняются по дням в
clusters.sqlite3. Запись зависит от содержимого ZIP и границ баров.
Команда ниже запускает график из корня проекта.
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_claster_max_volume --symbol RTS --date 2026-11-11
"""

from collections import defaultdict
from contextlib import closing
from datetime import date
from hashlib import sha256
from itertools import groupby
import json
from pathlib import Path
import sqlite3

from .day_cache import csv_identity
from .delta_core import read_day
from .finam_archives import archive_folder

CACHE_VERSION = "price-volume-v1"


def calculate_clusters(ticks, bars):
    """Возвращает пары (цена, объём) для bars по исходным сделкам дня ticks.

    Границы бара заданы номерами строк с единицы и включаются в расчёт.
    При одинаковом объёме на нескольких ценах выбирается меньшая цена.
    """
    result = []
    for bar in bars:
        first, last = bar["start_row"], bar["end_row"]
        if not 1 <= first <= last <= len(ticks.prices):
            raise ValueError(f"{ticks.day} — границы бара не совпадают с архивом сделок")
        volumes = defaultdict(int)
        for i in range(first - 1, last):
            volumes[ticks.prices[i]] += ticks.volumes[i]
        if sum(volumes.values()) != bar["volume"]:
            raise ValueError(f"{ticks.day} — объём бара изменился. Повторите запуск.")
        result.append(max(volumes.items(), key=lambda cluster: (cluster[1], -cluster[0])))
    return result


def cached_clusters(db, day, signature, count):
    """Возвращает из db число count кластеров дня day с нужной подписью или None."""
    row = db.execute("SELECT levels FROM cluster_days WHERE day=? AND signature=?",
                     (day.isoformat(), signature)).fetchone()
    if row is None:
        return None
    try:
        levels = [(price, volume) for price, volume in json.loads(row[0])]
    except (ValueError, TypeError):
        return None
    return levels if len(levels) == count else None


def load_clusters(input_root, symbol, bars, *, progress=None):
    """Возвращает кластеры в порядке bars для инструмента symbol под input_root.

    Дневная запись обновляется целиком при смене состава ZIP или границ баров.
    progress при задании получает этап, счётчики дней, дату и название операции.
    """
    days = [(date.fromisoformat(day), list(group)) for day, group in
            groupby(bars, key=lambda bar: bar["end_time"][:10])]
    if not days:
        return []

    source = archive_folder(input_root, symbol)
    folder = Path(input_root) / f"delta_bar_finam_{symbol}"
    folder.mkdir(parents=True, exist_ok=True)
    result = []
    hits = 0
    with closing(sqlite3.connect(folder / "clusters.sqlite3", timeout=30)) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS cluster_days (
            day TEXT PRIMARY KEY, signature TEXT NOT NULL, levels TEXT NOT NULL
        )""")
        for done, (day, day_bars) in enumerate(days):
            archive = source / f"{day:%Y%m%d}.zip"
            identity = csv_identity(archive)
            ranges = [(bar["start_row"], bar["end_row"]) for bar in day_bars]
            key = json.dumps((CACHE_VERSION, identity, ranges), separators=(",", ":"))
            signature = sha256(key.encode()).hexdigest()
            levels = cached_clusters(db, day, signature, len(day_bars))
            if progress is not None:
                action = "из кэша" if levels is not None else "расчёт"
                progress("Кластеры", done, len(days), day, action)
            if levels is None:
                ticks = read_day(archive, day)
                if csv_identity(archive) != identity:
                    raise ValueError(f"Архив изменился во время расчёта — {archive}. Повторите запуск.")
                levels = calculate_clusters(ticks, day_bars)
                with db:
                    db.execute("""INSERT INTO cluster_days(day, signature, levels) VALUES(?,?,?)
                        ON CONFLICT(day) DO UPDATE SET signature=excluded.signature, levels=excluded.levels""",
                               (day.isoformat(), signature, json.dumps(levels, separators=(",", ":"))))
            else:
                hits += 1
            result.extend(levels)
    if progress is not None:
        progress("Кластеры", len(days), len(days), days[-1][0], f"готово, из кэша {hits}")
    return result
