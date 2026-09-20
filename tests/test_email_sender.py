"""Sanity tests for src/email_sender.py's recipient parsing - no network
or real credentials needed.

Run with:  python -m tests.test_email_sender
"""
from __future__ import annotations

from src.email_sender import _parse_recipients


def test_parse_recipients_single_address():
    assert _parse_recipients("blake@example.com") == ["blake@example.com"]
    print("test_parse_recipients_single_address: OK")


def test_parse_recipients_multiple_addresses_with_spaces():
    assert _parse_recipients("blake@example.com, dad@example.com") == [
        "blake@example.com",
        "dad@example.com",
    ]
    print("test_parse_recipients_multiple_addresses_with_spaces: OK")


def test_parse_recipients_drops_empty_entries_from_stray_commas():
    assert _parse_recipients("blake@example.com,,dad@example.com,") == [
        "blake@example.com",
        "dad@example.com",
    ]
    print("test_parse_recipients_drops_empty_entries_from_stray_commas: OK")


def test_parse_recipients_empty_string_yields_no_recipients():
    assert _parse_recipients("") == []
    print("test_parse_recipients_empty_string_yields_no_recipients: OK")


if __name__ == "__main__":
    test_parse_recipients_single_address()
    test_parse_recipients_multiple_addresses_with_spaces()
    test_parse_recipients_drops_empty_entries_from_stray_commas()
    test_parse_recipients_empty_string_yields_no_recipients()
    print("All tests passed.")
