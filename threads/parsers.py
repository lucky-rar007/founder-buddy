"""
Parsing and Text Extraction Utilities for Thread Builder.

Handles HTML stripping, attachment removal, whitespace normalization,
and recipient/sender parsing.
"""

from __future__ import annotations

import re
from typing import Any
from bs4 import BeautifulSoup

# Attachment MIME type prefixes to silently ignore
_ATTACHMENT_TYPES = (
    "image/", "video/", "audio/", "application/pdf",
    "application/vnd", "application/zip", "application/octet-stream"
)


def strip_html_tags(html_content: str) -> str:
    """
    Strips HTML tags and normalizes whitespace.
    """
    if not html_content:
        return ""
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        for element in soup(["script", "style"]):
            element.decompose()
        text = soup.get_text(separator=" ", strip=True)
        # Collapse multiple spaces or newlines into a single space
        return re.sub(r"\s+", " ", text).strip()
    except Exception:
        # Fallback regex strip
        return re.sub(r"<[^>]+>", " ", html_content).strip()


def strip_attachments_from_html(html_content: str) -> str:
    """
    Removes attachment-related HTML elements from Teams/Outlook message bodies
    before text extraction. Handles:
      - <attachment> tags (Teams file/image cards)
      - <img> tags (inline images, base64 or URL-referenced)
      - <div> blocks with attachment-related classes (adaptive cards, file previews)
      - Base64-encoded image data URIs
    Returns cleaned HTML ready for strip_html_tags().
    """
    if not html_content:
        return ""
    try:
        soup = BeautifulSoup(html_content, "html.parser")

        # Remove Teams <attachment> card elements
        for tag in soup.find_all("attachment"):
            tag.decompose()

        # Remove all <img> tags (inline images, avatars, base64 blobs)
        for tag in soup.find_all("img"):
            tag.decompose()

        # Remove <div> blocks that are file/image attachment containers
        attachment_class_patterns = [
            "attachment", "fileCard", "file-card", "img-container",
            "imageContainer", "adaptiveCard", "adaptive-card",
            "fileAttachment", "thumbnailContainer"
        ]
        for div in soup.find_all("div"):
            div_class = " ".join(div.get("class", []))
            if any(p.lower() in div_class.lower() for p in attachment_class_patterns):
                div.decompose()

        # Remove <figure> and <picture> elements (image wrappers)
        for tag in soup.find_all(["figure", "picture", "video", "audio", "source"]):
            tag.decompose()

        return str(soup)
    except Exception:
        # Fallback: strip base64 data URIs with regex
        html_content = re.sub(r'src="data:[^"]+"', 'src="[ATTACHMENT_REMOVED]"', html_content)
        return html_content


def has_only_attachment_content(body_dict: dict[str, Any], attachments: list[dict]) -> bool:
    """
    Returns True if a Teams message body contains nothing except an attachment reference
    (i.e., the entire message content is a file share / image drop with no text).
    """
    if not attachments:
        return False

    content = body_dict.get("content", "")
    content_type = body_dict.get("contentType", "text").lower()

    if content_type != "html":
        return False

    # Strip attachment elements and check if any human text remains
    cleaned_html = strip_attachments_from_html(content)
    remaining_text = strip_html_tags(cleaned_html).strip()

    return len(remaining_text) < 5  # Only whitespace/empty left after stripping attachments


def sanitize_pii(text: str) -> str:
    """
    Scrubs sensitive credentials, API keys, passwords, credit card numbers,
    and SSNs before persisting or sending to LLMs.
    """
    if not text:
        return ""

    # Common API key patterns (Google AIzaSy, OpenAI sk-..., GitHub ghp_, JWT tokens)
    text = re.sub(r"AIzaSy[A-Za-z0-9_-]{33}", "[REDACTED_API_KEY]", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]{32,}", "[REDACTED_API_KEY]", text)
    text = re.sub(r"ghp_[A-Za-z0-9]{36}", "[REDACTED_GITHUB_TOKEN]", text)
    text = re.sub(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}", "[REDACTED_JWT_TOKEN]", text)

    # Passwords in plain text
    text = re.sub(r"(?i)\b(password|passwd|pwd|secret_key)\s*[:=]\s*[^\s]+", r"\1: [REDACTED_SECRET]", text)

    # Credit card numbers (13-16 digits with optional spaces/dashes)
    text = re.sub(r"\b(?:\d[ -]*?){13,16}\b", "[REDACTED_CREDIT_CARD]", text)

    # US Social Security Numbers
    text = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]", text)

    return text


def is_noise_message(text: str) -> bool:
    """
    Identifies non-actionable chit-chat, memes, automated greetings, or ultra-short system noise.
    Combines rule-based checks with the local ONNX classifier.
    """
    if not text or not text.strip():
        return True

    clean = text.strip().lower()
    
    # Ultra-short acknowledgement/greeting phrases
    noise_phrases = {
        "ok", "okay", "k", "thx", "thanks", "ty", "cool", "got it",
        "lol", "lmao", "haha", "hahaha", "nice", "yep", "yes", "no",
        "good morning", "good evening", "happy friday", "have a good weekend"
    }

    if clean in noise_phrases:
        return True

    # If text is strictly less than 4 characters and has no digits/letters
    if len(clean) < 4 and not re.search(r"[a-z0-9]", clean):
        return True

    # Run Local ONNX Classifier
    try:
        from threads.classifier import local_classifier
        result = local_classifier.classify_message(text)
        return result.get("is_noise", False)
    except Exception:
        return False


def clean_message_body(body_dict: dict[str, Any], attachments: list[dict] | None = None) -> str:
    """
    Extracts text from message body dictionary (Teams or Outlook),
    strips attachment elements, strips HTML, and scrubs PII.

    Args:
        body_dict: The message body object with 'content' and 'contentType' fields.
        attachments: Optional list of attachment metadata dicts from the message.
                     When provided, attachment-only messages return empty string.
    """
    if not body_dict:
        return ""

    content = body_dict.get("content", "")
    content_type = body_dict.get("contentType", "text").lower()

    if content_type == "html":
        # Remove attachment elements before extracting text
        content = strip_attachments_from_html(content)
        raw_text = strip_html_tags(content)
    else:
        raw_text = content.strip()

    return sanitize_pii(raw_text)


def extract_participants_from_teams(msg: dict[str, Any]) -> set[str]:
    """
    Extract unique participant names from a Teams root message and its replies.
    """
    participants = set()
    
    # Root message sender
    from_info = msg.get("from", {})
    if from_info and from_info.get("user"):
        participants.add(from_info["user"].get("displayName", "Unknown"))

    # Replies senders
    replies = msg.get("replies", [])
    for reply in replies:
        r_from = reply.get("from", {})
        if r_from and r_from.get("user"):
            participants.add(r_from["user"].get("displayName", "Unknown"))

    return participants


def extract_participants_from_outlook(email: dict[str, Any]) -> set[str]:
    """
    Extract unique participant names from an Outlook email (from, to, and cc).
    """
    participants = set()

    # From sender
    sender = email.get("from", {}).get("emailAddress", {}).get("name", "")
    if sender:
        participants.add(sender)

    # To recipients
    for recip in email.get("toRecipients", []):
        name = recip.get("emailAddress", {}).get("name", "")
        if name:
            participants.add(name)

    # Cc recipients
    for recip in email.get("ccRecipients", []):
        name = recip.get("emailAddress", {}).get("name", "")
        if name:
            participants.add(name)

    return participants
