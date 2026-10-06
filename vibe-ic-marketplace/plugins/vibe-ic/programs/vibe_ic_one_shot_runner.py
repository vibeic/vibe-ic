#!/usr/bin/env python3
"""vibe_ic_one_shot_runner.py — full Vibe-IC flow orchestrator.

Top-level chain that runs the entire spec → silicon pipeline:

    Phase 1 (optional)  → input/phase1_* → generated_docs/L*.json
        ↓
    Phase 2 (= 2a + 2b) → input/docs → 13 L docs → RTL → SOF → <half-duplex-tester>
        ↓
    Analog A1..A8        → analog/<block> hardmacros (skipped if no analog)
        ↓
    Phase 3              → synth → PnR → GDS → DRC → LVS

chip-AGNOSTIC. Auto-detects entry point:
  - Path A (NL prompt):  <project>/input/phase1_structured.yaml present
  - Path B (vendor docs): <project>/input/docs/ already populated;
                          phase1 SKIPped automatically.

Halt rules:
  - Phase 1 FAIL → halt before Phase 2
  - Phase 2 FAIL → halt before Phase 3 (and analog skipped if not run yet)
  - Analog WAIVED is non-blocking
  - Phase 3 FAIL → final verdict FAIL but report still emitted

Aggregate report: <project>/reports/vibe_ic_one_shot.json
Per-phase reports: phase1/phase2/phase1/phase2/phase3/analog _one_shot.json

Usage:
    python3 vibe_ic_one_shot_runner.py <project>
            [--top-name chip_top]
            [--container vibeic-eda]
            [--require-image vibeic-eda:<tag>]   # enforce WHICH image
            [--max-rtl-repair-retries 3]
            [--skip-hardware]
            [--skip-phase1]
            [--skip-analog]
            [--skip-phase3]
            [--die-um 1500x1500]
            [--util 0.4]
            [--pdk auto|sky130A|<custom>]
            [--ic-name <name>]      # forwarded to phase1
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import argparse
import _delivery_route
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple
import _path_layout as _pl
import _phase1_producer_identity as _p1id  # FX_STALE_LDOCS
import _audit_scope                     # R-0915-150 (one scope predicate)
import _runner_lock
import canonical_run_admission as _canonical_admission
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated


PROGRAMS_DIR = Path(__file__).resolve().parent
def _configure_execution_policy(args, **_rejected_mint_arguments):
    """Consume a launcher-issued policy; imported calls cannot issue it."""
    import execution_policy
    return execution_policy.configure(args)


def _write_runner_summary(out: Path, summary: dict, project: Path) -> None:
    """Publish the front door's own account with its actual dispatch generation."""
    from benchmark_dispatch import _bind_runner_report
    summary = _bind_runner_report(summary, project, __file__, out.name)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")


def _propagatable_image(container: str,
                        rec: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """`(reference, why_not)` — what to export as `VIBEIC_EDA_IMAGE` for a child
    that resolves an image of its own.

    A REFERENCE, NEVER AN Id (#2085). This used to be
    `rec["image_id"] or rec["image_ref"]`, and the reasoning behind preferring
    the id was right about IDENTITY and wrong about SHAPE: `.Image` is a bare
    `sha256:<64 hex>`, which `docker run` accepts and which is not a reference.
    The far end -- `_eda_image.judged_image()` -- reads this variable as one,
    split it into repository `sha256` + tag, re-attached the pinned digest, and
    handed `docker run` the string ``sha256@sha256:8c5694…``: rc=125, the
    gf180mcuD tech LEF unread, and `database_unit_um` published as
    NOT_DETERMINED with nothing saying the reference had been malformed.

    The preference that keeps BOTH properties -- immutable, and resolvable --
    is the registry-portable digest reference:

      1. `.Config.Image` when the container was already started from
         `<repo>@sha256:<digest>`, verbatim: same repository the operator named;
      2. otherwise that same identity recovered from RepoDigests by the FULL
         image Id already measured in the provenance record. Prefer the named
         repository when available, but a mirror digest still names the verified
         bytes. Reopening a short container name can select a different container;
      3. otherwise the recorded `image_ref` IF it is a reference at all -- a tag
         is mutable, which is the weakness this whole capture exists to correct,
         but a tag resolves and an Id does not name a place at all;
      4. otherwise NOTHING, with the reason recorded. Exporting an Id "because
         it is better than nothing" is what produced a malformed reference that
         read as a successful one.
    """
    ref = str(rec.get("image_ref") or "").strip()
    if _pin.reference_digest(ref):
        return ref, ""
    image_id = str(rec.get("image_id") or "").strip()
    why = ""
    if _pin.DIGEST_RE.match(image_id):
        digests, why = _pin.local_repo_digests(image_id)
        want = _pin.repository_of(ref)
        ranked = sorted(digests, key=lambda entry: 0 if _pin.repository_of(entry) == want else 1)
        for entry in ranked:
            if _pin.reference_digest(entry):
                return entry, ""
    if ref and not _pin.is_bare_image_id(ref):
        return ref, ""
    if not ref and not rec.get("image_id"):
        return None, ""          # nothing was identified; nothing to withhold
    return None, (
        f"the verified image could not be named by a reference a child can "
        f"run: the container records image_ref={ref!r} and "
        f"image_id={str(rec.get('image_id') or '')!r}, and an image Id is not "
        f"a reference (no repository half). {why or ''}".strip())


def _capture_container_image(project: Path, container: str,
                             require_image: Optional[str]) -> Dict[str, Any]:
    """Record WHICH IMAGE `--container` actually executes, into
    `reports/container_image.json`.

    Delegates to `container_image_provenance`, which is the program that knows
    how to ask docker and how to compare a tag against a content-addressed id.
    Best-effort by construction: an import or probe error degrades to a recorded
    note and NEVER crashes the run — the capture exists to make a run
    attributable, so failing the run because the attribution could not be taken
    would be worse than the gap it closes. Enforcement (a non-zero exit on
    MISMATCH) is the caller's decision and only happens under --require-image.
    """
    try:
        import container_image_provenance as _cip
        rec = _cip.verify(container, require_image)
    except Exception as exc:                                # noqa: BLE001
        rec = {"verdict": "SKIP", "container": container,
               "reason": f"image identity unverifiable: "
                         f"{type(exc).__name__}: {exc}"}
    # ── PROPAGATE the run's declared image to every child that resolves one ──
    # Recording the image is not the same as USING it. Steps that shell out via
    # `docker exec <container>` inherit `--container` and are fine; steps that
    # shell out via `docker run <IMAGE>` resolve an image of their OWN, and
    # `fault_atpg_run._resolve_docker_image()` does it by scanning which
    # candidate tags happen to be present LOCALLY — the same
    # picked-by-what-is-lying-around defect class as choosing a tech LEF by
    # filesystem order. When its pinned candidate is not pulled on this host it
    # falls through to the LAST-RESORT upstream `hpretl/iic-osic-tools:latest`,
    # which is a DIFFERENT DISTRIBUTION, not an older version of ours: it ships
    # stock tools without this project's forks.
    #
    # MEASURED on caravel_user_project x sky130A (v1.9.65, this host):
    # (Image tags below are spelled WITHOUT the registry prefix on purpose:
    # they are a historical MEASUREMENT of one run, not live image pointers
    # for `tools/vibeic-eda/sync_image_version.py` to keep in step.)
    #   reports/container_image.json : image_ref = the vibeic-eda fork, tag 0.2.58
    #                                  image_match true, verdict PASS
    #   the DFT step actually ran in : hpretl/iic-osic-tools:latest
    #                                  (`fault chain --help` | grep -c skip-boundary = 0;
    #                                   the pinned 0.2.58 answers 1)
    #   consequence                  : `fault chain` rc=64 "Unknown option
    #                                  '--skip-boundary'" -> no scan netlist ->
    #                                  Step 11 DFT FAIL -> 24 downstream steps
    #                                  PASS-VOIDED. The run VERIFIED one image
    #                                  and silently used another.
    #
    # So the resolved identity is exported here, at the one place that has
    # already resolved AND verified it. An operator-set VIBEIC_EDA_IMAGE /
    # IIC_EDA_IMAGE always wins (this only fills an EMPTY slot, so it cannot
    # override a deliberate cross-image experiment). What is exported is a
    # digest-pinned REFERENCE — see `_propagatable_image`, and #2085 for what
    # exporting the Id instead did to the far end.
    _img, _why_no_img = _propagatable_image(container, rec)
    if _img and not (os.environ.get("VIBEIC_EDA_IMAGE")
                     or os.environ.get("IIC_EDA_IMAGE")):
        os.environ["VIBEIC_EDA_IMAGE"] = str(_img)
        rec["propagated_to_child_docker_run"] = str(_img)
        rec["propagated_via"] = "VIBEIC_EDA_IMAGE"
    elif _img:
        rec["propagated_to_child_docker_run"] = None
        rec["propagated_via"] = (
            "operator env override in force (VIBEIC_EDA_IMAGE/IIC_EDA_IMAGE) — "
            "left as set")
    elif _why_no_img:
        # NOT SILENT. The run continues -- the capture is best-effort by
        # construction -- but a child that resolves its own image will now pick
        # one, and the record says why this run could not name the verified
        # image in a shape a child can run. An unpropagated image and a
        # propagated malformed one are different facts and are recorded as such.
        rec["propagated_to_child_docker_run"] = None
        rec["propagated_via"] = None
        rec["propagation_withheld"] = _why_no_img
    try:
        out = _pl.reports_dir(project) / "container_image.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    except OSError:
        pass
    return rec


def _capture_pdk_revision(project: Path, container: str) -> Dict[str, Any]:
    """Record WHICH PDK REVISION this run signed off against, into
    `reports/pdk_revision.json`.

    THE OTHER HALF OF `_capture_container_image`. That function exists because
    a run's tool identity was unrecorded and every sign-off number was
    therefore unattributable to a toolchain. The PDK half of the same claim was
    unrecorded too, and worse: every place a run said anything about its PDK
    said the REQUEST — `--pdk <name>`, `env_PDK_ROOT`, the registry entry, the
    published cell's own directory name. None of them names the revision the
    tools actually read, so two runs against a re-pulled volume are identical
    in the record and were measured against different data.

    Called AFTER the phases, not before, and the order is load-bearing:
    `pdk_revision_resolve --from-run` derives the trees from the absolute
    library paths in the run's OWN tool logs — what RAN, rather than what was
    configured — and those logs do not exist yet at the point the image
    identity is taken.

    BEST-EFFORT FOR THE RUN, BLOCKING AT PUBLISH. This never fails a run: the
    record's job is to state what was found, including "NOT DETERMINED", and a
    run that halted early or was told --skip-phase3 legitimately has no PDK to
    name. `benchmark_evidence_publish` is where the record becomes a
    requirement, because that is the act — publishing a sign-off number — that
    the missing revision makes unreproducible.
    """
    out = _pl.reports_dir(project) / "pdk_revision.json"
    try:
        import pdk_revision_resolve as _prr
        fs = _prr.Fs(container)
        trees, scanned = _prr.candidate_trees_from_run(project, fs)
        resolved = [_prr.resolve_tree(fs, t) for t in trees]
        rec = _prr.build_record(
            resolved, f"container:{fs.container}" if fs.container else "host", "run tool logs",
            note=(f"derived from {scanned} tool log(s) under {project}; "
                  f"{len(trees)} tree(s) offered a declared-revision artefact"))
        if not trees:
            rec["reason"] = (
                f"no PDK tree was derivable from this run: {scanned} tool "
                f"log(s) scanned, none naming an absolute library path under a "
                f"tree that declares a revision. A run with no physical "
                f"implementation is in this state legitimately; a run that "
                f"placed and routed is not.")
    except Exception as exc:                                # noqa: BLE001
        # #2069 — the refusal token is spelled literally on THIS path and only
        # here, because the import that owns it is what just failed. It is the
        # same string as `pdk_revision_resolve.REFUSAL_NOT_RECORDED`, and the
        # test that pins them equal is the thing that keeps it so.
        rec = {"schema": 1,
               "resolved": False,
               "revision": None,
               "refusal": "PDK_REVISION_NOT_RECORDED",
               "trees": [],
               "read_in": f"container:{container}",
               "derived_from": "run tool logs",
               "reason": f"the PDK revision could not be resolved: "
                         f"{type(exc).__name__}: {exc}"}
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    except OSError:
        pass
    return rec


def _deliverable_self_check(project: Path) -> Dict[str, Any]:
    """v1.3.51 FINALIZE self-check: run run_output_completeness_check on this
    run_dir so the run self-verifies its own deliverable before claiming done.

    The runner writes the COMPUTE half (reports/final_summary.md + the
    orchestrator verdict); the agent that DELEGATED this run owes the SYNTHESIS
    half (RESULT.md) as its final act. At finalize the RESULT is normally not
    written yet, so this is NON-GATING (it never changes the runner's exit code)
    — but it records the completeness state in the summary JSON and prints a
    STANDING reminder so a run that produces NO RESULT can never go silent: the
    launch-and-idle abandon bug (COMPUTE_DONE_DELIVERABLE_MISSING) is visible in
    the runner's own banner, and the agent's self-verify command is spelled out.
    Best-effort: any import/probe error degrades to a skipped note, never crashes
    the runner. chip-AGNOSTIC."""
    try:
        import run_output_completeness_check as _roc
        rep = _roc.check(project)
        return {
            "state": rep.state,
            "verdict": rep.verdict,
            "deliverable": rep.deliverable,
            "reason": rep.reason,
            "self_verify_cmd": (
                f"python3 {PROGRAMS_DIR / 'run_output_completeness_check.py'} "
                f"{project}"),
        }
    except Exception as exc:  # nosec — a self-check hiccup must not fail the run
        return {"state": "SELF_CHECK_UNAVAILABLE", "verdict": "SKIP",
                "reason": f"deliverable self-check skipped: {exc}"}


def _phase_runner(name: str) -> Path:
    return PROGRAMS_DIR / f"{name}_one_shot_runner.py"


def _launch_dashboard(project: Path, host: str, port: int,
                      full: bool = False) -> Optional[int]:
    """Best-effort: spawn the live web dashboard as a DETACHED, read-only
    observer of `project` so the user can watch each step light up while this
    orchestrator runs. Returns the child PID (or None on failure). Never raises
    — a dashboard hiccup must not touch the flow. The child survives this
    process (start_new_session) so the FINAL state stays viewable after the run;
    the caller prints the PID so the user can stop it.

    #204 — a DETACHED daemon is a deliberate feature for a real user run (its
    survival keeps the final state viewable), but a liability under a test
    harness / CI / headless run, where nothing reaps it and it squats the port
    for the next run. `VIBE_IC_NO_DASHBOARD` (set truthy) suppresses the spawn
    entirely so no such context can leak a daemon; the whole test suite sets it
    via an autouse fixture."""
    if os.environ.get("VIBE_IC_NO_DASHBOARD", "").strip().lower() \
            not in ("", "0", "false", "no", "off"):
        return None
    dash = PROGRAMS_DIR / "flow_dashboard.py"
    if not dash.is_file():
        return None
    log = project / "reports" / ".dashboard_server.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        fh = open(log, "ab")
        cmd = [sys.executable, str(dash), str(project), "--web",
               "--port", str(port), "--host", host]
        if full:
            cmd.append("--full")
        proc = subprocess.Popen(
            cmd, stdout=fh, stderr=fh, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        return proc.pid
    except Exception:
        return None


def _reachable_host(host: str) -> str:
    """Turn a BIND address into a URL host a browser can actually open. A
    wildcard bind (`0.0.0.0` / `::` / empty) is NOT routable, so advertise the
    machine's primary LAN IP instead (discovered via the routing table — a UDP
    `connect` picks the source IP without sending a packet). Loopback stays
    loopback; a specific interface IP the user chose is preserved. Never raises."""
    h = (host or "").strip()
    if h in ("127.0.0.1", "localhost"):
        return "127.0.0.1"
    if h not in ("0.0.0.0", "::", "", "*"):
        return h
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))          # no packet sent for UDP connect
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"


def _cli_snapshot(project: Path) -> str:
    """Best-effort ONE-SHOT CLI dashboard snapshot (`flow_dashboard.py --once`)
    — the glanceable step-map table rendered inline. Returns the text, or '' on
    any failure. Never raises — the dashboard must not touch the flow."""
    dash = PROGRAMS_DIR / "flow_dashboard.py"
    if not dash.is_file():
        return ""
    try:
        cp = subprocess.run(
            [sys.executable, str(dash), str(project), "--once", "--no-color"],
            capture_output=True, text=True, timeout=45)
        return cp.stdout or ""
    except Exception:
        return ""


#: ── the Phase-1 expert hand-off is a TWO-PASS protocol (#2204) ──────────────
#: `phase1_expert_parse_track` writes a pack, records
#: `ai_subtrack.status = HANDOFF_EMITTED`, and ends by telling the operator to
#: "invoke subagent vibe-ic:ic-expert-agent on … and re-run to consume its
#: answer". A subagent then authors `l_doc_expectations.json` beside the pack.
#: THE FRONT DOOR COULD NOT PERFORM THAT RE-RUN. `_phase1_decision` answered
#: "have the L documents been extracted" — the right question for the
#: EXTRACTOR and the wrong one for a two-pass hand-off — so from the first
#: successful run onward `L_count >= 13` was permanently true, every
#: subsequent orchestrator invocation SKIPPED Phase 1, and a delivered expert
#: answer sat on disk unread forever. MEASURED on the real project: the answer
#: file present, the track record still `HANDOFF_EMITTED`, `plan` recording
#: ("phase1", "SKIPPED", 0).
#:
#: The distinction the front door needs is a STATE, not a judgement —
#:     "phase 1 has run"  vs  "phase 1 has run AND its expert answer was read"
#: — and both halves of it are already on disk, written by the track itself.
_EXPERT_TRACK_REPORT_REL = "phase1/expert_parse_track.json"
#: `phase1_expert_parse_track.evaluate`'s `out_dir`, and the `output_target`
#: its hand-off descriptor names as the file the subagent must author.
_EXPERT_PACK_DIRNAME = "expert_parse_track_pack"
_EXPERT_ANSWER_NAME = "l_doc_expectations.json"
#: The producer's hand-off state. Other statuses alone cannot establish that
#: the CURRENT answer was read: even ERROR may precede opening the file.
_EXPERT_AI_UNREAD = "HANDOFF_EMITTED"
#: The mode `_phase1_decision` returns for that second pass. NOT "docs": the
#: extraction is done, and re-running it would both cost a full extraction on
#: every such run and move the L documents the delivered answer was authored
#: against.
_P1_MODE_EXPERT_SECOND_PASS = "expert_second_pass"
#: FX_STALE_LDOCS — a generated L doc no longer holds the bytes phase 1
#: recorded: neither regenerated over the edit nor reused as current.
_P1_MODE_REFUSED = "refused_generated_doc_edited"


def _expert_answer_pending(project: Path) -> Tuple[bool, str]:
    """Retry an answer whose bytes have no matching producer read receipt.

    The producer hashes the exact bytes it parses, including refused JSON.
    An unchanged refused/consumed answer terminates; changed or genuinely
    unread bytes re-enter. Legacy or malformed reports without a digest get
    one read to establish identity. Neither mtime nor status is a receipt.
    This decision grants no execution credit; the expert consumer owns that.
    """
    report = _pl.report_path(project, _EXPERT_TRACK_REPORT_REL)
    answer = report.parent / _EXPERT_PACK_DIRNAME / _EXPERT_ANSWER_NAME
    if not answer.is_file():
        # No answer was delivered. There is nothing to consume, and a re-entry
        # here would re-run the FIRST pass, which is idempotent and already
        # recorded — the tax, again.
        return (False, f"no expert answer at {answer}")
    try:
        blob = json.loads(report.read_text(errors="replace"))
    except OSError:
        return (True, f"{_EXPERT_ANSWER_NAME} exists and the expert track "
                      f"wrote no report to say it was read")
    except ValueError as exc:
        return (True, f"{_EXPERT_ANSWER_NAME} exists and the expert-track "
                      f"report does not parse ({exc}) — an unreadable record "
                      f"cannot say the answer was read")
    ai = blob.get("ai_subtrack") if isinstance(blob, dict) else None
    status = ai.get("status") if isinstance(ai, dict) else None
    if status == _EXPERT_AI_UNREAD:
        return (True, f"{_EXPERT_ANSWER_NAME} exists and the last "
                      f"expert-track record still says "
                      f"ai_subtrack.status={status} — an answer arrived that "
                      f"nobody has read")
    read_digest = ai.get("answer_sha256") if isinstance(ai, dict) else None
    if (status not in ("CONSUMED", "CONSUMED_EMPTY", "ANSWER_SCHEMA_MISMATCH", "ERROR")
            or not isinstance(read_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", read_digest) is None):
        return (True, "the expert record has no identified reading of this answer")
    try:
        current_digest = hashlib.sha256(answer.read_bytes()).hexdigest()
    except OSError as exc:
        return (True, f"cannot identify the current expert answer ({exc}); "
                      "the producer must report the read failure")
    if current_digest != read_digest:
        return (True, "the expert answer changed since the producer last read it")
    return (False, f"the unchanged expert answer was already read "
                   f"(ai_subtrack.status={status!r})")


def _phase1_decision(project: Path, force_skip: bool,
                     knobs: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """Decide whether to run Phase 1 and in which mode.

    Returns (run, mode) where:
      run  -> True if phase1 must run before phase2
      mode -> "prompt" (Path A NL inputs), "docs" (Path B vendor docs),
              "expert_second_pass" (#2204: the L documents already exist AND a
              delivered IC-Expert answer is on disk that the expert track's own
              record says nobody has read — the SECOND pass of the hand-off,
              which re-runs the expert track ALONE and re-extracts nothing),
              or "" when run is False.

    Path-B fix (v-orch): when a project carries POPULATED vendor docs
    (input/docs/ or phase1/input_doc/) but no generated L*.json yet,
    phase2 hard-requires the L docs, so the orchestrator MUST auto-run
    phase1 in docs mode rather than skip it. Previously docs-only
    projects skipped phase1 and dead-ended at the phase2 precondition.

    chip-AGNOSTIC — path existence + L-doc count only.
    """
    if force_skip:
        return (False, "")
    gd = _pl.generated_docs_dir(project)
    L_count = len(list(gd.glob("L*.json"))) if gd.is_dir() else 0
    # Already has the full L-doc set → the EXTRACTION has nothing to do.
    if L_count >= 13:
        # #2204 — but "the L documents exist" is not "Phase 1 is finished".
        # Phase 1's second track is a two-pass hand-off, and its second pass is
        # a state this project either is or is not in. Ask.
        pending, _why = _expert_answer_pending(project)
        if pending:
            return (True, _P1_MODE_EXPERT_SECOND_PASS)
        # FX_STALE_LDOCS — and "the L documents exist" is not "they are what
        # the CURRENT producer would write". A skip keyed on existence is a
        # stale cache: a phase-1 producer fix never reached an existing
        # project (measured, subservient f4). Reuse needs the producer's own
        # identity to match; see `_phase1_producer_identity`.
        fresh = _phase1_freshness(project, knobs)
        if fresh["state"] == _p1id.REUSE:
            return (False, "")
        if fresh["state"] == _p1id.REFUSE:
            return (False, _P1_MODE_REFUSED)
        # REGENERATE — but only from DESIGN INPUT. L docs with no input behind
        # them were HANDED to this project; they ARE its input, and input is
        # never regenerated or judged stale.
        if _design_input_present(project):
            return (True, "docs")
        return (False, "")
    return _phase1_decision_from_inputs(project)


def _stale_generated_docs_note(regenerating: bool,
                               fresh: Optional[Dict[str, Any]],
                               design_input: bool,
                               skipped_by: str) -> Optional[str]:
    """The disclosure a phase-1-skipping run owes when it reads stale docs.

    FX_STALE_LDOCS (5). A window / entry-step run keeps its contract -- it
    does not run phase 1 -- but it READS the generated docs. When they are not
    what the current producer would write, that is DISCLOSED by name. Not a
    FAIL: nothing was found wrong with the design, and a FAIL would say it
    was. Not a PASS either: `_demote_for_stale_generated_docs` turns a PASS
    over docs whose currency is not established into NOT_MEASURED, with this
    sentence as the reason.

    Owed by EVERY run that proceeds over those docs without regenerating them
    -- a window run, and the expert second pass too (review wave8 MINOR: it
    re-enters phase 1 but re-extracts nothing). Never owed for L docs with no
    design input behind them: they are the project's INPUT, exactly as
    `_phase1_decision` rules, and input is never judged stale (review wave8
    MAJOR: 33 corpus projects were NOT_MEASURED for good)."""
    if regenerating or not design_input or fresh is None \
            or fresh.get("state") == _p1id.REUSE:
        return None
    return (f"STALE_GENERATED_DOCS: this run did not regenerate phase 1 "
            f"({skipped_by}) "
            f"and read generated L docs that are {fresh.get('state')} "
            f"({fresh.get('reason')}): {fresh.get('why')}")


def _demote_for_stale_generated_docs(overall: str, why: Optional[str],
                                     reasons: List[str]) -> str:
    """A green verdict over stale docs is NOT_MEASURED, never red, never green."""
    if why and overall in ("PASS", "PASS_WITH_WAIVERS"):
        reasons.append(why)
        return "NOT_MEASURED"
    return overall


def _design_input_present(project: Path) -> bool:
    """Is there design input phase 1 could extract from? The same predicate
    the no-L-docs branch uses, asked on its own."""
    return _phase1_decision_from_inputs(project) == (True, "docs")


def _phase1_freshness(project: Path,
                      knobs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """`_phase1_producer_identity.assess` against THIS plugin, with the knobs
    this run would hand phase 1 (None: not known, the recorded ones apply)."""
    try:
        return _p1id.assess(project, PROGRAMS_DIR, knobs)
    except Exception as exc:                               # noqa: BLE001
        return {"state": _p1id.REGENERATE,
                "reason": _p1id.NO_PRODUCER_IDENTITY,
                "why": f"the producer identity could not be read ({exc})"}


def _phase1_decision_from_inputs(project: Path) -> Tuple[bool, str]:
    """The no-L-docs half of `_phase1_decision`: which design input exists.

    One predicate for every entry (`_phase1_producer_identity.
    design_input_mode`), so the front door and phase 2's `step_phase1` agree
    on what counts as design input (FX_STALE_LDOCS)."""
    return _p1id.design_input_mode(project)


def _need_phase1(project: Path, force_skip: bool) -> bool:
    """Back-compat boolean wrapper around `_phase1_decision`."""
    run, _mode = _phase1_decision(project, force_skip)
    return run


def _need_analog(project: Path, force_skip: bool) -> bool:
    if force_skip:
        return False
    for cand in (_pl.analog_dir(project) / "analog_block_list.json",
                  project / "input" / "analog_block_list.json"):
        if cand.is_file():
            return True
    l5 = _pl.generated_docs_dir(project) / "L5_ADI_SPEC.json"
    if l5.is_file():
        try:
            d = json.loads(l5.read_text())
            if d.get("no_analog") is True:
                return False
            blocks = d.get("analog_blocks") or d.get("blocks")
            if isinstance(blocks, list) and any(blocks):
                return True
        except Exception:
            pass
    return False


def _run_phase(label: str, runner: Path, args: List[str],
               env: Optional[Dict[str, str]] = None) -> int:
    print(f"\n{'='*72}\n=== {label} → {runner.name}\n{'='*72}")
    # ORGANIC #588 — pass the re-entrancy env so the spawned standalone
    # phase runner re-enters THIS orchestrator's project lock instead of
    # being refused by it.
    import execution_policy as _execution
    policy_cli_children = {
        "phase1_one_shot_runner.py", "phase2_one_shot_runner.py",
        "design_one_shot_runner.py",
        "phase23_one_shot_runner.py", "phase3_one_shot_runner.py",
        "analog_one_shot_runner.py",
    }
    supports_execution_policy = runner.name in policy_cli_children
    args = _execution.child_arguments(
        args, supports_execution_policy=supports_execution_policy)
    cp = subprocess.run([sys.executable, str(runner), *args], env=env,
                        pass_fds=(_execution.child_pass_fds()
                                   if supports_execution_policy else ()))
    return cp.returncode


def _positive_completed_rung_cap(value: str) -> int:
    """Validate the canonical front-door's explicit bounded-LEC opt-in."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _controller_mixed_step(execution, project: Path, step_id: str,
                           audit_path: Path):
    """Dispatch one mixed row through the already-issued shared Controller.

    ``None`` is the unchanged Default-mode signal; active Registry modes return
    a report-shaped result for the existing fixed sequence and gates.
    """
    result = execution.dispatch_fixed_step(project, step_id)
    if result is None:
        return None
    status = str(result.get("status", "NOT_MEASURED"))
    verdict = ("PASS" if status == "ADOPTED" else
               "FAIL" if status == "FAIL" or "FAIL" in
               (result.get("candidate_statuses") or {}).values() else
               "NOT_READY" if status in ("AWAITING_AI_SELECTION", "NOT_APPLICABLE") else
               "NOT_MEASURED")
    report = {"program": {"M1": "mixed_signal_top_lvs_run",
                          "M2": "mixed_signal_power_domain_run",
                          "M3": "mixed_signal_m3_run",
                          "M4": "mixed_signal_signoff_run"}[step_id],
              "verdict": verdict, "controller_status": status,
              "controller_result": result}
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    return (0 if verdict == "PASS" else 1 if verdict == "FAIL" else 2, report)


def _phase2_runner_argv(project: Path, *, top_name: str, container: str,
                       max_rtl_repair_retries: int,
                       lec_max_completed_rungs: Optional[int],
                       skip_hardware: bool, skip_phase3: bool,
                       skip_analog: bool, entry_step: Optional[str],
                       exit_step: Optional[str],
                       area_receipt: Optional[str] = None,
                       area_run_manifest: Optional[str] = None,
                       phase3_rederive_ic_name: Optional[str] = None
                       ) -> List[str]:
    """Build the canonical Phase-2 argv with explicit opt-ins only.

    The bounded LEC value is absent by default, preserving Step 13's
    unbounded producer behaviour.  This seam is deliberately pure so the
    front-door forwarding contract can be tested without launching a flow.
    """
    result = [str(project), "--top-name", top_name, "--container", container,
              "--max-rtl-repair-retries", str(max_rtl_repair_retries)]
    if lec_max_completed_rungs is not None:
        result += ["--lec-max-completed-rungs", str(lec_max_completed_rungs)]
    if skip_hardware:
        result.append("--skip-hardware")
    if skip_phase3:
        result.append("--skip-phase3")
    if skip_analog:
        result.append("--skip-analog")
    if entry_step:
        result += ["--entry-step", str(entry_step)]
    if exit_step:
        result += ["--exit-step", str(exit_step)]
    if bool(area_receipt) != bool(area_run_manifest):
        raise ValueError("--area-receipt and --area-run-manifest must be supplied together")
    if area_receipt:
        result += ["--area-receipt", str(area_receipt),
                   "--area-run-manifest", str(area_run_manifest)]
    if phase3_rederive_ic_name is not None:
        # Phase 3 will be handed `_resolve_top_name(..., ic_name, ...)`, not
        # `top_name` (see `_phase3_rederives_top`); step 13 needs the same.
        result += ["--phase3-rederives-top-with-ic-name",
                   phase3_rederive_ic_name]
    return result


def _read_report(p: Path) -> Dict[str, Any]:
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"verdict": "FAIL", "error": f"parse failed: {p}"}


#: The ONLY phase verdicts that are a measurement of success. Everything else is
#: not a pass, INCLUDING a token nobody taught this function: the roll-up is
#: fail-closed, because the alternative is what #2523 measured -- a phase verdict
#: outside every branch falling through the bottom of the function into PASS.
_PHASE_PASS = frozenset({"PASS"})

#: Passing, but not clean. Rule 11 forbids collapsing these onto a bare PASS.
#: COVERAGE-INCOMPLETE is v0.3.7 ORGANIC #505: a demoted coverage-only phase1
#: failure in the standalone-design shape. It does NOT fail the run but DOES
#: surface as PASS_WITH_WAIVERS so the overall verdict never hides the
#: documented doc-extraction gap.
_PHASE_PASS_WITH_NOTE = frozenset({"PASS_WITH_WAIVERS", "WAIVED",
                                   "COVERAGE-INCOMPLETE"})

#: The ONE reason a pass-tier row may carry a non-zero rc. R-0915-145.
#:
#: #505's demotion rewrites phase1's verdict to COVERAGE-INCOMPLETE and KEEPS its
#: rc, because a coverage-only phase1 failure always exits 1 -- the rc belongs to
#: the verdict the row had BEFORE the demotion. The roll-up's "claims a pass but
#: exited non-zero" rule is right for an UNDEMOTED row and wrong for this one, and
#: it turned the #505 standalone shape (--skip-phase3, coverage-only phase1) from
#: PASS_WITH_WAIVERS/exit 0 into FAIL/exit 1.
#:
#: DELIBERATELY NOT A GENERAL LAUNDERING PATH: `_roll_up` exempts a row only when
#: the demotion record carries EXACTLY this token, and the only place that mints it
#: is the #505 branch -- `_phase1_failure_is_coverage_only` AND `--skip-phase3`.
#: Anything else that wants an rc forgiven has to come and argue for its own token.
DEMOTION_COVERAGE_ONLY = "phase1_coverage_only_standalone"


def _aggregate(rows: Any,
               completion_audit_verdicts: Optional[List[str]] = None) -> str:
    """The verdict alone, for callers that pass a plain list of phase verdicts.

    THE ORIGINAL CONTRACT, KEPT. This function took `List[str]` and answered a
    `str`, and #505's coverage-axis properties are stated directly against it:

        _aggregate(["COVERAGE-INCOMPLETE", "PASS"]) == "PASS_WITH_WAIVERS"
        _aggregate(["COVERAGE-INCOMPLETE", "FAIL"]) == "FAIL"
        _aggregate(["PASS", "PASS"])               == "PASS"

    Changing the signature under them broke all three with
    `ValueError: too many values to unpack (expected 3)` -- a four-character
    verdict string unpacked as a row. The properties are the point and they are
    older than my change, so the adapter is here rather than in the tests: ONE
    implementation (`_roll_up`), two calling conventions, and no second weaker
    copy of the rule to drift.
    """
    return _roll_up(_as_rows(rows), completion_audit_verdicts)[0]


def _as_rows(rows: Any) -> List[Tuple[str, str, int]]:
    """Accept `["PASS", ...]`, `[(name, verdict, rc), ...]`, or a longer tuple.

    A phase entry that is a bare verdict has no rc to disagree with, so it gets
    rc 0; a longer tuple keeps its first three fields, which is what every caller
    in this file and in `plan` uses.
    """
    out: List[Tuple[str, str, int]] = []
    for i, row in enumerate(rows or []):
        if isinstance(row, str):
            out.append((("phase" + str(i + 1)), row, 0))
            continue
        if isinstance(row, (tuple, list)):
            if len(row) == 1:
                out.append((("phase" + str(i + 1)), str(row[0]), 0))
            elif len(row) == 2:
                out.append((str(row[0]), str(row[1]), 0))
            else:
                try:
                    rc = int(row[2])
                except (TypeError, ValueError):
                    rc = 0
                out.append((str(row[0]), str(row[1]), rc))
            continue
        out.append((("phase" + str(i + 1)), str(row), 0))
    return out


def _roll_up(rows: List[Tuple[str, str, int]],
             completion_audit_verdicts: Optional[List[str]] = None,
             demoted: Optional[Dict[str, Dict[str, Any]]] = None,
             audit_axis: Optional[Dict[str, Any]] = None
             ) -> Tuple[str, List[str]]:
    """Roll the phases up into ONE verdict, and say why it is that verdict.

    THE DEFECT THIS REPLACES, measured on spm run22 (READ-ONLY,
    reports/orchestrator/vibe_ic_one_shot.json, byte-exact):

        phases : phase1 PASS rc=0 | phase2 NOT_MEASURED rc=1
                 phase3 NOT_MEASURED rc=1 | analog SKIPPED | mixed_signal SKIPPED
        verdict: PASS                     <- and the process exited 0

    Three independent holes produced that one line, and each is closed here:

    1. NOT_MEASURED had no branch. The old body tested FAIL, then the
       waiver-ish tier, then `return "PASS"` -- so any token outside those two
       sets rolled up to PASS by falling off the end. Closed by inverting the
       polarity: a verdict is a pass only if it is IN `_PHASE_PASS` /
       `_PHASE_PASS_WITH_NOTE`, so an unknown token is not-measured, never a pass.

    2. `rc` was recorded in the plan and in the report and consulted by nothing.
       A phase that reports PASS while exiting non-zero is a REPORT DISAGREEING
       WITH A PROCESS, which is not a pass either; it fails, and the disclosure
       names both halves.

    3. The completion audit was not in the conjunction. run22's
       reports/audit/phase23_completion_audit.json says `verdict: FAIL` and
       phase3's own orchestrator report carries `completion_audit_verdict: FAIL`
       -- and the front door read neither. A completion audit that FAILS is a
       FAIL here; an ABSENT one is disclosed but not gating, because a
       phase1-only or phase2-only run legitimately has none.

    Returns `(verdict, disclosures)`. A roll-up that moves a verdict without
    saying which phase moved it is the same silence in a different place, so the
    reasons travel into the report and onto stdout.
    """
    fails: List[str] = []
    unmeasured: List[str] = []
    notes: List[str] = []
    #: Things a reader must be told that do NOT move the tier. A disclosure is not
    #: a waiver, and a run with nothing to disclose is a clean PASS.
    disclosed: List[str] = []
    for name, verdict, rc in rows:
        v = str(verdict or "").strip().upper()
        try:
            rc_i = int(rc)
        except (TypeError, ValueError):
            rc_i = 0
        if v == "FAIL":
            fails.append(f"{name} FAIL (rc={rc_i})")
        elif v in _PHASE_PASS or v in _PHASE_PASS_WITH_NOTE:
            _dem = (demoted or {}).get(name) or {}
            _demoted_here = (str(_dem.get("token") or "")
                             == DEMOTION_COVERAGE_ONLY)
            if rc_i != 0 and not _demoted_here:
                fails.append(
                    f"{name} reported {v} but the phase exited rc={rc_i} — a "
                    f"report disagreeing with its own process is not a pass")
            elif rc_i != 0 and _demoted_here:
                # The rc belongs to the verdict this row had BEFORE the demotion.
                notes.append(
                    f"{name} {v} (rc={rc_i} is the pre-demotion "
                    f"{_dem.get('original_verdict', 'FAIL')}; "
                    f"{_dem.get('reason', DEMOTION_COVERAGE_ONLY)})")
            elif v in _PHASE_PASS_WITH_NOTE:
                notes.append(f"{name} {v}")
        else:
            unmeasured.append(
                f"{name} {verdict or 'NO VERDICT'} (rc={rc_i}) — not measured, "
                f"so it cannot be rolled up as passing")

    # THE AUDIT AXIS, AND IT MAY NOT FAIL OPEN. R-0915-145.
    #
    # `if ca == "FAIL"` meant NOT_MEASURED, INSUFFICIENT_DATA, an unparseable
    # value and an ABSENT audit all read as "the axis is satisfied" -- so a phase3
    # run whose --strict completion refresh raised or timed out inside a swallowed
    # try published PASS at exit 0. Only PASS satisfies the axis; PASS_WITH_WAIVERS
    # caps at the waiver tier; FAIL fails; anything else, absence included, is
    # NOT_MEASURED with the reason stated.
    # SCOPED TO THE CALLER THAT ACTUALLY DECIDED THE AXIS. `main` always passes
    # `audit_axis`, computed by `_completion_audit_axis` from THIS invocation, so
    # the fail-closed rule always applies to a real run (pinned by
    # `test_main_always_supplies_the_axis`). A caller that passes no axis is not
    # talking about the completion audit at all -- #505's properties are stated as
    # `_aggregate(["COVERAGE-INCOMPLETE", "PASS"])`, with no audit in the sentence --
    # and for those the phase conjunction alone answers, with the older
    # "a FAIL token gates" behaviour kept for raw verdict lists. Applying the strict
    # axis to them turned every audit-less call into NOT_MEASURED, which is a
    # different claim than the one the caller made.
    if audit_axis is not None:
        axis = audit_axis
    else:
        _raw = [str(v or "").strip().upper()
                for v in (completion_audit_verdicts or [])]
        axis = ({"state": "FAIL", "reason": f"verdict(s) {sorted(set(_raw))}"}
                if any(t == "FAIL" for t in _raw)
                else {"state": "NOT_APPLICABLE", "reason": ""})
    _axis_state = str(axis.get("state") or "NOT_MEASURED").upper()
    _axis_why = str(axis.get("reason") or "")
    if _axis_state == "FAIL":
        fails.append(f"the phase2/3 completion audit says FAIL — {_axis_why}"
                     if _axis_why else "the phase2/3 completion audit says FAIL")
    elif _axis_state == "PASS_WITH_WAIVERS":
        notes.append(f"the phase2/3 completion audit passed with waivers"
                     + (f" — {_axis_why}" if _axis_why else ""))
    elif _axis_state == "NOT_APPLICABLE" and not _axis_why:
        pass            # no axis was in play and nothing to tell the reader
    elif _axis_state == "NOT_APPLICABLE":
        # phase3 did not run in this invocation, so there is no axis to read. SAID
        # OUT LOUD but TIER-NEUTRAL: "no axis" and "a satisfied axis" must never
        # look the same, and a phase1-only run must still be able to be a clean
        # PASS. A disclosure is not a waiver.
        disclosed.append(f"no phase2/3 completion audit axis — {_axis_why}"
                         if _axis_why else "no phase2/3 completion audit axis")
    elif _axis_state != "PASS":
        unmeasured.append(
            f"the phase2/3 completion audit is not a pass ({_axis_state})"
            + (f" — {_axis_why}" if _axis_why else ""))

    if fails:
        return "FAIL", fails + unmeasured + disclosed
    if unmeasured:
        return "NOT_MEASURED", unmeasured + disclosed
    if notes:
        return "PASS_WITH_WAIVERS", notes + disclosed
    return "PASS", disclosed


#: The tokens a completion audit can publish that SATISFY the axis, and nothing
#: else does. R-0915-145: a token this does not know is NOT_MEASURED, never a pass.
_AUDIT_AXIS_PASS = frozenset({"PASS"})
_AUDIT_AXIS_WAIVERS = frozenset({"PASS_WITH_WAIVERS", "WAIVED"})


def _audit_axis_from_verdicts(verdicts: Optional[List[str]]) -> Dict[str, Any]:
    """Collapse raw audit verdict tokens into one axis state, fail-closed.

    FAIL wins, then an unknown/absent token (NOT_MEASURED), then waivers, then
    PASS. `None` and `[]` are NOT a pass: an axis nobody could read is unmeasured.
    """
    toks = [str(v or "").strip().upper() for v in (verdicts or []) if str(v or "").strip()]
    if not toks:
        return {"state": "NOT_MEASURED",
                "reason": "no completion audit verdict could be read"}
    if any(t == "FAIL" for t in toks):
        return {"state": "FAIL", "reason": f"verdict(s) {sorted(set(toks))}"}
    unknown = [t for t in toks
               if t not in _AUDIT_AXIS_PASS and t not in _AUDIT_AXIS_WAIVERS]
    if unknown:
        return {"state": "NOT_MEASURED",
                "reason": f"verdict(s) {sorted(set(unknown))} are not a pass"}
    if any(t in _AUDIT_AXIS_WAIVERS for t in toks):
        return {"state": "PASS_WITH_WAIVERS", "reason": f"verdict(s) {sorted(set(toks))}"}
    return {"state": "PASS", "reason": ""}


#: How much earlier than a phase's start a report may be stamped and still count as
#: that phase's. MEASURED on this host: the filesystem reports mtime in ~64 ms
#: granules, so a file written microseconds AFTER `time.time()` was sampled can
#: carry a stamp microseconds BEFORE it, and a zero-tolerance comparison calls a
#: phase's own fresh report stale. One second is two orders of magnitude below the
#: staleness this is for -- an earlier RUN, minutes or hours back -- so it cannot
#: mask the case being detected.
# ONE value, owned by `_path_layout.FRESHNESS_TOLERANCE_S` — see
# `_path_layout.published_here` for why the predicate moved there. Kept as a
# module name because this file reads it in three places.
_FRESHNESS_TOLERANCE_S = _pl.FRESHNESS_TOLERANCE_S


def _phase_report_path(project: Path, report_name: str) -> Path:
    """Where the phase's report is -- THE ROUTER'S ANSWER, and only that. R-0915-151.

    My round-3 cut of this probed two locations and took the newer, because phase1's runner
    wrote `reports/phase1_one_shot.json` while `_path_layout` categorises the file as
    `orchestrator`. That closed the symptom by adding a FIFTH answer to a question that
    already had four, and it consecrated a location the repo's own
    `reports_subfolder_taxonomy_check` FAILS on -- measured: `1 stray file(s):
    phase1_one_shot.json`. It could also read a STALE file from the other location purely
    because it happened to be newer.

    The producer now resolves through this same router, so there is one definition and this
    function is a single call to it. Nothing here needs to know which phase it is asked
    about, which is the point: a reader that enumerates locations is a reader that goes
    stale the next time a producer moves.
    """
    return _pl.report_path(project, report_name)


def _report_exists(project: Path, report_name: str) -> bool:
    """Is there a `report_name` in this tree at all -- whoever wrote it, whenever?"""
    try:
        return _phase_report_path(project, report_name).is_file()
    except OSError:                                        # pragma: no cover
        return False


def _published_here(project: Path, report_name: str, started_at: float) -> bool:
    """Did THIS INVOCATION publish `report_name`? `exists AND fresh`, in ONE place.

    R-0915-160, third cut. This was spelled inline inside `_row_verdict` and nowhere else, and it
    is the test that decides whether a report on disk is this run's account of itself. A SECOND
    reader then grew that needed the same answer -- the #505 coverage-only demotion, which reads
    the phase-1 record for the sidecar name it carries -- and it did not ask this question at all.

    THE HOLE THAT OPENED (review wkevxl71c, on r8). Invocation A: a fresh pass 1, coverage-only at
    rc 1, its record naming the sidecar it wrote; the front door demotes, correctly. Invocation B
    on the same tree, `--skip-phase3`: the expert second pass dies on an uncaught exception, exits
    1 and writes NO record. `_row_verdict` says FAIL, which is right and halts -- and then the #505
    branch read A's STALE record, found the name still matching the untouched sidecar, saw rc == 1,
    and demoted. Phase 2 ran and the roll-up could publish PASS_WITH_WAIVERS for a run whose phase
    1 had CRASHED. The same shape covers a pass-1 crash before `_forget_any_earlier_coverage_
    sidecar` gets to run. It was unreachable before r8 only because nothing ever named a sidecar.

    So the question has ONE implementation and both readers ask it. A stale record never authorises
    a demotion, whatever it names.
    """
    try:
        path = _phase_report_path(project, report_name)
    except OSError:                                        # pragma: no cover
        return False
    # THE PREDICATE IS NOT SPELLED HERE ANY MORE. `_path_layout.published_here`
    # owns it, because the bounded-window reader asks the same question about
    # paths that are not phase reports. This function is now only the ROUTER
    # step: report name -> path. R-0924-1.
    return _pl.published_here(path, started_at)


def _row_verdict(project: Path, report_name: str, rc: int, started_at: float,
                 phase: str) -> Tuple[str, Optional[str]]:
    """This phase's verdict, or NOT_MEASURED with the reason. R-0915-151.

    A phase that RAN here and left no report written at or after its own start has
    not published a verdict, and `("PASS" if rc == 0 else "FAIL")` invents one. The
    case is real and shipped: phase3's `[SKIP] no usable PDK` returns 0 WITHOUT
    writing a report, so the front door read either a stale `phase3_one_shot.json`
    from an earlier run or a PASS conjured from rc 0 -- for a phase that measured
    nothing at all.
    """
    path = _phase_report_path(project, report_name)
    exists = _report_exists(project, report_name)
    fresh = _published_here(project, report_name, started_at)
    # ONE DECISION, ON (rc, DID THIS INVOCATION PUBLISH A REPORT). R-0915-160, second cut.
    #
    # THE PROCESS IS ALSO A WITNESS, AND WHEN IT FAILED IT IS THE ONLY ONE. My round-3 rule read
    # "rc is an exit status, not a measurement" and returned NOT_MEASURED for every reportless
    # phase. That is right for rc == 0 -- phase3's `[SKIP] no usable PDK` exits 0 without writing
    # anything, and a PASS conjured from that is a claim nobody made. It is WRONG for rc != 0: the
    # process DID tell us something, it told us it failed, and NOT_MEASURED does not halt.
    #
    # MY FIRST CUT PUT THAT ONLY UNDER `if not exists`, AND A REVIEW IS RIGHT THAT IT MISSES THE
    # CASE THAT MATTERS MOST -- the RE-RUN. R-0915-151 moved phase 1's producer onto the routed
    # path this reader reads, so on every re-run a report is already sitting there. A phase-1 crash
    # after the L documents are written -- the oracle-leak `SystemExit(2)`, or a killed expert
    # second pass at rc 137 -- then found `exists` true and `fresh` false, and the stale branch
    # answered NOT_MEASURED while ignoring rc entirely. No halt; phases 2 and 3 ran on
    # oracle-contaminated documents. Exactly the defect the rc!=0 rule exists to close, reached by
    # the other door.
    #
    # So the two facts are decided TOGETHER, and "did this invocation publish a report" is
    # `exists AND fresh` -- a stale file is not this run's account of itself, and nothing below
    # ever reads its verdict.
    #
    # ONE CLASS FOR EVERY NON-ZERO rc, INCLUDING THE STALL (rc 2 UNDETERMINED), and it is FAIL on
    # both paths. It used to be FAIL on a fresh project and NOT_MEASURED on a re-run, which is two
    # answers to one question. FAIL is the right single answer because MEASURED, every non-zero rc
    # a phase runner in this tree returns is a refusal or an error and none is benign: rc 1 is a
    # verdict of FAIL, a NOT_MEASURED aggregate, or an UNCAUGHT EXCEPTION; rc 2 is "not a
    # directory", the announced UNDETERMINED stall, or "REFUSED: canonical Phase-3 admission"; rc 3
    # is the refusal of a second concurrent run on a live project; rc 4 comes WITH a fresh report,
    # so it never reaches here.
    #
    # CORRECTING r7's OWN LIST: it put "an uncaught exception" under rc 2. It is rc 1. Each phase
    # runner exits through `_progress_run.exit_undetermined_on_stall(main)`, which catches
    # `Stalled` ONLY and returns RC_UNDETERMINED for it; anything else propagates and CPython
    # exits 1. Nothing about this rule changes -- both classes are FAIL here -- but a comment that
    # misfiles an exit code is how the next reader builds a wrong rule on top of it. A process that refused to run measured nothing AND said so, which is
    # a failure to produce the phase, not an absence of information about it.
    published_here = exists and fresh
    if not published_here:
        if rc != 0:
            _what = ("wrote no " + report_name) if not exists else (
                "left only a " + report_name + " from an earlier run")
            return "FAIL", (
                f"{phase}'s process exited {rc} and {_what}: this invocation published no "
                f"verdict for {phase}, and its exit status is the only account of itself it "
                f"gave. A failed process with no report OF ITS OWN is a FAIL, not an absence, "
                f"and it halts the run")
        if not exists:
            return "NOT_MEASURED", (
                f"{phase} ran in this invocation, exited 0 and left no {report_name}; rc=0 is "
                f"an exit status, not a measurement")
        return "NOT_MEASURED", (
            f"{phase} exited 0 and its {report_name} predates {phase}'s start in this "
            f"invocation, so that file describes an earlier run and its verdict is not read")
    rep = _read_report(path)
    # A COPY PUBLISHED BEFORE THE PHASE'S OWN FINAL AUDIT IS NOT ITS VERDICT.
    # design_one_shot_runner publishes phase2_one_shot.json once before the
    # final audit (so the audit judges this run's record) and again from its
    # tail. A record still marked `final_audit_pending` means the process never
    # reached the tail -- it raised, stalled or was killed during the audit --
    # and whatever aggregate it carried was never confirmed. Same answer as the
    # reportless rc != 0 case above: FAIL, and it halts.
    if rep.get("final_audit_pending") is True:
        return "FAIL", (
            f"{phase}'s process exited {rc} leaving only the {report_name} it "
            f"published BEFORE its final audit (final_audit_pending): the audit "
            f"and the tail never completed, so this invocation published no "
            f"final verdict for {phase}. A phase whose final audit did not "
            f"finish is a FAIL, not a PASS carried over from before the audit")
    verdict = rep.get("verdict")
    if verdict:
        return str(verdict), None
    return ("PASS" if rc == 0 else "FAIL"), None


def _completion_audit_axis(project: Path, *, phase3_ran: bool,
                           started_at: float) -> Dict[str, Any]:
    """The completion-audit axis for THIS invocation — or none, said out loud.

    THE CANONICAL DOCUMENT, AND NOTHING THAT CARRIES ITS VERDICT. R-0915-151.
    My round-2 version checked freshness on the CARRIER instead of the carried
    verdict, which a review caught: `phase3_one_shot_runner`'s finalize refresh
    swallows a TimeoutExpired (or any exception), and `_derive_headline_verdict`
    then reads `reports/audit/phase23_completion_audit.json` with NO date check and
    copies its verdict into a FRESH `phase3_one_shot.json` as
    `completion_audit_verdict`. So on a re-run whose refresh failed, the OLD run's
    audit PASS arrived at the front door dated today: my reader put the audit FILE in
    `ignored` and then accepted the SAME verdict from the carrier, axis PASS, exit 0
    -- precisely the swallowed-refresh case the rework claimed to close. The mirror
    is worse: a stale FAIL gating a good run.

    So a carrier is a POINTER, never a source. The axis reads the canonical audit
    document itself, and accepts it only when:

      * phase3 ran in THIS invocation (otherwise there is no axis at all), AND
      * the document was written at or after PHASE 3's START in this invocation --
        not merely after the run started, because the audit is phase3's to refresh,
        AND
      * the document says it judged the WHOLE FLOW.

    THAT LAST CHECK IS WHAT 77 MADE POSSIBLE. `flow_compliance_check` stamped every
    receipt `phase: "all"` regardless of `--stage`, so "who wrote this audit, over
    what population" was unanswerable; a phase-2-scoped audit, or
    `emit_final_summary`'s pre-Step-29 snapshot, was accepted as the phase2/3 axis.
    With R-0915-147 the audit carries `scope.whole_flow`, and a scoped pass no longer
    writes this path at all (R-0915-150). An audit with NO scope block predates that
    work, so its population cannot be established from the document: it is accepted
    only on the weaker `phase == "all"` signal, and WHICH signal was used is
    disclosed, because a weak signal read silently is the same mistake again.
    """
    if not phase3_ran:
        return {"state": "NOT_APPLICABLE",
                "reason": "phase3 did not run in this invocation, so this run has "
                          "no completion-audit axis; an earlier run's audit is not "
                          "evidence about this one",
                "sources": [], "ignored": [], "pointers": []}
    # Carriers are recorded for a reader and never consulted for the verdict.
    pointers: List[Dict[str, Any]] = []
    for name in ("phase2_one_shot.json", "phase3_one_shot.json",
                 "phase23_one_shot.json"):
        rep = _read_report(_pl.report_path(project, name))
        if rep.get("completion_audit_verdict"):
            pointers.append({"path": f"reports/orchestrator/{name}",
                             "carries": str(rep["completion_audit_verdict"]),
                             "used_as_evidence": False})

    audit = _pl.report_path(project, "phase23_completion_audit.json")
    try:
        fresh = audit.is_file() and (audit.stat().st_mtime
                                     + _FRESHNESS_TOLERANCE_S >= started_at)
    except OSError:                                        # pragma: no cover
        fresh = False
    if not audit.is_file():
        return {"state": "NOT_MEASURED",
                "reason": ("phase3 ran in this invocation and left no completion "
                           "audit at reports/audit/phase23_completion_audit.json"),
                "sources": [], "ignored": [], "pointers": pointers}
    if not fresh:
        return {"state": "NOT_MEASURED",
                "reason": ("the completion audit predates phase3's start in this "
                           "invocation, so it describes an earlier run -- a carrier "
                           "repeating its verdict in a fresh report does not make it "
                           "this run's measurement"),
                "sources": [],
                "ignored": ["reports/audit/phase23_completion_audit.json"],
                "pointers": pointers}
    doc = _read_report(audit)
    # THE SAME PREDICATE THE OTHER READERS USE, not a fourth copy of it. R-0915-150.
    #
    # `_audit_scope.audit_scope_is_whole_flow` is the one definition of "did this audit
    # judge the whole flow", and `benchmark_evidence_publish`, `phase3_one_shot_runner`
    # and the FPGA pre-burn guard all refuse a scoped audit through it. This reader had
    # the same rule written out a second time -- same answer today, and exactly the shape
    # that goes stale the first time the rule moves. A front door that disagreed with the
    # three readers beneath it about what the audit judged would be the worst place for
    # that divergence to live.
    #
    # `signal` is still disclosed, because the legacy branch (`phase == "all"` on a
    # document with no scope block, written before R-0915-147) is a WEAKER answer and a
    # weak signal read silently is the mistake this whole axis exists to correct. The
    # constant already SAYS that in words, so it is published verbatim rather than
    # re-worded here -- two spellings of one disclosure is how they drift apart.
    _whole, signal, _why = _audit_scope.audit_scope_is_whole_flow(doc)
    if not _whole:
        return {"state": "NOT_MEASURED",
                "reason": (f"the completion audit is not this run's whole-flow verdict: "
                           f"{_why}"),
                "sources": [], "ignored": [], "pointers": pointers,
                "scope_signal": signal}
    verdict = doc.get("verdict")
    if not verdict:
        return {"state": "NOT_MEASURED",
                "reason": "the completion audit carries no verdict",
                "sources": [], "ignored": [], "pointers": pointers,
                "scope_signal": signal}
    axis = _audit_axis_from_verdicts([str(verdict)])
    axis["sources"] = [{"path": "reports/audit/phase23_completion_audit.json",
                        "verdict": str(verdict)}]
    axis["ignored"] = []
    axis["pointers"] = pointers
    axis["scope_signal"] = signal
    return axis


def _completion_audit_verdicts(project: Path) -> List[str]:
    """Kept for callers that only want the raw tokens (tests, and the report).

    THE AXIS IS `_completion_audit_axis`, which is what the roll-up consumes: this
    helper cannot know whether phase3 ran or when this invocation started, and
    answering without those two facts is what produced the false FAIL on a
    `--skip-phase3` run.
    """
    out: List[str] = []
    audit = _pl.report_path(project, "phase23_completion_audit.json")
    doc = _read_report(audit)
    if doc.get("verdict"):
        out.append(str(doc["verdict"]))
    for name in ("phase2_one_shot.json", "phase3_one_shot.json",
                 "phase23_one_shot.json"):
        rep = _read_report(_pl.report_path(project, name))
        if rep.get("completion_audit_verdict"):
            out.append(str(rep["completion_audit_verdict"]))
    return out


def _phase1_failure_is_coverage_only(project: Path) -> Tuple[bool, dict]:
    """v0.3.7 — ORGANIC #505. Read the phase1 exit-reason sidecar
    (`_path_layout.COVERAGE_ONLY_SIDECAR_REL`, written by
    phase1_doc_one_shot_runner) and report whether phase1's FAIL is
    attributable SOLELY to doc-extraction coverage (orthogonal to the RTL
    deliverable). Returns ``(coverage_only, reason_dict)``; ``(False, {})``
    when the sidecar is absent/unreadable (e.g. prompt-mode phase1 that
    never wrote one) so the default halting behaviour is preserved."""
    f = _pl.coverage_only_sidecar_path(project)
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, {}
    return bool(d.get("coverage_only_failure")), d


_TOP_NAME_DEFAULT = "chip_top"
# An SV lifetime qualifier (`module automatic X`) is not the module's name.
_MODULE_DECL_RE = re.compile(
    r"(?m)^\s*module\s+(?:(?:automatic|static)\s+)?([A-Za-z_]\w*)")
_VERILOG_KW = {
    "module", "endmodule", "begin", "end", "if", "else", "case", "endcase",
    "for", "while", "assign", "always", "initial", "wire", "reg", "logic",
    "input", "output", "inout", "parameter", "localparam", "generate",
    "endgenerate", "function", "endfunction", "task", "endtask", "posedge",
    "negedge", "genvar", "integer", "real", "signed", "unsigned",
}


def _sanitize_module(name: str) -> str:
    """A design/ic name -> a legal Verilog module identifier (best effort)."""
    s = re.sub(r"\W", "_", str(name or "").strip())
    return s if re.match(r"^[A-Za-z_]\w*$", s or "") else ""


def _scan_rtl_modules(rtl_dir: Path) -> Tuple[set, set]:
    """Return (declared_modules, instantiated_module_names) for the source RTL.

    Instantiation detection is conservative: a declared module name D is 'used'
    if the corpus contains `D [#(...)] <instname> (` somewhere — which the
    module's own `module D (` declaration never matches (D there is followed by
    `(` or the port list, not by an instance identifier). Deterministic; no LLM."""
    if not rtl_dir.is_dir():
        return set(), set()
    return _scan_rtl_files([f for pat in ("*.v", "*.sv")
                            for f in sorted(rtl_dir.glob(pat))])


def _scan_rtl_files(files: List[Path]) -> Tuple[set, set]:
    """`_scan_rtl_modules` over an explicit file list.

    Both scans read CODE: comments and strings are blanked first
    (`_hdl_code_text`, offset-preserving), so `// This module ...` is neither a
    declaration nor half of an instantiation.

    An instance name may carry an ARRAY range (`adder u[N-1:0] (`): a module
    instantiated only that way is still instantiated, not a second root.

    A module's own PARAMETERISED header (`module X #(...) (...);`) is not an
    instantiation of X: from that header a lazy parameter group ran into the
    body until any `) <word> (` -- e.g. `negedge rst) if (`. So every
    declaration header is replaced by `;` before the instance search: a
    statement boundary, never a word the search could read as an instance
    name. (A bare `module` keyword left in its place was one: after
    `endmodule : top` or `endmodule // top` it read as `top module (`.)"""
    import _hdl_code_text as _hct
    decls: set = set()
    text_parts: List[str] = []
    for f in files:
        try:
            t = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        code = _hct.strip_hdl_comments_and_strings(t)
        text_parts.append(code)
        decls.update(_MODULE_DECL_RE.findall(code))
    corpus = "\n".join(text_parts)
    corpus = re.sub(
        r"\b(?:macro)?module\s+(?:(?:automatic|static)\s+)?[A-Za-z_]\w*",
        ";", corpus)
    insts: set = set()
    for d in decls:
        inst_re = re.compile(
            r"(?<![\w.])" + re.escape(d) + r"\s+(?:#\s*\([\s\S]*?\)\s*)?"
            r"[A-Za-z_]\w*\s*(?:\[[^\]\[;]*\]\s*)?\(")
        if inst_re.search(corpus):
            insts.add(d)
    return decls, insts


def _project_rel(project: Path, f: Path) -> str:
    try:
        return f.relative_to(project).as_posix()
    except ValueError:
        return str(f)


def _supplied_build_rtl(project: Path) -> List[Path]:
    """The design sources the design's INPUT supplies (.v/.sv), or [].

    The same definition phase 2's consume step stages from
    (`reused_ip_rtl_consume.discover_provided_build_rtl`). A probe failure
    returns [], i.e. the behaviour before this reader existed."""
    try:
        import reused_ip_rtl_consume as _consume
        return [f for f in _consume.discover_provided_build_rtl(project)
                if f.suffix in (".v", ".sv")]
    except Exception:  # noqa: BLE001
        return []


def _supplied_source_bound_top(project: Path, supplied: List[Path],
                               decls: set) -> Optional[Tuple[str, str]]:
    """Find a source-bound wrapper in supplied RTL before it is staged.

    This narrow repair applies only before L9 exists.  If either canonical L9
    path is present, preserve the existing explicit-top behavior and never give
    an old or stale declaration new override authority.

    With no L9 emitted, the conventional ``chip_top`` wrapper is accepted only
    when its exact source file declares ``chip_top``, the module is a graph
    root, and that module body instantiates another module declared in the same
    supplied corpus.  A leaf named ``chip_top`` is not enough evidence.
    """
    candidates = (
        _pl.generated_docs_dir(project) / "L9_INTEGRATION_SPEC.json",
        project / "generated_docs" / "L9_INTEGRATION_SPEC.json",
    )
    if any(path.exists() for path in candidates):
        # L9 freshness is owned by the existing Phase-1 stale-document logic;
        # this pre-L9 repair must not interpret or elevate an old declaration.
        return None

    all_insts = _scan_rtl_files(supplied)[1]
    import _hdl_code_text as _hct
    for path in supplied:
        if path.name not in (f"{_TOP_NAME_DEFAULT}.v",
                             f"{_TOP_NAME_DEFAULT}.sv"):
            continue
        file_decls, _ = _scan_rtl_files([path])
        if (_TOP_NAME_DEFAULT not in file_decls
                or _TOP_NAME_DEFAULT in all_insts):
            continue
        try:
            code = _hct.strip_hdl_comments_and_strings(
                path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        module_match = re.search(
            r"\bmodule\s+(?:(?:automatic|static)\s+)?"
            + re.escape(_TOP_NAME_DEFAULT)
            + r"\b(?P<body>.*?)\bendmodule\b", code, re.S)
        if module_match is None:
            continue
        child_names = sorted(decls - {_TOP_NAME_DEFAULT})
        has_child = any(re.search(
            r"(?<![\w.])" + re.escape(child)
            + r"\s+(?:#\s*\([\s\S]*?\)\s*)?"
            + r"[A-Za-z_]\w*\s*(?:\[[^\]\[;]*\]\s*)?\(",
            module_match.group("body"))
            for child in child_names)
        if has_child:
            return _TOP_NAME_DEFAULT, (
                f"supplied RTL structurally binds source wrapper top="
                f"'{_TOP_NAME_DEFAULT}' from {_project_rel(project, path)} "
                f"(graph root with child instance; L9 not yet emitted)")
    return None


def _resolve_top_name(project: Path, ic_name: str, top_name: str,
                      explicit: bool) -> Tuple[str, str]:
    """Deterministically pick the phase-3 top module.

    The historical default `--top-name chip_top` is wrong for a standalone
    block whose sole top is the design itself (e.g. spm), and forwarding it
    verbatim made phase-3 synth fail with "'chip_top' is not a valid top-level
    module". When --top-name was NOT given, derive it from the (now-existing)
    source RTL: keep chip_top if a chip_top module actually exists (real
    full-chip wrapper); else prefer the --ic-name module; else the sole root
    module (declared, never instantiated).

    An EXPLICIT --top-name wins -- but only when that module actually EXISTS in
    the staged RTL. A caller that passes the PROJECT/repo name rather than a
    module name (e.g. `--top-name caravel_user_project`, whose real top module
    is `user_project_wrapper`) otherwise had the bogus name forwarded verbatim
    into yosys, which is precisely the "'X' is not a valid top-level module"
    hard synth failure this function exists to prevent. When the explicit name
    is provably absent from the declared modules, fall through to the same
    deterministic derivation and record the override in the note so the
    substitution is auditable rather than silent. Absence must be PROVEN: if no
    RTL could be scanned we cannot know the name is wrong, so the explicit name
    is kept. (This resolution runs AFTER phase 1 has staged/produced the RTL and
    BEFORE phase 2, so the declared-module set is complete and authoritative --
    nothing creates a new top module in between.) Returns (top, note)."""
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    decls, insts = _scan_rtl_modules(rtl_dir)
    supplied_note = ""
    if not decls:
        # A design that SUPPLIES its RTL has it under input/ until phase 2's
        # consume step stages it, and this runs BEFORE phase 2. Reading only
        # rtl/ saw nothing, kept the `chip_top` default, and handed every
        # phase-2 step a module that does not exist in the design.
        supplied = _supplied_build_rtl(project)
        decls, insts = _scan_rtl_files(supplied)
        if explicit:
            # A front-door invocation commonly forwards ``--ic-name`` as an
            # explicit top.  If the supplied corpus proves that this is a
            # stale project-name placeholder, bind the real wrapper only while
            # L9 is absent.  Once L9 exists, preserve the current explicit-top
            # behavior; freshness is owned by the existing Phase-1 path.
            source_top = _supplied_source_bound_top(project, supplied, decls)
            if source_top is not None:
                selected, source_note = source_top
                if (selected != top_name
                        and top_name == _sanitize_module(ic_name)):
                    source_label = ("L9 top" if source_note.startswith("L9 ")
                                    else "supplied top")
                    return selected, (f"explicit --top-name='{top_name}' conflicts "
                                      f"with {source_note}; using the source-bound "
                                      f"{source_label}")
            return top_name, ""
        if decls:
            supplied_note = (
                "derived from supplied input RTL (not yet staged): "
                + ", ".join(_project_rel(project, f) for f in supplied))
    override_note = ""
    if explicit:
        if not decls or top_name in decls:
            # Either we cannot prove the name wrong, or it is genuinely there.
            return top_name, ""
        # Explicit name is provably NOT a module in this design -> derive, but
        # say so loudly; forwarding it can only produce a hard synth failure.
        override_note = (
            f"explicit --top-name='{top_name}' is not a module in the staged "
            f"RTL (declared: {', '.join(sorted(decls))}) -- deriving the top "
            f"instead")
    if not decls:
        return top_name, ""  # nothing to derive from; keep the default

    def _note(msg: str) -> str:
        msg = f"{msg}; {supplied_note}" if supplied_note else msg
        return f"{override_note}; {msg}" if override_note else msg

    if _TOP_NAME_DEFAULT in decls:
        # a genuine wrapper exists → honor it
        return _TOP_NAME_DEFAULT, (_note(f"top='{_TOP_NAME_DEFAULT}'")
                                   if override_note or supplied_note else "")
    roots = sorted(m for m in decls if m not in insts)
    ic = _sanitize_module(ic_name)
    if ic and ic in decls:
        return ic, _note(
            f"auto-derived top='{ic}' from --ic-name (no chip_top module)")
    if len(roots) == 1:
        return roots[0], _note(f"auto-derived top='{roots[0]}' (sole RTL root; "
                               f"no chip_top module)")
    # Ambiguous multi-root → preserve current behaviour. If we got here from an
    # explicit-but-absent name we CANNOT pick for the caller; return it
    # unchanged so synth fails loudly and honestly rather than on a guess.
    return top_name, override_note



def _phase3_rederives_top(flow_top: str, explicit: bool) -> bool:
    """Does the front door re-derive phase 3's top after phase 2?

    Only for the placeholder default the user did not type: phase 2 of a
    from-documents run writes the RTL, so the flow-level resolution above
    could not see it. Known BEFORE phase 2, which is why phase 2 is told
    (``--phase3-rederives-top-with-ic-name``): its step 13 must prove the
    netlist of the top phase 3 will build, not the placeholder's."""
    return flow_top == _TOP_NAME_DEFAULT and not explicit


def _line_buffer_own_stream() -> None:
    """Make this orchestrator's own prints land in the ORDER THEY HAPPENED.

    Python block-buffers stdout when it is not a tty, so under the redirect
    every real run uses (`> run.log 2>&1`) the parent's phase banners sat in a
    4 KB buffer until exit while its children — which inherit the same fd and
    write to it directly — flushed as they went. The file therefore recorded
    ALL child output first and ALL banners last.

    MEASURED (sha256 x sky130A, run1.log): `=== PHASE 2 ===` was followed
    immediately by `DONE` with zero phase-2 output between them, which reads as
    "phase 2 died instantly". Phase 2 had in fact run its full 3-retry RTL repair
    loop — at lines 109-131, ABOVE its own banner. Reproduced from first
    principles with a 6-line parent/child script: banners emerge in order with
    line buffering on and after everything with it off.

    Nothing about the log is wrong except the order, which is the part a reader
    uses to attribute a failure to a phase. Set once here rather than as
    `flush=True` on each of the print sites, so a print added later cannot
    silently reintroduce it.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)
        except Exception:
            pass          # a stream that cannot be reconfigured keeps its own


#: The runners THIS orchestrator can start a run inside. A step owned by any
#: other runner is refused by `--entry-step` (see the guard in main()).
#: Phase 3 additionally requires an exit step to bound its dispatch.
ENTRY_STEP_ENTERABLE_RUNNERS = ("phase1_one_shot_runner",
                                "design_one_shot_runner",
                                "phase3_one_shot_runner")


def main() -> int:
    """Canonical CLI contract: fail-closed authority refusal is always rc=2."""
    from execution_modes import Refusal
    try:
        return _main()
    except Refusal as exc:
        print(f'REFUSED: {exc}', file=sys.stderr)
        return 2


def _main() -> int:
    _line_buffer_own_stream()
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    p.add_argument("--top-name", default=_TOP_NAME_DEFAULT)
    p.add_argument("--container", default=_pin.default_container_name())
    p.add_argument("--area-receipt", default=None,
                   help="Explicit producer area receipt passed to Phase 3")
    p.add_argument("--area-run-manifest", default=None,
                   help="Explicit current-run manifest paired with --area-receipt")
    # `--container` names a CONTAINER (every step is `docker exec <container>`),
    # so nothing here ever asked which IMAGE that container was started from.
    # The identity is now RECORDED unconditionally (see the capture below) and
    # ENFORCED only when the operator asks, because a run with no container at
    # all is legitimate (e.g. --skip-phase3) and must not start failing.
    p.add_argument("--require-image", default=None,
                   help="image ref or id the --container MUST be running. "
                        "Omitted: the image identity is still RECORDED to "
                        "reports/container_image.json, just not enforced.")
    p.add_argument("--max-rtl-repair-retries", type=int, default=3)
    p.add_argument("--lec-max-completed-rungs",
                   type=_positive_completed_rung_cap, default=None,
                   help="OPT-IN: forward this positive completed-checkpoint "
                        "rung cap only to Phase-2 Step 13 LEC. Omitted keeps "
                        "LEC unbounded; this is not a wall-clock timeout.")
    p.add_argument("--skip-hardware", action="store_true")
    p.add_argument("--entry-step", default=None,
                   help="START the flow at this canonical step id. The step "
                        "decides WHICH runner owns the entry, and THIS "
                        "orchestrator can be entered at D1 for Phase 1, "
                        "2/4/1/9/11 for Phase 2, and Phase-3 (15/31/37) "
                        "with --exit-step for a bounded backend window. "
                        "Analog (A1..A9) steps are owned by "
                        "analog_one_shot_runner and are REFUSED here: run "
                        "that runner directly. Only a step that HEADS a "
                        "dispatch span is enterable; a mid-span step is "
                        "refused rather than approximated. With a window, rc reflects the DISPATCHED STEPS ONLY; whole-flow verdicts come from --refresh-only or an unbounded run.")
    p.add_argument("--exit-step", default=None,
                   help="STOP dispatch after this canonical step id. Phase-2 "
                        "exits are forwarded to the phase2 runner; Phase-3 "
                        "entries require an exit and are forwarded to the "
                        "phase3 runner as a bounded backend window. Sites "
                        "wholly past the exit are SKIPPED-BY-EXIT (the site "
                        "holding the exit still runs in full). Omitted: "
                        "unbounded behavior. With a window, rc reflects the "
                        "DISPATCHED STEPS ONLY; whole-flow verdicts come from "
                        "--refresh-only or an unbounded run.")
    p.add_argument("--skip-phase1", action="store_true")
    p.add_argument("--route", choices=("ic", "ip"),
                   help="Owner-stated delivery route: ic=DIE, ip=HARDMACRO. "
                        "Required unless already owner-declared in this project.")
    p.add_argument("--skip-analog", action="store_true")
    p.add_argument("--skip-phase3", action="store_true")
    p.add_argument("--die-um", default="auto",
                   help="die size WxH in µm, or 'auto' (default) to size the "
                        "die from the synth cell count + PDK site area + target "
                        "util so a small design is not stranded at a "
                        "route-plateauing low utilization on a fixed 1500x1500 die")
    p.add_argument("--util", type=float, default=0.4)
    p.add_argument("--pdk", default="auto")
    # vibe-ic 87ad3dfdf — THE REFUSAL NAMED A FLAG THIS ENTRY POINT COULD NOT
    # EXPRESS. `--allow-pdk-target-mismatch` existed only on
    # phase3_one_shot_runner. This runner is the canonical front door
    # (`/vibe-ic-all`) and forwarded ONLY --allow-oss-pdk-fallback, so a
    # DELIBERATE cross-PDK port was unreachable from it: the user hit
    # "declared PDK != resolved PDK, REFUSED", read a message telling them to
    # pass a flag, and had no way to pass it without abandoning the front door
    # and driving phase 3 by hand.
    #
    # The refusal itself is CORRECT and stays: measured on sha256 x gf180mcuD,
    # L19 derives pdk_target=sky130 from L1, and L7's 9-corner sign-off table
    # plus L9's SDC are sky130_fd_sc_hd-specific — so gf180 numbers cannot
    # claim that sign-off. (Control: spm's L1 names gf180mcuD as a SECOND
    # target with its own library, period and utilisation, which is why
    # spm x gf180mcuD converges legitimately.) What was missing was the
    # documented way to SAY "I know, measure it anyway and disclose it".
    p.add_argument("--allow-pdk-target-mismatch", action="store_true",
                   help="Pass through to phase3: acknowledge IN WRITING that "
                        "the PDK being measured is NOT the one the design's "
                        "own L-docs declare. The run is then a DISCLOSED "
                        "cross-PDK port — it may not claim the design's L7 "
                        "sign-off, whose corners are declared per-PDK.")
    p.add_argument("--allow-oss-pdk-fallback", action="store_true",
                   help="Pass through to phase3: acknowledge an "
                        "open-source in-container PDK fallback even "
                        "though a commercial PDK is configured for "
                        "this host. Without it a silent OSS fallback "
                        "is REFUSED (it would emit VOID sign-off "
                        "reports).")
    p.add_argument("--ic-name", default="UNNAMED_CHIP")
    p.add_argument("--dashboard", dest="dashboard", action="store_true",
                   default=True,
                   help="(DEFAULT ON) Auto-launch the execution dashboard for "
                        "this project — BOTH front-ends: a background read-only "
                        "WEB observer (open in a browser) plus an inline CLI "
                        "step-map snapshot + the live-attach command. Every "
                        "Phase 1/2/3 + Analog/Mixed/Mfg step lights up as it "
                        "runs; the web daemon survives the run so the final "
                        "state stays viewable. Disable with --no-dashboard.")
    p.add_argument("--no-dashboard", dest="dashboard", action="store_false",
                   help="Disable the auto-launched CLI + web dashboard entirely.")
    p.add_argument("--dashboard-port", type=int, default=8787,
                   help="Port for --dashboard (default 8787).")
    p.add_argument("--dashboard-host", default="127.0.0.1",
                   help="Bind host for --dashboard (default 127.0.0.1; use "
                        "0.0.0.0 to reach it from another machine on the LAN).")
    p.add_argument("--dashboard-full", action="store_true",
                   help="Run --dashboard in AUTHORITATIVE mode (each refresh "
                        "runs the flow_compliance gate matrix for true "
                        "PASS/SKIP/WAIVED verdicts; TTL-cached ~15s). Slower "
                        "than the default fast file-stat view.")
    import execution_policy as _execution
    p.add_argument('--route-authority-only', action='store_true', help='Verify the live route and emit its receipt without running producers.')
    p.add_argument('--receipt-channel-fd', type=int, help=argparse.SUPPRESS)
    _execution.add_arguments(p)
    args = p.parse_args()
    if bool(args.area_receipt) != bool(args.area_run_manifest):
        p.error("--area-receipt and --area-run-manifest must be supplied together")
    # The owner answer is recorded/validated before checking execution authority.
    # Imported API calls may express a route, but cannot start any producer.
    project = args.project.resolve()
    if not project.is_dir():
        print(f'ERROR: not a directory: {project}', file=sys.stderr)
        return 2
    route_refusal = _delivery_route.admit(project, args.route)
    if route_refusal:
        print(_delivery_route.refusal_message(route_refusal), file=sys.stderr)
        return 2
    if 'VIBEIC_EXECUTION_CAP_FD' not in os.environ:
        from execution_modes import Refusal
        raise Refusal('REQUEST_CAPABILITY_REQUIRED', 'enter through the canonical CLI')
    execution_policy_value = _configure_execution_policy(args)


    if args.route_authority_only:
        from execution_authority import consume
        issued = consume()
        if args.receipt_channel_fd is not None:
            import socket, struct
            channel = socket.socket(fileno=args.receipt_channel_fd)
            packet = json.dumps(dict(issued, socket=os.environ['VIBEIC_EXECUTION_AUTH_SOCKET'])).encode() + b'\n'
            sent = channel.sendmsg([packet], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                              struct.pack('i', int(os.environ['VIBEIC_EXECUTION_CAP_FD'])))])
            channel.sendall(packet[sent:])
            channel.recv(1)
        else:
            print(json.dumps(issued, sort_keys=True))
        return 0

    # Was --top-name given on the command line, or is it the historical default?
    # (argparse cannot tell a default from an explicit same-value pass; inspect
    # argv so we only AUTO-derive when the user OMITTED the flag.)
    top_name_explicit = any(
        a == "--top-name" or a.startswith("--top-name=") for a in sys.argv[1:]
    )

    project = args.project.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    # ---------------- Single-driver project lock (ORGANIC #498) ----------
    # Refuse a second concurrent invocation on a project already being
    # driven by a LIVE runner; clean a stale lock left by a dead one.
    # Acquired BEFORE any reports/manifests/provenance are written so two
    # racing orchestrators can never co-write the same reports/ tree.
    lock = _runner_lock.acquire_or_reenter(project, "vibe_ic_one_shot_runner")
    if lock is None:
        return 3
    # The route is an owner decision. Refuse before image capture, dashboard,
    # Phase 1, or any other producer can create a misleading partial run.
    route_refusal = _delivery_route.admit(project, args.route)
    if route_refusal:
        print(_delivery_route.refusal_message(route_refusal), file=sys.stderr)
        lock.release()
        return 2
    from execution_authority import consume
    execution_route = consume()['route']
    # ---------------- Container IMAGE provenance (capture always) ----------
    # Every containerised step downstream is dispatched as
    # `docker exec <container> ...`, so `--container` selects a CONTAINER and
    # nothing asked which IMAGE it was started from. Two measured consequences:
    # a long-running container built from an OLDER image silently produces
    # every tool version and every sign-off number with nothing in the run
    # record naming it; and an IMAGE ref passed where a container name belongs
    # matches no container, so each step falls through to its
    # container-unavailable branch and the run reports a downstream TOOL
    # failure instead of the real cause.
    #
    # RECORD unconditionally — that is what makes a published number
    # attributable to a toolchain afterwards. ENFORCE only when the operator
    # passed --require-image: a run legitimately without a container (Phase-1
    # only, --skip-phase3) must not start failing here.
    _img_rec = _capture_container_image(project, args.container,
                                        args.require_image)
    # #588 — env passed to every delegated standalone phase runner so it
    # re-enters this orchestrator's lock instead of being refused by it.
    #
    # SNAPSHOTTED AFTER the image capture, and the order is load-bearing:
    # `child_env` copies `os.environ`, and the capture above is what writes
    # VIBEIC_EDA_IMAGE into it. Built one line earlier (where it used to be),
    # the snapshot predates that write, every delegated phase runner inherits
    # an env without it, and the propagation silently does nothing — MEASURED:
    # `reports/container_image.json` recorded
    # `propagated_via: VIBEIC_EDA_IMAGE` while the DFT step in the delegated
    # phase-2 runner still reported `image_used:
    # hpretl/iic-osic-tools:latest`. A propagation that the record claims and
    # the children never see is worse than none, because the record then
    # attests to something untrue.
    _phase_env = _runner_lock.child_env(project, held_lock=lock)
    # `--require-image` is a DEMAND, so anything short of PASS fails it — not
    # only MISMATCH. An earlier revision halted on MISMATCH alone, which left
    # the most common way the demand goes unmet wide open: when the named
    # container does not exist the verdict is FAIL (`status=not_found`), not
    # MISMATCH, so the run fell through to the advisory below and CONTINUED —
    # on whatever tools happened to be on the host PATH. The operator gets a
    # reports/container_image.json recording FAIL, a one-line ⚠, and a full
    # set of step verdicts measured against an unpinned toolchain. Measured:
    # a run pinned to an image whose yosys is 0.67+ completed phase 2 on a
    # host yosys 0.33 and reported PASS for synthesis.
    #
    # SKIP (docker absent) is refused for the same reason: the operator asked
    # for a specific image and this run cannot show it got one.
    if args.require_image and _img_rec.get("verdict") != "PASS":
        print(f"ERROR: --require-image {args.require_image!r} not satisfied: "
              f"{_img_rec.get('verdict')} — {_img_rec.get('reason', '')}\n"
              f"  refusing to continue: every step verdict from here would be "
              f"measured against a toolchain this run cannot attest to.\n"
              f"  fix: start the container from the required image, or drop "
              f"--require-image to run unpinned (identity is still RECORDED "
              f"to reports/container_image.json).",
              file=sys.stderr)
        lock.release()
        return 2
    if _img_rec.get("verdict") not in ("PASS", None):
        advisory = (f"container image identity: {_img_rec.get('verdict')} — "
                    f"{_img_rec.get('reason', '')}")
        print(f"⚠ {advisory}")

    # ---------------- Live dashboard (CLI + web, DEFAULT ON) ----------------
    # Every run gets BOTH dashboard front-ends by default (opt out with
    # --no-dashboard): a detached read-only WEB daemon (browser) and a CLI view
    # (an inline step-map snapshot now + the live-attach command for a
    # full-screen CLI dashboard in a second terminal). Same read-only data
    # source; neither ever mutates the flow.
    dash_pid = None
    if args.dashboard:
        _reachable = _reachable_host(args.dashboard_host)
        _mode = "authoritative/--full" if args.dashboard_full else "live/fast"
        # v1.3.83 — the daemon retries ports when a stale daemon holds the
        # default and RECORDS its actually-bound URL under reports/; drop any
        # stale record, then print the recorded truth, never the request
        # (before this, a stale daemon on the default port made the printed
        # URL silently serve a PREVIOUS run's dashboard).
        _dash_url_f = project / "reports" / "dashboard_web.url"
        try:
            _dash_url_f.unlink()
        except Exception:
            pass
        dash_pid = _launch_dashboard(project, args.dashboard_host,
                                     args.dashboard_port,
                                     full=args.dashboard_full)
        _dash = PROGRAMS_DIR / "flow_dashboard.py"
        print("─" * 64)
        if dash_pid:
            _dash_port = str(args.dashboard_port)
            for _ in range(30):          # ≤3 s for the daemon to bind+record
                if _dash_url_f.is_file():
                    _rec = _dash_url_f.read_text().strip()
                    if _rec.rsplit(":", 1)[-1].isdigit():
                        _dash_port = _rec.rsplit(":", 1)[-1]
                    break
                time.sleep(0.1)
            _busy_note = ("" if _dash_port == str(args.dashboard_port) else
                          f"; port {args.dashboard_port} busy → {_dash_port}")
            print(f"📊 WEB dashboard → http://{_reachable}:"
                  f"{_dash_port}   ({_mode} · read-only · pid {dash_pid}"
                  f"{_busy_note})")
            print(f"                   stop with: kill {dash_pid}")
        else:
            print("⚠ web dashboard could not launch (continuing without it)")
        print(f"🖥  CLI dashboard → python3 {_dash} {project}"
              f"   (live; run in a 2nd terminal)")
        _snap = _cli_snapshot(project)
        if _snap.strip():
            print(_snap.rstrip())
        print("   (disable both front-ends with --no-dashboard)")
        print("─" * 64)

    t0 = time.time()
    plan: List[Tuple[str, str, int]] = []   # (phase, verdict, rc)
    #: name -> the demotion record that explains a pass-tier row's non-zero rc.
    #: Only the #505 branch writes here; see DEMOTION_COVERAGE_ONLY.
    _demoted: Dict[str, Dict[str, Any]] = {}
    #: Did phase3 RUN in THIS invocation? The completion-audit axis exists only
    #: then, and reading an earlier run's audit is not a measurement of this one.
    _phase3_ran = False
    #: When each phase STARTED here. A phase's report counts as this run's only if
    #: it was written at or after that phase began; `t0` is too weak, because a
    #: report written by an earlier invocation of a LATER phase can postdate t0.
    _phase_started: Dict[str, float] = {}
    halted_at: str = ""
    reports: Dict[str, Any] = {}
    advisories: List[str] = []   # v0.3.7 #505 — non-gating notes

    # ---------------- Phase 1 ----------------
    # ── ENTRY ROUTING (2026-08-25) ───────────────────────────────────────
    # A step id alone does not say who executes it, so resolve the OWNING runner
    # first and route to it. Resolving here rather than inside each phase keeps
    # one answer to "where does this task start"; the phase runners only receive
    # the decision. Refuse an unenterable step up front — an orchestrator that
    # silently ran the whole flow after being told to start at step 18 would be
    # doing something other than what it was asked.
    _entry_runner = None
    if getattr(args, "entry_step", None):
        try:
            import step_preflight as _spf_o          # noqa: PLC0415
        except ImportError as _e:
            print(f"REFUSED: --entry-step needs step_preflight ({_e})",
                  file=sys.stderr)
            return 2
        _entry_runner = _spf_o.runner_for_step(str(args.entry_step))
        if _entry_runner is None:
            _all = {r: list(_spf_o.enterable_steps(r))
                    for r in _spf_o.RUNNER_PLANS}
            print(f"REFUSED: no runner can be entered at step "
                  f"{args.entry_step!r}. Enterable steps per runner: {_all}",
                  file=sys.stderr)
            return 2
        if _entry_runner not in ENTRY_STEP_ENTERABLE_RUNNERS:
            # Entries owned by other runners are not wired here. Say so rather
            # than routing to the nearest phase.
            print(f"REFUSED: step {args.entry_step!r} is owned by "
                  f"{_entry_runner}, which this orchestrator cannot yet be "
                  f"entered at. Run that runner directly, or enter at a Phase "
                  f"1/2 step.", file=sys.stderr)
            return 2
        print(f"[entry] step {args.entry_step} -> {_entry_runner}")

    if _entry_runner == "phase3_one_shot_runner":
        # A Phase-3 entry is an isolated backend repair.  Do not run Phase 1,
        # Phase 2, analog, mixed signal or the whole-flow finalize tail here.
        # The backend owns the exact dispatch and its bounded audit.
        if not args.exit_step:
            print("REFUSED: a Phase-3 entry needs --exit-step", file=sys.stderr)
            return 2
        p3_args = [str(project), "--top-name", args.top_name,
                   "--ic-name", args.ic_name, "--container", args.container,
                   "--die-um", args.die_um, "--util", str(args.util),
                   "--pdk", args.pdk, "--entry-step", str(args.entry_step),
                   "--exit-step", str(args.exit_step)]
        if args.area_receipt:
            p3_args += ["--area-receipt", args.area_receipt,
                        "--area-run-manifest", args.area_run_manifest]
        if args.allow_oss_pdk_fallback:
            p3_args.append("--allow-oss-pdk-fallback")
        if args.allow_pdk_target_mismatch:
            p3_args.append("--allow-pdk-target-mismatch")
        import secrets
        window_run_id = secrets.token_hex(16)
        p3_env = dict(_phase_env)
        p3_env["VIBEIC_PHASE3_WINDOW_RUN_ID"] = window_run_id
        phase3_started = time.time()
        rc = _run_phase("PHASE 3 bounded window", _phase_runner("phase3"),
                        p3_args, env=p3_env)
        phase3_report = _phase_report_path(project, "phase3_one_shot.json")
        p3 = (_read_report(phase3_report)
              if _pl.published_here(phase3_report, phase3_started) else {})
        if p3.get("window_run_id") != window_run_id:
            p3 = {}
        phase3_verdict = p3.get("verdict", "NOT_MEASURED")
        p3_stale = p3.get("stale_downstream") or {}
        summary = {"program": "vibe_ic_one_shot_runner", "bounded": bool(p3),
                   **_delivery_route.report_label(project),
                   "declared_window": {"entry_step": args.entry_step,
                                       "exit_step": args.exit_step,
                                       "entry_runner": _entry_runner},
                   "phases": [{"name": "phase3", "verdict": phase3_verdict,
                               "rc": rc}],
                   "dispatched_verdict": phase3_verdict,
                   "verdict": ("FAIL" if phase3_verdict == "FAIL" else
                               "NOT_MEASURED" if p3_stale else phase3_verdict),
                   "audit_verdict": "NOT_MEASURED",
                   "audit_scope": ("bounded; whole-flow audit not refreshed"
                                   if p3 else "not measured; child report absent"),
                   "bounded_disclosures": p3.get("bounded_disclosures", []),
                   "stale_downstream": p3_stale}
        out = _pl.report_path(project, "vibe_ic_one_shot.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        _write_runner_summary(out, summary, project)
        lock.release()
        return rc if p3 else (rc or 2)

    # An entry owned by Phase 2 means Phase 1 is not this run's work: its
    # artefacts were supplied, not produced here. Force the skip through the
    # EXISTING decision function rather than adding a parallel switch, so there
    # stays exactly one place that decides whether Phase 1 runs.
    _force_skip_p1 = args.skip_phase1 or (
        _entry_runner == "design_one_shot_runner")

    # ── THE WINDOW BOUNDS THIS ORCHESTRATOR'S TAIL TOO (R-0924-1 r2) ─────────
    # Review w437hob32, MEDIUM: the phase-2 runner stopped refreshing whole-flow
    # documents under a window, and THIS runner -- the entry the owner actually
    # uses, and the one benchmark_dispatch drives -- went on running its own tail
    # unconditionally. So the leak survived at the front door, and worse, the
    # phase-2 report's `not_refreshed_here` was contradicted on disk moments
    # later by this function rewriting the very file it named.
    #
    # Phase 2's cut is decided from its own sites.  The Phase-3 cut below is
    # credited only after the child publishes a fresh bounded report, so an
    # argv flag cannot make a whole backend run appear narrow.
    _fd_window_flags = tuple(
        f"--{n} {v}" for n, v in (("entry-step", getattr(args, "entry_step", None)),
                                  ("exit-step", getattr(args, "exit_step", None))) if v)
    _fd_bounded = False
    _p3_exit_cut = None
    if args.exit_step:
        try:
            from decimal import Decimal
            _p3_exit_cut = Decimal(str(args.exit_step))
        except Exception:
            pass
    # A canonical exit before physical design suppresses Phase 3 altogether.
    # An exit inside physical design is forwarded to its runner; only a child
    # report from THIS invocation may make the front door call that bounded.
    _p3_skip_by_exit = (_p3_exit_cut is not None and _p3_exit_cut < 15)
    _p3_forward_window = (not args.skip_phase3 and
                          _p3_exit_cut is not None and
                          15 <= _p3_exit_cut < 37)
    _p3_window_ran = False
    if _fd_window_flags:
        try:
            import step_preflight as _spf_w            # noqa: PLC0415
            # Scope this question to Phase 2.  Phase 3's own result is folded
            # in after its dispatch, from the report written by THIS run.
            _fd_bounded = bool(
                (args.entry_step and _entry_runner == "design_one_shot_runner")
                or _spf_w.window_is_effective(
                    entry_step=args.entry_step, exit_step=args.exit_step,
                    runner="design_one_shot_runner"))
        except ImportError:
            # Fail CLOSED toward doing the work: an orchestrator that cannot
            # tell whether its window prunes anything must not silently skip
            # the documents a flagless run would publish.
            _fd_bounded = False
    _fd_disclosures: List[Dict[str, Any]] = []

    def _fd_disclose(refresh: str, writes: str) -> str:
        why = (f"run declared {' '.join(_fd_window_flags)}; {refresh} is a "
               f"WHOLE-FLOW refresh ({writes}) and was not run. That window "
               f"bounded this run's phase dispatch (see `phases` for what each "
               f"phase did and `declared_window` for the flags), so a document "
               f"restating every step in the flow is outside this run's declared "
               f"proof burden, not missing. Ask for it with "
               f"design_one_shot_runner --refresh-only.")
        _fd_disclosures.append({"refresh": refresh, "kind": "skipped",
                                "writes": writes,
                                "declared_by": " ".join(_fd_window_flags),
                                "why": why})
        print(f"[bounded] SKIPPED {refresh} -- {why}")
        return why
    # FX_STALE_LDOCS — the knobs THIS run hands phase 1, so a doc written
    # under another `--pdk` / `--ic-name` is not reused (review wave8 MAJOR).
    _p1_knobs = {"ic_name": args.ic_name, "pdk": args.pdk, "mode": "docs"}
    run_phase1, p1_mode = _phase1_decision(project, _force_skip_p1, _p1_knobs)
    # What the generated L docs on disk ARE, asked once and carried into the
    # report whatever is decided from it.
    _gd_now = _pl.generated_docs_dir(project)
    _p1_fresh = (_phase1_freshness(project, _p1_knobs)
                 if _gd_now.is_dir() and len(list(_gd_now.glob("L*.json"))) >= 13
                 else None)
    _p1_design_input = _design_input_present(project)
    if _p1_fresh is not None and not _p1_design_input:
        _p1_fresh = {"state": "KEPT_AS_INPUT", "reason": "NO_DESIGN_INPUT",
                     "why": "these L docs have no design input behind them: "
                            "they were handed to the project and ARE its "
                            "input, never regenerated or judged stale"}
    _p1_regenerating = (run_phase1 and p1_mode == "docs"
                        and _p1_fresh is not None
                        and _p1_fresh["state"] == _p1id.REGENERATE)
    if _p1_fresh is not None:
        print(f"[phase1] generated L docs: {_p1_fresh['state']} "
              f"({_p1_fresh['reason']}) — {_p1_fresh['why']}")
    if _p1_regenerating:
        # Move the stale docs aside first, so a layer step that fails during
        # regeneration cannot leave an older producer's doc in place.
        try:
            _moved = _p1id.supersede_docs(
                project, f"{_p1_fresh['reason']}: {_p1_fresh['why']}")
        except _p1id.SupersedeError as exc:
            # An old L doc left live must never be mixed with the new run.
            # Route through the existing Phase-1 refusal before dispatch.
            _p1_regenerating = False
            run_phase1 = False
            p1_mode = _P1_MODE_REFUSED
            _p1_fresh = {"state": _p1id.REFUSE,
                         "reason": "SUPERSEDE_FAILED", "why": str(exc)}
        else:
            advisories.append(
                f"phase1 REGENERATED the generated L docs — "
                f"{_p1_fresh['reason']}: {_p1_fresh['why']}"
                + (f" (the previous docs are kept at {_moved})" if _moved else ""))
    if _p1_fresh is not None and _p1_fresh.get("reason") == "SUPERSEDE_FAILED":
        _p1_skipped_by = "the stale-doc archive failed"
    elif args.skip_phase1:
        _p1_skipped_by = "--skip-phase1"
    elif p1_mode == _P1_MODE_EXPERT_SECOND_PASS:
        _p1_skipped_by = "the expert second pass re-extracts nothing"
    else:
        _p1_skipped_by = "its entry step is past phase 1"
    _p1_stale_why = _stale_generated_docs_note(
        _p1_regenerating or (run_phase1 and p1_mode == "docs"),
        _p1_fresh, _p1_design_input, _p1_skipped_by)
    if _p1_stale_why:
        advisories.append(_p1_stale_why)
    if p1_mode == _P1_MODE_REFUSED:
        advisories.append(
            f"phase1 REFUSED — {_p1_fresh['reason'] if _p1_fresh else ''}: "
            f"{_p1_fresh['why'] if _p1_fresh else ''}")
        plan.append(("phase1", "NOT_MEASURED", 1))
        halted_at = "phase1"
    elif run_phase1:
        runner = _phase_runner("phase1")
        p1_args = [str(project), "--ic-name", args.ic_name]
        if args.skip_analog:
            p1_args.append("--skip-analog")
        # #2204 — the second pass of the expert hand-off. The extraction is
        # ALREADY DONE and its L documents are what the delivered answer was
        # authored against, so this pass runs the second track and nothing
        # else. The reason is PRINTED: a Phase-1 re-entry the operator did not
        # ask for must say which fact on disk caused it.
        if p1_mode == _P1_MODE_EXPERT_SECOND_PASS:
            p1_args += ["--second-track-only"]
            _pending, _why = _expert_answer_pending(project)
            print(f"[phase1] EXPERT SECOND PASS — {_why}")
        # Path B (vendor docs, no L docs yet): force docs mode so the
        # doc-extraction track runs and produces L*.json for phase2.
        elif p1_mode == "docs":
            p1_args += ["--mode", "docs"]
            # ORGANIC-20260803b — a design document may state its timing
            # target ONCE PER PROCESS, as a table keyed by PDK. Phase 1
            # cannot resolve such a table without knowing which process this
            # run builds, and until now it was never told: `--pdk` reached
            # phase3 only, so the SDC that drives CTS and STA was authored
            # two phases before anything knew the process. Forwarded through
            # `parse_known_args` extras; ignored by every design whose spec
            # is not PDK-keyed.
            if args.pdk and str(args.pdk).strip().lower() != "auto":
                p1_args += ["--pdk", str(args.pdk).strip()]
        label = ("PHASE 1 (expert second pass → consume the delivered "
                 "IC-Expert answer)"
                 if p1_mode == _P1_MODE_EXPERT_SECOND_PASS
                 else "PHASE 1 (vendor docs → L1-L23)" if p1_mode == "docs"
                 else "PHASE 1 (NL → L1-L23)")
        _phase_started["phase1"] = time.time()
        rc = _run_phase(label, runner, p1_args, env=_phase_env)
        verdict, _fresh_why = _row_verdict(
            project, "phase1_one_shot.json", rc,
            _phase_started.get("phase1", t0), "phase1")
        if _fresh_why:
            advisories.append(_fresh_why)
        rep = _read_report(_phase_report_path(project, "phase1_one_shot.json"))
        plan.append(("phase1", verdict, rc))
        reports["phase1"] = rep
        if verdict == "FAIL":
            # v0.3.7 — ORGANIC #505: in the standalone-design shape
            # (--skip-phase3 → the RTL is the deliverable, no silicon
            # backend), a phase1 failure that is PURELY doc-extraction
            # coverage is orthogonal to the RTL verdict. Demote it to a
            # non-gating COVERAGE-INCOMPLETE advisory and let phase2 run,
            # so the overall verdict reflects the actual RTL deliverable
            # (synth / lint / sdc). A TODO-stub or hard phase1 failure is
            # NOT coverage-only and still halts. Full-chip flows (phase3
            # in scope) keep halting — doc-extraction feeds the backend.
            cov_only, cov_reason = _phase1_failure_is_coverage_only(project)
            # THE SIDECAR MUST BE THIS INVOCATION'S, AND THE rc MUST BE THE ONE THE
            # COVERAGE-ONLY PATH RETURNS. R-0915-151.
            #
            # `_phase1_failure_is_coverage_only` reads
            # `_path_layout.COVERAGE_ONLY_SIDECAR_REL` with no date check, and phase1
            # writes that sidecar BEFORE three later non-coverage blocking returns
            # (the extraction gap, the L8 clock conflict, ...). So a stale sidecar --
            # or a fresh one followed by a different failure -- demoted a
            # non-coverage phase1 FAIL to PASS_WITH_WAIVERS at exit 0.
            #
            # CORRECTING MY OWN CLAIM: I wrote that this guarantees the exemption is "minted
            # only behind the coverage-only predicate". That is too strong, and a review is
            # right to say so -- #505 keys the exemption on rc == 1, and rc 1 cannot tell a
            # coverage-only failure from an expert or 0.5ic failure. That is base behaviour;
            # what the checks below do is NARROW it, not make it exact. So: the
            # sidecar must have been written at or after phase1 STARTED in this
            # invocation, and only rc 1 -- what the coverage-only path returns -- is
            # exempt.
            # AND BEFORE EITHER SIDECAR ROUTE: DID PHASE 1 PUBLISH A RECORD HERE AT ALL?
            # R-0915-160, fourth cut (review w3nppqdpn).
            #
            # r9 put this question on the CARRIED-NAME route only, and the name route is reached
            # solely when the sidecar is not fresh -- so the MTIME route walked past it. The sibling
            # it left: a FIRST pass where D1 writes a fresh coverage-only sidecar and the pass then
            # dies before publishing its record (`_run_expert_track` -> `_wd.run_host_supervised`
            # raising, or the record write itself). rc 1, no record, `_side_fresh` True from the
            # mtime alone -- demoted, and phase 2 ran on a phase 1 that crashed. Pre-existing on
            # that route rather than introduced by r9, and worse on main, but the question is the
            # same one and it belongs to the DEMOTION, not to either route into it.
            #
            # So it is a PRECONDITION now, asked once, and both routes sit behind it. Measured
            # harmless: a legitimate coverage-only pass 1 always publishes its record before
            # returning (the docs branch and the prompt branch each write it as their last act), and
            # the expert second pass always rewrites it -- so no run that has earned the exemption
            # is refused by this.
            _rec_is_ours = _published_here(
                project, "phase1_one_shot.json", _phase_started.get("phase1", t0))
            if cov_only and not _rec_is_ours:
                advisories.append(
                    "phase1 exited " + str(rc) + " having published NO record in this invocation, "
                    "so nothing here is phase 1's own account of itself: the coverage-only "
                    "exemption needs a record from THIS pass and there is none. NOT demoting"
                    + (" (the record on disk belongs to an earlier run)"
                       if _report_exists(project, "phase1_one_shot.json") else ""))
                cov_only = False
            _side = _pl.coverage_only_sidecar_path(project)
            try:
                _side_fresh = (_side.is_file()
                               and _side.stat().st_mtime + _FRESHNESS_TOLERANCE_S
                               >= _phase_started.get("phase1", t0))
            except OSError:                                # pragma: no cover
                _side_fresh = False
            # OR THIS INVOCATION'S PASS-1 RECORD NAMES IT. R-0915-160, second cut.
            #
            # The mtime rule above is right for a FIRST pass and wrong for the expert second pass,
            # which is the AI-backup re-invocation R-0915-161 exists for: `run_second_pass_only`
            # CARRIES pass 1's record forward and never rewrites the sidecar, so the sidecar
            # legitimately predates this invocation's phase-1 start. Refusing it flipped a
            # `--skip-phase3` coverage-only project from PASS_WITH_WAIVERS to FAIL and halted at
            # phase 1, where main demoted and continued -- a re-invocation losing the very
            # exemption it was invoked to act on.
            #
            # The sidecar is therefore judged against THE RECORD IT BELONGS TO, by content: PASS
            # ONE stamps `pass1_coverage_sidecar.sha256` into the record it publishes, naming the
            # sidecar its own D1 wrote (`phase1_one_shot_runner._name_the_sidecar_this_pass_wrote`,
            # entitled by D1 having run in that pass, not by any clock); the second pass carries
            # that name forward and computes nothing. A sidecar the carried record does not name
            # stays refused, and one swapped afterwards fails the sha.
            #
            # TWO CLAIMS FROM r7 CORRECTED HERE, both of which this branch outgrew:
            #   * it said the sidecar is named "only if the sidecar was at least as new as the
            #     record being carried". That ordering is GONE: pass 1 writes the sidecar first and
            #     its record last, so the test was false on every real re-invocation and nothing
            #     was ever named (review wjn67aev3).
            #   * it said "`_row_verdict` already refuses a stale one". It does not, and cannot:
            #     `_row_verdict` RETURNS a verdict, and `rep` is read from that path unconditionally
            #     a few lines above. A crashed phase 1 that wrote no record leaves an EARLIER run's
            #     record in `rep`, whose name still matches the untouched sidecar -- which is how
            #     r8 opened a route to PASS_WITH_WAIVERS for a run whose phase 1 died (review
            #     wkevxl71c). The record has to be THIS invocation's, and it is ASKED --
            #     `_published_here`, the same `exists AND fresh` test `_row_verdict` uses, from the
            #     one implementation both readers share -- as the PRECONDITION on the demotion
            #     above, not as a test on this route. r9 put it here, on the name route, and a
            #     review was right that the mtime route then walked past it (w3nppqdpn): the
            #     question belongs to the demotion, which is the thing being authorised, and not to
            #     either road into it.
            if cov_only and not _side_fresh:
                # `cov_only` is already false unless the record is THIS pass's (the precondition
                # above), so `rep` here is this invocation's own account and the name it carries
                # can be trusted as far as its digest. Asked once, not twice.
                _named = (rep.get("pass1_coverage_sidecar")
                          if isinstance(rep, dict) else None)
                if isinstance(_named, dict) and _side.is_file():
                    try:
                        import hashlib as _hashlib          # noqa: PLC0415
                        _have = _hashlib.sha256(_side.read_bytes()).hexdigest()
                    except OSError:                        # pragma: no cover
                        _have = None
                    if _have and _have == str(_named.get("sha256") or ""):
                        _side_fresh = True
                        advisories.append(
                            "phase1's coverage-only sidecar predates this invocation's phase-1 "
                            "start, but THIS invocation's pass-1 record names it by content "
                            "(pass1_coverage_sidecar.sha256) and the bytes match, so it is the "
                            "sidecar that record was written against: demotion still available")
            if cov_only and not _side_fresh:
                advisories.append(
                    "phase1's coverage-only sidecar predates phase1's start in this "
                    "invocation and this invocation's pass-1 record does not name it, so it "
                    "describes an earlier run: NOT demoting")
                cov_only = False
            if cov_only and rc != 1:
                advisories.append(
                    f"phase1 failed with rc={rc}, which is not the rc the "
                    f"coverage-only path returns (1): NOT demoting")
                cov_only = False
            if args.skip_phase3 and cov_only:
                plan[-1] = ("phase1", "COVERAGE-INCOMPLETE", rc)
                # R-0915-145 — the rc stays on the row (it is what phase1's
                # process really did) and the DEMOTION is recorded beside it, so
                # the roll-up can tell "a demoted row whose rc belongs to its
                # pre-demotion FAIL" from "a row claiming a pass while its own
                # process exited non-zero". This is the ONLY site that mints the
                # token.
                _demoted["phase1"] = {
                    "token": DEMOTION_COVERAGE_ONLY,
                    "original_verdict": "FAIL",
                    "original_rc": rc,
                    "reason": (f"doc-extraction coverage only "
                               f"(coverage {cov_reason.get('coverage_pct')}%, "
                               f"todo {cov_reason.get('total_todo')}), "
                               f"standalone shape (--skip-phase3)"),
                }
                advisories.append(
                    f"phase1 doc-extraction COVERAGE-INCOMPLETE "
                    f"(coverage {cov_reason.get('coverage_pct')}%, "
                    f"todo {cov_reason.get('total_todo')}): non-gating in "
                    f"the standalone-design shape — the RTL deliverable "
                    f"verdict follows phase2; close the doc-extraction gap "
                    f"before a full-chip (phase3) flow."
                )
            else:
                halted_at = "phase1"
        elif (rc != 0 and verdict == "NOT_MEASURED"
              and rep.get("reason_class") == "awaiting_signed_judgement"
              and (rep.get("canonical_producer") or {}).get("step_id") == "D1"
              and (rep.get("canonical_producer") or {}).get("mode") == "default"
              and _published_here(project, "phase1_one_shot.json",
                                  _phase_started["phase1"])):
            # The canonical producer has handed off to its required expert.
            # Keep that unmeasured result; downstream registration/dispatch
            # must wait for the current signed judgement too.
            halted_at = "phase1"
            advisories.append("phase1 awaits its required signed AI judgement; "
                              "downstream registration and dispatch were not started")
    else:
        plan.append(("phase1", "SKIPPED", 0))

    # FX_STALE_LDOCS (review wave8 BLOCKER 2) — the generated docs as phase 1
    # left them. Anything that changes them from here to the end of this run
    # is THIS FLOW's doing (phase 2's `restamp_l_doc_skeletons`, analog A8's
    # rail synth, …), recorded as a derivation before the run ends, so the
    # next run does not mistake it for a hand edit -- whether or not the
    # writer went through the `dump` chokepoint, which records it too.
    _p1_docs_after = _p1id.docs_snapshot(project)

    # ---------------- Analog-applicability decision ----------------
    # Single source of truth (ORGANIC-20260606 #459): the analog-track
    # applicability is decided ONCE here, BEFORE phase2 runs, so the same
    # decision can (a) gate the analog A-track invocation below AND (b)
    # be forwarded into phase2's final_audit. Previously _need_analog()
    # was evaluated only AFTER phase2; phase2 therefore never learned that
    # the orchestrator was skipping the analog track, and final_audit
    # treated analog A9 as a HARD condition → every pure-digital run
    # halted at phase2. The two decision points now agree.
    run_analog = _need_analog(project, args.skip_analog)

    # ---------------- Top-module resolution (once, for BOTH phase 2 & 3) ------
    # The historical default '--top-name chip_top' is wrong for a standalone
    # block whose sole top is the design itself (e.g. spm). It must be resolved
    # BEFORE phase 2, not just phase 3: phase 2's equivalence check (step 13,
    # RTL≡netlist) uses it as the GOLD top, so a literal 'chip_top' makes LEC
    # compare 0 points → FAIL even though synth/PnR/GDS/DRC/LVS all pass. Derive
    # once from the (seeded or phase-1-produced) RTL and forward the SAME top to
    # both phases so their tops never disagree. Honors an explicit --top-name.
    flow_top, flow_top_note = _resolve_top_name(
        project, args.ic_name, args.top_name, top_name_explicit)
    if flow_top_note:
        print(f"[flow] {flow_top_note}", flush=True)
        advisories.append(f"flow {flow_top_note}")

    # Register consumers only after Phase 1 has produced their inputs and the
    # existing applicability decision has resolved the analog route. A Phase-1
    # failure must retain its own verdict instead of failing registration of
    # downstream rows whose inputs were never produced.
    if halted_at != "phase1":
        _execution.bootstrap(project, parameters={"top": flow_top,
            "container": args.container, "pdk_name": args.pdk,
            "skip_analog": not run_analog})

    # ---------------- Analog A1..A8 ----------------
    # FX_ADC_PHASE_ORDER — DISPATCHED BEFORE PHASE 2, reported after it.
    #
    # The A-track reads phase-1 artefacts (L5_ADI_SPEC / the block list) and,
    # for A8's inline macro/RTL comparison, may read supplied build RTL under
    # input/ through the same §4.05-safe discovery Phase 2 uses. It reads no
    # Phase-2-produced RTL. Phase 2, though, JUDGES the A-track: its
    # Step-4 acceptance run reads A4's corner records, and its final audit
    # (`flow_compliance_check --phase 2`) judges A1..A9, which the flow yaml
    # declares `phase_scope: agnostic` (R-0915-158: in BOTH scopes). With the
    # A-track dispatched after phase 2, both read artefacts that did not exist
    # yet. MEASURED on u_hawaii_adc (IC_STATUS_0928): the phase-2 audit FAILed
    # "Step A1: Analog Spec Extraction (missing_artefact)" and every A2..A9
    # upstream_failed, and that FAIL made phase 2 -- and the run -- red however
    # the A-track itself then did. Running the producer before its judge is the
    # ordering the flow yaml already implies (A1 blocks_on D1 only).
    #
    # The plan ROW is still appended after phase 2 (`_analog_row`), so the
    # run's phase order as reported is unchanged.
    # Non-blocking on FAIL. Dispatches off the single run_analog decision
    # computed above (#459) so the A-track invocation and phase2's
    # --skip-analog forwarding never disagree. The decision is sourced from
    # phase1 artefacts (L5_ADI_SPEC / analog_block_list), which are produced
    # before this point — phase2 does not emit them — so moving the decision
    # ahead of phase2 is behaviourally identical for analog/mixed-signal.
    # ORGANIC (GAP-ANALOG-1) — an analog / mixed-signal IC (run_analog==True) has
    # its silicon flow in this A-track, NOT the digital phase2. Its digital phase2
    # legitimately has NO synthesizable RTL (class rtl_gen=null), so phase2 FAILs
    # and sets halted_at="phase2" — but that is the EXPECTED digital outcome, not a
    # reason to skip the IC's OWN analog track. Previously `if not halted_at`
    # gated the A-track OUT on that expected digital FAIL, so an analog-only IC
    # could NEVER reach its analog flow via the one-shot entry. Dispatch the
    # A-track whenever run_analog AND phase1 did not itself halt (phase1 emits the
    # L5_ADI_SPEC the A-track needs); a phase2 digital halt does NOT block it. The
    # A-track stays non-blocking, and phase3's digital PnR remains correctly gated
    # on halted_at (a pure-analog IC still skips the digital PnR).
    _analog_dispatch = (run_analog and not _p3_skip_by_exit
                        and halted_at in ("", "phase2"))
    if _analog_dispatch:
        runner = _phase_runner("analog")
        # `--pdk` REACHES THE ANALOG TRACK. Until now this was the only phase
        # invocation that forwarded nothing: phase1 (above) and phase3 (below)
        # both pass the operator's `--pdk` on, and the A-track — the one track
        # whose every step is a PDK-bound simulation or a PDK-bound rule deck —
        # was given only the container. A run driven with `--pdk <X>` therefore
        # produced analog evidence that had nothing to do with `<X>`; measured
        # on `u_hawaii_adc`, a run invoked with `--pdk sky130A` wrote
        # `layout_provenance.json` naming ihp-sg13g2 twelve times, sky130A zero
        # times, and raised no mismatch advisory. The label on that run was the
        # only thing sky130A about it.
        #
        # `auto` is the argparse default and means "the design decides"; it is
        # not a selector, so it is not forwarded — same test the phase1 site
        # uses, so the two cannot drift apart.
        _analog_args = [str(project), "--container", args.container]
        if args.pdk and str(args.pdk).strip().lower() != "auto":
            _analog_args += ["--pdk", str(args.pdk).strip()]
        _phase_started["analog"] = time.time()
        rc = _run_phase("ANALOG A1..A8", runner, _analog_args, env=_phase_env)
        rep = _read_report(_pl.report_path(project, "analog_one_shot.json"))
        verdict = rep.get("verdict") or ("PASS" if rc == 0 else "FAIL")
        _analog_row = ("analog", verdict, rc)
        reports["analog"] = rep
        # Analog FAIL is logged but does NOT halt the digital flow —
        # downstream Phase 3 still proceeds (analog hardmacros land
        # via Step 14 floorplan in a future iteration).
    else:
        _analog_row = ("analog", "SKIPPED", 0)

    # ---------------- Phase 2 ----------------
    if not halted_at:
        runner = _phase_runner("phase2")
        # Forward --skip-phase3 so phase2's DFT/LEC chain (steps 11-13) gates the
        # heavy Fault ATPG OFF on a lightweight/RTL-only run (no silicon target),
        # while still running the fast LEC. On a full-chip flow (no --skip-phase3)
        # the full DFT insertion + ATPG runs.
        # v0.1.54 capture: forward --skip-analog so phase2 final_audit doesn't
        # FAIL a digital-only project on missing phase1/analog/analog_block_list.json.
        # (1) User explicitly asked to skip the analog track.
        # (2) #459: the orchestrator's OWN analog decision is authoritative. If
        # we are NOT running the A-track because _need_analog()==False (even
        # without a user --skip-analog), phase2's final_audit must agree — so
        # inject --skip-analog here too. For analog / mixed-signal projects
        # (run_analog==True) the flag is NEVER injected, so the A-track and its
        # final_audit condition stay active (corpus-sweep guard). The membership
        # guard makes (1)+(2) idempotent (no duplicate append).
        # `--skip-analog` is emitted once below from this resolved decision.
        # Forward --exit-step the same way --entry-step travels: the phase2
        # runner owns the site table, so the mapping (and the refusal for an
        # unmappable value) happens there, not here.
        p2_args = _phase2_runner_argv(
            project, top_name=flow_top, container=args.container,
            max_rtl_repair_retries=args.max_rtl_repair_retries,
            lec_max_completed_rungs=args.lec_max_completed_rungs,
            skip_hardware=args.skip_hardware, skip_phase3=args.skip_phase3,
            skip_analog=False,
            entry_step=(str(args.entry_step)
                        if _entry_runner == "design_one_shot_runner" else None),
            exit_step=(str(args.exit_step) if args.exit_step else None),
            area_receipt=args.area_receipt,
            area_run_manifest=args.area_run_manifest,
            phase3_rederive_ic_name=(
                args.ic_name
                if _phase3_rederives_top(flow_top, top_name_explicit)
                else None))
        if args.skip_analog:
            p2_args.append("--skip-analog")
        elif not run_analog:
            p2_args.append("--skip-analog")
        p2_admission = _canonical_admission.admit_span(
            project, "phase2", PROGRAMS_DIR, args.container,
            {"top_name": flow_top, "max_rtl_repair_retries": args.max_rtl_repair_retries,
             "skip_hardware": args.skip_hardware, "skip_phase3": args.skip_phase3,
             "skip_analog": "--skip-analog" in p2_args,
             "entry_step": args.entry_step, "exit_step": args.exit_step,
             "force_rtl_regen": False, "dry_run": False,
             "lec_max_completed_rungs": args.lec_max_completed_rungs})
        if not p2_admission.admitted:
            print(f"REFUSED: canonical Phase-2 admission: {p2_admission.reason} "
                  f"({p2_admission.detail})", file=sys.stderr)
            plan.append(("phase2", "REFUSED-CANONICAL-ADMISSION", 2))
            halted_at = "phase2"
        else:
            p2_env = _canonical_admission.child_env(
                p2_admission.identity_sha256, _phase_env)
            _phase_started["phase2"] = time.time()
            rc = _run_phase("PHASE 2 (= 2a + 2b)", runner, p2_args, env=p2_env)
            verdict, _fresh_why = _row_verdict(
                project, "phase2_one_shot.json", rc,
                _phase_started.get("phase2", t0), "phase2")
            if _fresh_why:
                advisories.append(_fresh_why)
            rep = _read_report(_phase_report_path(project, "phase2_one_shot.json"))
            plan.append(("phase2", verdict, rc))
            reports["phase2"] = rep
            if verdict == "FAIL":
                halted_at = "phase2"
    else:
        plan.append(("phase2", "SKIPPED", 0))


    plan.append(_analog_row)

    # ORGANIC #2064 — RE-EVALUATE THE ANALOG ACCEPTANCE, NOW THAT A4 HAS RUN.
    #
    # `design_one_shot_runner` emits and runs the acceptance checks beside the
    # L10 unit-TB pair, which is where Step 4 reads their JUnit. The A-track
    # has already run on this front-door path, so this is a cheap idempotent
    # refresh of the record-read checks, not a promised future measurement.
    # The refreshed JUnit is what the whole-flow audit below and at the end of
    # the run reads. Non-blocking and byte-for-byte a no-op for a design with
    # no analog verification plan.
    if _analog_dispatch:
        _acc_json = _pl.report_path(project, "analog/analog_acceptance_run.json")
        _run_phase("ANALOG ACCEPTANCE (re-evaluated after A4)",
                   PROGRAMS_DIR / "analog_acceptance_tb_gen.py",
                   [str(project), "--run", "--json", str(_acc_json)],
                   env=_phase_env)

    # Produce the stage-analog compliance record as part of the run, before
    # Step 14 or a later whole-flow audit consumes it.  The Step-14 gate also
    # invokes this scoped audit, but a final auditor's first write is tagged
    # ``audit_created`` and cannot count as evidence produced by the run it is
    # judging.  This pre-production is non-blocking: the A-track and the
    # Step-14 gate retain ownership of their own verdicts.
    if halted_at != "phase1" and not _p3_skip_by_exit:
        _analog_stage_json = (project / "reports" / "analog"
                              / "stage_analog_compliance.json")
        _analog_stage_rc = _run_phase(
            "ANALOG STAGE COMPLIANCE (pre-Step 14 evidence)",
            PROGRAMS_DIR / "flow_compliance_check.py",
            [str(project), "--stage-id", "stage_analog", "--strict",
             "--json", str(_analog_stage_json)],
            env=_phase_env)
        reports["analog_stage_compliance"] = _read_report(_analog_stage_json)
        if _analog_stage_rc != 0:
            advisories.append(
                "stage_analog compliance is not clean; Step 14 remains the "
                "verdict owner — see reports/analog/"
                "stage_analog_compliance.json")

    # ---------------- Phase 3 ----------------
    phase3_top = flow_top
    if not halted_at and not args.skip_phase3 and not _p3_skip_by_exit:
        runner = _phase_runner("phase3")
        # Reuse the flow-level resolved top. If phase 2 GENERATED the RTL (the
        # from-docs path, where no RTL existed at the flow-resolution point
        # above), re-resolve now that phase-2 output exists so phase-3 still
        # gets the real top rather than the default 'chip_top'.
        phase3_top = flow_top
        if _phase3_rederives_top(phase3_top, top_name_explicit):
            phase3_top, top_note = _resolve_top_name(
                project, args.ic_name, args.top_name, top_name_explicit)
            if top_note:
                print(f"[phase3] {top_note}", flush=True)
                advisories.append(f"phase3 {top_note}")
        p3_args = [str(project),
                   "--top-name", phase3_top,
                   "--ic-name", args.ic_name,
                   "--container", args.container,
                   "--die-um", args.die_um,
                   "--util", str(args.util),
                   "--pdk", args.pdk]
        if args.area_receipt:
            p3_args += ["--area-receipt", args.area_receipt,
                        "--area-run-manifest", args.area_run_manifest]
        if _p3_forward_window:
            p3_args += ["--entry-step", "9", "--exit-step", str(args.exit_step)]
        if getattr(args, "allow_oss_pdk_fallback", False):
            p3_args.append("--allow-oss-pdk-fallback")
        if getattr(args, "allow_pdk_target_mismatch", False):
            p3_args.append("--allow-pdk-target-mismatch")
        p3_admission = _canonical_admission.admit_span(
            project, "phase3", PROGRAMS_DIR, args.container,
            {"top_name": phase3_top, "ic_name": args.ic_name,
             "die_um": args.die_um, "util": args.util, "pdk": args.pdk,
             "allow_oss_pdk_fallback": bool(args.allow_oss_pdk_fallback),
             "allow_pdk_target_mismatch": bool(args.allow_pdk_target_mismatch),
             "spare_density": 0.02})
        if not p3_admission.admitted:
            print(f"REFUSED: canonical Phase-3 admission: {p3_admission.reason} "
                  f"({p3_admission.detail})", file=sys.stderr)
            plan.append(("phase3", "REFUSED-CANONICAL-ADMISSION", 2))
            halted_at = "phase3"
        else:
            p3_env = _canonical_admission.child_env(
                p3_admission.identity_sha256, _phase_env)
            window_run_id = None
            if _p3_forward_window:
                import secrets
                window_run_id = secrets.token_hex(16)
                p3_env["VIBEIC_PHASE3_WINDOW_RUN_ID"] = window_run_id
            _phase3_ran = True
            _phase_started["phase3"] = time.time()
            rc = _run_phase("PHASE 3 (synth → PnR → GDS → DRC → LVS)",
                            runner, p3_args, env=p3_env)
            verdict, _fresh_why = _row_verdict(
                project, "phase3_one_shot.json", rc,
                _phase_started.get("phase3", t0), "phase3")
            if _fresh_why:
                advisories.append(_fresh_why)
            rep = _read_report(_phase_report_path(project, "phase3_one_shot.json"))
            plan.append(("phase3", verdict, rc))
            reports["phase3"] = rep
            _p3_window_ran = bool(_p3_forward_window and rep.get("bounded")
                                  and rep.get("window_run_id") == window_run_id
                                  and _pl.published_here(
                                      _phase_report_path(project, "phase3_one_shot.json"),
                                      _phase_started["phase3"]))
            if verdict == "FAIL":
                halted_at = "phase3"
    else:
        plan.append(("phase3", "SKIPPED", 0))

    if _p3_forward_window and _phase3_ran and not _p3_window_ran:
        # The child refused or failed before publishing a fresh window
        # account.  An old Phase-3 report must not turn that into a bounded
        # PASS, and the unbounded finalize tail must not run after refusal.
        out = _pl.report_path(project, "vibe_ic_one_shot.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        _write_runner_summary(out, {
            "program": "vibe_ic_one_shot_runner", "bounded": False,
            **_delivery_route.report_label(project),
            "window_requested": {"entry_step": args.entry_step,
                                 "exit_step": args.exit_step},
            "verdict": "NOT_MEASURED",
            "reason": "Phase-3 child did not publish a fresh bounded report",
            "phases": [{"name": n, "verdict": v, "rc": rc}
                       for n, v, rc in plan],
        }, project)
        lock.release()
        return next((rc or 2 for name, _, rc in reversed(plan)
                     if name == "phase3"), 2)

    if _p3_window_ran:
        # A physical window ends here.  Mixed-signal merge, PDK finalisation
        # and the front-door whole-flow tail consume outputs beyond the cut.
        # They cannot run and still claim the same narrow window.
        p3_window = reports["phase3"]
        stale = p3_window.get("stale_downstream") or {}
        window_verdict = p3_window.get("verdict", "NOT_MEASURED")
        summary = {
            "program": "vibe_ic_one_shot_runner", "bounded": True,
            **_delivery_route.report_label(project),
            "declared_window": {"entry_step": args.entry_step,
                                "exit_step": args.exit_step,
                                "entry_runner": _entry_runner},
            "phases": [{"name": n, "verdict": v, "rc": rc}
                       for n, v, rc in plan],
            "dispatched_verdict": window_verdict,
            "verdict": ("FAIL" if window_verdict == "FAIL" else
                        "NOT_MEASURED" if stale else window_verdict),
            "audit_verdict": "NOT_MEASURED",
            "audit_scope": "bounded; whole-flow audit not refreshed",
            "stale_downstream": stale,
            "bounded_disclosures": p3_window.get("bounded_disclosures", []),
            "not_refreshed_here": ["reports/final_summary.md"],
        }
        out = _pl.report_path(project, "vibe_ic_one_shot.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        _write_runner_summary(out, summary, project)
        lock.release()
        return next(rc for name, _, rc in reversed(plan) if name == "phase3")

    # ---------------- Mixed-signal M1 (A+D top merge + top-level LVS) ------
    # M1-d4. `mixed_signal_top_lvs_run` is the ONLY writer of
    # phase3/mixed_signal/top_merged.gds (M1's declared required_output) and of
    # reports/analog/mixed_signal/top_lvs.json (the artefact
    # mixed_signal_merge_check demands for a PASS) — and no runner invoked it.
    # Measured on a synthetic A+D fixture with every input present: M1 came
    # back MISSING from flow_compliance_check because top_merged.gds never
    # existed, so its gate never even ran. Declaring the producer in the step's
    # gate is not enough on its own: check_step returns MISSING on absent
    # required_outputs BEFORE evaluating the gate, so the producer must be
    # driven from the flow. This is that drive.
    #
    # NON-BLOCKING by construction, exactly like the A-track above: the M1 gate
    # owns the verdict (a real netgen mismatch → M1 FAIL in the compliance
    # audit); a merge that cannot run here must not halt the digital chain.
    # Its inputs are the analog hardmacro GDS/Verilog (A8) and the phase-3
    # sign-off GDS + gate netlist, so it runs only when BOTH tracks ran.
    _ms_dispatch = (run_analog and not args.skip_phase3 and not _p3_skip_by_exit
                    and halted_at not in ("phase1", "phase2"))
    if _ms_dispatch:
        _ms_json = (project / "reports" / "analog" / "mixed_signal"
                    / "top_lvs_run.json")
        # The merge/extract needs the PDK's magicrc + netgen setup, so it needs
        # the RESOLVED pdk name, not the literal "auto" the operator may have
        # passed. Phase 3 records what it actually resolved to; fall back to
        # the CLI value when phase 3 did not run — an unresolvable name is the
        # producer's rc=2 skip naming the missing tech, never a guess.
        _ms_pdk = (reports.get("phase3") or {}).get("pdk") or args.pdk
        dispatched = _controller_mixed_step(_execution, project, "M1", _ms_json)
        if dispatched is None:
            rc = _run_phase(
                "MIXED-SIGNAL M1 (A+D GDS merge → Magic extract → netgen LVS)",
                PROGRAMS_DIR / "mixed_signal_top_lvs_run.py",
                [str(project), "--top", phase3_top,
                 "--container", args.container, "--pdk", str(_ms_pdk),
                 "--json", str(_ms_json)], env=_phase_env)
            rep = _read_report(_ms_json)
        else:
            rc, rep = dispatched
        # rc 2 is the producer's documented disclosed skip (inputs / tools /
        # PDK tech absent) — record it as SKIP, never as a pass.
        verdict = rep.get("verdict") or {0: "PASS", 2: "SKIP"}.get(rc, "FAIL")
        plan.append(("mixed_signal", verdict, rc))
        reports["mixed_signal"] = rep
        # Default M2 follows the fixed M1 producer. One native Yosys arm
        # reads the routed design; the canonical M2 gate independently checks
        # its bound outputs. A failed M1 cannot dispatch a downstream producer.
        if rc == 0 and verdict == "PASS":
            _m2_json = project / "reports/analog/mixed_signal/power_domain_producer_audit.json"
            _m2_json.unlink(missing_ok=True)
            _m2_dispatched = _controller_mixed_step(_execution, project, "M2", _m2_json)
            if _m2_dispatched is None:
                _m2_rc = _run_phase(
                "MIXED-SIGNAL M2 (placed power-domain protection paths)",
                PROGRAMS_DIR / "mixed_signal_power_domain_run.py",
                [str(project), "--top", phase3_top,
                 "--container", args.container, "--json", str(_m2_json)],
                env=_phase_env)
                _m2_rep = _read_report(_m2_json)
            else:
                _m2_rc, _m2_rep = _m2_dispatched
            # An exit status cannot stand in for a tool measurement. Missing
            # or contradictory producer output is never a passing M2 row.
            if (_m2_rc == 0
                    and _m2_rep.get("program") == "mixed_signal_power_domain_run"
                    and _m2_rep.get("verdict") == "PASS"):
                _m2_verdict = "PASS"
            else:
                _m2_verdict = "NOT_READY" if _m2_rc == 2 else "FAIL"
                if _m2_rc == 0:
                    _m2_rc = 1
        else:
            _m2_rc, _m2_verdict = 2, "NOT_READY"
            _m2_rep = {"verdict": _m2_verdict, "reason": "M1 did not pass; M2 not dispatched"}
        plan.append(("mixed_signal_M2", _m2_verdict, _m2_rc))
        reports["mixed_signal_M2"] = _m2_rep
        # Fixed M3/M4 dependency sequence. These rows remain independent of
        # digital completion, but an unmeasured mixed step cannot dispatch its
        # successor or borrow a passing verdict from missing audit bytes.
        if _m2_rc == 0 and _m2_verdict == "PASS":
            _m3_json = project / "reports/analog/mixed_signal/m3_producer_audit.json"
            _m3_json.unlink(missing_ok=True)
            _m3_dispatched = _controller_mixed_step(_execution, project, "M3", _m3_json)
            if _m3_dispatched is None:
                _m3_rc = _run_phase(
                "MIXED-SIGNAL M3 (current simulation / interface SI evidence)",
                PROGRAMS_DIR / "mixed_signal_m3_run.py",
                [str(project), "--top", phase3_top, "--container", args.container,
                 "--json", str(_m3_json)], env=_phase_env)
                _m3_rep = _read_report(_m3_json)
            else:
                _m3_rc, _m3_rep = _m3_dispatched
            _m3_verdict = "NOT_READY" if _m3_rc == 2 else "FAIL"
            # Even a producer rc=0 cannot bypass the existing strict gates.
            _m3_gates_ok = True
            for _gate, _rel in (
                    ("mixed_signal_cosim_check", "cosim_audit.json"),
                    ("mixed_signal_interface_si_check", "interface_si_audit.json")):
                _gate_json = project / "reports/analog/mixed_signal" / _rel
                _gate_json.unlink(missing_ok=True)
                _gate_rc = _run_phase(
                    "MIXED-SIGNAL M3 (" + _gate + ")", PROGRAMS_DIR / (_gate + ".py"),
                    [str(project), "--require-current-production", "--json", str(_gate_json)],
                    env=_phase_env)
                _gate_rep = _read_report(_gate_json)
                _m3_gates_ok = (_m3_gates_ok and _gate_rc == 0
                                and _gate_rep.get("verdict") == "PASS"
                                and _gate_rep.get("passed") is True)
            if (_m3_rc == 0 and _m3_rep.get("program") == "mixed_signal_m3_run"
                    and _m3_rep.get("verdict") == "PASS" and _m3_gates_ok):
                _m3_verdict = "PASS"
            elif _m3_rc == 0:
                _m3_rc = 1
        else:
            _m3_rc, _m3_verdict = 2, "NOT_READY"
            _m3_rep = {"verdict": "NOT_READY", "reason": "M2 did not pass; M3 not dispatched"}
        plan.append(("mixed_signal_M3", _m3_verdict, _m3_rc))
        reports["mixed_signal_M3"] = _m3_rep
        if _m3_rc == 0 and _m3_verdict == "PASS":
            _m4_json = project / "reports/analog/mixed_signal/signoff_producer_audit.json"
            _m4_json.unlink(missing_ok=True)
            _m4_dispatched = _controller_mixed_step(_execution, project, "M4", _m4_json)
            if _m4_dispatched is None:
                _m4_rc = _run_phase(
                "MIXED-SIGNAL M4 (derived mixed-signal / top-level PV verdict)",
                PROGRAMS_DIR / "mixed_signal_signoff_run.py",
                [str(project), "--top", phase3_top, "--json", str(_m4_json)], env=_phase_env)
                _m4_rep = _read_report(_m4_json)
            else:
                _m4_rc, _m4_rep = _m4_dispatched
            _m4_gate_json = project / "reports/analog/mixed_signal/signoff_audit.json"
            _m4_gate_json.unlink(missing_ok=True)
            _m4_gate_rc = _run_phase(
                "MIXED-SIGNAL M4 (current derivation audit)",
                PROGRAMS_DIR / "mixed_signal_signoff_check.py",
                [str(project), "--require-current-production", "--json", str(_m4_gate_json)],
                env=_phase_env)
            _m4_gate_rep = _read_report(_m4_gate_json)
            if (_m4_rc == 0 and _m4_rep.get("program") == "mixed_signal_signoff_run"
                    and _m4_rep.get("verdict") == "PASS" and _m4_gate_rc == 0
                    and _m4_gate_rep.get("passed") is True
                    and _m4_gate_rep.get("verdict") == "PASS"):
                _m4_verdict = "PASS"
            else:
                _m4_verdict = "NOT_READY" if _m4_rc == 2 else "FAIL"
                if _m4_rc == 0:
                    _m4_rc = 1
        else:
            _m4_rc, _m4_verdict = 2, "NOT_READY"
            _m4_rep = {"verdict": "NOT_READY", "reason": "M3 did not pass; M4 not dispatched"}
        plan.append(("mixed_signal_M4", _m4_verdict, _m4_rc))
        reports["mixed_signal_M4"] = _m4_rep
    else:
        plan.append(("mixed_signal", "SKIPPED", 0))

    # ---------------- What this run signed off AGAINST ----------------
    # Taken here rather than beside the image capture because it reads the
    # run's own tool logs, which do not exist until the phases have run.
    _pdk_rec = _capture_pdk_revision(project, args.container)
    if _pdk_rec.get("refusal"):
        # #2069 — the advisory leads with the SAME token the record carries and
        # the publish gate raises, so "this run was refused for a missing PDK
        # revision" is one greppable string across the three places it is said.
        # Keyed on the record's own `refusal` rather than on `not resolved`, so
        # the runner cannot advise one thing while the record says another.
        advisories.append(
            f"{_pdk_rec['refusal']}: {_pdk_rec.get('reason')} — this run's "
            f"sign-off cannot be re-derived, and benchmark_evidence_publish "
            f"will REFUSE to stage it (see reports/pdk_revision.json)")

    try:
        _derived = _p1id.record_flow_changes(
            project, _p1_docs_after, "vibe_ic_one_shot_runner:after-phase1")
        if _derived:
            advisories.append(
                f"generated L doc(s) rewritten by this run after phase 1, "
                f"recorded as flow derivations: {', '.join(_derived)}")
    except Exception as _exc:                              # noqa: BLE001
        advisories.append(f"flow derivations NOT recorded ({_exc}); a later "
                          f"run may read those rewrites as hand edits")

    # ---------------- Aggregate ----------------
    digital_rows = [(n, v, rc) for n, v, rc in plan
                    if n not in ("analog", "mixed_signal", "mixed_signal_M2",
                                 "mixed_signal_M3", "mixed_signal_M4")
                    and v != "SKIPPED"]
    _ca_verdicts = _completion_audit_verdicts(project)
    _audit_axis = _completion_audit_axis(
        project, phase3_ran=_phase3_ran,
        # PHASE 3's start, not the run's: the audit is phase3's to refresh, and a
        # document written before phase3 began cannot be its refresh.
        started_at=_phase_started.get("phase3", t0))
    if digital_rows:
        overall, _rollup_why = _roll_up(digital_rows, _ca_verdicts,
                                        demoted=_demoted,
                                        audit_axis=_audit_axis)
    else:
        overall, _rollup_why = "FAIL", ["no digital phase ran"]
    import ai_signed_judgement as _ai_judgement
    _ai_scope = ["D1", "1", "4", "5"]
    if not args.skip_analog:
        _ai_scope.extend(("A1", "A2", "A9"))
    if not args.skip_phase3:
        _ai_scope.append("36")
    _ai_pending = _ai_judgement.pending(
        project, tuple(_ai_scope))
    if _ai_pending and overall in ("PASS", "PASS_WITH_WAIVERS"):
        overall = "NOT_MEASURED"
        _rollup_why.extend(_ai_pending.values())
    overall = _demote_for_stale_generated_docs(overall, _p1_stale_why,
                                               _rollup_why)
    # A verdict that moved must say which phase moved it, in the report a reader
    # actually opens — not only on stdout.
    for _why in _rollup_why:
        advisories.append(f"verdict {overall}: {_why}")
    summary = {
        "phase": "vibe-ic",
        "project": str(project),
        **_delivery_route.report_label(project),
        "duration_s": time.time() - t0,
        "halted_at": halted_at or None,
        "phases": [{"name": n, "verdict": v, "rc": rc} for n, v, rc in plan],
        "advisories": advisories,   # v0.3.7 #505 — non-gating notes
        # WHICH IMAGE the run's --container actually executed. Carried in the
        # aggregate report as well as reports/container_image.json so a
        # published number is attributable to a toolchain without a second
        # file lookup.
        "container_image": _img_rec,
        # WHICH PDK REVISION the run signed off against — the other half of
        # the same attribution, and the half nothing recorded before.
        "pdk_revision": _pdk_rec,
        "verdict": overall,
        "ai_judgements": _ai_pending,
        # WHY the roll-up is what it is, phase by phase. Empty for a clean PASS.
        "verdict_reasons": _rollup_why,
        "completion_audit_verdicts": _ca_verdicts,
        # EVERYTHING THE ROLL-UP CONSUMED, so a reader -- including
        # `vibe_ic_entry_guard` -- can replay the same function instead of keeping
        # a second copy of the rule that drifts from it.
        "completion_audit_axis": _audit_axis,
        "demoted_phases": _demoted,
        # FX_STALE_LDOCS — whether the generated L docs were reused,
        # regenerated or refused, and why (None: fewer than 13 existed).
        "phase1_generated_docs": _p1_fresh,
    }
    _fd_bounded = _fd_bounded or _p3_window_ran or _p3_skip_by_exit
    _phase_for_ai = {"D1": "phase1", "1": "phase2", "4": "phase2",
                     "5": "phase2", "A1": "analog", "A2": "analog",
                     "A9": "analog", "36": "phase3"}
    for _sid, _detail in _ai_pending.items():
        for _phase in summary["phases"]:
            if (_phase["name"] == _phase_for_ai[_sid]
                    and _phase["verdict"] in ("PASS", "PASS_WITH_WAIVERS")):
                _phase["verdict"] = "NOT_MEASURED"
                _phase["rc"] = 1
    # v1.6.32: emit canonical final_summary.md (best-effort). Note that
    # phase23_one_shot_runner ALSO calls this; vibe_ic delegates to
    # phase23 today, so the final summary will be regenerated here on
    # the chained-end. Idempotent — generator overwrites.
    if _fd_bounded:
        _fd_disclose("emit_final_summary",
                     "reports/final_summary.md, and the whole-flow "
                     "flow_compliance_check --strict that final_report_generate.py "
                     "runs in order to write it")
        fs_ok = False
    else:
        fs_ok = _pl.emit_final_summary(project, PROGRAMS_DIR)

    # Per-step output view: <project>/steps/<phase>/<stage>/<id>_<slug>/
    # (SYMLINK views + per-step outputs.json + steps/index.json) so EVERY
    # clean-run has a browsable per-step folder and the web dashboard's per-step
    # "📂 open" link resolves. Best-effort — a view builder must never fail a run.
    #
    # Routed through the SHARED `_pl.emit_steps_view` (which every orchestrator
    # now calls) instead of the raw collector import that used to live here and
    # NOWHERE ELSE: the bare `except Exception: pass` also meant a failed build
    # left no trace, so "this run has no steps/" could not be told apart from
    # "this orchestrator never built one". The helper records the outcome in
    # reports/audit/steps_view.json either way.
    if _fd_bounded:
        # The phase runners that DID dispatch have already refreshed their own
        # rows and carried the rest; rebuilding the whole tree here would undo
        # that and restate 70 steps for a run that dispatched a window.
        _fd_disclose("steps_view",
                     "the whole steps/ tree, every phase and stage")
        _sv = {"status": "OK", "bounded": True,
               "note": "not rebuilt: this run declared a window; the phase "
                       "runners refreshed their own rows"}
    else:
        _sv = _pl.emit_steps_view(project, PROGRAMS_DIR,
                                  runner="vibe_ic_one_shot_runner")
    if _sv.get("status") != "OK":
        # Surface it in the top orchestrator's own report too — this is the
        # record a reader actually opens. Non-gating (advisories never move
        # the verdict); `advisories` is the list object already referenced by
        # `summary`, which is serialized further down.
        advisories.append(
            f"steps view NOT built ({_sv.get('status')}): {_sv.get('error')} "
            f"— see reports/audit/{_pl.STEPS_VIEW_REPORT_NAME}")

    # v1.3.51: FINALIZE deliverable self-check — record the completeness state
    # (non-gating) so a run that produces NO RESULT.md can never go silent.
    dsc = _deliverable_self_check(project)
    summary["deliverable_self_check"] = dsc
    if _fd_bounded:
        summary["declared_window"] = {
            "flags": list(_fd_window_flags),
            "entry_step": args.entry_step, "exit_step": args.exit_step,
            "entry_runner": _entry_runner,
        }
        summary["bounded_disclosures"] = _fd_disclosures
        summary["not_refreshed_here"] = sorted(
            _rel for _rel in ("reports/final_summary.md",
                              "reports/audit/phase23_completion_audit.json")
            if not _pl.published_here(project / _rel, t0))

    # FOUR-PHASE ATTRIBUTION — who routed this design, who solved it (the
    # deterministic emitter BY NAME, or the AI skill the runner waived to),
    # which gates ran and what each of them said, and whether anything
    # repaired it.
    #
    # This is what the general flow does to ANY design, so EVERY run gets it,
    # not only a run driven by a benchmark adapter. Measured before this
    # existed: a plain 4-to-1 multiplexer project recorded rtl_gen BLOCKED ->
    # rtl_repair_retry_iter -> rtl_gen PASS with deterministic_generator="multiplexer"
    # in its own step record, and grepping the WHOLE project tree for any
    # attribution artefact returned nothing. Every fact was already on disk
    # and nothing read it.
    #
    # Best-effort by construction: an attribution DESCRIBES the run, so
    # failing the run because the description could not be taken would be
    # worse than the gap it closes. The failure is recorded, never swallowed.
    try:
        import flow_phase_attribution as _fpa           # noqa: PLC0415
        _att = _fpa.attribute(project)
        _fpa.write_report(project, _att)
        summary["phase_attribution"] = _att
    except Exception as _exc:                            # noqa: BLE001
        summary["phase_attribution"] = {
            "attributed": False,
            "reason": f"four-phase attribution unavailable: "
                      f"{type(_exc).__name__}: {_exc}",
        }

    out = _pl.report_path(project, "vibe_ic_one_shot.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    _write_runner_summary(out, summary, project)

    print(f"\n{'='*72}")
    print(f"=== vibe_ic_one_shot_runner DONE — {out}")
    print(f"  overall verdict   : {overall}")
    for _why in _rollup_why:
        print(f"    because         : {_why}")
    if halted_at:
        print(f"  halted at         : {halted_at}")
    for n, v, _ in plan:
        print(f"    {n:8} : {v}")
    for adv in advisories:   # v0.3.7 #505 — non-gating advisories
        print(f"  advisory          : {adv}")
    print(f"  duration          : {summary['duration_s']:.1f}s")
    print(f"  final summary     : {'reports/final_summary.md' if fs_ok else 'NOT generated'}")
    if dsc.get("state") == "COMPLETE":
        print("  deliverable       : RESULT.md present + non-empty (self-check PASS)")
    elif dsc.get("state") not in ("SELF_CHECK_UNAVAILABLE",):
        print(f"  deliverable       : NOT DELIVERED YET — {dsc.get('state')}. "
              f"This run is NOT complete until RESULT.md is authored. "
              f"NO RESULT / empty output = the run FAILED.")
        print(f"  self-verify       : {dsc.get('self_verify_cmd')}")
    if args.dashboard:
        # Final CLI dashboard snapshot — the completed step map inline.
        _final_snap = _cli_snapshot(project)
        if _final_snap.strip():
            print(f"\n  CLI dashboard (final step map):")
            print(_final_snap.rstrip())
    if dash_pid:
        _reachable = _reachable_host(args.dashboard_host)
        print(f"  web dashboard     : http://{_reachable}:"
              f"{args.dashboard_port} still live (final state viewable) — "
              f"stop with: kill {dash_pid}")
    print(f"{'='*72}")
    lock.release()  # explicit; atexit/signal handlers are the backstop
    return 0 if overall in ("PASS", "PASS_WITH_WAIVERS") else 1


if __name__ == "__main__":
    if 'VIBEIC_EXECUTION_CAP_FD' not in os.environ and '--help' not in sys.argv and '-h' not in sys.argv:
        # Exec the isolated canonical issuer. Its only child is this fixed
        # runner, launched with -I so caller PYTHONPATH/sitecustomize cannot
        # intercept the issued credential before canonical entry.
        entry = argparse.ArgumentParser(add_help=False)
        entry.add_argument('project', type=Path)
        entry.add_argument('--route', choices=('ic', 'ip'))
        entry.add_argument('--execution-mode', choices=('default', 'ultra'), default='default')
        entry.add_argument('--receipt-channel-fd', type=int)
        selected, _ = entry.parse_known_args()
        if not selected.project.is_dir():
            print(f'ERROR: not a directory: {selected.project.resolve()}', file=sys.stderr)
            sys.exit(2)
        route_refusal = _delivery_route.admit(selected.project.resolve(), selected.route)
        if route_refusal:
            print(_delivery_route.refusal_message(route_refusal), file=sys.stderr)
            sys.exit(2)
        route = selected.route or _delivery_route.report_label(selected.project)['delivery_route'].lower()
        command = [str(Path(sys.executable).resolve()), '-I', '-S',
                   str(PROGRAMS_DIR / 'execution_authority.py'), '--project', str(selected.project.resolve()),
                   '--route', route, '--execution-mode', selected.execution_mode]
        if selected.receipt_channel_fd is not None:
            command += ['--channel-fd', str(selected.receipt_channel_fd)]
        os.execv(command[0], command + ['--', *sys.argv[1:]])
    sys.exit(main())
