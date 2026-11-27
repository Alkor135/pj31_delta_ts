r"""Хранит состояние прогона семафоров в JSON рядом с журналом CSV.

Атомарно сохраняет настройки, контрольную сумму свечей, шаг и позиции.
При продолжении проверяет свечи и восстанавливает CSV из JSON. Блокировка
удерживается до закрытия окна и освобождается при завершении процесса.
Команды ниже запускаются из корня проекта.
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor_backtest --trades MIX_semafor.csv --symbol MIX
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor_backtest --resume MIX_semafor.state.json
"""

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from errno import EACCES, EAGAIN
from hashlib import sha256
import json
from math import isfinite
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .backtest import Backtest, Position
from .semafor import PRESETS, validate_settings

STATE_VERSION = 1


@dataclass(frozen=True)
class ResumeSettings:
    """Хранит источник, разрешённые даты торгового прогона и параметры СФ/SMA."""

    symbol: str
    input_root: Path
    start: date
    end: date
    history_start: date | None
    preset: str
    offset: float
    settings: dict

    def record(self):
        """Возвращает настройки в формате для записи в JSON."""
        return dict(vars(self), input_root=str(self.input_root), start=self.start.isoformat(),
                    end=self.end.isoformat(),
                    history_start=self.history_start.isoformat() if self.history_start else None)

    @classmethod
    def from_record(cls, record):
        """Проверяет словарь record из JSON и возвращает нормализованные настройки прогона."""
        symbol, preset = record["symbol"], record["preset"]
        if symbol not in ("RTS", "MIX") or preset not in PRESETS:
            raise ValueError("неизвестный инструмент или пресет")
        offset = float(record["offset"])
        if not 0 <= offset <= 100000:
            raise ValueError("некорректный отступ семафоров")
        start, end = date.fromisoformat(record["start"]), date.fromisoformat(record["end"])
        history_start = record["history_start"]
        history_start = date.fromisoformat(history_start) if history_start is not None else None
        if start > end or (history_start is not None and history_start > start):
            raise ValueError("некорректный диапазон дат")
        input_root = Path(record["input_root"])
        if not input_root.is_absolute():
            raise ValueError("корень архивов должен быть абсолютным путём")
        settings = validate_settings(**record["settings"])
        return cls(symbol, input_root, start, end, history_start, preset, offset, settings)


@dataclass(frozen=True)
class SavedRun:
    """Хранит проверенные поля JSON до сопоставления с загруженными свечами."""

    state_path: Path
    csv_path: Path
    config: ResumeSettings
    fingerprint: str
    cursor: int
    positions: tuple


@contextmanager
def state_lock(path):
    """Удерживает блокировку прогона path до выхода из контекста."""
    with path.with_name(path.name + ".lock").open("a+b") as stream:
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (EACCES, EAGAIN):
                raise FileExistsError(f"Прогон уже открыт в другом окне — {path}") from exc
            raise
        yield


def bars_fingerprint(bars, first):
    """Возвращает подпись свечей bars по порядку с учётом границы предыстории first."""
    digest = sha256(f"{first}\n".encode())
    for bar in bars:
        digest.update(json.dumps(bar, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def position_from_record(record):
    """Возвращает Position из record, восстанавливая точные десятичные цены."""
    entry = Decimal(record["entry_price"])
    exit_price = record["exit_price"]
    exit_price = Decimal(exit_price) if exit_price is not None else None
    if not entry.is_finite() or (exit_price is not None and not exit_price.is_finite()):
        raise ValueError("некорректная цена позиции")
    position = Position(**dict(record, entry_price=entry, exit_price=exit_price))
    if position.side not in ("BUY", "SELL"):
        raise ValueError("некорректное направление позиции")
    for value in (position.entry_volume_diff, position.entry_buy_rate, position.entry_sell_rate,
                  position.close_buy_rate, position.close_sell_rate):
        if value is not None and (type(value) not in (int, float) or not isfinite(value)):
            raise ValueError("некорректное значение индикатора в позиции")
    return position


def read_saved_run(path, resources):
    """Читает JSON по path и удерживает блокировку в стеке resources до закрытия окна."""
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Файл состояния не найден — {path}")
    with ExitStack() as locked:
        locked.enter_context(state_lock(path))
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if type(saved["version"]) is not int or saved["version"] != STATE_VERSION:
                raise ValueError("неподдерживаемая версия")
            csv_name = saved["csv_name"]
            csv_path = path.with_name(csv_name)
            if csv_path.with_suffix(".state.json") != path:
                raise ValueError("имя журнала не соответствует имени JSON")
            if type(saved["cursor"]) is not int or not isinstance(saved["positions"], list):
                raise ValueError("некорректный шаг или список позиций")
            if not isinstance(saved["bars_sha256"], str):
                raise ValueError("некорректная подпись свечей")
            config = ResumeSettings.from_record(saved["configuration"])
            positions = tuple(position_from_record(record) for record in saved["positions"])
        except (TypeError, KeyError, ValueError, InvalidOperation, OverflowError) as exc:
            raise ValueError(f"Не удалось прочитать состояние {path} — {exc}") from exc
        resources.enter_context(locked.pop_all())
    return SavedRun(path, csv_path, config, saved["bars_sha256"], saved["cursor"], positions)


def matches_opening(bars, number, stamp, price, limit):
    """Проверяет цену и время открытия бара number от единицы в доступных bars до limit."""
    if type(number) is not int or not 1 <= number <= limit:
        return False
    bar = bars[number - 1]
    return stamp == bar["start_time"] and price == Decimal(str(bar["open"]))


class SavedBacktest(Backtest):
    """Сохраняет каждый шаг ручного прогона в JSON и обновляет журнал CSV."""

    def __init__(self, bars, first, config, resources, *, path=None, saved=None):
        """Создаёт прогон bars с границей first и настройками config или восстанавливает saved.

        path задаёт новый CSV. resources держит блокировку прогона до выхода.
        """
        self.config = config
        self._resources = resources
        self._csv_error = None
        self._fingerprint = bars_fingerprint(bars, first)
        visible = bars[first:]
        if saved is None:
            super().__init__(visible, config.symbol, path)
        else:
            self._restore(visible, saved)

    def _create_file(self, path):
        """Резервирует новый журнал path вместе с JSON и удерживает блокировку прогона."""
        state_path = path.with_suffix(".state.json")
        if path.exists() or state_path.exists():
            raise FileExistsError(f"Прогон уже существует — {path}")
        with ExitStack() as locked:
            locked.enter_context(state_lock(state_path))
            if state_path.exists():
                raise FileExistsError(f"Состояние уже существует — {state_path}")
            super()._create_file(path)
            self.state_path = state_path
            try:
                self._write_state(self.cursor, self.positions)
            except BaseException:
                path.unlink(missing_ok=True)
                raise
            self._resources.enter_context(locked.pop_all())

    def _restore(self, bars, saved):
        """Сверяет видимые bars со снимком saved и восстанавливает шаг и архив позиций."""
        if saved.fingerprint != self._fingerprint:
            raise ValueError("Свечи сохранённого прогона изменились. Восстановите исходные данные.")
        if not -1 <= saved.cursor <= len(bars):
            raise ValueError("Сохранённый шаг выходит за пределы диапазона")
        limit = min(saved.cursor + 1, len(bars))
        for position in saved.positions:
            if not matches_opening(bars, position.entry_bar, position.entry_time, position.entry_price, limit):
                raise ValueError("Сохранённый вход не совпадает с открытием бара")
            if position.exit_bar is None:
                if position.exit_time is not None or position.exit_price is not None:
                    raise ValueError("Неполные данные сохранённого выхода")
            elif (type(position.exit_bar) is not int or position.exit_bar < position.entry_bar
                  or not matches_opening(bars, position.exit_bar, position.exit_time, position.exit_price, limit)):
                raise ValueError("Сохранённый выход не совпадает с открытием бара")
        self._init_state(bars, saved.config.symbol, saved.cursor, saved.positions)
        self.path, self.state_path = saved.csv_path, saved.state_path
        self._sync_csv()

    @property
    def journal_status(self):
        """Возвращает пути прогона либо пояснение о не обновившемся CSV."""
        if self._csv_error is not None:
            return f"Состояние сохранено. CSV не обновлён — {self._csv_error}"
        return f"{self.path}   ·   Состояние {self.state_path}"

    def _write_state(self, cursor, positions):
        """Атомарно сохраняет курсор cursor и позиции positions в JSON этого прогона."""
        records = [dict(vars(p), entry_price=str(p.entry_price),
                        exit_price=str(p.exit_price) if p.exit_price is not None else None)
                   for p in positions]
        payload = dict(version=STATE_VERSION, configuration=self.config.record(), csv_name=self.path.name,
                       bars_sha256=self._fingerprint, cursor=cursor, positions=records)
        temp = NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=self.state_path.parent,
                                  prefix=self.state_path.name + ".", suffix=".tmp", delete=False)
        try:
            with temp:
                json.dump(payload, temp, ensure_ascii=False, allow_nan=False, indent=2)
                temp.write("\n")
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(temp.name, self.state_path)
        finally:
            Path(temp.name).unlink(missing_ok=True)

    def _sync_csv(self):
        """Обновляет CSV из сохранённых позиций и запоминает ошибку для повтора."""
        try:
            self._write_csv(self.positions)
        except OSError as exc:
            self._csv_error = exc
        else:
            self._csv_error = None

    def _commit(self, cursor, positions):
        """Сохраняет шаг cursor и позиции в JSON, затем обновляет память и CSV."""
        changed = positions != self.positions
        self._write_state(cursor, positions)
        self.cursor, self.positions = cursor, positions
        if changed or self._csv_error is not None:
            self._sync_csv()
