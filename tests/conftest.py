import os
import pathlib
import sys

# Test environment must be set before any gateway import (engine binds at import time).
_TEST_DB = pathlib.Path(__file__).parent / "test_checkpost.db"
os.environ.setdefault("CHECKPOST_DATABASE_URL", f"sqlite:///{_TEST_DB.as_posix()}")
os.environ.setdefault("CHECKPOST_RAZORPAY_MODE", "mock")
os.environ.setdefault("CHECKPOST_LLM_ENABLED", "false")
os.environ.setdefault("CHECKPOST_LLM_FAILURE_POLICY", "proceed")

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from gateway.core.db import engine, init_db  # noqa: E402
from gateway.core.db import Base  # noqa: E402
from gateway.payments import client as payments_client  # noqa: E402
from scripts.seed import BULKBOT_KEY, PILLPAL_KEY, seed  # noqa: E402


@pytest.fixture()
def world():
    """Fresh seeded database + fresh mock Razorpay for each test."""
    Base.metadata.drop_all(engine)
    init_db()
    ids = seed()
    payments_client.reset_mock()
    yield ids


@pytest.fixture()
def api(world):
    from gateway.main import app
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def pillpal_headers():
    return {"X-Agent-Key": PILLPAL_KEY}


@pytest.fixture()
def bulkbot_headers():
    return {"X-Agent-Key": BULKBOT_KEY}


@pytest.fixture()
def mock_rzp():
    return payments_client.get_client()
