"""vibe-ic#901 — a gate that declares it examined nothing is not a plain PASS.

THE DEFECT, reproduced end to end
---------------------------------
`vacuous_testbench_check` run against a tree with no simulation in it prints
and writes::

    {"gate": "vacuous_testbench", "verdict": "NOT_APPLICABLE",
     "reason": "no sim tree (step did not run)"}

and exits 0. `flow_compliance_check` recognised exactly two vacuity channels —
exit code 2, and a `VACUOUS_PASS:` token at the start of a line inside a
fixed-width tail of stdout — so the gate's own structured verdict reached no
consumer, the step reported `PASS`, the gate ledger row read `rc=0 PASS`, and
the run exited 0. The gate against vacuous passes was itself consumed as a
substantive pass.

WHY THE OBVIOUS FIX HAD TO WAIT FOR A COUNT
-------------------------------------------
Reading the gate's own `--json` report was tried alone (v1.10.14) and withdrawn
(v1.10.18): it turned a converged run red. The tier branch was
``passed and vacuous_hints and not non_hint_reasons``, and a sub-gate that
passes SUBSTANTIVELY appends nothing at all — so silence and vacuity were
indistinguishable and one inapplicable clause beside five substantive ones read
as "every executed sub-gate was vacuously satisfied". More disclosure therefore
produced more FALSE unanimity, cascading into PASS_VOIDED_BY_DEPENDENCY and an
overall FAIL that enumerated no failed gate.

So every gate clause that RUNS now says so, and the tier COMPARES the two
counts. `test_a_step_whose_other_clause_measured_the_design_stays_pass` is that
regression, pinned: it must give the same answer before and after this change.

Chip-AGNOSTIC: an empty tree and synthetic gate programs that do nothing but
write a verdict; no design, PDK, foundry or process appears anywhere.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import flow_compliance_check as F  # noqa: E402

FCC = PROGRAMS / "flow_compliance_check.py"
FLOW_YAML = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

#: <= 60s. `ci_harness_timeout_ceiling_check` derives a 60s per-call ceiling
#: from the 180s harness bound; an inner timeout above it can only fire after
#: the session has already been killed. Measured worst case for one audit over
#: these fixtures is ~2s.
_CALL_TIMEOUT = 55


# ────────────────────────────── fixtures ──────────────────────────────────
_SYNTH = '''#!/usr/bin/env python3
"""Synthetic gate. Writes ONE verdict into the --json report it was handed and
exits with the given code. It prints only a bare status line, which is the
prose channel the consumer deliberately cannot read."""
import json, sys
from pathlib import Path

VERDICT, RC, NAME = {verdict!r}, {rc!r}, {name!r}
argv = sys.argv[1:]
out = None
for i, a in enumerate(argv):
    if a == "--json" and i + 1 < len(argv):
        out = argv[i + 1]
if out:
    p = Path(out)
    if not p.is_absolute():
        p = Path.cwd() / p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({{"gate": NAME, "verdict": VERDICT}}, indent=1))
print("[%s] %s" % ("PASS" if RC == 0 else "FAIL", NAME))
sys.exit(RC)
'''


def _synth_gate(tmp_path: Path, name: str, verdict: str, rc: int = 0) -> Path:
    """A gate program on disk. Named by ABSOLUTE path in the flow, which
    `_resolve_program_cmd` honours (`PROGRAMS_DIR / '/abs/x.py'` is
    `/abs/x.py`), so nothing is written into the shipped programs tree."""
    p = tmp_path / "synthetic_gates" / f"{name}.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_SYNTH.format(verdict=verdict, rc=rc, name=name))
    return p


def _flow(tmp_path: Path, gate_block: str, tag: str = "flow") -> Path:
    """A one-step flow whose single step carries `gate_block` verbatim."""
    path = tmp_path / f"{tag}.yaml"
    path.write_text(
        "version: 2\n"
        "flow_name: i901_one_step\n"
        "total_steps: 1\n"
        "analog_steps: 0\n"
        "stages:\n"
        "  - id: stage1\n"
        "    name: \"the stage under audit\"\n"
        "    steps: [1]\n"
        "steps:\n"
        "  - id: 1\n"
        "    name: \"the step under audit\"\n"
        "    stage: stage1\n"
        "    gate:\n"
        "      all_of:\n"
        + gate_block
    )
    return path


def _audit(project: Path, flow_def: Path):
    """Drive the REAL entry point and read the REAL report. Never a local
    re-derivation of the rule: rc, stdout and the `--json` document only."""
    project.mkdir(parents=True, exist_ok=True)
    report = project / "i901_audit_report.json"
    r = subprocess.run(
        [sys.executable, str(FCC), ".", "--flow-def", str(flow_def),
         "--json", str(report)],
        cwd=project, capture_output=True, text=True, timeout=_CALL_TIMEOUT)
    doc = json.loads(report.read_text())
    return r.returncode, (r.stdout or "") + (r.stderr or ""), doc


def _step_under_audit(doc) -> dict:
    for s in doc.get("steps", []):
        if str(s.get("id")) == "1":
            return s
    raise AssertionError(f"the step under audit is absent from {doc!r}")


# ───────────── the defect, through the SHIPPED gate, end to end ───────────
def test_a_gate_that_declares_not_applicable_in_its_own_report_is_not_a_pass(
        tmp_path):
    """`vacuous_testbench_check` over a tree with no simulation in it.

    It writes `{"verdict": "NOT_APPLICABLE"}` into the report the flow's own
    command string names, and exits 0. Before #901 the step read PASS.
    """
    project = tmp_path / "empty_tree"
    flow = _flow(tmp_path, '        - program_exit_zero: "vacuous_testbench_check'
                           ' . --json reports/gates/vacuous_testbench.json"\n')
    rc, out, doc = _audit(project, flow)

    # the gate really did disclose, in the report the clause named
    declared = json.loads(
        (project / "reports/gates/vacuous_testbench.json").read_text())
    assert declared["verdict"].upper() in F._VACUOUS_JSON_VERDICTS, declared

    step = _step_under_audit(doc)
    assert step["status"] == "VACUOUS_PASS", (
        f"a gate that declared {declared['verdict']} in its own report was "
        f"consumed as {step['status']}\n{out}")


def test_the_gate_ledger_row_repeats_what_the_gate_said_about_itself(tmp_path):
    """The per-GATE row is a verdict surface too, and it said PASS."""
    project = tmp_path / "empty_tree"
    flow = _flow(tmp_path, '        - program_exit_zero: "vacuous_testbench_check'
                           ' . --json reports/gates/vacuous_testbench.json"\n')
    _rc, out, _doc = _audit(project, flow)
    row = re.search(r"GATE_RAN\s+vacuous_testbench_check\s+rc=0\s+(\S+)", out)
    assert row, out
    assert row.group(1) == "VACUOUS_PASS", (
        f"the ledger row reads {row.group(1)} for a gate whose own report "
        f"says it examined nothing\n{out}")


def test_the_optional_slot_reads_the_same_disclosure(tmp_path):
    """A disclosure only counts if the consumer reads it in BOTH slots — the
    same programs are wired through each, and a gate that discloses through an
    optional slot and is credited through a required one is the drift this
    convention exists to prevent."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "condition_marker.txt").write_text("present\n")
    gate = _synth_gate(tmp_path, "declares_nothing_examined", "NOT_APPLICABLE")
    flow = _flow(
        tmp_path,
        "        - optional_program_exit_zero:\n"
        f"            command: \"{gate} . --json reports/g.json\"\n"
        "            condition_files_exist: [\"condition_marker.txt\"]\n")
    _rc, out, doc = _audit(project, flow)
    assert _step_under_audit(doc)["status"] == "VACUOUS_PASS", out


# ───────────────────────── the disclosure survives ────────────────────────
def test_a_partially_vacuous_step_still_names_the_clause_that_examined_nothing(
        tmp_path):
    """The tier is one word per STEP and a partially vacuous step has no such
    word. Whichever tier resolves, the clause that examined nothing must still
    be named — dropping it for not having been unanimous would trade one
    silent pass for another."""
    project = tmp_path / "proj"
    na = _synth_gate(tmp_path, "declares_nothing_examined", "NOT_APPLICABLE")
    ok = _synth_gate(tmp_path, "declares_it_examined_the_unit", "PASS")
    flow = _flow(
        tmp_path,
        f'        - program_exit_zero: "{na} . --json reports/na.json"\n'
        f'        - program_exit_zero: "{ok} . --json reports/ok.json"\n')
    _rc, out, doc = _audit(project, flow)
    step = _step_under_audit(doc)
    assert step.get("partial_vacuity_disclosed") is True, step
    assert any("PARTIALLY-VACUOUS" in r and "declares_nothing_examined" in r
               for r in step["reasons"]), step["reasons"]
    assert "PARTIALLY-VACUOUS" in out, out


# ──────────────────── the population is not empty (meta) ──────────────────
def _declared_blocking_program_clauses() -> list:
    """DISCOVERED from the flow definition, which is the source of truth for
    what is wired — never a list typed here, which is how a seventh gate went
    unnoticed while six were being counted."""
    doc = yaml.safe_load(FLOW_YAML.read_text())
    found: list = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        spec = node.get("program_exit_zero")
        if isinstance(spec, dict):
            spec = spec.get("command")
        if isinstance(spec, str) and spec.strip():
            found.append(spec.strip())
        for key in ("all_of", "any_of"):
            sub = node.get(key)
            if isinstance(sub, (list, dict)):
                walk(sub)

    for step in doc.get("steps", []) or []:
        walk(step.get("gate") or {})
    seen, uniq = set(), []
    for c in found:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def test_every_declared_gate_that_reports_vacuity_reaches_the_step_tier():
    """The sweep #901 asks for, as a property rather than a list.

    Every blocking `program_exit_zero` clause the flow declares is run against
    an EMPTY project through the production evaluator. For each that exits 0,
    its own report is opened HERE — raw `json.load`, not the consumer's
    classifier — and if that report declares a verdict meaning "I examined
    nothing", the evaluator must have emitted the vacuity hint the step tier
    reads. It covers gates written later, which patching today's emitters
    would not.
    """
    os.environ[F._pl.GATE_TIMEOUT_ENV] = "55"
    clauses = _declared_blocking_program_clauses()
    assert len(clauses) >= 40, (
        f"only {len(clauses)} blocking gate clauses discovered — the flow "
        f"walk stopped seeing the population it is supposed to sweep")

    disclosing, undisclosed = [], []
    for cmd in clauses:
        with tempfile.TemporaryDirectory(prefix="i901_empty_") as td:
            project = Path(td)
            passed, reasons = F._evaluate_gate(project,
                                               {"program_exit_zero": cmd})
            if not passed:
                continue
            m = re.search(r"--json[= ]+(\S+)", cmd)
            if not m:
                continue
            report = Path(m.group(1).strip("'\""))
            if not report.is_absolute():
                report = project / report
            try:
                declared = json.loads(report.read_text(errors="replace"))
            except (OSError, ValueError):
                continue
            if not isinstance(declared, dict):
                continue
            words = {str(declared.get(k, "")).strip().upper()
                     for k in ("verdict", "status")}
            if not (words & F._VACUOUS_JSON_VERDICTS):
                continue
            seen_by_tier = any(r.startswith(F._VACUOUS_HINT_PREFIX)
                               for r in reasons)
            (disclosing if seen_by_tier else undisclosed).append(cmd)

    assert not undisclosed, (
        "these gates exited 0 on an empty project, declared in their own "
        "report that they examined nothing, and the step tier never saw it:\n"
        + "\n".join(f"  {c}" for c in undisclosed))
    # A sweep over an EMPTY population is itself the defect being removed.
    assert len(disclosing) >= 5, (
        f"only {len(disclosing)} gate(s) exercised this route — the sweep is "
        f"passing because it found nothing to judge, not because the "
        f"consumer reads the channel")


# ══════════════════════════════ THE GUARDS ════════════════════════════════
# Everything below must give the SAME answer with and without this change. A
# later fix that satisfies the tests above by making the tier fire more widely
# breaks these, which is the whole point of them.

def test_a_step_whose_other_clause_measured_the_design_stays_pass(tmp_path):
    """THE WITHDRAWN FIX, PINNED. One inapplicable clause beside one that
    measured the unit is not "every executed sub-gate was vacuously
    satisfied". v1.10.14 called it that and cascaded a converged run into an
    overall FAIL with `failed_gate_count: 0`."""
    project = tmp_path / "proj"
    na = _synth_gate(tmp_path, "declares_nothing_examined", "NOT_APPLICABLE")
    ok = _synth_gate(tmp_path, "declares_it_examined_the_unit", "PASS")
    flow = _flow(
        tmp_path,
        f'        - program_exit_zero: "{na} . --json reports/na.json"\n'
        f'        - program_exit_zero: "{ok} . --json reports/ok.json"\n')
    rc, out, doc = _audit(project, flow)
    assert _step_under_audit(doc)["status"] == "PASS", out
    assert rc == 0, out


def test_a_step_whose_every_clause_measured_the_design_is_untouched(tmp_path):
    """The polarity control. A consumer that answered "vacuous" to everything
    would satisfy every test above this line and convert every real pass into
    a disclosure — a worse defect than the one being fixed."""
    project = tmp_path / "proj"
    a = _synth_gate(tmp_path, "examined_the_unit_one", "PASS")
    b = _synth_gate(tmp_path, "examined_the_unit_two", "PASS")
    flow = _flow(
        tmp_path,
        f'        - program_exit_zero: "{a} . --json reports/a.json"\n'
        f'        - program_exit_zero: "{b} . --json reports/b.json"\n')
    rc, out, doc = _audit(project, flow)
    step = _step_under_audit(doc)
    assert step["status"] == "PASS", out
    assert step.get("partial_vacuity_disclosed", False) is False, step
    assert rc == 0, out


def test_a_real_finding_is_never_silenced_by_a_vacuous_sibling(tmp_path):
    """FAIL beats VACUOUS. A gate cannot both have found a violation and have
    examined nothing, and surfacing the violation is the only safe direction —
    silencing a real finding behind a skip is the failure mode the whole
    convention exists to prevent."""
    project = tmp_path / "proj"
    na = _synth_gate(tmp_path, "declares_nothing_examined", "NOT_APPLICABLE")
    bad = _synth_gate(tmp_path, "found_a_violation", "FAIL", rc=1)
    flow = _flow(
        tmp_path,
        f'        - program_exit_zero: "{na} . --json reports/na.json"\n'
        f'        - program_exit_zero: "{bad} . --json reports/bad.json"\n')
    rc, out, doc = _audit(project, flow)
    assert _step_under_audit(doc)["status"] == "FAIL", out
    assert rc == 1, out


@pytest.mark.parametrize("verdict", ["PASS", "FAIL", "PASS_WITH_WAIVERS"])
def test_a_substantive_verdict_is_never_read_as_vacuous(tmp_path, verdict):
    """The channel's polarity, at the tier rather than at the helper."""
    project = tmp_path / "proj"
    rc_for = {"PASS": 0, "FAIL": 1, "PASS_WITH_WAIVERS": 0}[verdict]
    g = _synth_gate(tmp_path, "examined_the_unit", verdict, rc=rc_for)
    flow = _flow(tmp_path,
                 f'        - program_exit_zero: "{g} . --json reports/g.json"\n')
    _rc, out, doc = _audit(project, flow)
    assert _step_under_audit(doc)["status"] != "VACUOUS_PASS", out
