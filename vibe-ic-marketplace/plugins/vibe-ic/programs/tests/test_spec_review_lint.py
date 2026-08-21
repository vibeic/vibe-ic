"""Unit tests for spec_review_lint.py (deterministic structural presence lint).

This lint extracts EXACTLY the structural/presence part of the `spec-review`
skill checklist (skills/spec-review/SKILL.md) so it runs identically every time:
  • every DECLARED signal has {direction, width, polarity, clock, reset}
  • every timing statement has a reference clock edge
  • every declared mode has entry AND exit
  • the four corner-case checklist items are covered.

The two task-anchor cases:
  • a COMPLETE spec yields ZERO findings (no false alerts), and
  • a spec missing a width/polarity yields exactly those findings.

Plus the no-false-alert guards: pure-prose (no interface list) yields no signal
findings; a bare verb "hold"/"setup" is NOT a timing statement; empty/tiny specs
SKIP; a missing file exits 2.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / 'spec_review_lint.py'
assert SCRIPT.exists()


def run(tmp_path, spec_text, ext='.md', *extra):
    spec = tmp_path / f'spec{ext}'
    spec.write_text(spec_text)
    jf = tmp_path / 'out.json'
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--json', str(jf), *extra, str(spec)],
        capture_output=True, text=True)
    findings = json.loads(jf.read_text())['findings'] if jf.exists() else []
    return res, findings


def codes(findings):
    return {f['code'] for f in findings}


# A fully-specified spec: every declared signal has direction/width/polarity/
# clock/reset, every timing statement names a reference edge, every mode has an
# entry+exit, and all four corner-case checklist items are covered.
COMPLETE = """\
# Accumulator block spec

Implement TopModule, a synchronous accumulator.

Interface:
 - input  clk
 - input  rst_n
 - input  data_bus (8 bits)
 - input  valid
 - output result (8 bits)
 - output ready

The reset rst_n is active-low and asynchronous. All signals are sampled on the
rising edge of clk and are reset by rst_n to their default values.

Idle mode: the block enters Idle mode upon reset and exits Idle mode when valid
is asserted. Run mode: the block enters Run mode when valid is high and exits Run
mode when the transaction completes.

Timing: data_bus must be stable 2 ns setup before the rising edge of clk.
result is registered on the rising edge of clk.

Corner cases: a reset during operation clears result. Back-to-back transactions
are supported with no idle cycle between them. On overflow the result saturates
and the full flag asserts; an empty input underflow holds the last value. Illegal
reserved inputs produce defined behaviour: result is held.
"""


# ---- task anchor 1: a complete spec yields ZERO findings -------------------
def test_complete_spec_no_findings(tmp_path):
    res, f = run(tmp_path, COMPLETE)
    assert f == [], f"expected no findings, got {f}"
    assert res.returncode == 0


# ---- task anchor 2: a spec missing a width AND a polarity -------------------
MISSING_WIDTH_POLARITY = """\
# Accumulator block spec

Implement TopModule, a synchronous accumulator.

Interface:
 - input  clk
 - input  rst
 - input  data_bus
 - input  valid
 - output result (8 bits)
 - output ready

All signals are sampled on the rising edge of clk and are reset by rst to their
default values.

Idle mode: the block enters Idle mode upon reset and exits Idle mode when valid
is asserted. Run mode: the block enters Run mode when valid is high and exits Run
mode when the transaction completes.

Timing: data_bus must be stable 2 ns setup before the rising edge of clk.
result is registered on the rising edge of clk.

Corner cases: a reset during operation clears result. Back-to-back transactions
are supported with no idle cycle. On overflow the result saturates and an empty
underflow holds. Illegal reserved opcodes are ignored.
"""


def test_missing_width_and_polarity_exact_findings(tmp_path):
    res, f = run(tmp_path, MISSING_WIDTH_POLARITY)
    # exactly two signal-attr findings: data_bus missing width, rst missing polarity
    attr = [x for x in f if x['code'] == 'signal-missing-attr']
    assert len(attr) == 2, f"expected 2 attr findings, got {f}"
    by_sig = {}
    for x in attr:
        # message names the signal in quotes: "declared signal 'X' is missing its Y"
        sig = x['message'].split("'")[1]
        miss = x['message'].split('missing its ')[1].split()[0]
        by_sig[sig] = miss
    assert by_sig.get('data_bus') == 'width'
    assert by_sig.get('rst') == 'polarity'
    # WARN-only, so without --strict the gate still PASSes
    assert res.returncode == 0


def test_missing_attr_strict_fails(tmp_path):
    res, _ = run(tmp_path, MISSING_WIDTH_POLARITY, '.md', '--strict')
    assert res.returncode == 1


# ---- no-false-alert: a 1-bit scalar control is NEVER flagged for width ------
def test_scalar_control_not_flagged_for_width(tmp_path):
    res, f = run(tmp_path, COMPLETE)
    # clk/valid/ready are scalars; none should be flagged for a missing width
    for x in f:
        assert 'missing its width' not in x['message']


# ---- no-false-alert: a bare verb "hold" is NOT a timing statement ----------
def test_bare_verb_hold_is_not_a_timing_statement(tmp_path):
    spec = """\
Implement TopModule.
 - input  clk
 - input  rst_n
 - output q
rst_n is an active-low asynchronous reset; q is sampled on the rising edge of clk
and reset by rst_n. On an illegal opcode the block holds q. The counter saturates
on overflow and empties to zero on underflow. A reset during operation clears q.
Back-to-back requests are accepted.
"""
    res, f = run(tmp_path, spec)
    assert 'timing-no-ref-edge' not in codes(f), f
    assert res.returncode == 0


# ---- a genuine timing statement WITH no ref edge IS flagged ----------------
def test_timing_without_ref_edge_is_flagged(tmp_path):
    spec = """\
Implement TopModule.
 - input  clk
 - input  rst_n
 - output q
rst_n is an active-low asynchronous reset; q is sampled on the rising edge of clk
and reset by rst_n. The output must meet a 3 ns setup. A reset during operation
clears q. Back-to-back requests are accepted. On overflow it saturates; on empty
underflow it holds. Illegal opcodes are ignored.
"""
    res, f = run(tmp_path, spec)
    # "3 ns setup" with no reference edge in that sentence -> flagged
    assert 'timing-no-ref-edge' in codes(f), f


# ---- mode entry/exit ------------------------------------------------------
def test_mode_missing_exit(tmp_path):
    spec = """\
Implement TopModule.
 - input  clk
 - input  rst_n
 - output q
rst_n is an active-low asynchronous reset; all signals are sampled on the rising
edge of clk and reset by rst_n.
Sleep mode: the block enters Sleep mode when enable is low.
Overflow saturates. Underflow holds. Illegal opcodes ignored. Back-to-back ok.
Reset during operation clears q.
"""
    res, f = run(tmp_path, spec)
    assert 'mode-missing-exit' in codes(f)
    assert 'mode-missing-entry' not in codes(f)  # entry IS present


# ---- corner-case coverage --------------------------------------------------
def test_corner_case_uncovered(tmp_path):
    spec = """\
Implement TopModule.
 - input  clk
 - input  rst_n
 - output q
rst_n is an active-low asynchronous reset; q is sampled on the rising edge of clk
and reset by rst_n. The block just registers the input.
"""
    res, f = run(tmp_path, spec)
    # none of the four corner cases addressed -> four uncovered findings
    cc = [x for x in f if x['code'] == 'corner-case-uncovered']
    assert len(cc) == 4, f


# ---- no-false-alert: pure prose (no interface list) -> no signal findings --
def test_pure_prose_no_signal_findings(tmp_path):
    spec = """\
This block computes a running average and outputs the result. It handles overflow
by saturating, underflow by holding empty, and reserved/illegal opcodes are
ignored. Back-to-back samples are accepted and a reset during operation
reinitialises the accumulator.
"""
    res, f = run(tmp_path, spec)
    assert 'signal-missing-attr' not in codes(f), f
    assert res.returncode == 0


# ---- JSON contract form ----------------------------------------------------
def test_json_contract_complete_no_findings(tmp_path):
    spec = json.dumps({
        "module": "TopModule",
        "ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "d", "direction": "input", "width": 8},
            {"name": "q", "direction": "output", "width": 8}],
        "reset": {"mode": "asynchronous", "polarity": "active-low",
                  "signal": "rst_n"}})
    res, f = run(tmp_path, spec, '.json')
    assert res.returncode == 0
    # JSON contract is authoritative; no signal-attr finding here
    assert 'signal-missing-attr' not in codes(f)


# ---- graceful degradation: empty / tiny / missing --------------------------
def test_empty_spec_skips(tmp_path):
    res, f = run(tmp_path, "")
    assert res.returncode == 0
    assert codes(f) == {'spec-too-short'}


def test_missing_spec_exits_2(tmp_path):
    res = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / 'nope.md')],
                         capture_output=True, text=True)
    assert res.returncode == 2


# ---- vibe-ic#693 — the verdict must disclose its own denominator -----------
#
# This program is reached through a GLOB. Measured on a published run: an
# `input/docs/*.md` pattern matched 1 file in a directory holding 17 `.rst`
# spec chapters, and the program still printed a verdict — reading exactly like
# a verdict over the whole corpus. The unread siblings are now reported at INFO,
# which by construction cannot move the exit code.
def _lint(tmp_path, argv):
    return subprocess.run([sys.executable, str(SCRIPT), *argv],
                          capture_output=True, text=True)


def test_partial_corpus_is_disclosed(tmp_path):
    d = tmp_path / 'docs'
    d.mkdir()
    (d / 'a.md').write_text(COMPLETE)
    (d / 'b.rst').write_text("Chapter two of the same spec, unread.\n" * 3)
    res = _lint(tmp_path, [str(d / 'a.md')])
    assert res.returncode == 0                     # INFO cannot fail the gate
    assert 'spec-corpus-partial' in res.stdout
    assert 'b.rst' in res.stdout
    assert '1 spec(s) linted of 2 candidate(s)' in res.stdout


def test_full_corpus_emits_no_disclosure(tmp_path):
    d = tmp_path / 'docs'
    d.mkdir()
    (d / 'a.md').write_text(COMPLETE)
    res = _lint(tmp_path, [str(d / 'a.md')])
    assert res.returncode == 0
    assert 'spec-corpus-partial' not in res.stdout
    assert '1 spec(s) linted of 1 candidate(s)' in res.stdout


def test_own_json_report_is_not_counted_as_an_unread_spec(tmp_path):
    d = tmp_path / 'docs'
    d.mkdir()
    (d / 'a.md').write_text(COMPLETE)
    jf = d / 'report.json'
    jf.write_text('{}')                            # pre-existing, beside the spec
    res = _lint(tmp_path, ['--json', str(jf), str(d / 'a.md')])
    assert res.returncode == 0
    assert 'spec-corpus-partial' not in res.stdout


def test_strict_is_load_bearing(tmp_path):
    """Without --strict the program cannot fail on WARNs, so a gate wired
    without it would be a gate that can never fire."""
    bad = tmp_path / 'bad.md'
    bad.write_text("# Gadget\n\n## Timing\nThe propagation delay is 5 ns.\n")
    assert _lint(tmp_path, [str(bad)]).returncode == 0
    assert _lint(tmp_path, ['--strict', str(bad)]).returncode == 1


def test_a_directory_argument_can_never_execute(tmp_path):
    """The flow must pass a GLOB LIST, never `.`. A directory is not a file, so
    the program exits 2 forever — which the flow reads as a permanent
    VACUOUS_PASS, i.e. wired somewhere it can never run."""
    (tmp_path / 'spec.md').write_text(COMPLETE)
    assert _lint(tmp_path, ['--strict', str(tmp_path)]).returncode == 2


def test_corner_case_checklist_is_evaluated_per_file_not_per_corpus(tmp_path):
    """MEASURED DEFECT, pinned so a fix has to update this test deliberately.

    A complete spec scores 0 findings alone. Adding one benign, unrelated
    appendix file to the SAME invocation yields 4 `corner-case-uncovered`
    WARNs — the appendix does not mention the corner cases, and the checklist
    is asked per FILE instead of per corpus. This is why `--strict` is wired
    ADVISORY: 78% of the WARNs measured over the published corpus are this.
    """
    d = tmp_path / 'docs'
    d.mkdir()
    (d / 'a.md').write_text(COMPLETE)
    alone = _lint(tmp_path, ['--strict', str(d / 'a.md')])
    assert alone.returncode == 0
    assert alone.stdout.count('corner-case-uncovered') == 0

    (d / 'appendix.md').write_text(
        "# Appendix A — Revision history\nRev 1.0 first release.\n")
    both = _lint(tmp_path, ['--strict', str(d / 'a.md'), str(d / 'appendix.md')])
    assert both.returncode == 1
    assert both.stdout.count('corner-case-uncovered') == 4
