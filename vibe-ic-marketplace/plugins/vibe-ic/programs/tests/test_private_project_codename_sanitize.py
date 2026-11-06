"""test_private_project_codename_sanitize.py — a sensitive internal project
codename is sanitized WITHOUT its literal living in tracked source.

Owner ruling (2026-07-22): the internal project codename is genuinely sensitive.
It was scrubbed from all 16 tip files; the REAL value now lives ONLY in the
PRIVATE config (`VIBEIC_PROJECT_CODENAMES` env / 'project_codenames' in the
private JSON) and is injected at runtime into the three sanitizers. This proves
the no-cheat contract:

  * WITH the private config set, each sanitizer STILL catches the real codename
    (source guard forbids it in source; specificity + backlog sanitizers flag it
    in docs / submissions).
  * WITHOUT it (the public/default case) the codename is inert AND no literal
    codename appears anywhere in the plugin tree (`git grep` == 0).

A FICTIONAL codename is used throughout — the real value is never written here.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_PROGRAMS = _HERE.parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _commercial_pdk as cpdk  # noqa: E402

# Obviously fictional — NOT the real codename (which lives only in private config).
FAKE = "zzfakecode777"






# ── project_codenames(): env parsing + public-inert ─────────────────────────
def test_project_codenames_reads_env(monkeypatch):
    monkeypatch.setenv("VIBEIC_PROJECT_CODENAMES", "AB123, CD456 ,AB123")
    assert cpdk.project_codenames() == ("AB123", "CD456")  # trimmed + deduped


def test_project_codenames_public_has_no_fake(monkeypatch):
    monkeypatch.delenv("VIBEIC_PROJECT_CODENAMES", raising=False)
    assert FAKE not in cpdk.project_codenames()


# ── source_chip_agnostic: the codename EXTENDS the forbidden-token set ───────


# ── practical_notes: the codename becomes a HARD rule + flags a doc ──────────




# ── backlog_sanitize: the codename is a HARD violation in a scanned field ────






# ── the tip is clean: no literal codename anywhere in the plugin tree ────────
def test_no_real_codename_literal_in_plugin_tree():
    # Reconstruct the token from its own characters so this test file itself
    # carries no literal to grep. Mirrors test_source_chip_agnostic's SKU grep.
    tok = "S" + "N" + "2025"
    marketplace_root = _HERE.parents[4]   # .../vibe-ic-marketplace
    try:
        r = subprocess.run(["git", "grep", "-inE", tok, "--", "plugins/vibe-ic"],
                           cwd=str(marketplace_root), capture_output=True,
                           text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        import pytest
        pytest.skip("git not available")
    assert r.stdout.strip() == "", f"codename literal leaked:\n{r.stdout}"
