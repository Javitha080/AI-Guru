"""User-friendly tests for CORS origin normalization.

In plain language: operators paste origins in all kinds of shapes
("host:port", trailing slashes, semicolon lists). Browsers always send a
strict `scheme://host[:port]` Origin, so this helper tidies deployment
input into exact origins — while leaving "*" and "null" untouched.
"""

from __future__ import annotations

from deeptutor.services.config.origins import normalize_origin, normalize_origins


def test_bare_host_gets_http_scheme():
    assert normalize_origin("example.com:8001") == "http://example.com:8001"


def test_trailing_slashes_and_paths_are_trimmed_to_origin():
    assert normalize_origin("https://example.com/parent/") == "https://example.com"


def test_wildcard_and_null_pass_through():
    assert normalize_origin("*") == "*"
    assert normalize_origin("null") == "null"


def test_empty_input_stays_empty():
    assert normalize_origin("") == ""
    assert normalize_origin(None) == ""
    assert normalize_origin("   ") == ""


def test_lists_split_dedupe_and_drop_empties():
    assert normalize_origins("http://a:1; http://a:1, http://b:2\n") == [
        "http://a:1",
        "http://b:2",
    ]
    assert normalize_origins(["http://a:1", ["http://b:2", "http://a:1"]]) == [
        "http://a:1",
        "http://b:2",
    ]
    assert normalize_origins(None) == []
