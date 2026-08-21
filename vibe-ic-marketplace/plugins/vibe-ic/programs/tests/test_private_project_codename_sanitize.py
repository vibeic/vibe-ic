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


def _env(codename):
    e = {k: v for k, v in os.environ.items() if k != "VIBEIC_PROJECT_CODENAMES"}
    if codename is not None:
        e["VIBEIC_PROJECT_CODENAMES"] = codename
    return e


def _py(code: str, codename):
    return subprocess.run([sys.executable, "-c", code], cwd=str(_PROGRAMS),
                          capture_output=True, text=True, env=_env(codename))


# ── project_codenames(): env parsing + public-inert ─────────────────────────
def test_project_codenames_reads_env(monkeypatch):
    monkeypatch.setenv("VIBEIC_PROJECT_CODENAMES", "AB123, CD456 ,AB123")
    assert cpdk.project_codenames() == ("AB123", "CD456")  # trimmed + deduped


def test_project_codenames_public_has_no_fake(monkeypatch):
    monkeypatch.delenv("VIBEIC_PROJECT_CODENAMES", raising=False)
    assert FAKE not in cpdk.project_codenames()


# ── source_chip_agnostic: the codename EXTENDS the forbidden-token set ───────
def test_source_guard_forbids_codename_with_config():
    code = "import source_chip_agnostic_check as s; print(repr(s._FORBIDDEN_TOKENS))"
    assert FAKE in _py(code, FAKE).stdout
    assert FAKE not in _py(code, None).stdout


# ── practical_notes: the codename becomes a HARD rule + flags a doc ──────────
def test_specificity_rule_for_codename_with_config():
    code = ("import practical_notes_specificity_check as p;"
            "print([r[0] for r in p.HARD_RULES])")
    rid = f"project_codename_{FAKE.lower()}"
    assert rid in _py(code, FAKE).stdout
    assert rid not in _py(code, None).stdout


def test_specificity_flags_codename_in_a_doc(tmp_path):
    note = tmp_path / "PRACTICAL_NOTES.md"
    note.write_text(f"# Notes\nThe {FAKE} project uses the widget.\n")
    prog = str(_PROGRAMS / "practical_notes_specificity_check.py")
    r_off = subprocess.run([sys.executable, prog, "--paths", str(note)],
                           capture_output=True, text=True, env=_env(None))
    r_on = subprocess.run([sys.executable, prog, "--paths", str(note)],
                          capture_output=True, text=True, env=_env(FAKE))
    assert r_on.returncode != 0          # WITH config -> flagged
    assert r_off.returncode == 0         # WITHOUT -> this fictional token is clean


# ── backlog_sanitize: the codename is a HARD violation in a scanned field ────
def _backlog(tmp_path):
    b = tmp_path / "b.yaml"
    b.write_text("type: enhancement\n"
                 "component: program:widget\n"
                 f"title: improve the {FAKE} block throughput\n"
                 "pattern: describe-the-generic-fix\n"
                 "plugin_version: 1.5.30\n")
    return b


def test_backlog_sanitize_flags_codename_with_config(tmp_path):
    b = _backlog(tmp_path)
    prog = str(_PROGRAMS / "backlog_sanitize_check.py")
    jf = tmp_path / "on.json"
    subprocess.run([sys.executable, prog, "--file", str(b), "--json", str(jf)],
                   capture_output=True, text=True, env=_env(FAKE))
    assert FAKE in jf.read_text()        # the codename is reported as matched


def test_backlog_sanitize_public_does_not_flag_fake(tmp_path):
    b = _backlog(tmp_path)
    prog = str(_PROGRAMS / "backlog_sanitize_check.py")
    jf = tmp_path / "off.json"
    subprocess.run([sys.executable, prog, "--file", str(b), "--json", str(jf)],
                   capture_output=True, text=True, env=_env(None))
    off = json.loads(jf.read_text())
    matched = " ".join(f.get("matched", "") for f in off.get("findings", []))
    assert FAKE not in matched


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
