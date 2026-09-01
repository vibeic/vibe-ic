"""#599 D1 + step 14 — the roll-up had no word between PASS and VACUOUS-PASS.

Two different things arrived wearing the same token, and neither gate was what
was wrong:

  * step 14  `yosys_hilomap_required_check` prints `VACUOUS_PASS:` because no
             `.ys` script existed, and in the same sentence reports that the
             runner's INLINE `yosys -p` command was extracted and verified.
             Its docstring keeps the vacuous word ON PURPOSE and says
             `reason_class` carries how much was verified. The roll-up read the
             token and never the reason.

  * D1       `phase1_expert_parse_track` used to return VACUOUS_PASS when no
             deterministic rule applied AND the AI sub-track never answered.
             Issue #1973 promotes that applicable, unexecuted state to a real
             INCOMPLETE exit: handoff creation is not expert execution.

DISCLOSED BY A PRINTED SENTINEL, never by matching a gate's prose — matching
prose is how a gate that says "I verified the inline command" was read as "I
examined nothing" to begin with.

The generic printed INCOMPLETE tier remains a disclosure when a gate exits 0.
The D1 expert track now exits 1 on that same state because its execution is
mandatory while its eventual design findings remain advisory. Those are two
different policies and must not share one return code.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


FC = _load("flow_compliance_check")
SRC = (_PROGRAMS / "flow_compliance_check.py").read_text(encoding="utf-8")


# ── the detector ────────────────────────────────────────────────────────────
def test_a_token_at_line_start_is_seen():
    assert FC._stdout_signals_token("noise\n  INCOMPLETE: x\n", "INCOMPLETE")


def test_a_token_mid_line_is_not():
    """Otherwise a gate MENTIONING the word in prose raises the tier — the
    text-matching failure this mechanism exists to avoid."""
    assert not FC._stdout_signals_token(
        "the run was INCOMPLETE last time\n", "INCOMPLETE")


def test_the_old_vacuous_detector_is_one_caller_of_it():
    """Three copies of the same loop would be three places to drift."""
    assert FC._stdout_signals_vacuous("VACUOUS_PASS: nothing applied")
    assert "_stdout_signals_token" in SRC


# ── the tiers are resolved, DRIVEN not read ─────────────────────────────────
#
# The first version of these two asserted the ORDER OF TWO STRINGS in the
# source. Making the INCOMPLETE branch unreachable (`elif False and ...`) left
# that order untouched and both assertions passed — an assertion that cannot
# fail for the reason it exists. They drive `check_step` now.
def _status(tmp_path, prints, monkeypatch):
    """Run a real step whose gate prints `prints` and exits 0.

    `_resolve_program_cmd` only resolves names under PROGRAMS_DIR, so the probe
    is injected there rather than shipped as a program nobody calls. The tier
    resolution is what is under test; the resolver is not.
    """
    g = tmp_path / "g.py"
    g.write_text("print(%r)\n" % prints, encoding="utf-8")
    monkeypatch.setattr(FC, "_resolve_program_cmd",
                        lambda cmd, cwd=None: [sys.executable, str(g)])
    step = {"id": "T1", "name": "tier probe",
            "gate": {"program_exit_zero": "probe"}}
    return FC.check_step(tmp_path, step, {}).status


def test_a_gate_that_examined_nothing_is_still_vacuous(tmp_path, monkeypatch):
    """THE ACCEPT CASE, and the one the other two must not swallow."""
    assert _status(tmp_path, "VACUOUS_PASS: nothing applied", monkeypatch) == "VACUOUS_PASS"


def test_a_substantive_disclosure_turns_a_vacuous_step_into_a_pass(tmp_path, monkeypatch):
    got = _status(tmp_path, "VACUOUS_PASS: no .ys script\n"
                            "SUBSTANTIVE_PASS: verified the inline command", monkeypatch)
    assert got == "PASS", (
        f"got {got}: a gate that verified the equivalent by another route is "
        f"still tallied as having examined nothing")


def test_an_unexamined_applicable_input_is_incomplete(tmp_path, monkeypatch):
    got = _status(tmp_path, "INCOMPLETE: the AI sub-track did not read", monkeypatch)
    assert got == "INCOMPLETE", got


def test_incomplete_wins_over_vacuous_when_a_gate_raises_both(tmp_path, monkeypatch):
    """"Applicable and not examined" is the stronger statement."""
    got = _status(tmp_path, "VACUOUS_PASS: no rule applied\n"
                            "INCOMPLETE: the AI sub-track did not read", monkeypatch)
    assert got == "INCOMPLETE", got


def test_a_plain_pass_is_untouched(tmp_path, monkeypatch):
    assert _status(tmp_path, "all good", monkeypatch) == "PASS"


def test_the_new_hints_are_held_out_of_the_displayed_reasons():
    """An internal marker printed as a reason is noise a reviewer learns to
    skip — the same treatment every other hint already gets."""
    seg = SRC[SRC.index("non_hint_reasons = [r for r in reasons"):][:700]
    assert "_SUBSTANTIVE_HINT_PREFIX" in seg and "_INCOMPLETE_HINT_PREFIX" in seg


def test_incomplete_is_counted_labelled_and_rendered():
    assert '"INCOMPLETE": 0}' in SRC, "not in the tally"
    assert '"INCOMPLETE": "INCOMPLETE"}' in SRC, "no display label"
    assert '"INCOMPLETE": "…"' in SRC, "no icon, so it renders as `?`"
    assert "incomplete_str" in SRC, "absent from the summary line"


def test_it_is_a_disclosure_tier_not_a_failure():
    """LOAD-BEARING. Aggregating it as a failure would turn designs red on a
    naming fix, which is a different decision with a corpus sweep in front of
    it."""
    for bucket in ("failing", "missing"):
        assert f'"INCOMPLETE"' not in SRC[SRC.index(f"{bucket} ="):][:400], (
            f"INCOMPLETE leaked into the {bucket} bucket")


# ── the two gates actually emit the sentinels ───────────────────────────────
def test_step14_discloses_only_on_the_verified_tiers():
    """`_unconfirmed` means no inline command was echoed anywhere, so nothing
    was read. Emitting the disclosure there would credit a step for work that
    did not happen — the defect, inverted."""
    src = (_PROGRAMS / "yosys_hilomap_required_check.py").read_text(
        encoding="utf-8")
    assert "SUBSTANTIVE_PASS:" in src
    # COMMENTS STRIPPED. The comment beside the guard has to NAME the tier it
    # excludes in order to explain the exclusion, so a scan that cannot tell
    # documentation from code fails on its own rationale — which is what the
    # first version of this assertion did, for the fifth time in this campaign.
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    at = code.index('print(f"SUBSTANTIVE_PASS')
    seg = code[at - 400:at]
    assert "inline_yosys_p_mode_conformant" in seg
    assert "inline_yosys_p_mode_confirmed" in seg
    assert "unconfirmed" not in seg, (
        "the disclosure fires on the tier where nothing was read")
    assert "_unconfirmed" in src, (
        "the comment explaining why that tier is excluded is gone")


def test_d1_discloses_incomplete_only_when_the_ai_half_did_not_read():
    src = (_PROGRAMS / "phase1_expert_parse_track.py").read_text(
        encoding="utf-8")
    assert 'print(f"INCOMPLETE: {PROGRAM}' in src
    seg = src[src.index('if rep["verdict"] == "INCOMPLETE":'):][:1100]
    assert 'non-empty schema-readable review' in seg
    assert 'ai[\'status\']' in seg
    assert 'VACUOUS_PASS' not in seg, (
        "an unanswered expert handoff is still published as a pass tier")


def test_the_yosys_gate_still_runs_and_says_something(tmp_path):
    """End-to-end on an empty project: no `.ys`, no synth log — the
    `_unconfirmed` tier, which must NOT carry the disclosure."""
    r = _pr.run(
        [sys.executable, str(_PROGRAMS / "yosys_hilomap_required_check.py"),
         str(tmp_path)], capture_output=True, text=True)
    out = r.stdout + r.stderr
    assert "VACUOUS_PASS" in out, out
    assert "SUBSTANTIVE_PASS" not in out, (
        "nothing was read on this project and the gate claimed otherwise")
