# pj31_delta_ts
Торговая система на основе дельты

## Виртуальное окружение Python

Для проекта используется локальное окружение `.venv` на Python 3.14.
Папка `.venv` исключена из Git через `.gitignore`.

Активация в PowerShell из папки проекта:

```powershell
.\.venv\Scripts\Activate.ps1
```

Работа без активации:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip --version
```

Повторное создание окружения при доступном Python 3.14:

```powershell
python -m venv .venv
```

Выход из активированного окружения: `deactivate`.

Установка зависимостей графика и запуск из корня проекта:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe .\finam_delta_bar_chart\chart.py
```

Код расчёта дельта-баров и поиска архивов входит в проект. Для запуска нужны зависимости из `requirements.txt` и дневные ZIP с тиками Finam. По умолчанию график ищет их в `C:\data_quote`. Для другого каталога укажите `--input-root`.

Нижняя панель графика и ручного бэктеста показывает разницу между накопленным объёмом текущей сессии и средним к тому же московскому времени за 20 предыдущих будних сессий со сделками. Зелёные столбцы идут вверх от нуля, красные вниз. Разница хранится в дневной базе SQLite инструмента. [Параметры запуска и формат данных](finam_delta_bar_chart/README.md)
