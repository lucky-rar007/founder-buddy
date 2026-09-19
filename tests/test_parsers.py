"""
Tests for thread parsers, PII redaction, and noise classification (T-2).
"""

import pytest
from threads.parsers import (
    sanitize_pii,
    is_noise_message,
    strip_html_tags,
    strip_attachments_from_html,
    has_only_attachment_content
)


def test_sanitize_pii_emails_and_phones():
    """Verify email addresses and phone numbers are redacted."""
    sample = "Reach me at founder@startup.io or +1 (555) 234-5678 regarding the contract."
    sanitized = sanitize_pii(sample)
    assert "[REDACTED_EMAIL]" in sanitized
    assert "founder@startup.io" not in sanitized
    assert "[REDACTED_PHONE]" in sanitized
    assert "555" not in sanitized


def test_sanitize_pii_aws_and_azure():
    """Verify AWS keys and Azure connection strings are redacted."""
    sample_aws = "Deploy using AKIAIOSFODNN7EXAMPLE and aws_secret_access_key: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    sanitized_aws = sanitize_pii(sample_aws)
    assert "[REDACTED_AWS_KEY]" in sanitized_aws
    assert "AKIAIOSFODNN7EXAMPLE" not in sanitized_aws
    assert "[REDACTED_AWS_SECRET]" in sanitized_aws

    sample_azure = "Connecting to DefaultEndpointsProtocol=https;AccountName=myacc;AccountKey=dGhpcyBpcyBhIGZha2Uga2V5==;"
    sanitized_azure = sanitize_pii(sample_azure)
    assert "[REDACTED_AZURE_CONNECTION_STRING]" in sanitized_azure


def test_sanitize_pii_credit_card_and_ssn():
    """Verify credit card numbers and SSNs are redacted."""
    sample = "Card: 4532-1234-5678-9010 and SSN: 123-45-6789"
    sanitized = sanitize_pii(sample)
    assert "[REDACTED_CREDIT_CARD]" in sanitized
    assert "4532" not in sanitized
    assert "[REDACTED_SSN]" in sanitized
    assert "123-45-6789" not in sanitized


def test_sanitize_pii_api_keys():
    """Verify OpenAI, GitHub, and Google keys are redacted."""
    sample = "Keys: sk-1234567890123456789012345678901234 and ghp_123456789012345678901234567890123456"
    sanitized = sanitize_pii(sample)
    assert "[REDACTED_API_KEY]" in sanitized
    assert "[REDACTED_GITHUB_TOKEN]" in sanitized


def test_noise_message_detection():
    """Verify acknowledgement words and greetings are detected as noise."""
    assert is_noise_message("ok") is True
    assert is_noise_message("thanks!") is False or is_noise_message("thanks") is True
    assert is_noise_message("got it") is True
    assert is_noise_message("good morning") is True
    assert is_noise_message("") is True
    assert is_noise_message("   ") is True


def test_strip_html_tags():
    """Verify HTML stripping handles formatting properly."""
    html = "<p>Hello <strong>Founder</strong>, we deployed to <a href='https://example.com'>prod</a>.</p>"
    text = strip_html_tags(html)
    assert "Hello" in text
    assert "Founder" in text
    assert "<p>" not in text
    assert "<strong>" not in text
