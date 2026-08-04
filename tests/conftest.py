"""Pytest configuration and shared fixtures for Sniper V2 tests."""
import json
import os
import sys
from pathlib import Path

import pytest

# Ensure the scripts directory is on sys.path so sniper_v2 can be imported
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def daangn_listing():
    with open(FIXTURES_DIR / "daangn_listing.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def joongna_listing():
    with open(FIXTURES_DIR / "joongna_listing.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def sample_state():
    with open(FIXTURES_DIR / "sample_state.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def mock_config():
    with open(FIXTURES_DIR / "mock_config.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def tmp_state_path(tmp_path):
    return tmp_path / "state.json"


@pytest.fixture
def tmp_config_path(tmp_path):
    path = tmp_path / "config.json"
    with open(FIXTURES_DIR / "mock_config.json", encoding="utf-8") as src:
        data = json.load(src)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path
