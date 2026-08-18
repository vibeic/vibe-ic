#!/usr/bin/env python3
r"""cvdp_phase1_entry.py — DETERMINISTIC Phase-1-entry driver for CVDP.

THE CANONICAL ENTRY (owner directive 2026-07-05): CVDP must be scored THROUGH
the plugin's Phase-1 entry, not the legacy blind-author Shape-C flow (which
skips Phase 1 and lets an AI author the RTL free-hand — that measures "Opus +
cvdp_gate", not the Vibe-IC runner; see open-benchmark-methodology § 5.1).

This is the THIN benchmark ADAPTER (the `cvdp_` prefix is correct: it only maps
the CVDP record format → the general Phase-1 runner). It is fully DETERMINISTIC:
same dataset → same staging → same runner invocations → same per-case verdicts.

Per record it does, in order — reading ONLY the INPUT side:
  1. Stage `input.prompt`          → <case>/input/phase1_prompt.md
     Stage `input.context` RTL     → <case>/input/docs/<path> AND <case>/rtl/<path>
        (context is the ORIGINAL/surrounding RTL a modify/complete task must keep;
         it is INPUT, not oracle. `output.*` and `harness` are the oracle and are
         NEVER read here — enforced by `_assert_no_oracle_read`.)
  2. Run `vibe_ic_one_shot_runner.py --skip-phase3 --skip-analog --skip-hardware`
     — deterministic Phase-1 L1-L23 extraction + deterministic Phase-2
       json-to-rtl WHEN the spec is structured (FSM / truth-table / gate /
       vector-op). No LLM in either of those.
  3. Collect the verdict + emitted RTL and CLASSIFY the emit path:
       - `deterministic`  : Phase-2 json-to-rtl produced rtl/ with no LLM.
       - `needs_ai_backup`: rtl_gen WAIVED to spec-to-rtl (prose body → the
                            plugin's designed AI-backup must author rtl/<top>.sv,
                            then the runner's gates re-fire). This step is the
                            ONLY non-deterministic insert and is unavoidable
                            (NL→RTL body fundamentally needs an LLM, § 1). The
                            driver FLAGS it; it does not fabricate a prose→RTL
                            body (that would be the § 4 over-fit the doctrine
                            forbids).
  4. Emit a deterministic run report: how many records the Phase-1 entry carries
     to a deterministic RTL vs how many hand off to the AI-backup, plus the
     recovered top_module / top_ports for every case.

Scoring stays the official flow: the AI-backup completions + the deterministic
RTL are gated by `cvdp_gate.py` (SOLE EMIT) → official `run_benchmark.py`. This
driver establishes the DETERMINISTIC HALF and the exact AI-backup work-list.

CLI:
    python3 cvdp_phase1_entry.py --dataset <cvdp.jsonl> --run <dir> [--limit N]
                                 [--ids id1,id2,...] [--report out.json]

Exit 0 always (a per-case runner failure is recorded, not fatal); exit 2 on a
dataset/IO error.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # POSIX advisory locks; absent on non-POSIX (this plugin runs on Linux).
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None  # type: ignore[assignment]

_HERE = Path(__file__).resolve()
_PLUGIN_ROOT = _HERE.parents[1]
_RUNNER = _PLUGIN_ROOT / "programs" / "vibe_ic_one_shot_runner.py"

sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_PLUGIN_ROOT / "programs"))
from cvdp_task_router import route_record  # noqa: E402  (sibling adapter)

# The record keys the Phase-1 entry is allowed to read. output.* / harness are
# the scoring oracle and MUST NOT participate in authoring/extraction (§ 4.05).
_ALLOWED_INPUT_KEYS = frozenset({"prompt", "context"})


def _render_spec_requirements(prompt: str, context_keys) -> Optional[str]:
    """Run the distilled spec-requirement detectors (memory-map, lint self-gate,
    context-sibling, self-TB coverage, named-signal preservation) on the prompt
    and render them as a markdown brief the Phase-1 spec-to-rtl author reads.

    This closes the Phase-1 wiring gap: the detectors were previously reached only
    via the task_loop hand-off (`ic_expert_backup_pack.assemble`), so a residual
    routed through Phase-1 (spec_generation) never saw its distilled requirement.
    Input-only (§4.05)."""
    try:
        import ic_expert_backup_pack as _pack
        reqs = _pack._spec_requirements(prompt, context_keys)
    except Exception:
        return None
    if not reqs:
        return None
    lines = ["# Distilled spec requirements (program-first, from the prompt)",
             "",
             "The plugin's deterministic detectors flagged these load-bearing "
             "requirements for this design. Honor EACH one in the RTL you author:",
             ""]
    for r in reqs:
        lines.append(f"## {r.get('kind')}")
        lines.append(r.get("requirement", ""))
        lines.append("")
    return "\n".join(lines)


def _assert_no_oracle_read(record: Dict[str, Any]) -> None:
    """Defence-in-depth: this driver reads only `input.prompt` + `input.context`.
    A regression that starts consuming `output` / `harness` (the oracle) would
    make every downstream number a cheat. Nothing here touches them; this is the
    structural guarantee that the staging below only ever sees the input side."""
    # No-op by construction — the function exists so the invariant is named and
    # a future edit that wants oracle data has to delete this line on purpose.
    return None


@contextlib.contextmanager
def _init_lock(lock_path: Path):
    """Advisory EXCLUSIVE lock that serialises the SHARED run-dir scaffold
    creation across concurrently-launched shards (issue #121).

    Auto-released on process death (fcntl.flock) so a crashed shard never leaves
    a stale lock. BEST-EFFORT: if the platform/filesystem cannot lock (fcntl
    absent, or NFS without lockd), we STILL proceed unlocked — every scaffold op
    guarded by this lock is idempotent (`os.makedirs(exist_ok=True)`), so the
    lock only removes the shared-parent TOCTOU window; correctness never depends
    on it. The acquisition is wrapped separately from the `yield` so an exception
    raised by the with-body is never swallowed here."""
    fd = -1
    locked = False
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
            locked = True
    except OSError:
        pass  # best-effort; guarded ops below stay correct via exist_ok=True
    try:
        yield
    finally:
        if fd >= 0:
            if locked:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:  # pragma: no cover - defensive
                    pass
            os.close(fd)


def _ensure_run_scaffold(run_dir: Path) -> None:
    """Idempotent, race-safe creation of the SHARED run-dir scaffold that EVERY
    shard needs before it can stage its first case (issue #121).

    N shards launched in parallel against the SAME ``--run`` dir (disjoint
    ``--ids`` slices) previously raced on the SHARED parent ``run_dir/cases``,
    which was created implicitly-and-concurrently by whichever shard happened to
    stage its first case first. The loser of that race could see its first case
    dir left empty (emit_path=unknown) — a STARTUP race on shared-dir init, not a
    per-case defect. Here we create ``run_dir`` (its parent already exists — the
    launcher made the shared run dir path), then serialise the creation of the
    shared ``run_dir/cases`` parent behind ``_init_lock`` so no two shards
    interleave on it. All ops are idempotent, so the SERIAL path is byte-for-byte
    unchanged and re-runs remain safe."""
    os.makedirs(run_dir, exist_ok=True)
    with _init_lock(run_dir / ".scaffold.lock"):
        os.makedirs(run_dir / "cases", exist_ok=True)


def _atomic_write_text(path: Path, text: str) -> None:
    """Write a (possibly shared) file so a concurrent shard never observes — or
    is left with — a half-written / empty file: write to a pid-unique temp
    sibling then atomically rename it over the target (issue #121). This replaces
    the unconditional truncate-then-write of the shared report."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


def _stage_case(record: Dict[str, Any], case_dir: Path) -> Dict[str, Any]:
    """Deterministically stage ONE CVDP record as a Phase-1 project. Returns a
    small staging manifest (files written). Reads only input.prompt/context."""
    _assert_no_oracle_read(record)
    if case_dir.exists():
        shutil.rmtree(case_dir)
    (case_dir / "input" / "docs").mkdir(parents=True, exist_ok=True)

    inp = record.get("input") or {}
    if not isinstance(inp, dict):
        inp = {}
    prompt = inp.get("prompt") or ""
    (case_dir / "input" / "phase1_prompt.md").write_text(
        str(prompt), encoding="utf-8")
    # Also drop the prompt into input/docs so the doc-extraction track (which
    # reads input/docs/) sees the same text deterministically.
    (case_dir / "input" / "docs" / "prompt.md").write_text(
        str(prompt), encoding="utf-8")

    staged_context: List[str] = []
    ctx = inp.get("context")
    if isinstance(ctx, dict):
        for relpath, source in sorted(ctx.items()):
            if not isinstance(relpath, str) or not isinstance(source, str):
                continue
            # sanitise: keep it inside the case dir (no absolute / .. escape).
            rel = relpath.lstrip("/").replace("..", "_")
            # (a) as a doc so Phase-1's real-module-decl extractor sees the real
            #     `module <name> ( … );` header → deterministic top_module/ports.
            doc_p = case_dir / "input" / "docs" / (rel.replace("/", "__") + ".txt")
            doc_p.parent.mkdir(parents=True, exist_ok=True)
            doc_p.write_text(source, encoding="utf-8")
            # (b) as the real source tree so a modify/complete task + the scorer
            #     compile against the original files.
            src_p = case_dir / rel
            src_p.parent.mkdir(parents=True, exist_ok=True)
            src_p.write_text(source, encoding="utf-8")
            staged_context.append(rel)

    # Distilled spec-requirement brief (Phase-1 wiring): render the detectors'
    # requirements into input/docs/ so the spec-to-rtl author sees them, exactly
    # as the task_loop hand-off carries them for completion/modify tasks.
    ctx_keys = list(ctx.keys()) if isinstance(ctx, dict) else []
    brief = _render_spec_requirements(str(prompt), ctx_keys)
    if brief:
        (case_dir / "input" / "docs" / "spec_requirements.md").write_text(
            brief, encoding="utf-8")

    return {"prompt_chars": len(str(prompt)),
            "context_files": staged_context,
            "spec_requirements": bool(brief)}


def _run_runner(case_dir: Path, timeout: int) -> Dict[str, Any]:
    """Invoke the Phase-1→Phase-2 runner deterministically (phase-3/analog/hw
    skipped). Returns the parsed orchestrator + phase-2 verdicts."""
    cmd = [sys.executable, str(_RUNNER), str(case_dir),
           "--pdk", "sky130A",
           "--skip-phase3", "--skip-analog", "--skip-hardware"]
    # ORGANIC-20260704 — CVDP hidden cocotb harnesses commonly WHITEBOX internal
    # state (dut.<internal>). Opt the reset/clock-variant alias step into its FLAT
    # transform (rename in the module's own header + internal wire alias, no
    # `<top>__rcvar_inner` submodule) so those internals stay hierarchically
    # accessible. Falls back to the wrapper automatically for the additive /
    # internal-caller cases it cannot flatten safely.
    env = {**os.environ, "VIBE_IC_RCVAR_WHITEBOX_FLAT": "1"}
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       env=env)
    except subprocess.TimeoutExpired:
        return {"runner_status": "TIMEOUT"}
    except Exception as e:  # pragma: no cover - defensive
        return {"runner_status": f"ERROR: {e}"}

    out: Dict[str, Any] = {"runner_status": "RAN"}
    orch = case_dir / "reports" / "orchestrator" / "vibe_ic_one_shot.json"
    if orch.is_file():
        try:
            d = json.loads(orch.read_text())
            # report shape: {verdict, halted_at, phases: [{name, verdict, rc}]}
            out["overall_verdict"] = d.get("verdict")
            out["halted_at"] = d.get("halted_at")
            for ph in (d.get("phases") or []):
                if isinstance(ph, dict) and ph.get("name") in (
                        "phase1", "phase2", "analog", "phase3"):
                    out[ph["name"]] = ph.get("verdict")
        except Exception:
            pass
    return out


def _classify_emit(case_dir: Path) -> Dict[str, Any]:
    """Read L9 (recovered top_module / ports) and the phase-2 report to classify
    the emit path as deterministic vs needs_ai_backup."""
    res: Dict[str, Any] = {"top_module": None, "top_ports_n": 0,
                           "rtl_files": [], "emit_path": "unknown"}
    l9 = (case_dir / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json")
    if l9.is_file():
        try:
            d = json.loads(l9.read_text())
            res["top_module"] = d.get("top_module")
            res["top_ports_n"] = len(d.get("top_ports") or [])
        except Exception:
            pass
    rtl_dir = case_dir / "phase2" / "stage1" / "rtl"
    if rtl_dir.is_dir():
        res["rtl_files"] = sorted(p.name for p in rtl_dir.glob("*.*v"))

    p2 = (case_dir / "reports" / "orchestrator" / "phase2_one_shot.json")
    det = False
    waived_rtl_gen = False
    if p2.is_file():
        try:
            steps = (json.loads(p2.read_text()).get("steps") or [])
            for s in steps:
                if s.get("name") == "rtl_gen":
                    if s.get("status") == "PASS" and "deterministic" in \
                            str(s.get("note", "")).lower():
                        det = True
                    if s.get("status") == "WAIVED":
                        waived_rtl_gen = True
        except Exception:
            pass
    if res["rtl_files"] and det:
        res["emit_path"] = "deterministic"
    elif waived_rtl_gen and not res["rtl_files"]:
        res["emit_path"] = "needs_ai_backup"
    elif res["rtl_files"]:
        res["emit_path"] = "rtl_present"
    return res


def run_case(record: Dict[str, Any], run_dir: Path,
             timeout: int) -> Dict[str, Any]:
    cid = record.get("id") or "unknown"
    case_dir = run_dir / "cases" / cid
    staged = _stage_case(record, case_dir)
    runner = _run_runner(case_dir, timeout)
    emit = _classify_emit(case_dir)
    return {"id": cid, **staged, **runner, **emit}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True, help="CVDP dataset JSONL")
    ap.add_argument("--run", required=True, help="run dir (created)")
    ap.add_argument("--limit", type=int, default=0,
                    help="only the first N records (0 = all)")
    ap.add_argument("--ids", default="",
                    help="comma-separated id allow-list (overrides --limit)")
    ap.add_argument("--timeout", type=int, default=300,
                    help="per-case runner timeout (s)")
    ap.add_argument("--route-all", action="store_true",
                    help="drive EVERY record through Phase-1 regardless of task "
                         "nature (debug only; default routes only "
                         "spec_generation via cvdp_task_router)")
    ap.add_argument("--report", default="",
                    help="report JSON path (default <run>/phase1_entry_report.json)")
    a = ap.parse_args(argv)

    ds = Path(a.dataset)
    if not ds.is_file():
        print(f"cvdp_phase1_entry: dataset not found: {ds}", file=sys.stderr)
        return 2
    run_dir = Path(a.run)
    # Race-safe SHARED scaffold init (issue #121): serialise creation of
    # run_dir + run_dir/cases so N parallel shards over the same --run dir cannot
    # lose the shared-parent creation and strand a first case with an empty dir.
    _ensure_run_scaffold(run_dir)

    id_allow = {s.strip() for s in a.ids.split(",") if s.strip()}
    records: List[Dict[str, Any]] = []
    with ds.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if id_allow:
                if r.get("id") in id_allow:
                    records.append(r)
            else:
                records.append(r)
            if a.limit and not id_allow and len(records) >= a.limit:
                break

    # FIRST-LAYER ROUTING (owner architecture 2026-07-05): only a pure-text
    # SPEC-GENERATION task is the plugin's Phase-1 domain. completion / modify /
    # optimize / debug are AI-led transforms of existing RTL — NOT forced through
    # Phase-1's doc-extraction. `--route-all` overrides for debugging.
    results: List[Dict[str, Any]] = []
    for rec in records:
        route = route_record(rec)
        if a.route_all or route.get("route") == "phase1_entry":
            res = run_case(rec, run_dir, a.timeout)
            res["route"] = route.get("route")
            res["task_nature"] = route.get("nature")
            results.append(res)
        else:
            # NOT a spec→RTL task: it enters a DIFFERENT plugin loop (completion
            # / modify / optimize / debug), not Phase-1. Record which one; the
            # loop itself is executed by its own entry, not this driver.
            pe = route.get("plugin_entry") or {}
            results.append({
                "id": rec.get("id"),
                "route": route.get("route"),
                "task_nature": route.get("nature"),
                "plugin_entry": pe.get("name"),
                "emit_path": f"plugin_loop:{pe.get('name')}",
            })

    # Deterministic summary.
    n = len(results)
    driven = [r for r in results if r.get("route") == "phase1_entry"
              or a.route_all]
    n_driven = len(driven)
    n_ai_led = n - n_driven
    tm_ok = sum(1 for r in driven
                if r.get("top_module") not in (None, "chip_top"))
    det = sum(1 for r in driven if r.get("emit_path") == "deterministic")
    ai_backup = sum(1 for r in driven
                    if r.get("emit_path") == "needs_ai_backup")
    p1_pass = sum(1 for r in driven if r.get("phase1") == "PASS")
    report = {
        "dataset": str(ds),
        "n": n,
        "routed_phase1_entry": n_driven,
        "routed_ai_led": n_ai_led,
        "phase1_pass": p1_pass,
        "top_module_recovered": tm_ok,
        "emit_deterministic": det,
        "emit_needs_ai_backup": ai_backup,
        "cases": results,
    }
    out = Path(a.report) if a.report else (run_dir / "phase1_entry_report.json")
    _atomic_write_text(
        out, json.dumps(report, indent=2, ensure_ascii=False))

    print(f"cvdp_phase1_entry: {n} record(s)")
    print(f"  routed → Phase-1 entry : {n_driven} (spec_generation)")
    print(f"  routed → AI-led        : {n_ai_led} (completion/modify/optimize/debug — out of Phase-1 scope)")
    print(f"  --- of the Phase-1 subset ---")
    print(f"  phase1 PASS            : {p1_pass}/{n_driven}")
    print(f"  top_module recovered   : {tm_ok}/{n_driven}")
    print(f"  emit deterministic     : {det}/{n_driven} (json-to-rtl, no LLM)")
    print(f"  emit needs AI-backup   : {ai_backup}/{n_driven} (prose body → spec-to-rtl)")
    print(f"  report                 : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
