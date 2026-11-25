"""Semantics matrix. Every module in this package registers its Semantics on import (auto-discovered),
so adding a version is: drop in a module + its vector suite. The core only calls for_format()."""
import importlib
import pkgutil

from .base import all_semantics, for_format, get, Semantics  # noqa: F401

for _m in sorted(m.name for m in pkgutil.iter_modules(__path__)):
    if _m != "base":
        importlib.import_module(__name__ + "." + _m)
