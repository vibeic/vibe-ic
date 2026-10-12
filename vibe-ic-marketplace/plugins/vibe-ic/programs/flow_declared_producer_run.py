#!/usr/bin/env python3
"""flow_declared_producer_run.py — run the producers the FLOW already declares,
so the RUN writes the documents it is supposed to write.

ENFORCEMENT: reporting (the step gates keep their own verdicts)
CHIP_AGNOSTIC: strict

WHY THIS EXISTS, MEASURED 2026-09-15 (lane icsub2) on `subservient` x
gf180mcuD, and the same tier is what `spm` is held on::

    step 26  MISSING
      SELF-CERTIFIED EVIDENCE EXCLUDED (audit_created)
        ['reports/phase3/antenna_signoff.json']
        absent when this audit began []
        recorded by an earlier pass of this audit as its own write
        ['reports/phase3/antenna_signoff.json']
      ... PRODUCER GAP: no pre-audit producer supplied these paths; wire them
      into the owning runner before claiming this step complete.

The audit prints that remedy on ELEVEN steps. It is right, and for a
well-defined subset the flow has ALREADY NAMED the producer: the step lists a
program under `programs:`, its own gate clause invokes that same program with
`--json <path>`, and `<path>` is one of the step's `required_outputs`. The flow
says, in three places at once, that THE RUN produces that document. Nothing in
the run ran it, the AUDITOR's evaluation of the gate did, and the audit then
correctly refused its own output as evidence.

MEASURED over the shipped flow, that subset is exactly 13 clauses on 13 steps::

    2       crosslayer_rewrite_equivalence_check, rtl_hygiene_lint, rom_init_lint
    8       sdc_syntax_check           11      bsdl_emit
    15.5ic  pad_assignment_gen         26      antenna_report_check
    28      perc_signoff_check         29      post_layout_sim_check
    31      erc_density_check          36      tapeout_signoff_check
    38      foundry_handoff_package_check      M1  mixed_signal_merge_check

THIS IS NOT THE AUDITOR RUNNING ITS OWN GATES. The distinction is the whole
point of the tier being closed: a RUN executing the producers the flow lists
under its steps' `programs:` is what a flow does; an AUDITOR executing them and
then grading its own output is self-certification. So this program is invoked
by the RUNNER and refuses to run at all if it is handed the auditor's role --
there is no `--from-audit` mode, and `flow_compliance_check` does not import it.

IT ONLY FILLS A GAP; IT NEVER OVERWRITES THE RUN'S OWN WORK. A clause is
executed only when its target is ABSENT, or when the audit's own authorship
note claims the file -- i.e. the only thing that has ever written that path is
the auditor. A document the run produced is left exactly as the run left it.

A NON-ZERO rc IS RECORDED, NEVER SWALLOWED. A clause completes only after a
successful execution leaves its nonempty producer-authored document. Failed
execution or missing/wrong-owner evidence is INCOMPLETE and blocks the current
backend consumer; the command-line census also returns nonzero.

chip-AGNOSTIC: everything is read from the flow yaml and the project tree.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import re
import subprocess  # nosec B404 — declared flow programs, argv from the yaml
import sys
import time
from pathlib import Path

from typing import Any, Dict, List, Optional, Tuple

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# BELOW the path setup above, not at the top of the file. `programs/` is flat and its modules
# import each other by BARE name; Python only puts a file's own directory on `sys.path` when
# that file is `__main__`, so under `spec_from_file_location` -- how the gates and much of the
# suite load a program -- a bare sibling import placed before that block raises
# ModuleNotFoundError. `test_issue2104_programs_load_by_path` names the offender, and it named
# `design_input_digest` for exactly this on next/icslot75-dig.
import _gate_authorship as _ga  # noqa: E402  R-0915-160 (who invoked the writer)

from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

PROGRAM = "flow_declared_producer_run"
VERSION = "1.0.0"
PROGRAMS_DIR = Path(__file__).resolve().parent
FLOW_YAML = PROGRAMS_DIR.parent / "flow" / "phase1_phase2_phase3.yaml"
REPORT_REL = "reports/audit/flow_declared_producer_run.json"

#: The gate keys whose value is a shell-shaped command string.
_COMMAND_KEYS = ("program_exit_zero", "advisory_program_exit_zero",
                 "optional_program_exit_zero")
_JSON_RE = re.compile(r"--json[=\s]+(\S+)")


def _iter_steps(node: Any):
    if isinstance(node, dict):
        if "id" in node and ("required_outputs" in node or "gate" in node):
            yield node
        for v in node.values():
            yield from _iter_steps(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_steps(v)


def _iter_commands(node: Any, out: List[str]) -> List[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _COMMAND_KEYS:
                if isinstance(v, str):
                    out.append(v)
                elif isinstance(v, dict) and isinstance(v.get("command"), str):
                    out.append(v["command"])
            else:
                _iter_commands(v, out)
    elif isinstance(node, list):
        for v in node:
            _iter_commands(v, out)
    return out


def _iter_command_specs(node: Any) -> List[Tuple[str, str]]:
    """Return declared commands with the flow's enforcement tier attached."""
    found: List[Tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _COMMAND_KEYS:
                enforcement = "advisory" if key == "advisory_program_exit_zero" \
                    else "blocking"
                if isinstance(value, str):
                    found.append((value, enforcement))
                elif isinstance(value, dict) and isinstance(value.get("command"), str):
                    found.append((value["command"], enforcement))
            else:
                found.extend(_iter_command_specs(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_iter_command_specs(value))
    return found


def declared_producer_clauses(flow_yaml: Path = FLOW_YAML
                              ) -> List[Dict[str, str]]:
    """Every clause the flow declares as a step's OWN producer of a declared
    output. `[{"step", "program", "command", "target"}]`, in flow order.

    THREE CONDITIONS, ALL FROM THE FLOW, none inferred:
      * the clause's program is listed under that step's `programs:`;
      * the clause names a `--json <path>`;
      * that path is one of the step's `required_outputs`.

    A clause meeting all three is the flow saying, in three places, that the
    RUN writes this document.
    """
    try:
        import yaml  # noqa: PLC0415 — optional at import time, required here
    except ImportError:
        return []
    try:
        doc = yaml.safe_load(flow_yaml.read_text(errors="replace"))
    except (OSError, ValueError):
        return []
    found: List[Dict[str, str]] = []
    #: THE FLOW'S OWN ORDER, taken once from the definition. R-0915-160. The two channels
    #: below are collected in separate passes and used to be CONCATENATED, which put every
    #: `program_outputs` clause after every gate clause regardless of step -- see the sort at
    #: the end of this function for what that cost.
    order = {str(_s.get("id")): _i for _i, _s in enumerate(_iter_steps(doc))}
    for step in _iter_steps(doc):
        outs = set(step.get("required_outputs") or [])
        producers = {str(p).strip() for p in (step.get("programs") or [])
                     if isinstance(p, str) and str(p).strip()}
        if not outs or not producers:
            continue
        for cmd, enforcement in _iter_command_specs(step.get("gate") or {}):
            parts = cmd.split()
            if not parts or parts[0] not in producers:
                continue
            m = _JSON_RE.search(cmd)
            if not m or m.group(1) not in outs:
                continue
            clause = {"step": str(step.get("id")), "program": parts[0],
                      "command": cmd, "target": m.group(1),
                      # The step's OTHER declared outputs — the evidence
                      # that the RUN performed this step at all. See
                      # `owed`.
                      "siblings": sorted(outs - {m.group(1)})}
            if enforcement == "advisory":
                # Preserve the flow's advisory tier beside the producer result.
                # A non-zero advisory finding remains visible, but it is not a
                # producer execution failure when the target is complete.
                clause["enforcement"] = "advisory"
            found.append(clause)

    # ── THE SECOND DECLARATION CHANNEL, which is NOT a gate (vibe-ic#2277) ──
    #
    # A step may declare a producer WITHOUT putting it in the gate, and for
    # some producers it MUST: #1980 ruled that step 31's PERC and via findings
    # are ADVISORY EVIDENCE, read through `program_outputs`, with the refusal
    # predicate owned by a separate program -- so naming those producers in the
    # `gate:` promotes them into gate coverage and the enforcement register,
    # which `test_issue1980_advisory_evidence_tiers` refuses by name.
    #
    # That left a real gap rather than a settled question:
    # `reports/phase3/perc_sweep.json` is a step-31 `required_output` declared
    # with its producer under `program_outputs`, and NOTHING ran it. The run
    # produced 8 of 9 declared outputs and the ninth was owed by nobody.
    #
    # `producer_command` closes it on the channel that does not touch a gate.
    # The THREE conditions are the same three, read from the same yaml:
    #   * the entry's `program` is listed under that step's `programs:`;
    #   * the entry states the command that writes the document;
    #   * the entry's `path` is one of the step's `required_outputs`.
    # The audit still executes no gate -- `_collect_program_output_records`
    # reads these entries "WITHOUT EXECUTING A GATE" and is untouched. Only
    # THIS program, which the phase-3 runner invokes, executes them, and only
    # when the document is absent.
    #
    # An entry with no `producer_command` is NOT adopted: silence is not a
    # dispatch instruction, and guessing a producer's argv is how a declared
    # output gets written by something nobody asked for.
    for step in _iter_steps(doc):
        outs = set(step.get("required_outputs") or [])
        producers = {str(p).strip() for p in (step.get("programs") or [])
                     if isinstance(p, str) and str(p).strip()}
        if not outs or not producers:
            continue
        for spec in step.get("program_outputs") or []:
            if not isinstance(spec, dict):
                continue
            program = str(spec.get("program") or "").strip()
            target = str(spec.get("path") or "").strip()
            cmd = spec.get("producer_command")
            if (not program or program not in producers
                    or target not in outs
                    or not isinstance(cmd, str) or not cmd.strip()):
                continue
            cmd = cmd.strip()
            if cmd.split()[0] != program:
                # The command must be the program the entry names. A row that
                # declares one producer and runs another is a mis-declaration,
                # not a dispatch.
                continue
            if any(f["step"] == str(step.get("id")) and f["target"] == target
                   for f in found):
                continue
            found.append({"step": str(step.get("id")), "program": program,
                          "command": cmd, "target": target,
                          "siblings": sorted(outs - {target})})

    # MERGED IN FLOW ORDER, NOT CONCATENATED. R-0915-160. This function's own docstring has
    # always said "in flow order"; it was not, and nothing checked.
    #
    # The gate channel is collected in the first pass and `program_outputs` in the second, so
    # every clause of the second channel ran after every clause of the first whatever step it
    # belonged to. MEASURED on the shipped flow: of 27 clauses, indices 0..24 were already in
    # perfect flow order, and there is exactly ONE `program_outputs` clause --
    #
    #     step 31  perc_corpus_sweep -> reports/phase3/perc_sweep.json
    #
    # -- which belongs beside step 31's other three clauses and landed last, after step 37's
    # `stage3_compliance` clause. That single misplacement produced all the disorder: three
    # inversions, against steps 37, 37.5ip and 37.5ic.
    #
    # WHAT IT COST, by differential on one project, running the real `stage3_compliance`
    # twice. Step 37's clause publishes a verdict about STAGE 3 -- which contains step 31 --
    # so it judged step 31 while step 31's own artefact did not yet exist:
    #
    #   perc_sweep.json ABSENT   sweep_reach_check  verdict=NOT_APPLICABLE
    #                            reason_class=DESIGN_DECLARED_NA enforcement=NOT_RUN_DECLARED
    #   perc_sweep.json PRESENT  sweep_reach_check  rc=2 verdict=INCOMPLETE
    #                            reason_class=EXECUTION_ERROR enforcement=DISCLOSED_INCOMPLETE
    #
    # So the published report recorded a declared gate as "this design does not have that"
    # when the run writes the artefact four clauses later. A FALSE NA, not a stale number --
    # and `owed()` never regenerated the report, so it survived every later run.
    #
    # `list.sort` is STABLE, which is the whole reason this is a sort and not a re-collection:
    # within one step the gate clauses keep their position ahead of that step's
    # `program_outputs` clauses, which is the order the flow states them in. A step id the
    # flow does not contain sorts last, deterministically, rather than raising.
    found.sort(key=lambda r: order.get(str(r.get("step")), len(order)))
    return found


def _glob_exists(project: Path, spec: str) -> bool:
    """Does any file match this declared-output spec?

    A spec may be a plain path, a glob, or `A OR B` — the three shapes the
    flow's `required_outputs` uses. The reader is deliberately permissive:
    the question is only "did the run leave evidence of this step", and a
    false NO leaves a gap open rather than manufacturing work.
    """
    for alt in (a.strip() for a in str(spec).split(" OR ")):
        if not alt:
            continue
        if any(ch in alt for ch in "*?["):
            try:
                for candidate in project.glob(alt):
                    if _is_run_owned_evidence(project, candidate, allow_empty=True):
                        return True
            except (OSError, ValueError, IndexError):
                continue
        elif _is_run_owned_evidence(project, project / alt, allow_empty=True):
            return True
    return False


def _document_role(path: Path) -> Optional[str]:
    """What the document at `path` says about who invoked its writer, or None.

    None is not `producer`: a document written before the stamp existed says nothing, and the
    caller falls back to the note for exactly those. Anything unreadable, non-JSON or not an
    object also says nothing -- the conservative direction, which leaves the run's artefact
    alone rather than manufacturing work from a parse failure.
    """
    try:
        import json as _json                                # noqa: PLC0415
        if path.stat().st_size > 4 * 1024 * 1024:
            return None
        return _ga.role_of(_json.loads(path.read_text(errors="replace")))
    except (OSError, ValueError):
        return None


def _audit_claims(project: Path, sid: str, rel: str) -> bool:
    """Has the AUDIT recorded this exact file as its own write?

    Delegated to `flow_compliance_check`'s own note reader so there is ONE
    definition of what that record is and what makes it stale. Absent module,
    absent note, or a note whose (size, mtime) no longer matches the live file
    all answer False -- the conservative direction, which leaves the run's own
    artefact alone.
    """
    try:
        import flow_compliance_check as _fcc  # noqa: PLC0415
        return bool(_fcc._prior_audit_created(project, sid, [rel]))
    except Exception:  # noqa: BLE001 — a sibling that cannot be read is named
        return False


@functools.lru_cache(maxsize=1)
def _flow_gate_json_targets() -> set[str]:
    """Return declared gate ``--json`` destinations, without reading a run tree."""
    try:
        import yaml  # noqa: PLC0415
        flow = yaml.safe_load(FLOW_YAML.read_text(errors="replace"))
    except (ImportError, OSError, ValueError):
        return set()
    found: set[str] = set()
    for step in _iter_steps(flow):
        for command in _iter_commands(step.get("gate") or {}, []):
            match = _JSON_RE.search(command)
            if match:
                found.add(match.group(1))
    return found


def _is_run_owned_evidence(project: Path, path: Path, *, for_input: bool = False,
                           allow_empty: bool = False) -> bool:
    """Whether a concrete output can prove that its owning step ran.

    Audit reports are observations, not producer inputs.  A role stamp is
    authoritative when present; for the input closure an unstamped path that
    is a declared gate ``--json`` destination is excluded, because legacy gate
    writers have no way to distinguish their audit invocation from the run.
    Producer documents at the same path retain precedence through
    ``invoked_as``. ``allow_empty`` is used only for declared sibling
    presence: an empty marker is still evidence that the run performed a
    step. Producer documents and input-identity files remain nonempty-gated.
    """
    try:
        if path.is_symlink():
            return False
        path = path.resolve()
        if not path.is_file() or (not allow_empty and path.stat().st_size <= 0):
            return False
        rel = path.relative_to(project).as_posix()
    except (OSError, ValueError):
        return False
    if rel == REPORT_REL or rel.startswith("reports/audit/"):
        return False
    role = _document_role(path)
    if role == _ga.ROLE_AUDIT:
        return False
    if role == _ga.ROLE_PRODUCER:
        return True
    # For an unstamped JSON gate result, the input closure cannot treat the
    # file as a producer input: legacy audit writers carry no role.  The
    # sibling-presence check remains presence based for compatibility with
    # pre-stamp producer outputs; ownership is resolved by ``owed`` itself.
    return not for_input or rel not in _flow_gate_json_targets()


def owed(project: Path, clauses: List[Dict[str, str]]
         ) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """`(to_run, skipped)` — the clauses whose document the RUN has not made.

    A clause is OWED when its target is absent, or when the only thing that
    has ever written it is the auditor. Anything else is the run's own work and
    is left byte-for-byte alone.
    """
    to_run, skipped = [], []
    for c in clauses:
        target = project / c["target"]
        # DID THE RUN PERFORM THIS STEP AT ALL? Only then is its verdict
        # document owed.
        #
        # MEASURED, and this clause exists because the first version did not
        # have it. Without it the pass ran `pad_assignment_gen` for step
        # 15.5ic on a HARDMACRO delivery — a step whose own predicate
        # (`_chip_path_requests_pad_ring`, vibe-ic#2246) says NO for exactly
        # this delivery — and `post_layout_sim_check` and
        # `mixed_signal_merge_check` for steps this design never ran. The
        # result was three MISSING steps turned into three FAILs and two new
        # failed gates: the flow was made to manufacture work for steps the
        # delivery does not have, which is the opposite of closing a producer
        # gap. A step the run DID perform has left at least one of its other
        # declared outputs on disk; a step it correctly skipped has left none.
        #
        # A clause whose step declares NO other output cannot be judged this
        # way and is left alone — the conservative direction, since the only
        # cost is a gap that stays open and is still reported by the audit.
        sibs = [s for s in (c.get("siblings") or []) if s]
        ran = any(_glob_exists(project, s) for s in sibs)
        if not ran:
            row = dict(c)
            row["why"] = (
                "the run did not perform this step: none of its other declared "
                f"output(s) {sibs or '[]'} is on disk, so its verdict document "
                "is not owed")
            skipped.append(row)
            continue
        if not target.exists():
            row = dict(c); row["why"] = "target absent"
            to_run.append(row)
            continue
        # THE DOCUMENT'S OWN ACCOUNT OF WHO INVOKED ITS WRITER ANSWERS FIRST. R-0915-160.
        #
        # Same precedence as `flow_compliance_check.authorship_answer`, and for the same
        # reason: the role is the only evidence here that is not an inference. The note is
        # bookkeeping ABOUT a write; the stamp is the write saying what it was.
        #
        # MEASURED before this: an `invoked_as: audit` document with no note, a
        # `producer`-stamped one, and an unstamped one all answered "the run already produced
        # it" -- the stamp was invisible to this function, which asked only "absent?" and
        # "does a note claim it?". So a report the AUDIT wrote was never regenerated by the
        # run, and a stale one (the false-NA stage-3 report R-0915-160's other half is about)
        # survived every later run, because `_audit_claims` needs a note and a note is a file
        # that can be swept or lost.
        _role = _document_role(target)
        if _role == _ga.ROLE_AUDIT:
            row = dict(c)
            row["why"] = ("present, but the document states `invoked_as: audit`: the only "
                          "writer so far is the auditor, so the run still owes it")
            to_run.append(row)
        elif _role == _ga.ROLE_PRODUCER:
            row = dict(c)
            if not _producer_target_has_content(target):
                row["why"] = ("present, but the producer stamp lacks a substantive current "
                               "report schema/content proof")
                to_run.append(row)
            else:
                row["why"] = "the run already produced it, and the document says so"
                skipped.append(row)
        elif _audit_claims(project, c["step"], c["target"]):
            row = dict(c)
            row["why"] = ("present and stating no role, but the audit's own authorship note "
                          "claims it: the only writer so far is the auditor")
            to_run.append(row)
        else:
            row = dict(c); row["why"] = "the run already produced it"
            skipped.append(row)
    return to_run, skipped


def _run_one(project: Path, row: Dict[str, str], timeout: int
             ) -> Dict[str, Any]:
    prog = PROGRAMS_DIR / f"{row['program']}.py"
    out = dict(row)
    if not prog.is_file():
        out.update({"rc": None, "executed": False,
                    "note": f"{row['program']}.py is not in programs/"})
        return out
    # Use the gate's existing project-relative argv semantics, including
    # nullglob for optional source extensions. Literal *.sv/*.v arguments
    # made the owed ROM producer refuse before it could publish its evidence.
    from flow_compliance_check import _resolve_program_cmd
    argv = _resolve_program_cmd(row["command"], cwd=project)
    if not argv:
        out.update({"rc": None, "executed": False,
                    "note": "declared producer command could not be resolved"})
        return out
    t0 = time.time()
    try:
        cp = subprocess.run(  # nosec B603 — argv from the flow yaml
            argv, cwd=str(project), capture_output=True, text=True,
            timeout=timeout)
        rc = cp.returncode
        tail = (cp.stderr or cp.stdout or "").strip()[-300:]
    except subprocess.TimeoutExpired:
        out.update({"rc": None, "executed": False,
                    "note": f"did not finish in {timeout}s"})
        return out
    except OSError as exc:
        out.update({"rc": None, "executed": False, "note": str(exc)})
        return out
    target = project / row["target"]
    # Bind the receipt to the bytes produced by THIS invocation as well as to
    # the producer role.  Reused results already carried this digest through
    # ``prior_targets``; first-run results must carry it too, otherwise the
    # evidence for a fresh producer is weaker than the evidence for a reuse.
    target_exists_after = (target.is_file() and not target.is_symlink()
                           and target.stat().st_size > 0)
    out.update({"rc": rc, "executed": True,
                "elapsed_s": round(time.time() - t0, 2),
                "target_exists_after": target_exists_after,
                "target_sha256": (_target_digest(target)
                                  if target_exists_after else None),
                "target_content_valid": (_producer_target_has_content(target)
                                          if target_exists_after else False),
                "authorship": _document_role(target) if target.exists() else None,
                "tail": tail})
    return out


def _result_is_producer_complete(result: Dict[str, Any]) -> bool:
    """Whether one owed clause completed as producer-owned evidence."""
    rc = result.get("rc")
    advisory_finding = rc == 1 and result.get("enforcement") == "advisory"
    if type(rc) is not int or (rc != 0 and not advisory_finding):
        return False
    if result.get("executed") is not True:
        return False
    if result.get("target_exists_after") is not True:
        return False
    if result.get("target_content_valid") is False:
        return False
    role = result.get("authorship")
    return role == _ga.ROLE_PRODUCER


def _run_clauses(project: Path, clauses: List[Dict[str, str]],
                 timeout: int = 900, *, prior_targets=None) -> Dict[str, Any]:
    """Execute only the supplied flow-declared producer clauses.

    The phase runner uses :func:`run` for its final all-step refresh. Backend
    workers need the same ownership decision *before* their consumer runs, but
    must not sweep producers for unrelated steps (or make a later step's
    document look like evidence for the current one). Keeping the census in one
    helper preserves the existing ``owed`` and authorship rules for both call
    paths.
    """
    to_run, skipped = owed(project, clauses)
    if prior_targets is not None:
        retained = []
        for row in skipped:
            if str(row.get("why", "")).startswith("the run did not perform this step"):
                # run_for_step explicitly selected this step. Its report-only
                # outputs cannot have siblings before the first producer runs.
                # The all-step refresh still uses owed's performed-step filter.
                to_run.append(dict(row, why="explicit current-step producer request"))
                continue
            target = project / row["target"]
            if (_producer_target_has_content(target) and
                    prior_targets.get(row["target"]) == _target_digest(target)):
                retained.append(dict(row, target_sha256=_target_digest(target),
                                     current_input_identity_valid=True))
            else:
                to_run.append(dict(row, why="prior target lacks current input/content proof"))
        skipped = retained
    results = [_run_one(project, row, timeout) for row in to_run]
    if prior_targets is not None:
        for clause, result in zip(to_run, results):
            result.setdefault("target", clause["target"])
            target = project / clause["target"]
            result["target_content_valid"] = _producer_target_has_content(target)
            result["target_sha256"] = _target_digest(target)
    unexecutable = [r for r in results if not r.get("executed")]
    invalid_results = [r for r in results if not _result_is_producer_complete(r)]
    produced = [r for r in results if _result_is_producer_complete(r)]
    # TWO DIFFERENT FACTS WERE COUNTED AS ONE (vibe-ic#619 / RC13). `skipped`
    # holds both "the run already produced it" and "the run did not perform this
    # step", and `already_produced_by_the_run` was `len(skipped)` -- so a project
    # where NOTHING ran reported every clause as already produced. MEASURED on
    # an empty directory at f19703dfa: "29 declared producer clause(s); 29
    # already produced by the run, 0 owed, 0 executed", exit 0. Every word of
    # that sentence except the first number was false.
    not_performed = [r for r in skipped
                     if str(r.get("why", "")).startswith(
                         "the run did not perform this step")]
    produced_already = [r for r in skipped if r not in not_performed]
    # THE POPULATION this census measures is the clauses whose step the run
    # actually PERFORMED. A clause skipped because its step never ran was not
    # judged; counting it as an answer is what made an empty subject look like a
    # finished flow.
    population = len(to_run) + len(produced_already)
    return {
        "program": PROGRAM, "version": VERSION,
        "declared_clauses": len(clauses),
        "owed": len(to_run),
        "already_produced_by_the_run": len(produced_already),
        "steps_the_run_did_not_perform": len(not_performed),
        "population": population,
        "executed": len(results) - len(unexecutable),
        "documents_now_present": len(produced),
        "unexecutable": unexecutable,
        "invalid_results": invalid_results,
        "results": results, "skipped": skipped,
        "verdict": ("ZERO_POPULATION" if population == 0
                    else "INCOMPLETE" if (unexecutable or invalid_results)
                    else "PRODUCED"),
    }


def _target_digest(path: Path) -> Optional[str]:
    try:
        if path.is_symlink() or not path.is_file() or not path.stat().st_size:
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _producer_target_has_content(path: Path) -> bool:
    """A writer label alone is not a completed verdict document."""
    try:
        if _target_digest(path) is None:
            return False
        document = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(document, dict) or _ga.role_of(document) != _ga.ROLE_PRODUCER:
        return False
    if not isinstance(document.get("program"), str) or not document["program"]:
        return False
    if document["program"] == "flow_compliance_check":
        return isinstance(document.get("steps"), list) and bool(document["steps"])
    return True


def _current_input_identity(project: Path, clauses) -> Dict[str, Any]:
    """Bind reuse to source and exact input bytes, independent of wall-clock run id."""
    project = project.resolve()
    excluded = {REPORT_REL, *(row["target"] for row in clauses)}
    files = {}
    for path in sorted(project.rglob("*")):
        relative = path.relative_to(project).as_posix()
        if relative in excluded:
            continue
        if path.is_symlink():
            # Future steps publish their output aliases before producing the
            # files. Like an absent regular output, that alias contributes no
            # current input bytes; the owning step checks it when it is due.
            if not path.exists():
                continue
            # The canonical step layout publishes local aliases of the same
            # project's phase outputs. Hash the real input once, rather than
            # refusing an alias emitted by our own runner.
            path = path.resolve(strict=True)
            if not path.is_relative_to(project):
                raise ValueError("producer input symlink leaves project: " + relative)
            relative = path.relative_to(project).as_posix()
            if relative in excluded:
                continue
        if path.is_file():
            # The audit can leave gate reports beside the producer's real
            # inputs.  Including those bytes makes a later audit rewrite the
            # producer's input identity and can make its own JSON appear to be
            # current producer evidence.  Keep producer-stamped reports; only
            # audit-owned or attribution-free declared gate outputs are
            # removed from the closure.  A zero-byte *source* is still a
            # semantic input: it must invalidate reuse when it changes to (or
            # from) empty.  Zero-byte outputs remain excluded by
            # `_is_run_owned_evidence` and cannot prove a producer ran.
            if path.stat().st_size == 0:
                if (relative.startswith("reports/audit/") or
                        relative in _flow_gate_json_targets() or
                        _document_role(path) == _ga.ROLE_AUDIT):
                    continue
            elif not _is_run_owned_evidence(project, path, for_input=True):
                continue
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    source_files = {str(path): _target_digest(path) for path in
                    [Path(__file__), FLOW_YAML, *
                     (PROGRAMS_DIR / (row["program"] + ".py") for row in clauses)]}
    if any(digest is None for digest in source_files.values()):
        raise ValueError("producer source has no readable current content")
    # Installed plugin packages contain source files, not repository metadata.
    # These exact bytes also detect a source edit before it is committed.
    source = "sha256:" + hashlib.sha256(
        json.dumps(source_files, sort_keys=True).encode()).hexdigest()
    return {"source_sha": source, "source_files": source_files, "files": files,
            "clauses": clauses}


def run_for_step(project: Path, step_id: str, timeout: int = 900
                 ) -> Dict[str, Any]:
    """Run only the producers declared for one current flow step.

    This is the pre-consumer seam used by a per-step backend worker.  The
    Filtering by the requested step prevents unrelated producer clauses from
    running or being credited to its evidence. Unlike the final all-step
    refresh, an explicitly selected step also starts its report producers when
    none of its outputs exists yet. Reuse still requires current-input and
    content-bound producer evidence.
    """
    sid = str(step_id)
    project = Path(project)
    clauses = [c for c in declared_producer_clauses()
               if str(c.get("step")) == sid]
    identity = _current_input_identity(project, clauses)
    try:
        prior = json.loads((project / REPORT_REL).read_text())
    except (OSError, ValueError):
        prior = {}
    prior_targets = {}
    if (isinstance(prior, dict) and prior.get("schema") == "vibeic/current-step-producer-census/1"
            and prior.get("step_id") == sid and prior.get("verdict") == "PRODUCED"
            and prior.get("input_identity") == identity):
        for row in prior.get("results", []) + prior.get("skipped", []):
            if isinstance(row, dict) and isinstance(row.get("target_sha256"), str):
                prior_targets[row.get("target")] = row["target_sha256"]
    rec = _run_clauses(project, clauses, timeout, prior_targets=prior_targets)
    rec["schema"] = "vibeic/current-step-producer-census/1"
    rec["step_id"] = sid
    rec["scope"] = "current-step"
    rec["input_identity"] = _current_input_identity(project, clauses)
    report = project / REPORT_REL
    report.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(report, json.dumps(rec, sort_keys=True, indent=2) + "\n")
    return rec

def run(project: Path, timeout: int = 900) -> Dict[str, Any]:
    return _run_clauses(project, declared_producer_clauses(), timeout)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir")
    ap.add_argument("--json", default="")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--list", action="store_true",
                    help="print the declared clauses and exit without running")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    project = Path(args.project_dir).resolve()
    if args.list:
        for c in declared_producer_clauses():
            print(f"{c['step']:8} {c['program']:36} -> {c['target']}")
        return 0
    if not project.is_dir():
        print(f"[CANNOT CHECK] {PROGRAM} — {project} is not a directory")
        return 2
    rec = run(project, args.timeout)
    target = Path(args.json) if args.json else project / REPORT_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    # vibe-ic#1082: the final name must appear only once the write completed --
    # this report IS a declared destination (REPORT_REL), and `required_outputs`
    # credits a step for the name existing, not for the file being whole.
    # `write_text` rather than `write_json` ON PURPOSE: `rec` carries `tail`,
    # the last 300 chars of a producer's own stderr/stdout (see `run` below),
    # and this plugin's producers quote zh-Hant spec lines. `write_json` passes
    # ensure_ascii=False, so converting through it would silently change the
    # bytes of every report that has non-ASCII in a tail. _atomic_artefact's own
    # rule is that a conversion does not alter what gets written.
    atomic_write_text(target, json.dumps(rec, indent=2) + "\n")
    # THE REFUSAL COMES BEFORE THE FINDINGS BRANCHES, and that placement is the
    # point: a refusal under `if rc == 0` is switched off by any finding,
    # including one read from the flow yaml, which says nothing about this tree.
    # The report is written FIRST (above) because a producer that writes nothing
    # when it declines cannot be told from one that never ran.
    if rec["population"] == 0:
        print(f"[ZERO_POPULATION] {PROGRAM} — none of the "
              f"{rec['declared_clauses']} declared producer clause(s) could be "
              f"judged: for every one of them the run left no other declared "
              f"output on disk, so no step is known to have been performed and "
              f"this census measured NOTHING about {project}. Not a pass: a "
              f"verdict over an empty population is the one red a census has.",
              file=sys.stderr)
        return 2
    print(f"[{rec['verdict']}] {PROGRAM} — {rec['declared_clauses']} declared "
          f"producer clause(s); {rec['population']} judged "
          f"({rec['already_produced_by_the_run']} already produced by the run, "
          f"{rec['owed']} owed, {rec['executed']} executed, "
          f"{rec['documents_now_present']} document(s) now present); "
          f"{rec['steps_the_run_did_not_perform']} clause(s) NOT judged because "
          f"the run did not perform their step")
    for r in rec["results"]:
        print(f"  step {r['step']:8} {r['program']:34} rc="
              f"{r.get('rc')} ({r.get('why')})")
    for r in rec["unexecutable"]:
        print(f"  NOT EXECUTABLE: step {r['step']} {r['program']}: "
              f"{r.get('note')}", file=sys.stderr)
    return 1 if rec["verdict"] == "INCOMPLETE" else 0


if __name__ == "__main__":
    sys.exit(main())
