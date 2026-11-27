r"""Рассчитывает три уровня «Семафора» CountZZ и острова SMA из дельта-баров.

Переносит алгоритм из pj24_delta_bars/chart_delta_bar_semafor.py.
Ищет экстремумы в скользящем окне, применяет Deviation и Backstep,
затем оставляет сильнейшие чередующиеся вершины и впадины. Направление
островов задаёт порядок двух простых средних по ценам закрытия.
Команда ниже запускает график из корня проекта.
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor --symbol RTS --depths 5 12 34 --ma-fast 3 --ma-slow 34
"""

from numbers import Integral

import numpy as np
import pandas as pd

DEFAULT_DEPTHS = (5, 12, 34)
DEFAULT_MA_FAST = 3
DEFAULT_MA_SLOW = 34
PRESETS = {"nuf": (1, 1), "fxi": (5, 3)}


def integer_parameter(value, name, minimum=0):
    """Возвращает value целым числом от minimum до 10000 или сообщает об ошибке параметра name."""
    if isinstance(value, bool) or not isinstance(value, Integral) or not minimum <= value <= 10000:
        raise ValueError(f"{name} должен быть целым числом от {minimum} до 10000")
    return int(value)


def validate_settings(depths, deviation, backstep, point,
                      ma_fast=DEFAULT_MA_FAST, ma_slow=DEFAULT_MA_SLOW):
    """Нормализует и возвращает настройки CountZZ и островов или сообщает об ошибке.

    depths задаёт три глубины в барах, deviation — допуск в единицах point,
    backstep — число прошлых баров для удаления слабых кандидатов,
    point — единицу цены, ma_fast и ma_slow — периоды двух SMA.
    """
    if len(depths) != 3:
        raise ValueError("Семафор требует три глубины — младшую, среднюю и старшую")
    depths = tuple(integer_parameter(value, "Глубина СФ") for value in depths)
    deviation = integer_parameter(deviation, "Deviation")
    backstep = integer_parameter(backstep, "Backstep")
    try:
        point = float(point)
    except (ValueError, TypeError) as exc:
        raise ValueError("Point должен быть числом") from exc
    if not np.isfinite(point) or not 0.01 <= point <= 100000 or not np.isclose(point, round(point, 2), rtol=0, atol=1e-12):
        raise ValueError("Point должен быть от 0.01 до 100000 и иметь до двух знаков после запятой")
    return dict(depths=depths, deviation=deviation, backstep=backstep, point=point,
                ma_fast=integer_parameter(ma_fast, "Период быстрой SMA", minimum=1),
                ma_slow=integer_parameter(ma_slow, "Период медленной SMA", minimum=1))


def count_zz(highs, lows, depth, tolerance, backstep):
    """Возвращает массивы впадин и вершин CountZZ для highs и lows.

    depth — размер окна, tolerance — допуск в единицах цены,
    backstep — число предыдущих баров для снятия слабого кандидата.
    NaN означает отсутствие метки. Нулевая глубина отключает уровень.
    """
    size = len(highs)
    low_points = np.full(size, np.nan)
    high_points = np.full(size, np.nan)
    if depth == 0 or size < depth:
        return low_points, high_points

    rolling_low = pd.Series(lows).rolling(depth).min().to_numpy()
    rolling_high = pd.Series(highs).rolling(depth).max().to_numpy()
    last_low = last_high = None
    for i in range(depth - 1, size):
        low, high = rolling_low[i], rolling_high[i]
        if low != last_low:
            last_low = low
            if lows[i] - low <= tolerance:
                for previous in range(max(0, i - backstep), i):
                    if low_points[previous] > low:
                        low_points[previous] = np.nan
                low_points[i] = low
        if high != last_high:
            last_high = high
            if high - highs[i] <= tolerance:
                for previous in range(max(0, i - backstep), i):
                    if high_points[previous] < high:
                        high_points[previous] = np.nan
                high_points[i] = high

    last_low = last_high = None
    low_position = high_position = None
    for i in range(depth - 1, size):
        low, high = low_points[i], high_points[i]
        if np.isfinite(high):
            if last_high is not None:
                if high > last_high:
                    high_points[high_position] = np.nan
                else:
                    high_points[i] = np.nan
            if last_high is None or high > last_high:
                last_high, high_position = high, i
            last_low = None
        if np.isfinite(low):
            if last_low is not None:
                if low < last_low:
                    low_points[low_position] = np.nan
                else:
                    low_points[i] = np.nan
            if last_low is None or low < last_low:
                last_low, low_position = low, i
            last_high = None
    # Финальный цикл исходного CountZZ убирает первую впадину прогрева.
    low_points[depth - 1] = np.nan
    return low_points, high_points


def calculate_semafor(bars, depths=DEFAULT_DEPTHS, deviation=1, backstep=1, point=1,
                      ma_fast=DEFAULT_MA_FAST, ma_slow=DEFAULT_MA_SLOW):
    """Возвращает таблицу меток трёх СФ и значений двух SMA для хронологических bars.

    Использует цены high, low и close каждого бара. Значения depths, deviation,
    backstep, point, ma_fast и ma_slow описаны в validate_settings. Дни образуют
    единую историю. Направление острова равно 1, когда быстрая SMA выше,
    −1 при обратном порядке и 0 при совпадении или прогреве.
    """
    settings = validate_settings(depths, deviation, backstep, point, ma_fast, ma_slow)
    prices = pd.DataFrame(bars, columns=["high", "low", "close"]).to_numpy(dtype=float)
    highs, lows, closes = prices.T
    if not np.isfinite(prices).all() or np.any((closes < lows) | (closes > highs)):
        raise ValueError("Требуются конечные цены low ≤ close ≤ high для каждого бара")
    result = {}
    tolerance = settings["deviation"] * settings["point"]
    for level, depth in enumerate(settings["depths"], 1):
        low, high = count_zz(highs, lows, depth, tolerance, settings["backstep"])
        result[f"sf{level}_low"] = low
        result[f"sf{level}_high"] = high
    closes = pd.Series(closes)
    fast = closes.rolling(settings["ma_fast"]).mean()
    slow = closes.rolling(settings["ma_slow"]).mean()
    result.update(ma_fast=fast, ma_slow=slow,
                  island_direction=np.select([fast > slow, fast < slow], [1, -1], default=0))
    points = pd.DataFrame(result)
    points.attrs.update(ma_fast=settings["ma_fast"], ma_slow=settings["ma_slow"])
    return points
