"""Writable cache directories for this process. No network and no installs.

Paths come from the environment, or from the current working directory when
those variables are unset. This module does not store an interpreter path
or a library version.
"""

from __future__ import annotations

import os


def ensure_cache_env() -> None:
    cwd = os.getcwd()
    os.environ.setdefault("MPLCONFIGDIR", os.path.join(cwd, "mplconfig"))
    os.environ.setdefault("XDG_CACHE_HOME", os.path.join(cwd, "xdg_cache"))
    os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)
    os.makedirs(os.environ["XDG_CACHE_HOME"], exist_ok=True)
