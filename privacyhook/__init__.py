"""Bodycam (formerly PrivacyHook). The Python package keeps its original
name so hooks already registered as `python -m privacyhook.hooks.…` keep
working after an upgrade."""

import os as _os

__version__ = "0.1.0"


def _alias_env() -> None:
    # Every setting can be given as BODYCAM_* or, as before, PRIVACYHOOK_*.
    for key, value in list(_os.environ.items()):
        if key.startswith("BODYCAM_"):
            _os.environ.setdefault("PRIVACYHOOK_" + key[len("BODYCAM_"):], value)


_alias_env()
