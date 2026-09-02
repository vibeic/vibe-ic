"""test_nda_diff_scan_check.py — §4.05 proofs for the diff-CONTENT NDA guard.

This guard closes the surface the two existing NDA guards miss: the CONTENT a
PR adds (every `+` line and every added/renamed PATH), anywhere in the repo —
not just the plugin source tree (`source_chip_agnostic_check`) or the commit
message (`commit_msg_nda_check`). #247 landed with a SKU + IP-vendor part in a
test fixture's CONTENT and in a fixture FILENAME; both slipped every prior gate.

§4.05 requires BOTH directions, or the gate is decorative:

  POSITIVE — a diff that adds only ordinary / generic content ("commercial PDK",
             "OTP_vendor", "commercial_otp_macro") is ACCEPTED (rc 0). A guard
             that fails these is unusable.
  NEGATIVE — a diff whose ADDED line or ADDED path names the SKU / brand /
             process / IP-vendor is REJECTED (rc != 0), in --rev-range,
             --diff-file and --stdin mode; a REMOVED (`-`) token (a scrub
             commit) is NOT flagged.

Every leak string is RECONSTRUCTED AT RUNTIME from `_commercial_pdk`'s encoded
store — no literal NDA token appears in this file (a test that spelled one out
would itself be the leak it tests for and would trip the source guard).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_PLUGIN_ROOT = _HERE.parents[2]
_PROGRAMS = _PLUGIN_ROOT / "programs"

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _commercial_pdk as cpdk  # noqa: E402
from _nda_fixture_tokens import FICTIONAL_NDA_TOKENS  # noqa: E402
import nda_diff_scan_check as guard  # noqa: E402

_CHECKER = _PROGRAMS / "nda_diff_scan_check.py"


# ---------------------------------------------------------------------------
# THIS MODULE OWNS THE TOKEN STORE IT MEASURES AGAINST.
#
# Every leak string below is built from `FICTIONAL_NDA_TOKENS`, so the guard
# under test has to be looking for THAT set or the experiment is not the one
# the assertions describe. `programs/tests/conftest.py` publishes exactly that
# set — but with `os.environ.setdefault`, and deliberately so: "a host that
# genuinely has the real tokens configured keeps them, so the suite measures
# that host as it is." That is right for the suite and WRONG for this file: on
# a configured host — which the landing tier is, because `_commercial_pdk`
# hands `VIBEIC_NDA_TOKENS` "to a gate subprocess through the environment" —
# `setdefault` loses, the guard hunts the real tokens, and every negative case
# here presents a fictional one it was never told to look for.
#
# MEASURED on this file, on unmodified main, with an ambient store exported:
#
#     7 failed, 6 passed        (13 passed with the variable unset)
#
# and identically for a store of the REAL tokens and for one of foreign-but-
# well-shaped values, in the pinned image and on the host: the defect is that
# the ambient set and the fixture set DIFFER, not what either one says.
#
# All SEVEN cases that assert a leak IS caught fail. The six survivors are the
# five that assert nothing is flagged (clean content, a `-` line, a substring)
# plus the unreadable-input case — none of them presents a token, so none of
# them can see the disagreement, and the file's own positives cannot detect it.
#
# That is the same defect `test_commit_msg_nda_check.py` carries the fix for:
# there, 10 negatives failing hit `--maxfail=10` and truncated the session at
# item 26 of 90, and a truncated session is NORECORD — UNKNOWN, not clean.
# `test_the_norecord_causes_stay_fixed.py` pins that module's idiom by name.
# This file builds its leak strings the same way, from the same set, and was
# left deferring to the ambient store.
#
# SCOPED, not global. A function-scoped autouse `monkeypatch` sets the variable
# for THIS module's tests and restores it afterwards, so the conftest's policy
# is untouched for every other file and nothing here depends on collection
# order. `_nda_token_map()` re-reads the environment on every call and never
# caches at import, so the override reaches both the in-process `guard.*` calls
# and every checker subprocess `_run` spawns, which inherit this environment.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _fictional_token_store(monkeypatch):
    monkeypatch.setenv("VIBEIC_NDA_TOKENS", json.dumps(FICTIONAL_NDA_TOKENS))


def _tok(role: str) -> str:
    """The fixture's token for `role` — never a real literal here.

    Was a decode of the real token out of the shipped plugin store. That store
    is gone; the suite supplies its own fictional set through the private-config
    channel, so this test no longer depends on a secret to run."""
    return FICTIONAL_NDA_TOKENS[role]


def _run(args, cwd=None, input_text=None):
    proc = subprocess.run([sys.executable, str(_CHECKER), *args],
                          capture_output=True, text=True, cwd=cwd,
                          input=input_text)
    return proc.returncode, proc.stdout, proc.stderr


def _git(repo: Path, *args, env=None):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True, env=env)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    return repo


# ── in-process unit tests: scan_unified_diff ────────────────────────────────
def test_added_line_with_sku_is_flagged():
    diff = ("+++ b/programs/x.py\n"
            f"+j_max = 2.0  # {_tok('sku_full')} SOA limit\n")
    findings = guard.scan_unified_diff(diff)
    assert findings and findings[0].kind == "added-line"
    assert findings[0].role == "sku_full"
    # masked — the literal token never appears in the finding.
    assert _tok("sku_full") not in findings[0].masked_context
    assert "<NDA-TOKEN:sku_full>" in findings[0].masked_context


def test_added_ip_vendor_is_flagged():
    diff = f"+++ b/a.md\n+the {_tok('ip_vendor')} OTP macro reference\n"
    roles = {f.role for f in guard.scan_unified_diff(diff)}
    assert "ip_vendor" in roles


def test_added_filename_with_part_is_flagged():
    # #247's exact filename-leak shape: the part number IN the path.
    diff = (f"diff --git a/x b/rtl/{_tok('ip_part')}_M3.lef\n"
            f"new file mode 100644\n"
            f"+++ b/rtl/{_tok('ip_part')}_M3.lef\n"
            "+MACRO m\n")
    findings = guard.scan_unified_diff(diff)
    assert any(f.kind == "added-path" and f.role == "ip_part"
               for f in findings), "leaked FILENAME not flagged"


def test_removed_line_with_token_is_not_flagged():
    # a scrub commit legitimately shows the token on a `-` line.
    diff = (f"+++ b/x.py\n-old = '{_tok('sku_full')}'\n"
            "+new = 'commercial_pdk'\n")
    assert guard.scan_unified_diff(diff) == []


def test_generic_added_content_passes():
    diff = ("+++ b/x.py\n"
            "+# a commercial PDK / commercial foundry OTP_vendor run\n"
            "+name = 'commercial_otp_macro'\n")
    assert guard.scan_unified_diff(diff) == []


def test_url_substring_is_not_a_false_positive():
    # A spec-doc URL embeds the vendor name inside a LONGER word — must NOT trip
    # the ip_vendor token (word-boundary rule). The false-positive string is
    # BUILT at runtime from the token so no literal vendor substring lives in
    # this test file (which would itself trip the SKU-literal source grep).
    embedded = "th" + _tok("ip_vendor") + "forum"        # e.g. "…Memory…forum"
    diff = f"+++ b/benchmark-data/spec.txt\n+see http://x/events/{embedded}/mike.pdf\n"
    assert guard.scan_unified_diff(diff) == []


# ── CLI: --stdin / --diff-file ──────────────────────────────────────────────
def test_stdin_leak_fails_and_masks(tmp_path):
    diff = f"+++ b/x.py\n+x = '{_tok('foundry_brand1')}'\n"
    rc, out, err = _run(["--stdin"], input_text=diff)
    assert rc == 1
    assert _tok("foundry_brand1") not in (out + err)   # masked in output
    assert "NDA-TOKEN" in err


def test_stdin_generic_passes():
    rc, out, err = _run(["--stdin"], input_text="+++ b/x\n+commercial foundry\n")
    assert rc == 0


def test_diff_file_mode(tmp_path):
    d = tmp_path / "p.diff"
    d.write_text(f"+++ b/x\n+use {_tok('foundry_product')} deck\n")
    rc, _, _ = _run(["--diff-file", str(d)])
    assert rc == 1
    rc2, _, _ = _run(["--diff-file", str(tmp_path / "missing.diff")])
    assert rc2 == 2   # unreadable input FAILS LOUD


# ── CLI: --rev-range against a real temp repo ───────────────────────────────
def test_rev_range_leak_fails(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "f.py").write_text("clean = 1\n")
    _git(repo, "add", "f.py"); _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "f.py").write_text(f"clean = 1\nleak = '{_tok('sku_prefix')}'\n")
    _git(repo, "add", "f.py"); _git(repo, "commit", "-qm", "add feature")
    rc, out, err = _run(["--repo", str(repo), "--rev-range", f"{base}..HEAD"])
    assert rc == 1
    assert _tok("sku_prefix") not in (out + err)


def test_rev_range_generic_passes(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "f.py").write_text("clean = 1\n")
    _git(repo, "add", "f.py"); _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "f.py").write_text("clean = 1\n# a commercial PDK note\n")
    _git(repo, "add", "f.py"); _git(repo, "commit", "-qm", "generic add")
    rc, _, _ = _run(["--repo", str(repo), "--rev-range", f"{base}..HEAD"])
    assert rc == 0


def test_rev_range_renamed_leaked_filename_fails(tmp_path):
    # a file renamed INTO a leaked name must be caught via the rename header.
    repo = _init_repo(tmp_path)
    (repo / "macro.lef").write_text("MACRO m\nEND m\n")
    _git(repo, "add", "macro.lef"); _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "mv", "macro.lef", f"{_tok('ip_part')}_M3.lef")
    _git(repo, "commit", "-qm", "rename")
    rc, out, err = _run(["--repo", str(repo), "--rev-range", f"{base}..HEAD"])
    assert rc == 1
    assert "added-path" in err or "NDA-TOKEN" in err


def test_unwalkable_range_errors_loud(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "f").write_text("x\n"); _git(repo, "add", "f")
    _git(repo, "commit", "-qm", "base")
    rc, _, _ = _run(["--repo", str(repo), "--rev-range", "nope..alsonope"])
    assert rc == 2   # a range that cannot be diffed FAILS LOUD, never silent-clean
