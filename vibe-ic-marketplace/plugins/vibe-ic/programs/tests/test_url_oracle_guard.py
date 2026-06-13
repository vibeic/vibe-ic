#!/usr/bin/env python3
"""Tests for url_oracle_guard.py — RTL-as-oracle prohibition helpers.

Pins the real decision logic of the cited-URL guard:
  * The project's own GitHub repo is identified from README badges/links.
  * Any URL pointing back into that self-repo is DENIED (the benchmark
    forbids using the IP's own RTL as a data source — the oracle).
  * Public-standard hosts (NIST / IETF / JEDEC / IEEE / SD-A / PCI-SIG /
    SATA-IO / USB-IF / ISO / OpenCores) are ALLOWED.
  * Every other host is neutral (allowed, caller decides).

logic-pinned: each assertion exercises a real branch of url_allowed /
parse_project_self_repo / is_self_repo_url / is_public_standard_url.
"""
from __future__ import annotations

import url_oracle_guard as g


# ── parse_project_self_repo ──────────────────────────────────────────
def test_parse_self_repo_from_badges_and_links():
    readme = (
        "[![CI](badge)](https://github.com/litex-hub/litesata/actions)\n"
        "See https://github.com/litex-hub/litesata for source.\n"
        "Standard: https://sata-io.org/spec\n"
    )
    # Most-mentioned org/repo wins.
    assert g.parse_project_self_repo(readme) == "litex-hub/litesata"


def test_parse_self_repo_skips_reserved_owners():
    # github.com/orgs/<x> is a sub-page, not a repo — must be ignored.
    assert g.parse_project_self_repo("https://github.com/orgs/foo") is None


def test_parse_self_repo_empty_returns_none():
    assert g.parse_project_self_repo("") is None
    assert g.parse_project_self_repo("no github urls here at all") is None


# ── is_self_repo_url ─────────────────────────────────────────────────
def test_self_repo_subpaths_match():
    repo = "litex-hub/litesata"
    assert g.is_self_repo_url("https://github.com/litex-hub/litesata", repo)
    assert g.is_self_repo_url(
        "https://github.com/litex-hub/litesata/blob/main/x.v", repo)
    assert g.is_self_repo_url(
        "https://raw.githubusercontent.com/litex-hub/litesata/main/x.v", repo)


def test_self_repo_no_self_known_cannot_fire():
    # Caller doesn't know the project's own repo -> deny rule cannot fire.
    assert g.is_self_repo_url("https://github.com/x/y", None) is False


def test_self_repo_other_repo_not_matched():
    assert g.is_self_repo_url(
        "https://github.com/other/project", "litex-hub/litesata") is False


# ── is_public_standard_url ───────────────────────────────────────────
def test_public_standard_hosts_recognized():
    assert g.is_public_standard_url("https://sata-io.org/spec")
    assert g.is_public_standard_url("https://csrc.nist.gov/pubs/x")
    assert g.is_public_standard_url("") is False
    assert g.is_public_standard_url("https://acme.example.com/x") is False


# ── url_allowed — the composed policy (PASS / FAIL / neutral) ─────────
def test_url_allowed_self_repo_denied():
    # The exact defect this guards: an URL into the project's own RTL repo.
    allowed, reason = g.url_allowed(
        "https://github.com/litex-hub/litesata/blob/main/litesata.v",
        "litex-hub/litesata")
    assert allowed is False
    assert reason == "self_repo_denied"


def test_url_allowed_public_standard_allowed():
    allowed, reason = g.url_allowed("https://sata-io.org/spec",
                                    "litex-hub/litesata")
    assert allowed is True
    assert reason == "public_standard_allowed"


def test_url_allowed_unknown_host_neutral():
    allowed, reason = g.url_allowed("https://acme.example.com/datasheet",
                                    "litex-hub/litesata")
    assert allowed is True
    assert reason == "unknown_host_neutral"
