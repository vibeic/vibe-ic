#!/usr/bin/env python3
"""The task decides where the run STARTS and where it STOPS.

    "怎麼可能為了回答一個 benchmark 的問題,都去跑 Phase 2、Phase 3 的整個流程呢?"
                                                — owner directive 2026-08-25

Entry alone was half the answer: with only an entry, VerilogEval's 156 atomic
problems would each run through synthesis and physical design to hand back a
single .sv file that the scorer reads and nothing else looks at.

STOPPING NEEDS TWO FIELDS. Measured against the three open benchmarks' real
scorers: VerilogEval reads `samples/<Prob>_sample01.sv`, RTLLM reads each
design's RTL, CVDP reads a `{id, completion}` RTL string — all three hand back
step 1's artefact and none reads a netlist or a GDS. But CVDP cid007 hands back
that same RTL and is GRADED ON AREA, measurable only at step 9. Same
answer_step, different verify_through; one field would have to pick one of those
two mistakes.
"""
import os
import sys

_PROGRAMS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, _PROGRAMS)

import task_nature_route as T  # noqa: E402


def _order():
    """Flow declaration order, the only ordering the flow actually gives."""
    return {sid: i for i, sid in enumerate(T.flow_step_ids())}


def test_every_declared_step_is_real():
    problems = T.validate_entries()
    assert not problems, "\n".join(problems)


def test_every_nature_says_what_proof_its_question_demands():
    """Nature fixes the ENTRY; the evidence class fixes the EXIT. The same
    nature ends in different places depending on the verb of the demand —
    "write this module" vs "write this module and prove it works"."""
    for nature, e in T.NATURE_ENTRY.items():
        ev = e.get("default_evidence")
        assert ev in T.EVIDENCE_EXIT, f"{nature}: {ev!r} is not an evidence class"


def test_no_nature_runs_past_its_own_verification():
    """The waste the directive objects to: running on after the answer is trusted."""
    o = _order()
    for nature, e in T.NATURE_ENTRY.items():
        entry = str(e["entry_step"])
        ver = str(T.EVIDENCE_EXIT[e["default_evidence"]]["exit_step"])
        assert o[ver] >= o[entry], (
            f"{nature}: verify_through {ver} precedes entry {entry} — the run "
            f"would have to stop before it starts")


def test_optimization_must_outrun_its_answer_step():
    """The case a single exit_step cannot express: RTL is handed back, area is
    graded, and area does not exist until synthesis."""
    e = T.NATURE_ENTRY["optimization"]
    o = _order()
    assert e["default_evidence"] == "area"
    assert T.EVIDENCE_EXIT["area"]["exit_step"] == "9"
    # the deliverable is still step 1's RTL — the metric is what must be proven
    assert T.DELIVERY_TARGETS["rtl"]["answer_step"] == "1"
    assert o["9"] > o["1"], "synthesis must follow RTL for this to mean anything"


def test_no_rtl_nature_verifies_through_physical_design():
    """No open RTL benchmark's scorer reads a netlist or a GDS. A nature that
    verified through PnR would burn work nothing consumes."""
    o = _order()
    for nature in ("spec_generation", "completion", "functional_modification",
                   "debug"):
        ver = str(T.EVIDENCE_EXIT[
            T.NATURE_ENTRY[nature]["default_evidence"]]["exit_step"])
        assert o[ver] < o["9"], (
            f"{nature} verifies through {ver}, at or past synthesis — no RTL "
            f"scorer reads that artefact")


def test_the_deliverable_can_predate_the_entry():
    """`optimization` and `debug` enter AFTER the step that DECLARES their
    deliverable: the RTL lives at step 1's path, but step 1 never runs — the
    file is edited in place. The delivery target is a LOCATION, not an
    instruction to run that step; reading it the other way sends both natures
    backwards through the flow."""
    o = _order()
    answer = str(T.DELIVERY_TARGETS["rtl"]["answer_step"])
    for nature in ("optimization", "debug"):
        assert o[answer] < o[str(T.NATURE_ENTRY[nature]["entry_step"])], (
            f"{nature} no longer exercises the location-not-instruction case; "
            f"if that is deliberate, rewrite this test rather than delete it")


# ── delivery targets: the same shape at the far end of the flow ──────────────
def test_shippable_gds_separates_the_artefact_from_its_signoff():
    """37 emits the GDS; 37.5ic ('Tape-out Precheck') says it is shippable.
    Identical structure to cid007 — which is why this is not a benchmark quirk."""
    d = T.DELIVERY_TARGETS["shippable_gds"]
    assert d["answer_step"] == "37"
    assert d["verify_through"] == "37.5ic"
    assert T.DELIVERY_TARGETS["gds"]["answer_step"] == "37"
    assert T.DELIVERY_TARGETS["gds"].get("verify_through", "37") == "37"


def test_ip_delivery_is_a_different_target_not_a_shorter_chip():
    """37.5ip and 37.5ic both block on [37, 0.5ic] — parallel deliverables."""
    ip = T.DELIVERY_TARGETS["ip_hardmacro"]
    assert ip["answer_step"] == "37.5ip"
    assert "lef" in ip["artefact"] and "lib" in ip["artefact"]


def test_every_delivery_target_names_real_steps():
    ids = set(T.flow_step_ids())
    for tgt, d in T.DELIVERY_TARGETS.items():
        for key in ("answer_step", "verify_through"):
            sid = d.get(key)
            if sid is not None:
                assert str(sid) in ids, f"{tgt}.{key}={sid!r} is not a flow step"


def test_rtl_delivery_is_what_the_open_benchmarks_actually_read():
    d = T.DELIVERY_TARGETS["rtl"]
    assert d["answer_step"] == "1"
    assert "phase2/stage1/rtl" in d["artefact"]


if __name__ == "__main__":
    for k, v in sorted(globals().items()):
        if k.startswith("test_"):
            v()
            print("PASS", k)
