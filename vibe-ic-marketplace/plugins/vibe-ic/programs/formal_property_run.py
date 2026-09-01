#!/usr/bin/env python3
"""formal_property_run.py — Step 5 formal-property RUNNER.

Deterministic driver that actually RUNS a SymbiYosys formal proof and writes
the `phase2/stage1/formal/results.json` evidence that
`formal_proof_evidence_check.py` (the Step-5 gate) validates. This is the
program behind the formal-verify skill's program-first doctrine: the
deterministic floor or FV engineer authors a `formal_<top>.sv` harness; THIS
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
  2 = INCOMPLETE: applicable formal work has no sound authored property, or
      the declaration/property denominator is not closed. Exact obligation IDs
      and the formal-verify route are written (never a fabricated pass).
  3 = ENV_UNAVAILABLE: the proof engine was never REACHED (see #216)
  4 = INCONCLUSIVE because a RESOURCE CEILING stopped the proof — the run
      names which resource ran out and at what limit
  5 = EMIT_ONLY: the .sby was authored and its sources staged; NO proof was
      run, so nothing was proved and nothing was refuted

BOUNDED BY CONSTRUCTION. A formal proof is entitled to be expensive; it is not
entitled to the host. Every invocation carries an address-space ceiling and a
deadline, on BOTH the container path and the ambient-PATH path, and the deadline
reaches the whole solver process group rather than the launcher we hold. A run a
ceiling stopped is INCONCLUSIVE — never PASS (nothing was proved) and never FAIL
(nothing was refuted) — and it says WHICH resource ran out, because
"inconclusive" with no resource named sends the reader to the design when the
fix is on the host. `assert_resource_honesty` is the executed guard.

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
import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import _container_exec as _CE  # vibe-ic#628 — bound the solver, not the client

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402
import _rtl_include_hub as _hub  # noqa: E402  (include-hub aggregator predicate)

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

# ── environment reachability (#216) ────────────────────────────────────────
# "The proof engine was never reached" and "the proof ran and was
# inconclusive" are DIFFERENT facts. The pre-fix shape collapsed them: an
# unreachable engine produced `verdict: INCONCLUSIVE` with one UNKNOWN
# property row PER .sby TASK — rows manufactured from the CONFIG, since the
# transcript was a single docker error line. That is a proof-strength claim
# made on zero proof evidence, and it left whoever had to fix the host with
# no capability name, no search location and no remedy.
#
# Each signature below is a TOOL/RUNTIME output shape (docker CLI, shell
# not-found, our own FileNotFoundError note) — never a chip or design
# literal, so the classification is chip-AGNOSTIC.
_ENV_GAP_SIGNATURES = (
    # (regex, missing_capability, remedy_template)
    (re.compile(r"No such container:\s*(?P<detail>\S+)", re.IGNORECASE),
     "docker container",
     "the EDA container named {searched_container!r} is not running — start "
     "it (docker start {searched_container!r}) or pass --container with the "
     "name of a running vibeic-eda container (docker ps)"),
    (re.compile(r"Cannot connect to the Docker daemon|"
                r"docker daemon is not running|"
                r"permission denied while trying to connect to the Docker",
                re.IGNORECASE),
     "docker daemon",
     "the Docker daemon is not reachable from this host — start Docker, or "
     "run with --container '' to invoke sby from the ambient PATH"),
    (re.compile(r"sby/docker not found on PATH", re.IGNORECASE),
     "sby",
     "neither `sby` nor `docker` is on PATH — install SymbiYosys (our fork "
     "ships in the vibeic-eda image at /usr/local/bin/sby) or run inside "
     "the container with --container <name>"),
    (re.compile(r"(?:^|[:\s])sby:?\s+(?:command not found|not found)"
                r"|command not found:\s*sby", re.IGNORECASE),
     "sby",
     "`sby` is not on PATH inside the search location — our SymbiYosys fork "
     "ships in the vibeic-eda image at /usr/local/bin/sby; verify with "
     "`docker exec <container> command -v sby`"),
)


def classify_env_gap(transcript: str,
                     container: Optional[str]) -> Optional[Dict[str, str]]:
    """Return a structured, ACTIONABLE environment gap when the transcript
    shows the proof engine was never REACHED, else None.

    Pure: transcript text in, dict out — no process is spawned, so the
    classification is unit-testable without Docker.

    A gap is only reported when the transcript ALSO carries no SymbiYosys
    signature: once sby has genuinely spoken, the run is a real (possibly
    inconclusive) proof and must never be re-labelled an environment gap.

    The returned dict answers the three questions a reader needs to fix the
    host: WHAT capability is missing, WHERE the flow looked for it, and WHAT
    to install or stage.
    """
    text = transcript or ""
    if _SBY_SIG_RE.search(text):
        return None  # sby ran and spoke — not an environment gap
    searched = (f"docker exec {container} (PATH=/foss/tools/bin:"
                f"/foss/tools/yosys/bin:$PATH)" if container
                else "ambient PATH of the calling shell")
    for rx, capability, remedy in _ENV_GAP_SIGNATURES:
        m = rx.search(text)
        if not m:
            continue
        return {
            "missing_capability": capability,
            "searched": searched,
            "searched_container": container or "",
            "remedy": remedy.format(searched_container=container or ""),
            "tool_message": (m.group(0) or "").strip()[:300],
        }
    return None

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


def assert_bound_honesty(props: List[dict]) -> bool:
    """HONESTY GUARD: a bounded model check (mode bmc) can NEVER be reported as
    an unbounded (full) proof, no matter how many frames it reached. `bound_kind`
    already enforces this, but this is the explicit, unit-tested contract so a
    future refactor cannot silently dress a deep BMC as a full proof. Returns
    True when every property's strength label is honest; raises otherwise."""
    for p in props:
        mode = (p.get("mode") or "").lower()
        if mode == "bmc" and p.get("bound") == "unbounded":
            raise AssertionError(
                f"dishonest strength: bmc task '{p.get('task')}' "
                f"(depth {p.get('depth')}) labelled 'unbounded' — a BMC that "
                "merely reached a high depth is NOT a full proof")
        if mode == "prove" and p.get("status") == "PASS" \
                and p.get("bound") != "unbounded":
            raise AssertionError(
                f"inconsistent strength: proved task '{p.get('task')}' "
                "not labelled 'unbounded'")
    return True


def assert_resource_honesty(results: dict,
                            resource_stop: Optional[dict]) -> bool:
    """HONESTY GUARD: a run a RESOURCE CEILING stopped can never be recorded as
    proved.

    The twin of `assert_bound_honesty`, and for the same reason: the rule is
    stated once, EXECUTED on every run, and unit-tested, so a future refactor
    cannot quietly let a bound-stop be counted as a proof. Recording an
    unfinished proof as proved is the worst outcome available here — it is the
    only one that makes the flow greener than the evidence.

    Returns True when the record is honest; raises AssertionError otherwise.
    """
    if not resource_stop:
        return True
    if results.get("all_proved") or results.get("verdict") == "PASS":
        raise AssertionError(
            "dishonest verdict: the proof was stopped by a "
            f"{resource_stop.get('resource')} ceiling "
            f"({resource_stop.get('limit')} {resource_stop.get('unit')}) yet "
            f"the record claims verdict={results.get('verdict')!r} "
            f"all_proved={results.get('all_proved')!r} — a proof that ran out "
            "of a resource is INCONCLUSIVE, never proved")
    return True


def proof_strength(props: List[dict]) -> str:
    """Overall honest strength of a property set:
      'unbounded' — at least one property PROVED unbounded (mode prove PASS)
                    and no counterexample anywhere;
      'bounded'   — no unbounded proof, but a BMC held to its depth (no cex);
      'cex'       — a real counterexample was found;
      'none'      — nothing decided.
    Only 'unbounded' is a full datapath proof; 'bounded' is disclosed-bounded."""
    if any(p.get("bound") == "cex" for p in props):
        return "cex"
    if any(p.get("bound") == "unbounded" for p in props):
        return "unbounded"
    if any(p.get("bound") == "bounded" for p in props):
        return "bounded"
    return "none"


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
    # HONESTY GUARD: never allow a bmc task to be dressed as an unbounded proof.
    assert_bound_honesty(props)
    all_proved = lp.all_pass
    any_unbounded = any(p["bound"] == "unbounded" for p in props)
    any_bounded = any(p["bound"] == "bounded" for p in props)
    strength = proof_strength(props)
    any_cex = any(p["bound"] == "cex" for p in props)
    any_pass = any(p["status"] == "PASS" for p in props)
    if not props:
        verdict = "SKIPPED-CONDITION"
    elif all_proved:
        verdict = "PASS"
    elif any_cex:
        # a REAL counterexample refuted a property — a hard formal FAIL
        verdict = "FAIL"
    elif any_pass:
        # some properties proved/bounded, others inconclusive (e.g. a wide
        # datapath prove that TIMED OUT) — no property was refuted. Honest
        # PARTIAL, NOT a fabricated PASS and NOT a counterexample FAIL.
        verdict = "PARTIAL"
    else:
        verdict = "INCONCLUSIVE"
    disclosure = []
    if any_unbounded:
        up = [p for p in props if p["bound"] == "unbounded"]
        disclosure.append(
            "property PROVED UNBOUNDED (mode prove — holds for all reachable "
            f"states): {', '.join(sorted(p['task'] for p in up))}")
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
        "version": "1.1.0",
        "top": top,
        "verdict": verdict,
        "all_proved": bool(all_proved),
        # HONEST top-level strength: True ONLY when a `prove` task truly PASSED.
        "unbounded_proved": bool(any_unbounded),
        "proof_strength": strength,
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


# ── invariant-strengthened harness (auxiliary-invariant / datapath proof) ──
# A strengthened harness reaches the DUT's INTERNAL state (e.g. a carry-save
# accumulator) so a k-inductive invariant can be PROVED UNBOUNDED where the
# output-only miter only reaches a bounded BMC depth. This Yosys build's
# built-in Verilog frontend has no hierarchical references, so the harness
# leaves the internal nets as UNDRIVEN placeholder wires and declares, in
# `// @connect <placeholder> = <inst>.<net>` pragmas, how the .sby should wire
# them at the netlist level (flatten + `connect -set`). The mechanism is
# design-INDEPENDENT — the per-design internal-net names live in the harness
# (which is design INPUT), never in this program.
_PRAGMA_CONNECT_RE = re.compile(
    r"//\s*@connect\s+(?P<lhs>[\w.$:\[\]]+)\s*=\s*(?P<rhs>[\w.$:\[\]]+)")
_PRAGMA_CHPARAM_RE = re.compile(
    r"//\s*@chparam\s+(?P<name>\w+)\s*=\s*(?P<val>-?\w+)")
_PRAGMA_INV_RE = re.compile(r"//\s*@invariant-harness\b")
# `// @task <name> <prove|bmc> [depth=<n>] [-- <read_verilog defines...>]`
# defines are the REST of the line (after `--`) so spaces are fine. The task
# NAMES / define macros live in the harness (design INPUT) — the program stays
# design-independent.
_PRAGMA_TASK_RE = re.compile(
    r"//\s*@task\s+(?P<name>\w+)\s+(?P<mode>prove|bmc)"
    r"(?:\s+depth=(?P<depth>\d+))?(?:\s+timeout=(?P<timeout>\d+))?"
    r"(?:\s+--\s+(?P<defines>.*?))?\s*$",
    re.MULTILINE)


def parse_harness_pragmas(text: str) -> dict:
    """Extract the strengthened-harness directives (pure). A harness is treated
    as invariant-strengthened if it carries the `@invariant-harness` marker OR
    any `@connect` pragma (reaching an internal net is what makes it stronger
    than a port-only harness). `@task` pragmas declare the proof tasks (each
    with its own read_verilog defines) so one harness can carry several
    selectable strengthened properties (e.g. an unbounded reference-equivalence
    task plus a bounded product-miter task)."""
    connects = [(m.group("lhs"), m.group("rhs"))
                for m in _PRAGMA_CONNECT_RE.finditer(text)]
    chparams = [(m.group("name"), m.group("val"))
                for m in _PRAGMA_CHPARAM_RE.finditer(text)]
    tasks = []
    for m in _PRAGMA_TASK_RE.finditer(text):
        tasks.append({
            "name": m.group("name"),
            "mode": m.group("mode"),
            "depth": int(m.group("depth")) if m.group("depth") else None,
            "timeout": int(m.group("timeout")) if m.group("timeout") else None,
            "defines": (m.group("defines") or "").strip(),
        })
    is_inv = bool(_PRAGMA_INV_RE.search(text)) or bool(connects)
    return {"connects": connects, "chparams": chparams, "tasks": tasks,
            "is_invariant": is_inv}


def emit_invariant_sby(rtl_files: List[str], harness_file: str, top: str,
                       connects: List, chparams: List,
                       tasks: Optional[List[dict]] = None,
                       prove_engine: str = "abc pdr",
                       bmc_engine: str = "abc bmc3",
                       prove_depth: int = 40, bmc_depth: int = 25) -> str:
    """Emit a .sby for an invariant-strengthened harness. The [script] flattens
    the DUT and `connect -set`s each declared placeholder to its internal net,
    then runs each declared task. A `prove` task (unbounded k-induction / PDR)
    attempts a FULL proof; a `bmc` task gives a bounded corroboration. Each task
    reads the harness with its OWN `defines` (task-scoped read_verilog) so one
    harness file can carry several selectable strengthened properties. When a
    `prove` task returns PASS the result is an honest UNBOUNDED proof (mode prove
    -> bound_kind 'unbounded'); a `bmc` PASS is never more than bounded."""
    if not tasks:
        tasks = [{"name": "prove", "mode": "prove", "depth": None,
                  "defines": ""},
                 {"name": "bmc", "mode": "bmc", "depth": None, "defines": ""}]
    reads = " ".join([harness_file] + list(rtl_files))
    srcs = list(rtl_files) + [harness_file]
    files_block = "\n".join(srcs)
    chparam_lines = [f"chparam -set {n} {v} {top}" for n, v in chparams]
    connect_lines = [f"connect -set {lhs} {rhs}" for lhs, rhs in connects]

    task_names, opts, engines, read_lines = [], [], [], []
    for t in tasks:
        nm, mode = t["name"], t["mode"]
        task_names.append(nm)
        if mode == "prove":
            depth = t.get("depth") or prove_depth
            opts += [f"{nm}: mode prove", f"{nm}: depth {depth}"]
            engines.append(f"{nm}: {prove_engine}")
        else:
            depth = t.get("depth") or bmc_depth
            opts += [f"{nm}: mode bmc", f"{nm}: depth {depth}"]
            engines.append(f"{nm}: {bmc_engine}")
        if t.get("timeout"):
            # bound a hard prove of a wide datapath so it reports an HONEST
            # TIMEOUT (inconclusive) instead of hanging — never a fake proof.
            opts.append(f"{nm}: timeout {t['timeout']}")
        defs = (t.get("defines") or "").strip()
        read_lines.append(
            f"{nm}: read_verilog -formal -sv {defs + ' ' if defs else ''}"
            f"{reads}")

    tasks_block = "\n".join(task_names)
    opts_block = "\n".join(opts) + "\naigsmt none\n"
    engines_block = "\n".join(engines)
    script = list(read_lines) + list(chparam_lines)
    script += [f"hierarchy -top {top}", "proc", "flatten"]
    script += list(connect_lines)
    script += ["opt -fast", f"prep -top {top}"]
    script_block = "\n".join(script)
    return f"""[tasks]
{tasks_block}

[options]
{opts_block}
[engines]
{engines_block}

[script]
{script_block}

[files]
{files_block}
"""


# ── stronger-engine (datapath) backend detection ───────────────────────────
# OSS unbounded / algebraic multiplier verifiers that beat bit-level BMC on a
# wide datapath. `abc pdr` (bundled in yosys/sby) is ALWAYS available; the rest
# are optional forks. Absence is reported HONESTLY — never a fabricated proof.
_DATAPATH_ENGINES = ("btormc", "pono", "avy", "amulet2", "amulet",
                     "boolector", "bitwuzla", "yices-smt2", "z3")


def detect_engines(container: Optional[str]) -> Dict[str, bool]:
    """Probe which stronger OSS model-checking / SMT engines are on PATH in the
    container (impure). `abc` (via yosys/sby) is always present. Used so an
    `--engine-backend btor|amulet` request can be honoured only when the engine
    truly exists — otherwise the program says so instead of faking a proof."""
    # #216 — `abc` used to be hardcoded True and reported as available even
    # when the probe itself could not run (nonexistent container, no Docker).
    # An availability map is EVIDENCE about the environment; asserting a tool
    # is present in an environment we could not reach is a claim with no
    # evidence behind it.
    #
    # `abc` is NOT a standalone binary in the image — it ships bundled inside
    # yosys/sby, so `command -v abc` legitimately misses it. Its availability
    # is therefore derived from the carrier (`sby`/`yosys`) actually being
    # found, which is exactly the condition under which sby can drive
    # `abc pdr`. That keeps the report honest in BOTH directions: no
    # fabricated presence when the environment is unreachable, and no false
    # absence when abc is genuinely usable.
    carriers = ("sby", "yosys")
    probe_tools = carriers + _DATAPATH_ENGINES
    probe = "; ".join(f"command -v {t} >/dev/null 2>&1 && echo {t}"
                      for t in probe_tools)
    reachable = True
    try:
        if container:
            cmd = ["docker", "exec", container, "bash", "-lc", probe]
        else:
            cmd = ["bash", "-lc", probe]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        found = set((p.stdout or "").split())
        # A nonzero rc with NO tool echoed means the shell itself never ran
        # (e.g. "No such container") — the probe result is not evidence.
        if p.returncode != 0 and not found:
            reachable = False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        found = set()
        reachable = False
    avail: Dict[str, bool] = {t: (reachable and t in found)
                              for t in _DATAPATH_ENGINES}
    # abc is usable exactly when its carrier toolchain was genuinely found.
    avail["abc"] = reachable and bool(found & set(carriers))
    avail["_env_reachable"] = reachable
    return avail


# ── exit-code lexicon (see the module docstring) ───────────────────────────
RC_ALL_PROVED = 0
RC_PROPERTY_FAILED = 1
RC_INCOMPLETE = 2
# Compatibility name for callers that imported the pre-#1974 constant. The
# canonical applicable/no-property path now means INCOMPLETE, not N/A.
RC_NOT_APPLICABLE = RC_INCOMPLETE
RC_ENV_UNAVAILABLE = 3
#: A ceiling stopped the proof. Deliberately NOT 1: "your design has a bug" and
#: "this host ran out of room" send the reader to different places.
RC_RESOURCE_INCONCLUSIVE = 4
#: The .sby was authored and NO proof was run. Deliberately NOT 0: an emit is
#: not a pass.
RC_EMIT_ONLY = 5

#: vibe-ic#628 — the share of host memory ONE solver process tree may address.
#: A bound on how much of the machine a disposable process may take, NOT a model
#: of what a proof needs: a formal property that fails to converge is the
#: EXPECTED behaviour of a solver on a hard instance, and the suite treated it as
#: if it were bounded. The runaway measured on a 125.7 GB host reached 109 GB;
#: at this share it would have been stopped near 31 GB with ~95 GB still free.
FORMAL_MEM_SHARE = 0.25
#: Never bound below this — a share of a small CI box must not make every proof
#: fail for want of memory, which is the same outage from the other end.
FORMAL_MEM_FLOOR_KB = 4 * 1024 * 1024


def memory_limit_kb(meminfo: Optional[str] = None,
                    env: Optional[Dict[str, str]] = None) -> Optional[int]:
    """Address-space bound (KiB) for the solver, or None when it cannot be
    derived — in which case NO limit is emitted and the transcript says so,
    rather than a guessed number being imposed.

    `VIBEIC_FORMAL_MEM_LIMIT_KB` overrides; `0` disables the bound explicitly,
    which is different from being unable to derive one and must stay sayable.
    """
    env = os.environ if env is None else env
    raw = str(env.get("VIBEIC_FORMAL_MEM_LIMIT_KB", "")).strip()
    if raw:
        try:
            v = int(raw)
        except ValueError:
            return None
        return None if v <= 0 else v
    text = meminfo
    if text is None:
        try:
            text = Path("/proc/meminfo").read_text(errors="replace")
        except OSError:
            return None
    m = re.search(r"^MemTotal:\s+(\d+)\s*kB", text or "", re.MULTILINE)
    if not m:
        return None
    return max(FORMAL_MEM_FLOOR_KB, int(int(m.group(1)) * FORMAL_MEM_SHARE))


# ── resource-ceiling classification (pure) ─────────────────────────────────
# "The proof did not converge" and "we ran out of a resource" are DIFFERENT
# facts, exactly as #216 separated "the engine was never reached" from "the
# proof was inconclusive". Collapsing them costs the reader the one thing that
# makes the result actionable: WHICH resource, and at what limit. A wall-clock
# stop is a budget question; an address-space stop is a host question; a
# non-converging solver is a design/property question. They have different fixes.
#
# Every signature below is a TOOL/RUNTIME output shape — the C++ runtime's
# allocation failure, glibc's, the kernel's signal report, or our own deadline
# note — never a chip, design or PDK literal, so the classification stays
# chip-AGNOSTIC.
_RESOURCE_STOP_SIGNATURES = (
    (re.compile(r"SOLVER DEADLINE|\bTIMEOUT after \d+s"), "wall_clock"),
    (re.compile(r"std::bad_alloc|\bbad_alloc\b|\bMemoryError\b|"
                r"[Cc]annot allocate memory|"
                r"virtual memory exhausted|[Oo]ut of memory|"
                r"memory allocation of \d+ bytes failed|"
                r"killed by signal 9|\bSIGKILL\b|^\s*Killed\s*$",
                re.MULTILINE), "memory"),
)

#: What each resource stop MEANS, so the record says it rather than assuming the
#: reader will infer it.
_RESOURCE_MEANING = {
    "wall_clock": ("the deadline expired while the solver was still working — "
                   "the properties may well hold and we simply did not finish"),
    "memory": ("the solver hit its address-space ceiling — the properties may "
               "well hold and we simply could not afford to find out here"),
}


def classify_resource_stop(transcript: str,
                           timeout_s: Optional[int] = None,
                           mem_limit_kb: Optional[int] = None
                           ) -> Optional[Dict[str, object]]:
    """Return a structured record when the run was stopped by a RESOURCE
    CEILING rather than by the solver reaching an answer, else None.

    Pure: transcript text in, dict out — no process is spawned, so the
    classification is unit-testable without a solver.

    The returned dict answers what a reader needs in order to act: WHICH
    resource ran out, at WHAT limit, what the tool actually said, and what the
    stop does and does not mean about the design.
    """
    text = transcript or ""
    for rx, resource in _RESOURCE_STOP_SIGNATURES:
        m = rx.search(text)
        if not m:
            continue
        if resource == "wall_clock":
            limit = int(timeout_s) if timeout_s is not None else None
            unit = "s"
        else:
            limit = int(mem_limit_kb) if mem_limit_kb else None
            unit = "KiB"
        return {
            "resource": resource,
            "limit": limit,
            "unit": unit,
            "tool_message": (m.group(0) or "").strip()[:300],
            "meaning": _RESOURCE_MEANING[resource],
        }
    return None


def apply_resource_stop(results: dict,
                        resource_stop: Optional[dict]) -> dict:
    """Fold a resource stop into the record, honestly. Pure (mutates + returns).

    Not a pass: nothing finished, so `all_proved` cannot stand. Not a fail
    either: the properties may well hold and we simply did not finish. The one
    thing a ceiling does NOT overturn is a real counterexample — a cex is sound
    evidence the moment it is found, so a FAIL survives a later stop rather than
    being laundered into "we ran out of time".

    `attempted` travels with it because the reader's next move is to raise the
    right ceiling, and they cannot pick one without knowing which tasks, modes
    and depths were dispatched.
    """
    if not resource_stop:
        return results
    results["resource_stop"] = resource_stop
    results["attempted"] = [
        {"task": p["task"], "mode": p["mode"], "depth": p["depth"],
         "engine": p["engine"], "status": p["status"]}
        for p in results.get("properties", [])]
    results["all_proved"] = False
    if results.get("verdict") != "FAIL":
        results["verdict"] = "INCONCLUSIVE"
    results.setdefault("bounded_vs_unbounded", []).append(
        f"RESOURCE CEILING: the run was stopped by its "
        f"{resource_stop['resource']} limit "
        f"({resource_stop['limit']} {resource_stop['unit']}) — "
        f"{resource_stop['meaning']}. Tool said: "
        f"{resource_stop['tool_message']}")
    return results


def local_bounded_argv(command: str,
                       mem_limit_kb: Optional[int]) -> List[str]:
    """The argv that runs `command` on THIS host under an address-space ceiling.

    The local twin of `_container_exec.container_deadline_argv`, and split out
    for the same reason: a test drives the argv the caller actually runs instead
    of re-typing it, and a re-typed argv agrees with the implementation only by
    coincidence — which is how this class of defect returns.

    `ulimit -v` is the FIRST thing in the shell line: set after the tool has
    started it bounds nothing, and the memory lives in the children. `exec`
    replaces the shell so the tool is our own direct child and a signal reaches
    it. When no limit can be derived NO `ulimit` is emitted at all — a guessed
    ceiling is one nobody can reason about, and too low is the same outage from
    the other end.
    """
    prefix = f"ulimit -v {int(mem_limit_kb)}; " if mem_limit_kb else ""
    return ["bash", "-lc", f"{prefix}exec {command}"]


# ── impure runner ──────────────────────────────────────────────────────────
def _kill_process_group(proc: "subprocess.Popen") -> None:
    """SIGTERM then SIGKILL the whole process GROUP.

    sby is a launcher; the memory and the cores live in the yosys it spawns.
    Signalling only the handle we hold leaves the solver running — the #623/#628
    shape in a third place, and the one that took a 125 GB host off the network.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:                       # already reaped
        proc.kill()
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except OSError:
            return
        try:
            proc.wait(timeout=_CE.DEFAULT_KILL_GRACE_S)
            return
        except subprocess.TimeoutExpired:
            continue


def _run_group_bounded(argv: List[str], cwd: Path,
                       timeout: int) -> "tuple":
    """Run `argv` in its OWN session so the deadline reaches the whole tree.

    Returns `(rc, combined_output)`. `rc == _CE.TIMEOUT_EXPIRED_RC` (124, the
    coreutils protocol the container path already speaks) means the deadline
    expired and the group was signalled; no orphan survives it.
    """
    proc = subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            errors="replace", start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out or ""
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        try:
            out, _ = proc.communicate(timeout=_CE.CLIENT_GRACE_S)
        except subprocess.TimeoutExpired:  # pragma: no cover - group is dead
            out = ""
        return _CE.TIMEOUT_EXPIRED_RC, out or ""


def _run_sby_ambient(name: str, formal_dir: Path, timeout: int,
                     mem_limit_kb: Optional[int]) -> str:
    """Run sby from the AMBIENT PATH under the SAME two bounds as the container.

    THE AMBIENT PATH IS NOT THE UNUSUAL ONE. It is the path taken whenever the
    caller ALREADY runs inside the vibeic-eda image — where `docker` is absent
    and `sby` is at /usr/local/bin/sby — which is how CI, the flow
    (`design_one_shot_runner` passes `container or None`) and every agent run
    it. It carried NO memory bound and only a CLIENT-side deadline, so an expiry
    killed the launcher we held while its yosys children carried on. MEASURED:
    two yosys reached 35.6 GB apiece on a 125 GB host, no log output for twelve
    minutes, MemAvailable falling ~2 GB per 20 s; the host stopped answering ssh.

    The bound was skipped here on the premise that "imposing a rlimit on the
    caller's own shell is not this function's business". It is not the caller's
    shell — it is a shell WE spawn, whose only child is the solver.
    """
    cmd = local_bounded_argv(f"sby -f {name}", mem_limit_kb)
    try:
        rc, out = _run_group_bounded(cmd, formal_dir, int(timeout))
    except FileNotFoundError:
        return "[formal_property_run] ERROR: sby/docker not found on PATH\n"
    if rc == _CE.TIMEOUT_EXPIRED_RC:
        # Named, because an anonymous death reads as a tool crash and sends the
        # reader to the wrong place.
        out += (f"\n[formal_property_run] SOLVER DEADLINE: the host-side "
                f"deadline stopped sby and its whole process group after "
                f"{int(timeout)}s. The proof is INCONCLUSIVE — not "
                f"disproved.\n")
    return out


def _run_sby(sby_path: Path, formal_dir: Path, container: Optional[str],
             timeout: int, mem_limit_kb: Optional[int] = None) -> str:
    """Run `sby -f <sby>` in `formal_dir` and return the transcript. When
    `container` is set the run is `docker exec <container>` with the vibeic-eda
    tool PATH; otherwise sby is invoked from the ambient PATH. BOTH paths carry
    an address-space ceiling and a deadline that reaches the solver.

    `mem_limit_kb` is the caller's explicit ceiling; `None` derives one from the
    host (`memory_limit_kb`), and `0` is an explicit, sayable "do not bound".
    """
    name = sby_path.name
    _lim = mem_limit_kb if mem_limit_kb is not None else memory_limit_kb()
    if not container:
        return _run_sby_ambient(name, formal_dir, timeout, _lim)
    path_export = ("export PATH=/foss/tools/bin:/foss/tools/yosys/bin:"
                   "$PATH")
    # vibe-ic#628 — BOUND THE SOLVER, NOT THE CLIENT. This was
    # `docker exec` under a client-side `subprocess.run(timeout=)`, which
    # is the #623 defect in a second place: the deadline killed the local
    # client while sby's yosys carried on inside the container, unsignalled
    # and unwatched. MEASURED on a 125.7 GB host: one such yosys reached
    # 109 GB RSS, still climbing at ~1 GB per 20 s, with MemAvailable at
    # 3.2 GB and swap exhausted — about a minute from the OOM killer, on a
    # machine also running four production services. Killing that one
    # process returned MemAvailable 3.2 GB -> 113.0 GB.
    #
    # Two bounds, because they stop different things:
    #   * the deadline moves INSIDE the container (coreutils `timeout`, the
    #     `_container_exec` primitive) so an expiry actually reaches the
    #     solver;
    #   * `ulimit -v` bounds ADDRESS SPACE for sby and every child it
    #     spawns — a process may lower its own rlimit but never raise it,
    #     so yosys cannot escape it. A deadline alone does not help a
    #     solver that eats the host in less time than its budget.
    _ul = f"ulimit -v {_lim}; " if _lim else ""
    inner = (f"{_ul}{path_export}; cd {formal_dir} && rm -rf {sby_path.stem} "
             f"&& sby -f {name}")
    cmd = ["docker", "exec", container,
           "timeout", "-k", str(_CE.DEFAULT_KILL_GRACE_S), str(int(timeout)),
           "bash", "-lc", inner]
    timeout = int(timeout) + _CE.CLIENT_GRACE_S
    try:
        p = _pr.run(cmd, cwd=str(formal_dir), capture_output=True,
                           text=True)
        out = (p.stdout or "") + (p.stderr or "")
        if container and p.returncode == 124:
            # The CONTAINER-side deadline fired, so the solver was signalled
            # where it lives. Named, because an anonymous death reads as a
            # tool crash and sends the reader to the wrong place.
            out += (f"\n[formal_property_run] SOLVER DEADLINE: the "
                    f"container-side `timeout` stopped sby after {timeout - _CE.CLIENT_GRACE_S}s. "
                    f"The proof is INCONCLUSIVE — not disproved.\n")
        return out
    except _pr.Stalled as e:
        out = e.stdout or ""
        err = e.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return out + err + (f"\n[formal_property_run] SOLVER STALLED: every "
                            f"progress signal sat still, so it was killed as "
                            f"hung. The proof is INCONCLUSIVE — not "
                            f"disproved. {e}\n")
    except FileNotFoundError:
        return "[formal_property_run] ERROR: sby/docker not found on PATH\n"


def _write_authoring_incomplete(formal_dir: Path, reason: str) -> None:
    """Record applicable-but-unauthored work. Silence is never inapplicable."""
    (formal_dir / "formal_authoring_request.json").write_text(json.dumps({
        "verdict": "INCOMPLETE",
        "program": "formal_property_run",
        "fallback_skill": "formal-verify",
        "invocation_status": "REQUIRED_NOT_INVOKED",
        "property_denominator": 1,
        "authored_property_count": 0,
        "unresolved_obligations": [{
            "id": "formal.property_missing",
            "layer": "L3/L6/L8",
            "description": reason,
            "status": "UNAUTHORED",
            "author": "formal-verify",
        }],
        "reason": reason,
    }, indent=2, ensure_ascii=False) + "\n")


def _assertion_count(path: Optional[Path]) -> int:
    """Count actual asserted properties in the authored harness."""
    if path is None or not path.is_file():
        return 0
    text = re.sub(r"/\*.*?\*/", " ", path.read_text(errors="replace"),
                  flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return len(re.findall(r"\bassert\s*(?:property\s*)?\(", text))


def _attach_property_contract(results: dict, formal_dir: Path,
                              harness: Optional[Path]) -> None:
    """Attach the auditable declaration/property denominator to a real run.

    A hand-authored harness with no manifest gets a denominator derived from
    its actual assertions. The in-flow generator writes `property_contract.json`
    with all remaining L3/L6/L8 obligations, which takes precedence.
    """
    actual = _assertion_count(harness)
    manifest_path = formal_dir / "property_contract.json"
    contract: dict = {}
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(errors="replace"))
            if isinstance(loaded, dict):
                contract = loaded
        except (OSError, ValueError):
            contract = {}
    request_floor = 0
    request_obligations: List[dict] = []
    request_path = formal_dir / "formal_authoring_request.json"
    if request_path.is_file():
        try:
            request = json.loads(request_path.read_text(errors="replace"))
            request_floor = int(request.get("property_denominator", 0))
            request_obligations = [
                row for row in (request.get("unresolved_obligations") or [])
                if isinstance(row, dict) and str(row.get("id", "")).strip()
            ]
        except (OSError, ValueError, TypeError):
            request_floor = 0
    unresolved = list(contract.get("unresolved_obligations") or [])
    try:
        denominator = int(contract.get("property_denominator", actual))
    except (TypeError, ValueError):
        denominator = actual
    # The request is the pre-expert snapshot. An expert may close obligations;
    # it may not shrink the denominator to make them disappear.
    denominator = max(denominator, request_floor, actual)
    covered = max(0, denominator - len(unresolved))
    if actual < covered:
        unresolved.append({
            "id": "formal.authored_property_count_mismatch",
            "layer": "formal",
            "description": (f"contract claims {covered} covered obligation(s) "
                            f"but harness contains {actual} assert statement(s)"),
            "status": "UNAUTHORED",
            "author": "formal-verify",
        })
    # A request is proof that the deterministic floor handed work to the
    # expert. Completion therefore needs a receipt, not merely prose saying a
    # fallback exists. The receipt cannot close an obligation by omission: it
    # must carry one disposition per immutable request ID, and AUTHORED rows
    # must name the actual property that discharges them.
    receipt_path = formal_dir / "formal_expert_review.json"
    receipt: dict = {}
    if receipt_path.is_file():
        try:
            loaded = json.loads(receipt_path.read_text(errors="replace"))
            if isinstance(loaded, dict):
                receipt = loaded
        except (OSError, ValueError):
            receipt = {}
    dispositions = {
        str(row.get("id")): row
        for row in (receipt.get("dispositions") or [])
        if isinstance(row, dict) and str(row.get("id", "")).strip()
    }
    expert_invoked = bool(
        request_obligations
        and str(receipt.get("invocation_status", "")).upper() == "INVOKED")
    receipt_unresolved: List[dict] = []
    for requested in request_obligations:
        oid = str(requested["id"])
        disposition = dispositions.get(oid) if expert_invoked else None
        status = str((disposition or {}).get("status", "")).upper()
        prop = str((disposition or {}).get("property", "")).strip()
        if status == "AUTHORED" and prop:
            continue
        row = dict(requested)
        row["status"] = status or "EXPERT_NOT_REVIEWED"
        if disposition and disposition.get("reason"):
            row["description"] = str(disposition["reason"])
        receipt_unresolved.append(row)
    by_id = {
        str(row.get("id", f"unnamed.{idx}")): row
        for idx, row in enumerate(unresolved + receipt_unresolved)
        if isinstance(row, dict)
    }
    unresolved = list(by_id.values())

    results["property_denominator"] = denominator
    results["authored_property_count"] = actual
    results["covered_property_count"] = min(
        actual, max(0, denominator - len(unresolved)))
    results["unresolved_obligations"] = unresolved
    results["expert_fallback_required"] = bool(request_obligations)
    results["expert_fallback_invoked"] = expert_invoked
    results["expert_fallback_receipt"] = (
        str(receipt_path.relative_to(formal_dir.parent.parent.parent))
        if expert_invoked else None)
    results["property_contract"] = (
        str(manifest_path.relative_to(formal_dir.parent.parent.parent))
        if manifest_path.is_file() else "derived from authored harness assertions")
    results["elaborated_sby"] = results.get("sby")
    results["proof_transcript"] = results.get("evidence")
    results["bounded_vs_unbounded_scope"] = list(
        results.get("bounded_vs_unbounded") or [])
    if unresolved and results.get("verdict") == "PASS":
        results["proof_verdict"] = "PASS"
        results["verdict"] = "INCOMPLETE"
        results["formal_completion"] = "INCOMPLETE"
    else:
        results["formal_completion"] = results.get("verdict")


def run(project: Path, harness: Optional[Path] = None,
        rtl: Optional[List[Path]] = None, top: Optional[str] = None,
        sby: Optional[Path] = None, container: Optional[str] = "vibeic-eda",
        bmc_depth: int = 12, safety_depth: int = 20,
        timeout: int = 900,
        invariant_harness: Optional[Path] = None,
        engine_backend: str = "auto",
        mem_limit_kb: Optional[int] = None,
        emit_only: bool = False) -> dict:
    """Author the .sby, run the proof, and record an HONEST verdict.

    `timeout` and `mem_limit_kb` are the RESOURCE CEILING the caller grants this
    proof. `mem_limit_kb=None` derives an address-space ceiling from the host;
    `0` is an explicit, sayable "do not bound". A run either ceiling stops comes
    back INCONCLUSIVE, carrying `resource_stop` (which resource, what limit,
    what the tool said) and `attempted` (the tasks that were dispatched) — never
    PASS, because nothing was proved, and never FAIL, because nothing was
    refuted.

    `emit_only=True` STOPS AFTER THE EMIT. The .sby is authored and its sources
    are staged, and the function returns before any executor exists: no engine
    is probed, no solver is launched, and no `results.json` is written. This is
    the entry point for a caller that wants the ARTEFACT and explicitly does not
    want the proof — a dry run, or a test asserting what ends up on the
    `read_verilog` line. It exists because the alternative such callers relied on
    was the ACCIDENT that the tool would not be found, which is false in the
    image the flow is designed for: inside vibeic-eda `sby` IS on PATH, so "it
    will just fail to launch" launched a real proof.
    """
    formal_dir = _pl.formal_dir(project)
    formal_dir.mkdir(parents=True, exist_ok=True)

    # An emit-only run probes NOTHING: engine availability is evidence about an
    # environment we are not going to use, and probing it would spawn the one
    # kind of thing this mode promises not to spawn.
    engine_availability = {} if emit_only else detect_engines(container)
    engine_note = None

    # An invariant-strengthened harness may be passed explicitly via
    # `invariant_harness`, or auto-detected: a plain `--harness` that carries
    # `@invariant-harness` / `@connect` pragmas is routed here too.
    inv_h = invariant_harness
    if inv_h is None and harness is not None and harness.is_file():
        if parse_harness_pragmas(harness.read_text())["is_invariant"]:
            inv_h = harness

    # 1) locate/emit the .sby + stage sources into formal/ ------------------
    sby_path: Optional[Path] = None
    if inv_h is not None and inv_h.is_file():
        # ---- invariant-strengthened (auxiliary-invariant) datapath proof ----
        if not rtl or top is None:
            return {"verdict": "ERROR", "rc": 1,
                    "reason": "invariant harness needs --rtl/--top"}
        prags = parse_harness_pragmas(inv_h.read_text())
        # `abc pdr` is the ONLY unbounded engine SymbiYosys can drive in `mode
        # prove`. A stronger OSS datapath engine (btormc/pono over BTOR2 via
        # `--kind`, or AMulet2 on a combinational multiplier netlist) is NOT
        # sby-prove-drivable — it needs a direct `write_btor -> btormc --kind`
        # (or AMulet) invocation. We therefore NEVER substitute it as an sby
        # prove engine (that would emit an invalid .sby: sby's btor backend is
        # bmc/cover-only). We keep abc pdr and record the request + honest
        # availability + note so the gap is disclosed, never faked.
        prove_engine = "abc pdr"
        engine_note = None
        if engine_backend in ("btor", "btormc", "amulet"):
            have = (engine_availability.get("btormc")
                    or engine_availability.get("pono")
                    or engine_availability.get("amulet2"))
            engine_note = (
                "requested stronger datapath engine "
                f"'{engine_backend}'; it is "
                + ("PRESENT but not sby-prove-drivable (btor backend is "
                   "bmc/cover-only; run write_btor -> btormc --kind directly)"
                   if have else
                   "ABSENT (btormc/pono/amulet2 not on PATH)")
                + " — kept abc pdr for the sby prove task; no proof fabricated")
        staged_rtl = []
        for r in rtl:
            dst = formal_dir / r.name
            if r.resolve() != dst.resolve():
                shutil.copy2(r, dst)
            staged_rtl.append(r.name)
        hdst = formal_dir / inv_h.name
        if inv_h.resolve() != hdst.resolve():
            shutil.copy2(inv_h, hdst)
        sby_text = emit_invariant_sby(
            staged_rtl, inv_h.name, top, prags["connects"], prags["chparams"],
            tasks=prags.get("tasks"),
            prove_engine=prove_engine, prove_depth=max(40, safety_depth),
            bmc_depth=bmc_depth)
        sby_path = formal_dir / f"{top}_inductive.sby"
        sby_path.write_text(sby_text)
    elif sby is not None and sby.is_file():
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
            _write_authoring_incomplete(
                formal_dir,
                "no formal property harness authored for this design — "
                "formal-verify must author formal_<top>.sv from the unresolved "
                "L3/L6/L8 declaration IDs before a proof can run; no proof "
                "was fabricated")
            return {"verdict": "INCOMPLETE", "rc": 2,
                    "reason": "applicable property harness not authored",
                    "fallback_skill": "formal-verify"}
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
        # An INCLUDE-HUB AGGREGATOR (a source whose body `include`s SIBLING
        # sources that are ALSO staged standalone) must not be handed to
        # `read_verilog` next to the files it includes: every included module
        # is then elaborated twice and yosys ABORTS with
        #     ERROR: Re-definition of module `\<name>'
        # before any engine starts. sby reports rc=16 / "did not return a
        # status" for every task, the step finds no clean proof and
        # self-reports a FORMAL capability gap it does not actually have.
        # Measured on caravel_user_project: `uprj_netlists.v` includes
        # `user_project_wrapper.v` and `user_proj_example.v`, which the file
        # list also carries standalone.
        # Same predicate `_rtl_include_hub` that phase-2 synth, the LEC gold
        # read and phase-3 synth already apply, so the selectors cannot drift.
        # FAIL-OPEN in both directions: an unreadable file is not a hub, and
        # if the filter would empty the list the unfiltered list is kept.
        _sibs = {r.name for r in rtl}
        _hubs = {r.name for r in rtl if _hub.is_include_hub(r, _sibs)}
        _kept = [n for n in staged_rtl if n not in _hubs]
        if _kept:
            staged_rtl = _kept
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

    # 1b) EMIT-ONLY — the artefact is written; the proof is NOT run ---------
    # Returns BEFORE the executor is reached, so the guarantee is structural
    # rather than environmental: there is no code path from here to a solver,
    # whatever tools happen to be installed. Nothing that resembles proof
    # evidence is written — the .sby is the whole artefact — so an emit-only run
    # can never be mistaken downstream for a proof that ran.
    if emit_only:
        return {
            "program": "formal_property_run",
            "verdict": "EMIT_ONLY",
            "all_proved": False,
            "property_count": 0,
            "properties": [],
            "sby": str(sby_path.relative_to(project)),
            "reason": ("emit-only: the .sby was authored and its sources "
                       "staged; NO proof engine was invoked, so NOTHING was "
                       "proved and NOTHING was refuted"),
            "rc": RC_EMIT_ONLY,
        }

    # 2) run sby -------------------------------------------------------------
    eff_mem_kb = (mem_limit_kb if mem_limit_kb is not None
                  else memory_limit_kb())
    transcript = _run_sby(sby_path, formal_dir, container, timeout,
                          mem_limit_kb=eff_mem_kb)
    log_path = formal_dir / f"{sby_path.stem}.sby.log"
    log_path.write_text(transcript)

    # 2b) #216 — the proof ENGINE was never reached ---------------------------
    # Distinguished from an inconclusive proof: nothing ran, so there is no
    # proof strength to report and no property row to emit. We write an
    # ENV_UNAVAILABLE manifest that NAMES the missing capability, WHERE the
    # flow looked, and the REMEDY, so the gap is actionable instead of a dead
    # end. This is strictly NOT greener: `all_proved` stays False, no
    # `results.json` proof artifact is produced, so Step 5's required outputs
    # remain absent and the gate still refuses to pass.
    env_gap = classify_env_gap(transcript, container)
    if env_gap is not None:
        env_manifest = {
            "program": "formal_property_run",
            "verdict": "ENV_UNAVAILABLE",
            "all_proved": False,
            "property_count": 0,
            "properties": [],
            "fallback_skill": "formal-verify",
            "env_gap": env_gap,
            "reason": (
                f"formal proof engine unreachable: "
                f"{env_gap['missing_capability']} not available at "
                f"{env_gap['searched']} — {env_gap['remedy']}. "
                f"Tool said: {env_gap['tool_message']}. "
                f"NOTHING was proved and nothing was refuted; this is an "
                f"ENVIRONMENT gap, not a design defect and not an "
                f"inconclusive proof."
            ),
            "sby": str(sby_path.relative_to(project)),
            "evidence": str(log_path.relative_to(project)),
            "engine_availability": engine_availability,
        }
        # Written under its OWN name — never `results.json`, which is the
        # proof-evidence artifact the Step-5 gate consumes. A run that never
        # reached the engine must not leave anything that looks like a proof.
        (formal_dir / "formal_env_unavailable.json").write_text(
            json.dumps(env_manifest, indent=2, ensure_ascii=False) + "\n")
        _write_env_gap_report(formal_dir, env_manifest)
        env_manifest["rc"] = RC_ENV_UNAVAILABLE
        return env_manifest

    # 3) parse + build results ----------------------------------------------
    cfg = parse_sby_config(sby_path.read_text())
    lp = parse_sby_log(transcript, sby_stem=sby_path.stem, seed=cfg)
    top_name = top or sby_path.stem
    ev_rel = str(log_path.relative_to(project))
    sby_rel = str(sby_path.relative_to(project))
    results = build_results(top_name, cfg, lp, ev_rel, sby_rel)
    _attach_property_contract(results, formal_dir, harness or inv_h)
    results["mode"] = ("invariant-strengthened"
                       if inv_h is not None else "standard")
    # HONEST engine record: which stronger OSS datapath engines were available,
    # and which was actually used. `abc pdr` is the in-container unbounded
    # engine; btormc/pono/amulet2 are optional forks (absent -> disclosed, not
    # faked). engine_backend records the REQUEST; the per-task `engine` field
    # (in properties[]) records what genuinely ran.
    results["engine_backend_requested"] = engine_backend
    results["engine_availability"] = engine_availability
    if engine_note:
        results["engine_note"] = engine_note

    # 3b) DID A RESOURCE CEILING STOP THE PROOF? (see `apply_resource_stop`)
    resource_stop = classify_resource_stop(transcript, timeout, eff_mem_kb)
    apply_resource_stop(results, resource_stop)
    # EXECUTED honesty guard, and DELIBERATELY SEPARATE from the function that
    # is supposed to keep the rule. `apply_resource_stop` is where a future
    # change would land — a new verdict name, a "PARTIAL is nicer here" tweak,
    # a refactor that reorders the fields — and a rule enforced only by the code
    # that could break it is enforced by nothing. This line re-derives the one
    # question that matters from the record as it FINALLY stands.
    assert_resource_honesty(results, resource_stop)
    # The invariant-strengthened proof is a SUPPLEMENTARY datapath-formal
    # attempt: it writes to its OWN results file so it can never clobber the
    # canonical `results.json` that the Step-5 evidence gate consumes (a wide
    # datapath prove may honestly not converge; that must not turn the flow's
    # existing PASS into a FAIL). The standard path keeps writing results.json.
    results_name = ("results.json" if inv_h is None
                    else f"{top_name}_inductive_results.json")
    if (inv_h is None and results["property_count"]
            and not results.get("unresolved_obligations")):
        # A real proof ran: results.json is now the canonical artifact, so a
        # stale `formal_not_run.json` skip-sentinel (from an earlier chain
        # where no proof ran) must not linger and contradict it.
        stale = formal_dir / "formal_not_run.json"
        if stale.is_file():
            stale.unlink()
        stale_request = formal_dir / "formal_authoring_request.json"
        if stale_request.is_file():
            stale_request.unlink()
    (formal_dir / results_name).write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    results["results_file"] = results_name

    # 4) human report --------------------------------------------------------
    _write_report(formal_dir, results)

    rc = (RC_ALL_PROVED
          if results["all_proved"] and not results.get("unresolved_obligations")
          else (
        RC_INCOMPLETE if results["verdict"] in
        ("SKIPPED-CONDITION", "INCOMPLETE") else
        RC_RESOURCE_INCONCLUSIVE if resource_stop else RC_PROPERTY_FAILED))
    results["rc"] = rc
    return results


def _write_env_gap_report(formal_dir: Path, manifest: dict) -> None:
    """#216 — the human-readable face of an ENV_UNAVAILABLE formal step.

    Answers the three questions that make an environment gap actionable:
    what capability is missing, where the flow looked for it, and what to
    install or stage. `ENV_UNAVAILABLE` with no detail is a dead end for
    whoever has to fix the host.
    """
    gap = manifest.get("env_gap") or {}
    lines = [
        "# Formal proof — ENVIRONMENT UNAVAILABLE",
        "",
        "**No proof ran.** The formal engine was never reached, so there is "
        "no proof result — neither a pass nor a counterexample.",
        "",
        "| what | value |",
        "|------|-------|",
        f"| missing capability | `{gap.get('missing_capability', '?')}` |",
        f"| where the flow looked | `{gap.get('searched', '?')}` |",
        f"| tool message | `{gap.get('tool_message', '?')}` |",
        "",
        "## Remedy",
        "",
        str(gap.get("remedy", "?")),
        "",
        "## Why this is not a proof verdict",
        "",
        "- `all_proved` is **false** and no `results.json` was written — "
        "Step 5's proof evidence is absent, so the gate still refuses to "
        "pass this step.",
        "- This state is NOT `INCONCLUSIVE`: an inconclusive result means "
        "the solver ran and did not converge. Here the solver never started.",
        "- Waiving this step requires a reviewed `waivers.json` entry with a "
        "ticket and `review_required: true`. A waiver is OPEN WORK, never a "
        "pass, and it never satisfies a downstream step that genuinely "
        "depends on formal results.",
    ]
    (formal_dir / "formal_env_unavailable.md").write_text(
        "\n".join(lines) + "\n")


def _write_report(formal_dir: Path, results: dict) -> None:
    lines = [f"# Formal proof report — {results['top']}", "",
             f"verdict: **{results['verdict']}**  "
             f"(all_proved={results['all_proved']}, "
             f"{results['proved']}/{results['property_count']} tasks PASS)",
             f"property denominator: **{results.get('property_denominator', '?')}**; "
             f"authored: **{results.get('authored_property_count', '?')}**; "
             f"unresolved: **{len(results.get('unresolved_obligations') or [])}**",
             "",
             "| task | mode | engine | depth | status | strength | cex frame |",
             "|------|------|--------|-------|--------|----------|-----------|"]
    if results.get("expert_fallback_required"):
        lines[4:4] = [
            f"expert fallback invoked: **{results.get('expert_fallback_invoked')}**; "
            f"receipt: `{results.get('expert_fallback_receipt') or 'missing'}`",
        ]
    for p in results["properties"]:
        lines.append(
            f"| {p['task']} | {p['mode']} | {p['engine']} | "
            f"{p['depth']} | {p['status']} | {p['bound']} | "
            f"{p['cex_frame'] if p['cex_frame'] is not None else ''} |")
    strength = results.get("proof_strength", "?")
    lines += ["", f"proof strength: **{strength}** "
              f"(unbounded_proved={results.get('unbounded_proved')})"]
    stop = results.get("resource_stop")
    if stop:
        lines += ["", "## Stopped by a resource ceiling",
                  f"- resource: **{stop['resource']}**  "
                  f"limit: **{stop['limit']} {stop['unit']}**",
                  f"- {stop['meaning']}",
                  f"- tool said: `{stop['tool_message']}`",
                  "- This is **INCONCLUSIVE**: nothing was proved and nothing "
                  "was refuted. Raise the ceiling and re-run, or accept the "
                  "bounded result that was reached — do not read it as a pass."]
    lines += ["", "## Bounded vs unbounded disclosure"]
    for d in results["bounded_vs_unbounded"]:
        lines.append(f"- {d}")
    unresolved = results.get("unresolved_obligations") or []
    if unresolved:
        lines += ["", "## Unresolved declaration/property obligations",
                  "", "Invoke `formal-verify`; Step 5 remains INCOMPLETE."]
        for row in unresolved:
            lines.append(
                f"- `{row.get('id', '?')}` ({row.get('layer', '?')}): "
                f"{row.get('description', 'property not authored')}")
    avail = results.get("engine_availability")
    if avail:
        present = sorted(k for k, v in avail.items() if v)
        absent = sorted(k for k, v in avail.items() if not v)
        lines += ["", "## Engine availability (honest)",
                  f"- present: {', '.join(present) if present else '(none)'}",
                  f"- absent : {', '.join(absent) if absent else '(none)'}"]
    lines += ["", f"Evidence transcript: `{results['evidence']}`",
              f"SymbiYosys task file: `{results['sby']}`", ""]
    suffix = ("_inductive_report.md"
              if results.get("mode") == "invariant-strengthened"
              else "_report.md")
    (formal_dir / f"{results['top']}{suffix}").write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# vibe-ic#562 — RE-ADJUDICATION RULES for this gate's published records.
#
# A published record can describe a state that no longer exists. For a formal
# run the dangerous drift is the PROOF STRENGTH: `unbounded_proved` means "holds
# for all reachable states", while a bounded BMC result only means "no
# counterexample within the bound". A record carrying PASS on the strength of a
# bounded proof is a record whose verdict a reader will over-trust, and the
# distinction is exactly what `assert_bound_honesty` guards at run time.
#
# `_STRENGTH_HONESTY` re-derives that one question from what the record itself
# publishes, so an old record is judged by today's rule rather than by the words
# it was written with.
import _record_adjudication as _ra  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402


def _strength_honesty(record: dict):
    """Would this gate still call this a PASS on the strength it recorded?"""
    verdict = record.get("verdict")
    if verdict != "PASS":
        return None                      # only a PASS can over-claim
    unbounded = bool(record.get("unbounded_proved"))
    if unbounded:
        return None                      # a real unbounded proof still stands
    return _ra.Supersession(
        would_issue="PARTIAL",
        because=("the record carries verdict PASS with unbounded_proved false, "
                 "so every property it proved was proved BOUNDED — no "
                 "counterexample within a bound, which is not a proof for all "
                 "reachable states. Today's rule reserves PASS for a run whose "
                 "properties all PASSED and discloses a bounded-only result as "
                 "PARTIAL; a reader taking this PASS as a full proof would be "
                 "over-trusting it"),
    )


RECORD_ADJUDICATION = _ra.declare(
    __file__,
    gate="formal_property_run",
    # The entry point of the verdict decision; the fingerprint follows the
    # module-local call closure from here, so `proof_strength` and
    # `assert_bound_honesty` are covered without being listed.
    decision_roots=("build_results",),
    # Regenerate with:
    #   python3 published_record_staleness_check.py \
    #       --print-decision-digest formal_property_run
    decision_digest="bfe3ec44467f0d8bebdabc306902e4a68bfc69592a3ca81b5ec34d355c7575ff",
    rules=(
        _ra.Rule(
            rule_id="formal_property_run.bounded-is-not-a-proof",
            landed_in="#562",
            requires=("verdict", "unbounded_proved"),
            decide=_strength_honesty,
            what=("a PASS whose properties were all proved BOUNDED claims more "
                  "than a bounded result supports; PARTIAL is the honest verdict"),
        ),
    ),
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--harness", type=Path, default=None,
                    help="authored formal_<top>.sv property harness")
    ap.add_argument("--invariant-harness", type=Path, default=None,
                    dest="invariant_harness",
                    help="strengthened auxiliary-invariant harness reaching "
                         "internal state (with @connect pragmas) for an "
                         "UNBOUNDED datapath proof")
    ap.add_argument("--engine-backend", default="auto", dest="engine_backend",
                    choices=["auto", "abc", "btor", "btormc", "amulet"],
                    help="stronger datapath engine to prefer when present "
                         "(absent engines are disclosed, never faked)")
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
    ap.add_argument("--mem-limit-kb", type=int, default=None,
                    dest="mem_limit_kb",
                    help="address-space ceiling (KiB) for the solver and every "
                         "child it spawns; omit to derive one from this host, "
                         "0 to run unbounded on purpose")
    ap.add_argument("--emit-only", action="store_true", dest="emit_only",
                    help="author the .sby and stage its sources, then STOP — "
                         "no proof is run, nothing is proved or refuted")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"ERROR: not a directory: {args.project_dir}", file=sys.stderr)
        return 1
    res = run(args.project_dir.resolve(), harness=args.harness, rtl=args.rtl,
              top=args.top, sby=args.sby,
              container=(args.container or None),
              bmc_depth=args.bmc_depth, safety_depth=args.safety_depth,
              timeout=args.timeout,
              invariant_harness=args.invariant_harness,
              engine_backend=args.engine_backend,
              mem_limit_kb=args.mem_limit_kb,
              emit_only=args.emit_only)
    rc = res.pop("rc", 0)
    out = json.dumps(res, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
