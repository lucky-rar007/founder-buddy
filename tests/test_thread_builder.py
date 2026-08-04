"""
Unit tests for Thread Builder & Parsers module.
"""

import pytest
from threads.parsers import (
    strip_html_tags,
    clean_message_body,
    extract_participants_from_teams,
    extract_participants_from_outlook
)
from threads.builder import ThreadBuilder


def test_strip_html_tags():
    raw_html = "<div><p>Hello <b>World</b>!</p><br><a href='http://example.com'>Link</a></div>"
    text = strip_html_tags(raw_html)
    assert "Hello" in text
    assert "World" in text
    assert "Link" in text
    assert "<div>" not in text


def test_clean_message_body():
    body_dict = {
        "contentType": "html",
        "content": "<p>Meeting notes update</p>"
    }
    cleaned = clean_message_body(body_dict)
    assert cleaned == "Meeting notes update"


def test_extract_participants_from_teams():
    msg = {
        "from": {"user": {"displayName": "Alice Smith"}},
        "replies": [
            {"from": {"user": {"displayName": "Bob Jones"}}},
            {"from": {"user": {"displayName": "Alice Smith"}}}
        ]
    }
    participants = extract_participants_from_teams(msg)
    assert "Alice Smith" in participants
    assert "Bob Jones" in participants
    assert len(participants) == 2


def test_extract_participants_from_outlook():
    email = {
        "from": {"emailAddress": {"name": "Arjun Patel"}},
        "toRecipients": [{"emailAddress": {"name": "David Kumar"}}],
        "ccRecipients": [{"emailAddress": {"name": "Priya Menon"}}]
    }
    participants = extract_participants_from_outlook(email)
    assert "Arjun Patel" in participants
    assert "David Kumar" in participants
    assert "Priya Menon" in participants
    assert len(participants) == 3


def test_thread_builder_init():
    builder = ThreadBuilder()
    assert builder.data_dir is not None
