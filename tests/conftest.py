import shutil
from pathlib import Path

import pytest

from underwriter.service import UnderwritingService
from underwriter.store import LocalDealStore

DATA = Path(__file__).resolve().parents[1] / "evals" / "data" / "deals"


@pytest.fixture
def store(tmp_path) -> LocalDealStore:
    shutil.copytree(DATA, tmp_path / "deals", ignore=shutil.ignore_patterns("truth.json", "work"))
    return LocalDealStore(tmp_path / "deals")


@pytest.fixture
def service(store) -> UnderwritingService:
    return UnderwritingService(store)
