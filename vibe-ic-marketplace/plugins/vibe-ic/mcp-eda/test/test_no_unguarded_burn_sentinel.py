#!/usr/bin/env python3
"""Wave 33 (mcp-eda v0.99.9) — verify check_no_unguarded_burn.sh works.

The sentinel is a CI guardrail. Two-axis test:

* Current source tree must PASS (exit 0). Regression caught: anything
  the wrapper / driver does still satisfies the rule.
* When we plant a deliberate violation in a temp file under src/,
  the sentinel must FAIL (exit 1) and emit the
  WAVE33_UNGUARDED_BURN_VIOLATION marker.

vibe-ic#1476 added the third axis: the violation must stay VISIBLE when the
line it sits on is not decodable as UTF-8. GNU grep in a UTF-8 locale
silently omits a matching line that contains an improperly-encoded byte —
it writes nothing for that line on stdout, notes `binary file matches` on
STDERR, and still exits 0. The sentinel discarded that stderr and swallowed
the status, so ONE truncated multi-byte character on a burn line turned the
gate's output into `OK: all burn calls in mcp-eda/src/ guarded` — a positive
attestation of safety produced by a scan that could not read the line. The
two tests below pin both halves: the violation is still caught, and a file
that is merely undecodable does not become a violation.

The fixture cleans up after itself.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "check_no_unguarded_burn.sh"
SRC = ROOT / "src"
assert SCRIPT.exists()

#: Every subprocess bound in this file. The landing harness runs pytest at
#: `--timeout=180 --timeout-method=thread`, where an inner bound at or above
#: the harness bound does not fail the TEST — it outlives the harness and
#: takes the whole session down, losing every other verdict in the run.
_BOUND_S = 60

#: A burn-class call the sentinel's PATTERN_BURN is written to match.
_BURN_CALL = 'return execSync(`quartus_pgm -c 1 -m JTAG -o "P;${sof}"`);'

#: One truncated UTF-8 sequence: a 3-byte lead byte with no continuation
#: bytes. This is what `cut -c` / `head -c` / any byte-wise truncation of
#: UTF-8 text leaves behind, and it is the exact byte from vibe-ic#1476.
_TRUNCATED_UTF8 = b"\xe2"


def _run_sentinel():
    # `errors="replace"`: when the sentinel catches a violation it echoes the
    # OFFENDING LINE back, and that line is exactly the one that may not be
    # decodable. A strict decoder here would turn a correct FAIL verdict into
    # a UnicodeDecodeError inside the harness — the same defect one layer up,
    # and it is how this test first went red after the fix landed.
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True, text=True, errors="replace", timeout=_BOUND_S,
    )


def test_current_tree_passes_sentinel():
    r = _run_sentinel()
    assert r.returncode == 0, (
        f"sentinel rejected current tree:\n"
        f"stdout={r.stdout}\nstderr={r.stderr}"
    )


def test_planted_violation_caught():
    # Plant a synthetic JS file with an unguarded execSync(quartus_pgm
    # ... -o "P;..." ...) and confirm the sentinel rejects it.
    decoy = SRC / "_wave33_planted_violation.js"
    decoy.write_text(
        '// synthetic violation for Wave 33 sentinel test\n'
        'function fakeBurn(sof) {\n'
        '  return execSync(`quartus_pgm -c 1 -m JTAG -o "P;${sof}"`);\n'
        '}\n'
    )
    try:
        r = subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True, text=True,
        )
        assert r.returncode == 1, (
            f"sentinel did NOT reject planted violation: {r.stdout}"
        )
        assert "WAVE33_UNGUARDED_BURN_VIOLATION" in r.stderr, r.stderr
        assert "_wave33_planted_violation.js" in r.stderr, r.stderr
    finally:
        if decoy.exists():
            decoy.unlink()


def test_test_fixture_violation_ignored():
    """Planting the same violation under a `test_` filename should
    NOT trip the sentinel — test fixtures are exempt."""
    decoy = SRC / "test_wave33_decoy.js"
    decoy.write_text(
        'execSync(`quartus_pgm -c 1 -m JTAG -o "P;foo.sof"`);\n'
    )
    try:
        r = _run_sentinel()
        assert r.returncode == 0, (
            f"sentinel mis-flagged test fixture:\n"
            f"stdout={r.stdout}\nstderr={r.stderr}"
        )
    finally:
        if decoy.exists():
            decoy.unlink()


def test_violation_on_an_undecodable_line_still_caught():
    """vibe-ic#1476 — the SAME violation, plus one truncated UTF-8 byte on
    the same line, must still be rejected.

    This is the reachability half. Before the fix the sentinel's own
    reproduction was:

        arm A  burn line, valid UTF-8                    -> exit 1  (caught)
        arm B  identical burn line + one bare 0xE2 byte  -> exit 0
               and stdout `OK: all burn calls in mcp-eda/src/ guarded`

    Nothing about the design changed between the two arms — only whether the
    instrument could read the line it was judging. A gate that answers OK
    because it could not look is the failure this repo removes, so exit 0
    here must be unreachable while the violation is present.
    """
    decoy = SRC / "_issue1476_planted_violation.js"
    decoy.write_bytes(
        b"// synthetic violation for vibe-ic#1476 sentinel test\n"
        b"function fakeBurn(sof) {\n"
        b"  " + _BURN_CALL.encode() + b" // note " + _TRUNCATED_UTF8 + b"\n"
        b"}\n"
    )
    try:
        r = _run_sentinel()
        assert r.returncode == 1, (
            "sentinel did NOT reject a planted violation whose line carries "
            "one truncated UTF-8 byte — it could not read the line and "
            "reported the same thing it reports for a clean tree.\n"
            f"rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}"
        )
        assert "WAVE33_UNGUARDED_BURN_VIOLATION" in r.stderr, r.stderr
        assert "_issue1476_planted_violation.js" in r.stderr, r.stderr
    finally:
        if decoy.exists():
            decoy.unlink()


def test_pass_states_how_much_it_looked_at():
    """vibe-ic#1476 — an empty result is not a zero, so a PASS has to say
    what its denominator was. Before the fix the banner was unqualified:
    a run that scanned 900 files and found nothing and a run that could not
    see anything at all printed the identical sentence."""
    r = _run_sentinel()
    assert r.returncode == 0, r.stderr
    m = re.search(r"scanned (\d+) \.js/\.ts/\.py file\(s\)", r.stdout)
    assert m, f"PASS banner does not disclose its denominator: {r.stdout!r}"
    assert int(m.group(1)) > 0, (
        f"PASS banner discloses a denominator of zero: {r.stdout!r}"
    )


def test_zero_denominator_refuses_instead_of_certifying(tmp_path):
    """A scan with nothing to scan must NOT be exit 0. Same script, an empty
    src/ — the gate has to refuse (exit 2) rather than print OK, because
    `OK` over an empty tree is the strongest form of the bug in #1476."""
    (tmp_path / "tools").mkdir()
    (tmp_path / "src").mkdir()
    clone = tmp_path / "tools" / SCRIPT.name
    clone.write_bytes(SCRIPT.read_bytes())
    r = subprocess.run(
        ["bash", str(clone)],
        capture_output=True, text=True, errors="replace", timeout=_BOUND_S,
    )
    assert r.returncode == 2, (
        "gate certified an EMPTY tree instead of refusing:\n"
        f"rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}"
    )
    assert "WAVE33_SCAN_COULD_NOT_LOOK" in r.stderr, r.stderr


def test_undecodable_byte_alone_is_not_a_violation():
    """The other direction — the fix must not buy its green by flagging
    everything. A file that is undecodable but contains NO burn-class call
    must leave the sentinel at exit 0."""
    decoy = SRC / "_issue1476_undecodable_clean.js"
    decoy.write_bytes(
        b"// undecodable but harmless: no burn call anywhere "
        + _TRUNCATED_UTF8 + b"\n"
        b"function notABurn(sof) {\n"
        b"  return execSync(`quartus_pgm --list`);\n"
        b"}\n"
    )
    try:
        r = _run_sentinel()
        assert r.returncode == 0, (
            "sentinel flagged an undecodable file that contains no "
            f"burn-class call:\nstdout={r.stdout}\nstderr={r.stderr}"
        )
    finally:
        if decoy.exists():
            decoy.unlink()
