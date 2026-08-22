#!/usr/bin/env python3
"""Tests for readme_vendor_extractor.py — best-effort vendor picker.

Pins the real priority order and the anti-placeholder contract:
  1. SPDX-FileCopyrightText (highest signal)
  2. Copyright (C) line
  3. Markdown authorship link  Maintainer: [name](url)
  4. Maintained|Authored|Designed by <name>  (with stop-word trim)
  5. github.com/<org>/<repo> badge (low confidence)
When no signal exists -> (None, None) so the caller emits
`vendor: null` + `no_vendor_in_input` rather than a "see datasheet"
placeholder. Junk tokens (TODO/TBD/N/A/numeric) are rejected.
"""
from __future__ import annotations

# programs/ is on sys.path via programs/tests/conftest.py.
import readme_vendor_extractor as mod  # noqa: E402

_extract = mod.extract_vendor


# ----------------------------------------------------------------------
# PASS — each pattern yields a real vendor token + evidence.
# ----------------------------------------------------------------------
def test_spdx_copyright_highest_priority():
    vendor, ev = _extract("SPDX-FileCopyrightText: 2021 Acme Corp <a@b.c>")
    assert vendor == "Acme Corp"
    assert ev["extraction_strategy"] == "spdx_copyright_match"
    assert "low_confidence" not in ev


def test_copyright_line():
    vendor, ev = _extract("Copyright (C) 2020 Widget Labs.")
    assert vendor and "Widget" in vendor
    assert ev["extraction_strategy"] == "copyright_line_match"


def test_authorship_link():
    vendor, ev = _extract("Maintainer: [Jane Roe](https://example.com)")
    assert vendor and "Jane" in vendor
    assert ev["extraction_strategy"] == "authorship_link_match"


def test_author_line_stopword_trim():
    # The non-greedy capture must stop at the continuation conjunction
    # so the vendor stays clean ("Foo Bar"), not the whole prose tail.
    vendor, ev = _extract("Maintained by Foo Bar but is not part of X")
    assert vendor == "Foo Bar"
    assert ev["extraction_strategy"] == "author_line_match_v1_6_393"


def test_github_badge_low_confidence():
    vendor, ev = _extract("badge https://github.com/openhwgroup/cv32e40p")
    assert vendor == "openhwgroup"
    assert ev["extraction_strategy"] == "github_badge_org_match"
    assert ev["low_confidence"] is True


def test_priority_spdx_beats_github():
    txt = ("SPDX-FileCopyrightText: 2019 RealVendor\n"
           "repo: github.com/someorg/somerepo")
    vendor, ev = _extract(txt)
    assert vendor == "RealVendor"
    assert ev["extraction_strategy"] == "spdx_copyright_match"


# ----------------------------------------------------------------------
# FAIL / anti-placeholder — no signal -> (None, None), never a guess.
# ----------------------------------------------------------------------
def test_no_signal_returns_none():
    assert _extract("This is a generic README with no authorship.") == \
        (None, None)


def test_empty_string_returns_none():
    assert _extract("") == (None, None)


def test_junk_token_rejected():
    # "TODO" is junk -> the copyright pattern match is discarded, and
    # nothing else matches -> (None, None).
    assert _extract("Copyright (C) 2021 TODO") == (None, None)


# ----------------------------------------------------------------------
# helper-level behavior.
# ----------------------------------------------------------------------
def test_is_junk_helper():
    assert mod._is_junk("TBD") is True
    assert mod._is_junk("123") is True       # all-numeric
    assert mod._is_junk("a") is True         # too short
    assert mod._is_junk("Acme") is False


def test_trim_vendor_capture_caps_four_tokens():
    out = mod._v1_6_393_trim_vendor_capture("One Two Three Four Five Six.")
    assert out == "One Two Three Four"
