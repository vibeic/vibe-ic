#!/usr/bin/env python3
"""Tests for version_bump_monotonic_check.py — strict version-bump gate
(current > previous) + marketplace equality re-assert (chip-AGNOSTIC)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1] / "version_bump_monotonic_check.py"
_spec = importlib.util.spec_from_file_location("version_bump_monotonic_check", _PROG)
vbm = importlib.util.module_from_spec(_spec)
sys.modules["version_bump_monotonic_check"] = vbm
_spec.loader.exec_module(vbm)


# ---- explicit two-value compare (no git) --------------------------------
def test_pass_patch_bump():
    assert vbm.main(["--current", "0.2.14", "--previous", "0.2.13"]) == 0


def test_pass_minor_bump():
    assert vbm.main(["--current", "0.3.0", "--previous", "0.2.99"]) == 0


def test_pass_numeric_not_lexical():
    # 0.2.10 > 0.2.9 numerically (lexical would say the opposite).
    assert vbm.main(["--current", "0.2.10", "--previous", "0.2.9"]) == 0


def test_fail_no_bump_equal():
    assert vbm.main(["--current", "0.2.13", "--previous", "0.2.13"]) == 1


def test_fail_regression():
    assert vbm.main(["--current", "0.2.12", "--previous", "0.2.13"]) == 1


def test_error_unparseable_current():
    assert vbm.main(["--current", "garbage", "--previous", "0.2.13"]) == 2


def test_error_unparseable_previous():
    assert vbm.main(["--current", "0.2.14", "--previous", ""]) == 2


# ---- evaluate() equality re-assert --------------------------------------
def test_evaluate_equality_mismatch_fails():
    rep, rc = vbm.evaluate("0.2.14", "0.2.13", "0.2.13", equality_checked=True)
    assert rc == 1
    assert rep.equality_ok is False


def test_evaluate_equality_ok():
    rep, rc = vbm.evaluate("0.2.14", "0.2.13", "0.2.14", equality_checked=True)
    assert rc == 0
    assert rep.bump_ok is True
    assert rep.equality_ok is True


# ---- git-backed path (real synthetic repo) ------------------------------
def _git(repo: Path, *args):
    subprocess.run(["git", "-C", str(repo), *args],
                   check=True, capture_output=True, text=True)


def _stage_repo(tmp_path: Path, first_ver: str) -> Path:
    repo = tmp_path / "repo"
    pjdir = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / ".claude-plugin"
    pjdir.mkdir(parents=True)
    pj = pjdir / "plugin.json"
    pj.write_text(json.dumps({"name": "vibe-ic", "version": first_ver}) + "\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"v{first_ver}")
    return pj


def test_git_pass_after_bump(tmp_path):
    pj = _stage_repo(tmp_path, "0.2.13")
    # working-tree bump (not yet committed) -> compares vs HEAD = 0.2.13.
    pj.write_text(json.dumps({"name": "vibe-ic", "version": "0.2.14"}) + "\n")
    rc = vbm.main(["--plugin-json", str(pj), "--base", "HEAD"])
    assert rc == 0


def test_git_fail_when_not_bumped(tmp_path):
    pj = _stage_repo(tmp_path, "0.2.13")
    # forgot to bump -> working tree == HEAD == 0.2.13 -> FAIL.
    rc = vbm.main(["--plugin-json", str(pj), "--base", "HEAD"])
    assert rc == 1


def test_git_with_marketplace_equality(tmp_path):
    pj = _stage_repo(tmp_path, "0.2.13")
    pj.write_text(json.dumps({"name": "vibe-ic", "version": "0.2.14"}) + "\n")
    mj = tmp_path / "repo" / "vibe-ic-marketplace" / ".claude-plugin" / "marketplace.json"
    mj.parent.mkdir(parents=True, exist_ok=True)
    mj.write_text(json.dumps({"plugins": [{"name": "vibe-ic", "version": "0.2.14"}]}) + "\n")
    out = tmp_path / "r.json"
    rc = vbm.main(["--plugin-json", str(pj), "--marketplace-json", str(mj),
                   "--base", "HEAD", "--json", str(out)])
    assert rc == 0
    rep = json.loads(out.read_text())
    assert rep["passed"] is True
    assert rep["equality_ok"] is True


def test_git_marketplace_mismatch_fails(tmp_path):
    pj = _stage_repo(tmp_path, "0.2.13")
    pj.write_text(json.dumps({"name": "vibe-ic", "version": "0.2.14"}) + "\n")
    mj = tmp_path / "repo" / "vibe-ic-marketplace" / ".claude-plugin" / "marketplace.json"
    mj.parent.mkdir(parents=True, exist_ok=True)
    mj.write_text(json.dumps({"plugins": [{"name": "vibe-ic", "version": "0.2.13"}]}) + "\n")
    rc = vbm.main(["--plugin-json", str(pj), "--marketplace-json", str(mj),
                   "--base", "HEAD"])
    assert rc == 1


# ---- honest errors on absent input --------------------------------------
def test_missing_plugin_json_is_error(tmp_path):
    assert vbm.main(["--plugin-json", str(tmp_path / "nope.json")]) == 2


def test_no_args_is_error():
    assert vbm.main([]) == 2
