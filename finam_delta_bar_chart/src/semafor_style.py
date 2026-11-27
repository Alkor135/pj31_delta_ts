r"""Задаёт общее оформление семафоров и островов SMA для графика и бэктеста.

Хранит цвета, формы и размеры, формирует показания индикаторов для одного бара.
Команды ниже запускаются из корня проекта.
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor --symbol RTS
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor_backtest --symbol MIX
"""

from math import cos, isfinite, pi, sin

LEVEL_STYLES = ((7, "точки"), (12, "светики"), (21, "солнышки"))
MARKER_SIDES = (("low", "низ", "#008820", -1), ("high", "верх", "#df2525", 1))
ISLAND_COLOURS = ((1, "#16a34a65"), (-1, "#ef444465"))
SMA_COLOURS = (("ma_fast", "#16803d"), ("ma_slow", "#d54747"))
RING_COLOUR = "#2563eb"
FXI_CENTER_COLOUR = "#ffe33d"


def sun_symbol():
    """Возвращает контур восьмилучевого солнышка для метки постоянного размера."""
    from PyQt6.QtGui import QPainterPath

    path = QPainterPath()
    path.moveTo(0.5, 0.0)
    for i in range(1, 16):
        angle = i * pi / 8
        radius = 0.5 if i % 2 == 0 else 0.25
        path.lineTo(radius * cos(angle), radius * sin(angle))
    path.closeSubpath()
    return path


def marker_style(level, preset, colour, sun):
    """Возвращает форму и цвет level от 1 до 3 для preset, стороны colour и контура sun."""
    shape = sun if level == 3 or (preset == "nuf" and level == 2) else "o"
    return shape, "#e5b400" if preset == "fxi" and level == 2 else colour


def semafor_details(points, index, depths):
    """Возвращает значения SMA и уровней depths на строке index таблицы points."""
    bar = points.iloc[index]
    labels = []
    if isfinite(bar.ma_fast) and isfinite(bar.ma_slow):
        labels.append(f"SMA {points.attrs['ma_fast']}/{points.attrs['ma_slow']} "
                      f"{bar.ma_fast:.12g}/{bar.ma_slow:.12g}")
    for level, depth in enumerate(depths, 1):
        for side, label, _, _ in MARKER_SIDES:
            value = bar[f"sf{level}_{side}"]
            if isfinite(value):
                labels.append(f"СФ {depth} {label} {value:.12g}")
    return " · ".join(labels)
