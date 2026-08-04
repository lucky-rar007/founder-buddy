"""
Unit tests for Database Manager, Fernet encryption, and FTS search.
"""

import pytest
from shared.database import (
    init_db, get_db, get_config, set_config, delete_config,
    get_all_config, is_onboarded, fts_search
)
from shared.crypto import ConfigEncryptor


def test_database_init():
    init_db()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        assert "app_config" in tables
        assert "threads" in tables
        assert "events" in tables
        assert "signals" in tables
        assert "actionables" in tables
        assert "dragging_issues" in tables
        assert "summaries" in tables


def test_config_crud_and_encryption():
    set_config("test_plain_key", "plain_value", encrypt=False)
    assert get_config("test_plain_key") == "plain_value"

    set_config("test_secret_key", "secret_value_123", encrypt=True)
    assert get_config("test_secret_key") == "secret_value_123"

    all_cfg = get_all_config()
    assert "test_plain_key" in all_cfg
    assert "test_secret_key" in all_cfg

    delete_config("test_plain_key")
    delete_config("test_secret_key")
    assert get_config("test_plain_key") is None
    assert get_config("test_secret_key") is None


def test_fernet_crypto():
    encryptor = ConfigEncryptor()
    secret = "SuperSecretPassword123!"
    encrypted = encryptor.encrypt(secret)
    assert encrypted != secret
    decrypted = encryptor.decrypt(encrypted)
    assert decrypted == secret


def test_fts_search():
    init_db()
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO threads
               (thread_id, source, source_id, subject, participants, message_count,
                first_message_at, last_message_at, raw_text, team_name, channel_name, thread_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("th_test_fts_99", "teams", "src_99", "Critical Infrastructure Failure", "Alice, Bob", 3,
             "2026-07-25T10:00:00", "2026-07-25T10:15:00", "Server outage reported on east region database cluster.", "Infrastructure", "Alerts", "2026-07-25")
        )

    results = fts_search("database cluster", limit=5)
    assert len(results) >= 1
    assert any(r["thread_id"] == "th_test_fts_99" for r in results)
