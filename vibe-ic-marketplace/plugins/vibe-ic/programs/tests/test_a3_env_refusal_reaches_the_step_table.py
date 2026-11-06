"""An environment refusal at A3 reaches the step table as itself, and the
steps below it name A3 rather than an absence they did not cause
(vibe-ic#2088).

MEASURED, END TO END, 2026-09-07 on 8HD-9 against 94617408759e, one real
project, one real `analog_one_shot_runner` invocation per arm, with the host's
`vibeic-eda` container holding sha256:06537f7e… (0.3.46) against a pin of
sha256:8c5694ab… (0.3.48). Rows for the block whose netlist A3 could not
produce:

  PRISTINE MAIN
    WAIVED  A3_netlist_gen       deterministic producer ERRORED rc=1 and wrote
                                 NO gap file — this is not an honest gap: …
    FAIL    A4_corner_sweep      A4_SHA_SOURCE_UNREADABLE: netlist_source=
                                 'phase3/analog/ldo/ldo.sp' … cannot be read now
    PASS    A5_layout            MATCHING: 1 did not say (ldo)
    PASS    A6_block_pv          MATCHING: 1 did not say (ldo)
    PASS    A7_post_layout_resim PASS — 1/1 block(s) clean

  WITH THIS COMMIT, same command, same container
    BLOCKED A3_netlist_gen       ENV_REFUSED: analog_a3_netlist_emit:
                                 CONTAINER_IMAGE_MISMATCH: container vibeic-eda
                                 runs sha256:06537f7e…, but the pinned runtime
                                 is …@sha256:8c5694ab…
    BLOCKED A4_corner_sweep      upstream A3_netlist_gen refused: <that line>
    BLOCKED A5_layout            upstream A3_netlist_gen refused: <that line>
    BLOCKED A6_block_pv          upstream A3_netlist_gen refused: <that line>
    BLOCKED A7_post_layout_resim upstream A3_netlist_gen refused: <that line>

THE THREE PASSES ARE THE POINT. A5, A6 and A7 reported PASS for a block whose
netlist was never produced, on a run where the cause was one line the producer
had already printed. `WAIVED` reads "not produced yet, invoke the skill" — and
no skill can supply a container running the pinned image, so the advice could
not be acted on either.

THE MEASURED ROW ALSO CORRECTS THE ISSUE'S OWN TEXT. #2088 reports the WAIVED
detail ending in a bare dash with nothing after it; at this base the tail
carries the traceback's last line, which does name the mismatch. What is
missing at THIS tip is not the text but the TIER: a host condition recorded as
a producer defect, and four downstream verdicts about the design.

The tests below drive the runner's own `step_for_block`. Only the A3
producer's ANSWER is supplied; the gate, the dispatch and every downstream step
are the shipped code.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401 — puts programs/ on sys.path
import _analog_producer_common as PC
import verdict as _V  # noqa: E402
import analog_one_shot_runner as R
from _analog_producer_fixture import block, make_project

LDO_SPEC = [{"name": "Vout", "target": 1.8, "unit": "V"},
            {"name": "Vref", "target": 0.9, "unit": "V"}]

REFUSAL = ("CONTAINER_IMAGE_MISMATCH: container vibeic-eda runs "
           "sha256:06537f7e8d3c17c6c9c60c20638e94faab0421533a55656ad1819f38"
           "3c373aba, but the pinned runtime is repo@sha256:8c5694abdf5c269c"
           "1d9def5368704e0c4b51c869d1d9c9380e123e07657fe9eb")
REFUSAL_LINE = PC.env_refused_line("analog_a3_netlist_emit", REFUSAL)


@pytest.fixture()
def project(tmp_path):
    p = make_project(tmp_path / "proj", [block("vreg_alpha", "ldo", LDO_SPEC)])
    blk = {"name": "vreg_alpha", "type": "ldo"}
    R.reset_env_refusals()
    R.step_for_block(p, blk, "A1_spec_extract")
    R.step_for_block(p, blk, "A2_topology_select")
    return p, blk


def _a3_answers(monkeypatch, rc, stderr):
    """Let everything run for real except the A3 producer, whose exit code and
    stderr are supplied. A spy that replaced the GATE too would be asserting
    against a runner nobody runs."""
    real = R._pr.run

    def _run(cmd, *a, **kw):
        if any("analog_a3_netlist_emit.py" in str(t) for t in cmd):
            return subprocess.CompletedProcess(list(cmd), rc, "", stderr)
        return real(cmd, *a, **kw)

    monkeypatch.setattr(R._pr, "run", _run)


# ═══ the step that hit it ═════════════════════════════════════════════════


def test_the_row_carries_the_refusals_own_line(project, monkeypatch):
    """Both digests, in the row. A reader told only that the environment
    refused cannot tell a stale container from a mis-set repository."""
    p, blk = project
    _a3_answers(monkeypatch, PC.EX_ENV_REFUSED, REFUSAL_LINE + "\n")
    res = R.step_for_block(p, blk, "A3_netlist_gen")
    assert "sha256:06537f7e" in res.detail, res.detail
    assert "sha256:8c5694ab" in res.detail, res.detail


def test_the_refusal_cannot_round_up_to_a_green_verdict(project, monkeypatch):
    p, blk = project
    _a3_answers(monkeypatch, PC.EX_ENV_REFUSED, REFUSAL_LINE + "\n")
    res = R.step_for_block(p, blk, "A3_netlist_gen")
    # R-0915-85 — `_FAIL_STATUSES` was this runner's own list of which words
    # meant "not green"; the flow owns that now and there is exactly one
    # answer. An env refusal is NOT a FAIL (nothing about the design failed)
    # and is NOT green either.
    assert _V.is_non_green(res.status), (res.status, res.detail)
    assert res.status == _V.Verdict.NOT_MEASURED.value, res
    assert res.reason_class, "an env refusal must name what stopped it"
    assert R._aggregate_verdict([res]) != "PASS"


def test_a_producer_that_really_errored_is_still_the_errored_row(project,
                                                                 monkeypatch):
    """THE PAIRED ARM. Narrowing what may be WAIVED must not delete the case
    it is for: a producer that crashed (rc 1) is still an ERRORED row, and is
    still not an environment refusal."""
    p, blk = project
    _a3_answers(monkeypatch, 1, "Traceback (most recent call last):\nboom\n")
    res = R.step_for_block(p, blk, "A3_netlist_gen")
    assert res.status == "NOT_MEASURED", (res.status, res.detail)
    assert "ERRORED rc=1" in res.detail, res.detail
    assert res.extras.get("verdict_tier") != "ENV_UNAVAILABLE"


# ═══ the steps below it ═══════════════════════════════════════════════════


def test_a_downstream_step_with_a_deck_on_disk_is_not_short_circuited(
        project, monkeypatch):
    """THE GUARD IS ON THE ARTEFACT, not on the refusal alone. A block whose
    deck an earlier run emitted still has one, and these steps can grade it —
    refusing there would decline work that can actually be done."""
    p, blk = project
    _a3_answers(monkeypatch, PC.EX_ENV_REFUSED, REFUSAL_LINE + "\n")
    R.step_for_block(p, blk, "A3_netlist_gen")
    deck = p / "phase3/analog/vreg_alpha/vreg_alpha.sp"
    deck.parent.mkdir(parents=True, exist_ok=True)
    deck.write_text("* a deck an earlier run left behind\n", encoding="utf-8")
    res = R.step_for_block(p, blk, "A5_layout")
    assert not res.detail.startswith("upstream "), res.detail


def test_a_step_that_does_not_consume_a3s_product_is_untouched(project,
                                                               monkeypatch):
    """A8 does not read the `.sp`, so an A3 refusal says nothing about it.
    Without this, "record the refusal" would quietly become "fail the run"."""
    p, blk = project
    _a3_answers(monkeypatch, PC.EX_ENV_REFUSED, REFUSAL_LINE + "\n")
    R.step_for_block(p, blk, "A3_netlist_gen")
    assert R.upstream_env_refusal("vreg_alpha", "A8_hardmacro_gen") is None
    assert R.upstream_env_refusal("vreg_alpha", "A9_hw_verify") is None


def test_a_refusal_is_scoped_to_its_own_block(project, monkeypatch):
    """Two blocks of one design fail independently; a refusal recorded for one
    must not block the other."""
    p, blk = project
    _a3_answers(monkeypatch, PC.EX_ENV_REFUSED, REFUSAL_LINE + "\n")
    R.step_for_block(p, blk, "A3_netlist_gen")
    assert R.upstream_env_refusal("vreg_alpha", "A4_corner_sweep") is not None
    assert R.upstream_env_refusal("other_blk", "A4_corner_sweep") is None


def test_a_run_inherits_no_refusal_from_the_previous_one(project, monkeypatch):
    p, blk = project
    _a3_answers(monkeypatch, PC.EX_ENV_REFUSED, REFUSAL_LINE + "\n")
    R.step_for_block(p, blk, "A3_netlist_gen")
    assert R.upstream_env_refusal("vreg_alpha", "A4_corner_sweep") is not None
    R.reset_env_refusals()
    assert R.upstream_env_refusal("vreg_alpha", "A4_corner_sweep") is None


# ═══ the reader that decides it ═══════════════════════════════════════════

def test_the_sentinel_is_read_at_the_start_of_a_line_only():
    """A token matched anywhere in a line is a token a MENTION of it also
    matches. The tier decides that nothing about the design was learned, so it
    is read from a sentinel that opens its own line and can therefore not be a
    negation, a quotation or a comment about one."""
    real = subprocess.CompletedProcess(
        [], 69, "", REFUSAL_LINE + "\n")
    assert R._producer_env_gap(real) == REFUSAL_LINE[:400]

    talked_about = subprocess.CompletedProcess(
        [], 0, "", "the run did not print ENV_REFUSED: anything at all\n")
    assert R._producer_env_gap(talked_about) is None
