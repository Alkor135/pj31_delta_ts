"""Ищет дневные ZIP с тиками Finam для выбранного инструмента."""

from datetime import datetime
from pathlib import Path

DEFAULT_ROOT = Path(r"C:\data_quote")


def archive_folder(input_root, symbol):
    """Возвращает путь к папке дневных ZIP инструмента symbol под input_root."""
    return Path(input_root) / f"data_finam_{symbol}_tick_zip"


def discover(input_root, symbol, end):
    """Возвращает словарь дат и ZIP под input_root для symbol до end включительно.

    Даты отсортированы по возрастанию. При отсутствии папки ValueError содержит
    её полный путь. Неверная дата в восьмизначном имени файла вызывает ValueError.
    """
    folder = archive_folder(input_root, symbol)
    if not folder.is_dir():
        raise ValueError(f"Не найдена папка исходных тиков: {folder.absolute()}")
    result = {}
    for path in folder.glob("*.zip"):
        if len(path.stem) != 8 or not path.stem.isdigit():
            continue
        day = datetime.strptime(path.stem, "%Y%m%d").date()
        if day <= end:
            result[day] = path
    return dict(sorted(result.items()))
