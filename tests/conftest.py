"""Shared fixtures: one seeded business DB per test session, isolated state DBs per test."""

from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from hearthly.seed.generator import Dataset, HearthlyGenerator
from hearthly.seed.writer import write_database

AS_OF = date.today()


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    return HearthlyGenerator(AS_OF, seed=42).build()


@pytest.fixture(scope="session")
def business_db(tmp_path_factory: pytest.TempPathFactory, dataset: Dataset) -> Path:
    path = tmp_path_factory.mktemp("biz") / "hearthly.db"
    write_database(dataset, path)
    os.environ["HEARTHLY_DB"] = str(path)
    return path


@pytest.fixture()
def state_db(tmp_path: Path, business_db: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "state.db"
    monkeypatch.setenv("HEARTHLY_STATE_DB", str(path))
    return path


@pytest.fixture(scope="session")
def conn(business_db: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{business_db}?mode=ro", uri=True)
    yield c
    c.close()
