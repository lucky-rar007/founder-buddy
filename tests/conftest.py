"""
Shared Pytest Fixtures for Founder Buddy.

Provides reusable fixtures for FastAPI test client, database initialization,
and mock API credentials to ensure hermetic and reproducible test runs.
"""

import pytest
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def setup_test_db(tmp_path_factory):
    """
    Initialize an isolated test database in a temp directory before test suite execution.
    Patches shared.database.DB_FILE to point to a temp path so no production data
    is read or written during testing.
    """
    import shared.database as db_module

    # Create isolated temp database path
    tmp_dir = tmp_path_factory.mktemp("test_data")
    test_db = tmp_dir / "test_founder_buddy.db"

    # Redirect the module-level DB_FILE constant before any connections are made
    original_db_file = db_module.DB_FILE
    original_db_dir = db_module.DB_DIR

    db_module.DB_FILE = test_db
    db_module.DB_DIR = tmp_dir

    # Initialize schema on the test database
    from shared.database import init_db
    init_db()

    yield

    # Restore original paths
    db_module.DB_FILE = original_db_file
    db_module.DB_DIR = original_db_dir

    # Clean up test database
    if test_db.exists():
        try:
            test_db.unlink()
        except Exception:
            pass


@pytest.fixture(scope="module")
def api_client():
    """Provides a FastAPI TestClient for endpoint integration tests."""
    from server.app import create_app
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def mock_gemini_key():
    """Sets a mock Gemini API key in configuration for testing."""
    from shared.database import set_config
    set_config("gemini_api_key", "AIzaSy_mock_test_key_for_unit_tests")
    return "AIzaSy_mock_test_key_for_unit_tests"
