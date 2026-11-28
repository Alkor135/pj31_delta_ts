# Вспомогательные модули графика Finam

| Модуль | Назначение |
| --- | --- |
| `finam_archives.py` | Формирование пути к папке выбранного инструмента под `--input-root` и поиск в ней дневных ZIP. |
| `delta_core.py` | Чтение тиков, калибровка порога дельты и расчёт свечей. |
| `day_cache.py` | Чтение и запись рассчитанных дней, в том числе поля `volume_diff`, в SQLite с проверкой архивов и версии расчёта. |
| `cluster_volume.py` | Суммирование объёмов сделок по ценам каждого бара, выбор максимума и сохранение дневных значений в `clusters.sqlite3` рядом с кэшем свечей. |
| `chart_view.py` | Общее окно свечей, интенсивностей и разницы объёма для расширенных графиков. Вызывающий скрипт передаёт функции отрисовки индикатора и формирования его показаний у курсора. |
| `backtest.py` | Состояние ручного бэктеста, расчёт накопленного и дневного PnL, закрытие позиций и журнал CSV. Поле `entry_volume_diff` хранит разницу объёмов по предыдущему раскрытому бару той же сессии. |
| `backtest_state.py` | Автосохранение шага, настроек и позиций в JSON. При продолжении проверяет подпись свечей, восстанавливает CSV и блокирует параллельную запись в тот же прогон. |
| `backtest_window.py` | Окно Qt, раскрытие свечей, метки входов и выходов с подсказками, таблица позиций, сводка PnL и статус сохранения. В бэктесте семафоров доступны кнопка легенды и закрытие позиции из строки. |
| `finplot_compat.py` | Загрузка `finplot` с поддержкой русской локали без правок установленных файлов. |
| `supertrend.py` | Расчёт Supertrend по максимуму, минимуму и закрытию баров. Первый ATR — среднее истинных диапазонов, следующие рассчитываются сглаживанием Уайлдера. |
| `semafor.py` | Расчёт трёх уровней CountZZ и островов SMA из `pj24_delta_bars`. Скользящие экстремумы фильтруются по допуску и расстоянию, средние строятся по ценам закрытия. |
| `semafor_style.py` | Общие цвета, размеры, формы меток и формат показаний СФ/SMA для графика и бэктеста. |
| `semafor_replay.py` | Ценовая панель ручного бэктеста с СФ/SMA и чёрными разделителями дат. При перемещении курсора обновляет индикаторы и видимые границы по доступным свечам и открытию. |
| `__init__.py` | Окно из 20 исторических сессий, цвета и формат разницы объёмов для графика и бэктеста. |

Вспомогательные модули загружают `chart.py`, `chart_2_supertrend.py`, `chart_claster_max_volume.py`, `chart_semafor.py` и `chart_semafor_backtest.py`. Функция `calculate_supertrend(bars, period, multiplier)` принимает хронологический ряд баров, период ATR в барах и множитель. Она возвращает уровень и направление для каждого бара после прогрева. Функция `load_clusters(input_root, symbol, bars)` принимает корень архивов, инструмент и готовые бары. Она возвращает пары «цена, объём в контрактах» в порядке баров и при необходимости обновляет дневной кэш.

`calculate_semafor(bars, depths, deviation, backstep, point, ma_fast, ma_slow)` принимает хронологические бары, настройки CountZZ и периоды SMA. Возвращает таблицу цен вершин и впадин, значений SMA и направления заливки для каждого бара. Отсутствие метки и непрогретые значения SMA обозначены `NaN`. Периоды по умолчанию равны 3 и 34 барам.

```powershell
.\.venv\Scripts\python.exe .\finam_delta_bar_chart\chart.py --help
.\.venv\Scripts\python.exe .\finam_delta_bar_chart\chart.py --symbol MIX --date 2026-11-11
.\.venv\Scripts\python.exe .\finam_delta_bar_chart\chart.py --backtest --symbol RTS --trades rts.csv
.\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_2_supertrend --fast-period 10 --fast-multiplier 2 --slow-period 21 --slow-multiplier 4
.\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_claster_max_volume --symbol MIX --date 2026-11-11
.\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor --symbol RTS --depths 5 12 34 --ma-fast 3 --ma-slow 34
.\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor_backtest --symbol RTS --date 2026-11-11 --history-start 2026-11-10
.\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor_backtest --resume MIX_semafor.state.json
```

[Параметры и примеры запуска графика](../README.md#запуск)
