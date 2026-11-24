# pj31_delta_ts
Торговая система на основе дельты

## Виртуальное окружение Python

Для проекта создано локальное окружение `.venv` на Python 3.14.9.
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

Для алгоритма дельта-баров требуется соседняя папка `pj24_delta_bars` с исходным кодом.
