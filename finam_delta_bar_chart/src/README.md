# Вспомогательные модули графика Finam

| Модуль | Назначение |
| --- | --- |
| `finam_archives.py` | Формирование пути к папке выбранного инструмента под `--input-root` и поиск в ней дневных ZIP. |
| `delta_core.py` | Чтение тиков, калибровка порога дельты и расчёт свечей. |
| `day_cache.py` | Чтение и запись рассчитанных дней, в том числе поля `volume_diff`, в SQLite с проверкой архивов и версии расчёта. |
| `cluster_volume.py` | Суммирование объёмов сделок по ценам каждого бара, выбор максимума и сохранение дневных значений в `clusters.sqlite3` рядом с кэшем свечей. |
| `chart_view.py` | Общее окно свечей, интенсивностей и разницы объёма для расширенных графиков. Вызывающий скрипт передаёт функции отрисовки индикатора и формирования его показаний у курсора. |
| `backtest.py` | Состояние ручного бэктеста и журнал позиций в CSV. Поле `entry_volume_diff` хранит разницу объёмов по предыдущему раскрытому бару той же сессии. |
| `backtest_window.py` | Окно Qt, раскрытие свечей, знаковые столбцы разницы объёмов, подсказки и таблица позиций. |
| `finplot_compat.py` | Загрузка `finplot` с поддержкой русской локали без правок установленных файлов. |
| `supertrend.py` | Расчёт Supertrend по максимуму, минимуму и закрытию баров. Первый ATR — среднее истинных диапазонов, следующие рассчитываются сглаживанием Уайлдера. |
| `__init__.py` | Окно из 20 исторических сессий, цвета и формат разницы объёмов для графика и бэктеста. |

Вспомогательные модули загружают `chart.py`, `chart_2_supertrend.py` и `chart_claster_max_volume.py`. Функция `calculate_supertrend(bars, period, multiplier)` принимает хронологический ряд баров, период ATR в барах и множитель. Она возвращает уровень и направление для каждого бара после прогрева. Функция `load_clusters(input_root, symbol, bars)` принимает корень архивов, инструмент и готовые бары. Она возвращает пары «цена, объём в контрактах» в порядке баров и при необходимости обновляет дневной кэш.

```powershell
.\.venv\Scripts\python.exe .\finam_delta_bar_chart\chart.py --help
.\.venv\Scripts\python.exe .\finam_delta_bar_chart\chart.py --symbol MIX --date 2026-11-11
.\.venv\Scripts\python.exe .\finam_delta_bar_chart\chart.py --backtest --symbol RTS --trades rts.csv
.\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_2_supertrend --fast-period 10 --fast-multiplier 2 --slow-period 21 --slow-multiplier 4
.\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_claster_max_volume --symbol MIX --date 2026-11-11
```

[Параметры и примеры запуска графика](../README.md#запуск)
