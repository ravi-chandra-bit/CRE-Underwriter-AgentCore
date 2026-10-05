"""Loads the credit policy and pricing configuration bundled with the package."""

from __future__ import annotations

import os
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

import yaml


@lru_cache(maxsize=4)
def load_policy(path: str | None = None) -> dict[str, Any]:
    """Return the credit policy. `CREDIT_POLICY_PATH` overrides the bundled synthetic policy."""
    path = path or os.environ.get("CREDIT_POLICY_PATH")
    if path:
        return yaml.safe_load(Path(path).read_text())
    text = resources.files("underwriter.data").joinpath("credit_policy.yaml").read_text()
    return yaml.safe_load(text)


@lru_cache(maxsize=1)
def load_pricing() -> dict[str, Any]:
    text = resources.files("underwriter.data").joinpath("model_pricing.yaml").read_text()
    return yaml.safe_load(text)
