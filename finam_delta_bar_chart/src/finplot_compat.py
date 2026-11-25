"""Загружает finplot с исправлением аварийного выхода по локали."""

from importlib import import_module
from importlib.machinery import SourceFileLoader
from importlib.util import find_spec, module_from_spec
import sys


# Блок из finplot 1.9.7. Точное совпадение ограничивает исправление этой проверкой.
_LOCALE_EXIT = r"""import locale
code,_ = locale.getdefaultlocale()
if code is not None and \
    (any(sanctioned in code.lower() for sanctioned in '_ru _by ru_ by_'.split()) or \
     any(sanctioned in code.lower() for sanctioned in 'ru be'.split())):
    import os
    os._exit(1)
    assert False
"""


def load_finplot():
    """Возвращает модуль finplot, пропуская известную проверку локали при загрузке.

    Исправление действует в памяти процесса и сохраняет локаль и файлы пакета.
    При отсутствии пакета или ошибке его загрузки передаёт исходное исключение.
    """
    name = "finplot"
    if name in sys.modules:
        return import_module(name)

    spec = find_spec(name)
    if spec is None or not isinstance(spec.loader, SourceFileLoader):
        return import_module(name)
    source = spec.loader.get_source(name)
    if source is None or _LOCALE_EXIT not in source:
        return import_module(name)

    # Пустые строки сохраняют номера строк исходника в трассировках.
    source = source.replace(_LOCALE_EXIT, "\n" * _LOCALE_EXIT.count("\n"))
    code = compile(source, spec.loader.path, "exec")
    module = module_from_spec(spec)
    sys.modules[name] = module
    try:
        exec(code, module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module
