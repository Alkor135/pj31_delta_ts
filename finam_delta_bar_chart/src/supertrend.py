r"""Рассчитывает уровни Supertrend по максимумам, минимумам и закрытиям дельта-баров.

Первый ATR равен среднему истинному диапазону, далее применяется сглаживание
Уайлдера. Уровень меняет сторону после закрытия за соответствующей границей.
В Python функцию можно импортировать и вызвать так.
    from finam_delta_bar_chart.src.supertrend import calculate_supertrend
    levels = calculate_supertrend(bars, period=10, multiplier=2)
Команда ниже запускает график из корня проекта.
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_2_supertrend --fast-period 10 --fast-multiplier 2
"""


def calculate_supertrend(bars, period, multiplier):
    """Возвращает по одному значению Supertrend на каждый бар из bars.

    Бары передаются в хронологическом порядке и содержат high, low и close.
    period — положительное число баров в ATR, multiplier — положительный
    множитель ATR. Результат содержит None до прогрева и пары (уровень, рост)
    после него. Рост равен True для нижней границы, False для верхней.
    """
    result = []
    previous_close = None
    tr_sum = 0.0
    atr = upper = lower = None
    rising = False

    for index, bar in enumerate(bars, 1):
        high, low, close = bar["high"], bar["low"], bar["close"]
        true_range = high - low
        if previous_close is not None:
            true_range = max(true_range, high - previous_close, previous_close - low)

        if index <= period:
            tr_sum += true_range
        if index < period:
            result.append(None)
            previous_close = close
            continue

        middle = (high + low) / 2
        if atr is None:
            atr = tr_sum / period
            upper, lower = middle + multiplier * atr, middle - multiplier * atr
        else:
            atr += (true_range - atr) / period
            basic_upper = middle + multiplier * atr
            basic_lower = middle - multiplier * atr
            if basic_upper < upper or previous_close > upper:
                upper = basic_upper
            if basic_lower > lower or previous_close < lower:
                lower = basic_lower
            if rising:
                rising = close >= lower
            else:
                rising = close > upper

        result.append((lower if rising else upper, rising))
        previous_close = close

    return result
