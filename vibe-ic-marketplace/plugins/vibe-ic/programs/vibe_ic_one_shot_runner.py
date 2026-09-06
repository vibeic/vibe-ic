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

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import _path_layout as _pl
import _runner_lock
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated


PROGRAMS_DIR = Path(__file__).resolve().parent


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
    # override a deliberate cross-image experiment). The content-addressed id is
    # preferred over the tag because it is exactly what the container is running
    # and cannot drift; the tag is the fallback when no id was resolved.
    _img = rec.get("image_id") or rec.get("image_ref")
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
            resolved, f"container:{container}", "run tool logs",
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


def _phase1_decision(project: Path, force_skip: bool) -> Tuple[bool, str]:
    """Decide whether to run Phase 1 and in which mode.

    Returns (run, mode) where:
      run  -> True if phase1 must run before phase2
      mode -> "prompt" (Path A NL inputs), "docs" (Path B vendor docs),
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
    p1_struct = project / "input" / "phase1_structured.yaml"
    p1_prompt = project / "input" / "phase1_prompt.md"
    docs = project / "input" / "docs"
    # phase1/input_doc/ is the canonical Path-B raw-corpus location.
    input_doc = (_pl.input_doc_dir(project)
                 if hasattr(_pl, "input_doc_dir") else None)
    gd = _pl.generated_docs_dir(project)
    L_count = len(list(gd.glob("L*.json"))) if gd.is_dir() else 0
    # Already has the full L-doc set → nothing to do.
    if L_count >= 13:
        return (False, "")
    def _has_extractable(d: Path) -> bool:
        # #583 — "populated" means at least one real, non-empty,
        # non-hidden document (a .gitkeep placeholder must not flip a
        # prompt-only project into docs mode).
        if not d.is_dir():
            return False
        for f in d.rglob("*"):
            if f.is_file() and not f.name.startswith(".") \
                    and f.stat().st_size > 0:
                return True
        return False

    docs_populated = _has_extractable(docs)
    input_doc_populated = bool(input_doc) and _has_extractable(input_doc)
    # UNIFIED DOC->JSON backend (owner directive 2026-06-20): EVERY front-end —
    # vendor docs, a free-text prompt, OR a dialogue convergence fact-graph —
    # flows through the one doc-extraction track so the L1-L24 JSON is
    # homogeneous. So the orchestrator now resolves ALL of them to "docs";
    # phase1_one_shot_runner --mode docs render-bridges a phase1_structured.yaml
    # (dialogue) / phase1_prompt.md (prose) into input/docs/ and re-detects the
    # precise mode. The legacy engine reverse-extractor stays reachable only via
    # an explicit `phase1_one_shot_runner --mode prompt` invocation.
    if (p1_struct.is_file() or docs_populated or input_doc_populated
            or p1_prompt.is_file()):
        return (True, "docs")
    # No inputs at all — phase1 will SKIP gracefully (don't run).
    return (False, "")


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
    cp = subprocess.run([sys.executable, str(runner), *args], env=env)
    return cp.returncode


def _read_report(p: Path) -> Dict[str, Any]:
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"verdict": "FAIL", "error": f"parse failed: {p}"}


def _aggregate(verdicts: List[str]) -> str:
    if any(v == "FAIL" for v in verdicts):
        return "FAIL"
    # v0.3.7 — ORGANIC #505: COVERAGE-INCOMPLETE is a non-gating advisory
    # tier (a demoted coverage-only phase1 failure in the standalone-design
    # shape). It does NOT fail the run but DOES surface as PASS_WITH_WAIVERS
    # so the overall verdict never hides the documented doc-extraction gap.
    if any(v in ("PASS_WITH_WAIVERS", "WAIVED", "COVERAGE-INCOMPLETE")
           for v in verdicts):
        return "PASS_WITH_WAIVERS"
    return "PASS"


def _phase1_failure_is_coverage_only(project: Path) -> Tuple[bool, dict]:
    """v0.3.7 — ORGANIC #505. Read the phase1 exit-reason sidecar
    (``reports/phase1/phase1_exit_reason.json``, written by
    phase1_doc_one_shot_runner) and report whether phase1's FAIL is
    attributable SOLELY to doc-extraction coverage (orthogonal to the RTL
    deliverable). Returns ``(coverage_only, reason_dict)``; ``(False, {})``
    when the sidecar is absent/unreadable (e.g. prompt-mode phase1 that
    never wrote one) so the default halting behaviour is preserved."""
    f = project / "reports" / "phase1" / "phase1_exit_reason.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, {}
    return bool(d.get("coverage_only_failure")), d


_TOP_NAME_DEFAULT = "chip_top"
_MODULE_DECL_RE = re.compile(r"(?m)^\s*module\s+([A-Za-z_]\w*)")
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
    decls: set = set()
    text_parts: List[str] = []
    if not rtl_dir.is_dir():
        return decls, set()
    for pat in ("*.v", "*.sv"):
        for f in sorted(rtl_dir.glob(pat)):
            try:
                t = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            text_parts.append(t)
            decls.update(_MODULE_DECL_RE.findall(t))
    corpus = "\n".join(text_parts)
    insts: set = set()
    for d in decls:
        inst_re = re.compile(
            r"(?<![\w.])" + re.escape(d) + r"\s+(?:#\s*\([\s\S]*?\)\s*)?[A-Za-z_]\w*\s*\(")
        if inst_re.search(corpus):
            insts.add(d)
    return decls, insts


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
        return f"{override_note}; {msg}" if override_note else msg

    if _TOP_NAME_DEFAULT in decls:
        # a genuine wrapper exists → honor it
        return _TOP_NAME_DEFAULT, (_note(f"top='{_TOP_NAME_DEFAULT}'")
                                   if override_note else "")
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
#: other runner is refused by `--entry-step` (see the guard in main()), so this
#: tuple is the single source of truth for BOTH the refusal and the help text —
#: they drifted apart once (the help advertised Phase-3 15/31/37 and analog
#: A1..A9 as routable while the guard refused every one of them), and a reader
#: has no way to tell which half is lying.
ENTRY_STEP_ENTERABLE_RUNNERS = ("phase1_one_shot_runner",
                                "design_one_shot_runner")


def main() -> int:
    _line_buffer_own_stream()
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    p.add_argument("--top-name", default=_TOP_NAME_DEFAULT)
    p.add_argument("--container", default=_pin.default_container_name())
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
    p.add_argument("--skip-hardware", action="store_true")
    p.add_argument("--entry-step", default=None,
                   help="START the flow at this canonical step id. The step "
                        "decides WHICH runner owns the entry, and THIS "
                        "orchestrator can be entered at the Phase 1 and Phase "
                        "2 spans only — D1 for Phase 1, 2/4/1/9/11 for Phase "
                        "2. Phase-3 (15/31/37) and analog (A1..A9) steps are "
                        "owned by phase3_one_shot_runner / "
                        "analog_one_shot_runner and are REFUSED here: run "
                        "that runner directly. Only a step that HEADS a "
                        "dispatch span is enterable; a mid-span step is "
                        "refused rather than approximated.")
    p.add_argument("--exit-step", default=None,
                   help="STOP the Phase-2 dispatch after this canonical step "
                        "id: forwarded verbatim to the phase2 runner, whose "
                        "dispatch sites wholly past it are recorded as "
                        "SKIPPED-BY-EXIT instead of run (the site holding "
                        "the exit still runs in full). Omitted: behaviour is "
                        "unchanged. Pair with --skip-phase3 when the exit "
                        "precedes physical design.")
    p.add_argument("--skip-phase1", action="store_true")
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
    args = p.parse_args()

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
            # Phase-3 and analog entries are NOT wired here yet. Say so rather
            # than routing to the nearest phase and reporting as if it were what
            # was asked.
            print(f"REFUSED: step {args.entry_step!r} is owned by "
                  f"{_entry_runner}, which this orchestrator cannot yet be "
                  f"entered at. Run that runner directly, or enter at a Phase "
                  f"1/2 step.", file=sys.stderr)
            return 2
        print(f"[entry] step {args.entry_step} -> {_entry_runner}")

    # An entry owned by Phase 2 means Phase 1 is not this run's work: its
    # artefacts were supplied, not produced here. Force the skip through the
    # EXISTING decision function rather than adding a parallel switch, so there
    # stays exactly one place that decides whether Phase 1 runs.
    _force_skip_p1 = args.skip_phase1 or (
        _entry_runner == "design_one_shot_runner")
    run_phase1, p1_mode = _phase1_decision(project, _force_skip_p1)
    if run_phase1:
        runner = _phase_runner("phase1")
        p1_args = [str(project), "--ic-name", args.ic_name]
        # Path B (vendor docs, no L docs yet): force docs mode so the
        # doc-extraction track runs and produces L*.json for phase2.
        if p1_mode == "docs":
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
        label = ("PHASE 1 (vendor docs → L1-L23)" if p1_mode == "docs"
                 else "PHASE 1 (NL → L1-L23)")
        rc = _run_phase(label, runner, p1_args, env=_phase_env)
        rep = _read_report(_pl.report_path(project, "phase1_one_shot.json"))
        verdict = rep.get("verdict") or ("PASS" if rc == 0 else "FAIL")
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
            if args.skip_phase3 and cov_only:
                plan[-1] = ("phase1", "COVERAGE-INCOMPLETE", rc)
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
    else:
        plan.append(("phase1", "SKIPPED", 0))

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

    # ---------------- Phase 2 ----------------
    if not halted_at:
        runner = _phase_runner("phase2")
        p2_args = [str(project),
                   "--top-name", flow_top,
                   "--container", args.container,
                   "--max-rtl-repair-retries", str(args.max_rtl_repair_retries)]
        if args.skip_hardware:
            p2_args.append("--skip-hardware")
        # Forward --skip-phase3 so phase2's DFT/LEC chain (steps 11-13) gates the
        # heavy Fault ATPG OFF on a lightweight/RTL-only run (no silicon target),
        # while still running the fast LEC. On a full-chip flow (no --skip-phase3)
        # the full DFT insertion + ATPG runs.
        if args.skip_phase3:
            p2_args.append("--skip-phase3")
        # v0.1.54 capture: forward --skip-analog so phase2 final_audit doesn't
        # FAIL a digital-only project on missing phase1/analog/analog_block_list.json.
        # (1) User explicitly asked to skip the analog track.
        if args.skip_analog:
            p2_args.append("--skip-analog")
        # (2) #459: the orchestrator's OWN analog decision is authoritative. If
        # we are NOT running the A-track because _need_analog()==False (even
        # without a user --skip-analog), phase2's final_audit must agree — so
        # inject --skip-analog here too. For analog / mixed-signal projects
        # (run_analog==True) the flag is NEVER injected, so the A-track and its
        # final_audit condition stay active (corpus-sweep guard). The membership
        # guard makes (1)+(2) idempotent (no duplicate append).
        elif not run_analog:
            p2_args.append("--skip-analog")
        if _entry_runner == "design_one_shot_runner":
            p2_args += ["--entry-step", str(args.entry_step)]
        # Forward --exit-step the same way --entry-step travels: the phase2
        # runner owns the site table, so the mapping (and the refusal for an
        # unmappable value) happens there, not here.
        if args.exit_step:
            p2_args += ["--exit-step", str(args.exit_step)]
        rc = _run_phase("PHASE 2 (= 2a + 2b)", runner, p2_args, env=_phase_env)
        rep = _read_report(_pl.report_path(project, "phase2_one_shot.json"))
        verdict = rep.get("verdict") or ("PASS" if rc == 0 else "FAIL")
        plan.append(("phase2", verdict, rc))
        reports["phase2"] = rep
        if verdict == "FAIL":
            halted_at = "phase2"
    else:
        plan.append(("phase2", "SKIPPED", 0))

    # ---------------- Analog A1..A8 ----------------
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
    _analog_dispatch = run_analog and halted_at in ("", "phase2")
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
        rc = _run_phase("ANALOG A1..A8", runner, _analog_args, env=_phase_env)
        rep = _read_report(_pl.report_path(project, "analog_one_shot.json"))
        verdict = rep.get("verdict") or ("PASS" if rc == 0 else "FAIL")
        plan.append(("analog", verdict, rc))
        reports["analog"] = rep
        # Analog FAIL is logged but does NOT halt the digital flow —
        # downstream Phase 3 still proceeds (analog hardmacros land
        # via Step 14 floorplan in a future iteration).
    else:
        plan.append(("analog", "SKIPPED", 0))

    # ORGANIC #2064 — RE-EVALUATE THE ANALOG ACCEPTANCE, NOW THAT A4 HAS RUN.
    #
    # `design_one_shot_runner` emits and runs the acceptance checks beside the
    # L10 unit-TB pair, which is where Step 4 reads their JUnit — and that is
    # BEFORE this A-track, so on a COLD project every clause is honestly
    # NOT_MEASURED ("flow step A4 has not produced a corner record"). The
    # checks are pure record reads with no simulator, so re-running them here,
    # after A4 has written its records, is cheap and idempotent, and the
    # refreshed JUnit is what the whole-flow audit below and at the end of the
    # run actually reads. Non-blocking and byte-for-byte a no-op for a design
    # with no analog verification plan.
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
    if halted_at != "phase1":
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
    if not halted_at and not args.skip_phase3:
        runner = _phase_runner("phase3")
        # Reuse the flow-level resolved top. If phase 2 GENERATED the RTL (the
        # from-docs path, where no RTL existed at the flow-resolution point
        # above), re-resolve now that phase-2 output exists so phase-3 still
        # gets the real top rather than the default 'chip_top'.
        phase3_top = flow_top
        if phase3_top == _TOP_NAME_DEFAULT and not top_name_explicit:
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
        if getattr(args, "allow_oss_pdk_fallback", False):
            p3_args.append("--allow-oss-pdk-fallback")
        if getattr(args, "allow_pdk_target_mismatch", False):
            p3_args.append("--allow-pdk-target-mismatch")
        rc = _run_phase("PHASE 3 (synth → PnR → GDS → DRC → LVS)",
                         runner, p3_args, env=_phase_env)
        rep = _read_report(_pl.report_path(project, "phase3_one_shot.json"))
        verdict = rep.get("verdict") or ("PASS" if rc == 0 else "FAIL")
        plan.append(("phase3", verdict, rc))
        reports["phase3"] = rep
        if verdict == "FAIL":
            halted_at = "phase3"
    else:
        plan.append(("phase3", "SKIPPED", 0))

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
    _ms_dispatch = (run_analog and not args.skip_phase3
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
        rc = _run_phase(
            "MIXED-SIGNAL M1 (A+D GDS merge → Magic extract → netgen LVS)",
            PROGRAMS_DIR / "mixed_signal_top_lvs_run.py",
            [str(project), "--top", phase3_top,
             "--container", args.container, "--pdk", str(_ms_pdk),
             "--json", str(_ms_json)],
            env=_phase_env)
        rep = _read_report(_ms_json)
        # rc 2 is the producer's documented disclosed skip (inputs / tools /
        # PDK tech absent) — record it as SKIP, never as a pass.
        verdict = rep.get("verdict") or {0: "PASS", 2: "SKIP"}.get(rc, "FAIL")
        plan.append(("mixed_signal", verdict, rc))
        reports["mixed_signal"] = rep
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

    # ---------------- Aggregate ----------------
    digital_verdicts = [v for n, v, _ in plan
                        if n not in ("analog", "mixed_signal")
                        and v != "SKIPPED"]
    overall = _aggregate(digital_verdicts) if digital_verdicts else "FAIL"
    summary = {
        "phase": "vibe-ic",
        "project": str(project),
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
    }
    # v1.6.32: emit canonical final_summary.md (best-effort). Note that
    # phase23_one_shot_runner ALSO calls this; vibe_ic delegates to
    # phase23 today, so the final summary will be regenerated here on
    # the chained-end. Idempotent — generator overwrites.
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
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    print(f"\n{'='*72}")
    print(f"=== vibe_ic_one_shot_runner DONE — {out}")
    print(f"  overall verdict   : {overall}")
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
    sys.exit(main())
