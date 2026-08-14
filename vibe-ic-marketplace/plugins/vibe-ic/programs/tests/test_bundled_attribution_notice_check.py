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
# POLARITY (vibe-ic#1241, the #712 vocabulary).
#
# `scan` read a value out of a sentence and wrote it as a declaration without
# asking whether the sentence DENIES it. Every test below is PAIRED: the
# denial case, and the assertion case that must still fire — because a gate
# made "robust" by reading less is the silent failure `_prose_polarity` names,
# and it would be worse here than the blindness it replaces.
# --------------------------------------------------------------------------

#: SPDX specifies this literal for "there is no copyright holder".
_SPDX_NONE_RTL = """// SPDX-FileCopyrightText: NONE
// SPDX-License-Identifier: Apache-2.0
module public_domain_ip; endmodule
"""

_DENIED_SENTENCE_RTL = """// This file is not copyrighted by Acme Corp.
// SPDX-License-Identifier: Apache-2.0
module unowned; endmodule
"""

#: A REAL holder whose name contains the denial token `non-`.
_NON_PROFIT_RTL = """// Copyright (c) 2020 Non-Profit Foundation
// SPDX-License-Identifier: Apache-2.0
module donated; endmodule
"""

_DENY_THEN_ASSERT_RTL = """// No copyright is claimed for the testbench stubs.
// Copyright (c) 2019 Olof Kindgren
// SPDX-License-Identifier: Apache-2.0
module wb_intercon; endmodule
"""


def test_an_SPDX_NONE_sentinel_is_not_a_bundled_holder(tmp_path, capsys):
    """`SPDX-FileCopyrightText: NONE` means there is NO holder. Read blind it
    became a third-party holder named "NONE" that NOTICE had to account for."""
    root = _tree(tmp_path, _OURS, {"vendor/pd.sv": _SPDX_NONE_RTL})
    # Assert on the census, not on stdout: pytest puts this test's own name —
    # which contains "NONE" — into `tmp_path`, so a substring check on output
    # that happens to print the path passes or fails for the wrong reason.
    assert bc.scan(root) == {}, bc.scan(root)
    rc = bc.main([str(root)])
    out = capsys.readouterr().out
    # rc 2 = REFUSE: the only SPDX file carried no holder, so nothing was
    # established. That is the honest answer and it is NOT a pass.
    assert rc == 2, out


def test_the_NONE_sentinel_guard_still_reports_a_REAL_holder(tmp_path, capsys):
    """PAIRED GUARD. Same tree plus one genuinely attributed file: suppressing
    the sentinel must not suppress the assertion beside it."""
    root = _tree(tmp_path, _OURS, {"vendor/pd.sv": _SPDX_NONE_RTL,
                                   "vendor/aes.sv": _THIRD_PARTY_RTL})
    rc = bc.main([str(root)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "lowRISC" in out, out


def test_a_denied_sentence_does_not_fabricate_a_holder(tmp_path, capsys):
    """"is not copyrighted by Acme Corp" was read as the holder `ed by Acme
    Corp`, because `[Cc]opyright` matches inside *copyrighted*. Its distinctive
    token is `ed`, which NOTICE contains as ordinary English — so the fabricated
    holder was silently accounted for and the gate went green on a lie."""
    root = _tree(tmp_path, _OURS, {"vendor/unowned.sv": _DENIED_SENTENCE_RTL})
    rc = bc.main([str(root)])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "Acme" not in out, out


def test_a_holder_whose_NAME_carries_a_denial_word_is_STILL_read(tmp_path, capsys):
    """PAIRED GUARD, and the one that decides the scope. `Non-Profit Foundation`
    has `_distinctive` "Non-Profit", which matches `\\bnon-?\\b`. A denial read
    off the NAME would drop a real holder and take the gate quietly green — the
    direction `_prose_polarity` calls the silent one. The scope therefore stops
    at the captured name."""
    root = _tree(tmp_path, _OURS, {"vendor/donated.sv": _NON_PROFIT_RTL})
    rc = bc.main([str(root)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "Non-Profit Foundation" in out, out


def test_a_denial_does_not_suppress_the_assertion_on_the_NEXT_line(tmp_path, capsys):
    """A header may deny in one line and attribute in the next. Stopping at the
    denial would report an attributed file as carrying no holder at all."""
    root = _tree(tmp_path, _OURS, {"vendor/wb.sv": _DENY_THEN_ASSERT_RTL})
    rc = bc.main([str(root)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "Olof Kindgren" in out, out


def test_scan_reaches_the_shared_polarity_vocabulary(tmp_path):
    """The consult is the property, so assert it structurally rather than only
    through outcomes: a future refactor that drops it must go red here and not
    only in `prose_polarity_consulted_check`."""
    import ast
    src = (_PROGRAMS / "bundled_attribution_notice_check.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "scan")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert {"is_denied", "sentence_scope"} & names, sorted(names)


#: The canonical real-world denial, from #1249's independent fix of this row —
#: US-government sources carry it verbatim and they DO get vendored.
_US_GOV_RTL = """// No copyright is claimed in the United States under Title 17, U.S. Code.
// SPDX-License-Identifier: Apache-2.0
module usgov; endmodule
"""


def test_a_US_government_notice_is_not_a_rightsholder(tmp_path, capsys):
    """Read blind this yields the holder "is claimed in the United States under
    Title 17, U.S. Code." — a fabricated party in a gate whose whole output is
    the list of people this repo owes attribution to. Getting it wrong invents
    a legal obligation rather than missing one."""
    root = _tree(tmp_path, _OURS, {"vendor/usgov.sv": _US_GOV_RTL})
    assert bc.scan(root) == {}, bc.scan(root)
    rc = bc.main([str(root)])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "Title 17" not in out, out
