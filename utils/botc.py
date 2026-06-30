from __future__ import annotations

import importlib.util
import os as _os
import sys as _sys

_botc_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "BOTC", "utils", "botc.py")
_spec = importlib.util.spec_from_file_location("botc_module", _botc_path)
_mod = importlib.util.module_from_spec(_spec)
_sys.modules["botc_module"] = _mod
_spec.loader.exec_module(_mod)


def __getattr__(name):
    return getattr(_mod, name)


def __dir__():
    return [x for x in dir(_mod) if not x.startswith("_")]
