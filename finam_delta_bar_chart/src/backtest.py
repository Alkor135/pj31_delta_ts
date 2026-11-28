r"""Ведёт ручной бэктест Finam от открытия одного дельта-бара до следующего.

Открытые позиции оцениваются по последней раскрытой цене. Дневной PnL
учитывает изменение результата за текущую московскую дату. В CSV сохраняются
сделки, закрытый PnL в пунктах, разница объёмов и две интенсивности при входе,
а также интенсивности покупок и продаж при выходе. Индикаторы берутся с
последнего завершённого бара той же сессии. CSV и таблица используют одну запись на позицию.
Можно закрыть выбранную позицию или все открытые. Перемотка назад отменяет
сделки убранного бара. Подкласс с JSON сохраняет также шаги без сделок.
Команды ниже запускаются из корня проекта.
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py --backtest --symbol RTS --date 2026-11-11
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py --backtest --trades mix.csv --symbol MIX
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor_backtest --symbol MIX --date 2026-11-11
"""

from bisect import bisect_left
import csv
from dataclasses import dataclass, replace
from decimal import Decimal
from itertools import count
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

RESULTS_DIR = Path(__file__).resolve().parent / "backtests"
COLUMNS = ("position_id", "symbol", "side", "entry_bar", "entry_time", "entry_price",
           "exit_bar", "exit_time", "exit_price", "pnl_points",
           "entry_volume_diff", "entry_buy_rate", "entry_sell_rate",
           "close_buy_rate", "close_sell_rate")


@dataclass(frozen=True)
class Position:
    """Хранит вход и выход одного контракта с известными на каждом шаге индикаторами и номерами баров от единицы."""

    side: str
    entry_bar: int
    entry_time: str
    entry_price: Decimal
    exit_bar: int | None = None
    exit_time: str | None = None
    exit_price: Decimal | None = None
    entry_volume_diff: float | None = None
    entry_buy_rate: float | None = None
    entry_sell_rate: float | None = None
    close_buy_rate: float | None = None
    close_sell_rate: float | None = None

    def pnl_at(self, price):
        """Возвращает PnL одного контракта в пунктах при оценке по цене price."""
        return price - self.entry_price if self.side == "BUY" else self.entry_price - price

    @property
    def pnl_points(self):
        """Возвращает результат закрытой позиции в пунктах цены или None для открытой."""
        if self.exit_price is None:
            return None
        return self.pnl_at(self.exit_price)

    def journal_record(self, number, symbol):
        """Возвращает поля позиции для CSV и таблицы с номером number и инструментом symbol."""
        return {"position_id": number, "symbol": symbol, **vars(self), "pnl_points": self.pnl_points}


class Backtest:
    """Связывает видимую историю, позиции и принадлежащий одному прогону CSV."""

    def __init__(self, bars, symbol, path=None):
        """Начинает прогон bars для symbol и создаёт CSV по path либо со свободным именем."""
        self._init_state(bars, symbol, 0, ())
        if path is not None:
            self.path = Path(path).resolve()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._create_file(self.path)
            except FileExistsError as exc:
                raise FileExistsError(f"Файл позиций уже существует: {self.path}. Укажите новое имя.") from exc
        else:
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            name = f"{symbol}_{bars[0]['start_time'][:10]}_{bars[-1]['start_time'][:10]}"
            for number in count(1):
                suffix = "" if number == 1 else f"_{number}"
                self.path = RESULTS_DIR / f"{name}{suffix}.csv"
                try:
                    self._create_file(self.path)
                    break
                except FileExistsError:
                    continue

    def _init_state(self, bars, symbol, cursor, positions):
        """Устанавливает бары, инструмент symbol, шаг cursor и позиции без записи на диск."""
        if not bars:
            raise ValueError("Для бэктеста нужен хотя бы один бар")
        self._bars = bars
        self.symbol = symbol
        self.cursor, self.positions = cursor, positions

    @staticmethod
    def _create_file(path):
        """Резервирует новый файл path и записывает заголовок CSV с кодировкой для Excel."""
        with path.open("x", encoding="utf-8-sig", newline="") as stream:
            csv.writer(stream).writerow(COLUMNS)

    @property
    def journal_status(self):
        """Возвращает текст состояния журнала для строки состояния окна."""
        return str(self.path)

    @property
    def finished(self):
        """Возвращает True после раскрытия последней свечи."""
        return self.cursor == len(self._bars)

    @property
    def realized_pnl(self):
        """Возвращает суммарный результат закрытых позиций в пунктах без комиссий."""
        return sum((p.pnl_points for p in self.positions if p.exit_bar is not None), Decimal(0))

    @property
    def mark_price(self):
        """Возвращает текущее открытие, последнее закрытие в конце диапазона или None до первого бара."""
        if self.cursor < 0:
            return None
        price = self._bars[-1]["close"] if self.finished else self._bars[self.cursor]["open"]
        return Decimal(str(price))

    @property
    def unrealized_pnl(self):
        """Возвращает суммарный PnL открытых позиций по последней видимой цене в пунктах."""
        price = self.mark_price
        if price is None:
            return Decimal(0)
        return sum((p.pnl_at(price) for p in self.positions if p.exit_bar is None), Decimal(0))

    @property
    def daily_pnl(self):
        """Возвращает изменение PnL за московский день текущего шага в пунктах.

        Выходы дня учитываются по цене исполнения, открытые позиции — по
        видимой цене. Для перенесённых позиций отсчёт идёт от закрытия
        предыдущего дня. При откате используются восстановленные сделки.
        """
        price = self.mark_price
        if price is None:
            return Decimal(0)

        index = min(self.cursor, len(self._bars) - 1)
        day = self._bars[index]["start_time"][:10]
        first = bisect_left(self._bars, day, hi=index + 1, key=lambda bar: bar["start_time"][:10])
        previous_close = Decimal(str(self._bars[first - 1]["close"])) if first else None
        total = Decimal(0)
        for position in self.positions:
            # Номера баров в позициях начинаются с единицы.
            if position.exit_bar is not None and position.exit_bar <= first:
                continue
            exit_or_mark = position.exit_price if position.exit_price is not None else price
            total += position.pnl_at(exit_or_mark)
            if position.entry_bar <= first:
                total -= position.pnl_at(previous_close)
        return total

    def bar_at(self, index):
        """Возвращает видимые поля бара index (от нуля) или None за границами открытой истории."""
        if 0 <= index < self.cursor:
            return self._bars[index]
        if index == self.cursor and index >= 0 and not self.finished:
            bar = self._bars[index]
            return {"start_time": bar["start_time"], "open": bar["open"]}
        return None

    def _write_csv(self, positions, *, skip_if_unchanged=False):
        """Атомарно записывает positions в порядке COLUMNS и сверяет старый CSV при skip_if_unchanged."""
        temp = NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="", dir=self.path.parent,
                                  prefix=self.path.name + ".", suffix=".tmp", delete=False)
        try:
            with temp:
                writer = csv.DictWriter(temp, fieldnames=COLUMNS)
                writer.writeheader()
                for number, p in enumerate(positions, start=1):
                    writer.writerow(p.journal_record(number, self.symbol))
            if skip_if_unchanged and self.path.is_file() and self.path.read_bytes() == Path(temp.name).read_bytes():
                return
            os.replace(temp.name, self.path)
        finally:
            Path(temp.name).unlink(missing_ok=True)

    def _commit(self, cursor, positions):
        """Записывает изменившиеся позиции и устанавливает шаг cursor после успешной записи."""
        if positions != self.positions:
            self._write_csv(positions)
            self.positions = positions
        self.cursor = cursor

    def forward(self):
        """Раскрывает текущую свечу и сдвигает курсор к следующему открытию либо к концу."""
        if not self.finished:
            self._commit(self.cursor + 1, self.positions)

    def back(self):
        """Возвращает предыдущее открытие, удаляет входы убранного бара и отменяет его выходы с их индикаторами."""
        if self.cursor < 0:
            return
        positions = self.positions
        if not self.finished:
            removed = self.cursor + 1
            positions = tuple(
                replace(p, exit_bar=None, exit_time=None, exit_price=None,
                        close_buy_rate=None, close_sell_rate=None) if p.exit_bar == removed else p
                for p in self.positions if p.entry_bar != removed
            )
        self._commit(self.cursor - 1, positions)

    def _previous_bar_indicators(self, bar):
        """Возвращает данные предыдущего раскрытого бара той же сессии, что и текущий bar, либо пустой словарь."""
        previous = self.bar_at(self.cursor - 1)
        if previous and previous["end_time"][:10] == bar["start_time"][:10]:
            return previous
        return {}

    def open_position(self, side):
        """Записывает вход side (BUY или SELL) по открытию с разницей объёмов и интенсивностями предыдущего бара."""
        if side not in ("BUY", "SELL"):
            raise ValueError(f"Неизвестное направление позиции: {side}")
        bar = self.bar_at(self.cursor)
        if bar is not None:
            indicators = self._previous_bar_indicators(bar)
            position = Position(side, self.cursor + 1, bar["start_time"], Decimal(str(bar["open"])),
                                entry_volume_diff=indicators.get("volume_diff"),
                                entry_buy_rate=indicators.get("buy_rate"),
                                entry_sell_rate=indicators.get("sell_rate"))
            self._commit(self.cursor, (*self.positions, position))

    def close_all(self):
        """Закрывает открытые позиции по текущему открытию и фиксирует интенсивности предыдущего бара сессии."""
        self._close_positions()

    def close_position(self, row):
        """Закрывает открытую позицию с номером строки row от нуля по текущему открытию."""
        if 0 <= row < len(self.positions):
            self._close_positions(row)

    def _close_positions(self, row=None):
        """Сохраняет выход для открытой позиции row или всех открытых, если row равен None."""
        bar = self.bar_at(self.cursor)
        if bar is None:
            return
        price = Decimal(str(bar["open"]))
        indicators = self._previous_bar_indicators(bar)
        positions = tuple(
            replace(p, exit_bar=self.cursor + 1, exit_time=bar["start_time"], exit_price=price,
                    close_buy_rate=indicators.get("buy_rate"), close_sell_rate=indicators.get("sell_rate"))
            if p.exit_bar is None and (row is None or index == row) else p
            for index, p in enumerate(self.positions)
        )
        if positions != self.positions:
            self._commit(self.cursor, positions)
