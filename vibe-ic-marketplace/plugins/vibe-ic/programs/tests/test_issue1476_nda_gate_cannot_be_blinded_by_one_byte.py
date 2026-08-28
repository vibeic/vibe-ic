#!/usr/bin/env python3
"""vibe-ic#1476 — a check that COULD NOT READ a file must never report what a
check that READ it and found nothing reports.

The issue was filed against the agent's `grep` shim, which returns empty
stdout, empty stderr and exit 1 — every observable signal of a genuine
no-match — for any file containing one truncated UTF-8 byte. The shim is
harness tooling this repo does not ship. This file is about the instance the
repo DOES own, which is worse, because it sat in the strictest gate here.

`source_chip_agnostic_check._scan_nda` is the NDA panel: no allowlist of any
kind, one sanctioned encoded home, and the stated contract that it is what
"guarantees `git grep <SKU>` stays 0 forever". It read every file with a
STRICT utf-8 decode and swallowed the failure:

    try:
        text = f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        continue

Measured on this tree before the fix, two fixtures whose NDA-token line is
byte-identical and which differ by exactly one trailing byte:

    arm A   token line, valid UTF-8                 ->  FAIL, 1 NDA finding
    arm B   same line + ONE bare 0xE2               ->  PASS, 0 findings

One half-cut em-dash — precisely what `cut -c` leaves behind, which is how
the issue's author hit this — removed the whole file from the scan, and the
gate certified a tree carrying a foundry SKU as clean. No counter moved, no
message was printed, and the exit code was 0.

The paired defect in the same file: `audit`'s own walk caught only `OSError`,
so the same byte under `programs/` raised `UnicodeDecodeError` out of the loop
and killed the run BEFORE the NDA panel below it ever executed. One byte could
either blind the gate or abort it.

The fix is a lossy decode plus a recorded UNREADABLE state, and the lossy
direction is safe by construction: every forbidden and NDA token is ASCII, so
`errors="replace"` preserves every byte that could form a match and can only
add noise around one. It cannot buy a green — which is what the tests below
pin, in BOTH directions.

NDA: this file contains no literal foundry SKU. Tokens are reconstructed at
runtime from the encoded store, the same way `test_source_chip_agnostic_check`
already does, so the guard does not catch its own regression test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import _commercial_pdk as _cpdk                      # noqa: E402
import source_chip_agnostic_check as C               # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PLUGIN_ROOT = _PROGRAMS.parent

# Longest real NDA token, decoded at runtime — never written as a literal.
_TOKEN = sorted(_cpdk.nda_tokens(), key=len, reverse=True)[0]

# The one byte. A lead byte of a 3-byte UTF-8 sequence with its continuation
# bytes cut off — what `cut -c1-N` produces from an em-dash, and what the issue
# bisected its own corrupted measurement down to.
_TRUNCATED = b"\xe2"


def _build_tree(root: Path, trailing: bytes) -> Path:
    """A minimal plugin tree whose ONLY leak sits outside programs/skills/
    commands/, so it is reachable exclusively through the tree-wide NDA panel.

    Returns the path of the leaking file.
    """
    (root / "programs").mkdir(parents=True, exist_ok=True)
    (root / "programs" / "widget.py").write_bytes(b"def widget():\n    return 1\n")
    src = root / "mcp-eda" / "src"
    src.mkdir(parents=True, exist_ok=True)
    leak = src / "probe.py"
    leak.write_bytes(b'CORNER_LIB = "' + _TOKEN.encode() + b'_typ.lib"'
                     + trailing + b"\n")
    return leak


def _nda_findings(root: Path):
    verdict, findings = C.audit(root)
    return verdict, [f for f in findings if f.rule == "FORBIDDEN_NDA_SKU"]


# ---------------------------------------------------------------------------
# The two arms. Same gate, same leak, one byte of difference.
# ---------------------------------------------------------------------------
def test_arm_a_a_plain_leak_is_caught(tmp_path: Path) -> None:
    """Control for arm B: without the byte, the gate does its job."""
    leak = _build_tree(tmp_path / "armA", b"")
    verdict, nda = _nda_findings(tmp_path / "armA")
    assert verdict == "FAIL", (verdict, C.SCAN_CENSUS)
    assert len(nda) == 1
    assert nda[0].file.replace("\\", "/") == "mcp-eda/src/probe.py"
    # the fixture really is valid UTF-8, so arm B differs by the byte alone
    leak.read_bytes().decode("utf-8")


def test_arm_b_one_truncated_byte_no_longer_hides_the_leak(tmp_path: Path) -> None:
    """THE REGRESSION. Before the fix this arm returned PASS with 0 findings."""
    leak = _build_tree(tmp_path / "armB", _TRUNCATED)
    verdict, nda = _nda_findings(tmp_path / "armB")
    assert verdict == "FAIL", (
        "one truncated UTF-8 byte hid an NDA leak from the NDA gate "
        f"(census={dict(C.SCAN_CENSUS)})")
    assert len(nda) == 1
    assert nda[0].file.replace("\\", "/") == "mcp-eda/src/probe.py"
    # and the arm really does carry the byte that used to be fatal
    assert leak.read_bytes().endswith(_TRUNCATED + b"\n")
    with pytest.raises(UnicodeDecodeError):
        leak.read_bytes().decode("utf-8")


def test_the_two_arms_differ_by_exactly_one_byte(tmp_path: Path) -> None:
    """Keeps the pair honest: if the arms ever drift apart in any other way,
    the verdict comparison above stops meaning what it claims to mean."""
    a = _build_tree(tmp_path / "a", b"").read_bytes()
    b = _build_tree(tmp_path / "b", _TRUNCATED).read_bytes()
    assert b == a[:-1] + _TRUNCATED + b"\n"
    assert len(b) - len(a) == 1


class _NoRecord(list):
    """The pre-fix bookkeeping, which is to say: there was none.

    `except (OSError, UnicodeDecodeError): continue` left no counter, no name
    and no trace. Reverting the record as well as the reader is what makes the
    control below a faithful reconstruction rather than a half one — with the
    reader alone reverted, the NEW bookkeeping already catches the skip and
    answers COULD_NOT_LOOK, which is a different (also correct) answer.
    """

    def append(self, item):      # noqa: D102 - deliberately drops the record
        return None

    def extend(self, items):     # noqa: D102
        return None


def test_the_prefix_gate_still_produces_the_OTHER_answer(tmp_path: Path,
                                                         monkeypatch) -> None:
    """POSITIVE CONTROL — the fixture is not one that fails no matter what.

    Revert the two things this fix changed (strict decode; skip left
    unrecorded), run the REAL gate over the SAME bytes, and arm B goes back to
    the false green it shipped with. Same tree, same gate, opposite verdicts,
    so the FAIL above is bought by the fix and not by a fixture that any scan
    would flag.
    """
    def _strict(path: Path):
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None       # the pre-fix `continue`, in helper form

    root = tmp_path / "armB"
    _build_tree(root, _TRUNCATED)

    monkeypatch.setattr(C, "_read_for_scan", _strict)
    monkeypatch.setattr(C, "UNREADABLE", _NoRecord())
    verdict_old, nda_old = _nda_findings(root)
    monkeypatch.undo()
    verdict_new, nda_new = _nda_findings(root)

    assert (verdict_old, len(nda_old)) == ("PASS", 0), (
        "the pre-fix gate should have certified this tree clean; if it did "
        "not, this fixture proves nothing about the fix")
    assert (verdict_new, len(nda_new)) == ("FAIL", 1)


def test_reverting_only_the_reader_still_refuses_to_certify(tmp_path: Path,
                                                            monkeypatch) -> None:
    """The two halves of the fix are independently load-bearing.

    With the lossy decode reverted but the UNREADABLE record kept, the gate no
    longer says PASS — it says COULD_NOT_LOOK. Belt and braces: the reader
    makes the leak visible, the record makes an invisible file impossible to
    mistake for a clean one.
    """
    def _strict(path: Path):
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    root = tmp_path / "armB"
    _build_tree(root, _TRUNCATED)
    monkeypatch.setattr(C, "_read_for_scan", _strict)
    verdict, findings = C.audit(root)
    assert verdict == "COULD_NOT_LOOK", (verdict, findings)
    assert "mcp-eda/src/probe.py" in [p.replace("\\", "/") for p in C.UNREADABLE]


# ---------------------------------------------------------------------------
# The other direction: the fix must not be a way to make the gate always fail,
# and must not be a way to make it always pass either.
# ---------------------------------------------------------------------------
def test_a_clean_tree_still_passes(tmp_path: Path) -> None:
    """A lossy decode must not manufacture findings out of noise."""
    root = tmp_path / "clean"
    (root / "programs").mkdir(parents=True)
    (root / "programs" / "widget.py").write_bytes(b"def widget():\n    return 1\n")
    # non-ASCII, and undecodable, but carrying no token at all
    (root / "programs" / "notes.md").write_bytes(
        "# notes — an em-dash\n".encode() + b"trailing " + _TRUNCATED + b"\n")
    verdict, findings = C.audit(root)
    assert verdict == "PASS", (verdict, findings)
    assert findings == []


def test_the_real_plugin_tree_is_still_clean_and_states_its_denominator() -> None:
    """The headline contract of this gate, unchanged by the fix — and now with
    a denominator, so a PASS over nothing cannot masquerade as this one.

    Deliberately IN-PROCESS. The equivalent subprocess assertion already lives
    in `test_organic_chip_agnostic_reports_its_denominator`, and a second
    full-tree `subprocess.run(..., timeout=60)` was measured taking longer than
    its own bound on a loaded host — a timeout is neither a pass nor a failure,
    and a test that can report one is a worse instrument than no test.
    """
    verdict, findings = C.audit(_PLUGIN_ROOT)
    assert verdict == "PASS", (verdict,
                               [(f.file, f.line) for f in findings[:20]])
    found = C.SCAN_CENSUS.get("nda_files_found", 0)
    read = C.SCAN_CENSUS.get("nda_files_read", 0)
    assert found > 100, C.SCAN_CENSUS
    assert read == found, C.SCAN_CENSUS
    assert C.SCAN_CENSUS.get("nda_files_unreadable", -1) == 0, C.SCAN_CENSUS


def test_the_pass_banner_names_the_NDA_denominator(tmp_path: Path) -> None:
    """The CLI half, over a tree small enough that the assertion measures the
    banner and not the host's load average."""
    root = tmp_path / "banner"
    (root / "programs").mkdir(parents=True)
    (root / "programs" / "widget.py").write_bytes(b"def widget():\n    return 1\n")
    r = _pr.run(
        [sys.executable, str(_PROGRAMS / "source_chip_agnostic_check.py"),
         str(root)],
        capture_output=True, text=True)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "PASS (1 file(s) scanned)" in out, out
    assert "NDA panel read 1 of 1 file(s) tree-wide" in out, out


# ---------------------------------------------------------------------------
# A file whose BYTES cannot be obtained is neither clean nor dirty.
# ---------------------------------------------------------------------------
def test_an_unreadable_file_is_not_a_pass(tmp_path: Path) -> None:
    """The general form of the issue: 'could not look' gets its own verdict and
    its own exit code, instead of borrowing the clean one."""
    root = tmp_path / "io"
    (root / "programs").mkdir(parents=True)
    (root / "programs" / "widget.py").write_bytes(b"def widget():\n    return 1\n")
    locked = root / "programs" / "locked.py"
    locked.write_bytes(b"def x():\n    return 2\n")
    locked.chmod(0o000)
    try:
        if C._read_for_scan(locked) is not None:
            pytest.skip("running as a user that can read mode-000 files")
        r = _pr.run(
            [sys.executable, str(_PROGRAMS / "source_chip_agnostic_check.py"),
             str(root)],
            capture_output=True, text=True)
    finally:
        locked.chmod(0o644)          # so tmp_path cleanup works
    out = r.stdout + r.stderr
    assert r.returncode == 2, out
    assert "COULD_NOT_LOOK" in out, out
    assert "programs/locked.py" in out.replace("\\", "/"), out
    # and it is NOT dressed up as a clean scan
    assert "PASS" not in out.split("COULD_NOT_LOOK")[0], out


def test_unreadable_state_is_reset_between_runs(tmp_path: Path) -> None:
    """A stale EMPTY list is the dangerous direction: it would let a blind run
    inherit a healthy one's certificate."""
    root = tmp_path / "io2"
    (root / "programs").mkdir(parents=True)
    locked = root / "programs" / "locked.py"
    locked.write_bytes(b"def x():\n    return 2\n")
    locked.chmod(0o000)
    try:
        if C._read_for_scan(locked) is not None:
            pytest.skip("running as a user that can read mode-000 files")
        v1, _ = C.audit(root)
        assert v1 == "COULD_NOT_LOOK", (v1, list(C.UNREADABLE))
        assert C.UNREADABLE
    finally:
        locked.chmod(0o644)
    v2, _ = C.audit(_PLUGIN_ROOT)
    assert v2 == "PASS", (v2, list(C.UNREADABLE))
    assert C.UNREADABLE == [], C.UNREADABLE


def test_the_deny_list_loader_survives_a_truncated_byte(tmp_path: Path) -> None:
    """The loader is a module-level initialiser: a strict decode there raised
    at IMPORT time, and its OSError twin silently returns an empty panel — a
    gate with no tokens passes everything."""
    p = tmp_path / "deny.txt"
    p.write_bytes(b"# comment\nalpha_sku\nbeta" + _TRUNCATED + b"\ngamma_sku\n")
    toks = C._load_deny_tokens(p)
    assert "alpha_sku" in toks and "gamma_sku" in toks, toks
    assert len(toks) == 3, toks
