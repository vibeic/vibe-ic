"""A #492 disclosure line is NOT a verdict — no consumer may read it as one.

THE DEFECT THIS PINS DOWN
-------------------------
#492 made the P0 umbrella DISCLOSE the registered structural gates that
argument parsing rejected. Those gates returned no verdict at all, so the
disclosure was deliberately NOT made a failure, and it is not one in the
umbrella's own status: the same project reports the same `Failed gates (N)`
before and after.

But the disclosure is written into ``StepResult.reasons``, and FOUR consumers
scrape that list line by line, treating every line as a failing gate unless it
carries a prefix they happen to know:

  1. ``_parse_p0_failing_subgates``      -> the heading + every bullet became
                                            a failing gate NAME;
  2. ``_normalise_p0_reason_line`` ->
     ``_per_gate_from_p0_reasons``        -> its unconditional ``"- "`` ->
                                            ``"FAIL: "`` rewrite turned every
                                            disclosed gate into a per-gate
                                            FAIL record carrying its REAL
                                            name;
  3. the ``structural_fail_lines`` scrape -> same ``- `` prefix, and that list
                                            is what sets ``forced_fail`` under
                                            ``--phase 2 --strict-structural``,
                                            the flags
                                            ``design_one_shot_runner.
                                            step_final_audit`` actually ships;
  4. the audit-JSON writer                -> consumes 1 and 2.

and (1) additionally feeds two ``all(...)`` predicates —
``_step_failure_is_informational_only`` and the
PASS_WITH_OPEN_SOURCE_CONSTRAINTS ``p0_is_deferrable`` test — both of which go
False the instant an unrecognised name appears. Each turns a TOLERATED outcome
into a FAIL: the exact false-FAIL class the disclosure was careful to avoid,
arriving through a channel nobody checked.

MEASURED on `subservient`, phase 2, production flags, before the fix:
``failed_gate_count 77`` of which 75 were artefacts (37 prose messages + 1
heading + 37 bare names — each disclosed gate counted TWICE, once per line
shape) and 2 were real; ``structural_fail_lines`` 39, of which 37 named gates
that never ran.

WHY THE UNIT SUITE WAS GREEN WHILE THIS SHIPPED
-----------------------------------------------
No test ever fed real producer output to a real parser. The composition of
``reasons`` lived inline in ``main()``, so every parser test had to hand-write
a fixture of what it BELIEVED the producer emitted — and none of them believed
in the disclosure block, because it did not exist when they were written. The
producer is now ``_compose_p0_reasons`` and the round trip is tested here.

BOTH REASON SHAPES ARE COVERED, deliberately. The umbrella emits the
``Failed gates (N):`` + indented-bullet shape only when >=2 gates fail, and the
audit writer's second scrape only runs when P0's status is FAIL. So the two
pollution channels do not both fire on the same run, and a fix validated
against one shape can leak on the other while looking complete.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

#: A gate name, as opposed to a sentence. Every entry of the audit artifact's
#: `failed_gates` must look like this — the invariant that both a prose
#: disclosure message and the disclosure heading violate.
_GATE_NAME_RE = re.compile(r"[A-Za-z_][\w.]*\Z")

_PROGRAMS = Path(__file__).resolve().parents[1]


def _load(name: str, filename: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(_PROGRAMS))
F = _load("_fcc_issue492_disclosure", "flow_compliance_check.py")
GI = _load("_gi_issue492_disclosure", "_gate_invocation.py")


# ───────────────────────── real umbrella output, once ────────────────────────

def _project_with_rtl(root: Path) -> Path:
    rtl = root / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "top.v").write_text(
        "module top (input wire clk, input wire rst_n, output reg [7:0] q);\n"
        "  always @(posedge clk or negedge rst_n) begin\n"
        "    if (!rst_n) q <= 8'd0;\n"
        "    else        q <= q + 8'd1;\n"
        "  end\n"
        "endmodule\n")
    return root


@pytest.fixture(scope="module")
def umbrella(tmp_path_factory):
    """Run the REAL P0 umbrella once. Every disclosure string used below is
    the callee's own error text as produced by a real subprocess dispatch —
    nothing about the disclosure's wording is invented by this test."""
    proj = _project_with_rtl(tmp_path_factory.mktemp("p0_umbrella"))
    passed, fails, skips, waivers = F._run_structural_rtl_gates(proj)
    not_invoked = [s for s in skips
                   if GI.NOT_INVOCABLE_SENTINEL in s]
    if not not_invoked:
        pytest.skip("no gate is currently un-invocable — nothing to disclose")
    return {
        "passed": passed, "fails": fails, "skips": skips, "waivers": waivers,
        "not_invoked": not_invoked,
        "not_invoked_names": {s.split(" ", 1)[0] for s in not_invoked},
        "fail_names": [f[len("FAIL: "):].split(" — ")[0] for f in fails],
    }


def _p0(reasons, status="FAIL"):
    return F.StepResult(id="P0", name="P0 umbrella", stage="stage1",
                        status=status, reasons=list(reasons), evidence=[])


def _disclosure_block(umbrella):
    """The disclosure exactly as the umbrella composes it into `reasons`."""
    return F._compose_p0_reasons([], umbrella["skips"], [])


# ══════════════════════ 1. the producer ↔ parser round trip ══════════════════
# The contract that had no test: whatever the producer writes, the parser must
# read back as EXACTLY the failing gates and nothing else.

@pytest.mark.parametrize("n_fails", [0, 1, 2, 4])
def test_roundtrip_parser_recovers_exactly_the_failing_gates(umbrella, n_fails):
    fails = [f"FAIL: gate_{i}_check — first line of gate output"
             for i in range(n_fails)]
    reasons = F._compose_p0_reasons(fails, umbrella["skips"],
                                    umbrella["waivers"])
    recovered = F._parse_p0_failing_subgates(
        _p0(reasons, "FAIL" if fails else "PASS"))
    assert recovered == [f"gate_{i}_check" for i in range(n_fails)]


def test_roundtrip_uses_both_shapes(umbrella):
    """Premise check: the two shapes really are different, so the
    parametrised round trip above is not testing one shape twice."""
    one = F._compose_p0_reasons(["FAIL: a_check — m"], umbrella["skips"], [])
    two = F._compose_p0_reasons(["FAIL: a_check — m", "FAIL: b_check — m"],
                                umbrella["skips"], [])
    assert not any(r.startswith("Failed gates") for r in one)
    assert any(r.startswith("Failed gates") for r in two)
    assert any(r.lstrip().startswith("- b_check") for r in two)


def test_the_disclosure_is_still_disclosed(umbrella):
    """The fix must suppress the MIS-READING, not the disclosure. Every
    never-invoked gate is still named in `reasons`, under its own heading,
    with the callee's own error text."""
    reasons = _disclosure_block(umbrella)
    heading = [r for r in reasons
               if r.startswith(GI.NOT_INVOCABLE_HEADING_SENTINEL)]
    assert len(heading) == 1
    assert str(len(umbrella["not_invoked"])) in heading[0]
    named = {r.lstrip("- ").split(" ", 1)[0] for r in reasons
             if GI.NOT_INVOCABLE_SENTINEL in r}
    assert named == umbrella["not_invoked_names"]


# ══════════════════ 2. consumer 1 — _parse_p0_failing_subgates ═══════════════

@pytest.mark.parametrize("status", ["PASS", "FAIL"])
def test_no_disclosure_line_is_read_as_a_failing_gate(umbrella, status):
    reasons = _disclosure_block(umbrella)
    assert F._parse_p0_failing_subgates(_p0(reasons, status)) == []


def test_heading_is_never_a_gate_name(umbrella):
    reasons = F._compose_p0_reasons(["FAIL: real_check — boom"],
                                    umbrella["skips"], [])
    names = F._parse_p0_failing_subgates(_p0(reasons))
    assert names == ["real_check"]
    assert not any(GI.NOT_INVOCABLE_HEADING_SENTINEL in n for n in names)
    assert not any(GI.NOT_INVOCABLE_SENTINEL in n for n in names)


# ══════════════ 3. consumer 2 — _normalise / _per_gate_from_p0_reasons ═══════
# This channel is the nastier one: it recovers the gate's REAL name, so its
# output is indistinguishable from a genuine verdict by inspection.

@pytest.mark.parametrize("n_fails", [0, 1, 2])
def test_no_never_invoked_gate_gets_a_per_gate_record(umbrella, n_fails):
    fails = [f"FAIL: gate_{i}_check — msg" for i in range(n_fails)]
    reasons = F._compose_p0_reasons(fails, umbrella["skips"], [])
    per_gate = F._per_gate_from_p0_reasons(reasons)
    assert [g["name"] for g in per_gate] == \
        [f"gate_{i}_check" for i in range(n_fails)]
    assert not (
        {g["name"] for g in per_gate} & umbrella["not_invoked_names"])


def test_normalise_drops_disclosure_lines_not_just_the_failed_gates_header(
        umbrella):
    for line in _disclosure_block(umbrella):
        if (GI.NOT_INVOCABLE_SENTINEL in line
                or line.startswith(GI.NOT_INVOCABLE_HEADING_SENTINEL)):
            assert F._normalise_p0_reason_line(line) == "", line[:80]


# ═════════════════ 4. the two all(...) predicates that flip ══════════════════

def test_informational_only_survives_the_disclosure(umbrella):
    """`_step_failure_is_informational_only` is an `all(...)` over the parser's
    output; 38 phantom names made it False and the step reached `failing`."""
    gates = sorted(F.INFORMATIONAL_GATES)[:2]
    fails = [f"FAIL: {g} — coverage signal, not a blocker" for g in gates]
    with_disclosure = F._compose_p0_reasons(fails, umbrella["skips"], [])
    without = F._compose_p0_reasons(fails, [], [])
    assert F._step_failure_is_informational_only(_p0(without)) is True
    assert F._step_failure_is_informational_only(_p0(with_disclosure)) is True


def test_thin_input_deferral_survives_the_disclosure(umbrella):
    """The PASS_WITH_OPEN_SOURCE_CONSTRAINTS promotion computes
    `all(g in _P0_THIN_INPUT_DEFERRABLE_SUBGATES for g in
    _parse_p0_failing_subgates(p0))`. Phantom names made it False, so a
    deferrable run FAILed instead of being deferred."""
    gates = sorted(F._P0_THIN_INPUT_DEFERRABLE_SUBGATES)[:2]
    fails = [f"FAIL: {g} — needs a commercial tool" for g in gates]
    reasons = F._compose_p0_reasons(fails, umbrella["skips"], [])
    subgates = F._parse_p0_failing_subgates(_p0(reasons))
    assert subgates == gates
    assert all(g in F._P0_THIN_INPUT_DEFERRABLE_SUBGATES for g in subgates)


def test_a_real_failure_still_blocks_both_predicates(umbrella):
    """Guard: the fix must not make everything tolerable. A genuine
    non-informational, non-deferrable failure still defeats both `all(...)`."""
    fails = [f"FAIL: {sorted(F.INFORMATIONAL_GATES)[0]} — soft",
             "FAIL: some_real_check — hard"]
    reasons = F._compose_p0_reasons(fails, umbrella["skips"], [])
    res = _p0(reasons)
    assert F._step_failure_is_informational_only(res) is False
    assert not all(g in F._P0_THIN_INPUT_DEFERRABLE_SUBGATES
                   for g in F._parse_p0_failing_subgates(res))


# ═════════ 5. the recogniser is anchored — a real failure is never lost ══════

def test_a_genuine_failure_mentioning_the_sentinel_is_still_a_failure(
        umbrella):
    """A substring test for "NOT INVOKED" would drop this real failure — the
    same false-clean bug in the opposite direction. The recogniser is anchored
    on the shape the formatter emits, so a gate whose own output happens to
    contain the phrase is unaffected."""
    fails = [f"FAIL: chatty_check — the DUT reports {GI.NOT_INVOCABLE_SENTINEL}"
             f" for 3 handlers",
             "FAIL: other_check — plain"]
    reasons = F._compose_p0_reasons(fails, umbrella["skips"], [])
    assert F._parse_p0_failing_subgates(_p0(reasons)) == \
        ["chatty_check", "other_check"]
    assert {g["name"] for g in F._per_gate_from_p0_reasons(reasons)} == \
        {"chatty_check", "other_check"}


def test_recogniser_covers_the_bullet_and_the_bare_payload():
    """The same predicate must work on the raw skip payload (how the umbrella
    filters) AND on the composed `  - ` bullet (how a consumer sees it)."""
    entry = GI.format_not_invocable_entry("some_check", "argparse said no")
    assert GI.is_not_invocable_entry(entry)
    assert GI.is_not_invocable_disclosure(f"  - {entry}")
    assert GI.is_not_invocable_disclosure(
        GI.format_not_invocable_heading(3, 241))
    assert not GI.is_not_invocable_disclosure("  - real_check — plain message")
    assert not GI.is_not_invocable_disclosure("SKIP: real_check")


# ══════════════════════ 6. passed_gate_count is a count ══════════════════════

def test_passed_gate_count_is_the_registry_partition(umbrella):
    """Every registered gate lands in exactly one of fail/skip/waiver/pass, so
    the four populations must sum to the registry size."""
    n = F._p0_passed_gate_count(umbrella["passed"], umbrella["fails"],
                                umbrella["skips"], umbrella["waivers"])
    assert n > 0
    assert (n + len(umbrella["fails"]) + len(umbrella["skips"])
            + len(umbrella["waivers"])) == len(F._STRUCTURAL_RTL_GATES)


def test_passed_gate_count_is_zero_when_no_gate_ran():
    assert F._p0_passed_gate_count(None, [], ["no RTL directory found"], []) == 0


# ════════════════ 7. END-TO-END through the real CLI entry point ═════════════
# The only shape that would actually have caught this: drive main(), read the
# artifact it writes. Deliberately written to depend on NOTHING added by the
# fix, so it fails on unmodified main with a real assertion rather than an
# ImportError.

def _run_main(project: Path, tmp_path: Path):
    report = tmp_path / "full.json"
    rc = F.main([str(project), "--phase", "2", "--strict-structural",
                 "--allow-thin-input", "--json", str(report)])
    audit = json.loads(
        (project / "reports" / "audit"
         / "phase23_completion_audit.json").read_text())
    full = json.loads(report.read_text())
    p0 = next((s for s in full["steps"] if s["id"] == "P0"), None)
    assert p0 is not None, "the P0 umbrella produced no step result"
    disclosed = {r.strip().lstrip("- ").split(" ", 1)[0]
                 for r in p0["reasons"]
                 if GI.NOT_INVOCABLE_SENTINEL in r}
    return rc, audit, p0, disclosed


def test_end_to_end_audit_artifact_reports_only_real_failures(tmp_path):
    """`reports/audit/phase23_completion_audit.json` is, by its own write-site
    comment, "the contract the mcp-eda pre-burn guard consumes". Every
    invariant below was violated by commit 7b7eebff3, first released in
    v1.7.69."""
    proj = _project_with_rtl(tmp_path / "proj")
    _rc, audit, _p0, disclosed = _run_main(proj, tmp_path)
    assert disclosed, "premise: this project discloses never-invoked gates"

    for name in audit["failed_gates"]:
        # Kills the prose messages AND the heading in one invariant, without
        # naming either — a gate name has no spaces.
        assert _GATE_NAME_RE.match(name), \
            f"failed_gates entry is not a gate name: {name!r}"
        assert name not in disclosed, \
            f"{name} never ran, yet it is reported as a failed gate"

    for rec in audit["gates"]:
        assert rec["name"] not in disclosed, \
            f"{rec['name']} never ran, yet it has a {rec['verdict']} record"

    for line in audit["structural_fail_lines"]:
        assert GI.NOT_INVOCABLE_SENTINEL not in line, \
            "a never-invoked gate is being counted as a structural failure — " \
            "this is what forces the verdict under --strict-structural"

    assert audit["failed_gate_count"] == len(audit["failed_gates"])
    assert audit["passed_gate_count"] > 0, (
        "gates ran and passed, but the audit reports zero passes")


def test_end_to_end_no_gate_is_counted_twice(tmp_path):
    """The two line shapes produced two entries per disclosed gate — a bare
    name from one scrape, the whole message from the other. Those two strings
    are DIFFERENT, so plain set-uniqueness never noticed; the duplicate is
    visible only in the leading token, which is the gate either way."""
    proj = _project_with_rtl(tmp_path / "proj")
    _rc, audit, _p0, _disclosed = _run_main(proj, tmp_path)
    leading = [n.split()[0] for n in audit["failed_gates"] if n.split()]
    dupes = sorted({t for t in leading if leading.count(t) > 1})
    assert not dupes, f"gate(s) reported more than once: {dupes}"
