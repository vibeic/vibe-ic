"""An attribution gate that has never fired is indistinguishable from none.

vibe-ic#1043. The load-bearing tests are the ones where a bundled work is
PLANTED without a NOTICE entry and the gate has to catch it — and the ones that
stop it from being satisfied by a NOTICE that says nothing.

The gate walks a real tree and reads real files, so every fixture here is a
real tree on disk rather than a stubbed scan: what is being tested is whether
the gate can SEE a file, which a stub cannot answer.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import bundled_attribution_notice_check as bc  # noqa: E402

_T = 55

_OURS = """Vibe-IC
Copyright 2026 VibeIC.AI Contributors

Licensed under the Apache License, Version 2.0.
"""

_THIRD_PARTY_RTL = """// Copyright lowRISC contributors (OpenTitan project).
// SPDX-License-Identifier: Apache-2.0
module aes_core; endmodule
"""

_OUR_RTL = """// Copyright 2026 VibeIC.AI Contributors
// SPDX-License-Identifier: Apache-2.0
module ours; endmodule
"""


def _tree(tmp_path: Path, notice: str, files: dict) -> Path:
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    (root / "NOTICE").write_text(notice)
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


# --------------------------------------------------------------------------
# THE CONTROL: a bundled work with no NOTICE entry.
# --------------------------------------------------------------------------

def test_it_fires_on_a_bundled_work_absent_from_notice(tmp_path, capsys):
    root = _tree(tmp_path, _OURS, {"vendor/aes.sv": _THIRD_PARTY_RTL})
    rc = bc.main([str(root)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "lowRISC" in out and "vendor/aes.sv" in out, out
    assert "1 file(s), Apache-2.0" in out, out


def test_it_passes_once_the_holder_is_named(tmp_path, capsys):
    """The other arm. Same tree, same file — only NOTICE differs, and only
    NOTICE decides."""
    notice = _OURS + "\nBUNDLED: lowRISC contributors (OpenTitan project), Apache-2.0\n"
    root = _tree(tmp_path, notice, {"vendor/aes.sv": _THIRD_PARTY_RTL})
    rc = bc.main([str(root)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "every bundled third-party holder is named" in out, out


def test_our_OWN_files_are_not_third_party(tmp_path, capsys):
    """The repository's own copyright is read out of NOTICE itself, so renaming
    the project cannot silently turn our own files into unattributed bundled
    works — and the gate carries no project name of its own to drift from the
    real one."""
    root = _tree(tmp_path, _OURS, {"src/ours.v": _OUR_RTL})
    rc = bc.main([str(root)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "VibeIC.AI Contributors" in out, out


# --------------------------------------------------------------------------
# The ways this gate could be satisfied without meaning anything.
# --------------------------------------------------------------------------

def test_a_tree_with_no_spdx_source_REFUSES_instead_of_passing(tmp_path, capsys):
    """A census over nothing matches an empty NOTICE trivially. Scoring that
    PASS is the confident zero this repo keeps finding."""
    root = _tree(tmp_path, _OURS, {"README.md": "no code here"})
    rc = bc.main([str(root)])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "REFUSE" in out and "establishes nothing" in out, out


def test_a_missing_NOTICE_is_a_FAIL_not_a_pass(tmp_path, capsys):
    root = tmp_path / "repo"
    (root / "vendor").mkdir(parents=True)
    (root / "vendor" / "aes.sv").write_text(_THIRD_PARTY_RTL)
    rc = bc.main([str(root)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "no NOTICE" in out, out


def test_naming_a_DIFFERENT_holder_does_not_satisfy_it(tmp_path, capsys):
    """A NOTICE section that lists somebody else must not launder the one that
    is actually bundled."""
    notice = _OURS + "\nBUNDLED: Efabless Corporation, Apache-2.0\n"
    root = _tree(tmp_path, notice, {"vendor/aes.sv": _THIRD_PARTY_RTL})
    rc = bc.main([str(root)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "lowRISC" in out, out


# --------------------------------------------------------------------------
# Shape of the scan.
# --------------------------------------------------------------------------

def test_it_reads_BOTH_copyright_spellings(tmp_path, capsys):
    """Upstreams use `Copyright` and `SPDX-FileCopyrightText` interchangeably.
    A gate that saw one would report a confident zero on a tree full of the
    other — measured: the bundled Efabless and Olof Kindgren files in this repo
    use the SPDX spelling, the lowRISC ones use the bare word."""
    spdx_style = ("// SPDX-FileCopyrightText: 2020 Efabless Corporation\n"
                  "// SPDX-License-Identifier: Apache-2.0\n"
                  "module m; endmodule\n")
    root = _tree(tmp_path, _OURS, {"vendor/e.v": spdx_style})
    rc = bc.main([str(root)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "Efabless" in out, out


@pytest.mark.parametrize("suffix", [".sv", ".v", ".tcl", ".py", ".c"])
def test_a_licence_header_binds_in_any_bundled_source(tmp_path, capsys, suffix):
    """A header in a build script binds exactly as one in RTL does. The
    OpenTitan reference flow bundled here is `.tcl`, and scoping the scan to
    HDL would have missed it — measured, 386 of the lowRISC files."""
    root = _tree(tmp_path, _OURS, {f"vendor/x{suffix}": _THIRD_PARTY_RTL})
    assert bc.main([str(root)]) == 1, capsys.readouterr().out


def test_the_distinctive_token_is_DERIVED_not_listed():
    """The token NOTICE must carry comes from the holder string, so a new
    upstream needs no edit to this gate. A hardcoded list of the upstreams
    bundled today would pass forever on the fifth one."""
    assert bc._distinctive("lowRISC contributors (OpenTitan project)") == "lowRISC"
    assert bc._distinctive("The SkyWater PDK Authors") == "SkyWater"
    assert bc._distinctive("Efabless Corporation") == "Efabless"
    assert bc._distinctive("2020 Efabless Corporation") == "Efabless"
    src = (_PROGRAMS / "bundled_attribution_notice_check.py").read_text()
    for name in ("lowRISC", "Efabless", "SkyWater", "Kindgren", "opentitan"):
        assert f'"{name}"' not in src, (
            f"{name!r} is spelled as a literal in the gate; the set of bundled "
            f"upstreams must be discovered, not listed, or the gate rots the "
            f"first time a new one is vendored")


def test_the_report_names_every_holder_and_its_licence(tmp_path):
    root = _tree(tmp_path, _OURS, {"vendor/aes.sv": _THIRD_PARTY_RTL})
    out = tmp_path / "r.json"
    bc.main([str(root), "--json", str(out)])
    doc = json.loads(out.read_text())
    assert doc["spdx_files"] == 1
    assert doc["own_holders"] == ["VibeIC.AI Contributors"]
    holder = "lowRISC contributors (OpenTitan project)"
    assert doc["holders"][holder]["licences"] == ["Apache-2.0"]
    assert doc["unaccounted"] == [holder]


def test_it_runs_as_a_cli(tmp_path):
    root = _tree(tmp_path, _OURS, {"vendor/aes.sv": _THIRD_PARTY_RTL})
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "bundled_attribution_notice_check.py"),
         str(root)], capture_output=True, text=True, timeout=_T)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "lowRISC" in r.stdout, r.stdout


# --------------------------------------------------------------------------
# The repository itself. This is the assertion #1043 is actually about, and it
# is the one that makes the withdrawal question moot: NOTICE is at the root,
# outside every withdrawable run directory.
# --------------------------------------------------------------------------

def test_THIS_repository_accounts_for_everything_it_bundles(capsys):
    repo = _PROGRAMS.parents[3]
    if not (repo / "NOTICE").is_file():          # pragma: no cover
        pytest.skip(f"no NOTICE at {repo}")
    rc = bc.main([str(repo)])
    out = capsys.readouterr().out
    assert rc == 0, out


# ═══════════════════════════════════════════════════════════════════════
# vibe-ic#1241 — A SENTENCE THAT DENIES THE BUNDLING IS NOT AN ATTRIBUTION
# ═══════════════════════════════════════════════════════════════════════
# The match against NOTICE used to be a bare `re.search(token, text)`, which
# accepts the holder's name ANYWHERE — so a sentence denying the bundling
# satisfied the very requirement it denies.
#
# MEASURED on this branch's base (`31406fb4`) before the fix, by replacing the
# real Efabless entry in the repo's own NOTICE with
#
#     Note: Efabless Corporation source is NOT bundled in this repository
#     and no attribution is required for it.
#
#     base   [PASS] 7 holder(s) over 513 SPDX-headered file(s)   rc 0
#     fixed  [FAIL] Efabless Corporation — 27 file(s), Apache-2.0
#
# 27 Apache-2.0 files were distributed with their section 4(d) record satisfied
# by a sentence stating no record was required.
#
# These two exist because the fix landed with NO test: both arms of the suite
# passed identically, so reverting `_named_without_denial` to `re.search` would
# have left the suite green and the defect silent.
def test_PAIRED_a_NOTICE_sentence_DENYING_the_bundling_is_not_attribution(
        tmp_path, capsys):
    """THE DEFECT. The name is present; a substring match finds it and passes."""
    notice = _OURS + (
        "\nNote: lowRISC contributors (OpenTitan project) source is NOT "
        "bundled in this repository and no attribution is required for it.\n")
    root = _tree(tmp_path, notice, {"vendor/aes.sv": _THIRD_PARTY_RTL})
    rc = bc.main([str(root)])
    out = capsys.readouterr().out
    assert rc == 1, (
        "a sentence DENYING the bundling satisfied the attribution it "
        "denies — this is the #1241 polarity defect:\n" + out)
    assert "lowRISC" in out, out


def test_the_denial_rule_does_not_reject_a_REAL_entry_beside_a_denial(
        tmp_path, capsys):
    """THE CONTROL, and the reason the rule examines EVERY mention.

    A NOTICE that attributes a work AND elsewhere discusses what is not
    bundled is ordinary. A first-hit-decides implementation fails this for the
    wrong reason, which would be worse than the defect it replaced: it would
    demand attribution for work already attributed.
    """
    notice = _OURS + (
        "\nBUNDLED: lowRISC contributors (OpenTitan project), Apache-2.0\n"
        "\nNote: lowRISC contributors (OpenTitan project) tooling is NOT "
        "bundled here; only its RTL is.\n")
    root = _tree(tmp_path, notice, {"vendor/aes.sv": _THIRD_PARTY_RTL})
    rc = bc.main([str(root)])
    out = capsys.readouterr().out
    assert rc == 0, (
        "a real attribution was rejected because a DIFFERENT sentence "
        "mentioned the same holder in a denial:\n" + out)
