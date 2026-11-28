r"""Запускает ручной бэктест дельта-баров Finam с семафорами и островами SMA.

Шаг раскрывает свечу и пересчитывает метки по доступной истории. Стрелки
перематывают бары и открывают позиции. Кнопка «Закрыть» в строке завершает
выбранную позицию по текущему открытию, C закрывает все.
CSV сохраняет сделки и прежние поля журнала. В окне показаны цена,
интенсивности и индикаторы СФ/SMA. Кнопка «Легенда» скрывает подписи.
Каждое действие записывается в JSON рядом с CSV. Параметр --resume
продолжает сохранённый прогон на том же шаге.

Команды ниже запускаются из корня проекта.
    .\.venv\Scripts\python.exe .\finam_delta_bar_chart\chart_semafor_backtest.py --symbol RTS --date 2026-11-11
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor_backtest --symbol MIX --start 2026-11-11 --history-start 2026-11-10 --date 2026-11-11 --trades MIX_semafor.csv
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor_backtest --symbol MIX --start 2026-09-01 --history-start 2026-08-01 --trades .\finam_delta_bar_chart\backtests\MIX_semafor.csv
    .\.venv\Scripts\python.exe -m finam_delta_bar_chart.chart_semafor_backtest --resume .\finam_delta_bar_chart\backtests\MIX_semafor.state.json
"""

from contextlib import ExitStack
from datetime import date
from functools import partial
from pathlib import Path
import sqlite3
import sys
from zipfile import BadZipFile

if __package__:
    from .chart import ConsoleProgress
    from .chart_semafor import load_semafor_range, semafor_parser, semafor_settings
    from .src.backtest_state import ResumeSettings, SavedBacktest, read_saved_run
else:
    from chart import ConsoleProgress
    from chart_semafor import load_semafor_range, semafor_parser, semafor_settings
    from src.backtest_state import ResumeSettings, SavedBacktest, read_saved_run


def main(argv=None):
    """Разбирает argv, начинает или продолжает ручной прогон и возвращает код завершения."""
    parser = semafor_parser("Ручной бэктест Finam с Семафором и островами SMA")
    journal = parser.add_mutually_exclusive_group()
    journal.add_argument("--trades", type=Path, help="путь к новому CSV позиций")
    journal.add_argument("--resume", type=Path, help="продолжить прогон из JSON с сохранёнными настройками")
    args = parser.parse_args(argv)

    try:
        with ExitStack() as resources:
            saved = read_saved_run(args.resume, resources) if args.resume is not None else None
            source = saved.config if saved is not None else args
            if saved is None:
                settings, offset = semafor_settings(parser, args)
            end = source.end if saved is not None else args.date
            print(f"{source.symbol} · Поиск архивов и проверка дневного кэша…", file=sys.stderr, flush=True)
            progress = ConsoleProgress(sys.stderr)
            try:
                bars, first = load_semafor_range(source.input_root, source.symbol, end, source.start,
                                                 history_start=source.history_start, progress=progress)
            finally:
                progress.finish_line()
            if first == len(bars):
                raise ValueError("Для бэктеста нужен хотя бы один бар в торговом диапазоне")

            config = saved.config if saved is not None else ResumeSettings(
                source.symbol, source.input_root.resolve(), date.fromisoformat(bars[first]["start_time"][:10]),
                date.fromisoformat(bars[-1]["end_time"][:10]), source.history_start, source.preset, offset, settings,
            )
            session = SavedBacktest(bars, first, config, resources, path=args.trades, saved=saved)
            print(f"Файл позиций: {session.path}", flush=True)
            print(f"Файл состояния: {session.state_path}", flush=True)
            if __package__:
                from .src.backtest_window import show_backtest
                from .src.semafor_replay import SemaforReplayChart
            else:
                from src.backtest_window import show_backtest
                from src.semafor_replay import SemaforReplayChart

            chart_factory = partial(SemaforReplayChart, history=bars[:first], settings=config.settings,
                                    preset=config.preset, offset=config.offset)
            show_backtest(session, chart_factory=chart_factory, toggle_legend=True, individual_close=True)
    except (ImportError, OSError, ValueError, BadZipFile, sqlite3.Error) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
