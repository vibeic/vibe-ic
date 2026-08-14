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


# --------------------------------------------------------------------------
# POLARITY — vibe-ic#1241. A sentence that DENIES the copyright must not be
# read as one that asserts it.
#
# `_COPYRIGHT` matches `[Cc]opyright` wherever the word falls on a line and
# captures the rest, so before this guard an English header comment produced a
# holder IDENTICAL to a real attribution:
#
#     // Copyright 2020 Acme Corporation             -> ['Acme Corporation']
#     // This file is not copyright Acme Corporation -> ['Acme Corporation']
#
# Both directions are asserted. A "fix" that dropped every line containing a
# negation would satisfy the denial cases and destroy the control — and the
# control is the one that matters, because losing a real holder means shipping
# a bundled work with no attribution recorded.
# --------------------------------------------------------------------------

_DENIED_RTL = """// This file is not copyright Acme Corporation.
// SPDX-License-Identifier: Apache-2.0
module m; endmodule
"""

_DENIED_CLAIMED = """// No copyright is claimed by Acme Corporation for this file.
// SPDX-License-Identifier: Apache-2.0
module m; endmodule
"""

_ASSERTED_RTL = """// Copyright 2020 Acme Corporation
// SPDX-License-Identifier: Apache-2.0
module m; endmodule
"""


@pytest.mark.parametrize("header", [_DENIED_RTL, _DENIED_CLAIMED])
def test_a_denied_copyright_is_not_a_holder(tmp_path, header):
    """The denial cases: no holder may be extracted."""
    root = _tree(tmp_path, _OURS, {"vendor/m.sv": header})
    assert bc.scan(root) == {}, (
        "a sentence denying the copyright produced a holder, so a file saying "
        "it is NOT copyright X is indistinguishable from one attributing X")


def test_PAIRED_a_plain_copyright_is_still_a_holder(tmp_path):
    """The control, which the denial guard must not break.

    Without this, dropping every line containing a negation would pass the two
    tests above while silently losing real attributions.
    """
    root = _tree(tmp_path, _OURS, {"vendor/m.sv": _ASSERTED_RTL})
    assert list(bc.scan(root)) == ["Acme Corporation"]


def test_a_denial_does_not_suppress_a_real_holder_elsewhere_in_the_header(tmp_path):
    """Scoping: the denial retracts its own sentence, not the whole file.

    A header may disclaim one party and attribute another. Line-scoped polarity
    keeps the second; a file-wide "does it contain a negation" test would not.
    """
    header = ("// This file is not copyright Acme Corporation.\n"
              "// Copyright 2020 Beta Industries\n"
              "// SPDX-License-Identifier: Apache-2.0\n"
              "module m; endmodule\n")
    root = _tree(tmp_path, _OURS, {"vendor/m.sv": header})
    assert list(bc.scan(root)) == ["Beta Industries"]
