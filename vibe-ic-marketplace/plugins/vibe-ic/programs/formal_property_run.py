#!/usr/bin/env python3
"""formal_property_run.py — Step 5 (cap:formal_property_proof) RUNNER.

Deterministic driver that actually RUNS a SymbiYosys formal proof and writes
the `phase2/stage1/formal/results.json` evidence that
`formal_proof_evidence_check.py` (the Step-5 gate) validates. This is the
program behind the formal-verify skill's "runner" doctrine: assertion-gen /
the FV engineer authors the properties (a `formal_<top>.sv` harness); THIS
program dispatches them to SymbiYosys, parses the transcript, and records an
HONEST proved / failed / bounded-depth / cex result.

It is chip-AGNOSTIC — the mechanism (emit a `.sby`, run `sby`, parse the log,
build results.json) is design-independent; the per-design properties live in
the harness file the caller supplies. Two authoring aids are built in and are
themselves general:

  * `emit_reset_safety_harness()` — for any module with a clock, an
    active-high synchronous reset and a registered output, emits the
    always-valuable safety property "one cycle after reset the output is a
    defined known value" (unbounded-provable). No chip literal.
  * `emit_sby()` — wraps a harness in a two-task `.sby`: a `prove` task
    (unbounded k-induction / PDR for the cheap safety invariants) and a
    `bmc` task (a real BOUNDED proof to a chosen depth for properties whose
    full unbounded proof is solver-hard, e.g. a wide multiplier miter).

Verdicts / exit codes:
  0 = all authored properties PROVED (every sby task returned PASS)
  1 = a property FAILED (a real counterexample) — reported with its frame
  2 = NOT_APPLICABLE: no formal properties authored for this design — an
      honest SKIPPED-CONDITION manifest is written (never a fabricated pass)

§4.05: reads only design INPUT (the RTL + the authored property harness).
It never reads a hidden testbench/oracle to synthesise a proof.

Anti-fabrication: `all_proved:true` is written ONLY when the parsed sby
transcript shows every task DONE (PASS); a missing/short/absent transcript,
or any DONE (FAIL/ERROR), can never yield all_proved:true.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402

# ── SBY transcript signatures (tool-output shapes, not chip literals) ──────
# A multi-task run tags every line with `[<sby>_<task>]`; a single-task run
# tags `[<sby>]`.
_LINE_RE = re.compile(r"\[(?P<task>[^\]]+)\]\s+(?P<rest>.*)$")
_DONE_RE = re.compile(r"DONE \((?P<status>PASS|FAIL|ERROR|UNKNOWN|TIMEOUT)",
                      re.IGNORECASE)
_SUMMARY_RET_RE = re.compile(
    r"summary:\s*(?:engine_\d+\s*\([^)]*\)\s*returned|Status:)\s*"
    r"(?P<status>PASS|FAIL|ERROR|UNKNOWN|TIMEOUT)", re.IGNORECASE)
_ENGINE_RE = re.compile(r"engine_\d+:\s*(?P<engine>abc\s+\w+|smtbmc.*|btor.*|"
                        r"aiger.*)$", re.IGNORECASE)
_CEX_FRAME_RE = re.compile(r"asserted in frame (?P<frame>\d+)", re.IGNORECASE)
_SBY_SIG_RE = re.compile(r"\bSBY\b|symbiyosys|smtbmc|engine_\d", re.IGNORECASE)

# ── .sby config parsing (per-task mode/depth/engine) ───────────────────────
_SECTION_RE = re.compile(r"^\[(?P<name>[\w-]+)\]\s*$")
# a line inside a section may be task-scoped: `task: value` or `~task: value`
_SCOPED_RE = re.compile(r"^(?P<neg>~?)(?P<task>[\w-]+):\s*(?P<val>.*)$")


@dataclass
class TaskResult:
    name: str
    status: str = "UNKNOWN"          # PASS / FAIL / ERROR / UNKNOWN
    engine: str = ""
    mode: str = ""                   # prove / bmc / cover
    depth: Optional[int] = None
    cex_frame: Optional[int] = None

    @property
    def bound_kind(self) -> str:
        return bound_kind(self.mode, self.status)


@dataclass
class LogParse:
    tasks: Dict[str, TaskResult] = field(default_factory=dict)

    @property
    def all_pass(self) -> bool:
        return bool(self.tasks) and all(
            t.status == "PASS" for t in self.tasks.values())

    @property
    def any_fail(self) -> bool:
        return any(t.status in ("FAIL", "ERROR") for t in self.tasks.values())


# ── pure helpers (unit-tested; no docker / no filesystem) ──────────────────
def bound_kind(mode: str, status: str) -> str:
    """Classify the STRENGTH of a task result, honestly.

    prove + PASS  -> 'unbounded'   (holds for all reachable states)
    bmc   + PASS  -> 'bounded'     (no bug within the depth; NOT a full proof)
    cover + PASS  -> 'reachable'
    *     + FAIL  -> 'cex'         (a real counterexample)
    otherwise     -> 'inconclusive'
    """
    m = (mode or "").lower()
    s = (status or "").upper()
    if s == "FAIL":
        return "cex"
    if s != "PASS":
        return "inconclusive"
    if m == "prove":
        return "unbounded"
    if m == "bmc":
        return "bounded"
    if m == "cover":
        return "reachable"
    return "inconclusive"


def parse_sby_config(text: str) -> Dict[str, TaskResult]:
    """Parse a .sby into per-task {mode, depth, engine}. Understands the
    [tasks] list and task-scoped `task:`/`~task:` lines in [options]/[engines].
    A run with no [tasks] section is a single implicit task named ''."""
    section = None
    tasks: List[str] = []
    # collect raw (scope, key/val) per section
    opt_global: Dict[str, str] = {}
    opt_task: Dict[str, Dict[str, str]] = {}
    eng_global = ""
    eng_task: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        msec = _SECTION_RE.match(line)
        if msec:
            section = msec.group("name").lower()
            continue
        if not line or line.startswith("#"):
            continue
        if section == "tasks":
            # `<taskname> [alias...]` — first token is the task id
            tasks.append(line.split()[0])
            continue
        msc = _SCOPED_RE.match(line)
        scope = None
        val = line
        if msc and not line.lower().startswith(("mode ", "depth ", "engine ")):
            scope = msc.group("task")
            neg = msc.group("neg")
            val = msc.group("val").strip()
            if neg:                      # `~task:` — applies to all but `task`
                scope = None
        if section == "options":
            kv = val.split(None, 1)
            if len(kv) == 2:
                k, v = kv[0].lower(), kv[1].strip()
                if scope:
                    opt_task.setdefault(scope, {})[k] = v
                else:
                    opt_global[k] = v
        elif section == "engines":
            if scope:
                eng_task[scope] = val
            else:
                eng_global = val
    if not tasks:
        tasks = [""]
    out: Dict[str, TaskResult] = {}
    for t in tasks:
        mode = opt_task.get(t, {}).get("mode", opt_global.get("mode", ""))
        depth_s = opt_task.get(t, {}).get("depth", opt_global.get("depth"))
        try:
            depth = int(depth_s) if depth_s is not None else None
        except (TypeError, ValueError):
            depth = None
        out[t] = TaskResult(name=t, mode=mode, depth=depth,
                            engine=eng_task.get(t, eng_global))
    return out


def parse_sby_log(text: str, sby_stem: str = "",
                  seed: Optional[Dict[str, TaskResult]] = None) -> LogParse:
    """Parse a SymbiYosys transcript into per-task PASS/FAIL/engine/cex.

    `sby_stem` (the .sby basename without extension) is stripped from the
    `<stem>_<task>` bracket tag so task names match the .sby. `seed` may
    pre-populate mode/depth from parse_sby_config so the merge is one step.
    """
    lp = LogParse()
    if seed:
        for k, v in seed.items():
            lp.tasks[k] = TaskResult(name=k, mode=v.mode, depth=v.depth,
                                     engine=v.engine)

    def _task_for(tag: str) -> str:
        tag = tag.strip()
        if sby_stem and tag == sby_stem:
            return ""
        if sby_stem and tag.startswith(sby_stem + "_"):
            return tag[len(sby_stem) + 1:]
        # unknown tag: if it matches a seeded task name use it, else use raw
        if tag in lp.tasks:
            return tag
        return tag

    for raw in text.splitlines():
        m = _LINE_RE.search(raw)
        if not m:
            continue
        tag = m.group("task")
        rest = m.group("rest")
        # skip non-task tags (SBY sometimes brackets other things)
        name = _task_for(tag)
        tr = lp.tasks.get(name)
        if tr is None:
            tr = TaskResult(name=name)
            lp.tasks[name] = tr
        me = _ENGINE_RE.search(rest)
        if me:
            tr.engine = me.group("engine").strip()
        mf = _CEX_FRAME_RE.search(rest)
        if mf and tr.cex_frame is None:
            tr.cex_frame = int(mf.group("frame"))
        md = _DONE_RE.search(rest)
        if md:
            tr.status = md.group("status").upper()
            continue
        ms = _SUMMARY_RET_RE.search(rest)
        if ms and tr.status in ("UNKNOWN", ""):
            tr.status = ms.group("status").upper()
    # drop pseudo-tasks that never carried a real status/engine and are not
    # in the seed (e.g. a stray bracket tag) — keep only decided ones.
    if seed:
        for k in list(lp.tasks):
            if k not in seed and lp.tasks[k].status == "UNKNOWN" \
                    and not lp.tasks[k].engine:
                del lp.tasks[k]
    return lp


def build_results(top: str, cfg: Dict[str, TaskResult], lp: LogParse,
                  evidence_relpath: str, sby_relpath: str) -> dict:
    """Merge config (mode/depth) with the log (status/engine/cex) into the
    canonical results.json dict the Step-5 gate consumes. all_proved is true
    ONLY when at least one task ran and every task returned PASS."""
    props = []
    for name, tr in sorted(lp.tasks.items()):
        c = cfg.get(name)
        mode = tr.mode or (c.mode if c else "")
        depth = tr.depth if tr.depth is not None else (c.depth if c else None)
        merged = TaskResult(name=name, status=tr.status, engine=tr.engine,
                            mode=mode, depth=depth, cex_frame=tr.cex_frame)
        props.append({
            "task": name or top,
            "mode": mode,
            "engine": merged.engine,
            "depth": depth,
            "status": tr.status,
            "bound": merged.bound_kind,
            "cex_frame": tr.cex_frame,
        })
    all_proved = lp.all_pass
    any_unbounded = any(p["bound"] == "unbounded" for p in props)
    any_bounded = any(p["bound"] == "bounded" for p in props)
    if not props:
        verdict = "SKIPPED-CONDITION"
    elif all_proved:
        verdict = "PASS"
    else:
        verdict = "FAIL"
    disclosure = []
    if any_unbounded:
        disclosure.append("safety invariants proved UNBOUNDED (mode prove)")
    if any_bounded:
        bd = [p for p in props if p["bound"] == "bounded"]
        depths = sorted({p["depth"] for p in bd if p["depth"] is not None})
        disclosure.append(
            "functional property proved BOUNDED via BMC to depth "
            f"{max(depths) if depths else '?'} (no counterexample within the "
            "bound; a full unbounded proof of a wide datapath may be "
            "solver-hard — this is a disclosed bounded result, not a full "
            "proof)")
    return {
        "program": "formal_property_run",
        "version": "1.0.0",
        "top": top,
        "verdict": verdict,
        "all_proved": bool(all_proved),
        "property_count": len(props),
        "proved": sum(1 for p in props if p["status"] == "PASS"),
        "failed": sum(1 for p in props if p["status"] == "FAIL"),
        "properties": props,
        "bounded_vs_unbounded": disclosure,
        "sby": sby_relpath,
        "evidence": evidence_relpath,
    }


# ── harness / sby emitters (general authoring aids) ────────────────────────
def emit_reset_safety_harness(top: str, clk: str = "clk", rst: str = "rst",
                              out_port: str = "p", out_known: str = "1'b0",
                              extra_ports: Optional[List[str]] = None) -> str:
    """Emit a minimal formal harness proving the always-valuable safety
    invariant: one cycle after a synchronous active-high reset, the registered
    output settles to a known value. General — no chip literal. `extra_ports`
    are declared as free `(* anyseq *)` inputs and connected by name."""
    extra_ports = extra_ports or []
    decls = "\n".join(
        f"    (* anyseq *) wire {p};" for p in extra_ports)
    conns = "".join(f", .{p}({p})" for p in extra_ports)
    return f"""// formal_{top}.sv — auto-emitted reset-safety harness (general).
`default_nettype none
module formal_{top} (input wire {clk});
    (* anyseq *) wire {rst};
{decls}
    wire {out_port};
    {top} dut (.{clk}({clk}), .{rst}({rst}){conns}, .{out_port}({out_port}));
    reg f_past_valid = 1'b0;
    always @(posedge {clk}) f_past_valid <= 1'b1;
    reg rst_q = 1'b0;
    always @(posedge {clk}) rst_q <= {rst};
    always @(posedge {clk})
        if (f_past_valid && rst_q) assert ({out_port} == {out_known});
endmodule
`default_nettype wire
"""


def emit_sby(rtl_files: List[str], harness_file: str, top: str,
             safety_defs: str = "-DSPM_SAFETY_ONLY",
             bmc_defs: str = "-DSPM_RESET_AT_T0",
             safety_depth: int = 20, bmc_depth: int = 12,
             engine_prove: str = "abc pdr",
             engine_bmc: str = "abc bmc3") -> str:
    """Emit a two-task .sby: a `safety` task (unbounded prove) and a `bmc`
    task (bounded model check). Files are listed under [files] so the Step-5
    evidence gate can resolve every referenced source. `aigsmt none` avoids
    the SMT witness-replay step (only an external SMT solver could satisfy it)
    so ABC's own engines produce the verdict standalone."""
    reads = " ".join([harness_file] + list(rtl_files))
    srcs = list(rtl_files) + [harness_file]
    files_block = "\n".join(srcs)
    return f"""[tasks]
safety   prove
bmc      bmc

[options]
safety: mode prove
safety: depth {safety_depth}
bmc:    mode bmc
bmc:    depth {bmc_depth}
aigsmt none

[engines]
safety: {engine_prove}
bmc:    {engine_bmc}

[script]
safety: read_verilog -formal {safety_defs} {reads}
~safety: read_verilog -formal {bmc_defs} {reads}
prep -top {top}

[files]
{files_block}
"""


# ── impure runner ──────────────────────────────────────────────────────────
def _run_sby(sby_path: Path, formal_dir: Path, container: Optional[str],
             timeout: int) -> str:
    """Run `sby -f <sby>` in `formal_dir` and return the transcript. When
    `container` is set the run is `docker exec <container>` with the vibeic-eda
    tool PATH; otherwise sby is invoked from the ambient PATH."""
    name = sby_path.name
    if container:
        path_export = ("export PATH=/foss/tools/bin:/foss/tools/yosys/bin:"
                       "$PATH")
        inner = (f"{path_export}; cd {formal_dir} && rm -rf {sby_path.stem} "
                 f"&& sby -f {name}")
        cmd = ["docker", "exec", container, "bash", "-lc", inner]
    else:
        cmd = ["sby", "-f", name]
    try:
        p = subprocess.run(cmd, cwd=str(formal_dir), capture_output=True,
                           text=True, timeout=timeout)
        return (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        err = e.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return out + err + f"\n[formal_property_run] TIMEOUT after {timeout}s\n"
    except FileNotFoundError:
        return "[formal_property_run] ERROR: sby/docker not found on PATH\n"


def _write_not_applicable(formal_dir: Path, reason: str) -> None:
    (formal_dir / "formal_not_run.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION",
        "program": "formal_property_run",
        "fallback_skill": "assertion-gen",
        "reason": reason,
    }, indent=2, ensure_ascii=False) + "\n")


def run(project: Path, harness: Optional[Path] = None,
        rtl: Optional[List[Path]] = None, top: Optional[str] = None,
        sby: Optional[Path] = None, container: Optional[str] = "vibeic-eda",
        bmc_depth: int = 12, safety_depth: int = 20,
        timeout: int = 900) -> dict:
    formal_dir = _pl.formal_dir(project)
    formal_dir.mkdir(parents=True, exist_ok=True)

    # 1) locate/emit the .sby + stage sources into formal/ ------------------
    sby_path: Optional[Path] = None
    if sby is not None and sby.is_file():
        sby_path = formal_dir / sby.name
        if sby.resolve() != sby_path.resolve():
            shutil.copy2(sby, sby_path)
    else:
        existing = sorted(formal_dir.glob("*.sby"))
        if existing and harness is None:
            sby_path = existing[0]

    if sby_path is None:
        # need to author a .sby from a harness
        if harness is None or not harness.is_file():
            _write_not_applicable(
                formal_dir,
                "no formal property harness authored for this design — "
                "assertion-gen must author formal_<top>.sv (properties) "
                "before a proof can run; no proof was fabricated")
            return {"verdict": "SKIPPED-CONDITION", "rc": 2,
                    "reason": "no harness"}
        if not rtl or top is None:
            return {"verdict": "ERROR", "rc": 1,
                    "reason": "harness given but --rtl/--top missing"}
        # stage sources
        staged_rtl = []
        for r in rtl:
            dst = formal_dir / r.name
            if r.resolve() != dst.resolve():
                shutil.copy2(r, dst)
            staged_rtl.append(r.name)
        hdst = formal_dir / harness.name
        if harness.resolve() != hdst.resolve():
            shutil.copy2(harness, hdst)
        sby_text = emit_sby(staged_rtl, harness.name, top,
                            safety_depth=safety_depth, bmc_depth=bmc_depth)
        sby_path = formal_dir / f"{top}_formal.sby"
        sby_path.write_text(sby_text)
    else:
        # a .sby already exists: ensure its [files] sources are staged
        cfg_text = sby_path.read_text()
        for line in cfg_text.splitlines():
            ls = line.strip()
            if ls.endswith((".v", ".sv")) and "/" in ls and Path(ls).is_file():
                shutil.copy2(ls, formal_dir / Path(ls).name)

    # 2) run sby -------------------------------------------------------------
    transcript = _run_sby(sby_path, formal_dir, container, timeout)
    log_path = formal_dir / f"{sby_path.stem}.sby.log"
    log_path.write_text(transcript)

    # 3) parse + build results ----------------------------------------------
    cfg = parse_sby_config(sby_path.read_text())
    lp = parse_sby_log(transcript, sby_stem=sby_path.stem, seed=cfg)
    top_name = top or sby_path.stem
    ev_rel = str(log_path.relative_to(project))
    sby_rel = str(sby_path.relative_to(project))
    results = build_results(top_name, cfg, lp, ev_rel, sby_rel)
    if results["property_count"]:
        # A real proof ran: results.json is now the canonical artifact, so a
        # stale `formal_not_run.json` skip-sentinel (from an earlier chain
        # where no proof ran) must not linger and contradict it.
        stale = formal_dir / "formal_not_run.json"
        if stale.is_file():
            stale.unlink()
    (formal_dir / "results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n")

    # 4) human report --------------------------------------------------------
    _write_report(formal_dir, results)

    rc = 0 if results["all_proved"] else (
        2 if results["verdict"] == "SKIPPED-CONDITION" else 1)
    results["rc"] = rc
    return results


def _write_report(formal_dir: Path, results: dict) -> None:
    lines = [f"# Formal proof report — {results['top']}", "",
             f"verdict: **{results['verdict']}**  "
             f"(all_proved={results['all_proved']}, "
             f"{results['proved']}/{results['property_count']} tasks PASS)", "",
             "| task | mode | engine | depth | status | strength | cex frame |",
             "|------|------|--------|-------|--------|----------|-----------|"]
    for p in results["properties"]:
        lines.append(
            f"| {p['task']} | {p['mode']} | {p['engine']} | "
            f"{p['depth']} | {p['status']} | {p['bound']} | "
            f"{p['cex_frame'] if p['cex_frame'] is not None else ''} |")
    lines += ["", "## Bounded vs unbounded disclosure"]
    for d in results["bounded_vs_unbounded"]:
        lines.append(f"- {d}")
    lines += ["", f"Evidence transcript: `{results['evidence']}`",
              f"SymbiYosys task file: `{results['sby']}`", ""]
    (formal_dir / f"{results['top']}_report.md").write_text("\n".join(lines))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--harness", type=Path, default=None,
                    help="authored formal_<top>.sv property harness")
    ap.add_argument("--rtl", type=Path, nargs="*", default=None,
                    help="design RTL sources (INPUT only)")
    ap.add_argument("--top", default=None, help="formal top module name")
    ap.add_argument("--sby", type=Path, default=None,
                    help="pre-authored .sby (overrides emit)")
    ap.add_argument("--container", default="vibeic-eda",
                    help="docker container running SymbiYosys ('' = local)")
    ap.add_argument("--bmc-depth", type=int, default=12)
    ap.add_argument("--safety-depth", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"ERROR: not a directory: {args.project_dir}", file=sys.stderr)
        return 1
    res = run(args.project_dir.resolve(), harness=args.harness, rtl=args.rtl,
              top=args.top, sby=args.sby,
              container=(args.container or None),
              bmc_depth=args.bmc_depth, safety_depth=args.safety_depth,
              timeout=args.timeout)
    rc = res.pop("rc", 0)
    out = json.dumps(res, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
