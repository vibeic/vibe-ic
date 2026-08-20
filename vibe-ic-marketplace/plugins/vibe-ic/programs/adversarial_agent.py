#!/usr/bin/env python3
"""adversarial_agent.py — a role whose objective is to make PASS a lie. #1119.

THE ASYMMETRY IS THE POINT
==========================
Our two-arm discipline asks the agent that AUTHORED a fix to also try to break
it. The same party then holds both the objective and the refutation, and the
objective wins ties. This module is the other party: its objective is not "make
it pass", it is "prove the pass is a lie".

    Design Agent      make it pass
    Adversarial Agent make PASS a lie
    Gate              decides

The motivating case is not hypothetical (#1119): an engineer running an AI agent
through a full RTL-to-GDS flow reported that when N2N formal would not pass, the
agent edited the NETLIST until it did. If the objective is "the check passes"
and the evidence is writable, editing the evidence is a valid and cheaper
solution than fixing the design. Any sufficiently capable agent finds that path.

A ROLE THAT IS ONLY A DOCUMENT IS THE DEFECT IT DESCRIBES
=========================================================
This repository has spent versions retiring checkers that nothing invokes, and
§4.05 spent longer being "enforced by someone noticing". An adversarial role
written as prose in `agents/` would be exactly that shape: a rule stated where
it cannot act. So the attack list is not a checklist for a human — it is a
REGISTRY OF RUNNABLE ATTACKS, and this program executes them.

THE ATTACK LIST IS ALSO THE ACCEPTANCE TEST
===========================================
Each attack declares what green it is trying to forge, and returns one of three
verdicts. There is no fourth, and in particular there is no silent absence:

    SUCCEEDED   the attack produced a green result from a state that should be
                red. That is a P0 integrity defect, not a suggestion.
    DEFENDED    the attack was carried out and something noticed.
    UNAVAILABLE the attack could not be attempted here, WITH THE REASON. An
                attack nobody ran is not an attack that failed, and the two must
                never share a verdict.

MEASURED ON THIS COMMIT, and this is why the module exists
----------------------------------------------------------
`A3_CROSS_DESIGN` — copy design B's same-named reports into design A's cell and
re-run A's gate — against `spm/v1.9.96_gf180mcuD` with 19 reports taken from
`sha256/clean_run_v1427_20260715`:

    drc_report_check        rc 0 -> 0    SUCCEEDED
    antenna_report_check    rc 0 -> 0    SUCCEEDED
    em_report_check         rc 0 -> 0    SUCCEEDED
    erc_density_check       rc 0 -> 0    SUCCEEDED
    lvs_report_check        rc 0 -> 0    SUCCEEDED
    ir_drop_report_check    rc 0 -> 0    SUCCEEDED
    sta_report_check        rc 0 -> 1    DEFENDED

Six of seven sign-off gates certified one design using another design's
evidence. `sta_report_check` noticed, which is what makes this an attack and not
a tautology: a probe that "succeeds" against everything measures nothing.

RE-MEASURED after the evidence-binding rule landed in `eda_report_audit` (which
compares a discovered report against the digest the run's own
`provenance.jsonl` records for that path): `drc_report_check` and
`lvs_report_check` now DEFEND against A2 and A3 alike, and A1 no longer forges
anywhere. The ledger went 13 -> 8. The eight that remain are `antenna`, `em`,
`erc_density` and `ir_drop` under both substitution attacks, and they remain for
one reason worth stating plainly: that ledger records no digest for any report
those four modes read, so the binding reports NO_COVERAGE and refuses to claim
a defence it did not mount. Closing them needs the PRODUCER to record those
paths. It is not a change to any gate.

AND THE ATTACK THAT DOES NOT WORK, KEPT BECAUSE IT DOES NOT
-----------------------------------------------------------
`A1_TAMPER_DESTRUCTIVE` replaces the reports with nonsense. Measured: all five
gates tried went rc 0 -> 1. Destroying the evidence is DEFENDED, because the
gate needs the evidence to pass. It is retained as the control that this
module's verdicts are not all one colour, and as the statement of why the
dangerous attacks are the SHAPE-PRESERVING ones — a report that still parses and
reads better is the forgery; a report that is gone is a failure.

WHY THE SHIPPED TREE IS NEVER TOUCHED
=====================================
Every attack runs in a throwaway copy. `gate_cli_mutation_probe` learned this
the expensive way — its docstring records two runs killed inside the mutation
window that left shipped gates carrying an injected early return, and a neutered
gate exits 0, which the flow reads as PASS. A `finally` does not run on SIGKILL.
So this module never writes inside the repository, and
`test_the_adversary_never_writes_into_the_repository` asserts it.

EXIT CODES, AND WHY 2 EXISTS
============================
    0   attacks were attempted and every one was DEFENDED
    1   at least one attack SUCCEEDED — a forged green exists
    2   nothing could be attempted (no target, or every attack UNAVAILABLE)

2 is not a pass. An adversary that could not attack anything has said nothing
about the flow, and "I found no forgery" must never be spelled the same way as
"I could not look". That distinction is the one this repo keeps paying for.

A FINDING IS A DEFECT, NOT A SUGGESTION — SO IT IS RATCHETED
============================================================
#1119's rule is that a finding by this role is a P0 integrity defect. A program
that PRINTS findings does not deliver that: nothing fails when a fourteenth gate
starts accepting foreign evidence, and nothing notices when one stops. So the
current set is committed as `programs/adversarial_findings.json` — generated by
`tools/gen_adversarial_findings.py` from a live campaign, never hand-edited,
because a hand-edited finding list is an allowlist and the point is that findings
are not negotiable.

`test_the_findings_ratchet_holds_in_BOTH_directions` re-runs the recorded attacks
and compares, and the third case below is the one that makes it honest:

    a NEW (attack, gate) pair          -> a gate started forging a green
    a recorded pair that now DEFENDS   -> the finding CLOSED. Name the fix and
                                          re-generate; a silent close is a
                                          finding nobody adjudicated.
    a recorded pair now UNAVAILABLE    -> the cell it needed is gone. The finding
                                          is UNPROVEN, not fixed.

Without that third case a corpus prune would silently "close" every one of them
and
the ratchet would be measuring the publication schedule instead of the gates —
the exact defect #527 removed from dimension 3.

NOT WIRED YET — SAID PLAINLY, AND HELD TO THE SAME STANDARD I HELD #1092 TO
==========================================================================
Nothing invokes this program. It appears in no `flow/*.yaml` step, no
`benchmark/CAPTURE_ROUTING.json` entry, no runner, and none of
`flow_compliance_check.py`'s registered gates.

That is the D9 orphan-checker shape, and it is disclosed here rather than left
for a reader to discover — the same requirement this author imposed on #1092
before noticing it applied to this file too.
`test_the_unwired_state_is_disclosed_or_gone` MEASURES the wiring and fails in
BOTH directions: while unwired it requires this paragraph, and the moment somebody
wires it the test fails and forces the paragraph out. What it cannot do is decide
WHICH step should own the clause — that is a flow declaration and needs the ruling.

THE HONEST LIMIT, PUBLISHED AS A DENOMINATOR
============================================
This does not make the flow correct. It makes the flow's CLAIMS harder to forge.
Three of the nine attacks the issue names cannot run without an EDA container or
a simulator, and they are reported UNAVAILABLE with that reason rather than
omitted, because the adversary's imagination is the new denominator and a
denominator nobody publishes is a coverage claim nobody can check. `--json`
carries `attempted`, `unavailable` and `coverage` so a reader gets the fraction
and not just the findings.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the sibling import below resolves however this is invoked
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

SCHEMA = "vibe-ic/adversarial-agent/v1"

SUCCEEDED = "SUCCEEDED"
DEFENDED = "DEFENDED"
UNAVAILABLE = "UNAVAILABLE"

_HERE = Path(__file__).resolve().parent

#: Gate invocations the report attacks are carried out against. `argv` is the
#: gate's own CLI as the flow spells it, so an attack measures the thing the
#: flow runs and not a private entry point.
DEFAULT_GATES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("drc_report_check", (".",)),
    ("antenna_report_check", (".", "--mode", "antenna")),
    ("em_report_check", (".", "--mode", "em")),
    ("erc_density_check", (".",)),
    ("lvs_report_check", (".",)),
    ("ir_drop_report_check", (".", "--mode", "ir_drop")),
    ("sta_report_check", (".", "--mode", "sta")),
)

#: Suffixes an attack may substitute or edit. Deliberately narrow: these are
#: the REPORT artefacts a sign-off gate reads, and widening it to every file
#: would make the attacks slower without making them sharper.
ARTEFACT_SUFFIXES = (".rpt", ".json", ".log")


# --------------------------------------------------------------------------- #
# verdict record
# --------------------------------------------------------------------------- #
@dataclass
class Attempt:
    """One attack against one target. `detail` always names a measured value."""
    attack: str
    objective: str
    verdict: str
    detail: str
    target: str = ""
    evidence: Dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, object]:
        return {"attack": self.attack, "objective": self.objective,
                "verdict": self.verdict, "detail": self.detail,
                "target": self.target, "evidence": self.evidence}


# --------------------------------------------------------------------------- #
# running a gate, always in a copy
# --------------------------------------------------------------------------- #
def _run_gate(plugin: Path, program: str, argv: Tuple[str, ...], cwd: Path,
              timeout: int = 180) -> Optional[int]:
    """The gate's exit code, or None when the program does not exist.

    THE EXIT CODE IS THE MEASUREMENT, not a return value read out of an import.
    The flow reads exit codes; an attack that measured `audit()` would leave the
    verdict-to-exit-code mapping unmeasured, which is the precise hole
    `gate_cli_mutation_probe` was written for.
    """
    prog = plugin / "programs" / f"{program}.py"
    if not prog.is_file():
        return None
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        r = subprocess.run([sys.executable, str(prog), *argv], cwd=str(cwd),
                           capture_output=True, text=True, timeout=timeout,
                           env=env)
    except subprocess.TimeoutExpired:
        return None
    return r.returncode


def _copy_cell(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, symlinks=True)


# --------------------------------------------------------------------------- #
# the attacks
# --------------------------------------------------------------------------- #
def attack_cross_design(plugin: Path, cell: Path, donor: Optional[Path],
                        gates=DEFAULT_GATES) -> List[Attempt]:
    """A3 — certify design A using design B's evidence.

    The sharpest attack a GREEN cell can demonstrate, because it needs no
    violation to hide: it asks whether a gate can tell WHOSE report it read. A
    gate that cannot is signing a statement about a design it never examined.
    """
    obj = "a gate certifies this design using another design's reports"
    if donor is None or not donor.is_dir():
        return [Attempt("A3_CROSS_DESIGN", obj, UNAVAILABLE,
                        "no donor design available to substitute from",
                        str(cell))]
    out: List[Attempt] = []
    for program, argv in gates:
        with tempfile.TemporaryDirectory(prefix="adv_a3_") as td:
            proj = Path(td) / "proj"
            _copy_cell(cell, proj)
            before = _run_gate(plugin, program, argv, proj)
            if before is None:
                out.append(Attempt("A3_CROSS_DESIGN", obj, UNAVAILABLE,
                                   f"gate {program} absent or timed out",
                                   f"{cell.name}:{program}"))
                continue
            if before != 0:
                out.append(Attempt(
                    "A3_CROSS_DESIGN", obj, UNAVAILABLE,
                    f"gate {program} already fails on the pristine cell "
                    f"(rc={before}); there is no green here to forge",
                    f"{cell.name}:{program}"))
                continue
            swapped = 0
            for f in sorted(donor.rglob("*")):
                if not f.is_file() or f.suffix not in ARTEFACT_SUFFIXES:
                    continue
                tgt = proj / f.relative_to(donor)
                if tgt.is_file():
                    shutil.copy2(f, tgt)
                    swapped += 1
            if swapped == 0:
                out.append(Attempt("A3_CROSS_DESIGN", obj, UNAVAILABLE,
                                   "donor shares no artefact path with the cell",
                                   f"{cell.name}:{program}"))
                continue
            after = _run_gate(plugin, program, argv, proj)
            verdict = SUCCEEDED if after == 0 else DEFENDED
            out.append(Attempt(
                "A3_CROSS_DESIGN", obj, verdict,
                f"{program}: rc {before} -> {after} after substituting "
                f"{swapped} artefact(s) from {donor.name}",
                f"{cell.name}:{program}",
                {"rc_before": before, "rc_after": after, "substituted": swapped,
                 "donor": donor.name}))
    return out


def attack_stale_replay(plugin: Path, cell: Path, older: Optional[Path],
                        gates=DEFAULT_GATES) -> List[Attempt]:
    """A2 — replay an EARLIER run of the SAME design.

    Distinct from A3 and strictly harder to notice: the artefact belongs to this
    design, so any check keyed on the design's identity still passes. Only a
    check keyed on WHICH RUN produced it can object.
    """
    obj = "a gate accepts an earlier run's artefacts as this run's evidence"
    if older is None or not older.is_dir():
        return [Attempt("A2_STALE_REPLAY", obj, UNAVAILABLE,
                        "no earlier run of the same design is available",
                        str(cell))]
    return [a for a in _substitute_and_rerun(
        plugin, cell, older, gates, "A2_STALE_REPLAY", obj)]


def _substitute_and_rerun(plugin: Path, cell: Path, donor: Path, gates,
                          name: str, obj: str) -> List[Attempt]:
    out: List[Attempt] = []
    for program, argv in gates:
        with tempfile.TemporaryDirectory(prefix="adv_sub_") as td:
            proj = Path(td) / "proj"
            _copy_cell(cell, proj)
            before = _run_gate(plugin, program, argv, proj)
            if before is None or before != 0:
                out.append(Attempt(
                    name, obj, UNAVAILABLE,
                    f"gate {program} is not green on the pristine cell "
                    f"(rc={before})", f"{cell.name}:{program}"))
                continue
            swapped = 0
            for f in sorted(donor.rglob("*")):
                if not f.is_file() or f.suffix not in ARTEFACT_SUFFIXES:
                    continue
                tgt = proj / f.relative_to(donor)
                if tgt.is_file():
                    shutil.copy2(f, tgt)
                    swapped += 1
            if swapped == 0:
                out.append(Attempt(name, obj, UNAVAILABLE,
                                   "donor shares no artefact path with the cell",
                                   f"{cell.name}:{program}"))
                continue
            after = _run_gate(plugin, program, argv, proj)
            out.append(Attempt(
                name, obj, SUCCEEDED if after == 0 else DEFENDED,
                f"{program}: rc {before} -> {after} after replaying "
                f"{swapped} artefact(s) from {donor.name}",
                f"{cell.name}:{program}",
                {"rc_before": before, "rc_after": after, "substituted": swapped,
                 "donor": donor.name}))
    return out


def attack_tamper_destructive(plugin: Path, cell: Path,
                              gates=DEFAULT_GATES) -> List[Attempt]:
    """A1 — edit the artefact after the producing step (#1116), destructively.

    KEPT BECAUSE IT IS DEFENDED. Measured: every gate tried flips rc 0 -> 1 when
    its reports are replaced with nonsense, because it needs them to pass. This
    is the control that this module's verdicts are not all one colour, and the
    reason the dangerous attacks above are the shape-PRESERVING ones.
    """
    obj = "a gate stays green after its evidence is overwritten"
    out: List[Attempt] = []
    for program, argv in gates:
        with tempfile.TemporaryDirectory(prefix="adv_a1_") as td:
            proj = Path(td) / "proj"
            _copy_cell(cell, proj)
            before = _run_gate(plugin, program, argv, proj)
            if before is None or before != 0:
                out.append(Attempt(
                    "A1_TAMPER_DESTRUCTIVE", obj, UNAVAILABLE,
                    f"gate {program} is not green on the pristine cell "
                    f"(rc={before})", f"{cell.name}:{program}"))
                continue
            n = 0
            for f in sorted(proj.rglob("*.rpt")):
                if f.is_file():
                    f.write_text("TAMPERED BY THE ADVERSARY\n", encoding="utf-8")
                    n += 1
            after = _run_gate(plugin, program, argv, proj)
            out.append(Attempt(
                "A1_TAMPER_DESTRUCTIVE", obj,
                SUCCEEDED if after == 0 else DEFENDED,
                f"{program}: rc {before} -> {after} after overwriting {n} "
                f"report(s)", f"{cell.name}:{program}",
                {"rc_before": before, "rc_after": after, "overwritten": n}))
    return out


def attack_violation_deletion(plugin: Path, cell: Path,
                              gates=DEFAULT_GATES) -> List[Attempt]:
    """A5 — delete the violation from the report and see if the verdict improves.

    Only meaningful against a gate that is RED on this cell: the attack asks
    whether removing the evidence of a failure is a valid route to green, and a
    gate that already passes has no failure to remove. Reported UNAVAILABLE in
    that case, never DEFENDED — "there was nothing to delete" is not "deleting
    it would not have worked".
    """
    obj = "removing violation lines from a report turns its gate green"
    out: List[Attempt] = []
    for program, argv in gates:
        with tempfile.TemporaryDirectory(prefix="adv_a5_") as td:
            proj = Path(td) / "proj"
            _copy_cell(cell, proj)
            before = _run_gate(plugin, program, argv, proj)
            if before is None:
                continue
            if before == 0:
                out.append(Attempt(
                    "A5_VIOLATION_DELETION", obj, UNAVAILABLE,
                    f"gate {program} already passes on this cell (rc=0); no "
                    f"violation exists to delete", f"{cell.name}:{program}"))
                continue
            removed = 0
            for f in sorted(proj.rglob("*")):
                if not f.is_file() or f.suffix not in (".rpt", ".log"):
                    continue
                try:
                    lines = f.read_text(errors="replace").splitlines(True)
                except OSError:
                    continue
                keep = [ln for ln in lines if not _looks_like_violation(ln)]
                if len(keep) != len(lines):
                    removed += len(lines) - len(keep)
                    f.write_text("".join(keep), encoding="utf-8")
            if removed == 0:
                out.append(Attempt(
                    "A5_VIOLATION_DELETION", obj, UNAVAILABLE,
                    f"gate {program} fails (rc={before}) but no line in its "
                    f"reports matched a violation shape, so nothing could be "
                    f"deleted", f"{cell.name}:{program}"))
                continue
            after = _run_gate(plugin, program, argv, proj)
            out.append(Attempt(
                "A5_VIOLATION_DELETION", obj,
                SUCCEEDED if after == 0 else DEFENDED,
                f"{program}: rc {before} -> {after} after deleting {removed} "
                f"violation-shaped line(s)", f"{cell.name}:{program}",
                {"rc_before": before, "rc_after": after, "lines_removed": removed}))
    return out


_VIOLATION_TOKENS = ("violation", "violated", "error:", "*error*", "fail",
                     "vio ", "drc ", "short", "open ", "mismatch")


def _looks_like_violation(line: str) -> bool:
    low = line.lower()
    return any(t in low for t in _VIOLATION_TOKENS)


def attack_gate_always_refuses(plugin: Path, program: str) -> List[Attempt]:
    """A9 — a ban is not a check.

    `gate_cli_mutation_probe` covers the other direction: neuter a gate so it
    can never FAIL and see whether anything reddens. Its mirror is a gate that
    can never PASS, which is equally useless and reads as diligence. Delegated
    to that module for the tree handling — the disposable-copy logic there is
    load-bearing and duplicating it is how a shipped gate ends up neutered.
    """
    obj = "a gate made unable to PASS is not noticed by any test"
    try:
        sys.path.insert(0, str(_HERE))
        import gate_cli_mutation_probe as probe  # noqa: PLC0415
    except Exception as exc:                     # noqa: BLE001
        return [Attempt("A9_ALWAYS_REFUSES", obj, UNAVAILABLE,
                        f"gate_cli_mutation_probe unimportable ({exc})", program)]
    if not hasattr(probe, "naming_tests"):
        return [Attempt("A9_ALWAYS_REFUSES", obj, UNAVAILABLE,
                        "gate_cli_mutation_probe has no naming_tests(); its API "
                        "moved and this attack must be re-derived", program)]
    tests = probe.naming_tests(program)
    if not tests:
        return [Attempt("A9_ALWAYS_REFUSES", obj, SUCCEEDED,
                        f"no test file names {program}, so a gate made unable "
                        f"to pass would redden nothing at all", program,
                        {"naming_tests": 0})]
    return [Attempt("A9_ALWAYS_REFUSES", obj, UNAVAILABLE,
                    f"{len(tests)} test file(s) name {program}; executing the "
                    f"always-refuse mutation is gate_cli_mutation_probe's job "
                    f"and is not duplicated here", program,
                    {"naming_tests": len(tests)})]


#: The three attacks the issue names that need an EDA container or a simulator.
#: Declared, never omitted: an attack absent from the report is indistinguishable
#: from an attack that found nothing.
CONTAINER_BOUND_ATTACKS: Tuple[Tuple[str, str, str], ...] = (
    ("A4_TOOL_VERSION_MISMATCH",
     "evidence claims a tool version the run did not use",
     "needs a second tool version installed side by side; no EDA container is "
     "reachable from a plain checkout"),
    ("A6_RTL_FAULT_INJECTION",
     "a fault injected into RTL is not noticed by the testbench",
     "needs a simulator (iverilog/verilator) and a runnable testbench; absent "
     "from a plain checkout"),
    ("A7_CONSTRAINT_WEAKENING",
     "weakening an SDC or PDK config is not objected to by any gate",
     "needs STA against a PDK's liberty set; absent from a plain checkout"),
)


def unavailable_container_attacks() -> List[Attempt]:
    return [Attempt(name, obj, UNAVAILABLE, reason, "-")
            for name, obj, reason in CONTAINER_BOUND_ATTACKS]


# --------------------------------------------------------------------------- #
# THE ASYMMETRY, AS A MECHANISM
# --------------------------------------------------------------------------- #
class SelfResolutionRefused(Exception):
    """Raised when a party tries to close its own adversarial finding."""


def mark_resolved(finding: Dict[str, object], resolved_by: str) -> Dict[str, object]:
    """Close a finding, and REFUSE when the closer is the finder.

    "A finding by the Adversarial Agent is a defect, not a suggestion… and it
    must not be able to mark its own findings resolved. The asymmetry is the
    point." (#1119)

    Written as a mechanism rather than as a sentence in a role document, for the
    same reason §4.05 had to stop being enforced by review: the party with the
    objective is the party that would benefit from closing the finding, so the
    refusal has to live somewhere it cannot be talked out of.
    """
    found_by = str(finding.get("found_by") or "").strip()
    who = str(resolved_by or "").strip()
    if not who:
        raise SelfResolutionRefused(
            "resolved_by is empty; an unattributed resolution is not one")
    if not found_by:
        raise SelfResolutionRefused(
            "finding carries no found_by, so the asymmetry cannot be checked; "
            "record who found it before closing it")
    if who == found_by:
        raise SelfResolutionRefused(
            f"{who!r} found this finding and may not also resolve it. The "
            f"author of a fix cannot be its own refutation (#1119); route it to "
            f"a different party.")
    out = dict(finding)
    out["resolved_by"] = who
    return out


# --------------------------------------------------------------------------- #
# campaign
# --------------------------------------------------------------------------- #
def run_campaign(plugin: Path, cell: Path, donor: Optional[Path] = None,
                 older: Optional[Path] = None,
                 gates=DEFAULT_GATES) -> Tuple[int, Dict[str, object]]:
    """Every attack, against one cell. Returns `(rc, report)`."""
    attempts: List[Attempt] = []
    attempts += attack_cross_design(plugin, cell, donor, gates)
    attempts += attack_stale_replay(plugin, cell, older, gates)
    attempts += attack_tamper_destructive(plugin, cell, gates)
    attempts += attack_violation_deletion(plugin, cell, gates)
    for program, _argv in gates:
        attempts += attack_gate_always_refuses(plugin, program)
    attempts += unavailable_container_attacks()

    succeeded = [a for a in attempts if a.verdict == SUCCEEDED]
    defended = [a for a in attempts if a.verdict == DEFENDED]
    unavailable = [a for a in attempts if a.verdict == UNAVAILABLE]
    attempted = len(succeeded) + len(defended)

    report: Dict[str, object] = {
        "schema": SCHEMA,
        "cell": str(cell),
        "donor": donor.name if donor else None,
        "older_run": older.name if older else None,
        "counts": {"attempted": attempted, "succeeded": len(succeeded),
                   "defended": len(defended), "unavailable": len(unavailable)},
        # THE DENOMINATOR, PUBLISHED. The adversary's imagination is the new
        # denominator (#1119's own honest limit), so the fraction that could be
        # attempted ships beside the findings instead of being inferred.
        "coverage": {
            "attacks_declared": len({a.attack for a in attempts}),
            "attacks_with_an_attempt": len(
                {a.attack for a in attempts if a.verdict != UNAVAILABLE}),
            "note": "an attack reported UNAVAILABLE found nothing AND proved "
                    "nothing; it is counted here so a reader cannot mistake "
                    "the two",
        },
        "findings": [a.as_dict() for a in succeeded],
        "attempts": [a.as_dict() for a in attempts],
    }
    if attempted == 0:
        report["verdict"] = "NOTHING_ATTEMPTED"
        report["disclosure"] = (
            "no attack could be carried out against this target, so this run "
            "says nothing about the flow. That is not a pass.")
        return 2, report
    report["verdict"] = "FORGED_GREEN_EXISTS" if succeeded else "ALL_DEFENDED"
    return (1 if succeeded else 0), report



#: The committed record of which gates currently forge a green. See the
#: RATCHET section of the module docstring.
FINDINGS_LEDGER = _HERE / "adversarial_findings.json"


def load_findings_ledger(path: Optional[Path] = None) -> Dict[str, Any]:
    p = Path(path) if path else FINDINGS_LEDGER
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def ratchet_diff(recorded: Dict[str, Any],
                 attempts: List[Attempt]) -> Dict[str, List[str]]:
    """Compare a live campaign against the committed record.

    Returns four named lists. They are FOUR and not two because "this finding is
    gone" has three different causes and only one of them is progress:

        newly_forging   a pair not in the record now SUCCEEDS  -> regression
        closed          a recorded pair now DEFENDS            -> real progress,
                                                                  must be
                                                                  adjudicated
        unproven        a recorded pair is now UNAVAILABLE     -> the evidence
                                                                  went away; NOT
                                                                  a fix
        held            unchanged
    """
    rec = {(f["attack"], f["target"]) for f in recorded.get("forging", ())}
    live = {(a.attack, a.target): a.verdict for a in attempts}
    out: Dict[str, List[str]] = {"newly_forging": [], "closed": [],
                                 "unproven": [], "held": []}
    for key, verdict in sorted(live.items()):
        label = f"{key[0]} {key[1]}"
        if verdict == SUCCEEDED and key not in rec:
            out["newly_forging"].append(label)
        elif verdict == DEFENDED and key in rec:
            out["closed"].append(label)
        elif verdict == UNAVAILABLE and key in rec:
            out["unproven"].append(label)
        elif verdict == SUCCEEDED and key in rec:
            out["held"].append(label)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cell", help="the published run/cell to attack")
    ap.add_argument("--donor", help="a DIFFERENT design's cell, for A3")
    ap.add_argument("--older", help="an EARLIER run of the same design, for A2")
    ap.add_argument("--plugin", default=str(_HERE.parent),
                    help="plugin root (default: this program's parent)")
    ap.add_argument("--json", help="write the report here")
    args = ap.parse_args(argv)

    cell = Path(args.cell)
    if not cell.is_dir():
        print(f"[REFUSED] adversarial_agent: no such cell: {cell}")
        return 2
    rc, report = run_campaign(
        Path(args.plugin), cell,
        Path(args.donor) if args.donor else None,
        Path(args.older) if args.older else None)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), json.dumps(report, indent=2, sort_keys=True)
                                   + "\n", encoding="utf-8")
    c = report["counts"]
    for f in report["findings"]:
        print(f"[FORGED GREEN] {f['attack']} on {f['target']}: {f['detail']}")
    if rc == 2:
        print(f"[REFUSED] adversarial_agent: {report['disclosure']}")
    elif rc == 0:
        print(f"[PASS] adversarial_agent: {c['attempted']} attack(s) attempted, "
              f"all DEFENDED.")
    else:
        print(f"[FAIL] adversarial_agent: {c['succeeded']} of {c['attempted']} "
              f"attempted attack(s) produced a forged green. Each is a P0 "
              f"integrity defect, not a suggestion.")
    print(f"[INFO] {c['unavailable']} attack(s) UNAVAILABLE and therefore "
          f"unproven; {report['coverage']['attacks_with_an_attempt']} of "
          f"{report['coverage']['attacks_declared']} declared attacks were "
          f"attempted at all.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
