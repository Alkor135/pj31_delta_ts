r"""Строит график адаптивных дельта-баров из дневных тиков Finam RTS или MIX.

Заимствует чтение ZIP, подбор порога и построение OHLC из соседнего проекта
pj24_delta_bars. На свечи накладывает частоту направленных сделок. Под свечами
сравнивает накопленный объём со средним к тому же времени. Для среднего объёма
и порога дельты берёт одни и те же 20 предыдущих будних сессий со сделками.
Каждая рассчитанная сессия сохраняется в delta_bar_finam_RTS/chart.sqlite3 или
delta_bar_finam_MIX/chart.sqlite3 под корнем архивов. Повторный запуск читает
готовые дни из базы. Консоль показывает ход загрузки. Даты указаны по Москве.
В режиме --backtest раскрывает бары по одному, сохраняет в CSV позиции
и индикаторы на входе, показывает открытый и закрытый PnL в пунктах без комиссий.

Примеры из корня pj31_delta_ts с локальным окружением .venv:
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py --symbol MIX --date 2026-11-11
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py --start 2026-11-09 --date 2026-11-11
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py --start 2016-11-09 --date 2026-11-11
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py --input-root C:\data_quote --png RTS.png
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py --backtest --symbol RTS --date 2026-11-11
    .\.venv\Scripts\python.exe finam_delta_bar_chart\chart.py --backtest --symbol MIX --trades mix.csv
"""

import argparse
from array import array
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from itertools import accumulate
from math import ceil
import os
from pathlib import Path
import sqlite3
import sys
from time import monotonic
from zipfile import BadZipFile

ENGINE_ROOT = Path(__file__).resolve().parents[2] / "pj24_delta_bars"
if not (ENGINE_ROOT / "source" / "delta_core.py").is_file():
    raise SystemExit(f"Не найден исходный проект с алгоритмом дельта-баров: {ENGINE_ROOT}")
sys.path.insert(0, str(ENGINE_ROOT))
try:
    from source.delta_core import NS_SECOND, build_bars, calibrate, read_day
    from tick_to_delta_bars import DEFAULT_ROOT, discover
finally:
    # Соседний проект тоже содержит backtest. Его путь нужен только для импорта ядра.
    sys.path.remove(str(ENGINE_ROOT))
if __package__:
    from .day_cache import open_cache
else:
    from day_cache import open_cache

WINDOW = 20
# Повышать при изменении локальных формул индикаторов или состава сохраняемых полей.
CACHE_VERSION = "weekday-volume-rates-v1"
BUY_COLOR = "#188552"
SELL_COLOR = "#cf404d"


class ConsoleProgress:
    """Выводит ход текущего этапа и оценивает остаток по скорости обработки дней."""

    def __init__(self, stream):
        """Направляет сообщения в поток stream и определяет, можно ли обновлять одну строку."""
        self.stream = stream
        self.terminal = stream.isatty()
        self.phase = None
        self.line_width = 0

    def __call__(self, phase, done, total, day, action):
        """Показывает этап phase, число выполненных единиц done из total и операцию action за day."""
        now = monotonic()
        if phase != self.phase:
            self.phase = phase
            self.started = now
            self.last_output = None
            self.last_done = 0
        # В перенаправленном потоке сохраняем первый прогноз, редкие обновления и итог.
        if (not self.terminal and self.last_output is not None and done < total
                and now - self.last_output < 5 and not (self.last_done == 0 and done > 0)):
            return
        eta = "--:--:--"
        if done:
            seconds = ceil((now - self.started) * (total - done) / done)
            hours, rest = divmod(seconds, 3600)
            minutes, seconds = divmod(rest, 60)
            eta = ("~" if done < total else "") + f"{hours:02}:{minutes:02}:{seconds:02}"
        filled = 10 * done // total
        bar = "#" * filled + "-" * (10 - filled)
        line = f"{phase} [{bar}] {100 * done // total:3}% {done}/{total}  {day} {action}  осталось {eta}"
        if self.terminal:
            print("\r" + line.ljust(self.line_width), end="", file=self.stream, flush=True)
            self.line_width = len(line)
            if done == total:
                self.finish_line()
        else:
            print(line, file=self.stream, flush=True)
        self.last_output = now
        self.last_done = done

    def finish_line(self):
        """Завершает активную строку терминала перед следующим сообщением или ошибкой."""
        if self.line_width:
            print(file=self.stream, flush=True)
            self.line_width = 0


@dataclass
class VolumeProfile:
    """Хранит московские времена тиков и префиксные суммы объёма одной сессии."""

    times: array
    cumulative: array

    @classmethod
    def from_ticks(cls, ticks):
        """Возвращает профиль дня ticks с начальным нулём для запросов до первой сделки."""
        return cls(ticks.times, array("q", accumulate(ticks.volumes, initial=0)))

    def at(self, stamp):
        """Возвращает объём всех сделок до stamp включительно (наносекунды от полуночи)."""
        return self.cumulative[bisect_right(self.times, stamp)]


def session_bars(ticks, history, profiles):
    """Возвращает свечи дня ticks с порогом по history и средним объёмом по profiles тех же будних сессий."""
    bars = build_bars(ticks, calibrate(history).threshold)
    values = ticks.path.values
    previous = 0
    daily_volume = 0
    for bar in bars:
        first, last = bar["start_row"] - 1, bar["end_row"] - 1
        buys = sells = 0
        for i in range(first, last + 1):
            value = values[i]
            buys += value > previous
            sells += value < previous
            previous = value
        close = ticks.times[last]
        # Доли секунды в архивах могут кодировать только порядок сделок.
        seconds = max(1, close // NS_SECOND - ticks.times[first] // NS_SECOND)
        daily_volume += bar["volume"]
        bar.update(buy_rate=buys / seconds, sell_rate=sells / seconds,
                   daily_volume=daily_volume,
                   mean_volume=sum(profile.at(close) for profile in profiles) / len(profiles))
    return bars


def load_chart(input_root, symbol, end=None, start=None, *, progress=None):
    """Возвращает свечи инструмента symbol с индикаторами из дневного кэша или ZIP под input_root.

    end задаёт точную последнюю сессию, по умолчанию выбирается последняя с тиками.
    start включает более ранние дни в тот же график. Обе границы — даты по Москве.
    Свечи строятся для всех сессий со сделками. Историю для порога и среднего
    пополняют только завершённые сессии с понедельника по пятницу, в которых были тики.
    progress при задании получает этап, число готовых и общее число единиц, дату и операцию.
    """
    if start and end and start > end:
        raise ValueError("Начало диапазона позже последней даты")
    archives = discover(input_root, symbol, end or date.max)
    if end and end not in archives:
        raise ValueError(f"{symbol}: отсутствует архив за {end}")
    core_hash = sha256((ENGINE_ROOT / "source" / "delta_core.py").read_bytes()).hexdigest()
    with open_cache(input_root, symbol, archives, f"{CACHE_VERSION}/{WINDOW}/{core_hash}") as cache:
        return load_range(cache, symbol, start, end, progress)


def load_history(cache, symbol, before, progress):
    """Возвращает окно калибровки и профили объёма для symbol до даты before, сообщая ход через progress."""
    history = deque(maxlen=WINDOW)
    profiles = deque(maxlen=WINDOW)
    for day in reversed(cache.weekdays):
        if day >= before:
            continue
        if progress is not None:
            progress("История", len(history), WINDOW, day, "чтение")
        ticks = cache.read_ticks(day, read_day)
        if ticks.times:
            history.appendleft(ticks.history())
            profiles.appendleft(VolumeProfile.from_ticks(ticks))
            if len(history) == WINDOW:
                if progress is not None:
                    progress("История", WINDOW, WINDOW, day, "готово")
                break
    if len(history) < WINDOW:
        raise ValueError(f"{symbol}: до {before} найдено {len(history)} будних сессий с тиками, "
                         f"для среднего объёма и адаптивного порога требуется {WINDOW}")
    return history, profiles


def latest_session(cache, symbol):
    """Возвращает последнюю непустую дату для symbol из cache и тики, если пришлось их прочитать."""
    for day in reversed(cache.archives):
        bars = cache.get(day)
        if bars is None:
            ticks = cache.read_ticks(day, read_day)
            if ticks.times:
                return day, ticks
            cache.save(day, None, [])
        elif bars:
            return day, None
    raise ValueError(f"{symbol}: нет архивов со сделками")


def load_range(cache, symbol, start, end, progress):
    """Загружает диапазон start…end из cache для symbol, дополняя пропуски и вызывая progress."""
    latest, last_ticks = latest_session(cache, symbol) if end is None else (end, None)
    start = start or latest
    if start > latest:
        raise ValueError(f"Последняя доступная сессия {symbol}: {latest}")

    result = []
    history = profiles = None
    hits = 0
    days = [day for day in cache.archives if start <= day <= latest]
    for done, day in enumerate(days):
        bars = cache.get(day)
        if bars is not None:
            hits += 1
            if progress is not None:
                progress("Диапазон", done, len(days), day, "из кэша")
            if bars and day.weekday() < 5:
                # Для следующего пропуска будут нужны реальные тики этого буднего дня.
                history = profiles = None
        else:
            if progress is not None:
                progress("Диапазон", done, len(days), day, "чтение")
            ticks = last_ticks if day == latest and last_ticks is not None else cache.read_ticks(day, read_day)
            if ticks.times:
                if history is None:
                    if done and progress is not None:
                        progress("Диапазон", done, len(days), day, "чтение истории")
                    history, profiles = load_history(cache, symbol, day, progress if done == 0 else None)
                if progress is not None:
                    progress("Диапазон", done, len(days), day, "расчёт")
                bars = session_bars(ticks, history, profiles)
                cache.save(day, history[0].day, bars)
                if day < latest and day.weekday() < 5:
                    history.append(ticks.history())
                    profiles.append(VolumeProfile.from_ticks(ticks))
            else:
                bars = []
                cache.save(day, None, bars)
        if day == end and not bars:
            raise ValueError(f"{symbol}: архив за {end} пуст")
        result.extend(bars)
    if progress is not None:
        progress("Диапазон", len(days), len(days), latest, f"готово, из кэша {hits}")
    return result


def show_chart(bars, symbol, png=None):
    """Показывает свечи bars инструмента symbol и среднее по будням или сохраняет график по пути png."""
    if png:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import finplot as fplt
    import pandas as pd
    import pyqtgraph as pg
    from PyQt6.QtGui import QFont, QFontDatabase
    from PyQt6.QtWidgets import QApplication

    data = pd.DataFrame(bars)
    data["x"] = range(len(data))
    closes = data["end_time"].tolist()
    period = closes[0][:10]
    if closes[-1][:10] != period:
        period += " — " + closes[-1][:10]

    class MoscowTimeAxis(pg.AxisItem):
        """Подписывает порядковые номера свечей московским временем их закрытия."""

        def tickStrings(self, values, scale, spacing):
            """Возвращает подписи делений values для переданных Qt масштаба scale и шага spacing."""
            labels = []
            for value in values:
                i = round(value)
                if 0 <= i < len(closes) and abs(value - i) < 0.01:
                    stamp = closes[i]
                    labels.append(stamp[8:10] + "." + stamp[5:7] + "\n" + stamp[11:19])
                else:
                    labels.append("")
            return labels

    def crosshair_info(x, y, xtext, ytext):
        """Возвращает подписи курсора (x, y) со временем бара и значениями индикаторов."""
        i = round(x)
        if 0 <= i < len(bars):
            b = bars[i]
            xtext = (f"{closes[i]} МСК · Δ {b['delta']:+} / {b['threshold']}\n"
                     f"Покупки {b['buy_rate']:.2f}, продажи {b['sell_rate']:.2f} сд/с\n"
                     f"Объём {b['daily_volume']:,}, среднее {b['mean_volume']:,.1f}")
            if not b["is_complete"]:
                xtext += " · остаток дня"
        return xtext, ytext

    fplt.background = "#ffffff"
    fplt.odd_plot_background = "#fafbfb"
    fplt.foreground = "#263a40"
    fplt.legend_fill_color = "#fffffff0"
    fplt.legend_border_color = "#d2dada"
    fplt.legend_text_color = fplt.foreground
    fplt.grid_alpha = 0.10
    fplt.candle_bull_color = fplt.candle_bull_body_color = "#19704c"
    fplt.candle_bear_color = fplt.candle_bear_body_color = "#ad313f"
    fplt.autoviewrestore(False)
    app = pg.mkQApp()
    if png and sys.platform == "win32":
        # Платформа Qt offscreen под Windows не подгружает системные шрифты.
        font = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf"
        if QFontDatabase.addApplicationFont(str(font)) >= 0:
            app.setFont(QFont("Segoe UI", 9))
    price, volume = fplt.create_plot(f"{symbol} · Адаптивные дельта-бары · {period}", rows=2)
    fplt.candlestick_ochl(data[["x", "open", "close", "high", "low"]], ax=price)
    rates = price.overlay(scale=0.70, yaxis="linear")
    rates.vb.v_zoom_baseline = 0
    next_in_session = data.end_time.str[:10].eq(data.end_time.shift(-1).str[:10]).to_numpy()
    for field, label, color in (("buy_rate", "Покупки", BUY_COLOR), ("sell_rate", "Продажи", SELL_COLOR)):
        curve = fplt.plot(data.x, data[field], ax=rates, color=color, width=1.3,
                          style="o" if len(bars) == 1 else None, legend=f"{label}, сделок/с")
        if len(bars) > 1:
            curve.setData(curve.xData, curve.yData, connect=next_in_session)
            curve.setFillLevel(0)
            curve.setBrush(pg.mkBrush(color + "24"))

    for field, width, color, layer in (("daily_volume", 0.86, BUY_COLOR, -20),
                                        ("mean_volume", 0.42, SELL_COLOR, -19)):
        item = fplt.volume_ocv(data[["x", "open", "close", field]], candle_width=width, ax=volume)
        item.colors.update(bull_frame=color, bull_body=color, bear_frame=color, bear_body=color)
        # При отдалении нельзя складывать значения накопительного ряда соседних баров.
        item.resamp = None
        item.setZValue(layer)
    fplt.add_legend(f"<span style='color:{BUY_COLOR}'>■ Объём с начала сессии</span>&nbsp;&nbsp;"
                    f"<span style='color:{SELL_COLOR}'>■ Среднее за {WINDOW} будних сессий</span> · контракты", ax=volume)
    caption = f"{symbol} · {period}"
    if closes[0][:10] == closes[-1][:10]:
        caption += f" · порог Δ {bars[-1]['threshold']}"
    fplt.add_legend(caption, ax=price)
    volume.setAxisItems({"bottom": MoscowTimeAxis(orientation="bottom")})
    volume.getAxis("bottom").setHeight(45)
    for axis in (price, volume):
        axis.getAxis("right").setWidth(75)
        axis.set_visible(xgrid=True, ygrid=True)
        fplt.add_crosshair_info(crosshair_info, ax=axis)
        for i in range(1, len(closes)):
            if closes[i][:10] != closes[i - 1][:10]:
                axis.addItem(pg.InfiniteLine(i - 0.5, angle=90, pen="#9aa7ac"), ignoreBounds=True)
    if png:
        window = price.vb.win
        window.show_maximized = False
        window.resize(1500, 850)
        fplt.show(qt_exec=False)
        QApplication.processEvents()
        if not window.grab().save(str(png), "PNG"):
            raise OSError(f"Не удалось сохранить PNG: {png}")
        fplt.close()
    else:
        fplt.show()


def main(argv=None):
    """Разбирает argv, открывает просмотр, бэктест или экспорт PNG и возвращает код завершения."""
    parser = argparse.ArgumentParser(description="Адаптивные дельта-бары и тиковые индикаторы Finam")
    parser.add_argument("--symbol", choices=("RTS", "MIX"), default="RTS", help="инструмент (по умолчанию RTS)")
    parser.add_argument("--date", type=date.fromisoformat, help="дата сессии ГГГГ-ММ-ДД (по умолчанию последняя с тиками)")
    parser.add_argument("--start", type=date.fromisoformat, help="начало многодневного графика включительно")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_ROOT, help=f"корень тиковых архивов ({DEFAULT_ROOT})")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--png", type=Path, help="сохранить график в PNG")
    mode.add_argument("--backtest", action="store_true", help="ручной бэктест с клавиатуры")
    parser.add_argument("--trades", type=Path, help="путь к новому CSV позиций для --backtest")
    args = parser.parse_args(argv)
    if args.trades is not None and not args.backtest:
        parser.error("--trades используется вместе с --backtest")
    try:
        print(f"{args.symbol} · Поиск архивов и проверка дневного кэша…", file=sys.stderr, flush=True)
        progress = ConsoleProgress(sys.stderr)
        try:
            bars = load_chart(args.input_root, args.symbol, args.date, args.start, progress=progress)
        finally:
            progress.finish_line()
        print(f"Построение графика · свечей {len(bars)}", file=sys.stderr, flush=True)
        if args.backtest:
            if __package__:
                from .backtest import Backtest
                from .backtest_window import show_backtest
            else:
                from backtest import Backtest
                from backtest_window import show_backtest
            session = Backtest(bars, args.symbol, args.trades)
            print(f"Файл позиций: {session.path}", flush=True)
            show_backtest(session)
        else:
            show_chart(bars, args.symbol, args.png)
    except ImportError as exc:
        print(f"Не удалось загрузить модуль графика: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, BadZipFile, sqlite3.Error) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    if args.png:
        print(f"Сохранено {len(bars)} свечей: {args.png.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
