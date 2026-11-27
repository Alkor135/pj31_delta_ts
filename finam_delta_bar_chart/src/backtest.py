r"""Ведёт ручной бэктест Finam от открытия одного дельта-бара до следующего.

Открытые позиции оцениваются по последней раскрытой цене. В CSV сохраняются
сделки, закрытый PnL в пунктах, разница объёмов и две интенсивности при входе,
а также интенсивности покупок и продаж при выходе. Индикаторы берутся с
последнего завершённого бара той же сессии. CSV и таблица используют одну запись на позицию.
Перемотка назад отменяет сделки убранного бара.
Модуль запускается через chart.py, примеры из корня проекта:
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py --backtest --symbol RTS --date 2026-11-11
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py --backtest --trades mix.csv --symbol MIX
"""

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
        if not bars:
            raise ValueError("Для бэктеста нужен хотя бы один бар")
        self._bars = bars
        self.symbol = symbol
        self.cursor = 0
        self.positions = ()
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

    @staticmethod
    def _create_file(path):
        """Резервирует новый файл path и записывает заголовок CSV с кодировкой для Excel."""
        with path.open("x", encoding="utf-8-sig", newline="") as stream:
            csv.writer(stream).writerow(COLUMNS)

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

    def bar_at(self, index):
        """Возвращает видимые поля бара index (от нуля) или None за границами открытой истории."""
        if 0 <= index < self.cursor:
            return self._bars[index]
        if index == self.cursor and index >= 0 and not self.finished:
            bar = self._bars[index]
            return {"start_time": bar["start_time"], "open": bar["open"]}
        return None

    def _save(self, positions):
        """Атомарно записывает поля журнала для позиций positions в порядке COLUMNS и обновляет состояние."""
        temp = NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="", dir=self.path.parent,
                                  prefix=self.path.name + ".", suffix=".tmp", delete=False)
        try:
            with temp:
                writer = csv.DictWriter(temp, fieldnames=COLUMNS)
                writer.writeheader()
                for number, p in enumerate(positions, start=1):
                    writer.writerow(p.journal_record(number, self.symbol))
            os.replace(temp.name, self.path)
        finally:
            Path(temp.name).unlink(missing_ok=True)
        self.positions = positions

    def forward(self):
        """Раскрывает текущую свечу и сдвигает курсор к следующему открытию либо к концу."""
        if not self.finished:
            self.cursor += 1

    def back(self):
        """Возвращает предыдущее открытие, удаляет входы убранного бара и отменяет его выходы с их индикаторами."""
        if self.cursor < 0:
            return
        if not self.finished:
            removed = self.cursor + 1
            positions = tuple(
                replace(p, exit_bar=None, exit_time=None, exit_price=None,
                        close_buy_rate=None, close_sell_rate=None) if p.exit_bar == removed else p
                for p in self.positions if p.entry_bar != removed
            )
            if positions != self.positions:
                self._save(positions)
        self.cursor -= 1

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
            self._save((*self.positions, position))

    def close_all(self):
        """Закрывает открытые позиции по текущему открытию и фиксирует интенсивности предыдущего бара сессии."""
        bar = self.bar_at(self.cursor)
        if bar is None or all(p.exit_bar is not None for p in self.positions):
            return
        price = Decimal(str(bar["open"]))
        indicators = self._previous_bar_indicators(bar)
        self._save(tuple(
            replace(p, exit_bar=self.cursor + 1, exit_time=bar["start_time"], exit_price=price,
                    close_buy_rate=indicators.get("buy_rate"), close_sell_rate=indicators.get("sell_rate"))
            if p.exit_bar is None else p for p in self.positions
        ))
