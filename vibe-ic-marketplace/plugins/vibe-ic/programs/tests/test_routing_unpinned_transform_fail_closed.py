#!/usr/bin/env python3
"""An unpinned transform must still route fail-CLOSED to a real entry.

MEASURED DEFECT (2026-08-31 adversarial review, 8 of 12 real transform
sentences fell in). `classify_task_nature` labels a context-bearing task whose
verb no prose hint recognises `nature="transform_existing_rtl"`. That label is
DISCLOSURE — it is deliberately not a NATURE_ENTRY key. Both consumers
(`benchmark_dispatch._solve_one`, `flow_phase_attribution.derive_routing`)
looked the LABEL up with `.get(nature, {})`: empty row, entry/evidence/exit all
None, the `--skip-phase3` condition never true — a full GDS run for an RTL
deliverable. The router had already computed the right table key
(`_UNPINNED_TRANSFORM_ENTRY`) to pick `plugin_entry`; it just never returned
it. The fix returns it as `entry_nature`, present on EVERY branch, and the
consumers index the table with THAT — a lookup that cannot miss.

Two recall bugs ride along: `reduce\\s+(area|...)` had no room for an article
("reduce the area" fell through), and the completion noun whitelist lacked
`logic` ("complete the missing logic" fell through).

EVERY FIXTURE IS GENERIC. No vendor, SKU or design name; the sentences are
minimal synthetic shapes reproducing the adversarial review's structure.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import benchmark_dispatch as bd  # noqa: E402
import flow_phase_attribution as fpa  # noqa: E402
import task_nature_route as tnr  # noqa: E402


_BODY = """module widget (
    input  a,
    input  b,
    output c
);
    assign c = a & b;
endmodule
"""

# The adversarial review's fall-through shapes: real transform requests whose
# verb no prose hint pinned, each arriving WITH the RTL it transforms.
_TRANSFORM_SENTENCES = (
    "Extend this module so the output is registered.",
    "Refactor the provided design to use a single always block.",
    "Add a second read port to the register file.",
    "Update the FSM to add a new WAIT state.",
    "Convert this Moore FSM into a Mealy FSM.",
    "Reduce the area of this design.",
    "Complete the missing logic in this module.",
    "Rewrite the module to use one-hot state encoding.",
)


# ── 1. every verdict carries a table key, and the key resolves ───────────────

@pytest.mark.parametrize("sentence", _TRANSFORM_SENTENCES)
def test_entry_nature_is_always_a_table_key_with_a_real_exit(sentence):
    """The consumer-side lookup chain must produce a value at every link."""
    v = tnr.classify_task_nature(sentence + "\n\n" + _BODY, True, None)
    assert v["entry_nature"] in tnr.NATURE_ENTRY, v
    row = tnr.NATURE_ENTRY[v["entry_nature"]]
    entry = row.get("entry_step")
    ev = row.get("default_evidence")
    exit_step = (tnr.EVIDENCE_EXIT.get(ev) or {}).get("exit_step")
    assert entry is not None, v
    assert ev is not None, v
    assert exit_step is not None, v


def test_the_unpinned_label_is_kept_and_the_key_is_returned_beside_it():
    """`nature` stays the disclosing label — the fix adds the key, it does not
    overwrite what the verdict admits about itself."""
    v = tnr.classify_task_nature(
        "Refactor the provided design to use a single always block.\n\n"
        + _BODY, True, None)
    assert v["nature"] == "transform_existing_rtl"
    assert v["entry_nature"] == "functional_modification"
    assert v["source"] == "context_heuristic"


# ── 2. the two recall bugs ───────────────────────────────────────────────────

def test_reduce_the_area_is_an_optimization_hint():
    hints = dict(tnr._PROSE_HINTS)
    assert hints["optimization"].search("Reduce the area of this design")
    assert hints["optimization"].search("reduce area")
    v = tnr.classify_task_nature(
        "Reduce the area of this design.\n\n" + _BODY, True, None)
    assert v["nature"] == "optimization"
    assert v["entry_nature"] == "optimization"


def test_complete_the_missing_logic_is_a_completion_hint():
    hints = dict(tnr._PROSE_HINTS)
    assert hints["completion"].search("Complete the missing logic")
    v = tnr.classify_task_nature(
        "Complete the missing logic in this module.\n\n" + _BODY, True, None)
    assert v["nature"] == "completion"
    assert v["entry_nature"] == "completion"


def test_the_widened_hints_do_not_leak_outside_their_objects():
    """§ 4.05 — both widenings admit MORE prompts, so the boundary just
    outside each must still be refused."""
    hints = dict(tnr._PROSE_HINTS)
    for benign in ("Reduce the latency of the pipeline",
                   "Reduce the risk of metastability",
                   "reduce noise on the output"):
        assert not hints["optimization"].search(benign), benign
    for benign in ("The complete logic equations are given below.",
                   "Implement the logic described above.",
                   "Provide complete documentation for the module."):
        assert not hints["completion"].search(benign), benign


# ── 3. the five pinned natures are a no-op ───────────────────────────────────

@pytest.mark.parametrize("nature", sorted(tnr.NATURE_ENTRY))
def test_declared_natures_are_unchanged(nature):
    v = tnr.classify_task_nature("", False, nature)
    assert v["nature"] == nature
    assert v["entry_nature"] == nature
    assert v["route"] == tnr.NATURE_ENTRY[nature]["route"]
    assert v["plugin_entry"] == tnr.NATURE_ENTRY[nature]["plugin_entry"]


def test_every_classify_branch_returns_entry_nature():
    """One probe per branch of `classify_task_nature`."""
    cases = (
        ("Build an adder from this description.", False),   # no_context
        ("Fix the bug in this module.\n\n" + _BODY, False),  # embedded_rtl
        ("The output is incorrect when both inputs are high.", False),  # warn
        ("Complete the following module.", False),  # completion w/o artifact
        ("Extend this module so the output is registered.", True),  # unpinned
    )
    for prompt, has_ctx in cases:
        v = tnr.classify_task_nature(prompt, has_ctx, None)
        assert v["entry_nature"] in tnr.NATURE_ENTRY, (prompt, v)


# ── 4. the drift guard ───────────────────────────────────────────────────────

def test_validate_entries_accepts_the_real_tables():
    assert tnr.validate_entries() == []


def test_validate_entries_rejects_a_drifted_unpinned_entry(monkeypatch):
    monkeypatch.setattr(tnr, "_UNPINNED_TRANSFORM_ENTRY", "no_such_nature")
    problems = tnr.validate_entries()
    assert any("_UNPINNED_TRANSFORM_ENTRY" in p for p in problems), problems


# ── 5. the consumers, end to end ─────────────────────────────────────────────

def _consumer_lookup(verdict):
    row = tnr.NATURE_ENTRY[verdict["entry_nature"]]
    ev = row.get("default_evidence")
    return (row.get("entry_step"), ev,
            (tnr.EVIDENCE_EXIT.get(ev) or {}).get("exit_step"))


def test_dispatch_argv_for_an_unpinned_transform_skips_phase3(tmp_path):
    """THE MEASURED CONSEQUENCE. Before the fix the empty row made exit_step
    None and the runner ran the full GDS flow for an RTL deliverable."""
    v = tnr.classify_task_nature(
        "Convert this Moore FSM into a Mealy FSM.\n\n" + _BODY, True, None)
    entry, ev, exit_step = _consumer_lookup(v)
    argv = bd._solver_argv(tmp_path / "runner.py", tmp_path / "proj",
                           entry, exit_step)
    assert "--skip-phase3" in argv, argv


def test_dispatch_argv_without_an_exit_runs_phase3(tmp_path):
    """The old fail-open shape, pinned: a None exit means Phase 3 runs — which
    is exactly why the lookup must never come back empty."""
    argv = bd._solver_argv(tmp_path / "runner.py", tmp_path / "proj",
                           None, None)
    assert "--skip-phase3" not in argv, argv


def test_derive_routing_resolves_an_unpinned_transform(tmp_path):
    """The second consumer, on a real project layout."""
    proj = tmp_path / "proj"
    (proj / "input" / "rtl").mkdir(parents=True)
    (proj / "input" / "phase1_prompt.md").write_text(
        "Update the FSM to add a new WAIT state.\n")
    (proj / "input" / "rtl" / "top.v").write_text(_BODY)
    r = fpa.derive_routing(proj)
    assert r["verdict"]["nature"] == "transform_existing_rtl"
    assert r["verdict"]["entry_nature"] == "functional_modification"
    assert r["entry"] is not None
    assert r["evidence"] is not None
    assert r["exit_step"] is not None
