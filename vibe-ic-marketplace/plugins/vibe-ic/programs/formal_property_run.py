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
import json
import re
import shutil
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import _container_exec as _CE  # vibe-ic#628 — bound the solver, not the client

sys.path.insert(0, str(Path(__file__).parent))
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated
import _container_exec as _ce  # noqa: E402 — the ONE guarded docker-exec argv
import _path_layout as _pl  # noqa: E402
import _rtl_include_hub as _hub  # noqa: E402  (include-hub aggregator predicate)
import _atomic_artefact as _aa  # noqa: E402  (vibe-ic#1082)

# ── SBY transcript signatures (tool-output shapes, not chip literals) ──────
# A multi-task run tags every line with `[<sby>_<task>]`; a single-task run
# tags `[<sby>]`.
_LINE_RE = re.compile(r"\[(?P<task>[^\]]+)\]\s+(?P<rest>.*)$")
_DONE_RE = re.compile(r"DONE \((?P<status>PASS|FAIL|ERROR|UNKNOWN|TIMEOUT)",
                      re.IGNORECASE)
_SUMMARY_RET_RE = re.compile(
    r"summary:\s*(?:engine_\d+\s*\([^)]*\)\s*returned|Status:)\s*"
    r"(?P<status>PASS|FAIL|ERROR|UNKNOWN|TIMEOUT)\b"
    # A k-induction engine (`smtbmc` in `mode prove`) reports its two HALVES
    # separately — `returned pass for basecase`, then `returned FAIL for
    # induction` — and only the task's `DONE (...)` line is the verdict. A
    # basecase pass is a BOUNDED result; read as the task status it would turn
    # a transcript cut before `DONE` into an unbounded proof. MEASURED in the
    # released image (SBY v0.67-31-g2c2f04e): an 8-bit counter wrapping at 50
    # with `assert(q != 200)` gives `pass for basecase`, `FAIL for induction`,
    # `DONE (UNKNOWN, rc=4)`.
    r"(?!\s+for\s+(?:basecase|induction))", re.IGNORECASE)
#: `summary: Elapsed clock time [H:MM:SS (secs)]: 0:00:03 (3)` — per task.
_ELAPSED_RE = re.compile(
    r"summary:\s*Elapsed clock time \[H:MM:SS \(secs\)\]:\s*\S+\s*\((?P<secs>\d+)\)",
    re.IGNORECASE)
_ENGINE_RE = re.compile(r"engine_\d+:\s*(?P<engine>abc\s+\w+|smtbmc.*|btor.*|"
                        r"aiger.*)$", re.IGNORECASE)
_CEX_FRAME_RE = re.compile(r"asserted in frame (?P<frame>\d+)", re.IGNORECASE)
# THE GUARD THAT MEANS "the engine has spoken". `\bSBY\b` used to be enough,
# and that was the defect: this program's OWN diagnostic — "sby/docker not
# found on PATH" — contains the word `sby`, so the guard fired on the very
# message that says the engine was never found. `classify_env_gap` then
# returned None for every unreachable environment and the run fell through to
# a fabricated INCONCLUSIVE `results.json` with one UNKNOWN row per configured
# task — the exact #216 shape this file exists to prevent, reopened by a word
# boundary. MEASURED inside the pinned vibeic-eda image (no docker CLI):
# `classify_env_gap` -> None, results.json written, gate said NO_PROOF_CLAIM.
#
# A signature must therefore be a shape ONLY the engine emits: sby's own
# log-line prefix `SBY hh:mm:ss [task]`, an `engine_N` line, or a solver name.
# The bare token `sby` is a word anyone may say, this program included.
_SBY_SIG_RE = re.compile(r"SBY\s+\d{1,2}:\d{2}:\d{2}|symbiyosys|smtbmc"
                         r"|engine_\d", re.IGNORECASE)

#: Lines THIS program wrote into the transcript. They are the runner's voice,
#: never the engine's, so they can never be evidence that the engine spoke.
_RUNNER_VOICE_RE = re.compile(r"^\s*\[formal_property_run\].*$", re.MULTILINE)

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
    # ORDER MATTERS, most specific first. A container was NAMED and the
    # `docker` CLI through which we would reach it is absent — this host has
    # no such container because it has no containers. The generic docker-daemon
    # signature below would also match the phrase and would then hand out
    # `docker start` as the whole remedy, which is not actionable on a host
    # with no docker CLI; requiring the "CLI is not on PATH" clause means only
    # THIS program's own line can match here, never a real daemon reply.
    # `[^\n]*` to the end of the line, so `tool_message` carries the WHOLE
    # runner line — claim AND reason — rather than a prefix ending at the
    # container name. A truncated tool message is a diagnosis the reader
    # cannot check, and a bare "No such container" with the reason cut off
    # would read as a docker reply.
    (re.compile(r"No such container:\s*'(?P<detail>[^']+)'[^\n]*"
                r"docker`? CLI is not on PATH[^\n]*", re.IGNORECASE),
     "docker container",
     "the EDA container named {searched_container!r} is not running here — "
     "the `docker` CLI is not on PATH, so nothing on this host can reach or "
     "start it. Run this step on a host with Docker and the container up "
     "(docker start {searched_container!r}), or pass --container '' to invoke "
     "sby from the ambient PATH — our SymbiYosys fork ships in the vibeic-eda "
     "image at /usr/local/bin/sby"),
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


# ── the frontend split, and the retry that closes it ───────────────────────
# `read_verilog -sv` is yosys's own SystemVerilog frontend, and it does not
# accept a package import in a MODULE HEADER — `module m import p::*; #(...)`,
# which is how the OpenTitan sources are written. MEASURED on opentitan_aes,
# plugin v1.15.66:
#
#     base: aes.sv:10: ERROR: syntax error, unexpected TOK_IMPORT
#     base: task failed. ERROR.
#     DONE (ERROR, rc=16) ... engine_0 did not return a status
#
# Both tasks died before an engine started, and the step then reported a
# FORMAL capability gap the host did not have: `read_slang`, the full SV-2017
# frontend, was installed the whole time and phase-2 synth was reading the
# SAME sources through it. `lec_run` already re-reads its gold with
# `read_slang` on this signature family; this is the same fallback for the
# proof.
#
# The two frontends are COMPLEMENTARY, not ranked, which is why this is a
# retry and not a new default:
#   * `read_verilog -sv` accepts SVA and rejects those sources;
#   * `read_slang` elaborates those sources and refuses SVA
#     ("SVA unsupported"), so the harness is re-emitted in the equivalent
#     IMMEDIATE assertion form for that arm.
# A design that parses today keeps a byte-identical .sby, its concurrent
# properties, and its verdict.
_FRONTEND_ABORT_RE = re.compile(
    r"unexpected TOK_IMPORT|unexpected TOK_PACKAGE|unexpected TOK_TYPEDEF"
    r"|unexpected ':'|Executing Verilog-2005 frontend"
    r"|ERROR: syntax error, unexpected")


def frontend_aborted_the_read(transcript: str) -> bool:
    """True when the sby transcript shows the READ failed on a construct a
    full SV-2017 frontend accepts — never merely that a proof did not close.

    Both conditions are required, so an inconclusive PROOF can never be
    re-run as if it were a parse problem: a yosys frontend error signature,
    AND no engine having returned a status."""
    if not transcript:
        return False
    if not _FRONTEND_ABORT_RE.search(transcript):
        return False
    if re.search(r"\breturned\s+(?:PASS|FAIL|UNKNOWN|TIMEOUT)\b", transcript):
        return False
    return ("did not return a status" in transcript
            or "ERROR: syntax error" in transcript)


def engine_spoke(transcript: str) -> bool:
    """True only when the PROOF ENGINE itself left a mark on the transcript.

    Pure. The runner's own `[formal_property_run] ...` lines are removed
    first: they are this program talking ABOUT the engine, and one of them
    ("...not found on PATH") is precisely the message that says the engine
    was never reached. Counting them as engine output is what let an
    unreachable environment be reported as an inconclusive proof.
    """
    return bool(_SBY_SIG_RE.search(
        _RUNNER_VOICE_RE.sub("", transcript or "")))


def search_location(container: Optional[str]) -> str:
    """WHERE the flow looked for the engine (pure)."""
    return (f"docker exec {container} (PATH=/foss/tools/bin:"
            f"/foss/tools/yosys/bin:$PATH)" if container
            else "ambient PATH of the calling shell")


def unreachable_env_gap(transcript: str,
                        container: Optional[str]) -> Dict[str, str]:
    """The BACKSTOP gap, for when the probe says the environment was never
    reached but the transcript carries no signature this file recognises.

    `detect_engines` already answers "was the environment reachable?" and
    writes `_env_reachable` into the record. That answer was computed and then
    ignored: the emission hung entirely on matching a message shape, so any
    runtime wording nobody had anticipated fell straight through to a
    fabricated proof verdict. A gap keyed on a shape only reports the shapes
    already known; keyed on the probe's own verdict it cannot be out-run.

    Pure: the transcript's first non-empty line is carried verbatim as the
    tool message, so the diagnosis stays checkable and nothing is invented.
    """
    first = next((ln.strip() for ln in (transcript or "").splitlines()
                  if ln.strip()), "")
    where = search_location(container)
    if container:
        remedy = (f"the EDA container named {container!r} was never contacted "
                  f"— it is not running, or this host cannot reach it. Start "
                  f"it (docker start {container!r}) and re-run, or pass "
                  f"--container '' to invoke sby from the ambient PATH; our "
                  f"SymbiYosys fork ships in the vibeic-eda image at "
                  f"/usr/local/bin/sby")
    else:
        remedy = ("no proof engine answered on the ambient PATH — install "
                  "SymbiYosys (our fork ships in the vibeic-eda image at "
                  "/usr/local/bin/sby) or re-run with --container <name> "
                  "naming a running vibeic-eda container")
    return {
        "missing_capability": "docker container" if container else "sby",
        "searched": where,
        "searched_container": container or "",
        "remedy": remedy,
        "tool_message": first[:300],
    }


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
    if engine_spoke(text):
        return None  # sby ran and spoke — not an environment gap
    searched = search_location(container)
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
    elapsed_s: Optional[int] = None  # sby's own per-task wall clock

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
        mt = _ELAPSED_RE.search(rest)
        if mt:
            tr.elapsed_s = int(mt.group("secs"))
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


#: The second PROVE engine. `mode prove` with `[engines] smtbmc yices` is a
#: k-induction proof in SymbiYosys; it is NOT bmc-only. MEASURED in the released
#: image (SBY v0.67-31-g2c2f04e, yices-smt2 2.7.0; bitwuzla/z3/boolector
#: absent, so yices is the only smtbmc solver there): a 4-bit mod-10 counter
#: gives `successful proof by k-induction` / `DONE (PASS, rc=0)`.
KIND_PROVE_ENGINE = "smtbmc yices"
#: A task named `<prove task><KIND_ARM_SUFFIX>` is the SAME claim as its base
#: task, proved by the second engine. It is folded into the base row.
KIND_ARM_SUFFIX = "_kind"


def fold_prove_arms(lp: LogParse) -> Tuple[LogParse, List[dict]]:
    """Fold every `<task>_kind` prove arm into its base prove task.

    Two engines asked the SAME question (`mode prove`, same script), so the
    claim has ONE row whose status is the better honest answer:

      * any arm FAIL (a counterexample; k-induction's basecase FAIL and pdr's
        FAIL are both real traces) -> FAIL. If the other arm PASSed the two
        engines disagree; that is recorded and the row is NEVER PASS.
      * else any arm PASS (`DONE (PASS)`, an unbounded proof) -> PASS, and the
        faster arm (sby's own elapsed clock; ties keep the first engine) is
        the `selected` one.
      * else the base task's own status (UNKNOWN / ERROR / TIMEOUT) — an
        induction step that failed is UNKNOWN, never a proof and never a cex.

    Each arm keeps its own status from its own `DONE` line, so the
    anti-fabrication rule holds per engine: an arm with no `DONE` stays
    UNKNOWN and cannot contribute a PASS. Returns the folded parse and one
    record per folded claim."""
    folded = LogParse()
    records: List[dict] = []
    arms_of: Dict[str, TaskResult] = {}
    for name, tr in lp.tasks.items():
        base = name[:-len(KIND_ARM_SUFFIX)] if name.endswith(KIND_ARM_SUFFIX) else None
        if base and base in lp.tasks and (tr.mode or "").lower() == "prove" \
                and (lp.tasks[base].mode or "").lower() == "prove":
            arms_of[base] = tr
            continue
        folded.tasks[name] = tr
    uncalibrated = None
    if arms_of:
        import instrument_calibration as _instrument_calibration
        try:
            _instrument_calibration.assert_calibrated(
                "formal_property_run::fold_prove_arms")
        except _instrument_calibration.Uncalibrated as exc:
            uncalibrated = str(exc)
    for base, kind in arms_of.items():
        primary = lp.tasks[base]
        if uncalibrated:
            # The second arm may not judge (NOT_MEASURED / uncalibrated); the
            # claim is the first engine's alone, and the record says why.
            folded.tasks[base] = primary
            records.append({
                "task": base, "status": primary.status,
                "selected_engine": primary.engine, "engines_disagree": False,
                "arms": [{"task": kind.name, "engine": kind.engine,
                          "status": "NOT_MEASURED",
                          "reason_class": "uncalibrated",
                          "detail": uncalibrated}]})
            continue
        arms = [primary, kind]
        statuses = [a.status for a in arms]
        disagreement = "FAIL" in statuses and "PASS" in statuses
        if "FAIL" in statuses:
            chosen = next(a for a in arms if a.status == "FAIL")
        elif "PASS" in statuses:
            passing = [a for a in arms if a.status == "PASS"]
            chosen = min(passing, key=lambda a: (a.elapsed_s is None,
                                                 a.elapsed_s or 0))
        else:
            chosen = primary
        folded.tasks[base] = TaskResult(
            name=base, status=chosen.status, engine=chosen.engine,
            mode=primary.mode, depth=primary.depth,
            cex_frame=chosen.cex_frame, elapsed_s=chosen.elapsed_s)
        records.append({
            "task": base,
            "status": chosen.status,
            "selected_engine": chosen.engine,
            "engines_disagree": disagreement,
            "arms": [{"task": a.name, "engine": a.engine, "status": a.status,
                      "bound": a.bound_kind, "elapsed_s": a.elapsed_s}
                     for a in arms],
        })
    return folded, records


def build_results(top: str, cfg: Dict[str, TaskResult], lp: LogParse,
                  evidence_relpath: str, sby_relpath: str) -> dict:
    """Merge config (mode/depth) with the log (status/engine/cex) into the
    canonical results.json dict the Step-5 gate consumes. all_proved is true
    ONLY when at least one task ran and every task returned PASS. A second
    prove engine's arm is folded into its claim first (`fold_prove_arms`)."""
    lp, prove_arms = fold_prove_arms(lp)
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
    if any(r["engines_disagree"] for r in prove_arms):
        verdict = "FAIL"
        disclosure.append(
            "PROVE ENGINES DISAGREE: one engine proved and the other found a "
            "counterexample for the same claim — recorded as FAIL, never PASS: "
            + ", ".join(r["task"] for r in prove_arms if r["engines_disagree"]))
    extra = {"prove_arms": prove_arms} if prove_arms else {}
    return {
        **extra,
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


# ── SystemVerilog include headers ───────────────────────────────────────────
# A source that carries `` `include "x.svh" `` is NOT self-contained. sby copies
# every `[files]` entry into its own `src/` working directory and runs yosys
# there, so a header that was never staged is simply not on disk when the
# frontend reaches the directive and yosys aborts before any engine starts:
#
#     ERROR: Can't open include file `prim_assert_yosys_macros.svh'!
#
# sby then reports rc=16 / "did not return a status" for every task, and the
# step self-reports a FORMAL capability gap it does not have — the same
# unmeasured-thing-reading-as-a-measured-zero shape the include-hub filter
# above exists to refuse. MEASURED on opentitan_aes (2026-09-02): every task
# ERRORed on `prim_assert_yosys_macros.svh`, which was staged in the run's own
# phase2/stage1/rtl/ and never copied into formal/.
#
# The headers are resolved from the sources' OWN `include` directives, not from
# a blind `*.svh` glob: a header nothing includes is not evidence and is not
# staged. Resolution is transitive (a header may include another) and bounded.
# Headers go into `[files]` ONLY — never into `read_verilog`, which would
# elaborate a macro body as a compilation unit. Chip-AGNOSTIC: no vendor,
# filename or SKU literal appears here.
_INCLUDE_RE = re.compile(r'^\s*`include\s+"([^"\n]+)"', re.MULTILINE)

#: Bound on the transitive walk, so a cyclic include set terminates.
_MAX_INCLUDE_DEPTH = 16


def resolve_include_headers(sources: List[Path],
                            search_dirs: Optional[List[Path]] = None
                            ) -> List[Path]:
    """Header files the given sources `include`, resolved on disk.

    Returns the resolved headers in a stable order. A directive naming a file
    that is NOT findable is silently absent from the result — this function
    reports what it FOUND; whether an unresolvable include is fatal is the
    frontend's call, not this resolver's.
    """
    roots: List[Path] = []
    for d in (search_dirs or []):
        if d.is_dir() and d not in roots:
            roots.append(d)
    for s in sources:
        parent = s.parent
        if parent.is_dir() and parent not in roots:
            roots.append(parent)

    found: "Dict[str, Path]" = {}
    frontier = [s for s in sources if s.is_file()]
    seen = {s.resolve() for s in frontier}
    for _ in range(_MAX_INCLUDE_DEPTH):
        if not frontier:
            break
        nxt: List[Path] = []
        for src in frontier:
            try:
                text = src.read_text(errors="replace")
            except OSError:
                continue
            for raw in _INCLUDE_RE.findall(text):
                name = Path(raw).name
                if name in found:
                    continue
                for root in roots:
                    cand = root / raw
                    if not cand.is_file():
                        cand = root / name
                    if cand.is_file():
                        found[name] = cand
                        if cand.resolve() not in seen:
                            seen.add(cand.resolve())
                            nxt.append(cand)
                        break
        frontier = nxt
    return [found[k] for k in sorted(found)]


def emit_sby(rtl_files: List[str], harness_file: str, top: str,
             safety_defs: str = "-DSPM_SAFETY_ONLY",
             bmc_defs: str = "-DSPM_RESET_AT_T0",
             safety_depth: int = 20, bmc_depth: int = 12,
             engine_prove: str = "abc pdr",
             engine_bmc: str = "abc bmc3",
             include_files: Optional[List[str]] = None,
             frontend: str = "read_verilog",
             observers: Optional[List[Tuple[str, str]]] = None,
             dut_simdef: Optional[str] = None,
             kind_engine: Optional[str] = None,
             harness_top: Optional[str] = None) -> str:
    """Emit a two-task .sby: a `safety` task (unbounded prove) and a `bmc`
    task (bounded model check). Files are listed under [files] so the Step-5
    evidence gate can resolve every referenced source.

    `kind_engine` (e.g. `KIND_PROVE_ENGINE`) adds a THIRD task,
    `safety<KIND_ARM_SUFFIX>`: the same `mode prove` claim over the same read,
    driven by a second unbounded engine. `build_results` folds it into the
    `safety` row (`fold_prove_arms`). Without it the text is byte-identical.

    `-sv` is not optional. Without it yosys uses the Verilog-2005 frontend,
    which rejects SystemVerilog a synthesisable design legitimately uses.
    MEASURED in the pinned image on a four-line probe:

        read_verilog -formal     svprobe.sv  ->  svprobe.sv:1: ERROR: syntax
              error, unexpected TOK_ID, expecting ')' or ',' or '='
        read_verilog -formal -sv svprobe.sv  ->  Successfully finished
              Verilog frontend.

    for `module svprobe (input logic clk, ...); logic [3:0] cnt;
    always_comb ...` -- ordinary synthesisable SystemVerilog.
    `emit_invariant_sby` beside this function already passes `-sv`; the two
    emitters disagreed and only this one was wrong. `-sv` accepts
    Verilog-2005 too, so no design loses a parse.

    THIS IS NOT SUFFICIENT FOR EVERY DESIGN, and the limit is worth stating
    where the flag is. yosys's own SystemVerilog frontend still rejects a
    package import in the MODULE HEADER (`module m import p::*; #( ... )`)
    with `TOK_IMPORT`, which is how the OpenTitan sources are written. Phase-2
    synth reaches them through `read_slang`; this emitter does not, and that
    frontend split -- not this flag -- is what keeps such a design from a
    formal verdict.

    `aigsmt none` avoids
    the SMT witness-replay step (only an external SMT solver could satisfy it)
    so ABC's own engines produce the verdict standalone."""
    reads = " ".join([harness_file] + list(rtl_files))
    # v1.15.67 — THE FRONTEND SPLIT, closed. `read_verilog -sv` is yosys's own
    # SystemVerilog frontend and it rejects a package import in the MODULE
    # HEADER (`module m import p::*; #(...)`), which is how the OpenTitan
    # sources are written. MEASURED on opentitan_aes at v1.15.66:
    #
    #     aes.sv:10: ERROR: syntax error, unexpected TOK_IMPORT
    #     DONE (ERROR, rc=16) ... engine_0 did not return a status
    #
    # Both tasks died before an engine started and the step reported a FORMAL
    # capability gap the host did not have. Phase-2 synth reads the SAME
    # sources through `read_slang`, the full SV-2017 frontend, and the LEC
    # gold-read already falls back to it on this exact signature family. Same
    # probe, in the pinned image, over the same 131-file `[files]` list:
    # `read_slang --single-unit` elaborates every OpenTitan source.
    #
    # `--single-unit` reads them as ONE compilation unit so a macro defined in
    # an early file is visible to a later one — the shared preprocessor scope
    # the successive `read_verilog` calls have by construction, and which
    # slang otherwise gives each file separately.
    #
    # The DEFAULT is unchanged: `read_verilog -sv` emits a byte-identical .sby
    # for every design that has always parsed, and the caller re-emits with
    # `frontend="read_slang"` only after that frontend has actually aborted.
    if frontend == "read_slang":
        # No `--formal`: `read_slang` has no such flag and keeps assertions
        # and formal statements by default (`--ignore-assertions` is the
        # opt-OUT). Probed in the pinned image via `help read_slang`.
        _safety_read = f"read_slang --single-unit {safety_defs} {reads}"
        _bmc_read = f"read_slang --single-unit {bmc_defs} {reads}"
    elif dut_simdef is not None:
        # R-0915-157 — THE PROOF PROVES THE CHIP'S DESIGN. The DUT is read
        # EXACTLY as the chip's synthesis reads it (`_chip_synth_read`: no
        # `-formal`, the chip's `-DSIMULATION` decision); only the harness is
        # read with `-formal` and the proof task's defines. FORMAL is never
        # defined for the DUT, so an `ifdef FORMAL` arm the chip never builds
        # cannot be what is proved.
        _safety_read = f"read_verilog -formal -sv {safety_defs} {harness_file}"
        _bmc_read = f"read_verilog -formal -sv {bmc_defs} {harness_file}"
    else:
        _safety_read = f"read_verilog -formal -sv {safety_defs} {reads}"
        _bmc_read = f"read_verilog -formal -sv {bmc_defs} {reads}"
    # `multiclock on` — WITHOUT IT AN EDGE-POLARITY MUTATION IS INVISIBLE
    # (2026-09-15, icspm2). The flow asks the `formal-verify` expert to
    # discharge `L8.clock_and_reset_waveform.clocks.0.edge`, i.e. the DECLARED
    # CLOCK EDGE. MEASURED on a real `spm` harness in the pinned image (SBY
    # v0.67-31-g2c2f04e), one solo harness per property x a single-edit RTL
    # mutant that flips `@(posedge clk)` to `@(negedge clk)`:
    #
    #     default (no multiclock)   base PASS   negedge mutant ERROR
    #         engine_0: Error: Does not work for combinational networks.
    #     multiclock on             base PASS   negedge mutant FAIL   x4 properties
    #
    # An ERROR is not a discrimination: the engine never evaluated the model, so
    # the flow could not tell a design that honours its declared edge from one
    # that does not — on the very obligation it had asked an expert to prove.
    # With the option the base still proves and every property refutes the
    # mutant. The predecessor lane recorded this as an unverified candidate
    # ("edge POLARITY is outside what a clocked model checker can see"); it is
    # verified here and the opposite is true.
    #
    # COST, measured on the same design: safety arm (mode prove, abc pdr,
    # UNBOUNDED) PASS at size 8 and 32; bmc arm (abc bmc3, depth 12, the default
    # above) PASS at size 8 and 32. Nothing that proved stops proving.
    #
    # Headers are STAGED but never READ: `[files]` puts them in sby's `src/` so
    # a `` `include `` resolves; `read_verilog` must not be handed a macro body.
    srcs = list(rtl_files) + [harness_file] + list(include_files or [])
    files_block = "\n".join(srcs)
    # R-0915-144 — OBSERVERS: DUT state made visible the way the engine binds
    # it (see `formal_harness_gen.OBSERVE_PRAGMA`). The design is flattened
    # and each observer is `connect -nomap -set` to the flattened net, AFTER
    # `select -assert-any` has proved that net exists: a net that is not there
    # stops the task with an ERROR, so an observer can never be left undriven
    # (a free variable) behind a proof. -nomap addresses the named placeholder,
    # not its canonical alias: default alias mapping can unset a packed alias,
    # another observer, or an assertion operand's driver after flatten. The
    # native registered-alias controls exercise those paths and the original
    # clock/reset/state mutations. Existing placeholder drivers are still
    # removed; -nounset would retain them. No observers → identical script.
    bind_lines = ""
    model_top = harness_top or top
    dut_lines = ""
    if dut_simdef is not None and frontend != "read_slang":
        import _chip_synth_read as _csr
        dut_lines = "\n".join(_csr.chip_read_lines(
            [Path(f) for f in rtl_files], dut_simdef)) + "\n"
    if observers or dut_lines:
        _b = [f"hierarchy -top {model_top}", "proc", "flatten"]
        if dut_lines:
            # SILICON HAS NO INITIALIZERS (R-0915-157): every flattened DUT
            # wire (`<inst>.<net>`) loses its `init`, so design flops start
            # from ARBITRARY state. The harness's own registers (no dot) keep
            # theirs — `f_past_valid` must start at 0.
            _b.append(f"setattr -unset init {model_top}/w:*.*")
        for lhs, rhs in observers or []:
            _b.append(f"select -assert-any {model_top}/w:{rhs}")
            _b.append(f"connect -nomap -set {lhs} {rhs}")
        bind_lines = "\n".join(_b) + "\n"
    if kind_engine:
        kt = "safety" + KIND_ARM_SUFFIX
        return f"""[tasks]
safety   prove
{kt} prove
bmc      bmc

[options]
safety: mode prove
safety: depth {safety_depth}
{kt}: mode prove
{kt}: depth {safety_depth}
bmc:    mode bmc
bmc:    depth {bmc_depth}
aigsmt none
multiclock on

[engines]
safety: {engine_prove}
{kt}: {kind_engine}
bmc:    {engine_bmc}

[script]
{dut_lines}safety: {_safety_read}
{kt}: {_safety_read}
bmc: {_bmc_read}
{bind_lines}prep -top {model_top}

[files]
{files_block}
"""
    return f"""[tasks]
safety   prove
bmc      bmc

[options]
safety: mode prove
safety: depth {safety_depth}
bmc:    mode bmc
bmc:    depth {bmc_depth}
aigsmt none
multiclock on

[engines]
safety: {engine_prove}
bmc:    {engine_bmc}

[script]
{dut_lines}safety: {_safety_read}
~safety: {_bmc_read}
{bind_lines}prep -top {model_top}

[files]
{files_block}
"""


def proof_define_sets() -> tuple:
    """The `-D` flags of every task `emit_sby` writes (safety, bmc), read from
    its own defaults so the structural netlist is elaborated exactly as each
    proof task reads the RTL — one spelling, never retyped."""
    import inspect
    params = inspect.signature(emit_sby).parameters
    return tuple(dict.fromkeys(
        (params["safety_defs"].default, params["bmc_defs"].default)))


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
                       prove_depth: int = 40, bmc_depth: int = 25,
                       include_files: Optional[List[str]] = None) -> str:
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
    # See emit_sby: staged into sby's src/ for `` `include ``, never read.
    srcs = list(rtl_files) + [harness_file] + list(include_files or [])
    files_block = "\n".join(srcs)
    chparam_lines = [f"chparam -set {n} {v} {top}" for n, v in chparams]
    connect_lines = [f"connect -nomap -set {lhs} {rhs}" for lhs, rhs in connects]

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
            cmd = _ce.docker_exec_argv(container, "bash", "-lc", probe)
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
    # THE STALL COMES FIRST, and the order is load-bearing: the container path
    # still speaks coreutils `timeout` (a clock this program does not own), so
    # both shapes can appear, and the one this host actually observed must win.
    (re.compile(r"SOLVER STALLED: .*?after (\d+) consecutive looks"),
     "no_progress"),
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
    "no_progress": ("every readable progress signal sat still — the solver "
                    "stopped moving, which is a finding about the run and not "
                    "about the host; the properties may well hold and we did "
                    "not finish"),
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
        if resource == "no_progress":
            # THE LIMIT IS READ OUT OF WHAT WAS OBSERVED, never re-derived from
            # a constant: the number of looks is in the sentence the run wrote,
            # and a second copy resolved here could disagree with the run that
            # actually happened.
            limit = int(m.group(1))
            unit = "consecutive looks"
        elif resource == "wall_clock":
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
#: HOW MANY CONSECUTIVE MOTIONLESS LOOKS make the solver a stall, and how far
#: apart to look. Read AT CALL TIME, never bound as a default argument: the
#: failure path below is reachable in a test only if the cadence can be made
#: small, and `gatekeeper_prepare_landing._default_census_writer` records what a
#: bound nobody can override costs — "a bound whose failure path is unreachable,
#: which is the same defect the bound was added to prevent, one level up".
#: `None` means the primitive's own measured cadence, which is the shipped one.
SOLVER_STALL_LOOKS = None      # None -> _progress_run.DEFAULT_STALL_LOOKS
SOLVER_POLL_S = None           # None -> the host-measured poll interval


def _run_group_bounded(argv: List[str], cwd: Path,
                       timeout: int) -> "tuple":
    """Run `argv` under PROGRESS supervision, in its own session.

    Returns `(rc, combined_output)`. `rc == _pr.RC_STALLED` means every readable
    progress signal — the captured output, the process tree's CPU, its block
    I/O — sat still for a count of consecutive looks and the whole GROUP was
    stopped; no orphan survives it.

    WHAT CHANGED, AND WHY (vibe-ic#2051, owner ruling R4). This was
    `proc.communicate(timeout=timeout)` followed by a hand-written SIGTERM/
    SIGKILL of the process group — a WALL CLOCK deciding to stop a job, which is
    the one thing #2051 forbids: elapsed time answers "how long has it been",
    never "is this working", so the same commit on a slower host came back
    INCONCLUSIVE while a solver that was genuinely computing was killed. A SAT
    proof that legitimately runs for hours advances CPU at every look and can
    now never be stopped; a solver that has actually wedged is stopped SOONER
    than the deadline would have, and is reported as a stall rather than as a
    clock.

    `timeout` is not gone and is not ignored: it is handed to the supervisor as
    the RECORDED BUDGET (`hard_ceiling_s`), which — since #2051 — is announced
    once when crossed and stops nothing. So the caller's declared expectation
    still reaches the record, and no longer decides anything.

    THE GROUP REAP IS PRESERVED, and it is the reason `start_new_session=True`
    is passed: sby is a launcher and the memory lives in the yosys it spawns
    (35.6 GB apiece on a 125 GB host, #623/#628). `_watchdog._default_kill`
    signals a process GROUP only when the child is its own group leader, which
    is exactly what that argument makes it.
    """
    try:
        cp = _pr.run(argv, cwd=str(cwd), stdout=subprocess.PIPE,
                     stderr=subprocess.STDOUT, text=True, errors="replace",
                     start_new_session=True,
                     hard_ceiling_s=float(timeout),
                     **_solver_supervision())
    except _pr.Stalled as stall:
        return _pr.RC_STALLED, (stall.stdout or "")
    return cp.returncode, cp.stdout or ""


def _solver_supervision() -> Dict[str, object]:
    """The supervision cadence, resolved from the module constants at CALL TIME.

    An unset knob is not passed at all, so the primitive's own default (and its
    host measurement of the spawn floor) stands — a copied number here would be
    a second declaration of a cadence that already has an owner.
    """
    kw: Dict[str, object] = {}
    if SOLVER_STALL_LOOKS is not None:
        kw["stall_looks"] = int(SOLVER_STALL_LOOKS)
    if SOLVER_POLL_S is not None:
        kw["poll_s"] = float(SOLVER_POLL_S)
    return kw


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
    if rc == _pr.RC_STALLED:
        # Named, because an anonymous death reads as a tool crash and sends the
        # reader to the wrong place — and named as what it WAS. The clock that
        # used to write "SOLVER DEADLINE ... after Ns" here is gone (#2051): a
        # solver still moving is never stopped, so what remains to report is the
        # one thing that did happen, that every readable progress signal sat
        # still. The count of looks travels in the sentence because it is the
        # observation, where the seconds were only the host.
        looks = (int(SOLVER_STALL_LOOKS) if SOLVER_STALL_LOOKS is not None
                 else _pr.DEFAULT_STALL_LOOKS)
        out += (f"\n[formal_property_run] SOLVER STALLED: sby and its whole "
                f"process group were stopped after {looks} consecutive looks "
                f"in which the captured output, the process tree's CPU and its "
                f"block I/O ALL sat still. The proof is INCONCLUSIVE — not "
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
    cmd = _ce.docker_exec_argv(container, "timeout", "-k", str(_CE.DEFAULT_KILL_GRACE_S), str(int(timeout)), "bash", "-lc", inner)
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
        # A container was explicitly requested, so the missing thing is the
        # `docker` CLI — not `sby`, which this branch never looked for. Saying
        # "sby/docker not found on PATH" here sent the reader to install a
        # solver that may well be sitting on the ambient PATH already, and it
        # never named the container the caller asked us to reach.
        #
        # AND IT SAYS "NO SUCH CONTAINER", not "could not be reached". Those
        # are different claims and the weaker one is not the one the evidence
        # supports: with no `docker` CLI on PATH this process can reach NO
        # container at all, so the named one does not exist as far as this
        # host is concerned. "Could not be reached" leaves open a container
        # that is up and merely unqueryable — which is exactly the hedge that
        # let an absent environment be reported as something short of absent.
        # The reason travels with the claim in the SAME line, so no reader can
        # mistake this for a reply from a docker daemon we never spoke to.
        return (f"[formal_property_run] ERROR: No such container: "
                f"{container!r} — the `docker` CLI is not on PATH here, so no "
                f"container is reachable from this host\n")


def _write_authoring_incomplete(formal_dir: Path, reason: str) -> None:
    """Record applicable-but-unauthored work. Silence is never inapplicable."""
    # vibe-ic#1082 — `formal_authoring_request.json` is a DECLARED
    # required_output (flow/phase1_phase2_phase3.yaml). Written through the
    # atomic helper: a raw write_text killed part-way leaves a truncated file
    # that `required_outputs` reads as PRESENT, so the run reports the receipt
    # exists while none of the obligations that make it actionable are in it.
    _aa.write_json(formal_dir / "formal_authoring_request.json", {
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
    })


def _assertion_count(path: Optional[Path],
                     extra: Optional[List[Path]] = None) -> int:
    """Count actual asserted properties in the authored harness.

    `extra` carries the files the harness INCLUDES. An assert lives where it
    is written, and an expert-authored property lives in
    `formal_expert_properties.svh`, not in the generated harness that
    `` `include ``s it -- so counting the harness alone reports 0 of them and
    the caller then publishes `contract claims N covered obligation(s) but
    harness contains 0 assert statement(s)` about a proof that really did
    discharge N outputs. MEASURED on `subservient` x gf180mcuD: harness 1 +
    fragment 3 = 4 asserts, and sby proved outputs 0..3.
    """
    texts = []
    for f in [path] + list(extra or []):
        if f is None or not f.is_file():
            continue
        body = re.sub(r"/\*.*?\*/", " ", f.read_text(errors="replace"),
                      flags=re.DOTALL)
        texts.append(re.sub(r"//[^\n]*", "", body))
    return sum(len(re.findall(r"\bassert\s*(?:property\s*)?\(", x))
               for x in texts)


# ── R-0915-144 — observers, the `dut.*` refusal, and the program discharge ──
PROGRAM_RECEIPT = "formal_program_discharge.json"
STRUCTURAL_EVIDENCE = "formal_structural_evidence.json"
DISCHARGED_BY_PROGRAM = "DISCHARGED_BY_PROGRAM"
STRUCTURAL_REFUTED = "STRUCTURAL_REFUTED"
# An `@observe` pragma is read WHOLE — to the end of its line — and only a
# plain wire bound to a plain (dotted) net is accepted. Anything else is
# UNREADABLE and refused, never truncated: the old pattern stopped at `$`, so
# `= dut.a$b` bound to `dut.a` (round-6 review).
_OBSERVE_LINE_RE = re.compile(r"//\s*@observe\b(?P<rest>[^\n]*)$", re.MULTILINE)
_OBSERVE_BODY_RE = re.compile(
    r"^\s+(?P<lhs>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"(?P<rhs>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*$")
_CONNECT_RE = re.compile(r"^[ \t]*connect[ \t]+(?P<nomap>-nomap[ \t]+)?"
                         r"-set[ \t]+(?P<lhs>\S+)[ \t]+(?P<rhs>\S+)[ \t]*$",
                         re.MULTILINE)
_SV_KEYWORDS = {
    "module", "property", "endproperty", "assert", "assume", "cover", "always",
    "always_ff", "always_comb", "initial", "wire", "reg", "logic", "input",
    "output", "inout", "parameter", "localparam", "assign", "if", "else",
    "begin", "end", "sequence", "restrict", "genvar", "generate", "function",
    "task", "return", "case", "default", "import", "bit", "int", "integer",
}
_IMPLICIT_HIER_RE = re.compile(
    r"Identifier `\\?([A-Za-z_]\w*\.[A-Za-z_][\w.]*)' is implicitly declared")


def parse_observers(text: str) -> List[Tuple[str, str]]:
    """`// @observe <wire> = <inst>.<net>` pragmas of a harness (pure) — only
    the ones read WHOLE. See `unreadable_observers` for the rest."""
    out = []
    for m in _OBSERVE_LINE_RE.finditer(text):
        b = _OBSERVE_BODY_RE.match(m.group("rest"))
        if b:
            out.append((b.group("lhs"), b.group("rhs")))
    return out


def unreadable_observers(text: str) -> List[str]:
    """Every `@observe` pragma this program cannot read whole (pure)."""
    return [m.group(0).strip() for m in _OBSERVE_LINE_RE.finditer(text)
            if not _OBSERVE_BODY_RE.match(m.group("rest"))]


def observer_binding_mismatches(harness_text: str, sby_text: str) -> List[str]:
    """(d) Every `connect -set` in the task file must be EXACTLY an observer the
    harness declared (same wire, same net), each wire bound once, and every
    declared observer bound. Anything else is named (pure)."""
    # the harness's own `@connect` pragmas (the invariant-strengthened path)
    # are declarations too — exact lhs/rhs, still checked both ways
    declared = parse_observers(harness_text) + [
        (l, r) for l, r in parse_harness_pragmas(harness_text)["connects"]]
    decl = {}
    probs = []
    for lhs, rhs in declared:
        if lhs in decl and decl[lhs] != rhs:
            probs.append(f"observer {lhs} declared for two nets")
        decl[lhs] = rhs
    bound: Dict[str, List[str]] = {}
    for m in _CONNECT_RE.finditer(sby_text):
        bound.setdefault(m.group("lhs"), []).append(m.group("rhs"))
    for lhs, rhss in bound.items():
        if lhs not in decl:
            probs.append(f"connect -set {lhs} binds a wire no observer declares")
        elif len(rhss) != 1 or rhss[0] != decl[lhs]:
            probs.append(f"connect -set {lhs} {' '.join(rhss)} != declared {decl[lhs]}")
    for lhs, rhs in decl.items():
        if lhs not in bound:
            probs.append(f"{lhs} = {rhs} (the task file does not bind it)")
    return probs


def unbound_hierarchical_refs(text: str) -> List[str]:
    """Hierarchical references INTO an instance the harness declares (pure).

    `<inst>.<net>` in a property does not bind to the DUT in this flow's formal
    path: yosys `read_verilog` has no hierarchical references and makes it an
    implicitly declared, UNDRIVEN local wire — a free variable. A property over
    it proves or refutes nothing about the design (MEASURED on spm, lane
    icspm5 §48: `dut.pr` failed at frame 3 while the same claim over the port
    `p = pr` proved). Comments are stripped first, so an `@observe` pragma —
    which is how DUT state IS made visible — is never counted.
    """
    body = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    body = re.sub(r"//[^\n]*", "", body)
    insts = set()
    for m in re.finditer(
            r"(?:^|;)\s*([A-Za-z_]\w*)\s*(?:#\s*\((?:[^()]|\([^()]*\))*\)\s*)?"
            r"([A-Za-z_]\w*)\s*\(", body, flags=re.MULTILINE):
        if m.group(1) not in _SV_KEYWORDS and m.group(2) not in _SV_KEYWORDS:
            insts.add(m.group(2))
    refs: List[str] = []
    for inst in sorted(insts):
        for r in re.finditer(rf"(?<![\w.$]){re.escape(inst)}\.([A-Za-z_]\w*)",
                             body):
            ref = f"{inst}.{r.group(1)}"
            if ref not in refs:
                refs.append(ref)
    return refs


def _sha256(path: Path) -> Optional[str]:
    import hashlib
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


# Case-INSENSITIVE: a `` `ASSUME(...) `` macro is an assumption too (review
# round 2, M3).
_ASSUME_RE = re.compile(r"\b(?:assume|restrict)\b", re.IGNORECASE)


def foreign_assumptions(harness_text: str) -> List[str]:
    """Assume/restrict statements in the harness (and its included fragment).

    The PROGRAM authors none. Any assumption present came from someone else,
    and it can make every generated property VACUOUS — `assume property
    (!rst)` alone makes "zero one cycle after reset" true of any design
    (review (a)). A program closure is therefore refused while one is present.
    """
    body = re.sub(r"/\*.*?\*/", " ", harness_text, flags=re.DOTALL)
    body = re.sub(r"//[^\n]*", "", body)
    return [ln.strip()[:160] for ln in body.splitlines() if _ASSUME_RE.search(ln)]


def _program_routed(contract: dict) -> List[dict]:
    return [o for o in (contract.get("unresolved_obligations") or [])
            if isinstance(o, dict) and not o.get("program_refused")
            and (o.get("program_rule") or {}).get("kind") in ("STRUCTURAL", "MIXED")]


def _clear_program_receipt(formal_dir: Path) -> None:
    """A receipt answers ONE run. Cleared at the start of every run, so a
    previous run's pair can never be read back as this run's (review H3)."""
    for name in (PROGRAM_RECEIPT, STRUCTURAL_EVIDENCE):
        try:
            (formal_dir / name).unlink()
        except FileNotFoundError:
            pass


def _program_discharge(formal_dir: Path, container: Optional[str],
                       harness_text: str,
                       model_text: Optional[str] = None) -> Optional[dict]:
    """Answer the STRUCTURAL / MIXED obligations the contract routes to the
    program, and write the INVOKED_BY_PROGRAM receipt. None when there are
    none. The receipt is never the expert's file: an AI answer and a program
    answer are different records (R-0915-125(a)).

    The receipt is BOUND to this run: the digest of the contract it answers,
    of every RTL file measured and of the evidence file it cites. The read-back
    refuses any pair that does not match (review H3)."""
    contract_path = formal_dir / "property_contract.json"
    try:
        contract = json.loads(contract_path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    rows = _program_routed(contract)
    subject = contract.get("structural_subject") or {}
    if not rows or not subject.get("top"):
        return None
    import formal_structural_check as _fsc
    claims: List[dict] = []
    for o in rows:
        for c in o["program_rule"].get("claims") or []:
            if c.get("rule") in _fsc.STRUCTURAL_RULES:
                key = {"rule": c["rule"], "signal": c.get("signal", ""),
                       "value": c.get("value", "")}
                if key not in claims:
                    claims.append(key)
    evidence = _fsc.check([Path(f) for f in subject.get("rtl_files") or []],
                          subject["top"], claims,
                          formal_dir / "structural_check", container,
                          simdef=subject.get("simdef", ""),
                          klass={"clock": subject.get("clock", ""),
                                 "resets": subject.get("resets") or []})
    evidence["work_dir"] = "structural_check"
    _aa.write_json(formal_dir / STRUCTURAL_EVIDENCE, evidence)
    answers = {(r["rule"], r.get("signal", ""), r.get("value", "")): r
               for r in evidence.get("claims") or []}
    body = re.sub(r"//[^\n]*", "", harness_text)
    assumes = foreign_assumptions(model_text if model_text is not None
                                  else harness_text)
    dispositions = []
    for o in rows:
        per_claim, status = [], DISCHARGED_BY_PROGRAM
        for c in o["program_rule"].get("claims") or []:
            if c.get("rule") in _fsc.STRUCTURAL_RULES:
                a = answers.get((c["rule"], c.get("signal", ""),
                                 c.get("value", ""))) or {}
                v = a.get("verdict", _fsc.NOT_DISCHARGED)
                per_claim.append({"claim": c, "verdict": v,
                                  "finding": a.get("finding", "not measured")})
                if v == _fsc.REFUTED:
                    status = STRUCTURAL_REFUTED
                elif v != _fsc.PASS and status == DISCHARGED_BY_PROGRAM:
                    status = _fsc.NOT_DISCHARGED
        missing = [p for p in o.get("properties") or []
                   if not re.search(rf"\bproperty\s+{re.escape(p)}\b", body)]
        needs_props = any(c.get("rule") not in _fsc.STRUCTURAL_RULES
                          for c in o["program_rule"].get("claims") or [])
        if needs_props and (missing or not o.get("properties")):
            if status == DISCHARGED_BY_PROGRAM:
                status = _fsc.NOT_DISCHARGED
            per_claim.append({"claim": "temporal", "verdict": _fsc.NOT_DISCHARGED,
                              "finding": f"generated properties absent: {missing}"})
        if needs_props and assumes and status == DISCHARGED_BY_PROGRAM:
            status = _fsc.NOT_DISCHARGED
            per_claim.append({"claim": "vacuity", "verdict": _fsc.NOT_DISCHARGED,
                              "finding": ("the harness carries assumption(s) "
                                          "the program did not author, which "
                                          "can make its properties vacuous: "
                                          + " | ".join(assumes))})
        if o.get("binding") and status == DISCHARGED_BY_PROGRAM:
            # R-0924-2 (landed): a NAME obligation is discharged by BINDING at
            # the Step-5 gate. The structural check measured it — a refutation
            # above stands — but a structural PASS is recorded as a finding on
            # the open row, never as this program's closure.
            status = _fsc.NOT_DISCHARGED
            per_claim.append({"claim": "binding", "verdict": _fsc.NOT_DISCHARGED,
                              "finding": ("structurally confirmed; a NAME "
                                          "obligation is discharged by BINDING "
                                          "at the Step-5 gate (R-0924-2)")})
        dispositions.append({
            "id": o["id"], "status": status, "kind": o["program_rule"]["kind"],
            "claims": per_claim, "properties": list(o.get("properties") or []),
            "evidence": STRUCTURAL_EVIDENCE,
            "reason": "; ".join(str(p["finding"]) for p in per_claim),
        })
    receipt = {
        "program": "formal_property_run", "ruling": "R-0915-144",
        "invocation_status": "INVOKED_BY_PROGRAM",
        "structural_evidence": STRUCTURAL_EVIDENCE,
        "binding": {
            "contract_sha256": _sha256(contract_path),
            "evidence_sha256": _sha256(formal_dir / STRUCTURAL_EVIDENCE),
            "top": subject["top"],
            "rtl_sha256": evidence.get("rtl_sha256") or {},
        },
        "foreign_assumptions": assumes,
        "dispositions": dispositions,
    }
    _aa.write_json(formal_dir / PROGRAM_RECEIPT, receipt)
    return receipt


def _verified_program_closures(formal_dir: Path) -> Tuple[
        Dict[str, dict], Dict[str, dict], Dict[str, dict]]:
    """READ BACK the program receipt: (closed, refuted, undischarged) by id.

    Refused wholesale unless the pair is THIS run's (review H3): the receipt's
    contract digest is the current contract's, its evidence digest is the
    evidence file's, the evidence measured the contract's subject top and
    every RTL file still has the digest that was measured. Then, per
    disposition: its id must be an obligation the CURRENT contract routes to
    the program; it must cite at least one structural claim; and every cited
    claim must carry the same verdict in the evidence on disk — the
    disposition's own word is never taken."""
    contract_path = formal_dir / "property_contract.json"
    try:
        receipt = json.loads((formal_dir / PROGRAM_RECEIPT).read_text(errors="replace"))
        evidence = json.loads((formal_dir / STRUCTURAL_EVIDENCE)
                              .read_text(errors="replace"))
        contract = json.loads(contract_path.read_text(errors="replace"))
    except (OSError, ValueError):
        return {}, {}, {}
    if not all(isinstance(x, dict) for x in (receipt, evidence, contract)):
        return {}, {}, {}
    if (receipt.get("program") != "formal_property_run"
            or str(receipt.get("invocation_status", "")).upper() != "INVOKED_BY_PROGRAM"):
        return {}, {}, {}
    bind = receipt.get("binding") or {}
    subject = contract.get("structural_subject") or {}
    rtl = bind.get("rtl_sha256") or {}
    if (not bind.get("contract_sha256")
            or bind.get("contract_sha256") != _sha256(contract_path)
            or bind.get("evidence_sha256") != _sha256(formal_dir / STRUCTURAL_EVIDENCE)
            or bind.get("top") != subject.get("top")
            or evidence.get("top") != subject.get("top")
            or sorted(rtl) != sorted(str(f) for f in subject.get("rtl_files") or [])
            or evidence.get("rtl_sha256") != rtl
            or not rtl or any(_sha256(Path(f)) != h for f, h in rtl.items())):
        return {}, {}, {}
    routed = {str(o["id"]) for o in _program_routed(contract)}
    # R-0924-2 (landed): a NAME obligation is discharged by BINDING at the
    # gate, never here. The structural check still measures it — a refutation
    # stands and a finding is written onto the open row — but a structural
    # PASS does not close it, so one declaration has one discharger.
    by_binding = {str(o["id"]) for o in _program_routed(contract) if o.get("binding")}
    verdicts = {(r.get("rule"), r.get("signal", ""), r.get("value", "")): r.get("verdict")
                for r in evidence.get("claims") or []}
    closed, refuted, undischarged = {}, {}, {}
    for d in receipt.get("dispositions") or []:
        if not isinstance(d, dict) or str(d.get("id")) not in routed:
            continue
        undischarged[str(d["id"])] = d
        cited = [c["claim"] for c in d.get("claims") or []
                 if isinstance(c.get("claim"), dict)]
        if not cited:
            continue
        keys = [(c.get("rule"), c.get("signal", ""), c.get("value", "")) for c in cited]
        if d.get("status") == STRUCTURAL_REFUTED:
            if any(verdicts.get(k) == "REFUTED" for k in keys):
                refuted[str(d["id"])] = d
        elif (d.get("status") == DISCHARGED_BY_PROGRAM
              and str(d["id"]) not in by_binding
              and all(verdicts.get(k) == "PASS" for k in keys)
              and not any(c.get("claim") in ("temporal", "vacuity")
                          for c in d.get("claims") or [])):
            closed[str(d["id"])] = d
    for k in list(closed) + list(refuted):
        undischarged.pop(k, None)
    return closed, refuted, undischarged


def _attach_property_contract(results: dict, formal_dir: Path,
                              harness: Optional[Path]) -> None:
    """Attach the auditable declaration/property denominator to a real run.

    A hand-authored harness with no manifest gets a denominator derived from
    its actual assertions. The in-flow generator writes `property_contract.json`
    with all remaining L3/L6/L8 obligations, which takes precedence.
    """
    # THE HARNESS MAY NOT HAVE BEEN HANDED IN. `run()` reuses an existing
    # `.sby` when no harness is passed, and `harness` is then None -- so this
    # counted 0 asserts for a run that proved four, and the mismatch row below
    # fired on a complete proof. The harness a reused task file READS is in
    # its own `[files]` block; resolve it there rather than reporting a
    # denominator against a file nobody named.
    _harness = harness
    if _harness is None or not _harness.is_file():
        for cand in sorted(formal_dir.glob("formal_*.sv")):
            _harness = cand
            break
    actual = _assertion_count(
        _harness, [formal_dir / EXPERT_PROPERTIES_SVH])
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
    request: dict = {}
    request_obligations: List[dict] = []
    request_path = formal_dir / "formal_authoring_request.json"
    from formal_harness_gen import _authoring_request_snapshot, _expert_closed_obligations
    request_snapshot = _authoring_request_snapshot(formal_dir)
    if request_path.is_file() or request_snapshot is not None:
        try:
            # An invalid active role/identity cannot erase its denominator or
            # requested IDs. It remains open; only verified identity earns credit.
            loaded = json.loads(request_path.read_text() if request_path.is_file()
                                else request_snapshot["text"])
            if not isinstance(loaded, dict):
                raise TypeError("authoring request is not a JSON object")
            request = loaded
            request_floor = int(request.get("property_denominator", 0))
            request_obligations = [
                row for row in (request.get("unresolved_obligations") or [])
                if isinstance(row, dict) and str(row.get("id", "")).strip()
            ]
        except (OSError, ValueError, TypeError):
            request_floor = 0
    if request_snapshot is None and not request_obligations and (
            request_path.is_file() or contract.get("authoring_request") is not None):
        request_obligations = [{"id": "formal.authoring_request_invalid", "layer": "formal",
                                "status": "UNAUTHORED", "author": "formal-verify",
                                "description": "authoring request identity or requested IDs are unreadable"}]
    unresolved = list(contract.get("unresolved_obligations") or [])
    # R-0915-144 — the PROGRAM's answer, read back against its evidence. A
    # closed id leaves the contract's open list; a refuted one stays, named.
    program_closed, program_refuted, program_open = _verified_program_closures(
        formal_dir)
    # A closure that RESTS ON GENERATED PROPERTIES stands only if the proof
    # proved them. A failed or inconclusive proof keeps the obligation open —
    # the counterexample is the answer, not the structural half (review H1).
    if results.get("all_proved") is not True:
        for oid in [k for k, d in program_closed.items() if d.get("properties")]:
            d = dict(program_closed.pop(oid))
            d["reason"] = ("its generated properties did not all prove: "
                           + ", ".join(d.get("properties") or []))
            program_open[oid] = d
    unresolved = [o for o in unresolved
                  if str(o.get("id")) not in program_closed]
    # An obligation the program looked at and could not discharge carries
    # the program's own reason, so the expert starts from it.
    _annotated = []
    for o in unresolved:
        d = program_open.get(str(o.get("id")))
        if d is not None:
            o = dict(o)
            o["status"] = "PROGRAM_NOT_DISCHARGED"
            o["description"] = (f"{o.get('description', '')} — program: "
                                f"{d.get('reason', '')}")
        _annotated.append(o)
    unresolved = _annotated
    # Review (a): an assumption the program did not author can make every
    # generated property vacuous. The obligations the GENERATOR closed with
    # its own properties are reopened while one is present — named, not
    # silently counted as covered.
    _root = formal_dir.parent.parent.parent
    _sby_rel = results.get("sby")
    _assumes = foreign_assumptions(_model_texts(
        (_root / _sby_rel) if isinstance(_sby_rel, str) else None,
        formal_dir, _harness))
    if _assumes:
        for row in contract.get("covered_obligations") or []:
            if (isinstance(row, dict) and row.get("program_rule")
                    and row.get("author") == "formal_harness_gen"):
                reopened = dict(row)
                reopened["status"] = "VACUITY_RISK_ASSUME"
                reopened["description"] = (
                    "program-authored property not counted: the harness carries "
                    "assumption(s) the program did not author: "
                    + " | ".join(_assumes))
                unresolved.append(reopened)
    # An obligation the program closed STRUCTURALLY has no assert statement:
    # its evidence is the netlist check. It is counted as authored so a
    # structural answer is not reported as a missing property — and ONLY one
    # with no property of its own, so nothing is counted twice.
    structural_only = sum(1 for d in program_closed.values()
                          if not d.get("properties"))
    try:
        denominator = int(contract.get("property_denominator", actual))
    except (TypeError, ValueError):
        denominator = actual
    # The request is the pre-expert snapshot. An expert may close obligations;
    # it may not shrink the denominator to make them disappear.
    denominator = max(denominator, request_floor, actual)
    covered = max(0, denominator - len(unresolved))
    if actual + structural_only < covered:
        unresolved.append({
            "id": "formal.authored_property_count_mismatch",
            "layer": "formal",
            "description": (f"contract claims {covered} covered obligation(s) "
                            f"but harness contains {actual} assert statement(s)"
                            + (f" and the program closed {structural_only} "
                               f"structurally" if structural_only else "")),
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
    # R-0915-125(a). TWO invocation statuses, kept DISTINCT in the record:
    #   INVOKED             a human / the `/formal-verify` skill answered.
    #   INVOKED_BY_PROGRAM  the runner discharged the obligation ITSELF, and
    #                       the receipt carries the proof transcript that ran.
    # They are never collapsed: an AI answer and a program answer must not be
    # indistinguishable to anyone reading the record afterwards. The raw status
    # is published alongside the boolean so a consumer can tell them apart
    # without re-reading the receipt.
    _invocation_status = str(receipt.get("invocation_status", "")).upper()
    expert_invoked = bool(
        request_obligations and request_snapshot is not None
        and receipt.get("request_sha256") == request_snapshot["sha256"]
        and _invocation_status == "INVOKED"
        and receipt.get("fallback_skill", "formal-verify") == request.get("fallback_skill"))
    expert_closed = {str(row["id"]) for row in _expert_closed_obligations(
        formal_dir, request_obligations,
        _harness.read_text(errors="replace") if _harness is not None else "")}
    program_invoked = bool(request_obligations and (program_closed or program_refuted))
    expert_used = False
    receipt_unresolved: List[dict] = []
    for requested in request_obligations:
        oid = str(requested["id"])
        if oid in program_closed:
            continue
        if oid in program_refuted:
            row = dict(requested)
            row["status"] = STRUCTURAL_REFUTED
            row["description"] = str(program_refuted[oid].get("reason") or
                                     "the structural check refuted the declaration")
            receipt_unresolved.append(row)
            continue
        disposition = dispositions.get(oid) if expert_invoked else None
        status = str((disposition or {}).get("status", "")).upper()
        prop = str((disposition or {}).get("property", "")).strip()
        if status == "AUTHORED" and prop and oid in expert_closed:
            expert_used = True
            continue
        row = dict(requested)
        row["status"] = status or "EXPERT_NOT_REVIEWED"
        if disposition and disposition.get("reason"):
            row["description"] = str(disposition["reason"])
        elif oid in program_open:
            row["status"] = "PROGRAM_NOT_DISCHARGED"
            row["description"] = (f"{requested.get('description', '')} — "
                                  f"program: {program_open[oid].get('reason', '')}")
        receipt_unresolved.append(row)
    by_id = {
        str(row.get("id", f"unnamed.{idx}")): row
        for idx, row in enumerate(unresolved + receipt_unresolved)
        if isinstance(row, dict)
    }
    unresolved = list(by_id.values())

    results["property_denominator"] = denominator
    # Review L9: never a numerator above its denominator. When the program
    # closed obligations, the authored count is the number of OBLIGATIONS
    # covered (asserts and structural closures are different units and are
    # published separately); otherwise it is the assert count, as before.
    _closed_obligations = max(0, denominator - len(unresolved))
    results["authored_property_count"] = (
        min(_closed_obligations, actual + structural_only)
        if program_closed else actual)
    results["assert_statement_count"] = actual
    results["program_structural_discharge_count"] = structural_only
    results["covered_property_count"] = min(
        actual + structural_only, _closed_obligations)
    results["unresolved_obligations"] = unresolved
    results["expert_fallback_required"] = bool(request_path.is_file() and request_obligations)
    results["expert_fallback_requested"] = bool(request_obligations)
    results["expert_fallback_skill"] = request.get("fallback_skill") if request_obligations else None
    results["expert_fallback_request_sha256"] = request_snapshot["sha256"] if request_snapshot else None
    results["expert_fallback_invoked_by"] = (receipt.get("invoked_by") if expert_invoked
                                              else "formal_property_run" if program_invoked else None)
    results["expert_fallback_invoked"] = expert_invoked or program_invoked
    #: WHICH KIND of answer discharged it, or "" when none has. Published so the
    #: distinction survives into `formal_proof_evidence_check` and into anything
    #: that reads results.json later (R-0915-125(a)). R-0915-144: when the
    #: PROGRAM answered and no expert disposition was used, the status is
    #: INVOKED_BY_PROGRAM and the receipt is the program's own file; the moment
    #: an expert answer closes anything, the status is the expert's.
    _root = formal_dir.parent.parent.parent
    if expert_invoked and (expert_used or not program_invoked):
        results["expert_fallback_invocation_status"] = _invocation_status
        results["expert_fallback_receipt"] = str(receipt_path.relative_to(_root))
    elif program_invoked:
        results["expert_fallback_invocation_status"] = "INVOKED_BY_PROGRAM"
        results["expert_fallback_receipt"] = str(
            (formal_dir / PROGRAM_RECEIPT).relative_to(_root))
    else:
        results["expert_fallback_invocation_status"] = ""
        results["expert_fallback_receipt"] = None
    if program_invoked:
        results["program_discharged_obligations"] = sorted(program_closed)
    if program_refuted:
        # A PROGRAM MEASURED that the design contradicts its declaration. That
        # is a refutation, like a counterexample — never "work not yet done".
        results["structural_refutations"] = [
            {"id": oid, "reason": d.get("reason"),
             "evidence": d.get("evidence")} for oid, d in sorted(program_refuted.items())]
    results["property_contract"] = (
        str(manifest_path.relative_to(formal_dir.parent.parent.parent))
        if manifest_path.is_file() else "derived from authored harness assertions")
    results["elaborated_sby"] = results.get("sby")
    results["proof_transcript"] = results.get("evidence")
    results["bounded_vs_unbounded_scope"] = list(
        results.get("bounded_vs_unbounded") or [])
    if program_refuted:
        results["proof_verdict"] = results.get("verdict")
        results["verdict"] = "FAIL"
        results["formal_completion"] = "FAIL"
    elif unresolved and results.get("verdict") == "PASS":
        results["proof_verdict"] = "PASS"
        results["verdict"] = "INCOMPLETE"
        results["formal_completion"] = "INCOMPLETE"
    else:
        results["formal_completion"] = results.get("verdict")


#: ONE spelling of the expert-property fragment's name, taken from the
#: program that emits the `` `include `` for it rather than retyped here.
try:
    from formal_harness_gen import EXPERT_PROPERTIES_SVH  # noqa: E402
except Exception:  # noqa: BLE001 — a sibling that cannot be imported is named
    EXPERT_PROPERTIES_SVH = "formal_expert_properties.svh"


def _ensure_expert_fragment_staged(sby_path: Path, formal_dir: Path) -> bool:
    """Add the expert-property fragment to a REUSED .sby's `[files]` block.

    Returns True when the file was changed. A no-op when the fragment is not
    on disk (nothing to stage) or is already listed (nothing to add), so a
    project without expert properties reads and writes byte-identical .sby
    files to the ones it had before this existed.

    The append is to `[files]` ONLY. It is a fragment, and `read_verilog` must
    never be handed a macro body -- the same rule the header staging follows.
    """
    frag = formal_dir / EXPERT_PROPERTIES_SVH
    if not frag.is_file():
        return False
    try:
        text = sby_path.read_text(errors="replace")
    except OSError:
        return False
    if "[files]" not in text:
        return False
    head, _, files_block = text.partition("[files]")
    if any(line.strip() == EXPERT_PROPERTIES_SVH
           for line in files_block.splitlines()):
        return False
    try:
        sby_path.write_text(
            head + "[files]" + files_block.rstrip("\n")
            + f"\n{EXPERT_PROPERTIES_SVH}\n")
    except OSError:
        return False
    return True


def _ensure_expert_observers_bound(sby_path: Path, formal_dir: Path) -> bool:
    """Bind observers newly declared by an expert fragment in a reused task.

    A fragment may add ``@observe`` declarations after the original ``.sby``
    was emitted.  Staging that fragment alone is insufficient: the old task
    has no ``connect -set`` commands, so the pre-proof refusal correctly sees
    undriven observer wires.  Add only absent bindings immediately before the
    existing ``prep -top``. Compatible legacy bindings are upgraded to -nomap
    so reused tasks preserve the same alias drivers as freshly emitted tasks.
    A pre-existing incompatible binding is deliberately
    left for ``observer_binding_mismatches`` to refuse rather than overwritten.
    """
    observers = parse_observers(_harness_texts(sby_path, formal_dir, None))
    if not observers:
        return False
    try:
        text = sby_path.read_text(errors="replace")
    except OSError:
        return False
    head, marker, after_script = text.partition("[script]")
    script, files_marker, tail = after_script.partition("[files]")
    if not marker or not files_marker:
        return False
    top_match = re.search(r"(?m)^\s*prep\s+-top\s+([A-Za-z_]\w*)\s*$", script)
    if top_match is None:
        return False
    declared: Dict[str, str] = {}
    for lhs, rhs in observers:
        if lhs in declared and declared[lhs] != rhs:
            return False
        declared[lhs] = rhs
    strict_connect = _CONNECT_RE
    lines_before = script.splitlines(keepends=True)
    found: Dict[str, List[str]] = {}
    needs_nomap = False
    for line in lines_before:
        match = strict_connect.match(line.rstrip("\n"))
        if match and match.group("lhs") in declared:
            found.setdefault(match.group("lhs"), []).append(match.group("rhs"))
            needs_nomap |= match.group("nomap") is None
    if any(any(rhs != declared[lhs] for rhs in rhss)
           for lhs, rhss in found.items()):
        return False
    if not needs_nomap and all(found.get(lhs) == [rhs] for lhs, rhs in declared.items()):
        return False
    stripped: List[str] = []
    select_re = re.compile(r"^[ \t]*select[ \t]+-assert-any[ \t]+"
                           r"(?P<net>\S+)[ \t]*$")
    for line in lines_before:
        match = strict_connect.match(line.rstrip("\n"))
        if (match and match.group("lhs") in declared
                and match.group("rhs") == declared[match.group("lhs")]):
            wanted = f"{top_match.group(1)}/w:{match.group('rhs')}"
            if stripped:
                prior = select_re.match(stripped[-1].rstrip("\n"))
                if prior and prior.group("net") == wanted:
                    stripped.pop()
            continue
        stripped.append(line)
    script = "".join(stripped)
    top_match = re.search(r"(?m)^\s*prep\s+-top\s+([A-Za-z_]\w*)\s*$", script)
    if top_match is None:
        return False
    lines = []
    if not re.search(r"(?m)^\s*flatten\s*$", script):
        lines += [f"hierarchy -top {top_match.group(1)}", "proc", "flatten"]
    for lhs, rhs in declared.items():
        lines += [f"select -assert-any {top_match.group(1)}/w:{rhs}",
                  f"connect -nomap -set {lhs} {rhs}"]
    prep_at = top_match.start()
    revised = script[:prep_at] + "\n".join(lines) + "\n" + script[prep_at:]
    try:
        sby_path.write_text(head + marker + revised + files_marker + tail)
    except OSError:
        return False
    return True


def _stage_include_headers(rtl: List[Path], formal_dir: Path,
                           already: Optional[List[str]] = None) -> List[str]:
    """Copy the headers `rtl` includes into `formal_dir`; return their names.

    The names go into the .sby `[files]` block so sby stages them in `src/`
    next to the sources that include them.

    A directive may name a SOURCE the file list already carries (OpenTitan's
    `` `include "prim_assert.sv" `` is the measured case). Those are skipped:
    they are already staged, and listing the same name twice in `[files]` is a
    second claim about one file.
    """
    staged = set(already or [])
    names: List[str] = []
    # THE EXPERT-AUTHORED PROPERTY FRAGMENT, staged like any other include.
    # `formal_harness_gen` emits `` `include "formal_expert_properties.svh" ``
    # inside the harness when this file is present; sby copies every `[files]`
    # entry into its own `src/`, so without this line the include would resolve
    # in `formal/` and NOT in the directory yosys actually reads from. Staged
    # but never READ, exactly like the header case below: it is a fragment, and
    # handing a macro body to `read_verilog` is what that rule exists to stop.
    _expert = formal_dir / EXPERT_PROPERTIES_SVH
    if _expert.is_file() and _expert.name not in staged:
        names.append(_expert.name)
        staged.add(_expert.name)
    for h in resolve_include_headers(list(rtl)):
        if h.name in staged:
            continue
        dst = formal_dir / h.name
        try:
            if h.resolve() != dst.resolve():
                shutil.copy2(h, dst)
        except OSError:
            continue
        names.append(h.name)
    return names


def _sha256_file(path: Path) -> Optional[str]:
    try:
        import hashlib
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def proof_inputs(sby_path: Path, formal_dir: Path) -> dict:
    """R-0924-2 r2 — THE SOURCES THIS PROOF READ, by content.

    Every `[files]` entry of the .sby, hashed from sby's own `src/` copy in a
    task work directory (what the engine actually read), else from the staged
    file as it stands the moment sby returns. A consumer that inspects a
    harness compares against this, so a harness rewritten after the proof —
    by a later generate whose proof never ran (ENV_UNAVAILABLE / emit-only) —
    is never paired with this proof."""
    text = sby_path.read_text(errors="replace")
    names: List[str] = []
    in_files = False
    for line in text.splitlines():
        ls = line.strip()
        if ls.startswith("[") and ls.endswith("]"):
            in_files = ls == "[files]"
            continue
        if in_files and ls:
            names.append(ls.split()[-1])
    srcs = sorted(d / "src" for d in formal_dir.glob(f"{sby_path.stem}*")
                  if (d / "src").is_dir())
    files: Dict[str, Optional[str]] = {}
    source = "staged"
    for n in names:
        base = Path(n).name
        copy = next((d / base for d in srcs if (d / base).is_file()), None)
        if copy is not None:
            source = f"sby src ({copy.parent.parent.name})"
        files[base] = _sha256_file(copy if copy is not None else formal_dir / base)
    return {"source": source, "files": files}


def _prove_engine_mode(project: Path, requested: str) -> str:
    """`direct` or `dual` for the standard prove task (see `run`)."""
    if requested in ("direct", "dual"):
        return requested
    if requested != "auto":
        raise ValueError(f"prove_engines must be auto|direct|dual, not {requested!r}")
    import librelane_contract as _ll
    mode = _ll.selected_mode(project, "5")
    # step 5 has no LibreLane arm; `librelane` there names nothing to run.
    return "dual" if mode == "dual" else "direct"


def run(project: Path, harness: Optional[Path] = None,
        rtl: Optional[List[Path]] = None, top: Optional[str] = None,
        sby: Optional[Path] = None, container: Optional[str] = _pin.default_container_name(),
        bmc_depth: int = 12, safety_depth: int = 20,
        timeout: int = 900,
        invariant_harness: Optional[Path] = None,
        engine_backend: str = "auto",
        mem_limit_kb: Optional[int] = None,
        emit_only: bool = False,
        prove_engines: str = "auto") -> dict:
    """Author the .sby, run the proof, and record an HONEST verdict.

    `prove_engines`: `direct` = `abc pdr` alone; `dual` = `abc pdr` AND
    `smtbmc yices` k-induction on the same claim, folded to the better honest
    verdict (`fold_prove_arms`); `auto` = the project's step-5 switch
    (`phase3/librelane_switch.json` `{"steps":{"5":"dual"}}`, read by
    `librelane_contract.selected_mode`), `direct` when absent.

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
    # The canonical runner also supplies its image name when it is already
    # inside that image. Probe and execute the installed toolchain there.
    if container and _ce.local_exec_mode("formal_property_run"):
        container = None
    formal_dir = _pl.formal_dir(project)
    formal_dir.mkdir(parents=True, exist_ok=True)
    _clear_program_receipt(formal_dir)

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
    chip_read: Optional[dict] = None
    if inv_h is not None and inv_h.is_file():
        # ---- invariant-strengthened (auxiliary-invariant) datapath proof ----
        if not rtl or top is None:
            return {"verdict": "ERROR", "rc": 1,
                    "reason": "invariant harness needs --rtl/--top"}
        prags = parse_harness_pragmas(inv_h.read_text())
        # CORRECTED (T91): `abc pdr` is NOT the only unbounded engine sby
        # drives in `mode prove` — `smtbmc yices` completes a k-induction
        # proof there (MEASURED, see `KIND_PROVE_ENGINE`; the standard harness
        # path runs it as a second arm under `prove_engines="dual"`). What IS
        # true: a stronger OSS datapath engine (btormc/pono over BTOR2 via
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
        staged_hdrs = _stage_include_headers(rtl, formal_dir,
                                             staged_rtl)
        sby_text = emit_invariant_sby(
            staged_rtl, inv_h.name, top, prags["connects"], prags["chparams"],
            tasks=prags.get("tasks"),
            prove_engine=prove_engine, prove_depth=max(40, safety_depth),
            bmc_depth=bmc_depth, include_files=staged_hdrs)
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

    # A REUSED .sby IS A STALE ONE, and staleness here is not cosmetic.
    # `formal_harness_gen` emits `` `include "formal_expert_properties.svh" ``
    # into the harness the moment that fragment exists; a .sby written BEFORE
    # it existed does not list it, sby stages every `[files]` entry into its
    # own `src/` and nothing else, and yosys then dies with
    #     ERROR: Can't open include file `formal_expert_properties.svh'!
    # turning a proof that passes into ERROR / INCONCLUSIVE. MEASURED exactly
    # that way on the first run of this path. The repair is the smallest one
    # that can be right: a task file that names a source must stage it.
    if sby_path is not None and sby_path.is_file():
        _ensure_expert_fragment_staged(sby_path, formal_dir)
        _ensure_expert_observers_bound(sby_path, formal_dir)

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
        staged_hdrs = _stage_include_headers(rtl, formal_dir,
                                             staged_rtl)
        # Observers from the harness AND the expert fragment it includes — an
        # expert's `@observe` is bound exactly like the generator's (review M8).
        _observers = parse_observers(_harness_texts(None, formal_dir, harness))
        # R-0915-157: the chip's own define decision for the DUT read
        import _chip_synth_read as _csr
        _dut_macros = _csr.staged_macro_files(project)
        _dut_simdef, _ = _csr.chip_sim_define(rtl, _dut_macros)
        # R-0915-157 round 9: the exact chip read this proof proves, under
        # the top the harness generator named (see results["chip_read"])
        try:
            _crtop = json.loads((formal_dir / "property_contract.json")
                                .read_text()).get("chip_read_top")
        except (OSError, ValueError):
            _crtop = None
        if _crtop:
            chip_read = _csr.chip_read_record(rtl, _dut_macros, _crtop)
        _mode = _prove_engine_mode(project, prove_engines)
        _kind = None
        if _mode == "dual":
            if emit_only or engine_availability.get("yices-smt2"):
                _kind = KIND_PROVE_ENGINE
            else:
                engine_note = ("prove_engines=dual requested; yices-smt2 is "
                               "ABSENT, so only abc pdr ran — no second arm "
                               "was fabricated")
        # The proof artifact is named for the DUT (`top`), while the formal
        # harness normally wraps that DUT in its own module. Yosys must prep
        # the module actually read as the proof root.
        _htxt = hdst.read_text(errors="replace")
        _htxt = re.sub(r"/\*.*?\*/|//[^\n]*", "", _htxt, flags=re.S)
        _hm = re.search(r"\bmodule\s+(?:automatic\s+|static\s+)?([A-Za-z_$][\w$]*)",
                        _htxt)
        _harness_top = _hm.group(1) if _hm else top
        # read_verilog treats a hierarchical expression in the harness as an
        # implicit free wire. read_slang resolves it during elaboration and
        # rejects a misspelled path (measured on the shipped SV frontend).
        # Use that frontend up front for an immediate assertion with a direct
        # reference; a concurrent SVA still follows the older guarded path.
        _full_harness = _harness_texts(None, formal_dir, harness)
        _direct = unbound_hierarchical_refs(_full_harness)
        _direct_slang = bool(_direct and
                             re.search(r"\bassert\s*\(", _full_harness) and
                             not re.search(r"\bassert\s+property\b", _full_harness))
        sby_text = emit_sby(staged_rtl, harness.name, top,
                            safety_depth=safety_depth, bmc_depth=bmc_depth,
                            include_files=staged_hdrs, observers=_observers,
                            dut_simdef=_dut_simdef, kind_engine=_kind,
                            harness_top=_harness_top,
                            frontend="read_slang" if _direct_slang else "read_verilog")
        sby_path = formal_dir / f"{top}_formal.sby"
        sby_path.write_text(sby_text)
    else:
        # a .sby already exists: ensure its [files] sources are staged
        cfg_text = sby_path.read_text()
        for line in cfg_text.splitlines():
            ls = line.strip()
            if (ls.endswith((".v", ".sv", ".svh", ".vh"))
                    and "/" in ls and Path(ls).is_file()):
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

    # 1c) R-0915-144 — REFUSE A PROPERTY OVER `<inst>.<net>` BEFORE IT RUNS --
    # Such a reference is an undriven local wire to the engine (see
    # `unbound_hierarchical_refs`), so whatever the proof said would be about a
    # free variable, not the design. Refused by name; nothing is proved.
    _htext = _harness_texts(sby_path, formal_dir, harness)
    _refusal_results_name = (
        f"{top or (sby_path.stem if sby_path else 'formal')}_inductive_results.json"
        if inv_h is not None else "results.json")
    _hier = unbound_hierarchical_refs(_htext)
    _sby_text = sby_path.read_text(errors="replace") if sby_path else ""
    _slang_read = ("read_slang" in _sby_text and
                   "read_verilog" not in _sby_text)
    if _hier and not _slang_read:
        return _refuse_hierarchical(formal_dir, project, sby_path, _hier,
                                    "the harness text",
                                    results_name=_refusal_results_name)
    # Every `@observe` anywhere in what the proof reads must be BOUND by the
    # task file that runs it. An unbound observer is an undriven wire — the
    # same free variable as `dut.<net>` — so it is refused the same way. This
    # is what catches a REUSED .sby written before the observers existed.
    _unreadable = unreadable_observers(_htext)
    if _unreadable:
        return _refuse_hierarchical(formal_dir, project, sby_path, _unreadable,
                                    "observer pragma(s) that cannot be read whole",
                                    results_name=_refusal_results_name)
    _unbound = observer_binding_mismatches(_htext, _sby_text)
    if _unbound:
        return _refuse_hierarchical(formal_dir, project, sby_path, _unbound,
                                    "observer binding(s) that do not match what the harness declares",
                                    results_name=_refusal_results_name)

    # 2) run sby -------------------------------------------------------------
    eff_mem_kb = (mem_limit_kb if mem_limit_kb is not None
                  else memory_limit_kb())
    transcript = _run_sby(sby_path, formal_dir, container, timeout,
                          mem_limit_kb=eff_mem_kb)
    log_path = formal_dir / f"{sby_path.stem}.sby.log"
    log_path.write_text(transcript)

    # 2a) THE FRONTEND SPLIT — retry the READ, once, with `read_slang` -------
    # See `frontend_aborted_the_read` for the measurement and for why this is a
    # retry rather than a new default. Strictly ONE retry, and only when the
    # first attempt shows a READ abort on a construct a full SV-2017 frontend
    # accepts — an inconclusive PROOF never reaches here.
    # The .sby may have been supplied rather than emitted by this run, in
    # which case this run has no staged file list to re-emit from and must
    # leave the caller's artefact alone.
    if frontend_aborted_the_read(transcript) and "staged_rtl" in dir():
        _slang_note = ("read_verilog -sv aborted the READ; re-read with "
                       "read_slang (SV-2017)")
        _reemitted = False
        try:
            import formal_harness_gen as _fhg
            # `read_slang` refuses SVA, so the harness has to come back in the
            # equivalent IMMEDIATE form. Regenerated by the SAME author from
            # the SAME design input — never rewritten in place, so the harness
            # on disk always matches the properties the proof is about.
            _regen = _fhg.generate(project=project, top=top,
                                   assertion_form="immediate",
                                   container=container)
            _reemitted = _regen.get("verdict") == "EMITTED"
        except Exception:   # noqa: BLE001 — no regen, no retry
            _reemitted = False
        if _reemitted:
            sby_path.write_text(emit_sby(
                staged_rtl, harness.name, top,
                safety_depth=safety_depth, bmc_depth=bmc_depth,
                include_files=staged_hdrs, frontend="read_slang",
                observers=parse_observers(
                    _harness_texts(None, formal_dir, harness)),
                harness_top=_harness_top))
            transcript = _run_sby(sby_path, formal_dir, container, timeout,
                                  mem_limit_kb=eff_mem_kb)
            transcript = (f"# {_slang_note}\n" + transcript)
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
    if env_gap is None and not engine_spoke(transcript) \
            and engine_availability.get("_env_reachable") is False:
        # THE PROBE ALREADY ANSWERED. `detect_engines` decided reachability
        # before any solver was launched and recorded it as `_env_reachable`;
        # the emission then hung entirely on recognising a message shape, so a
        # runtime wording nobody had anticipated fell through to a fabricated
        # proof verdict. Keyed on the probe's own verdict instead, the manifest
        # cannot be out-run by a new error string. `is False` (never falsy):
        # an absent key means no probe ran and must not be read as a gap.
        env_gap = unreachable_env_gap(transcript, container)
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

    # The same refusal, from the ENGINE's own words: a reference the text scan
    # could not see (a macro, an include) still shows up as yosys declaring it
    # implicitly. A proof over it is not reported.
    _implicit = sorted(set(_IMPLICIT_HIER_RE.findall(transcript)))
    if _implicit:
        return _refuse_hierarchical(formal_dir, project, sby_path, _implicit,
                                    "the yosys transcript",
                                    results_name=_refusal_results_name)

    # 3) parse + build results ----------------------------------------------
    cfg = parse_sby_config(sby_path.read_text())
    lp = parse_sby_log(transcript, sby_stem=sby_path.stem, seed=cfg)
    top_name = top or sby_path.stem
    ev_rel = str(log_path.relative_to(project))
    sby_rel = str(sby_path.relative_to(project))
    results = build_results(top_name, cfg, lp, ev_rel, sby_rel)
    results["proof_inputs"] = proof_inputs(sby_path, formal_dir)
    if inv_h is None:
        # R-0915-144 — the program answers the structural obligations the
        # contract routes to it, BEFORE the contract is attached, so the
        # read-back below sees this run's receipt and evidence.
        _program_discharge(formal_dir, container, _htext,
                           _model_texts(sby_path, formal_dir, harness))
    _attach_property_contract(results, formal_dir, harness or inv_h)
    if chip_read is not None:
        results["chip_read"] = chip_read
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


def _model_texts(sby_path: Optional[Path], formal_dir: Path,
                 harness: Optional[Path]) -> str:
    """EVERYTHING the proof model reads: the harness, the expert fragment and
    every `[files]` entry of the task file — the RTL and its headers included.
    `read_verilog -formal` defines FORMAL, so an `ifdef FORMAL assume(...)` in
    the RTL is a live constraint; scanning only the harness missed it (review
    round 2, M3)."""
    texts = [_harness_texts(sby_path, formal_dir, harness)]
    if sby_path is not None and sby_path.is_file():
        _, _, files_block = sby_path.read_text(errors="replace").partition("[files]")
        for line in files_block.splitlines():
            name = line.strip().split()[-1] if line.strip() else ""
            if not name:
                continue
            f = Path(name) if Path(name).is_absolute() else formal_dir / name
            if f.is_file() and f.name != EXPERT_PROPERTIES_SVH:
                texts.append(f.read_text(errors="replace"))
    return "\n".join(texts)


def _harness_texts(sby_path: Optional[Path], formal_dir: Path,
                   harness: Optional[Path]) -> str:
    """The harness a proof reads, plus the expert fragment it includes."""
    texts = []
    cands = [harness] if harness is not None else []
    if sby_path is not None and sby_path.is_file():
        for line in sby_path.read_text(errors="replace").splitlines():
            ls = line.strip()
            if ls.startswith("formal_") and ls.endswith((".sv", ".v")):
                cands.append(formal_dir / ls)
    cands.append(formal_dir / EXPERT_PROPERTIES_SVH)
    seen = set()
    for c in cands:
        if c is None or not c.is_file() or c.resolve() in seen:
            continue
        seen.add(c.resolve())
        texts.append(c.read_text(errors="replace"))
    return "\n".join(texts)


def _refuse_hierarchical(formal_dir: Path, project: Path,
                         sby_path: Optional[Path], refs: List[str],
                         where: str, results_name: str = "results.json") -> dict:
    """Write the refusal as the canonical results.json and return it."""
    reason = (
        f"HIERARCHICAL_REFERENCE_UNBOUND (R-0915-144): {where} references "
        f"{', '.join(refs)}. In this flow's formal path such a reference is an "
        f"implicitly declared, undriven local wire -- a free variable -- so a "
        f"property over it is not a statement about the design. Make DUT state "
        f"observable with a `// @observe <wire> = <inst>.<net>` observer "
        f"instead. NOTHING was proved and nothing was refuted.")
    results = {
        "program": "formal_property_run", "verdict": "ERROR",
        "all_proved": False, "property_count": 0, "properties": [],
        "refusal": reason, "hierarchical_references": refs,
        "sby": (str(sby_path.relative_to(project))
                if sby_path is not None else None),
    }
    # The INDUCTIVE path never writes the main results.json (it has its own
    # `<top>_inductive_results.json`): an opt-in inductive run must never
    # replace a standard Step-5 result (round-7 review).
    _aa.write_json(formal_dir / results_name, results)
    results["results_file"] = results_name
    results["rc"] = RC_PROPERTY_FAILED
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
    # Re-reviewed after the prove-arm/resource changes: build_results still
    # permits all-bounded tasks to say PASS while unbounded_proved is false;
    # the rule below must continue to demote that archived claim to PARTIAL.
    decision_digest="b6967ecacf30cce0e66da91ac89d9d68b63356fb7177fdb5ac4a5adc24f22abb",
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
    ap.add_argument("--container", default=_pin.default_container_name(),
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
    ap.add_argument("--prove-engines", default="auto", dest="prove_engines",
                    choices=("auto", "direct", "dual"),
                    help="direct = abc pdr; dual = abc pdr + smtbmc yices "
                         "k-induction, better verdict kept; auto = the "
                         "project's step-5 switch (default direct)")
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
              emit_only=args.emit_only,
              prove_engines=args.prove_engines)
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
