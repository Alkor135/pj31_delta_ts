r"""Запускает ручной бэктест дельта-баров Finam с семафорами и островами SMA.

Шаг раскрывает свечу и пересчитывает метки по доступной истории. Стрелки
перематывают бары и открывают позиции, C закрывает их по текущему открытию.
CSV сохраняет сделки и прежние поля журнала. В окне показаны цена,
интенсивности и индикаторы СФ/SMA. Кнопка «Легенда» скрывает подписи.

Команды ниже запускаются из корня проекта.
    .\.venv\Scripts\python.exe .\finam_delta_bar_chart\chart_semafor_backtest.py --symbol RTS --date 2026-11-11
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor_backtest --symbol MIX --start 2026-11-11 --history-start 2026-11-10 --date 2026-11-11 --trades MIX_semafor.csv
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor_backtest --symbol MIX --start 2026-09-01 --history-start 2026-08-01 --trades .\finam_delta_bar_chart\backtests\MIX_semafor.csv
"""

from functools import partial
from pathlib import Path
import sqlite3
import sys
from zipfile import BadZipFile

if __package__:
    from .chart import ConsoleProgress
    from .chart_semafor import load_semafor_range, semafor_parser, semafor_settings
    from .src.backtest import Backtest
else:
    from chart import ConsoleProgress
    from chart_semafor import load_semafor_range, semafor_parser, semafor_settings
    from src.backtest import Backtest


def main(argv=None):
    """Разбирает argv, загружает бары и запускает ручной бэктест. Возвращает код завершения."""
    parser = semafor_parser("Ручной бэктест Finam с Семафором и островами SMA")
    parser.add_argument("--trades", type=Path, help="путь к новому CSV позиций")
    args = parser.parse_args(argv)
    settings, offset = semafor_settings(parser, args)

    try:
        print(f"{args.symbol} · Поиск архивов и проверка дневного кэша…", file=sys.stderr, flush=True)
        progress = ConsoleProgress(sys.stderr)
        try:
            bars, first = load_semafor_range(args.input_root, args.symbol, args.date, args.start,
                                             history_start=args.history_start, progress=progress)
        finally:
            progress.finish_line()
        if __package__:
            from .src.backtest_window import show_backtest
            from .src.semafor_replay import SemaforReplayChart
        else:
            from src.backtest_window import show_backtest
            from src.semafor_replay import SemaforReplayChart

        session = Backtest(bars[first:], args.symbol, args.trades)
        print(f"Файл позиций: {session.path}", flush=True)
        chart_factory = partial(SemaforReplayChart, history=bars[:first], settings=settings,
                                preset=args.preset, offset=offset)
        show_backtest(session, chart_factory=chart_factory, toggle_legend=True)
    except (ImportError, OSError, ValueError, BadZipFile, sqlite3.Error) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
