"""
Configuration loader.
Reads config.yaml once and exposes it as a nested, attribute-friendly object so
the rest of the code reads like `cfg.risk.tp_pct` instead of dict-digging.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import yaml

_DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")


def _to_ns(obj: Any) -> Any:
    """Recursively turn dicts into SimpleNamespace for dotted access."""
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _to_ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_to_ns(v) for v in obj]
    return obj


def load_config(path: str | None = None) -> SimpleNamespace:
    """Load config.yaml (or an override path) into a dotted namespace."""
    path = path or _DEFAULT_PATH
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    cfg = _to_ns(raw)
    cfg._path = path  # keep the source path for logging
    return cfg
