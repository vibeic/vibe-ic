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
import shutil
import subprocess
import sys
import time
import uuid
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
_RUNTIME_PROGRAM_TREE = None


def _verify_runtime_command(command) -> None:
    if _RUNTIME_PROGRAM_TREE is not None:
        _RUNTIME_PROGRAM_TREE.verify_command(command)


def _activate_runtime_program_tree(project: Path) -> None:
    global PROGRAMS_DIR, _RUNTIME_PROGRAM_TREE
    import runtime_program_tree as _rpt
    tree = _rpt.activate(project, PROGRAMS_DIR, Path(__file__))
    _RUNTIME_PROGRAM_TREE = tree
    PROGRAMS_DIR = tree.programs_dir
    globals()["__file__"] = str(PROGRAMS_DIR / "vibe_ic_one_shot_runner.py")


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
    # An optional operator pin must not leave an immutable observed image
    # without the match proof required by ordinary downstream PDK readers.
    # Ask the existing verifier; never manufacture image_match from PASS.
    if (not require_image and rec.get("verdict") == "PASS"
            and _pin.reference_digest(str(_img or ""))):
        try:
            rec = _cip.verify(container, str(_img))
            rec["pin_source"] = "observed_immutable_image"
        except Exception as exc:
            rec = {**rec, "verdict": "SKIP", "image_match": False,
                   "reason": "observed image pin verification failed: "
                             f"{type(exc).__name__}: {exc}"}
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
        _verify_runtime_command(cmd)
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
        command = [sys.executable, str(dash), str(project), "--once", "--no-color"]
        _verify_runtime_command(command)
        cp = subprocess.run(
            command,
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
                     knobs: Optional[Dict[str, Any]] = None, *,
                     checkpoint: bool = False) -> Tuple[bool, str]:
    """Select prompt/docs input extraction or an unread expert answer's second pass.
    Return (run, mode); explicit skips and current supplied-only L docs remain intact.
    Missing extraction outcomes recover through docs mode only with design input."""
    if force_skip:
        return (False, "")
    gd = _pl.generated_docs_dir(project)
    L_count = len(list(gd.glob("L*.json"))) if gd.is_dir() else 0
    # Already has the full L-doc set → the EXTRACTION has nothing to do.
    if L_count >= 13:
        # Existing L docs may still have an unread expert answer.
        pending, _why = _expert_answer_pending(project)
        if pending:
            # Recover absent extraction; preserve known failures and valid legacy outcomes.
            path, _legacy = _pl.report_path_for_reading(project, "phase1_one_shot.json")
            try:
                summary = json.loads(path.read_text())
                if not isinstance(summary, dict):
                    raise ValueError("first-pass summary is not an object")
                pass1 = summary.get("pass1")
                verdicts = ("PASS", "PASS_WITH_WAIVERS", "FAIL")
                if isinstance(pass1, dict):
                    available = (pass1.get("verdict") in verdicts
                                 and type(pass1.get("rc")) is int
                                 and pass1["rc"] >= 0)
                else:
                    available = (summary.get("mode") != "expert_second_pass"
                                 and summary.get("verdict") in verdicts)
            except (OSError, ValueError):
                available = False
            if not available and _design_input_present(project):
                print("[phase1] RECOVER_PHASE1_FIRST_PASS — no usable extraction "
                      "summary to carry; running docs mode before expert consumption")
                return (True, "docs")
            return (True, _P1_MODE_EXPERT_SECOND_PASS)
        # Reuse requires current producer identity, not L-doc existence.
        # Edited documents retain the existing refusal path.
        fresh = (_phase1_checkpoint_freshness(project, knobs) if checkpoint
                 else _phase1_freshness(project, knobs))
        if fresh["state"] == _p1id.REUSE or (
                checkpoint and fresh["state"] == _p1id.REVALIDATE):
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


def _phase1_checkpoint_freshness(project: Path,
                               knobs: Optional[Dict[str, Any]] = None) -> dict:
    """Nominate intact historical outputs for the current D1 consumer.

    Source drift is disclosed, never treated as a current producer. Only the
    complete consumer and content-bound expert judgement can accept reuse.
    """
    fresh = _phase1_freshness(project, knobs)
    if fresh.get('reason') == _p1id.PRODUCER_CHANGED:
        try:
            return _p1id.assess(project, PROGRAMS_DIR, knobs, checkpoint=True)
        except Exception as exc:
            return {"state": _p1id.REGENERATE,
                    "reason": _p1id.NO_PRODUCER_IDENTITY,
                    "why": f"the retained checkpoint could not be read ({exc})"}
    return fresh


def _standalone_rtl_provenance(project: Path, knobs: Dict[str, Any],
                               original_inputs: dict) -> dict:
    """BLOCKING source integrity for bounded RTL; never qualifies full D1."""
    fresh = _phase1_checkpoint_freshness(project, knobs)
    if fresh['state'] not in (_p1id.REUSE, _p1id.REVALIDATE):
        raise ValueError(f"{fresh['reason']}: {fresh['why']}")
    now = _p1id.input_tree_snapshot(project)
    if any(value[0] is None or now.get(name, (None,))[0] != value[0]
           for name, value in original_inputs.items()):
        raise ValueError('original design input or supplied RTL changed')
    documents = _p1id.generated_docs(project)
    if len(documents) < 13 or any(
            not isinstance(json.loads(path.read_text()), dict) for path in documents):
        raise ValueError('produced Phase1 documents are incomplete or malformed')
    import emit_attestation
    provenance = emit_attestation.phase1_provenance(project)
    if provenance.get('ran') is not True:
        raise ValueError('produced Phase1 provenance is absent')
    return provenance


def _revalidate_phase1_checkpoint(project: Path, knobs: Dict[str, Any]) -> dict:
    """Recheck a current D1 checkpoint; this call produces no L documents.

    Keep the original producer identity and write attribution. A signature is
    one input to the unchanged complete consumer, never its replacement.
    """
    import _flow_yaml
    import ai_signed_judgement as ai
    import execution_backend_gates as gates
    import execution_backend_worker as worker
    import step_output_collector as versions

    project = Path(project).resolve()
    row = next(r for r in _flow_yaml.load()['steps'] if str(r['id']) == 'D1')
    inputs = worker._declared_input_files(project, row.get('required_inputs', ()))
    prior = next((r for r in versions._read_index(project)['steps']
                  if str(r.get('id')) == 'D1'), None)
    root = versions._versions_root(project)
    previous = root / prior['folder'] if prior else None
    written = (previous / 'written.json').read_bytes() if (
        previous is not None and (previous / 'written.json').is_file()) else None
    authority = _p1id.sidecar_dir(project) / _p1id._si.SIDECAR
    checkpoint = {'producer_started': False, 'producer_reused': True,
                  'prior_folder': prior.get('folder') if prior else None}
    error = None
    try:
        identity = authority.read_bytes()
        checkpoint['producer_identity_sha256'] = hashlib.sha256(identity).hexdigest()
        bound = gates.contracts(project, row)
        if not inputs:
            raise ValueError('D1 checkpoint has no resolved input identity')
        freshness = _phase1_checkpoint_freshness(project, knobs)
        checkpoint['source_assessment'] = freshness
        checkpoint['producer_current'] = freshness['state'] == _p1id.REUSE
        if freshness['state'] not in (_p1id.REUSE, _p1id.REVALIDATE):
            raise ValueError('D1 retained checkpoint is no longer valid')
        if previous is not None and (previous / 'outputs.json').is_file():
            retained = json.loads((previous / 'outputs.json').read_text())
            if 'inputs' in retained and retained['inputs'] != inputs:
                raise ValueError('D1 retained checkpoint inputs changed')
            for output in retained.get('outputs', ()):
                path = project / output['rel']
                if not path.is_file() or versions._sha(path) != output['sha256']:
                    raise ValueError('D1 retained checkpoint output changed: ' + output['rel'])
    except (OSError, ValueError, KeyError) as exc:
        error = f'D1_CHECKPOINT_BINDING_REFUSED: {exc}'
    except gates.em.Refusal as exc:
        error = f'D1_CHECKPOINT_BINDING_REFUSED: {exc}'

    attempt = versions.begin_step(project, 'D1', inputs)
    consumer = None
    observed_consumer = None
    try:
        with versions.active_steps(project, [attempt]):
            if authority.is_file():
                versions.retain_before(project, 'D1', [authority])
            if error is None:
                consumer = gates.evaluate(project, row)
                observed_consumer = consumer
                # A measured FAIL stays FAIL even if a gate also changed data.
                if consumer['status'] == 'PASS':
                    outputs = gates.contracts(project, row)
                    if (outputs != bound or authority.read_bytes() != identity
                            or worker._declared_input_files(
                                project, row.get('required_inputs', ())) != inputs
                            or _phase1_checkpoint_freshness(project, knobs) != freshness
                            or not ai.check(project, 'D1')[0]):
                        error = 'D1_CHECKPOINT_BINDING_REFUSED: evidence changed during revalidation'
                    else:
                        consumer['outputs'] = outputs
            status = consumer['status'] if consumer is not None else 'NOT_MEASURED'
            if error is not None and status != 'FAIL':
                status = 'NOT_MEASURED'
                if consumer is not None:
                    consumer = {**consumer, 'status': status,
                                'step': {**consumer.get('step', {}), 'status': status,
                                         'reason_class': 'checkpoint_binding_refused',
                                         'reasons': [error]}}
            if written is not None:
                # Byte-for-byte old attribution, explicitly cited as reused;
                # do not publish a new producer observation for a no-op.
                (root / attempt['folder'] / 'written.json').write_bytes(written)
                checkpoint['written_sha256'] = hashlib.sha256(written).hexdigest()
            saved = versions.finish_step(
                project, attempt, verdict=status,
                result={'runner': 'vibe_ic_one_shot_runner',
                        'site': 'phase1_checkpoint_revalidation',
                        'checkpoint': checkpoint, 'detail': error or '',
                        'observed_canonical_consumer': observed_consumer,
                        'canonical_consumer': consumer},
                canonical_pass=(status == 'PASS'))
    except BaseException as exc:
        if not (root / attempt['folder'] / 'outputs.json').exists():
            versions.finish_step(project, attempt, verdict='INTERRUPTED',
                                 result={'checkpoint': checkpoint,
                                         'detail': f'{type(exc).__name__}: {exc}'})
        raise
    if saved['capture_errors']:
        raise OSError('D1 checkpoint revalidation could not be retained: ' +
                      '; '.join(saved['capture_errors']))
    reasons = (consumer or {}).get('step', {}).get('reasons', ())
    return {'verdict': status, 'detail': error or '; '.join(reasons),
            'folder': saved['folder'], 'producer_reused': True}



def _revalidate_step5_checkpoint(project: Path) -> Optional[dict]:
    """Consume a signed, pending native Step5 checkpoint without rerunning it.

    This is the existing Phase3-entry handoff, not a producer invocation.
    Keep its original write attribution; the unchanged complete consumer owns
    acceptance. Other partial backend entries keep their existing scope.
    """
    import _flow_yaml
    import ai_signed_judgement as ai
    import execution_backend_gates as gates
    import execution_backend_worker as worker
    import step_output_collector as versions

    project = Path(project).resolve()
    prior = next((r for r in versions._read_index(project)['steps']
                  if str(r.get('id')) == '5'), None)
    if prior is None:
        return None
    root = versions._versions_root(project)
    previous = root / prior['folder']
    try:
        retained_bytes = (previous / 'outputs.json').read_bytes()
        retained = json.loads(retained_bytes)
    except (OSError, ValueError):
        return None
    result = retained.get('result') or {}
    old_consumer = result.get('canonical_consumer') or {}
    pending = (old_consumer.get('step') or {}).get('reason_class') == 'awaiting_signed_judgement'
    if not pending and not retained.get('canonical_pass'):
        if result.get('site') == 'step5_checkpoint_revalidation':
            return {'verdict': retained['status'], 'folder': prior['folder'],
                    'detail': result.get('detail', ''), 'producer_reused': True}
        return None

    checkpoint = {'producer_started': False, 'producer_reused': True,
                  'prior_folder': prior['folder'],
                  'prior_record_sha256': hashlib.sha256(retained_bytes).hexdigest()}
    try:
        row = next(r for r in _flow_yaml.load()['steps'] if str(r['id']) == '5')
        inputs = worker._declared_input_files(project, row.get('required_inputs', ()))
        if not inputs or retained.get('inputs') != inputs or retained.get('capture_errors'):
            raise ValueError('original producer input identity is absent or changed')
        if not retained.get('canonical_pass'):
            own = result.get('step_rows') or []
            if (retained.get('status') != 'NOT_MEASURED'
                    or old_consumer.get('status') != 'NOT_MEASURED'
                    or result.get('invocation_status') != 'PASS' or not own
                    or any(r.get('status') != 'PASS' for r in own)):
                raise ValueError('the pending native producer did not complete successfully')
        written = (previous / 'written.json').read_bytes()
        write_record = json.loads(written)
        if str(write_record.get('id')) != '5' or not write_record.get('produced'):
            raise ValueError('original producer write attribution is absent')
        if not retained.get('outputs'):
            raise ValueError('original native output hashes are absent')
        for output in retained['outputs']:
            current = project / output['rel']
            original = previous / output['snapshot']
            if (not current.is_file() or current.is_symlink()
                    or versions._sha(current) != output['sha256']
                    or not original.is_file() or versions._sha(original) != output['sha256']):
                raise ValueError('original native output changed: ' + output['rel'])
        bound = gates.contracts(project, row)
        credit, detail = ai.check(project, '5')
        if not credit:
            raise ValueError(detail)
        evidence = ai.evidence_sha256(project, '5')
        if retained.get('canonical_pass'):
            return {'verdict': 'PASS', 'folder': prior['folder'],
                    'detail': 'current complete Step5 acceptance retained',
                    'producer_reused': True}
    except (OSError, ValueError, KeyError, gates.em.Refusal) as exc:
        return {'verdict': 'NOT_MEASURED', 'folder': prior['folder'],
                'detail': f'STEP5_CHECKPOINT_BINDING_REFUSED: {exc}',
                'producer_reused': True}

    # Retain the resolved preimage before any complete consumer can mutate it.
    # Starting an attempt does not publish a new producer or replace its index.
    attempt = versions.begin_step(project, '5', inputs)
    checkpoint['written_sha256'] = hashlib.sha256(written).hexdigest()
    try:
        with versions.active_steps(project, [attempt]):
            (root / attempt['folder'] / 'written.json').write_bytes(written)
            consumer = gates.evaluate(project, row)
            observed = consumer
            error = ''
            # A measured scientific FAIL stays FAIL, including during a changed readset.
            if consumer['status'] == 'PASS':
                try:
                    if (gates.contracts(project, row) != bound
                            or worker._declared_input_files(project, row.get('required_inputs', ())) != inputs
                            or (previous / 'written.json').read_bytes() != written
                            or (previous / 'outputs.json').read_bytes() != retained_bytes
                            or ai.evidence_sha256(project, '5') != evidence
                            or not ai.check(project, '5')[0]
                            or any(not (project / r['rel']).is_file()
                                   or (project / r['rel']).is_symlink()
                                   or versions._sha(project / r['rel']) != r['sha256']
                                   for r in retained['outputs'])):
                        raise ValueError('evidence changed during complete revalidation')
                    consumer['outputs'] = bound
                except (OSError, ValueError, KeyError, gates.em.Refusal) as exc:
                    error = f'STEP5_CHECKPOINT_BINDING_REFUSED: {exc}'
                    consumer = {**consumer, 'status': 'NOT_MEASURED',
                                'step': {**consumer['step'], 'status': 'NOT_MEASURED',
                                         'reason_class': 'checkpoint_binding_refused',
                                         'reasons': [error]}}
            saved = versions.finish_step(
                project, attempt, verdict=consumer['status'],
                result={'runner': 'vibe_ic_one_shot_runner',
                        'site': 'step5_checkpoint_revalidation', 'checkpoint': checkpoint,
                        'detail': error, 'observed_canonical_consumer': observed,
                        'canonical_consumer': consumer},
                canonical_pass=consumer['status'] == 'PASS')
    except BaseException as exc:
        if not (root / attempt['folder'] / 'outputs.json').exists():
            versions.finish_step(project, attempt, verdict='INTERRUPTED',
                                 result={'checkpoint': checkpoint,
                                         'detail': f'{type(exc).__name__}: {exc}'})
        raise
    if saved['capture_errors']:
        raise OSError('Step5 revalidation could not be retained: ' + '; '.join(saved['capture_errors']))
    return {'verdict': saved['status'], 'folder': saved['folder'],
            'detail': error or '; '.join(consumer['step'].get('reasons', ())),
            'producer_reused': True}


def _complete_step7_sdc(project: Path, top: str, pdk_name: str,
                        container: str) -> dict:
    """Refresh stale Step7 SDC through its existing author and full consumer."""
    import _flow_yaml
    import design_one_shot_runner as design
    import execution_backend_gates as gates
    import phase3_one_shot_runner as phase3
    import step_output_collector as versions
    import step_preflight as preflight
    from _ppa import timing

    try:
        pdk = design._phase2_pdk_config(project, pdk_name)
        current, stale = timing.read_step7_asic_sdc(phase3, project, top, pdk)
        if current is not None:
            prior = versions.latest_pass(project, '7')
            selected = next((row for row in versions._read_index(project)['steps']
                             if str(row['id']) == '7'), None)
            consumer = ((prior or {}).get('result') or {}).get('canonical_consumer') or {}
            row7 = next(row for row in _flow_yaml.load()['steps'] if str(row['id']) == '7')
            try:
                outputs = gates.contracts(project, row7)
            except (OSError, ValueError, RuntimeError):
                outputs = None
            if (prior and selected and prior['folder'] == selected['folder']
                    and prior.get('current_inputs') and prior.get('canonical_pass')
                    and prior['status'] == 'PASS' and consumer.get('status') == 'PASS'
                    and outputs and outputs == consumer.get('outputs')):
                return {'verdict': 'PASS', 'producer_reused': True,
                        'detail': 'current complete Step7 and input-bound SDC'}
        admission = preflight.entry_admission(project, 'design_one_shot_runner', '7')
        if not admission['admitted']:
            return {'verdict': 'NOT_MEASURED', 'detail': admission['reason']}

        def produce_sdc():
            timing.emit_step7_asic_sdc(phase3, project, top, pdk, container)
            current, error = timing.read_step7_asic_sdc(phase3, project, top, pdk)
            return {'rc': 0 if current is not None else 2,
                    'detail': error or 'Step7 SDC refreshed by its canonical author',
                    'stale_input': stale}

        began = time.time()
        preflight.retained_call(project, '7', produce_sdc, canonical_acceptance=True)
        current = next((row for row in versions.current_acceptance(project, began)
                        if str(row['id']) == '7'), None)
    except (OSError, ValueError, RuntimeError) as exc:
        return {'verdict': 'NOT_MEASURED', 'detail': str(exc)}
    if current is None:
        return {'verdict': 'NOT_MEASURED',
                'detail': 'Step7 refresh published no complete consumer'}
    consumer = (current.get('result') or {}).get('canonical_consumer') or {}
    status = ('PASS' if current.get('canonical_pass') and current['status'] == 'PASS'
              and consumer.get('status') == 'PASS' else
              'FAIL' if current['status'] == 'FAIL' else 'NOT_MEASURED')
    return {'verdict': status, 'folder': current['folder'],
            'detail': '; '.join(consumer.get('step', {}).get('reasons', ()))
                      or str(current['result'].get('producer_return', {}))}


def _complete_step14_handoff(project: Path) -> dict:
    """Run the existing synthesis audits and retain their complete consumer.

    This closes the Phase2 handoff before the existing Phase3 head15. It does
    not synthesize a new netlist or add a runner entry at canonical Step14.
    """
    import flow_declared_producer_run as declared
    import step_output_collector as versions
    import step_preflight as preflight

    def produce_handoff():
        census = declared.run_for_step(project, '14', timeout=_pl.audit_timeout_s(project))
        from execution_backend_producers import _current_step_producer_authority
        allowed, reason, authority = _current_step_producer_authority(census, project=project)
        return {'rc': 0 if allowed else 1 if authority == 'FAIL' else 2,
                'authority_verdict': authority, 'authority_detail': reason,
                'current_step_producers': census}

    preflight.retained_call(project, '14', produce_handoff, canonical_acceptance=True)
    current = next(r for r in versions._read_index(project)['steps'] if str(r['id']) == '14')
    record = json.loads((versions._versions_root(project) / current['folder'] / 'outputs.json').read_text())
    consumer = record['result'].get('canonical_consumer') or {}
    status = ('PASS' if record.get('canonical_pass') and record['status'] == 'PASS'
              else 'FAIL' if record['status'] == 'FAIL' else 'NOT_MEASURED')
    return {'verdict': status, 'folder': current['folder'],
            'detail': '; '.join(consumer.get('step', {}).get('reasons', ()))
                      or str(record['result'].get('producer_return', {}))}


def _current_step9_checkpoint(project: Path, *,
                              require_canonical: bool = False
                              ) -> tuple[dict | None, str | None]:
    """Bind the current native synthesis state used by downstream owners.

    Step 9 also measures an area budget.  An absent design-owned budget makes
    that *row* NOT_MEASURED, but does not invalidate a receipt-bound mapped
    netlist whose native handoff consumer passes.  DFT and pre-layout consume
    that handoff, not the unrelated area comparison.
    """
    import step_output_collector as versions
    import synth_handoff_netlist_check as handoff

    pointer = next((row for row in versions._read_index(project).get('steps', ())
                    if str(row.get('id')) == '9'), None)
    if not pointer or not pointer.get('folder'):
        return None, 'requires a current Step9 native synthesis record'
    try:
        prior = json.loads((versions._versions_root(project)
                            / pointer['folder'] / 'outputs.json').read_text())
        if require_canonical:
            latest = versions.latest_pass(project, '9')
            consumer = ((latest or {}).get('result') or {}).get(
                'canonical_consumer') or {}
            if (not latest or latest.get('folder') != pointer['folder']
                    or not latest.get('current_inputs')
                    or not latest.get('canonical_pass')
                    or latest.get('status') != 'PASS'
                    or consumer.get('status') != 'PASS'):
                return None, 'requires the current canonical Step9 checkpoint'
            import _flow_yaml
            import execution_backend_gates as gates

            row9 = next(row for row in _flow_yaml.load()['steps']
                        if str(row['id']) == '9')
            if consumer.get('outputs') != gates.contracts(project, row9):
                return None, 'requires the current canonical Step9 checkpoint'
        bound = handoff.bound_handoff(project)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if prior.get('status') == 'FAIL':
        return None, 'latest Step9 producer failed'
    if not isinstance(bound, dict) or bound.get('verdict') != 'PASS':
        findings = '; '.join((bound or {}).get('findings', ()))
        return None, findings or 'current native synthesis handoff is not PASS'
    declared = next((row for row in prior.get('outputs', ())
                     if row.get('rel') == 'phase2/stage2/synth/netlist.v'), None)
    canonical = Path(str(bound.get('canonical') or ''))
    if (not declared or not canonical.is_file()
            or versions._sha(canonical) != declared.get('sha256')
            or bound.get('netlist_sha256') != declared.get('sha256')):
        return None, 'Step9 versioned netlist no longer matches its native handoff'
    return {'step9_record': prior, 'native_handoff': bound}, None


def _complete_step10_prelayout(project: Path, top: str, pdk_name: str,
                              container: str) -> dict:
    """Resume D26 using functional timing on the current adopted netlist.

    The retained Step10 call remains the functional baseline. When scan is
    required, an additional functional-mode STAPrePNR arm measures the D24
    subject. Shift/capture timing belongs to D49/D70, not this pre-route step.
    """
    import _atomic_artefact as atomic
    import design_one_shot_runner as design
    import librelane_contract as contract
    import phase3_one_shot_runner as phase3
    import step_output_collector as versions
    import synth_handoff_netlist_check as handoff

    project = Path(project).resolve()
    selected_d26 = _flow109_selected_row('D26')
    receipt_path = project / 'reports/flow109/d26_scan_mode.json'
    receipt = {
        'schema': 'vibeic.flow109.d26-timing-modes.v1',
        'step_id': 'D26', 'position': 38, 'top': top,
        'aggregate_status': 'NOT_MEASURED', 'modes_measured': [],
        'functional_baseline': {'status': 'NOT_MEASURED'},
        'post_scan_arms': {},
        'scan': {'applicability': 'UNKNOWN', 'status': 'NOT_MEASURED'},
    }

    def publish(status: str, detail: str, *, folder=None) -> dict:
        if not selected_d26:
            answer = {'verdict': status, 'detail': detail}
            if folder is not None:
                answer['folder'] = folder
            return answer
        receipt['aggregate_status'] = status
        receipt['detail'] = detail
        atomic.write_json(receipt_path, receipt)
        ref = {'path': str(receipt_path.relative_to(project)),
               'sha256': contract.digest(receipt_path)}
        answer = {'verdict': status, 'detail': detail,
                  'timing_modes_receipt': ref}
        if folder is not None:
            answer['folder'] = folder
        return answer

    def rooted_file(value, label: str) -> Path:
        if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
            raise ValueError(f'D26_SCAN_INPUT_INVALID: {label}')
        raw = Path(os.fspath(value))
        candidate = raw if raw.is_absolute() else project / raw
        resolved = candidate.resolve(strict=False)
        if (candidate.is_symlink() or not resolved.is_relative_to(project)
                or not resolved.is_file() or resolved.stat().st_size <= 0):
            raise ValueError(f'D26_SCAN_INPUT_FOREIGN_OR_ABSENT: {label}')
        return resolved

    def file_ref(path: Path) -> dict:
        return {'path': str(path.relative_to(project)),
                'sha256': contract.digest(path)}

    prior, error = _current_step9_checkpoint(project, require_canonical=True)
    if error:
        return publish('NOT_MEASURED', 'Step10 ' + error)
    bound = handoff.bound_handoff(project)
    if not bound or bound['verdict'] != 'PASS':
        status = (bound or {}).get('verdict', 'NOT_MEASURED')
        return publish(status, '; '.join((bound or {}).get('findings', ()))
                       or 'Step10 requires the current native synthesis handoff')
    if Path(bound['mapped']).name != f'{top}_synth.v':
        return publish('NOT_MEASURED',
                       'Step10 top differs from the current native synthesis handoff')

    began = time.time()
    try:
        pdk = design._phase2_pdk_config(project, pdk_name)
        result = phase3.step_prelayout_signoff(
            project, top, pdk, container)
    except (OSError, ValueError, RuntimeError) as exc:
        return publish('NOT_MEASURED', str(exc))
    current = next((row for row in versions.current_acceptance(project, began)
                    if str(row['id']) == '10'), None)
    if current is None:
        status = 'FAIL' if result.status == 'FAIL' else 'NOT_MEASURED'
        receipt['functional_baseline'].update(
            status=status, producer_status=result.status, canonical_pass=False,
            current_inputs=False, canonical_consumer_status=None)
        return publish(status, result.detail or 'Step10 published no complete consumer')
    status = ('PASS' if current.get('canonical_pass') and current['status'] == 'PASS'
              else 'FAIL' if current['status'] == 'FAIL' else 'NOT_MEASURED')
    consumer = (current.get('result') or {}).get('canonical_consumer')
    if not isinstance(consumer, dict):
        status = 'FAIL' if current['status'] == 'FAIL' else 'NOT_MEASURED'
        receipt['functional_baseline'].update(
            status=status, folder=current.get('folder'),
            canonical_pass=bool(current.get('canonical_pass')),
            current_inputs=bool(current.get('current_inputs')),
            canonical_consumer_status=None)
        return publish(status, 'Step10 has no complete canonical consumer',
                       folder=current.get('folder'))
    baseline_detail = ('; '.join(consumer.get('step', {}).get('reasons', ()))
                       or result.detail)
    receipt['functional_baseline'] = {
        'status': status, 'folder': current['folder'],
        'canonical_pass': bool(current.get('canonical_pass')),
        'current_inputs': bool(current.get('current_inputs')),
        'canonical_consumer_status': consumer.get('status'),
        'detail': baseline_detail,
    }
    if status in ('PASS', 'FAIL'):
        receipt['modes_measured'].append('functional_baseline')

    # This function also serves the legacy/native Step10 entry.  Preserve that
    # exact API and behavior unless the validated public Flow109 request owns
    # D26; only D26 has the two-mode receipt contract.
    if not selected_d26:
        return {'verdict': status, 'folder': current['folder'],
                'detail': baseline_detail}
    if (status == 'PASS'
            and (not current.get('current_inputs') or consumer.get('status') != 'PASS')):
        receipt['functional_baseline']['status'] = 'NOT_MEASURED'
        receipt['modes_measured'].remove('functional_baseline')
        return publish('NOT_MEASURED',
                       'D26 functional baseline is not current/canonical',
                       folder=current['folder'])

    # D09 is the only authority for whether scan applies.  Missing or invalid
    # source is unknown, never an inferred requires_scan:false.
    try:
        import fault_scan_chain_insert as scan
        planned, problems = scan.load_d09_dft_contract(project)
        if planned is None:
            receipt['scan']['reason'] = '; '.join(problems or ['D09 binding absent'])
            aggregate = 'FAIL' if status == 'FAIL' else 'NOT_MEASURED'
            return publish(aggregate, 'D26 scan applicability is unresolved',
                           folder=current['folder'])
        receipt['scan']['d09_binding'] = planned
        if planned['intent']['requires_scan'] is False:
            receipt['scan'].update(applicability='NOT_APPLICABLE',
                                   status='NOT_APPLICABLE',
                                   reason='D09_REQUIRES_SCAN_DISABLED')
            return publish(status, baseline_detail, folder=current['folder'])
        clock, reset, active_low = design.derive_dft_clock_reset(project)
        planned, problems = scan.load_d09_dft_contract(
            project, expected_clock=clock or None, expected_reset=reset or None,
            reset_active_low=active_low if reset else False)
        if planned is None or problems or not clock or not reset:
            receipt['scan']['reason'] = '; '.join(
                problems or ['actual functional clock/reset is unresolved'])
            aggregate = 'FAIL' if status == 'FAIL' else 'NOT_MEASURED'
            return publish(aggregate, 'D26 scan authority does not match actual clock/reset',
                           folder=current['folder'])
        receipt['scan'].update(applicability='APPLICABLE', d09_binding=planned)
        if status != 'PASS':
            receipt['scan']['reason'] = 'functional baseline did not pass'
            return publish(status, baseline_detail, folder=current['folder'])

        import lec_gate_netlist_select as netlists
        adopted, note, is_scan = netlists.pnr_consumed_netlist(project, top)
        adopted = rooted_file(adopted, 'D24 adopted post-scan netlist')
        adopted_ref = file_ref(adopted)
        d24 = versions.latest_pass(project, '12')
        d24_outputs = ((d24 or {}).get('outputs') or [])
        retained = [item for item in d24_outputs
                    if item.get('rel') == adopted_ref['path']]
        d24_consumer = (((d24 or {}).get('result') or {}).get('canonical_consumer')
                        or {})
        if (is_scan is not True or not d24 or d24.get('status') != 'PASS'
                or not d24.get('canonical_pass') or not d24.get('current_inputs')
                or d24_consumer.get('status') != 'PASS' or len(retained) != 1
                or retained[0].get('sha256') != adopted_ref['sha256']):
            raise ValueError('D26_D24_ADOPTED_NETLIST_NOT_CURRENT')
        receipt['scan']['adopted_d24'] = {
            **adopted_ref, 'current': True, 'is_scan_inserted': True,
            'native_step': '12', 'flow109_step': 'D24', 'position': 36,
            'resolver_note': note, 'folder': d24.get('folder'),
        }

        # Derive functional case controls from the source-bound native roles;
        # the clock/period remain the already-passing functional Step7 deck.
        functional_gate_path = rooted_file(
            'phase3/librelane/prelayout/gates/step8_sdc_opensta.json',
            'functional prelayout SDC gate')
        functional_gate = json.loads(functional_gate_path.read_text())
        functional_sdc = rooted_file(functional_gate.get('sdc'), 'functional SDC')
        if (functional_gate.get('verdict') != 'PASS'
                or functional_gate.get('sdc_sha256') != contract.digest(functional_sdc)):
            raise ValueError('D26_FUNCTIONAL_CONSTRAINT_NOT_CURRENT')
        intent = planned['intent']
        expected_roles = {'scan_enable', 'scan_in', 'scan_out', 'test', 'tck'}
        if set(intent.get('test_port_def') or {}) != expected_roles:
            raise ValueError('D26_D09_FIVE_ROLE_AUTHORITY_INVALID')
        native_ports = {role: item.get('native') for role, item in
                        intent['test_port_def'].items()}
        selector = intent['test_mode']['clock_select']
        test_port = selector.get('native')
        shift_port = native_ports.get('scan_enable')
        scan_in_port = native_ports.get('scan_in')
        scan_clock_port = native_ports.get('tck')
        reset_authority = intent['test_mode'].get('reset') or {}
        reset_port = reset_authority.get('signal')
        controls = (test_port, shift_port, scan_in_port, scan_clock_port,
                    reset_port)
        if (any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', str(port or ''))
                for port in controls)
                or len(set(controls)) != len(controls)
                or selector.get('functional_value') != 0
                or selector.get('scan_value') != 1
                or intent['test_mode'].get('scan_clock') != scan_clock_port
                or reset_authority.get('active_level') not in (0, 1)):
            raise ValueError('D26_FUNCTIONAL_CASE_AUTHORITY_INVALID')
        reset_deasserted = 1 - reset_authority['active_level']
        derived_sdc = project / 'reports/flow109/d26_timing/functional_post_scan.sdc'
        functional_text = functional_sdc.read_text()
        if functional_text and not functional_text.endswith('\n'):
            functional_text += '\n'
        functional_text += (
            '# D26 source-bound post-scan functional mode\n'
            f'# D09 path: {planned["path"]}\n'
            f'# D09 sha256: {planned["sha256"]}\n'
            f'set_case_analysis 0 [get_ports {{{test_port}}}]\n'
            f'set_case_analysis 0 [get_ports {{{shift_port}}}]\n'
            f'set_case_analysis 0 [get_ports {{{scan_in_port}}}]\n'
            f'set_case_analysis 0 [get_ports {{{scan_clock_port}}}]\n'
            f'set_case_analysis {reset_deasserted} '
            f'[get_ports {{{reset_port}}}]\n')
        atomic.write_text(derived_sdc, functional_text)
        functional_constraint = {
            **file_ref(derived_sdc), 'mode': 'functional',
            'base_sdc': file_ref(functional_sdc),
            'clock': intent['test_mode']['clock'],
            'clock_select': test_port, 'clock_select_value': 0,
            'scan_enable': shift_port, 'scan_enable_value': 0,
            'scan_input': scan_in_port, 'scan_input_value': 0,
            'scan_clock': scan_clock_port, 'scan_clock_value': 0,
            'reset': reset_port, 'reset_value': reset_deasserted,
            'd09_path': planned['path'], 'd09_sha256': planned['sha256'],
        }

        image = contract.resolve_image(project)
        pdk_root = Path(contract.pdk_root_resolution(
            project, str(pdk.name), image=image)['path'])
        if not pdk_root.is_dir():
            raise ValueError('D26_PDK_ROOT_MISSING')
        mounts = [(pdk_root, '/pdk')]
        rtl = sorted(_pl.rtl_dir(project).glob('*.sv')) + \
            sorted(_pl.rtl_dir(project).glob('*.v'))
        stem = Path(str(getattr(pdk, 'liberty', ''))).stem
        scl = stem.split('__', 1)[0] if '__' in stem else None
        import librelane_prelayout as prelayout
        gates_root = project / 'reports/flow109/d26_timing'

        def run_arm(name: str, sdc: Path, constraint_record: dict) -> dict:
            folder = prelayout.run_prelayout(
                project, image, str(pdk.name), top, adopted, sdc, rtl,
                arm='d26_post_scan_' + name, std_cell_library=scl,
                mounts=mounts, pdk_root='/pdk')
            native_receipt = contract.validate_step_receipt(
                folder, 'OpenROAD.STAPrePNR')
            config = json.loads((folder / 'config.json').read_text())
            state = json.loads((folder / 'state_out.json').read_text())
            if (Path(str(config.get('PNR_SDC_FILE') or '')).resolve() != sdc
                    or Path(str(state.get('nl') or '')).resolve() != adopted):
                raise ValueError(f'D26_{name.upper()}_NATIVE_INPUT_MISMATCH')
            sdc_path = gates_root / f'{name}_sdc_gate.json'
            slack_path = gates_root / f'{name}_slack_gate.json'
            sdc_gate = prelayout.judge_sdc(folder, config, sdc, sdc_path)
            slack_gate = prelayout.judge_slack(folder, slack_path)
            if (sdc_gate.get('netlist_sha256') != adopted_ref['sha256']
                    or sdc_gate.get('sdc_sha256') != contract.digest(sdc)
                    or sdc_gate.get('state_out_sha256') !=
                    contract.digest(folder / 'state_out.json')
                    or slack_gate.get('state_out_sha256') !=
                    contract.digest(folder / 'state_out.json')):
                raise ValueError(f'D26_{name.upper()}_GATE_INPUT_MISMATCH')
            gate_statuses = (sdc_gate.get('verdict'), slack_gate.get('verdict'))
            arm_status = ('FAIL' if 'FAIL' in gate_statuses else
                          'PASS' if gate_statuses == ('PASS', 'PASS') else
                          'NOT_MEASURED')
            return {
                'status': arm_status, 'constraint': constraint_record,
                'adopted_netlist': adopted_ref,
                'native': {'folder': str(folder.relative_to(project)),
                           'receipt': file_ref(folder / 'vibeic_receipt.json'),
                           'input_step': native_receipt['input'].get('step')},
                'sdc_gate': {**file_ref(sdc_path), 'verdict': sdc_gate.get('verdict'),
                             'findings': sdc_gate.get('findings'),
                             'corners': sdc_gate.get('corners')},
                'slack_gate': {**file_ref(slack_path),
                               'verdict': slack_gate.get('verdict'),
                               'findings': slack_gate.get('findings'),
                               'corners': slack_gate.get('corners')},
            }

        functional_arm = run_arm('functional', derived_sdc, functional_constraint)
        receipt['post_scan_arms'] = {'functional': functional_arm}
        receipt['scan']['status'] = 'NOT_MEASURED'
        receipt['scan']['reason'] = 'shift and capture timing belong to D49/D70'
        if functional_arm['status'] in ('PASS', 'FAIL'):
            receipt['modes_measured'].append('post_scan_functional')
        aggregate = functional_arm['status']
        detail = ('D26 functional baseline and adopted-netlist functional mode passed'
                  if aggregate == 'PASS' else
                  'D26 functional timing mode failed' if aggregate == 'FAIL' else
                  'D26 functional timing mode is not measured')
        return publish(aggregate, detail, folder=current['folder'])
    except (contract.Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        receipt['scan']['status'] = 'NOT_MEASURED'
        receipt['scan']['reason'] = str(exc)
        aggregate = 'FAIL' if status == 'FAIL' else 'NOT_MEASURED'
        return publish(aggregate, str(exc), folder=current['folder'])


def _finish_selected_native_owner(project: Path, native_step: str,
                                  acceptance: dict) -> dict | None:
    """Forward the completed owner's verdict through the shared Flow109 exit."""
    import flow109

    status = acceptance['verdict']
    extras = {'step_id': native_step, 'default_row_status': status,
              'completed': status == 'PASS'}
    if native_step == '11' and 'scan_cell_list' in acceptance:
        extras['scan_cell_list'] = acceptance['scan_cell_list']
        extras['native_component_status'] = acceptance.get('component_status', 'NOT_MEASURED')
    if native_step == '12' and 'post_dft_component' in acceptance:
        extras['post_dft_component'] = acceptance['post_dft_component']
        extras['native_component_status'] = acceptance.get('component_status', 'NOT_MEASURED')
    return flow109.finish_native_window(project, {'steps': [{
        'status': status, 'extras': extras,
    }]})


def _flow109_selected_row(row_id: str) -> bool:
    """Whether the validated current public request selects ``row_id``."""
    import flow109

    path = os.environ.get(flow109.CONTEXT_ENV)
    if not path:
        return False
    try:
        context = flow109.validate_execution_context(
            json.loads(Path(path).read_text(encoding='utf-8')))
    except (OSError, ValueError, flow109.Flow109Error):
        return False
    rows = context.get('resolved_rows') or [context.get('resolved_row', {})]
    return (len(rows) == 1 and rows[0].get('id') == row_id
            and context.get('requested_step') == row_id)


def _d10_yosys_observation(project: Path) -> dict:
    """Observe only facts bound by the existing native JsonHeader producer."""
    import _cdc_netlist as native

    path = project / native.NETLIST_REL
    try:
        if (path.is_symlink() or not path.is_file()
                or not path.resolve().is_relative_to(project.resolve())):
            raise ValueError('native netlist absent or symlink')
        netlist = native.load(path)
        binding = native.require_binding(project, path, netlist)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != binding['sha256']['netlist.json']:
            raise ValueError('native netlist changed after binding')
        doc = json.loads(raw)
        modules = doc['modules']
        if not isinstance(modules, dict) or netlist.top not in modules:
            raise ValueError('native module inventory missing')
        blackboxes = {name for name, module in modules.items()
                      if native._int((module.get('attributes') or {}).get('blackbox', 0))}
        instances = []

        pending = [(netlist.top, '', frozenset())]
        while pending:
            module_name, prefix, ancestors = pending.pop()
            if module_name in ancestors:
                raise ValueError('recursive native module hierarchy')
            cells = modules[module_name].get('cells', {})
            if not isinstance(cells, dict):
                raise ValueError('native cell inventory missing')
            for name, cell in cells.items():
                if not isinstance(name, str) or not isinstance(cell, dict) or not isinstance(cell.get('type'), str):
                    raise ValueError('invalid native cell inventory')
                kind, instance = cell['type'], prefix + name
                if kind in blackboxes:
                    instances.append(instance)
                elif kind in modules:
                    pending.append((kind, instance + '/', ancestors | {module_name}))
                elif not kind.startswith('$'):
                    raise ValueError('unresolved native cell type')
        instances.sort()
        return {'status': 'OBSERVED', 'producer': 'Yosys.JsonHeader',
                'netlist_sha256': binding['sha256']['netlist.json'],
                'input_fingerprint': binding['input']['fingerprint'],
                'elaboration_errors': 0, 'observed_blackbox_instances': instances,
                'unexpected_blackboxes': 0 if not instances else None,
                'qualification': 'NOT_MEASURED'}
    except (native.Refusal, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return {'status': 'NOT_MEASURED', 'detail': str(exc)}


def _d10_p0_native(project: Path) -> dict:
    """Run the existing P0 producer into this attempt without replacing prior evidence."""
    import _cdc_netlist as native
    import _specrtl_common
    import flow109
    import librelane_contract as contract
    import p0_tool_frontend_check as frontend

    diagnostic = None
    bound_identity = None
    try:
        context = flow109.validate_execution_context(json.loads(
            Path(os.environ[flow109.CONTEXT_ENV]).read_text(encoding='utf-8')))
        attempt = flow109._bound_attempt(project, context, os.environ.get(flow109.ATTEMPT_ENV))
        if (attempt / 'result.json').exists() or (attempt / 'result.json').is_symlink():
            raise ValueError('immutable attempt result already exists')
        files = _specrtl_common.rtl_source_files(project)
        top = frontend._top(project)
        if not files or not top:
            raise ValueError('selected RTL or top is unavailable')
        before = native.source_binding(project, top, files)
        tool_paths = {name: shutil.which(name) for name in ('yosys', 'verilator')}
        if any(not path for path in tool_paths.values()):
            raise ValueError('local native frontend tools unavailable')
        def tool_hashes():
            return {name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                    for name, path in tool_paths.items()}
        tools_before = tool_hashes()
        producer_sha = hashlib.sha256(Path(frontend.__file__).read_bytes()).hexdigest()
        runner_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        authority = None
        if os.environ.get(contract.LOCAL_ATTESTATION_ENV):
            authority = contract.local_image_attestation()
        output_root = attempt / 'p0-native'
        output_root.mkdir(mode=0o700)
        result = frontend.check(project, output_project=output_root)
        result_path = output_root / 'p0_result.json'
        result_bytes = json.dumps(result, sort_keys=True, ensure_ascii=False).encode('utf-8') + b'\n'
        with result_path.open('xb') as stream:
            stream.write(result_bytes)
        diagnostic = {'path': str(result_path.relative_to(project)),
                      'sha256': hashlib.sha256(result_bytes).hexdigest()}
        after = native.source_binding(project, top, _specrtl_common.rtl_source_files(project))
        if (before != after or tools_before != tool_hashes()
                or producer_sha != hashlib.sha256(Path(frontend.__file__).read_bytes()).hexdigest()
                or runner_sha != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
                or (authority is not None and contract.local_image_attestation() != authority)):
            raise ValueError('native inputs, sources, tools or launch changed during execution')
        bound_identity = {'qualification': 'NOT_MEASURED', 'top': top,
                'input_fingerprint': before['fingerprint'], 'tool_sha256': tools_before,
                'producer_source_sha256': producer_sha, 'runner_source_sha256': runner_sha,
                'producer_result': diagnostic,
                'image': authority.get('image') if authority else None,
                'image_id': authority.get('image_id') if authority else None,
                'cid': authority.get('cid') if authority else None,
                'attestation_sha256': authority.get('attestation_sha256') if authority else None}
        if result.get('passed') is not True:
            from flow109_frontend import d10_native_failure
            failure = d10_native_failure(result)
            if failure:
                return {**bound_identity, 'status': 'FAIL', 'native_failure': failure}
            raise ValueError('native failure lacks a supported elaboration diagnostic')
        elab = output_root / frontend.RTL_ELAB_REL
        if (result.get('passed') is not True
                or (result.get('elaboration') or {}).get('written') is not True
                or elab.is_symlink() or not elab.is_file()):
            raise ValueError('native P0 did not produce a successful elaboration')
        raw = elab.read_bytes()
        parsed = json.loads(raw)
        if not isinstance(parsed.get('modules'), dict) or top not in parsed['modules']:
            raise ValueError('native P0 elaboration does not contain the selected top')
        return {**bound_identity, 'status': 'PASS',
                'elaboration_path': str(elab.relative_to(project)),
                'elaboration_sha256': hashlib.sha256(raw).hexdigest()}
    except (flow109.Flow109Error, native.Refusal, contract.Refusal, OSError,
            ValueError, TypeError, KeyError, AttributeError) as exc:
        return {**(bound_identity or {}), 'status': 'NOT_MEASURED',
                'detail': str(exc), 'producer_result': diagnostic}


def _validate_d10_p0_consumer(project: Path, p0: Mapping) -> dict:
    """Validate actual P0 result, current launch, source inputs and tool commands."""
    import _cdc_netlist as native
    import _specrtl_common
    import librelane_contract as contract
    import p0_tool_frontend_check as frontend
    project = Path(project).resolve()
    reference = p0['producer_result']
    relative = Path(reference['path'])
    path = project / relative
    if (relative.is_absolute() or '..' in relative.parts or path.is_symlink()
            or not path.is_file() or not path.resolve().is_relative_to(project)
            or hashlib.sha256(path.read_bytes()).hexdigest() != reference['sha256']):
        raise ValueError('P0 producer result is missing, foreign or stale')
    result = json.loads(path.read_text())
    from flow109_frontend import d10_native_failure
    failure = d10_native_failure(result) if p0.get('status') == 'FAIL' else None
    if (p0.get('status') not in ('PASS', 'FAIL')
            or p0.get('status') == 'FAIL' and
               (not failure or p0.get('native_failure') != failure)):
        raise ValueError('P0 native outcome is not bound to a supported diagnostic')
    files = _specrtl_common.rtl_source_files(project)
    top = frontend._top(project)
    before = native.source_binding(project, top, files)
    authority = contract.local_image_attestation()
    for key, field in (('image', 'image'), ('image_id', 'image_id'), ('cid', 'cid'),
                       ('attestation_sha256', 'attestation_sha256')):
        if p0.get(key) != authority.get(field):
            raise ValueError('P0 live launch identity differs: ' + key)
    if (p0.get('top') != top or p0.get('input_fingerprint') != before['fingerprint']
            or p0.get('producer_source_sha256') != hashlib.sha256(Path(frontend.__file__).read_bytes()).hexdigest()
            or p0.get('runner_source_sha256') != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()):
        raise ValueError('P0 source, producer or runner identity differs')
    if not failure:
        elab_relative = Path(p0['elaboration_path'])
        elaboration = project / elab_relative
        if (elab_relative.is_absolute() or '..' in elab_relative.parts or elaboration.is_symlink()
                or not elaboration.is_file() or not elaboration.resolve().is_relative_to(project)
                or hashlib.sha256(elaboration.read_bytes()).hexdigest() != p0['elaboration_sha256']
                or (result.get('elaboration') or {}).get('written') is not True
                or (result.get('elaboration') or {}).get('top') != top
                or (path.parent / str((result.get('elaboration') or {}).get('path', ''))).resolve()
                    != elaboration.resolve()):
            raise ValueError('P0 native elaboration is missing or stale')
    elif (result.get('elaboration') or {}).get('written') is not False:
        raise ValueError('P0 failed elaboration cannot borrow an output graph')
    actual_tools = {name: hashlib.sha256(Path(shutil.which(name)).read_bytes()).hexdigest()
                    for name in ('yosys', 'verilator')}
    if p0.get('tool_sha256') != actual_tools:
        raise ValueError('P0 executable identity differs')
    if (result.get('program') != 'p0_tool_frontend_check' or result.get('passed') is not (not bool(failure))
            or result.get('sources') != [str(p.relative_to(project)) for p in files]):
        raise ValueError('P0 producer or input population differs')
    tools = result['tools']
    names = [str(p.resolve()) for p in files]
    include_dirs = sorted({str(p.parent.resolve()) for p in files})
    if any(not re.fullmatch(r'[A-Za-z0-9_./-]+', name) for name in names):
        raise ValueError('P0 input path cannot be represented')
    yosys = tools['Yosys.JsonHeader']
    argv = yosys['argv']
    if not isinstance(argv, list) or len(argv) != 5 or argv[:4] != ['yosys', '-Q', '-T', '-p']:
        raise ValueError('P0 Yosys argv differs')
    output = re.search(r'; proc; write_json ([^;\s]+/vibeic_p0_elab_[^/\s;]+/rtl_elab\.json)$', argv[4])
    if output is None:
        raise ValueError('P0 Yosys output argument differs')
    relaxed = yosys.get('relaxed_flags', [])
    if relaxed not in ([], [frontend.DECL_RELAX_FLAG]):
        raise ValueError('P0 relaxed flags are invalid')
    prefix = ('read_slang --single-unit ' + (frontend.DECL_RELAX_FLAG + ' ' if relaxed else '')
              + f'--top {top} ' + ' '.join('-I ' + d for d in include_dirs)
              + ' ' + ' '.join(names) + '; hierarchy -check -top ' + top
              + '; proc; write_json ' + output.group(1))
    if (argv[4] != prefix or yosys.get('execution') != 'host'
            or not failure and yosys.get('exit_code') != 0):
        raise ValueError('P0 Yosys command or verdict differs')
    if relaxed:
        strict = prefix.replace(frontend.DECL_RELAX_FLAG + ' ', '', 1)
        if (yosys.get('strict_argv') != ['yosys', '-Q', '-T', '-p', strict]
                or type(yosys.get('strict_exit_code')) is not int or yosys['strict_exit_code'] <= 0):
            raise ValueError('P0 strict retry identity differs')
    expected = ['verilator', '--lint-only', '--Wall', '-Wno-fatal', '--top-module', top,
                *('-I' + d for d in include_dirs), *names]
    verilator = tools['Verilator.Lint']
    if (verilator.get('argv') != expected or not failure and verilator.get('exit_code') != 0
            or verilator.get('execution') != 'host'):
        raise ValueError('P0 Verilator command or verdict differs')
    return {**({'native_failure': failure} if failure else {}),
            'status': 'PASS', 'producer_result': dict(reference), 'input_fingerprint': before['fingerprint'],
            'producer_source_sha256': p0['producer_source_sha256'],
            'runner_source_sha256': p0['runner_source_sha256'],
            'tool_sha256': actual_tools, 'image_id': authority['image_id'],
            'cid': authority['cid'], 'attestation_sha256': authority['attestation_sha256'],
            'argv_validation': 'MATCH', 'qualification': 'NOT_MEASURED'}


def _d10_dft_ports(project: Path, p0: dict) -> dict:
    """Consume the current P0 elaboration and source-bound DFT intent."""
    import _cdc_netlist as native
    import _specrtl_common
    import fault_scan_chain_insert as scan
    import flow109_metric_acceptance as metric
    import librelane_contract as contract
    if p0.get('status') != 'PASS':
        return {'status': 'NOT_MEASURED', 'reason': 'P0_NOT_AVAILABLE'}
    try:
        project = Path(project).resolve()
        identity = _validate_d10_p0_consumer(project, p0)
        elaboration = project / p0['elaboration_path']
        if elaboration.is_symlink() or not elaboration.resolve().is_relative_to(project) or not elaboration.is_file():
            raise ValueError('P0 elaboration is unavailable')
        raw = elaboration.read_bytes()
        if hashlib.sha256(raw).hexdigest() != p0['elaboration_sha256']:
            raise ValueError('P0 elaboration changed')
        top = p0['top']
        before = native.source_binding(project, top, _specrtl_common.rtl_source_files(project))
        if before['fingerprint'] != p0['input_fingerprint']:
            raise ValueError('P0 source changed')
        binding, problems = scan.load_d09_dft_contract(project)
        if binding is None or problems:
            raise ValueError('DFT intent unavailable: ' + '; '.join(problems))
        result = metric.dft_port_consistency(binding, json.loads(raw), top)
        current, problems = scan.load_d09_dft_contract(project)
        after = native.source_binding(project, top, _specrtl_common.rtl_source_files(project))
        if current != binding or problems or after != before or hashlib.sha256(elaboration.read_bytes()).hexdigest() != p0['elaboration_sha256']:
            raise ValueError('DFT port inputs changed')
        return {**result, 'intent_binding': binding, 'p0_identity': identity,
                'elaboration_sha256': p0['elaboration_sha256']}
    except (native.Refusal, contract.Refusal, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {'status': 'NOT_MEASURED', 'reason': 'DFT_PORT_INPUT_UNAVAILABLE', 'detail': str(exc)}


def _finish_d10_unimplemented_owner(project: Path, *, run_p0: bool = False) -> dict:
    """Publish an honest D10 terminal until its three metric bindings exist."""
    import flow109

    evidence = {'yosys_observation': _d10_yosys_observation(project),
                'p0_native': (_d10_p0_native(project) if run_p0 else
                              {'status': 'NOT_MEASURED',
                               'detail': 'current passing Phase 2 report is unavailable'})}
    try:
        import librelane_contract as contract
        import _cdc_netlist as native
        evidence['p0_consumer_identity'] = _validate_d10_p0_consumer(project, evidence['p0_native'])
    except (native.Refusal, contract.Refusal, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        evidence['p0_consumer_identity'] = {'status': 'NOT_MEASURED', 'detail': str(exc)}
    evidence['dft_port_consistency'] = _d10_dft_ports(project, evidence['p0_native'])
    try:
        from flow109_metric_acceptance import observe_d10_frontend_metrics
        path = os.environ.get(flow109.CONTEXT_ENV)
        if not path:
            raise ValueError('D10 execution context is unavailable')
        context = flow109.validate_execution_context(json.loads(Path(path).read_text()))
        evidence['native_metric_observation'] = observe_d10_frontend_metrics(
            project, context, evidence['p0_native'])
    except (flow109.Flow109Error, OSError, ValueError, TypeError, KeyError, ImportError) as exc:
        evidence['native_metric_observation'] = {
            'status': 'NOT_MEASURED', 'qualification': 'NOT_MEASURED',
            'reason': 'D10_OBSERVATION_UNAVAILABLE', 'detail': str(exc)}
    dft_failed = evidence['dft_port_consistency'].get('status') == 'FAIL'
    native_failed = (evidence['native_metric_observation'].get('qualification') == 'PASS'
                     and evidence['native_metric_observation'].get('status') == 'FAIL')
    row_failed = dft_failed or native_failed
    detail = ('D10_METRIC_BINDINGS_UNIMPLEMENTED: elaboration errors, '
              'unexpected blackboxes and adopted feature inventory require '
              'a canonical producer and consumer')
    if (evidence['native_metric_observation'].get('native_failure') or {}).get('status') == 'FAIL':
        detail = ('D10_QUALIFIED_NATIVE_METRIC_FAILED: missing independent obligations '
                  'do not erase the measured native defect' if native_failed else
                  'D10_NATIVE_FAILURE_OBSERVED: TOOL_QUALIFICATION_UNPROVEN; '
                  'unqualified native evidence cannot close the D10 row contract')
    try:
        finished = flow109.finish_native_window(project, {'steps': [{
            'status': 'FAIL' if row_failed else 'NOT_MEASURED', 'extras': {
                'step_id': 'P0', 'default_row_status': 'FAIL' if row_failed else 'NOT_MEASURED',
                'completed': False, 'detail': detail, 'evidence': evidence,
            },
        }]})
    except flow109.Flow109Error as exc:
        finished = None
        detail = f'D10_FINALIZATION_REFUSED: {exc}'
    except FileExistsError as exc:
        attempt = os.environ.get(flow109.ATTEMPT_ENV)
        expected = Path(attempt) / 'result.json' if attempt else None
        if exc.filename is None or expected is None or Path(exc.filename) != expected:
            raise
        finished = None
        detail = 'D10_FINALIZATION_REFUSED: immutable attempt result already exists'
    if not isinstance(finished, Mapping):
        detail = 'D10_FINALIZATION_UNAVAILABLE: ' + detail
    verdict = ('FAIL' if isinstance(finished, Mapping) and row_failed
               and finished.get('default_row_status') == 'FAIL' else 'NOT_MEASURED')
    return {'verdict': verdict, 'whole_flow_verdict': 'NOT_MEASURED',
            'detail': detail, 'evidence': evidence}


def _d10_metrics_unimplemented() -> bool:
    """Do not retain this refusal after the selected row is actually wired."""
    import flow109

    try:
        context = flow109.validate_execution_context(json.loads(
            Path(os.environ[flow109.CONTEXT_ENV]).read_text(encoding='utf-8')))
        row = context.get('resolved_row') or context['resolved_rows'][0]
        dispatch = row['profile']['dispatch']
        return dispatch.get('flow109_metrics_status') == 'UNIMPLEMENTED'
    except (OSError, ValueError, KeyError, IndexError, TypeError, flow109.Flow109Error):
        return True


def _d09_bound_phase2_evidence(
        project: Path, report: Mapping, invocation: Mapping,
        *, published_current: bool) -> tuple[str, dict, str]:
    """Judge D09 only from one source/material-bound Phase-2 owner report."""
    import benchmark_dispatch as dispatch

    project = Path(project).resolve()
    report_path = _pl.report_path(project, 'phase2_one_shot.json')
    try:
        if published_current is not True:
            raise ValueError('Phase-2 report was not published by this child invocation')
        if report_path.is_symlink() or not report_path.is_file():
            raise ValueError('fresh Phase-2 report is absent or a symlink')
        if json.loads(report_path.read_text(encoding='utf-8')) != report:
            raise ValueError('supplied Phase-2 report differs from the published report')
        binding = report['runner_binding']
        argv = binding['argv']
        source = binding['source']
        expected = dict(invocation)
        if (set(expected) != {'invocation_id', 'argv', 'project', 'source'}
                or expected.get('project') != str(project)
                or not expected.get('invocation_id')
                or binding.get('schema') != 'vibeic.runner_report_binding.v1'
                or binding.get('invocation_id') != expected['invocation_id']
                or binding.get('project') != str(project)
                or binding.get('argv') != expected['argv']
                or binding.get('source') != expected['source']
                or binding.get('report_name') != 'phase2_one_shot.json'
                or not isinstance(argv, list) or len(argv) < 3
                or str(Path(argv[2]).resolve()) != str(project)
                or Path(argv[1]).name != 'phase2_one_shot_runner.py'
                or source != dispatch._runner_source_snapshot(
                    argv, consumer=source['consumer']['path'])
                or binding.get('material') != dispatch._runner_material_snapshot(project)):
            raise ValueError('report project, invocation, source, input, or RTL binding differs')
        producer = binding.get('producer') or {}
        producer_path = Path(str(producer.get('path') or ''))
        if (producer_path.name != 'design_one_shot_runner.py'
                or not producer_path.is_file()
                or hashlib.sha256(producer_path.read_bytes()).hexdigest()
                != producer.get('sha256')):
            raise ValueError('report producer is not the current Phase-2 author')
        entry = argv.index('--entry-step')
        exit_ = argv.index('--exit-step')
        declared = report.get('declared_window') or {}
        if (argv[entry + 1] != '1' or argv[exit_ + 1] != '4'
                or str(declared.get('entry_step')) != '1'
                or str(declared.get('exit_step')) != '4'
                or not {'1', '2', '3', '4'}.issubset(
                    {str(item) for item in declared.get('dispatched_step_ids', ())})):
            raise ValueError('Phase-2 report does not own the complete native 1..4 span')
        material = binding['material']
        rtl = material.get('output_rtl')
        if not isinstance(rtl, dict) or not rtl:
            raise ValueError('bound RTL inventory is empty')
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return 'NOT_MEASURED', {}, f'D09_REPORT_UNBOUND: {exc}'

    steps = report.get('steps')
    if not isinstance(steps, list) or not all(isinstance(row, Mapping) for row in steps):
        return 'NOT_MEASURED', {}, 'D09_REQUIRED_EVIDENCE_ABSENT: invalid step population'

    def unique(names: tuple[str, ...]) -> Mapping | None:
        found = [row for row in steps if row.get('name') in names]
        return found[0] if len(found) == 1 else None

    author = unique(('rtl_gen',))
    lint = unique(('rtl_lint_tool', 'rtl_validate'))
    manifests = unique(('phase2_manifests',))
    reference = unique(('reference_tb',))
    required_names = {'rtl_gen', 'rtl_lint_tool', 'rtl_validate',
                      'phase2_manifests', 'reference_tb'}
    failures = sorted({str(row.get('name')) for row in steps
                       if row.get('name') in required_names
                       and row.get('status') == 'FAIL'})
    if failures:
        return 'FAIL', {}, 'D09_REQUIRED_CHECK_FAILED: ' + ', '.join(failures)
    author_extras = (author or {}).get('extras') or {}
    preserved = (author is not None and author.get('status') == 'PASS_WITH_WAIVERS'
                 and author_extras.get('preserved') is True)
    outputs = (author or {}).get('output_files') or ()
    generated_rtl = {str(Path(path).resolve()) for path in outputs
                     if isinstance(path, str) and Path(path).suffix in {'.v', '.sv'}}
    bound_rtl = {str((project / 'phase2/stage1/rtl' / path).resolve()) for path in rtl}
    generated = (author is not None and author.get('status') == 'PASS'
                 and author_extras.get('program_first') is True
                 and isinstance(author_extras.get('deterministic_generator'), str)
                 and bool(author_extras['deterministic_generator'].strip())
                 and bool(generated_rtl) and generated_rtl == bound_rtl)
    if (author is None or lint is None or manifests is None or reference is None
            or not (preserved or generated)
            or lint.get('status') != 'PASS'
            or manifests.get('status') != 'PASS'
            or reference.get('status') != 'PASS'):
        return ('NOT_MEASURED', {},
                'D09_REQUIRED_EVIDENCE_ABSENT: preserved or bound generated RTL, '
                'validation/lint PASS, manifests PASS, and reference-TB PASS are required')

    cdc_paths = tuple(f'reports/phase2/cdc/{name}.json'
                      for name in ('crossing', 'async_input', 'reset_dep'))
    if not set(cdc_paths).issubset(set(manifests.get('output_files') or ())):
        return 'NOT_MEASURED', {}, 'D09_REQUIRED_EVIDENCE_ABSENT: CDC/RDC outputs undeclared'
    cdc_receipts = []
    for relative in cdc_paths:
        path = project / relative
        try:
            if path.is_symlink() or not path.is_file():
                raise ValueError('absent or symlink')
            raw = path.read_bytes()
            body = json.loads(raw)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return 'NOT_MEASURED', {}, f'D09_REQUIRED_EVIDENCE_ABSENT: {relative}: {exc}'
        if not isinstance(body, Mapping):
            return 'NOT_MEASURED', {}, f'D09_REQUIRED_EVIDENCE_ABSENT: {relative} is not an object'
        if body.get('verdict') == 'FAIL':
            return 'FAIL', {}, f'D09_REQUIRED_CHECK_FAILED: {relative}'
        if body.get('verdict') != 'PASS':
            return 'NOT_MEASURED', {}, f'D09_REQUIRED_EVIDENCE_ABSENT: {relative} is not PASS'
        cdc_receipts.append({'path': relative,
                             'sha256': hashlib.sha256(raw).hexdigest()})

    inventory = [{'path': path, **record} for path, record in sorted(rtl.items())]
    evidence = {
        'runner_invocation_id': binding['invocation_id'],
        'runner_source': source,
        'producer': binding['producer'],
        'material_sha256': hashlib.sha256(json.dumps(
            material, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        'rtl_inventory': inventory,
        'input_inventory': material.get('input', {}),
        'cdc_rdc_receipts': cdc_receipts,
        'phase2_report': {'path': str(report_path.relative_to(project)),
                          'sha256': hashlib.sha256(report_path.read_bytes()).hexdigest()},
    }
    return 'PASS', evidence, 'complete same-invocation D09 owner evidence'


def _finish_d09_selected_owner(
        project: Path, report: Mapping, invocation: Mapping, *,
        published_current: bool) -> dict:
    """Finalize D09 once; never promote raw authoring or wrapper success."""
    import flow109

    project = Path(project)
    launched_id = (invocation.get('invocation_id')
                   if isinstance(invocation, Mapping) else None)
    if not _flow109_selected_row('D09'):
        return {'verdict': 'NOT_MEASURED', 'whole_flow_verdict': 'NOT_MEASURED',
                'launched_invocation_id': launched_id,
                'detail': 'D09_FINALIZATION_REFUSED: selected context is absent, stale, or foreign'}
    status, evidence, detail = _d09_bound_phase2_evidence(
        project, report, invocation, published_current=published_current)
    try:
        finished = flow109.finish_native_window(project, {'steps': [{
            'status': status,
            'extras': {'step_id': '1', 'default_row_status': status,
                       'completed': status == 'PASS', 'detail': detail,
                       'evidence': evidence},
        }]})
    except flow109.Flow109Error as exc:
        finished = None
        detail = f'D09_FINALIZATION_REFUSED: {exc}'
    except FileExistsError as exc:
        attempt = os.environ.get(flow109.ATTEMPT_ENV)
        expected = Path(attempt) / 'result.json' if attempt else None
        if exc.filename is None or expected is None or Path(exc.filename) != expected:
            raise
        finished = None
        detail = ('D09_FINALIZATION_REFUSED: FLOW109_ATTEMPT_RESULT_EXISTS: '
                  'immutable attempt result already exists')
    components = finished.get('components') if isinstance(finished, Mapping) else None
    component = components[0] if isinstance(components, list) and len(components) == 1 else {}
    valid = (finished if isinstance(finished, Mapping)
             and finished.get('schema') == 'vibeic.flow109.window-attempt-result.v1'
             and finished.get('default_row_status') == status
             and finished.get('whole_flow_acceptance') == 'NOT_MEASURED'
             and finished.get('delivery_accepted') is False
             and component.get('step_id') == 'D09'
             and component.get('default_row_status') == status
             and component.get('completed') is (status == 'PASS') else None)
    if valid is None:
        status = 'NOT_MEASURED'
    return {'verdict': status, 'whole_flow_verdict': 'NOT_MEASURED',
            'launched_invocation_id': launched_id,
            'detail': detail, 'evidence': evidence}


def _finish_d25_selected_owner(project: Path) -> dict:
    """Publish the selected LEC owner's actual consumer through the sole writer."""
    import flow109
    import flow109_metric_acceptance as metrics
    try:
        context = flow109.validate_execution_context(json.loads(
            Path(os.environ[flow109.CONTEXT_ENV]).read_text()))
        if context['resolved_row']['id'] != 'D25':
            raise flow109.Flow109Error('D25_CONTEXT_INVALID', 'not the selected owner')
        attempt = flow109._bound_attempt(project, context, os.environ.get(flow109.ATTEMPT_ENV))
        if (attempt / 'result.json').exists():
            raise flow109.Flow109Error('FLOW109_ATTEMPT_RESULT_EXISTS', 'immutable D25 attempt')
        accepted = metrics.accept_d25(project, context)
        status = accepted['status']
        if metrics.accept_d25(project, context) != accepted:
            raise flow109.Flow109Error('D25_NATIVE_INPUT_STALE', 'consumer changed during finalization')
        finished = flow109.finish_native_window(project, {'steps': [{
            'status': accepted['component_status'], 'extras': {
                'step_id': '13', 'default_row_status': status, 'completed': False,
                'metric_acceptance': accepted, 'detail': accepted['reason'],
            }}]})
        if (not isinstance(finished, Mapping) or finished.get('default_row_status') != status
                or finished.get('whole_flow_acceptance') != 'NOT_MEASURED'
                or finished.get('delivery_accepted') is not False):
            raise flow109.Flow109Error('D25_FINALIZATION_UNAVAILABLE', 'canonical writer did not confirm verdict')
        return {'verdict': status, 'component_status': accepted['component_status'],
                'whole_flow_verdict': 'NOT_MEASURED', 'metric_acceptance': accepted,
                'detail': accepted['reason']}
    except (flow109.Flow109Error, OSError, ValueError, KeyError, TypeError) as exc:
        return {'verdict': 'NOT_MEASURED', 'component_status': 'NOT_MEASURED',
                'whole_flow_verdict': 'NOT_MEASURED', 'detail': 'D25_FINALIZATION_REFUSED: ' + str(exc)}


def _finish_d26_selected_owner(project: Path, acceptance: dict) -> dict:
    """Finalize D26 only while its exact timing-mode evidence is current."""
    import flow109
    import librelane_contract as contract

    project = Path(project).resolve()
    status = acceptance.get('verdict')
    timing_ref = acceptance.get('timing_modes_receipt')

    def current_timing_modes() -> tuple[dict | None, str | None]:
        try:
            if (not isinstance(timing_ref, Mapping)
                    or set(timing_ref) != {'path', 'sha256'}):
                raise ValueError('timing_modes_receipt reference is absent or malformed')
            raw_path = Path(str(timing_ref['path']))
            candidate = raw_path if raw_path.is_absolute() else project / raw_path
            path = candidate.resolve()
            if (candidate.is_symlink() or not path.is_relative_to(project)
                    or not path.is_file()
                    or contract.digest(path) != timing_ref['sha256']):
                raise ValueError('timing_modes_receipt bytes are missing, foreign, or changed')
            doc = json.loads(path.read_text(encoding='utf-8'))
            baseline = doc.get('functional_baseline') or {}
            if (doc.get('schema') != 'vibeic.flow109.d26-timing-modes.v1'
                    or doc.get('step_id') != 'D26' or doc.get('position') != 38
                    or status not in ('PASS', 'FAIL', 'NOT_MEASURED')
                    or doc.get('aggregate_status') != status
                    or baseline.get('status') not in
                    ('PASS', 'FAIL', 'NOT_MEASURED')
                    or (baseline.get('status') == 'PASS'
                        and (baseline.get('canonical_pass') is not True
                             or baseline.get('current_inputs') is not True
                             or baseline.get('canonical_consumer_status') != 'PASS'))
                    or (status == 'PASS' and baseline.get('status') != 'PASS')
                    or not isinstance(doc.get('top'), str) or not doc['top']):
                raise ValueError('timing_modes_receipt schema or terminal state is invalid')

            import fault_scan_chain_insert as scan
            planned, problems = scan.load_d09_dft_contract(project)
            recorded_d09 = doc.get('scan', {}).get('d09_binding')
            if recorded_d09 is None:
                if (status == 'NOT_MEASURED' and not doc.get('post_scan_arms')
                        and planned is None):
                    return doc, None
                raise ValueError('timing_modes_receipt omits current D09 binding')
            if planned is None or problems or recorded_d09 != planned:
                raise ValueError('current D09 binding differs from timing_modes_receipt')
            if planned['intent']['requires_scan'] is False:
                if (doc['scan'].get('applicability') != 'NOT_APPLICABLE'
                        or doc['scan'].get('status') != 'NOT_APPLICABLE'
                        or doc.get('post_scan_arms') != {}
                        or doc.get('aggregate_status') != baseline.get('status')
                        or doc.get('modes_measured') !=
                        (['functional_baseline'] if baseline.get('status') in
                         ('PASS', 'FAIL') else [])):
                    raise ValueError('no-scan timing_modes_receipt claims extra modes')
                return doc, None
            if planned['intent']['requires_scan'] is not True:
                raise ValueError('D09 scan applicability is not explicit')
            import design_one_shot_runner as design
            clock, reset, active_low = design.derive_dft_clock_reset(project)
            planned, problems = scan.load_d09_dft_contract(
                project, expected_clock=clock or None,
                expected_reset=reset or None,
                reset_active_low=active_low if reset else False)
            if (planned is None or problems or not clock or not reset
                    or doc.get('scan', {}).get('d09_binding') != planned):
                raise ValueError('D09 binding differs from current clock/reset roles')

            scan_doc = doc.get('scan') or {}
            arms = doc.get('post_scan_arms') or {}
            if scan_doc.get('applicability') != 'APPLICABLE':
                raise ValueError('scan applicability differs from current D09')
            if (arms and ('functional' not in arms
                    or 'post_scan_functional' not in doc.get('modes_measured', []))):
                raise ValueError('functional timing mode population is incomplete')

            adopted_doc = scan_doc.get('adopted_d24') or {}
            if adopted_doc:
                import lec_gate_netlist_select as netlists
                adopted, _note, is_scan = netlists.pnr_consumed_netlist(
                    project, doc['top'])
                adopted = Path(adopted).resolve()
                if (not adopted.is_relative_to(project) or not adopted.is_file()
                        or is_scan is not True
                        or str(adopted.relative_to(project)) != adopted_doc.get('path')
                        or contract.digest(adopted) != adopted_doc.get('sha256')
                        or adopted_doc.get('current') is not True
                        or adopted_doc.get('is_scan_inserted') is not True):
                    raise ValueError('current D24 adopted subject differs')
                import step_output_collector as versions
                d24 = versions.latest_pass(project, '12')
                output = next((item for item in (d24 or {}).get('outputs', ())
                               if item.get('rel') == adopted_doc.get('path')), None)
                consumer = (((d24 or {}).get('result') or {}).get(
                    'canonical_consumer') or {})
                if (not d24 or d24.get('status') != 'PASS'
                        or not d24.get('canonical_pass')
                        or not d24.get('current_inputs')
                        or consumer.get('status') != 'PASS'
                        or not output
                        or output.get('sha256') != adopted_doc.get('sha256')):
                    raise ValueError('current D24 acceptance differs')
            elif arms:
                raise ValueError('complete timing arms omit D24 adopted subject')

            if not arms:
                if (status in ('FAIL', 'NOT_MEASURED')
                        and scan_doc.get('status') == 'NOT_MEASURED'):
                    return doc, None
                raise ValueError('timing mode population is absent')

            for name in ('functional',):
                arm = arms[name]
                constraint_ref = arm.get('constraint') or {}
                if (arm.get('status') not in ('PASS', 'FAIL', 'NOT_MEASURED')
                        or constraint_ref.get('mode') != name
                        or arm.get('adopted_netlist') != {
                            'path': adopted_doc['path'], 'sha256': adopted_doc['sha256']}):
                    raise ValueError(f'{name} timing arm subject or mode differs')
                if (name == 'functional'
                        and (constraint_ref.get('clock') != clock
                             or constraint_ref.get('clock_select') !=
                             planned['intent']['test_mode']['clock_select']['native']
                             or constraint_ref.get('clock_select_value') != 0
                             or constraint_ref.get('scan_enable') !=
                             planned['intent']['test_port_def']['scan_enable']['native']
                             or constraint_ref.get('scan_enable_value') != 0
                             or constraint_ref.get('scan_input') !=
                             planned['intent']['test_port_def']['scan_in']['native']
                             or constraint_ref.get('scan_input_value') != 0
                             or constraint_ref.get('scan_clock') !=
                             planned['intent']['test_port_def']['tck']['native']
                             or constraint_ref.get('scan_clock_value') != 0
                             or constraint_ref.get('reset') !=
                             planned['intent']['test_mode']['reset']['signal']
                             or constraint_ref.get('reset_value') != 1 -
                             planned['intent']['test_mode']['reset']['active_level']
                             or constraint_ref.get('d09_path') != planned['path']
                             or constraint_ref.get('d09_sha256') != planned['sha256'])):
                    raise ValueError('functional timing mode authority differs')
                constraint_path = (project / str(constraint_ref.get('path') or '')).resolve()
                if (not constraint_path.is_relative_to(project)
                        or not constraint_path.is_file()
                        or contract.digest(constraint_path) != constraint_ref.get('sha256')):
                    raise ValueError(f'{name} timing constraint is missing or changed')
                native = arm.get('native') or {}
                folder = (project / str(native.get('folder') or '')).resolve()
                native_ref = native.get('receipt') or {}
                native_path = (project / str(native_ref.get('path') or '')).resolve()
                if (not folder.is_relative_to(project) or not folder.is_dir()
                        or native_path != folder / 'vibeic_receipt.json'
                        or not native_path.is_file()
                        or contract.digest(native_path) != native_ref.get('sha256')):
                    raise ValueError(f'{name} native receipt is missing or changed')
                contract.validate_step_receipt(folder, 'OpenROAD.STAPrePNR')
                config = json.loads((folder / 'config.json').read_text(encoding='utf-8'))
                state = json.loads((folder / 'state_out.json').read_text(encoding='utf-8'))
                if (Path(str(config.get('PNR_SDC_FILE') or '')).resolve() != constraint_path
                        or Path(str(state.get('nl') or '')).resolve() != adopted):
                    raise ValueError(f'{name} native input subject differs')
                gate_verdicts = []
                for gate_name in ('sdc_gate', 'slack_gate'):
                    gate_ref = arm.get(gate_name) or {}
                    gate_path = (project / str(gate_ref.get('path') or '')).resolve()
                    if (not gate_path.is_relative_to(project) or not gate_path.is_file()
                            or contract.digest(gate_path) != gate_ref.get('sha256')):
                        raise ValueError(f'{name} {gate_name} is missing or changed')
                    gate = json.loads(gate_path.read_text(encoding='utf-8'))
                    if (gate.get('verdict') not in ('PASS', 'FAIL', 'NOT_MEASURED')
                            or gate_ref.get('verdict') != gate.get('verdict')):
                        raise ValueError(f'{name} {gate_name} verdict differs')
                    gate_verdicts.append(gate['verdict'])
                    # The immutable gate bytes are authoritative here; calling
                    # a judge would overwrite them, so bind their source fields.
                    if (gate.get('state_out_sha256') != contract.digest(folder / 'state_out.json')
                            or (gate_name == 'sdc_gate'
                                and (gate.get('netlist_sha256') != adopted_doc['sha256']
                                     or gate.get('sdc_sha256') != constraint_ref['sha256']))):
                        raise ValueError(f'{name} {gate_name} inputs differ')
                arm_status = ('FAIL' if 'FAIL' in gate_verdicts else
                              'PASS' if gate_verdicts == ['PASS', 'PASS'] else
                              'NOT_MEASURED')
                if arm.get('status') != arm_status:
                    raise ValueError(f'{name} timing arm verdict differs')
            aggregate = arms['functional']['status']
            if aggregate != status:
                raise ValueError('timing arm aggregate differs from terminal status')
            return doc, None
        except (contract.Refusal, OSError, ValueError, KeyError, TypeError,
                json.JSONDecodeError) as exc:
            return None, str(exc)

    if timing_ref is not None or status == 'PASS':
        timing_doc, refusal = current_timing_modes()
        if timing_doc is None:
            status = 'NOT_MEASURED'
            acceptance = {**acceptance, 'verdict': status,
                          'detail': 'D26_TIMING_MODES_RECEIPT_REFUSED: ' + refusal}
            timing_ref = None

    try:
        extras = {'step_id': '10', 'default_row_status': status,
                  'completed': status == 'PASS'}
        if timing_ref is not None:
            extras['timing_modes_receipt'] = dict(timing_ref)
        finished = flow109.finish_native_window(project, {'steps': [{
            'status': status, 'extras': extras,
        }]})
    except flow109.Flow109Error as exc:
        finished = None
        detail = f'D26_FINALIZATION_REFUSED: {exc}'
    except FileExistsError as exc:
        attempt = os.environ.get(flow109.ATTEMPT_ENV)
        expected = Path(attempt) / 'result.json' if attempt else None
        if exc.filename is None or expected is None or Path(exc.filename) != expected:
            raise
        finished = None
        detail = ('D26_FINALIZATION_REFUSED: '
                  'FLOW109_ATTEMPT_RESULT_EXISTS: immutable attempt '
                  'result already exists')
    else:
        detail = 'D26_FINALIZATION_RESULT_INVALID'
    components = finished.get('components') if isinstance(finished, Mapping) else None
    component = components[0] if isinstance(components, list) and len(components) == 1 else {}
    finalized = (finished if isinstance(finished, Mapping)
                 and finished.get('schema') == 'vibeic.flow109.window-attempt-result.v1'
                 and finished.get('default_row_status') in ('PASS', 'FAIL', 'NOT_MEASURED')
                 and finished.get('default_row_status') == acceptance.get('verdict')
                 and finished.get('whole_flow_acceptance') == 'NOT_MEASURED'
                 and finished.get('delivery_accepted') is False
                 and component.get('step_id') == 'D26'
                 and component.get('default_row_status') == finished.get('default_row_status')
                 and component.get('completed') is (finished.get('default_row_status') == 'PASS')
                 and ((timing_ref is None
                       and 'timing_modes_receipt' not in component)
                      or component.get('timing_modes_receipt') == timing_ref)
                 else None)
    if finalized is None:
        return {**acceptance, 'verdict': 'NOT_MEASURED', 'detail': detail}
    return {**acceptance, 'verdict': finalized['default_row_status']}


def _complete_step8_early_preflight(project: Path) -> dict:
    """Run only Step 8's registered netlist-independent owner consumer."""
    import design_one_shot_runner as design
    import flow109

    row = design.step_sdc_validation(project)
    extras = dict(row.extras)
    status = row.status
    if extras.get('early_preflight') is not True:
        status = 'NOT_MEASURED'
    try:
        finished = flow109.finish_native_window(project, {'steps': [{
            'status': status,
            'extras': {**extras, 'step_id': '8', 'default_row_status': status,
                       'completed': status == 'PASS', 'detail': row.detail,
                       'output_files': list(row.output_files)},
        }]})
    except flow109.Flow109Error as exc:
        finished = None
        finalization_detail = f'D20_FINALIZATION_REFUSED: {exc}'
    except FileExistsError as exc:
        attempt = os.environ.get(flow109.ATTEMPT_ENV)
        expected = Path(attempt) / 'result.json' if attempt else None
        if exc.filename is None or expected is None or Path(exc.filename) != expected:
            raise
        finished = None
        finalization_detail = ('D20_FINALIZATION_REFUSED: '
                               'FLOW109_ATTEMPT_RESULT_EXISTS: immutable attempt '
                               'result already exists')
    else:
        finalization_detail = 'D20_FINALIZATION_RESULT_INVALID'
    components = finished.get('components') if isinstance(finished, Mapping) else None
    component = components[0] if isinstance(components, list) and len(components) == 1 else {}
    finalized = (finished if isinstance(finished, Mapping)
                 and finished.get('schema') == 'vibeic.flow109.window-attempt-result.v1'
                 and finished.get('default_row_status') in ('PASS', 'FAIL', 'NOT_MEASURED')
                 and finished.get('whole_flow_acceptance') == 'NOT_MEASURED'
                 and finished.get('delivery_accepted') is False
                 and component.get('step_id') == 'D20'
                 and component.get('default_row_status') == finished.get('default_row_status')
                 and component.get('completed') is (finished.get('default_row_status') == 'PASS')
                 else None)
    status = (finalized or {}).get('default_row_status', 'NOT_MEASURED')
    if finalized is not None:
        finalization_detail = row.detail
    return {'verdict': status, 'detail': finalization_detail,
            'early_preflight': extras.get('early_preflight') is True,
            'deferred_until': extras.get('deferred_until'),
            'mapped_path_claimed': False, 'frontend_dispatched': False,
            'outputs': list(row.output_files)}


def _d23_scan_replace_component(project: Path, top: str, checkpoint: Mapping) -> dict:
    """Run physical Default scan replacement without creating a scan chain.

    The result is component evidence only; it does not claim D23 or D30 PASS.
    """
    import tempfile
    try:
        import flow109
        import librelane_contract as contract
        import design_one_shot_runner as design
        import dft_post_optimization_scan_survival_check as cell_gate
        from lec_post_layout_check import _parse_netlist_instances
    except ImportError as exc:
        return {'verdict': 'NOT_MEASURED', 'component_status': 'NOT_MEASURED',
                'detail': str(exc), 'whole_flow_verdict': 'NOT_MEASURED'}
    try:
        project = Path(project).resolve()
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', top):
            raise ValueError('top is not a supported identifier')
        context = flow109.validate_execution_context(json.loads(
            Path(os.environ[flow109.CONTEXT_ENV]).read_text()))
        rows = context.get('resolved_rows') or [context.get('resolved_row', {})]
        if (len(rows) != 1 or rows[0].get('id') != 'D23'
                or context.get('features', {}).get('physical') is not True
                or context.get('features', {}).get('requires_scan') is not True):
            raise ValueError('not the physical D23 scan owner')
        attempt = flow109._bound_attempt(project, context, os.environ.get(flow109.ATTEMPT_ENV))
        if (attempt / 'result.json').exists() or (attempt / 'result.json').is_symlink():
            raise ValueError('immutable D23 attempt already completed')
        intent = flow109.dft_source_intent(project, context)
        plan = flow109.dft_plan_reference(intent)
        authority = contract.local_image_attestation()
        mapped = Path(str(checkpoint['native_handoff']['canonical']))
        if mapped.is_symlink() or not mapped.is_file() or not mapped.resolve().is_relative_to(project):
            raise ValueError('mapped input is foreign or missing')
        before = mapped.read_bytes()
        if hashlib.sha256(before).hexdigest() != checkpoint['native_handoff']['netlist_sha256']:
            raise ValueError('mapped input differs from synthesis handoff')
        pdk = design._phase2_pdk_config(project)
        paths = [Path(str(getattr(pdk, key))).resolve() for key in ('tech_lef', 'cell_lef', 'liberty')]
        if any(not path.is_file() for path in paths):
            raise ValueError('PDK technology, cell LEF or Liberty is missing')
        tool = shutil.which('openroad')
        if not tool:
            raise ValueError('OpenROAD unavailable')
        tool_sha = hashlib.sha256(Path(tool).read_bytes()).hexdigest()
        producer_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        comparator_sha = hashlib.sha256(Path(cell_gate.__file__).read_bytes()).hexdigest()
        pdk_sha = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        def q(path):
            value = str(path)
            if any(char in value for char in '{}\n\r'):
                raise ValueError('unsafe Tcl path')
            return '{' + value + '}'
        with tempfile.TemporaryDirectory(prefix='flow109-d23-') as td:
            staged = Path(td) / 'mapped.v'; staged.write_bytes(before)
            output = Path(td) / 'scan_replace.v'
            script = Path(td) / 'replace.tcl'
            script.write_text('read_lef ' + q(paths[0]) + '\nread_lef ' + q(paths[1])
                              + '\nread_liberty ' + q(paths[2]) + '\nread_verilog ' + q(staged)
                              + '\nlink_design ' + top + '\nscan_replace\nwrite_verilog '
                              + q(output) + '\n')
            run = subprocess.run([tool, '-no_init', '-exit', str(script)],
                                 capture_output=True, text=True, timeout=120)
            if run.returncode != 0 or '[ERROR' in run.stdout + run.stderr or not output.is_file():
                raise ValueError('OpenROAD scan replacement did not finish')
            after = output.read_bytes()
            recipe_bytes = script.read_bytes()
            log_bytes = (run.stdout + run.stderr).encode('utf-8')
            argv = [tool, '-no_init', '-exit', str(script)]
        a = _parse_netlist_instances(before.decode('utf-8'))
        b = _parse_netlist_instances(after.decode('utf-8'))
        if set(a) != set(b):
            raise ValueError('scan replacement changed instance population')
        cells = [{'instance': name, 'cell': b[name][0]} for name in sorted(a)
                 if a[name][0] != b[name][0]]
        checked = cell_gate.reconcile_scan_cell_list(before.decode('utf-8'),
                    after.decode('utf-8'), after.decode('utf-8'), cells, top=top)
        if checked.get('verdict') != 'PASS':
            raise ValueError('scan replacement inventory not verified: ' + str(checked))
        if (mapped.read_bytes() != before
                or hashlib.sha256(Path(tool).read_bytes()).hexdigest() != tool_sha
                or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != producer_sha
                or hashlib.sha256(Path(cell_gate.__file__).read_bytes()).hexdigest() != comparator_sha
                or any(hashlib.sha256(path.read_bytes()).hexdigest() != pdk_sha[str(path)] for path in paths)
                or contract.local_image_attestation() != authority
                or flow109.dft_source_intent(project, context) != intent):
            raise ValueError('scan replacement inputs changed during execution')
        out = attempt / 'd23_scan_replace.v'
        with out.open('xb') as stream:
            stream.write(after)
        recipe_path = attempt / 'd23_scan_replace.tcl'
        log_path = attempt / 'd23_scan_replace.log'
        for target, data in ((recipe_path, recipe_bytes), (log_path, log_bytes)):
            with target.open('xb') as stream:
                stream.write(data)
        artifact = attempt / 'd23_scan_cells.json'
        payload = {'schema': 'vibeic.flow109.d23-scan-cells.v1', 'producer': 'D23',
                   'operation': 'OpenROAD.scan_replace', 'top': top, 'cells': cells,
                   'mapped': {'path': str(mapped.relative_to(project)), 'sha256': hashlib.sha256(before).hexdigest()},
                   'replaced': {'path': str(out.relative_to(project)), 'sha256': hashlib.sha256(after).hexdigest()},
                   'openroad_sha256': tool_sha, 'yosys_sha256': checked['parser_sha256'],
                   'producer_source_sha256': producer_sha, 'comparator_source_sha256': comparator_sha,
                   'argv': argv, 'returncode': run.returncode,
                   'recipe': {'path': str(recipe_path.relative_to(project)), 'sha256': hashlib.sha256(recipe_bytes).hexdigest()},
                   'log': {'path': str(log_path.relative_to(project)), 'sha256': hashlib.sha256(log_bytes).hexdigest()},
                   'pdk_sha256': pdk_sha, 'cid': authority['cid'], 'image': authority['image'],
                   'image_id': authority['image_id'], 'attestation_sha256': authority['attestation_sha256'],
                   'd01_intent': intent['source_binding'], 'dft_plan': plan}
        with artifact.open('x', encoding='utf-8') as stream:
            json.dump(payload, stream, sort_keys=True, indent=2)
            stream.write('\n')
        return {'verdict': 'NOT_MEASURED', 'component_status': 'PASS',
                'detail': 'D23 scan replacement measured; row metrics remain unqualified',
                'scan_cell_list': {'path': str(artifact.relative_to(project)),
                                   'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()},
                'whole_flow_verdict': 'NOT_MEASURED'}
    except (flow109.Flow109Error, contract.Refusal, OSError, ValueError, KeyError,
            TypeError, AttributeError, subprocess.TimeoutExpired, UnicodeError) as exc:
        return {'verdict': 'NOT_MEASURED', 'component_status': 'NOT_MEASURED',
                'detail': str(exc), 'whole_flow_verdict': 'NOT_MEASURED'}


def _complete_step11_dft(project: Path, top: str, container: str) -> dict:
    """Run the existing Step-11 producer on the current Step-9 subject."""
    import design_one_shot_runner as design
    import fault_atpg_run as atpg
    import fault_scan_chain_insert as scan
    import step_output_collector as versions

    _prior, error = _current_step9_checkpoint(project)
    if error:
        return {'verdict': 'NOT_MEASURED', 'detail': 'Step11 ' + error}
    if _flow109_selected_row('D23'):
        try:
            import flow109
            context = flow109.validate_execution_context(json.loads(
                Path(os.environ[flow109.CONTEXT_ENV]).read_text()))
            flow109._bound_attempt(project, context, os.environ.get(flow109.ATTEMPT_ENV))
            if (context.get('features', {}).get('physical') is True
                    and context.get('features', {}).get('requires_scan') is True):
                return _d23_scan_replace_component(project, top, _prior)
        except (flow109.Flow109Error, OSError, ValueError, KeyError, TypeError, ImportError):
            return {'verdict': 'NOT_MEASURED', 'detail': 'D23 context is unavailable'}
    clk, reset, active_low = design.derive_dft_clock_reset(project)
    # The retained entry owns a DFT insertion request, so validate the exact
    # L20 contract against the mapped subject before either scan insertion or
    # ATPG starts.  The underlying full-flow producer historically continues
    # ATPG after a scan-insertion refusal; that is useful evidence in a broad
    # run, but it is not completion of this selected D23 owner row.
    try:
        mapped_rel, _selection = atpg.resolve_mapped_netlist(
            project, 'phase2/stage2/synth/netlist.v')
        mapped = project / mapped_rel
        if not mapped.is_file():
            return {'verdict': 'NOT_MEASURED',
                    'detail': 'Step11 mapped synthesis subject is absent'}
        flop_count = scan.count_flops(mapped.read_text(errors='replace'))
        _binding, problems = scan.load_l20_scan_contract(
            project, expected_clock=clk, expected_length=flop_count)
    except (OSError, ValueError, RuntimeError) as exc:
        return {'verdict': 'NOT_MEASURED',
                'detail': f'Step11 L20/native-subject validation failed: {exc}'}
    if problems:
        return {'verdict': 'NOT_MEASURED',
                'detail': 'Step11 L20/native-subject mismatch: '
                          + '; '.join(problems)}
    began = time.time()
    try:
        result = design._step_dft_insertion(
            project, top, container, clk, reset, active_low, True)
    except (OSError, ValueError, RuntimeError) as exc:
        return {'verdict': 'NOT_MEASURED', 'detail': str(exc)}
    current = next((row for row in versions.current_acceptance(project, began)
                    if str(row['id']) == '11'), None)
    if current is None:
        return {'verdict': 'FAIL' if result.status == 'FAIL' else 'NOT_MEASURED',
                'detail': result.detail or 'Step11 published no complete consumer'}
    consumer = (current.get('result') or {}).get('canonical_consumer')
    if not isinstance(consumer, dict):
        return {'verdict': 'FAIL' if current['status'] == 'FAIL' else 'NOT_MEASURED',
                'folder': current['folder'],
                'detail': 'Step11 has no complete canonical consumer'}
    status = ('PASS' if current.get('canonical_pass') and current['status'] == 'PASS'
              and consumer.get('status') == 'PASS' else
              'FAIL' if current['status'] == 'FAIL' else 'NOT_MEASURED')
    return {'verdict': status, 'folder': current['folder'],
            'detail': '; '.join(consumer.get('step', {}).get('reasons', ()))
                      or result.detail}


def _d24_post_dft_component(project: Path) -> dict:
    """Optimize the bound D23 replacement in the same attested native launch.

    Output is immutable component evidence, not a D24 row or LEC PASS.
    """
    import tempfile
    import flow109
    import librelane_contract as contract
    import dft_post_optimization_scan_survival_check as cell_gate
    try:
        project = Path(project).resolve()
        context = flow109.validate_execution_context(json.loads(
            Path(os.environ[flow109.CONTEXT_ENV]).read_text()))
        rows = context.get('resolved_rows') or [context.get('resolved_row', {})]
        if (len(rows) != 1 or rows[0].get('id') != 'D24'
                or context.get('features', {}).get('physical') is not True
                or context.get('features', {}).get('requires_scan') is not True):
            raise ValueError('not the physical D24 scan owner')
        attempt = flow109._bound_attempt(project, context, os.environ.get(flow109.ATTEMPT_ENV))
        if (attempt / 'result.json').exists() or (attempt / 'result.json').is_symlink():
            raise ValueError('immutable D24 attempt already completed')
        intent = flow109.dft_source_intent(project, context)
        source = flow109.d23_scan_replacement_binding(project, context, intent)
        authority = contract.local_image_attestation()
        tool = shutil.which('yosys')
        if not tool:
            raise ValueError('Yosys unavailable')
        tool_sha = hashlib.sha256(Path(tool).read_bytes()).hexdigest()
        source_path = project / source['replaced']['path']
        before = source_path.read_bytes()
        with tempfile.TemporaryDirectory(prefix='flow109-d24-') as td:
            staged = Path(td) / 'source.v'; staged.write_bytes(before)
            output = Path(td) / 'optimized.v'
            recipe = f'read_verilog {staged}; opt_clean -purge; write_verilog -noattr {output}'
            run = subprocess.run([tool, '-Q', '-T', '-p', recipe], capture_output=True,
                                 text=True, timeout=120)
            if run.returncode != 0 or not output.is_file():
                raise ValueError('Yosys post-DFT optimization failed')
            after = output.read_bytes()
        check = cell_gate.reconcile_scan_cell_list(
            (project / source['mapped']['path']).read_text(), before.decode(),
            after.decode(), source['cells'], top=source['top'])
        if check.get('verdict') != 'PASS':
            raise ValueError('D24 scan cells differ from D23 list')
        if (source_path.read_bytes() != before
                or hashlib.sha256(Path(tool).read_bytes()).hexdigest() != tool_sha
                or contract.local_image_attestation() != authority
                or flow109.d23_scan_replacement_binding(project, context, intent) != source):
            raise ValueError('D24 inputs changed during execution')
        target = attempt / 'd24_post_dft.v'
        with target.open('xb') as stream:
            stream.write(after)
        log = attempt / 'd24_yosys.log'
        with log.open('x', encoding='utf-8') as stream:
            stream.write(run.stdout + run.stderr)
        ref = lambda path: {'path': str(path.relative_to(project)),
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        receipt = attempt / 'd24_component.json'
        with receipt.open('x', encoding='utf-8') as stream:
            json.dump({'schema': 'vibeic.flow109.d24-component.v1', 'producer': 'D24',
                'source': source['replaced'], 'scan_cell_list': source['scan_cell_list'],
                'netlist': ref(target), 'log': ref(log), 'yosys_sha256': tool_sha,
                'cid': authority['cid'], 'attestation_sha256': authority['attestation_sha256'],
                'returncode': run.returncode}, stream, sort_keys=True, indent=2)
            stream.write('\n')
        return {'verdict': 'NOT_MEASURED', 'component_status': 'PASS',
                'detail': 'D24 optimized bound D23 output; row metrics remain unqualified',
                'post_dft_component': ref(receipt), 'whole_flow_verdict': 'NOT_MEASURED'}
    except (flow109.Flow109Error, contract.Refusal, OSError, ValueError, KeyError,
            TypeError, AttributeError, subprocess.TimeoutExpired, UnicodeError) as exc:
        return {'verdict': 'NOT_MEASURED', 'component_status': 'NOT_MEASURED',
                'detail': str(exc), 'whole_flow_verdict': 'NOT_MEASURED'}


def _complete_step12_post_dft(project: Path, container: str) -> dict:
    """Run the existing Step-12 producer and return its complete consumer."""
    import design_one_shot_runner as design
    import step_output_collector as versions

    if _flow109_selected_row('D24'):
        try:
            import flow109
            context = flow109.validate_execution_context(json.loads(
                Path(os.environ[flow109.CONTEXT_ENV]).read_text()))
            if (context.get('features', {}).get('physical') is True
                    and context.get('features', {}).get('requires_scan') is True):
                return _d24_post_dft_component(project)
        except (flow109.Flow109Error, OSError, ValueError, KeyError, TypeError, ImportError):
            return {'verdict': 'NOT_MEASURED', 'detail': 'D24 context is unavailable'}

    began = time.time()
    try:
        result = design._step_post_dft_optimization(project, container)
    except (OSError, ValueError, RuntimeError) as exc:
        return {'verdict': 'NOT_MEASURED', 'detail': str(exc)}
    current = next((row for row in versions.current_acceptance(project, began)
                    if str(row['id']) == '12'), None)
    if current is None:
        return {'verdict': 'FAIL' if result.status == 'FAIL' else 'NOT_MEASURED',
                'detail': result.detail or 'Step12 published no complete consumer'}
    consumer = (current.get('result') or {}).get('canonical_consumer')
    if not isinstance(consumer, dict):
        return {'verdict': 'FAIL' if current['status'] == 'FAIL' else 'NOT_MEASURED',
                'folder': current['folder'],
                'detail': 'Step12 has no complete canonical consumer'}
    status = ('PASS' if current.get('canonical_pass') and current['status'] == 'PASS'
              and consumer.get('status') == 'PASS' else
              'FAIL' if current['status'] == 'FAIL' else 'NOT_MEASURED')
    return {'verdict': status, 'folder': current['folder'],
            'detail': '; '.join(consumer.get('step', {}).get('reasons', ()))
                      or result.detail}


def _complete_step8_postcheck(project: Path, top: str) -> dict:
    """Accept the existing prelayout evidence without invoking its producers."""
    import _flow_yaml
    import design_one_shot_runner as design
    import execution_backend_gates as gates
    import librelane_contract as contract
    import step_output_collector as versions
    import synth_handoff_netlist_check as handoff

    canonical = {str(row['id']): row for row in _flow_yaml.load()['steps']}
    selected = {str(row['id']): row for row in versions._read_index(project)['steps']}
    for sid in ('9', '10'):
        prior = versions.latest_pass(project, sid)
        latest = selected.get(sid) or {}
        if (not prior or not prior.get('current_inputs')
                or not prior.get('canonical_pass') or prior.get('status') != 'PASS'
                or latest.get('folder') != prior.get('folder')):
            return {'verdict': 'FAIL' if latest.get('status') == 'FAIL' else 'NOT_MEASURED',
                    'detail': f'Step8 postcheck requires the current complete Step{sid} checkpoint'}
        consumer = (prior.get('result') or {}).get('canonical_consumer') or {}
        try:
            outputs = gates.contracts(project, canonical[sid])
        except (OSError, ValueError, RuntimeError) as exc:
            return {'verdict': 'NOT_MEASURED', 'detail': str(exc)}
        if (consumer.get('status') != 'PASS' or not consumer.get('outputs')
                or outputs != consumer['outputs']):
            return {'verdict': 'NOT_MEASURED',
                    'detail': f'Step{sid} outputs no longer match its complete consumer'}
    bound = handoff.bound_handoff(project)
    if not bound or bound.get('verdict') != 'PASS':
        return {'verdict': (bound or {}).get('verdict', 'NOT_MEASURED'),
                'detail': '; '.join((bound or {}).get('findings', ()))
                          or 'Step8 requires the current native synthesis handoff'}
    if Path(bound['mapped']).name != f'{top}_synth.v':
        return {'verdict': 'NOT_MEASURED', 'detail': 'Step8 top differs from the synthesis handoff'}
    try:
        gate = json.loads((project / 'phase3/librelane/prelayout/gates/step8_sdc_opensta.json').read_text())
        state = (project / gate['source']).resolve()
        if not state.is_relative_to(project.resolve()):
            raise ValueError('Step8 prelayout state is outside the project')
        folder = state.parent
        native = {'folder': str(folder),
                  'receipt_sha256': contract.digest(folder / 'vibeic_receipt.json')}
        began = time.time()
        result = design.step_sdc_validation_post_prelayout(project, top, native_result=native)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        return {'verdict': 'NOT_MEASURED', 'detail': str(exc)}
    current = next((row for row in versions.current_acceptance(project, began)
                    if str(row['id']) == '8'), None)
    if current is None:
        return {'verdict': 'FAIL' if result.status == 'FAIL' else 'NOT_MEASURED',
                'detail': result.detail or 'Step8 published no complete consumer'}
    consumer = (current.get('result') or {}).get('canonical_consumer') or {}
    status = ('PASS' if current.get('canonical_pass') and current['status'] == 'PASS'
              and consumer.get('status') == 'PASS' else
              'FAIL' if current['status'] == 'FAIL' else 'NOT_MEASURED')
    return {'verdict': status, 'folder': current['folder'],
            'detail': '; '.join(consumer.get('step', {}).get('reasons', ())) or result.detail}


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
               env: Optional[Dict[str, str]] = None, *,
               _retain_mixed: bool = True,
               invocation: Optional[Dict[str, Any]] = None) -> int:
    mixed_step = {"mixed_signal_top_lvs_run.py": "M1",
                  "mixed_signal_power_domain_run.py": "M2",
                  "mixed_signal_m3_run.py": "M3",
                  "mixed_signal_signoff_run.py": "M4"}.get(runner.name)
    stage_analog = (runner.name == 'flow_compliance_check.py'
                    and '--stage-id' in args
                    and args[args.index('--stage-id') + 1] == 'stage_analog')
    retained_id = mixed_step
    if retained_id is not None and _retain_mixed:
        import step_preflight
        return step_preflight.retained_call(
            Path(args[0]), retained_id, _run_phase, label, runner, args,
            env=env, _retain_mixed=False, invocation=invocation,
            canonical_acceptance=True)
    history = None
    if stage_analog and _retain_mixed and '--json' in args:
        import execution_policy
        if execution_policy.request()['mode'] == 'default':
            # This is a scoped audit, not a synthesis producer. Preserve its
            # report versions without allocating a synthetic Step14 invocation.
            report = Path(args[args.index('--json') + 1])
            history = report.parent / 'history' / f'{report.stem}_{time.time_ns()}'
            history.mkdir(parents=True)
            if report.is_file():
                shutil.copy2(report, history / 'before.json')
    # Default retains the selected call before invalidating its audit file.
    # Other modes keep their established caller-side invalidation.
    if (mixed_step in {"M2", "M3", "M4"} or stage_analog) and "--json" in args:
        import execution_policy
        if execution_policy.request()["mode"] == "default":
            Path(args[args.index("--json") + 1]).unlink(missing_ok=True)
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
    try:
        command = [sys.executable, str(runner), *args]
        _verify_runtime_command(command)
        child_env = env
        if invocation is not None:
            import benchmark_dispatch as dispatch

            context = {
                "invocation_id": uuid.uuid4().hex,
                "argv": command,
                "project": str(Path(args[0]).resolve()),
                "source": dispatch._runner_source_snapshot(command),
            }
            invocation.clear()
            invocation.update(context)
            child_env = dict(env or os.environ)
            child_env[dispatch._RUNNER_CONTEXT_ENV] = json.dumps(
                context, sort_keys=True)
        cp = subprocess.run(command, env=child_env,
                            pass_fds=(_execution.child_pass_fds()
                                       if supports_execution_policy else ()))
        return cp.returncode
    finally:
        if history is not None and report.is_file():
            shutil.copy2(report, history / 'after.json')


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
                       phase3_rederive_ic_name: Optional[str] = None,
                       pdk: str = "auto"
                       ) -> List[str]:
    """Build the canonical Phase-2 argv with explicit opt-ins only.

    The bounded LEC value is absent by default, preserving Step 13's
    unbounded producer behaviour.  This seam is deliberately pure so the
    front-door forwarding contract can be tested without launching a flow.
    """
    result = [str(project), "--top-name", top_name, "--container", container,
              "--max-rtl-repair-retries", str(max_rtl_repair_retries)]
    if pdk != "auto":
        result += ["--pdk", pdk]
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


def _rollup_phase_rows(plan, execution_mode=None):
    """Use the same applicable phase population in the runner and report reader."""
    excluded = () if execution_mode == 'default' else (
        'analog', 'mixed_signal', 'mixed_signal_M2', 'mixed_signal_M3', 'mixed_signal_M4')
    return [(name, verdict, rc) for name, verdict, rc in plan
            if name not in excluded and verdict != 'SKIPPED']


def _roll_up(rows: List[Tuple[str, str, int]],
             completion_audit_verdicts: Optional[List[str]] = None,
             demoted: Optional[Dict[str, Dict[str, Any]]] = None,
             audit_axis: Optional[Dict[str, Any]] = None,
             halted_at: Optional[str] = None
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

    # A retained checkpoint can be a passing tier without satisfying the
    # stricter downstream handoff. Keep its row intact, but a halted whole
    # invocation has not completed merely because later rows were skipped.
    # Scoped phase/window callers omit this whole-invocation context.
    if halted_at:
        unmeasured.append(f"invocation halted at {halted_at}; downstream dispatch did not complete")
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


def _phase3_window_report_path(project: Path, window_run_id: str) -> Path:
    """The terminal account published for this parent's exact window token."""
    return (project / "reports/orchestrator/windows" / window_run_id
            / "phase3_one_shot.json")


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


def _current_default_acceptance(project: Path, started_at: float) -> list:
    import execution_policy
    if execution_policy.request()['mode'] != 'default':
        return []
    import step_output_collector
    return step_output_collector.current_acceptance(project, started_at)


def _acceptance_status(record: dict) -> str:
    result = record.get('result') or {}
    consumer = result.get('canonical_consumer') or result.get('canonical_step_result') or {}
    step = consumer.get('step', consumer)
    status = record['status']
    # Honor the canonical consumer's existing board exclusion. A measured
    # FAIL cannot be excluded, and an absent board never becomes PASS.
    if status == 'NOT_MEASURED' and step.get('excluded_from_verdict'):
        return 'NOT_APPLICABLE'
    return status


def _default_track_verdict(project: Path, started_at: float, step_id: str,
                           verdict: str) -> str:
    """A selected mixed producer advances only after its current complete check."""
    import execution_policy
    if execution_policy.request()['mode'] != 'default':
        return verdict
    records = [row for row in _current_default_acceptance(project, started_at)
               if str(row['id']) == step_id]
    blocked = [row for row in records if _acceptance_status(row) not in
               ('PASS', 'PASS_WITH_WAIVERS', 'NOT_APPLICABLE')]
    if verdict == 'FAIL' or any(row['status'] == 'FAIL' for row in blocked):
        return 'FAIL'
    if blocked or verdict == 'NOT_READY':
        return 'NOT_MEASURED'
    if verdict == 'PASS' and any(_acceptance_status(row) == 'PASS_WITH_WAIVERS'
                                 for row in records):
        return 'PASS_WITH_WAIVERS'
    return verdict


def _row_verdict(project: Path, report_name: str, rc: int, started_at: float,
                 phase: str, *, _acceptance=None,
                 report_path: Optional[Path] = None,
                 expected_window_run_id: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """This phase's verdict, or NOT_MEASURED with the reason. R-0915-151.

    A phase that RAN here and left no report written at or after its own start has
    not published a verdict, and `("PASS" if rc == 0 else "FAIL")` invents one. The
    case is real and shipped: phase3's `[SKIP] no usable PDK` returns 0 WITHOUT
    writing a report, so the front door read either a stale `phase3_one_shot.json`
    from an earlier run or a PASS conjured from rc 0 -- for a phase that measured
    nothing at all.
    """
    accepted = (_current_default_acceptance(project, started_at)
                if _acceptance is None else _acceptance)
    blocked = [record for record in accepted if _acceptance_status(record) not in
               ('PASS', 'PASS_WITH_WAIVERS', 'NOT_APPLICABLE')]
    consumer_reason = (f"{phase}'s current canonical consumer did not accept " +
                       ', '.join(f"step {record['id']}: {record['status']}" for record in blocked))
    if any(record['status'] == 'FAIL' for record in blocked):
        return 'FAIL', consumer_reason
    if report_path is None:
        path = _phase_report_path(project, report_name)
        exists = _report_exists(project, report_name)
        fresh = _published_here(project, report_name, started_at)
    else:
        path = report_path
        exists = path.is_file()
        fresh = _pl.published_here(path, started_at)
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
    if report_path is not None and not isinstance(rep, dict):
        rep = {}
    if expected_window_run_id is not None and not (
            rep.get("bounded") and
            rep.get("window_run_id") == expected_window_run_id and
            rep.get("verdict")):
        # Check provenance BEFORE a report can supply the phase row. Checking
        # it only later for the bounded label still borrowed PASS from another
        # window (or the rc=0 fallback of an incomplete account).
        return ("FAIL" if rc else "NOT_MEASURED"), (
            f"{phase} exited {rc}, but {path} does not carry this window's "
            f"bounded identity and stated verdict ({expected_window_run_id}); "
            "its phase verdict is not adopted")
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
    verdict = str(verdict) if verdict else ('PASS' if rc == 0 else 'FAIL')
    if (expected_window_run_id is not None
            and _roll_up([(phase, verdict, 0)])[0] == 'NOT_MEASURED'):
        return 'NOT_MEASURED', (
            f"{phase}'s scoped report states {verdict!r}; the existing phase "
            "roll-up does not accept it as a measured success")
    if verdict == 'FAIL':
        return verdict, None
    if blocked:
        return 'NOT_MEASURED', consumer_reason
    if verdict == 'PASS' and any(_acceptance_status(record) == 'PASS_WITH_WAIVERS'
                                 for record in accepted):
        return 'PASS_WITH_WAIVERS', f"{phase}'s current canonical consumer retains an existing waiver"
    return verdict, None


def _phase2_pad_top_deferral(project: Path, report: dict, started_at: float) -> Optional[dict]:
    """Carry only the Step-5 obligation owned by the later pad-top producer."""
    import design_one_shot_runner as design
    import full_stack_functional_tb as functional
    import librelane_contract as contract
    import flow_compliance_check as compliance
    import _flow_yaml
    try:
        if (report.get('verdict') != 'NOT_MEASURED' or report.get('ai_judgements')
                or report.get('final_audit_pending') or report.get('declared_window')):
            return None
        rows = report['steps']
        deferred = [r for r in rows if r['name'] == 'full_stack_functional_tb']
        audits = [r for r in rows if r['name'] == 'final_audit']
        if (len(deferred) != 1 or deferred[0]['status'] != 'NOT_MEASURED'
                or len(audits) != 1 or audits[0]['status'] != 'NOT_MEASURED'):
            return None
        remaining = [design.StepResult(**r) for r in rows
                     if r['name'] not in ('full_stack_functional_tb', 'final_audit')]
        remaining_verdict = design._aggregate_verdict(remaining)
        if not remaining or remaining_verdict not in ('PASS', 'PASS_WITH_WAIVERS'):
            return None
        audit_path = project / 'reports/phase2/gates/phase2_compliance.json'
        gate_path = project / 'reports/phase2/gates/bit_level_full_stack.json'
        if not all(_pl.published_here(p, started_at) for p in (audit_path, gate_path)):
            return None
        audit = json.loads(audit_path.read_text())
        gate = json.loads(gate_path.read_text())
        if (audit.get('program') != 'flow_compliance_check'
                or Path(audit['project']).resolve() != project.resolve()
                or audit['scope']['phase'] != '2' or audit['scope'].get('stage')
                or audit['scope'].get('stage_id') or audit.get('overall') != 'NOT_MEASURED'
                or audit.get('structural_fail_lines') or audit.get('step_artifact_fail_lines')
                or audit.get('ordering_violations_gating') or audit.get('blocker_list_error')
                or audit.get('blocker_contract_violations')):
            return None
        incomplete = [r for r in audit['steps'] if r['status'] not in
                      ('PASS', 'PASS_WITH_WAIVERS', 'NOT_APPLICABLE')
                      and not (r['status'] == 'NOT_MEASURED' and r.get('excluded_from_verdict'))]
        audited_ids = [str(r['id']) for r in audit['steps']]
        declared_ids = {str(r['id']) for r in _flow_yaml.load()['steps']
                        if (isinstance(r['id'], int) and 1 <= r['id'] <= 6)
                        or (not isinstance(r['id'], int) and (
                            str(r.get('phase_scope') or '').strip().lower() == 'agnostic'
                            or compliance._STAGE_PHASE.get(
                                str(r.get('stage') or '').strip()) in (None, '2')))}
        if (not audited_ids or len(audited_ids) != len(set(audited_ids))
                or set(audited_ids) != set(audit['scope']['steps_judged'])
                or audit['scope']['step_count'] != len(audited_ids)
                or set(audited_ids) != declared_ids):
            return None
        ledger = audit['gate_execution_ledger']
        blocked = [r for r in ledger if r['verdict'] not in
                   ('PASS', 'PASS_WITH_WAIVERS', 'NOT_APPLICABLE')]
        if (not ledger or len(incomplete) != 1 or str(incomplete[0]['id']) != '5'
                or incomplete[0]['status'] != 'NOT_MEASURED' or len(blocked) != 1
                or blocked[0]['gate'] != 'bit_level_full_stack_tb_check'
                or blocked[0]['rc'] != 2 or blocked[0].get('exit_code') != 2
                or blocked[0].get('structured_verdict') != 'NOT_MEASURED'
                or blocked[0]['reason_class'] != 'BLOCKED_BY_UPSTREAM'
                or gate.get('rule') != 'functional_full_stack_top_absent'
                or gate.get('verdict') != 'NOT_MEASURED'
                or gate.get('reason_class') != 'BLOCKED_BY_UPSTREAM'):
            return None
        accepted = _current_default_acceptance(project, started_at)
        rejected = [r for r in accepted if _acceptance_status(r) not in
                    ('PASS', 'PASS_WITH_WAIVERS', 'NOT_APPLICABLE')]
        if not rejected or any(str(r['id']) != '5' or r['status'] != 'NOT_MEASURED'
                               for r in rejected):
            return None
        record = json.loads(functional.record_path(project).read_text())
        required = functional.required_full_stack_top(project)
        inputs = functional._design_input_digest(project)
        if (required.get('refusal_class') != 'BLOCKED_BY_UPSTREAM'
                or not required['pad_ring'] or record.get('reason_class') != 'BLOCKED_BY_UPSTREAM'
                or record.get('verdict') != 'NOT_MEASURED'
                or record.get('generated_at_unix', 0) < started_at
                or record.get('design_input') != inputs):
            return None
        rtl = {str(p.relative_to(project)): contract.digest(p)
               for p in functional._rtl_sources(project)}
        context = {name: contract.digest(project / 'phase1/generated_docs' / name)
                   for name in ('L3_CMD_PROTOCOL.json', 'L4_REGMAP.json')}
        if not rtl or not all(context.values()):
            return None
        return {'step': '5', 'status': 'NOT_MEASURED', 'state': 'DEFERRED',
                'owner': 'phase3.io_pad_chip_top_gen', 'project': str(project.resolve()),
                'remaining_verdict': remaining_verdict, 'design_input': inputs, 'rtl': rtl,
                'gate_context': context,
                'source': {Path(m.__file__).name: contract.digest(Path(m.__file__))
                           for m in (functional, design)},
                'outer_source_sha256': contract.digest(Path(__file__)),
                'phase2_audit_sha256': contract.digest(audit_path)}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _resolve_phase2_pad_top(project: Path, deferred: dict, started_at: float) -> Tuple[str, int]:
    """Resolve the named obligation with its current complete late consumer."""
    import full_stack_functional_tb as functional
    import bit_level_full_stack_tb_check as gate
    import librelane_contract as contract
    try:
        report = json.loads((project / 'reports/phase3/gates/full_stack_functional.json').read_text())
        bound = report['post_padring']
        if (not isinstance(bound, dict) or not isinstance(deferred.get('rtl'), dict)
                or not isinstance(deferred.get('source'), dict)
                or not isinstance(bound.get('source'), dict)
                or set(deferred['source']) != {'full_stack_functional_tb.py', 'design_one_shot_runner.py'}
                or set(bound['source']) != {'full_stack_functional_tb.py',
                                           'bit_level_full_stack_tb_check.py', 'phase3_one_shot_runner.py'}):
            return 'NOT_MEASURED', 2
        if (bound['project'] != deferred['project'] or deferred['project'] != str(project.resolve())
                or bound['started_at'] < started_at
                or bound['pad_producer_started_at'] < started_at
                or bound['pad_producer_started_at'] > bound['started_at']
                or not deferred['rtl'] or not deferred['source'] or not bound['source']
                or deferred['outer_source_sha256'] != contract.digest(Path(__file__))
                or deferred['phase2_audit_sha256'] != contract.digest(
                    project / 'reports/phase2/gates/phase2_compliance.json')
                or deferred['design_input'] != functional._design_input_digest(project)
                or set(deferred['gate_context']) != {'L3_CMD_PROTOCOL.json', 'L4_REGMAP.json'}
                or any(contract.digest(project / 'phase1/generated_docs' / name) != sha
                       for name, sha in deferred['gate_context'].items())
                or any(not (project / p).is_file() or contract.digest(project / p) != sha
                       for p, sha in deferred['rtl'].items())
                or any(contract.digest(PROGRAMS_DIR / name) != sha
                       for name, sha in deferred['source'].items())
                or any(contract.digest(PROGRAMS_DIR / name) != sha
                       for name, sha in bound['source'].items())
                or bound['functional_record_sha256'] != contract.digest(functional.record_path(project))
                or bound['chip_top_record_sha256'] != contract.digest(project / functional.CHIP_TOP_RECORD_REL)):
            return 'NOT_MEASURED', 2
        rc, current, _sentinel = gate.functional_full_stack_verdict(project)
        if rc != bound['rc'] or current['verdict'] != report['verdict']:
            return 'NOT_MEASURED', 2
        if current['verdict'] == 'PASS':
            return deferred['remaining_verdict'], rc
        return current['verdict'], rc
    except (OSError, ValueError, KeyError, TypeError):
        return 'NOT_MEASURED', 2


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


def _record_continuation_evidence(project: Path, entry: str, exit_: Optional[str],
                                  reason: Optional[str] = None) -> None:
    """Publish an advisory byte inventory before the existing bounded dispatch."""
    import _flow_yaml
    import step_output_collector as versions
    import datetime
    order = list(map(str, _flow_yaml.ordered_step_ids()))
    end = str(exit_) if exit_ is not None else order[-1]
    try:
        lo, hi = order.index(str(entry)), order.index(end)
        if lo > hi:
            return  # The existing owner reports invalid windows.
        evidence = versions.continuation_evidence(project, order[lo:hi + 1])
        if reason:
            evidence["reason"] = reason
            evidence["selection"] = "evidence-based ordinary recovery"
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
        path = project / 'reports/orchestrator' / f'continuation_plan-{stamp}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, indent=2) + '\n')
        print(f'[continuation] requested={",".join(evidence["requested_steps"])}; '
              f'unchanged retained={len(evidence.get("retained_unchanged_steps", []))}; '
              f'unknown impact={len(evidence["unknown_impact"])}; '
              f'no automatic expansion; evidence={path}', flush=True)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Evidence inspection is advisory; never convert a report failure
        # into a phase restart or a fabricated checkpoint acceptance.
        print(f'[continuation] evidence unavailable: {exc}; requested scope unchanged', flush=True)


def _resume_dependency_graph() -> Tuple[List[str], Dict[str, set]]:
    """Return canonical order and the flow's existing direct dependencies.

    This deliberately reads the declared flow instead of introducing another
    checkpoint/dependency registry.  ``required_inputs.from`` is the byte
    dependency; ``blocks_on`` is the verdict dependency already consumed by
    flow compliance.
    """
    import _flow_yaml
    rows = _flow_yaml.load().get("steps") or []
    order = [str(row["id"]) for row in rows if isinstance(row, dict) and "id" in row]
    declared = set(order)
    graph: Dict[str, set] = {sid: set() for sid in order}
    for row in rows:
        if not isinstance(row, dict) or "id" not in row:
            continue
        sid = str(row["id"])
        for dep in row.get("blocks_on") or []:
            if str(dep) in declared:
                graph[sid].add(str(dep))
        for item in row.get("required_inputs") or []:
            if (isinstance(item, dict) and item.get("from") is not None
                    and str(item["from"]) in declared):
                graph[sid].add(str(item["from"]))
    return order, graph


def _validated_disproven_output(project: Path, item: Mapping[str, Any],
                                 consumer: str, versions: Any) -> Tuple[Optional[str], Optional[str]]:
    """Validate an existing immutable failed-consumer receipt.

    The receipt is an ordinary retained ``outputs.json`` attempt, not a new
    evidence format.  It must be content-addressed, fail for the named
    consumer, and bind one exact input to the current retained producer output.
    """
    sid = str(item.get("step_id") or "")
    receipt_rel = item.get("receipt")
    receipt_sha = item.get("receipt_sha256")
    output_rel = item.get("output_path")
    output_sha = item.get("output_sha256")
    if not all(isinstance(value, str) and value for value in
               (receipt_rel, receipt_sha, output_rel, output_sha)):
        return None, f"step {sid} disproval lacks immutable receipt/output bindings"
    root = project.resolve()
    receipt = (root / receipt_rel).resolve()
    retained_root = versions._versions_root(root).resolve()
    if (not receipt.is_relative_to(retained_root)
            or receipt_rel != str(receipt.relative_to(root))
            or receipt.name != "outputs.json" or receipt.is_symlink()
            or not receipt.is_file()):
        return None, f"step {sid} disproval receipt is not a retained outputs.json"
    raw = receipt.read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt_sha:
        return None, f"step {sid} disproval receipt hash mismatch"
    try:
        record = json.loads(raw)
    except (ValueError, TypeError):
        return None, f"step {sid} disproval receipt is not valid JSON"
    # Content addressing proves only that the caller supplied the bytes it
    # hashed.  Producer authority comes from the collector's existing attempt
    # journal and current index row, all naming this exact retained folder.
    try:
        indexed = [row for row in versions._read_index(root).get("steps", [])
                   if isinstance(row, dict) and str(row.get("id")) == consumer]
        if len(indexed) != 1:
            raise ValueError
        index_row = indexed[0]
        attempt = json.loads((receipt.parent / "attempt.json").read_text())
        folder = receipt.parent.relative_to(retained_root)
        identity = ("id", "name", "phase", "stage", "folder")
        if (index_row.get("versioned") is not True
                or index_row.get("status") != "FAIL"
                or str(folder) != index_row.get("folder")
                or receipt != retained_root / index_row["folder"] / "outputs.json"
                or any(record.get(key) != index_row.get(key) for key in identity)
                or any(record.get(key) != attempt.get(key) for key in identity)
                or attempt.get("status") != "RUNNING"
                or record.get("storage_root") != str(retained_root.relative_to(root))
                or attempt.get("storage_root") != record.get("storage_root")
                or record.get("started_at") != attempt.get("started_at")
                or record.get("inputs") != attempt.get("inputs")
                or record.get("input_files") != attempt.get("input_files")
                or record.get("capture_errors") != []
                or attempt.get("capture_errors") != []):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None, f"step {sid} disproval is not a registered complete consumer attempt"
    result = record.get("result") or {}
    consumed = (result.get("canonical_consumer")
                or result.get("canonical_step_result") or {})
    consumed_status = consumed.get("verdict") or consumed.get("status")
    if (str(record.get("id")) != consumer or record.get("status") != "FAIL"
            or record.get("canonical_pass") is not False
            or consumed_status != "FAIL" or not record.get("started_at")
            or not record.get("finished_at")):
        return None, f"step {sid} disproval is not a bound failed consumer {consumer} receipt"
    bound = (record.get("inputs") or {}).get(output_rel)
    bound_sha = bound.get("sha256") if isinstance(bound, dict) else bound
    if bound_sha != output_sha:
        return None, f"step {sid} disproval consumer subject hash mismatch"
    captured = [row for row in record.get("input_files") or []
                if isinstance(row, dict) and row.get("rel") == output_rel]
    if len(captured) != 1:
        return None, f"step {sid} disproval consumer input capture is incomplete"
    captured = captured[0]
    snapshot_rel = captured.get("snapshot")
    snapshot = receipt.parent / snapshot_rel if isinstance(snapshot_rel, str) else None
    if (captured.get("sha256") != output_sha
            or type(captured.get("size")) is not int or captured["size"] < 0
            or snapshot_rel != str(Path("inputs") / output_rel)
            or snapshot is None or snapshot.is_symlink() or not snapshot.is_file()
            or not snapshot.resolve().is_relative_to(receipt.parent.resolve())
            or snapshot.stat().st_size != captured["size"]
            or hashlib.sha256(snapshot.read_bytes()).hexdigest() != output_sha):
        return None, f"step {sid} disproval consumer input capture does not bind subject bytes"
    retained = versions.latest_pass(project, sid)
    if not retained or not retained.get("canonical_pass"):
        return None, f"step {sid} has no retained canonical PASS to invalidate"
    outputs = {row.get("rel"): row.get("sha256")
               for row in retained.get("outputs") or [] if isinstance(row, dict)}
    live = (project / output_rel).resolve()
    if (outputs.get(output_rel) != output_sha or not live.is_relative_to(root)
            or not live.is_file()
            or hashlib.sha256(live.read_bytes()).hexdigest() != output_sha):
        return None, f"step {sid} disproval is stale or does not bind the retained output"
    return (f"failed consumer {consumer} receipt {receipt_rel} "
            f"sha256={receipt_sha} rejects {output_rel} sha256={output_sha}"), None


def _minimal_resume_plan(project: Path, request: Mapping[str, Any]) -> Dict[str, Any]:
    """Select the next *one* demonstrated recovery action from retained bytes.

    Recovery is intentionally iterative.  A changed/missing producer is run,
    then this planner is invoked again so its actual new output decides which
    dependent (if any) is next.  Scheduling a whole descendant cone before
    that observation is the broad-rerun defect tracked by #3480.
    """
    import step_output_collector as versions

    if request.get("schema") != "vibeic/minimal-resume-request/1":
        raise ValueError("resume request needs schema vibeic/minimal-resume-request/1")
    consumer = str(request.get("consumer_step") or "").strip()
    order, graph = _resume_dependency_graph()
    if consumer not in graph:
        raise ValueError(f"unknown consumer_step {consumer!r}")

    ancestors = set()
    pending = [consumer]
    while pending:
        sid = pending.pop()
        if sid in ancestors:
            continue
        ancestors.add(sid)
        pending.extend(graph.get(sid, ()))

    evidence = versions.continuation_evidence(project, order)
    rows = {str(row.get("step_id")): dict(row)
            for row in evidence.get("checkpoints") or []
            if isinstance(row, dict) and row.get("step_id") is not None}

    # A path resolver repair can move bytes without changing them.  The
    # request names both paths; the planner independently hashes the new path
    # and only then cancels the old-path "missing" observation.
    relocations = {}
    for item in request.get("equivalent_relocations") or []:
        if not isinstance(item, dict):
            continue
        old, new = item.get("retained_path"), item.get("current_path")
        if isinstance(old, str) and isinstance(new, str):
            relocations[old] = new
    for row in rows.values():
        kept = []
        accepted = []
        for diff in row.get("differences") or []:
            new_rel = relocations.get(diff.get("path"))
            new_path = (project / new_rel).resolve() if new_rel else None
            if (diff.get("kind") == "input" and diff.get("state") == "missing"
                    and new_path is not None
                    and new_path.is_relative_to(project.resolve())
                    and new_path.is_file() and not new_path.is_symlink()
                    and hashlib.sha256(new_path.read_bytes()).hexdigest()
                    == diff.get("retained_sha256")):
                accepted.append({"retained_path": diff["path"],
                                 "current_path": new_rel,
                                 "sha256": diff["retained_sha256"]})
            else:
                kept.append(diff)
        row["differences"] = kept
        if accepted:
            row["equivalent_relocations"] = accepted
            if row.get("observation") == "differences" and not kept:
                row["observation"] = "unchanged"

    explicit = request.get("explicit_rerun_steps") or []
    if explicit:
        explicit = [str(s) for s in explicit]
        bad = [s for s in explicit if s not in graph]
        if bad:
            raise ValueError("unknown explicit_rerun_steps: " + ", ".join(bad))
        return {
            "schema": "vibeic/minimal-resume-plan/1", "status": "READY",
            "reason": "explicit rerun request: " + str(request.get("reason") or "operator request"),
            "consumer_step": consumer, "execution_steps": explicit,
            "selection": "explicit_owner_window",
            "next_step": explicit[0], "remaining_explicit_steps": explicit[1:],
            "reused_checkpoints": [], "unknown_impact": [],
            "historical_records_mutated": False,
        }

    disproven = {}
    unresolved = []
    for item in request.get("disproven_outputs") or []:
        if not isinstance(item, dict) or str(item.get("step_id")) not in ancestors:
            continue
        sid = str(item.get("step_id"))
        proof, refusal = _validated_disproven_output(
            project, item, consumer, versions)
        if refusal:
            unresolved.append(refusal)
        elif proof:
            disproven[sid] = proof

    invalid = {}
    reused = []
    for sid in ancestors:
        row = rows.get(sid)
        if sid in disproven:
            invalid[sid] = "prior output disproven: " + disproven[sid]
            continue
        if row is None or row.get("observation") == "unknown":
            unresolved.append(f"step {sid} has insufficient retained provenance")
            continue
        diffs = row.get("differences") or []
        actionable = [d for d in diffs
                      if ((d.get("kind"), d.get("state")) in {
                              ("input", "changed"), ("output", "missing")}
                          or ((d.get("kind"), d.get("state")) ==
                              ("output", "changed")
                              and versions.registered_output_mismatch(
                                  project, sid, d.get("path"),
                                  d.get("retained_sha256"),
                                  d.get("current_sha256"))))]
        ambiguous = [d for d in diffs if d not in actionable]
        if ambiguous:
            unresolved.extend(
                f"step {sid} {d.get('kind')} {d.get('path')} is "
                f"{d.get('state')}; owner evidence is needed"
                for d in ambiguous)
        if actionable:
            invalid[sid] = "; ".join(
                f"{d.get('kind')} {d.get('path')} {d.get('state')}"
                for d in actionable)
        elif not ambiguous:
            reused.append(sid)

    base = {
        "schema": "vibeic/minimal-resume-plan/1", "consumer_step": consumer,
        "historical_records_mutated": False, "unknown_impact": [],
        "reused_checkpoints": [s for s in order if s in reused],
        "checkpoint_observations": [rows[s] for s in order if s in rows and s in ancestors],
    }
    if unresolved:
        return {**base, "status": "UNRESOLVED", "execution_steps": [],
                "unknown_impact": sorted(set(unresolved)),
                "reason": "insufficient provenance; inspect before scheduling producers"}

    # The first invalid row in canonical order is the earliest demonstrated
    # producer.  Dependents are deliberately deferred until its new receipt is
    # visible, preventing a speculative phase restart.
    invalid_ordered = [s for s in order if s in invalid]
    if invalid_ordered:
        step = invalid_ordered[0]
        deferred = [s for s in invalid_ordered[1:] if s != step and s != consumer]
        if consumer != step:
            deferred.append(consumer)
        return {**base, "status": "READY", "execution_steps": [step],
                "next_step": step, "reason": invalid[step],
                "deferred_for_replanning": deferred}
    if bool(request.get("revalidate_consumer")):
        return {**base, "status": "READY", "execution_steps": [consumer],
                "next_step": consumer,
                "reason": str(request.get("reason") or "revalidate affected consumer"),
                "deferred_for_replanning": []}
    return {**base, "status": "NO_ACTION", "execution_steps": [],
            "unknown_impact": [],
            "reason": "no retained input/output invalidation was demonstrated"}


def _write_minimal_resume_plan(project: Path, plan: Mapping[str, Any]) -> Path:
    """Append a timestamped decision; never rewrite historical step records."""
    import datetime
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    path = project / "reports/orchestrator" / f"minimal_resume_plan-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(plan), indent=2, sort_keys=True) + "\n")
    return path


def _minimal_resume_entry(plan: Mapping[str, Any]) -> Optional[Tuple[str, str]]:
    """Translate one action or explicit contiguous window to an existing entry."""
    steps = list(plan.get("execution_steps") or [])
    if plan.get("status") != "READY" or not steps:
        return None
    steps = [str(step) for step in steps]
    if len(steps) == 1:
        return steps[0], steps[0]
    if plan.get("selection") != "explicit_owner_window":
        return None
    order, _ = _resume_dependency_graph()
    try:
        start = order.index(steps[0])
        end = order.index(steps[-1])
    except ValueError:
        return None
    if start >= end or steps != order[start:end + 1]:
        return None
    return steps[0], steps[-1]


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
    p.add_argument('--step', help='Flow109 row for a single diagnostic gate')
    p.add_argument('--only', help='Exact source-owned diagnostic gate name')
    p.add_argument('--dry-run', action='store_true',
                   help='Run one diagnostic gate without publishing project artifacts')
    p.add_argument("--flow", choices=("109",), default="109",
                   help="Flow109 canonical public runtime (default: 109), "
                        "using current D01..D81, A01..A19 and M01..M09 row "
                        "IDs from flow/flow109.json.")
    p.add_argument("--flow109-manifest", type=Path,
                   help="JSON containing explicit Boolean features, step_profiles, runtime_tool_uses and qualification_registry.")
    p.add_argument("--flow109-plan-only", action="store_true",
                   help="Resolve 109 configuration without starting any native producer; never reports IC PASS.")
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
    p.add_argument("--rtl-input", choices=("structured", "original"), default="structured",
                   help="RTL authoring input authority; original consumes the complete original specification in a bounded RTL-only window.")
    p.add_argument("--entry-step", default=None,
                   help="START an explicit Flow109 window at a current "
                        "canonical row ID: D01..D81, A01..A19 or M01..M09. "
                        "The row must be selected and applicable in the "
                        "--flow109-manifest; the registry routes it to its "
                        "existing owner or adapter and refuses unsupported "
                        "owner crossings or unimplemented rows. Supply "
                        "--exit-step; for one row, pass the same ID to both "
                        "bounds. Internal numeric/native keys are not public "
                        "step IDs. Window rc covers dispatched rows only, "
                        "separate from Flow109 and whole-flow acceptance.")
    p.add_argument("--exit-step", default=None,
                   help="END the explicit Flow109 window inclusively at a "
                        "current canonical Dxx, Axx or Mxx row ID. It is "
                        "required with --entry-step; both bounds must be "
                        "selected and applicable, ordered by the current "
                        "registry, and supported by compatible registered "
                        "dispatch owners. Rows outside the window are not "
                        "dispatched. Window rc covers dispatched rows only, "
                        "separate from Flow109 and whole-flow acceptance.")
    p.add_argument("--resume-request", type=Path,
                   help="JSON ordinary-recovery request. Retained per-step "
                        "input/output hashes select at most the next "
                        "demonstrated step; this is distinct from an explicit "
                        "--entry-step rerun.")
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
    if args.resume_request and (args.entry_step or args.exit_step):
        p.error("--resume-request cannot be combined with explicit --entry-step/--exit-step")
    if bool(args.area_receipt) != bool(args.area_run_manifest):
        p.error("--area-receipt and --area-run-manifest must be supplied together")
    # The owner answer is recorded/validated before checking execution authority.
    # Imported API calls may express a route, but cannot start any producer.
    project = args.project.resolve()
    if not project.is_dir():
        print(f'ERROR: not a directory: {project}', file=sys.stderr)
        return 2
    if args.dry_run or args.step or args.only:
        if (not args.dry_run or args.step != 'D10' or not args.only
                or args.entry_step or args.exit_step or args.resume_request
                or args.flow109_plan_only):
            print('REFUSED: single-gate diagnostic requires --step D10 --only <gate> --dry-run without a flow window', file=sys.stderr)
            return 2
        import flow109_metric_acceptance
        diagnostic = flow109_metric_acceptance.dry_run_d10(project, args.only)
        print(json.dumps(diagnostic, sort_keys=True))
        return {'PASS': 0, 'FAIL': 1, 'NOT_MEASURED': 2}[diagnostic['gate_status']]
    route_refusal = _delivery_route.admit(project, args.route)
    if route_refusal:
        print(_delivery_route.refusal_message(route_refusal), file=sys.stderr)
        return 2
    import flow109
    try:
        flow_result = flow109.prepare_front_door(args, project)
    except flow109.Flow109Error as exc:
        if exc.code == "FLOW109_DFT_INTENT_MISSING":
            print(f"REFUSED: D22 input MISSING: {exc}", file=sys.stderr)
        else:
            print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        if args.flow != "109" or not hasattr(exc, "report") or not hasattr(exc, "code"):
            raise
        from _atomic_artefact import write_json
        write_json(project / "reports" / "flow109" / "admission.json", exc.report)
        print(f"REFUSED: {exc.code}: {exc}", file=sys.stderr)
        return 2
    except ImportError as exc:
        if args.flow != "109":
            raise
        print(f"REFUSED: FLOW109_ADMISSION_UNIMPLEMENTED: {exc}", file=sys.stderr)
        return 2
    if flow_result is not None:
        return flow_result
    if (args.execution_mode == 'ultra' or args.route_authority_only) and 'VIBEIC_EXECUTION_CAP_FD' not in os.environ:
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

    _resume_plan = None
    if args.resume_request:
        try:
            _resume_request = json.loads(args.resume_request.read_text())
            if not isinstance(_resume_request, dict):
                raise ValueError("request root is not an object")
            _resume_plan = _minimal_resume_plan(project, _resume_request)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            print(f"REFUSED: minimal resume request: {exc}", file=sys.stderr)
            return 2
        _selected = list(_resume_plan.get("execution_steps") or [])
        _resume_entry = _minimal_resume_entry(_resume_plan)
        if _selected and _resume_entry is None:
            # Never infer a window from an automatic/disjoint set.  Only the
            # owner's explicit canonical contiguous list reaches the already
            # supported entry/exit interface.
            _resume_plan["status"] = "UNRESOLVED"
            _resume_plan["unknown_impact"] = [
                "multiple steps are not one explicit canonical contiguous window"]
            _resume_plan["execution_steps"] = []
            _selected = []
        if _resume_entry:
            args.entry_step, args.exit_step = _resume_entry

    try:
        _pl.select_rtl_input(project, args.rtl_input, args.entry_step, args.exit_step)
        _activate_runtime_program_tree(project)
    except Exception as exc:
        print(f"REFUSED: runtime program tree: {exc}", file=sys.stderr)
        return 2

    # ---------------- Single-driver project lock (ORGANIC #498) ----------
    # Refuse a second concurrent invocation on a project already being
    # driven by a LIVE runner; clean a stale lock left by a dead one.
    # Acquired BEFORE any reports/manifests/provenance are written so two
    # racing orchestrators can never co-write the same reports/ tree.
    lock = _runner_lock.acquire_or_reenter(project, "vibe_ic_one_shot_runner")
    if lock is None:
        return 3
    if _resume_plan is not None:
        _resume_path = _write_minimal_resume_plan(project, _resume_plan)
        print(f"[resume] status={_resume_plan['status']}; "
              f"execute={','.join(_resume_plan.get('execution_steps') or []) or '-'}; "
              f"reason={_resume_plan.get('reason')}; plan={_resume_path}", flush=True)
        if _resume_plan["status"] != "READY":
            lock.release()
            return 0 if _resume_plan["status"] == "NO_ACTION" else 2
    # The route is an owner decision. Refuse before image capture, dashboard,
    # Phase 1, or any other producer can create a misleading partial run.
    route_refusal = _delivery_route.admit(project, args.route)
    if route_refusal:
        print(_delivery_route.refusal_message(route_refusal), file=sys.stderr)
        lock.release()
        return 2
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
        flow109.finish_native_window(project, {
            "steps": [], "flow109_stop_reason":
            "required container image identity was not satisfied"})
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
    _prelayout_entry = (str(getattr(args, 'entry_step', None)) == '10'
                        and execution_policy_value['mode'] == 'default')
    _flow109_owner_entry = bool(os.environ.get('VIBEIC_FLOW109_CONTEXT'))
    _sdc_early_entry = (str(getattr(args, 'entry_step', None)) == '8'
                        and execution_policy_value['mode'] == 'default'
                        and _flow109_owner_entry)
    _sdc_postcheck_entry = (str(getattr(args, 'entry_step', None)) == '8'
                            and execution_policy_value['mode'] == 'default'
                            and not _flow109_owner_entry)
    _dft_entry = (str(getattr(args, 'entry_step', None)) == '11'
                  and execution_policy_value['mode'] == 'default'
                  and not (_flow109_owner_entry
                           and _flow109_selected_row('D25')
                           and str(getattr(args, 'exit_step', None)) == '13'))
    _post_dft_entry = (str(getattr(args, 'entry_step', None)) == '12'
                       and execution_policy_value['mode'] == 'default')
    if getattr(args, "entry_step", None):
        try:
            import step_preflight as _spf_o          # noqa: PLC0415
        except ImportError as _e:
            print(f"REFUSED: --entry-step needs step_preflight ({_e})",
                  file=sys.stderr)
            return 2
        _entry_runner = _spf_o.runner_for_step(str(args.entry_step))
        if (_prelayout_entry or _sdc_early_entry or _sdc_postcheck_entry
                or _dft_entry or _post_dft_entry):
            # These retained Default owners have complete consumers and do
            # not need the larger dispatch span that normally contains them.
            _entry_runner = 'design_one_shot_runner'
        if _entry_runner is None and execution_policy_value['mode'] == 'default':
            # Default's native backend rows have their own input contracts
            # and checkpoints. They no longer need the monolithic PnR head.
            from phase3_one_shot_runner import _phase3_window_sites
            try:
                native_sites = _phase3_window_sites(str(args.entry_step),
                                                    str(args.entry_step))
            except ValueError:
                native_sites = []
            if native_sites in (['default_pnr'], ['default_backend']):
                _entry_runner = 'phase3_one_shot_runner'
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
        _record_continuation_evidence(
            project, str(args.entry_step), args.exit_step,
            (str(_resume_plan.get("reason")) if _resume_plan is not None else None))
        if _sdc_early_entry and str(args.exit_step) != '8':
            print('REFUSED: Default Step8 early preflight needs --exit-step 8', file=sys.stderr)
            lock.release()
            return 2
        if _sdc_postcheck_entry and str(args.exit_step) != '8':
            print('REFUSED: Default Step8 postcheck needs --exit-step 8', file=sys.stderr)
            lock.release()
            return 2
        if _post_dft_entry and str(args.exit_step) != '12':
            print('REFUSED: Default Step12 post-DFT owner needs --exit-step 12', file=sys.stderr)
            lock.release()
            return 2
        if _dft_entry and str(args.exit_step) != '11':
            print('REFUSED: Default Step11 DFT owner needs --exit-step 11', file=sys.stderr)
            lock.release()
            return 2

    if _entry_runner == "phase3_one_shot_runner":
        # A Phase-3 entry is an isolated backend repair.  Do not run Phase 1,
        # Phase 2, analog, mixed signal or the whole-flow finalize tail here.
        # The backend owns the exact dispatch and its bounded audit.
        if not args.exit_step:
            print("REFUSED: a Phase-3 entry needs --exit-step", file=sys.stderr)
            return 2
        step5_acceptance = (_revalidate_step5_checkpoint(project)
                            if execution_policy_value['mode'] == 'default'
                            and str(args.entry_step) == '15' else None)
        if step5_acceptance is not None and step5_acceptance['verdict'] != 'PASS':
            out = _pl.report_path(project, "vibe_ic_one_shot.json")
            out.parent.mkdir(parents=True, exist_ok=True)
            _write_runner_summary(out, {
                'program': 'vibe_ic_one_shot_runner', 'bounded': False,
                'verdict': step5_acceptance['verdict'], 'halted_at': 'phase2',
                'phases': [{'name': 'phase2', 'verdict': step5_acceptance['verdict'],
                            'rc': 1 if step5_acceptance['verdict'] == 'FAIL' else 2}],
                'step5_checkpoint_review': step5_acceptance,
                'whole_flow_verdict': 'NOT_MEASURED'}, project)
            flow109.finish_native_window(project, {
                'steps': [], 'flow109_stop_reason':
                'current Step5 checkpoint acceptance did not pass'})
            lock.release()
            return 1 if step5_acceptance['verdict'] == 'FAIL' else 2
        step7_acceptance = (_complete_step7_sdc(
            project, args.top_name, args.pdk, args.container)
            if execution_policy_value['mode'] == 'default'
            and str(args.entry_step) == '15' else None)
        if step7_acceptance is not None and step7_acceptance['verdict'] != 'PASS':
            status = step7_acceptance['verdict']
            out = _pl.report_path(project, 'vibe_ic_one_shot.json')
            out.parent.mkdir(parents=True, exist_ok=True)
            _write_runner_summary(out, {
                'program': 'vibe_ic_one_shot_runner', 'bounded': False,
                'verdict': status, 'halted_at': 'phase2',
                'phases': [{'name': 'phase2', 'verdict': status,
                            'rc': 1 if status == 'FAIL' else 2}],
                'step7_sdc_refresh': step7_acceptance,
                'whole_flow_verdict': 'NOT_MEASURED'}, project)
            flow109.finish_native_window(project, {
                'steps': [], 'flow109_stop_reason':
                'current Step7 constraint consumer did not pass'})
            lock.release()
            return 1 if status == 'FAIL' else 2
        # Only the signed Phase2 handoff adds Step14 here. Isolated backend
        # repairs without that checkpoint retain their existing entry scope.
        step14_acceptance = (_complete_step14_handoff(project)
                             if step5_acceptance is not None else None)
        if step14_acceptance is not None and step14_acceptance['verdict'] != 'PASS':
            out = _pl.report_path(project, "vibe_ic_one_shot.json")
            out.parent.mkdir(parents=True, exist_ok=True)
            _write_runner_summary(out, {
                'program': 'vibe_ic_one_shot_runner', 'bounded': False,
                'verdict': step14_acceptance['verdict'], 'halted_at': 'phase2',
                'phases': [{'name': 'phase2', 'verdict': step14_acceptance['verdict'],
                            'rc': 1 if step14_acceptance['verdict'] == 'FAIL' else 2}],
                'step5_checkpoint_review': step5_acceptance,
                'step14_handoff': step14_acceptance,
                'whole_flow_verdict': 'NOT_MEASURED'}, project)
            flow109.finish_native_window(project, {
                'steps': [], 'flow109_stop_reason':
                'current Step14 handoff consumer did not pass'})
            lock.release()
            return 1 if step14_acceptance['verdict'] == 'FAIL' else 2
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
        phase3_report = _phase3_window_report_path(project, window_run_id)
        p3 = (_read_report(phase3_report)
              if _pl.published_here(phase3_report, phase3_started) else {})
        if not (isinstance(p3, dict) and p3.get("bounded")
                and p3.get("window_run_id") == window_run_id and p3.get("verdict")):
            p3 = {}
        phase3_verdict, _fresh_why = (_row_verdict(
            project, "phase3_one_shot.json", rc, phase3_started, "phase3",
            report_path=phase3_report, expected_window_run_id=window_run_id)
            if p3 else ("NOT_MEASURED", "child report absent or invalid"))
        p3_stale = p3.get("stale_downstream") or {}
        summary = {"program": "vibe_ic_one_shot_runner", "bounded": bool(p3),
                   **_delivery_route.report_label(project),
                   "declared_window": {"entry_step": args.entry_step,
                                       "exit_step": args.exit_step,
                                       "entry_runner": _entry_runner},
                   "phases": [{"name": "phase3", "verdict": phase3_verdict,
                               "rc": rc}],
                   "dispatched_verdict": phase3_verdict,
                   "verdict": ("FAIL" if phase3_verdict == "FAIL" else "NOT_MEASURED"),
                   "whole_flow_verdict": "NOT_MEASURED",
                   "verdict_reasons": [_fresh_why] if _fresh_why else [],
                   "audit_verdict": "NOT_MEASURED",
                   "audit_scope": ("bounded; whole-flow audit not refreshed"
                                   if p3 else "not measured; child report absent"),
                   "bounded_disclosures": p3.get("bounded_disclosures", []),
                   "stale_downstream": p3_stale}
        if step5_acceptance is not None:
            summary['step5_checkpoint_review'] = step5_acceptance
        if step14_acceptance is not None:
            summary['step14_handoff'] = step14_acceptance
        out = _pl.report_path(project, "vibe_ic_one_shot.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        _write_runner_summary(out, summary, project)
        # Retain the canonical per-row outcome without promoting component
        # success to Flow109 metric or whole-flow acceptance.
        flow109.finish_native_window(project, p3, phase3_report)
        lock.release()
        return (rc or (0 if phase3_verdict in _PHASE_PASS | _PHASE_PASS_WITH_NOTE else 1)
                if p3 else (rc or 2))

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
    import _flow_yaml
    _canonical_order = _flow_yaml.ordered_step_ids()
    _physical_order = (_flow_yaml.ordered_step_ids(execution_stages=range(4, 9), execution_tracks=('default',))
                       if _execution.request()['mode'] == 'default' else
                       _flow_yaml.ordered_step_ids(stages=('stage3', 'stage4')))
    _exit_label = str(args.exit_step) if args.exit_step else None
    # IDs survive reordering. In particular final PV31 follows stream37;
    # comparing their numbers would launch a whole backend for a narrow exit.
    _p3_skip_by_exit = bool(
        _exit_label in _canonical_order and _physical_order
        and _canonical_order.index(_exit_label)
        < _canonical_order.index(_physical_order[0]))
    _p3_forward_window = bool(not args.skip_phase3
                              and _exit_label in _physical_order)
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
    import task_nature_route as _request_routes
    _rtl_only_request = bool(
        _execution.request()['mode'] == 'default' and args.skip_phase3
        and args.entry_step != 'D1'
        and _request_routes.is_rtl_only_evidence(exit_step=args.exit_step))
    _rtl_source_before = (_p1id.input_tree_snapshot(project)
                          if _rtl_only_request else {})
    _p1_knobs = {"ic_name": args.ic_name, "pdk": args.pdk, "mode": "docs"}
    _p1_checkpoint = (_execution.request()['mode'] == 'default'
                      and args.rtl_input != "original")
    run_phase1, p1_mode = _phase1_decision(
        project, _force_skip_p1, _p1_knobs, checkpoint=_p1_checkpoint)
    # What the generated L docs on disk ARE, asked once and carried into the
    # report whatever is decided from it.
    _gd_now = _pl.generated_docs_dir(project)
    _p1_fresh = ((_phase1_checkpoint_freshness(project, _p1_knobs)
                  if _p1_checkpoint else _phase1_freshness(project, _p1_knobs))
                 if _gd_now.is_dir() and len(list(_gd_now.glob("L*.json"))) >= 13
                 else None)
    _p1_design_input = _design_input_present(project)
    _phase1_checkpoint_review = None
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
    _p1_stale_why = None if args.rtl_input == "original" else _stale_generated_docs_note(
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
        _p1_acceptance = _current_default_acceptance(project, _phase_started['phase1'])
        verdict, _fresh_why = _row_verdict(
            project, "phase1_one_shot.json", rc,
            _phase_started.get("phase1", t0), "phase1", _acceptance=_p1_acceptance)
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
            if any(str(record['id']) != 'D1' and _acceptance_status(record) not in
                   ('PASS', 'PASS_WITH_WAIVERS', 'NOT_APPLICABLE')
                   for record in _p1_acceptance):
                cov_only = False
                advisories.append('phase1 has a current non-coverage canonical rejection: NOT demoting')
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
        elif verdict == 'NOT_MEASURED' and _execution.request()['mode'] == 'default':
            halted_at = 'phase1'
    else:
        plan.append(("phase1", "SKIPPED", 0))
        if (args.rtl_input != "original" and _execution.request()['mode'] == 'default'
                and _p1_fresh is not None
                and _p1_fresh['state'] in (_p1id.REUSE, _p1id.REVALIDATE)):
            # Producer freshness preserves the checkpoint; the current expert
            # consumer still decides whether Phase2 may use its documents.
            import ai_signed_judgement as _checkpoint_ai
            credit, detail = _checkpoint_ai.check(project, "D1")
            rejected = (not credit and _checkpoint_ai.check(
                project, "D1", expected_verdict="FAIL")[0])
            review = "PASS" if credit else "FAIL" if rejected else "NOT_MEASURED"
            _phase1_checkpoint_review = {
                "verdict": review, "detail": detail, "producer_reused": True}
            if credit and not _rtl_only_request:
                accepted = _revalidate_phase1_checkpoint(project, _p1_knobs)
                _phase1_checkpoint_review['canonical_acceptance'] = accepted
                review = accepted['verdict']
                credit = review == 'PASS'
                detail = accepted['detail']
                _phase1_checkpoint_review.update(verdict=review, detail=detail)
                plan[-1] = ("phase1", review, 0)
                if credit and _p1_fresh['state'] == _p1id.REVALIDATE:
                    # This run accepted old outputs through the current D1
                    # consumer. The original producer record stays untouched.
                    if _p1_stale_why in advisories:
                        advisories.remove(_p1_stale_why)
                    _p1_stale_why = None
                    _p1_fresh = {**_p1_fresh,
                                 'consumer_revalidated': True,
                                 'revalidation_folder': accepted['folder']}
                    advisories.append(
                        'REVALIDATED_PHASE1_CHECKPOINT: unchanged retained '
                        'documents passed the current D1 consumer and expert '
                        'judgement; original producer attribution is preserved')
            if not credit:
                # No producer process was rerun: rc remains zero. The row
                # records the consumer verdict that stopped this transition.
                plan[-1] = ("phase1", review, 0)
                halted_at = "phase1"
                advisories.append("phase1 checkpoint handoff refused: " + detail)

    if (_rtl_only_request and _p1_design_input
            and args.rtl_input != "original"):
        # A bounded RTL request consumes the original specification and intact
        # produced documents, not full-chip D1 qualification. Keep D1's actual
        # verdict; the selected Phase2 producer and its Program/AI gates decide
        # the requested RTL evidence. No stale or reportless producer is excused.
        try:
            if p1_mode == _P1_MODE_REFUSED or (run_phase1 and not _published_here(
                    project, 'phase1_one_shot.json', _phase_started['phase1'])):
                raise ValueError('Phase1 refused or published no current producer report')
            _rtl_provenance = _standalone_rtl_provenance(
                project, _p1_knobs, _rtl_source_before)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            halted_at = 'phase1'
            advisories.append('BOUNDED_RTL_PHASE1_PROVENANCE_REFUSED: ' + str(exc))
        else:
            halted_at = ''
            _fd_disclosures.append({
                'refresh': 'full D1 qualification', 'kind': 'outside_requested_evidence',
                'declared_by': ' '.join(_fd_window_flags),
                'provenance': _rtl_provenance,
                'why': 'Original source and source-bound produced Ldocs are intact; '
                       'the selected standalone RTL evidence follows Phase2. '
                       'Historical producer source drift remains disclosed. '
                       'The recorded D1 verdict is unchanged.'})
            advisories.append(
                'BOUNDED_RTL_PHASE1_PROVENANCE: original source and source-bound '
                'produced Ldocs retained; full D1 qualification is outside '
                'this standalone RTL request. Its actual verdict remains '
                'recorded; Phase2 Program/AI gates still apply.')

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
        _default_parameters = {"top": flow_top,
            "container": args.container, "pdk_name": args.pdk,
            "skip_analog": not run_analog}
        if _execution.request()['mode'] == 'default':
            _default_parameters['skip_hardware'] = bool(args.skip_hardware)
        _execution.bootstrap(project, parameters=_default_parameters)

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
    # Dispatches off the single run_analog decision
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
    # In Default, a selected A-track rejection stops later producers. Other
    # modes retain their existing non-blocking behavior.
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
        if execution_policy_value['mode'] == 'default':
            verdict, _analog_why = _row_verdict(
                project, 'analog_one_shot.json', rc, _phase_started['analog'], 'analog')
            if _analog_why:
                advisories.append(_analog_why)
            if verdict in ('FAIL', 'NOT_MEASURED'):
                halted_at = 'analog'
        _analog_row = ("analog", verdict, rc)
        reports["analog"] = rep
    else:
        _analog_row = ("analog", "SKIPPED", 0)

    # ---------------- Phase 2 ----------------
    _phase2_pad_top_deferred = None
    if not halted_at:
        if _sdc_early_entry:
            step8_acceptance = _complete_step8_early_preflight(project)
            status = step8_acceptance['verdict']
            rc = 0 if status == 'PASS' else 1 if status == 'FAIL' else 2
            out = _pl.report_path(project, 'vibe_ic_one_shot.json')
            out.parent.mkdir(parents=True, exist_ok=True)
            _write_runner_summary(out, {
                'program': 'vibe_ic_one_shot_runner', 'bounded': True,
                **_delivery_route.report_label(project), 'verdict': status,
                'halted_at': None if status == 'PASS' else 'phase2',
                'declared_window': {'entry_step': '8', 'exit_step': '8'},
                'phases': [{'name': n, 'verdict': v, 'rc': code} for n, v, code in plan],
                'step8_early_preflight': step8_acceptance,
                'whole_flow_verdict': 'NOT_MEASURED'}, project)
            lock.release()
            return rc
        if _sdc_postcheck_entry:
            step8_acceptance = _complete_step8_postcheck(project, flow_top)
            status = step8_acceptance['verdict']
            rc = 0 if status == 'PASS' else 1 if status == 'FAIL' else 2
            out = _pl.report_path(project, 'vibe_ic_one_shot.json')
            out.parent.mkdir(parents=True, exist_ok=True)
            _write_runner_summary(out, {
                'program': 'vibe_ic_one_shot_runner', 'bounded': True,
                **_delivery_route.report_label(project), 'verdict': status,
                'halted_at': None if status == 'PASS' else 'phase2',
                'declared_window': {'entry_step': '8', 'exit_step': '8'},
                'phases': [{'name': n, 'verdict': v, 'rc': code}
                           for n, v, code in plan],
                'step8_postcheck': step8_acceptance,
                'whole_flow_verdict': 'NOT_MEASURED'}, project)
            lock.release()
            return rc
        if _prelayout_entry:
            step10_acceptance = _complete_step10_prelayout(
                project, flow_top, args.pdk, args.container)
            reports['step10_prelayout'] = step10_acceptance
            prelayout_status = step10_acceptance['verdict']
            if prelayout_status == 'PASS':
                step8_acceptance = _complete_step8_postcheck(project, flow_top)
                if 'timing_modes_receipt' in step10_acceptance:
                    step8_acceptance = {
                        **step8_acceptance,
                        'timing_modes_receipt':
                            step10_acceptance['timing_modes_receipt'],
                    }
                reports['step8_postcheck'] = step8_acceptance
                prelayout_status = step8_acceptance['verdict']
            if _flow109_owner_entry:
                terminal = (reports.get('step8_postcheck')
                            or step10_acceptance)
                d26_acceptance = _finish_d26_selected_owner(
                    project, {**terminal, 'verdict': prelayout_status})
                reports['d26_finalization'] = d26_acceptance
                prelayout_status = d26_acceptance['verdict']
            if (prelayout_status != 'PASS'
                    or str(args.exit_step) == '10'):
                status = prelayout_status
                rc = 0 if status == 'PASS' else 1 if status == 'FAIL' else 2
                out = _pl.report_path(project, 'vibe_ic_one_shot.json')
                out.parent.mkdir(parents=True, exist_ok=True)
                _write_runner_summary(out, {
                    'program': 'vibe_ic_one_shot_runner', 'bounded': True,
                    **_delivery_route.report_label(project),
                    'verdict': status,
                    'halted_at': None if status == 'PASS' else 'phase2',
                    'declared_window': {'entry_step': '10',
                                        'exit_step': str(args.exit_step)},
                    'phases': [{'name': n, 'verdict': v, 'rc': code}
                               for n, v, code in plan],
                    'step10_prelayout': step10_acceptance,
                    'step8_postcheck': reports.get('step8_postcheck'),
                    'd26_finalization': reports.get('d26_finalization'),
                    'whole_flow_verdict': 'NOT_MEASURED'}, project)
                lock.release()
                return rc
        if _dft_entry:
            step11_acceptance = _complete_step11_dft(
                project, args.top_name, args.container)
            _finish_selected_native_owner(project, '11', step11_acceptance)
            status = step11_acceptance['verdict']
            rc = 0 if status == 'PASS' else 1 if status == 'FAIL' else 2
            out = _pl.report_path(project, 'vibe_ic_one_shot.json')
            out.parent.mkdir(parents=True, exist_ok=True)
            _write_runner_summary(out, {
                'program': 'vibe_ic_one_shot_runner', 'bounded': True,
                **_delivery_route.report_label(project), 'verdict': status,
                'halted_at': None if status == 'PASS' else 'phase2',
                'declared_window': {'entry_step': '11', 'exit_step': '11'},
                'phases': [{'name': n, 'verdict': v, 'rc': code}
                           for n, v, code in plan],
                'step11_dft': step11_acceptance,
                'whole_flow_verdict': 'NOT_MEASURED'}, project)
            lock.release()
            return rc
        if _post_dft_entry:
            step12_acceptance = _complete_step12_post_dft(project, args.container)
            _finish_selected_native_owner(project, '12', step12_acceptance)
            status = step12_acceptance['verdict']
            rc = 0 if status == 'PASS' else 1 if status == 'FAIL' else 2
            out = _pl.report_path(project, 'vibe_ic_one_shot.json')
            out.parent.mkdir(parents=True, exist_ok=True)
            _write_runner_summary(out, {
                'program': 'vibe_ic_one_shot_runner', 'bounded': True,
                **_delivery_route.report_label(project), 'verdict': status,
                'halted_at': None if status == 'PASS' else 'phase2',
                'declared_window': {'entry_step': '12', 'exit_step': '12'},
                'phases': [{'name': n, 'verdict': v, 'rc': code}
                           for n, v, code in plan],
                'step12_post_dft': step12_acceptance,
                'whole_flow_verdict': 'NOT_MEASURED'}, project)
            lock.release()
            return rc
        phase2_entry = ('11' if _prelayout_entry else
                        str(args.entry_step)
                        if _entry_runner == 'design_one_shot_runner' else None)
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
            pdk=args.pdk,
            max_rtl_repair_retries=args.max_rtl_repair_retries,
            lec_max_completed_rungs=args.lec_max_completed_rungs,
            skip_hardware=args.skip_hardware, skip_phase3=args.skip_phase3,
            skip_analog=False,
            entry_step=phase2_entry,
            exit_step=(str(args.exit_step) if args.exit_step else None),
            area_receipt=args.area_receipt,
            area_run_manifest=args.area_run_manifest,
            phase3_rederive_ic_name=(
                args.ic_name
                if _phase3_rederives_top(flow_top, top_name_explicit)
                else None))
        if args.rtl_input == "original":
            p2_args += ["--rtl-input", "original"]
        if args.skip_analog:
            p2_args.append("--skip-analog")
        elif not run_analog:
            p2_args.append("--skip-analog")
        p2_admission = _canonical_admission.admit_span(
            project, "phase2", PROGRAMS_DIR, args.container,
            {"top_name": flow_top, "max_rtl_repair_retries": args.max_rtl_repair_retries,
             "rtl_input": args.rtl_input,
             "skip_hardware": args.skip_hardware, "skip_phase3": args.skip_phase3,
             "skip_analog": "--skip-analog" in p2_args,
             "entry_step": (phase2_entry if _prelayout_entry else args.entry_step),
             "exit_step": args.exit_step,
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
            d09_selected = _flow109_selected_row('D09')
            d09_invocation: Dict[str, Any] = {}
            _phase_started["phase2"] = time.time()
            rc = _run_phase(
                "PHASE 2 (= 2a + 2b)", runner, p2_args, env=p2_env,
                invocation=d09_invocation if d09_selected else None)
            verdict, _fresh_why = _row_verdict(
                project, "phase2_one_shot.json", rc,
                _phase_started.get("phase2", t0), "phase2")
            if _fresh_why:
                advisories.append(_fresh_why)
            rep = _read_report(_phase_report_path(project, "phase2_one_shot.json"))
            if d09_selected:
                d09_acceptance = _finish_d09_selected_owner(
                    project, rep, d09_invocation,
                    published_current=_pl.published_here(
                        _phase_report_path(project, "phase2_one_shot.json"),
                        _phase_started["phase2"]))
                reports['d09_finalization'] = d09_acceptance
                verdict = d09_acceptance['verdict']
                rc = 0 if verdict == 'PASS' else 1 if verdict == 'FAIL' else 2
            elif _flow109_selected_row('D10') and _d10_metrics_unimplemented():
                d10_acceptance = _finish_d10_unimplemented_owner(
                    project, run_p0=(verdict == 'PASS' and _pl.published_here(
                        _phase_report_path(project, 'phase2_one_shot.json'),
                        _phase_started['phase2'])))
                reports['d10_finalization'] = d10_acceptance
                if verdict != 'FAIL':
                    verdict, rc = 'NOT_MEASURED', 2
            plan.append(("phase2", verdict, rc))
            reports["phase2"] = rep
            if (verdict == 'NOT_MEASURED' and _execution.request()['mode'] == 'default'
                    and rc in (0, 1) and not args.skip_phase3 and not _p3_skip_by_exit):
                _phase2_pad_top_deferred = _phase2_pad_top_deferral(
                    project, rep, _phase_started['phase2'])
                if _phase2_pad_top_deferred:
                    _phase2_pad_top_deferred['phase2_process'] = {'verdict': verdict, 'rc': rc}
            if (verdict == 'FAIL' or (verdict == 'NOT_MEASURED'
                    and _execution.request()['mode'] == 'default' and not _phase2_pad_top_deferred)):
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
    if halted_at not in ('phase1', 'analog') and not _p3_skip_by_exit:
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
    step14_acceptance = None
    if not halted_at and not args.skip_phase3 and not _p3_skip_by_exit:
        if _p3_forward_window and execution_policy_value['mode'] == 'default':
            # A bounded Phase2 omits the whole-flow producer sweep. Complete
            # its existing synthesis handoff before entering the physical
            # owner; its phase summary alone cannot authorize Step15.
            step7_acceptance = _complete_step7_sdc(
                project, phase3_top, args.pdk, args.container)
            if step7_acceptance['verdict'] != 'PASS':
                status = step7_acceptance['verdict']
                out = _pl.report_path(project, 'vibe_ic_one_shot.json')
                out.parent.mkdir(parents=True, exist_ok=True)
                _write_runner_summary(out, {
                    'program': 'vibe_ic_one_shot_runner', 'bounded': True,
                    **_delivery_route.report_label(project),
                    'verdict': status, 'halted_at': 'phase2',
                    'phases': [{'name': n, 'verdict': v, 'rc': code}
                               for n, v, code in plan],
                    'step7_sdc_refresh': step7_acceptance,
                    'whole_flow_verdict': 'NOT_MEASURED'}, project)
                lock.release()
                return 1 if status == 'FAIL' else 2
            step14_acceptance = _complete_step14_handoff(project)
            if step14_acceptance['verdict'] != 'PASS':
                status = step14_acceptance['verdict']
                rc = 1 if status == 'FAIL' else 2
                out = _pl.report_path(project, 'vibe_ic_one_shot.json')
                out.parent.mkdir(parents=True, exist_ok=True)
                _write_runner_summary(out, {
                    'program': 'vibe_ic_one_shot_runner', 'bounded': True,
                    **_delivery_route.report_label(project),
                    'verdict': status, 'halted_at': 'phase2',
                    'phases': [{'name': n, 'verdict': v, 'rc': code}
                               for n, v, code in plan],
                    'step14_handoff': step14_acceptance,
                    'whole_flow_verdict': 'NOT_MEASURED'}, project)
                lock.release()
                return rc
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
            # Phase2 already owns synthesis. Default continues through the
            # existing native backend window at its declared physical head.
            entry = (_physical_order[0] if execution_policy_value['mode'] == 'default'
                     else '9')
            p3_args += ["--entry-step", entry, "--exit-step", str(args.exit_step)]
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
            phase3_report = (_phase3_window_report_path(project, window_run_id)
                             if _p3_forward_window else
                             _phase_report_path(project, "phase3_one_shot.json"))
            verdict, _fresh_why = _row_verdict(
                project, "phase3_one_shot.json", rc,
                _phase_started.get("phase3", t0), "phase3",
                **({"report_path": phase3_report,
                    "expected_window_run_id": window_run_id}
                   if _p3_forward_window else {}))
            if _fresh_why:
                advisories.append(_fresh_why)
            rep = _read_report(phase3_report)
            if not isinstance(rep, dict):
                rep = {}
            plan.append(("phase3", verdict, rc))
            reports["phase3"] = rep
            _p3_window_ran = bool(_p3_forward_window and rep.get("bounded")
                                  and rep.get("window_run_id") == window_run_id
                                  and _pl.published_here(
                                      phase3_report, _phase_started["phase3"]))
            if verdict == "FAIL":
                halted_at = "phase3"
    else:
        plan.append(("phase3", "SKIPPED", 0))

    if _phase2_pad_top_deferred and _phase3_ran:
        status, consumer_rc = _resolve_phase2_pad_top(
            project, _phase2_pad_top_deferred, _phase_started['phase3'])
        _phase2_pad_top_deferred['terminal_verdict'] = status
        _phase2_pad_top_deferred['terminal_rc'] = consumer_rc
        # The child process's early NOT_MEASURED/rc remains in the original
        # phase report. This row is its acceptance after the named late gate.
        plan = [(name, status, consumer_rc) if name == 'phase2' else (name, word, code)
                for name, word, code in plan]
        if status == 'FAIL':
            halted_at = 'phase2'

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

    if _p3_skip_by_exit and "phase2" in reports:
        # A front-end checkpoint operation ends at the requested cut too.
        # Its child already checked the dispatched steps and their AI reviews.
        # Do not ask a later whole-flow audit to decide this operation's rc.
        p2_window = reports["phase2"]
        fresh_window = bool(
            p2_window.get("declared_window")
            and _pl.published_here(
                _phase_report_path(project, "phase2_one_shot.json"),
                _phase_started["phase2"]))
        window_rows = [(n, v, rc) for n, v, rc in plan if v != "SKIPPED"]
        window_verdict, window_reasons = _roll_up(
            window_rows, audit_axis={"state": "NOT_APPLICABLE",
                                    "reason": "bounded operation; whole-flow audit not refreshed"})
        if not fresh_window and window_verdict != "FAIL":
            window_verdict = "NOT_MEASURED"
            window_reasons.append("Phase-2 child did not publish a fresh window report")
        summary = {
            "program": "vibe_ic_one_shot_runner", "bounded": True,
            "phase": "vibe-ic", "project": str(project),
            **_delivery_route.report_label(project),
            "declared_window": p2_window.get("declared_window", {}),
            "phases": [{"name": n, "verdict": v, "rc": rc} for n, v, rc in
                       [*plan, ("mixed_signal", "SKIPPED", 0)]],
            "dispatched_verdict": window_verdict,
            "verdict": "FAIL" if window_verdict == "FAIL" else "NOT_MEASURED",
            "verdict_reasons": window_reasons,
            "whole_flow_verdict": "NOT_MEASURED", "audit_verdict": "NOT_MEASURED",
            "halted_at": halted_at or None,
            "advisories": advisories,
            "phase1_checkpoint_review": _phase1_checkpoint_review,
            "d09_finalization": reports.get("d09_finalization"),
            "d10_finalization": reports.get("d10_finalization"),
            "audit_scope": "bounded; whole-flow audit not refreshed",
            "completion_audit_axis": {"state": "NOT_MEASURED",
                                      "reason": "bounded; whole-flow audit not refreshed"},
            "ai_judgements": p2_window.get("ai_judgements", {}),
            "bounded_disclosures": [*_fd_disclosures,
                                    *p2_window.get("bounded_disclosures", [])],
            "not_refreshed_here": p2_window.get("not_refreshed_here", []),
        }
        out = _pl.report_path(project, "vibe_ic_one_shot.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        if _flow109_selected_row('D25'):
            d25 = _finish_d25_selected_owner(project)
            summary['d25_finalization'] = d25
            if window_verdict != 'FAIL':
                window_verdict = d25['verdict']
            summary['verdict'] = summary['dispatched_verdict'] = window_verdict
        _write_runner_summary(out, summary, project)
        lock.release()
        return (0 if window_verdict in ("PASS", "PASS_WITH_WAIVERS") else
                2 if window_verdict == 'NOT_MEASURED' and 'd25_finalization' in summary else 1)

    if _p3_window_ran:
        # A physical window ends here.  Mixed-signal merge, PDK finalisation
        # and the front-door whole-flow tail consume outputs beyond the cut.
        # They cannot run and still claim the same narrow window.
        p3_window = reports["phase3"]
        stale = p3_window.get("stale_downstream") or {}
        # The phase row already includes current canonical consumer acceptance.
        # A raw child account cannot replace its measured FAIL or nonmeasurement.
        window_verdict = next(v for n, v, _ in reversed(plan) if n == "phase3")
        summary = {
            "program": "vibe_ic_one_shot_runner", "bounded": True,
            **_delivery_route.report_label(project),
            "declared_window": {"entry_step": args.entry_step,
                                "exit_step": args.exit_step,
                                "entry_runner": _entry_runner},
            "phases": [{"name": n, "verdict": v, "rc": rc}
                       for n, v, rc in plan],
            "dispatched_verdict": window_verdict,
            "verdict": ("FAIL" if window_verdict == "FAIL" else "NOT_MEASURED"),
            "whole_flow_verdict": "NOT_MEASURED",
            "audit_verdict": "NOT_MEASURED",
            "audit_scope": "bounded; whole-flow audit not refreshed",
            "stale_downstream": stale,
            "bounded_disclosures": p3_window.get("bounded_disclosures", []),
            "not_refreshed_here": ["reports/final_summary.md"],
        }
        if step14_acceptance is not None:
            summary['step14_handoff'] = step14_acceptance
        if 'step10_prelayout' in reports:
            summary['step10_prelayout'] = reports['step10_prelayout']
        out = _pl.report_path(project, "vibe_ic_one_shot.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        _write_runner_summary(out, summary, project)
        lock.release()
        phase3_rc = next(rc for name, _, rc in reversed(plan) if name == "phase3")
        return phase3_rc or (0 if window_verdict in _PHASE_PASS | _PHASE_PASS_WITH_NOTE else 1)

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
                    and halted_at not in ("phase1", "phase2", "analog"))
    if _ms_dispatch:
        _mixed_started = time.time()
        _mixed_pass = ('PASS', 'PASS_WITH_WAIVERS') if execution_policy_value['mode'] == 'default' else ('PASS',)
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
        verdict = _default_track_verdict(project, _mixed_started, 'M1', verdict)
        plan.append(("mixed_signal", verdict, rc))
        reports["mixed_signal"] = rep
        # Default M2 follows the fixed M1 producer. One native Yosys arm
        # reads the routed design; the canonical M2 gate independently checks
        # its bound outputs. A failed M1 cannot dispatch a downstream producer.
        if rc == 0 and verdict in _mixed_pass:
            _m2_json = project / "reports/analog/mixed_signal/power_domain_producer_audit.json"
            if _execution.request()["mode"] != "default":
                _m2_json.unlink(missing_ok=True)
            _m2_dispatched = _controller_mixed_step(_execution, project, "M2", _m2_json)
            if _m2_dispatched is None:
                _m2_rc = _run_phase(
                "MIXED-SIGNAL M2 (placed power-domain protection paths)",
                PROGRAMS_DIR / "mixed_signal_power_domain_run.py",
                [str(project), "--top", phase3_top,
                 "--container", args.container, "--json", str(_m2_json)],
                env=_phase_env)
                # Keep the producer's process status visible before the
                # controller fallback rebind below. This is both the actual
                # fail-closed receipt and the status edge the wiring audit
                # must follow.
                _m2_rep = _read_report(_m2_json)
                if _m2_rc != 0:
                    _m2_rep = dict(_m2_rep)
                _m2_rep["producer_rc"] = _m2_rc
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
            _m2_verdict = _default_track_verdict(project, _mixed_started, 'M2', _m2_verdict)
        else:
            _m2_rc, _m2_verdict = 2, ('NOT_MEASURED' if execution_policy_value['mode'] == 'default' else 'NOT_READY')
            _m2_rep = {"verdict": _m2_verdict, "reason": "M1 did not pass; M2 not dispatched"}
        plan.append(("mixed_signal_M2", _m2_verdict, _m2_rc))
        reports["mixed_signal_M2"] = _m2_rep
        # Fixed M3/M4 dependency sequence. These rows remain independent of
        # digital completion, but an unmeasured mixed step cannot dispatch its
        # successor or borrow a passing verdict from missing audit bytes.
        if _m2_rc == 0 and _m2_verdict in _mixed_pass:
            _m3_json = project / "reports/analog/mixed_signal/m3_producer_audit.json"
            if _execution.request()["mode"] != "default":
                _m3_json.unlink(missing_ok=True)
            _m3_dispatched = _controller_mixed_step(_execution, project, "M3", _m3_json)
            if _m3_dispatched is None:
                _m3_rc = _run_phase(
                "MIXED-SIGNAL M3 (current simulation / interface SI evidence)",
                PROGRAMS_DIR / "mixed_signal_m3_run.py",
                [str(project), "--top", phase3_top, "--container", args.container,
                 "--json", str(_m3_json)], env=_phase_env)
                _m3_rep = _read_report(_m3_json)
                if _m3_rc != 0:
                    _m3_rep = dict(_m3_rep)
                _m3_rep["producer_rc"] = _m3_rc
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
            _m3_verdict = _default_track_verdict(project, _mixed_started, 'M3', _m3_verdict)
        else:
            _m3_rc, _m3_verdict = 2, ('NOT_MEASURED' if execution_policy_value['mode'] == 'default' else 'NOT_READY')
            _m3_rep = {"verdict": "NOT_READY", "reason": "M2 did not pass; M3 not dispatched"}
        plan.append(("mixed_signal_M3", _m3_verdict, _m3_rc))
        reports["mixed_signal_M3"] = _m3_rep
        if _m3_rc == 0 and _m3_verdict in _mixed_pass:
            _m4_json = project / "reports/analog/mixed_signal/signoff_producer_audit.json"
            if _execution.request()["mode"] != "default":
                _m4_json.unlink(missing_ok=True)
            _m4_dispatched = _controller_mixed_step(_execution, project, "M4", _m4_json)
            if _m4_dispatched is None:
                _m4_rc = _run_phase(
                "MIXED-SIGNAL M4 (derived mixed-signal / top-level PV verdict)",
                PROGRAMS_DIR / "mixed_signal_signoff_run.py",
                [str(project), "--top", phase3_top, "--json", str(_m4_json)], env=_phase_env)
                _m4_rep = _read_report(_m4_json)
                if _m4_rc != 0:
                    _m4_rep = dict(_m4_rep)
                _m4_rep["producer_rc"] = _m4_rc
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
            _m4_verdict = _default_track_verdict(project, _mixed_started, 'M4', _m4_verdict)
        else:
            _m4_rc, _m4_verdict = 2, ('NOT_MEASURED' if execution_policy_value['mode'] == 'default' else 'NOT_READY')
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
    digital_rows = _rollup_phase_rows(plan, execution_policy_value['mode'])
    _ca_verdicts = _completion_audit_verdicts(project)
    _audit_axis = _completion_audit_axis(
        project, phase3_ran=_phase3_ran,
        # PHASE 3's start, not the run's: the audit is phase3's to refresh, and a
        # document written before phase3 began cannot be its refresh.
        started_at=_phase_started.get("phase3", t0))
    if digital_rows:
        overall, _rollup_why = _roll_up(digital_rows, _ca_verdicts,
                                        demoted=_demoted,
                                        audit_axis=_audit_axis,
                                        halted_at=halted_at)
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
        "execution_mode": execution_policy_value['mode'],
        "project": str(project),
        **_delivery_route.report_label(project),
        "duration_s": time.time() - t0,
        "halted_at": halted_at or None,
        "phase2_deferred_obligation": _phase2_pad_top_deferred,
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
        "phase1_checkpoint_review": _phase1_checkpoint_review,
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
        entry.add_argument('--route-authority-only', action='store_true')
        entry.add_argument('--receipt-channel-fd', type=int)
        selected, _ = entry.parse_known_args()
        # Default is one local driver calling the existing phase runners in
        # order. It needs no candidate issuer, capability socket, isolated
        # interpreter, or source snapshot before the first producer can run.
        if selected.execution_mode == 'default' and not selected.route_authority_only:
            sys.exit(main())
        if not selected.project.is_dir():
            print(f'ERROR: not a directory: {selected.project.resolve()}', file=sys.stderr)
            sys.exit(2)
        route_refusal = _delivery_route.admit(selected.project.resolve(), selected.route)
        if route_refusal:
            print(_delivery_route.refusal_message(route_refusal), file=sys.stderr)
            sys.exit(2)
        route = selected.route or _delivery_route.report_label(selected.project)['delivery_route'].lower()
        if selected.execution_mode == 'ultra':
            # Codex and direct CLI installs do not necessarily execute Claude's
            # SessionStart hook. Finish normal Ultra installation here once;
            # the isolated issuer and all later consumers remain offline.
            from execution_source_identity import prepare_installed
            try:
                prepare_installed()
            except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                print('REFUSED: CANONICAL_ISSUANCE_INVALID: ' + str(exc), file=sys.stderr)
                sys.exit(2)
        command = [str(Path(sys.executable).resolve()), '-I', '-S',
                   str(PROGRAMS_DIR / 'execution_authority.py'), '--project', str(selected.project.resolve()),
                   '--route', route, '--execution-mode', selected.execution_mode]
        if selected.receipt_channel_fd is not None:
            command += ['--channel-fd', str(selected.receipt_channel_fd)]
        os.execv(command[0], command + ['--', *sys.argv[1:]])
    sys.exit(main())
