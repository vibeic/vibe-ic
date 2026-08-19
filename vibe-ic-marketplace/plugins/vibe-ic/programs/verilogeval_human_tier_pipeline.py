#!/usr/bin/env python3
"""verilogeval_human_tier_pipeline.py — the VerilogEval-HUMAN (code-complete,
ICCAD-2023) TIER-1→5 CONVERGE PIPELINE.

GOAL (owner directive 2026-06-23): apply the SAME 5-tier converge model the CVDP
pipeline (cvdp_solve_pipeline.py) uses, to the VerilogEval-HUMAN code-complete
benchmark. Each problem is a quadruple in dataset_code-complete-iccad2023/:

    ProbNNN_<name>_ifc.txt     the EXACT module interface (ANSI header)
    ProbNNN_<name>_prompt.txt  the spec (prose + the repeated interface)
    ProbNNN_<name>_ref.sv      the GOLDEN RefModule (verification/RCA ONLY)
    ProbNNN_<name>_test.sv     the official testbench (binds TopModule + RefModule)

The 5-tier model, mapped to VE-human:

  Tier 1  a registry/canonical DETERMINISTICALLY emits RTL that PASSES the
          official _test.sv under `iverilog -g2012 && vvp` (NO AI in the loop).
          A problem is Tier1 ONLY when the emit is iverilog-VERIFIED to pass —
          a registry hit that does NOT verify is NOT Tier1.
  Tier 2  a program extracts a COMPLETE spec (the _ifc.txt gives the EXACT
          interface; plus every structure the prompt states) and an AI authors
          from it + the conformance gate. Most-stable AI tier.
  Tier 3  a MEANINGFUL conformance gate (interface from _ifc.txt +/- structure)
          constrains an AI author; the spec is not fully COMPLETE.
  Tier 4  too-incomplete to gate meaningfully.
  Tier 5  a GENUINE dataset floor — PROVEN by running _ref.sv against _test.sv;
          only golden-FAILS-its-own-test is a real floor.

§4.05 NO-LEAK / NO-CHEAT (binding):
  * The gate ONLY enforces facts that ARE in the extracted spec / _ifc.txt. It
    NEVER demands an unstated fact (false-rejecting a correct AI solve is the
    worst failure of a stabilizer).
  * The golden _ref.sv is NEVER fed to the solver / extractor / gate. It is read
    ONLY by the Tier-5 floor prover (run ref+test under iverilog) and by the
    Tier-1 verifier (the official _test.sv already instantiates RefModule, so
    verification compiles ref+test together — that is the benchmark's own
    scoring path, not a leak into authoring).
  * Tier classification + gate come from the _ifc.txt interface + the prompt
    prose (both submitter-visible). gate_check parses the CANDIDATE header/body.

GENERAL + chip-AGNOSTIC: every decision keys on STRUCTURE (the ANSI interface
shape, the stated artifact/structure, generic Verilog grammar), NEVER on a
problem id or a design name.

Public API
    classify(prob) -> int                      the tier integer
    build_gate(prob) -> dict                   the conformance gate
    gate_check(prob, candidate_rtl) -> dict    {pass, violations}
    solve(prob) -> {tier, rtl, gate, ...}      full result (Tier1 emits RTL)
    load_problem(dataset_dir, stem) -> dict    read the 4 files for one problem
    floor_evidence(prob) -> str|None           ref-fails-test proof (Tier5)
    tier1_verify(prob, rtl) -> (bool, str)     iverilog+vvp the emit vs _test.sv

CLI
    python3 verilogeval_human_tier_pipeline.py --dataset DIR --dist
    python3 verilogeval_human_tier_pipeline.py --dataset DIR --id Prob069_truthtable1
    python3 verilogeval_human_tier_pipeline.py --dataset DIR --verify-tier1   # iverilog-check every Tier1
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Reused (import, read — the shipped deterministic emitter), §4.05 SKIP-on-doubt.
import spec_artifact_registry as _registry  # noqa: E402  generate(text,top)->(kind,rtl)
# Supplemental VE-HUMAN structural Tier-1 emitters — a STRICT add-only fallback,
# consulted only on a registry miss/fail (see deterministic_emit). §4.05-clean.
import verilogeval_human_tier1_solvers as _supplemental_solvers  # noqa: E402
import semantic_spec_floor_check as _semfloor  # noqa: E402  golden-vs-prompt semantic floor

TIER_PROGRAM = 1   # registry DETERMINISTICALLY emits RTL that iverilog-PASSES _test.sv
TIER_AI_EMIT = 2   # COMPLETE spec (ifc interface + every stated structure) + gate
TIER_AI_GATED = 3  # MEANINGFUL interface gate (from _ifc.txt) constrains the AI
TIER_UNGATED = 4   # too-incomplete to gate meaningfully
TIER_FLOOR = 5     # genuine floor — PROVEN by ref-fails-its-own-test

_IVERILOG_TIMEOUT_S = 120  # generous: the longest golden sim (200k samples) runs
                           # in <1s, but a WRONG candidate emit can induce a
                           # combinational loop that never settles — the wall-clock
                           # cap turns that into an honest FAIL, not a hang.


# --------------------------------------------------------------------------- #
# (0) problem IO — read the 4 dataset files for one problem stem
# --------------------------------------------------------------------------- #
def discover_problems(dataset_dir: str) -> List[str]:
    """Every problem stem (`ProbNNN_<name>`) in the dataset, sorted by number."""
    d = Path(dataset_dir)
    stems = sorted({p.name[:-len("_ifc.txt")] for p in d.glob("*_ifc.txt")})
    def _key(s: str) -> Tuple[int, str]:
        m = re.match(r"Prob(\d+)", s)
        return (int(m.group(1)) if m else 1 << 30, s)
    return sorted(stems, key=_key)


def load_problem(dataset_dir: str, stem: str) -> dict:
    """Read the interface / prompt / ref / test for one problem. ref_sv/test_sv
    paths are carried (NOT fed to the solver) for the Tier-5 prover + Tier-1
    verifier only."""
    d = Path(dataset_dir)
    def _read(suf: str) -> str:
        p = d / f"{stem}{suf}"
        return p.read_text(errors="replace") if p.exists() else ""
    return {
        "stem": stem,
        "id": stem,
        "ifc": _read("_ifc.txt"),
        "prompt": _read("_prompt.txt"),
        "ref_path": str(d / f"{stem}_ref.sv"),
        "test_path": str(d / f"{stem}_test.sv"),
    }


# --------------------------------------------------------------------------- #
# (1) interface parse from _ifc.txt — the EXACT ports the harness binds
# --------------------------------------------------------------------------- #
_MODULE_HEADER_RE = re.compile(
    r"\bmodule\s+(\w+)\s*(?:#\s*\((?P<params>.*?)\)\s*)?\((?P<ports>.*?)\)\s*;",
    re.S)

# one port declaration inside an ANSI header port list.
_PORT_RE = re.compile(
    r"\b(input|output|inout)\b\s+(?:(?:wire|reg|logic)\b\s*)?(?:signed\b\s*)?"
    r"(?:\[\s*([^\]:]+)\s*:\s*([^\]]+)\s*\]\s*)?(\w+)")


def _range_width(hi: Optional[str], lo: Optional[str]) -> Optional[int]:
    """Bit-width of `[hi:lo]` when BOTH bounds are integer literals; 1 when no
    range; None for a parameter-expression range (unknown-but-present width —
    never enforce a literal width on it, §4.05)."""
    if hi is None or lo is None:
        return 1
    try:
        return abs(int(hi.strip()) - int(lo.strip())) + 1
    except ValueError:
        return None


def parse_interface(ifc_text: str) -> Optional[Tuple[str, List[dict]]]:
    """(module_name, ports[{name,dir,width}]) from an ANSI header, or None.
    The VE-human _ifc.txt is ALWAYS a clean ANSI header — this is the EXACT
    interface the official _test.sv binds, so it pins the contract completely."""
    m = _MODULE_HEADER_RE.search(ifc_text or "")
    if not m:
        return None
    name = m.group(1)
    ports_text = m.group("ports") or ""
    ports: List[dict] = []
    for pm in _PORT_RE.finditer(ports_text):
        d, hi, lo, pname = pm.groups()
        ports.append({"name": pname, "dir": d, "width": _range_width(hi, lo)})
    return name, ports


# --------------------------------------------------------------------------- #
# (2) structure extraction from the prompt prose — every STATED structure
# --------------------------------------------------------------------------- #
def _extract_structures(prompt_text: str) -> dict:
    """Recover the structures the prompt STATES, via the shipped artifact
    registry recognizers. Only what the registry actually recognizes is carried
    (§4.05: we never invent a structure). Returns a dict of token lists the gate
    requires the candidate to REPRESENT."""
    try:
        artifacts = _registry.detect(prompt_text)
    except Exception:
        artifacts = []
    enum_modes: List[str] = []
    fsm_states: List[str] = []
    register_names: List[str] = []
    for a in artifacts:
        s = a.get("structured") or {}
        # FSM state labels
        for k in ("states", "state_names"):
            for v in (s.get(k) or []):
                tok = _struct_key(v)
                if tok and tok not in fsm_states:
                    fsm_states.append(tok)
        # enumerated modes / named constants
        for k in ("modes", "enum_modes", "labels"):
            for v in (s.get(k) or []):
                tok = _struct_key(v)
                if tok and tok not in enum_modes:
                    enum_modes.append(tok)
    return {
        "enum_modes": enum_modes,
        "fsm_states": fsm_states,
        "register_names": register_names,
        "artifact_types": [a.get("type") for a in artifacts],
    }


def _struct_key(item) -> Optional[str]:
    if isinstance(item, str):
        return item.strip() or None
    if isinstance(item, dict):
        for k in ("name", "symbol", "state", "mode", "label", "field", "reg"):
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


# --------------------------------------------------------------------------- #
# (3) build the CONFORMANCE GATE
# --------------------------------------------------------------------------- #
def build_gate(prob: dict) -> dict:
    """Distill the _ifc.txt interface + stated structures into the conformance
    gate. The interface comes from the _ifc.txt header (the EXACT contract the
    harness binds) — so the VE-human gate ALWAYS has a meaningful port set when
    the ifc parses (which it always does for this dataset). Every structure entry
    is a token the candidate must REPRESENT; nothing un-recognized is demanded."""
    parsed = parse_interface(prob.get("ifc") or "")
    if parsed is None:
        # fall back to the interface repeated inside the prompt
        parsed = parse_interface(prob.get("prompt") or "")
    module_name, ports = (parsed or (None, []))
    structures = _extract_structures(prob.get("prompt") or "")
    # §4.05 FALSE-REJECT GUARD (adversarial self-check 2026-06-23): an FSM
    # state-DIAGRAM names its states (`OFF`/`ON`, `A`..`F`, `000`..) purely as a
    # labeling convention — a CORRECT design (incl. the GOLDEN _ref.sv itself,
    # which renames the prompt's `OFF/ON` to `A/B`) may use ANY state encoding /
    # any label / a bare binary constant. Demanding the prompt's literal state
    # token to appear as an RTL identifier FALSE-REJECTS the golden and every
    # legitimately-renamed correct author (12 verified-correct Tier1 FSMs failed
    # their OWN gate on this rule). State names are therefore NOT enforced; only
    # the INTERFACE (ports — the hard contract the _test.sv binds) is. Enum-mode
    # and register tokens ARE kept: those are spec-mandated symbolic constants /
    # named registers a correct design must surface, not free-choice labels.
    # (For the VE-human dataset the registry recovers no enum/register tokens, so
    # this list is empty in practice; it stays for cross-dataset reuse.)
    return {
        "module_name": module_name,
        "ports": ports,
        "structures": {
            "enum_modes": structures["enum_modes"],
            "fsm_states": [],  # NOT enforced — see §4.05 false-reject guard above
            "register_names": structures["register_names"],
        },
        "fsm_states_seen": structures["fsm_states"],  # diagnosis only, NOT a gate
        "artifact_types": structures["artifact_types"],
    }


def _interface_complete(prob: dict, gate: dict) -> bool:
    """COMPLETE := the gate carries the exact module name + a fully-resolved port
    set (every port has a known integer width — no unknown param-expression
    widths) AND the prompt states no un-recovered structure beyond the ports.
    For VE-human the _ifc.txt is always literal-width, so the interface itself is
    COMPLETE; this returns True whenever every port width is an int."""
    if not gate.get("module_name") or not gate.get("ports"):
        return False
    for p in gate["ports"]:
        if not isinstance(p.get("width"), int):
            return False
    return True


# --------------------------------------------------------------------------- #
# (4) Tier-5 floor prover — run _ref.sv against _test.sv under iverilog
# --------------------------------------------------------------------------- #
# #1437 — the marker _run_iverilog writes when the COMPILER ITSELF was absent, and
# the only string floor_evidence() accepts as "no compiler ran". Deliberately
# NARROW: it is this module's own sentinel plus the repo-wide `COMMAND_NOT_FOUND`
# convention (_watchdog, design_one_shot_runner, phase{1_doc,3}_one_shot_runner),
# never a bare "No such file or directory" — iverilog prints that for a missing
# `include`, which is a REAL compile error about the design, and widening the
# predicate to it would silently stop reporting genuine compile failures.
_TOOL_ABSENT = "iverilog: COMMAND_NOT_FOUND"

# The PASS form of the official testbench's own verdict line — what the forgery
# gate (vibe-ic#1745) has to keep a candidate from PRINTING. The scorer below
# decides PASS by matching `Mismatches: N in M samples` on the SIMULATION's
# stdout, and the DUT shares that stdout, so a candidate carrying
# `$display("Mismatches: 0 in 20 samples")` forges its own verdict. Kept in the
# same shape the harness greps for, so there is no second vocabulary to drift.
_MISMATCH_PASS_REGEX = r"Mismatches:\s*0\s+in\s+\d+\s+samples"


def _tool_was_absent(log: str) -> bool:
    """True iff `log` is _run_iverilog's own absent-compiler sentinel."""
    return _TOOL_ABSENT in (log or "")


def _run_iverilog(top_sv_text: Optional[str], ref_path: str, test_path: str,
                  top_name: str = "TopModule") -> Tuple[bool, str]:
    """Compile + run a TopModule (given as text, or — when top_sv_text is None —
    aliased from the ref so the harness can grade the GOLDEN against itself) plus
    the ref + the official test, under iverilog -g2012 && vvp. Returns
    (passed, log). PASS := the test reports `Mismatches: 0` and did not TIMEOUT.

    NOTE on the Tier-5 prover (top_sv_text is None): the test binds BOTH TopModule
    and RefModule. To grade the GOLDEN against its OWN test we must supply a
    TopModule — we make it by RENAMING the ref's RefModule to TopModule (a pure
    rename of the golden, the only honest way to ask "does the golden pass its own
    test"). This is the §4.05-clean floor proof: a real floor is the golden
    failing here."""
    # vibe-ic#1745 — FORGERY GATE, BLOCKING, ahead of the compile. `top_sv_text
    # is None` is the Tier-5 floor probe, whose "candidate" is the dataset's own
    # golden rather than an answer to the question: the gate has nothing to
    # protect there and could only FALSE-FLOOR a sound problem, so it is scoped
    # to a SUBMITTED candidate. The gate can only turn a PASS into a FAIL, never
    # the reverse; an unavailable gate returns clean rather than manufacturing a
    # failure it did not observe.
    if top_sv_text is not None:
        try:
            import harness_verdict_forgery_gate as _hvfg
            _g = _hvfg.gate(top_sv_text, _MISMATCH_PASS_REGEX)
            if _g["verdict"] == _hvfg.FORGERY:
                return False, _g["reason"]
        except ImportError:
            pass          # gate unavailable: never MANUFACTURE a failure
    ref_text = Path(ref_path).read_text(errors="replace")
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        if top_sv_text is None:
            # alias the golden as TopModule (rename RefModule -> TopModule).
            top_text = re.sub(r"\bRefModule\b", top_name, ref_text)
        else:
            top_text = top_sv_text
        (tdp / "top.sv").write_text(top_text)
        (tdp / "ref.sv").write_text(ref_text)
        (tdp / "test.sv").write_text(Path(test_path).read_text(errors="replace"))
        sim = tdp / "sim.vvp"
        try:
            # watchdog-exempt: bounded single-file iverilog compile (elaboration/sim build); fixed budget adequate — not an open-ended EDA generator
            cp = subprocess.run(
                ["iverilog", "-g2012", "-o", str(sim),
                 str(tdp / "top.sv"), str(tdp / "ref.sv"), str(tdp / "test.sv")],
                capture_output=True, text=True, timeout=_IVERILOG_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return False, "iverilog: COMPILE TIMEOUT"
        except FileNotFoundError as e:
            # #1437 — an ABSENT iverilog raised here, so callers got a traceback.
            # It must NOT fall into the `returncode != 0` arm below either: that
            # arm's log reads "iverilog compile error", and floor_evidence() turns
            # a non-pass into "golden _ref.sv FAILS its own _test.sv" — a
            # benchmark-DEFECT claim. A compiler that never ran cannot support it,
            # so emit the marker floor_evidence() recognises instead.
            return False, f"{_TOOL_ABSENT}: {e}"
        if cp.returncode != 0:
            return False, "iverilog compile error:\n" + (cp.stderr or cp.stdout or "")
        try:
            rp = subprocess.run(["vvp", str(sim)], capture_output=True, text=True,
                                cwd=str(tdp), timeout=_IVERILOG_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return False, "vvp: SIMULATION TIMEOUT"
        except FileNotFoundError as e:
            # #1437 — the design COMPILED but the simulator could not be RUN.
            # Same reasoning as the compile arm: floor_evidence() must not read
            # this as the golden failing its own test.
            return False, f"{_TOOL_ABSENT}: {e}"
        out = (rp.stdout or "") + (rp.stderr or "")
        # The ONLY authoritative verdict is the harness's own `Mismatches: N in M`
        # summary line. NOTE: the long-running problems' testbench arms an internal
        # `#1000000` watchdog that PRINTS the literal word "TIMEOUT" and then the
        # sim still reaches `$finish` with 0 mismatches — that benign watchdog
        # print is NOT a failure (treating it as one was a FALSE-floor bug). A
        # genuine timeout is the WALL-CLOCK subprocess.TimeoutExpired handled
        # above; here we grade STRICTLY on the Mismatches summary.
        m = re.search(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples", out)
        if not m:
            return False, "no Mismatches summary line in output:\n" + out[-400:]
        nbad, ntot = int(m.group(1)), int(m.group(2))
        passed = (nbad == 0 and ntot > 0)
        return passed, f"Mismatches: {nbad} in {ntot} samples"


def floor_evidence(prob: dict) -> Optional[str]:
    """Return a cited reason iff this is a GENUINE Tier-5 floor. TWO defect classes:
    (1) STRUCTURAL — the GOLDEN _ref.sv FAILS the official _test.sv (broken pair).
    (2) SEMANTIC — the golden PASSES its own (golden-derived) test yet CONTRADICTS
        the prompt's own machine-extractable spec (a Karnaugh map, or an embedded
        'fix the bug' reference whose select polarity the golden inverts). The
        golden-derived TB can never catch this; an independent prompt-derived oracle
        (semantic_spec_floor_check) does. Conservative — (2) fires only on an
        unambiguous extraction + cited contradiction, never false-flooring a sound
        design; mere incompleteness is Tier 4, never Tier 5."""
    ref_p, test_p = prob.get("ref_path"), prob.get("test_path")
    if not (ref_p and test_p and Path(ref_p).exists() and Path(test_p).exists()):
        return None
    passed, log = _run_iverilog(None, ref_p, test_p)
    if _tool_was_absent(log):
        return None          # #1437 — no compiler ran; a floor cannot be claimed
    if not passed:
        return f"golden _ref.sv FAILS its own _test.sv ({log.splitlines()[0] if log else 'unknown'})"
    sem = _semfloor.semantic_floor_evidence(prob.get("prompt") or "",
                                            Path(ref_p).read_text(errors="replace"))
    if sem:
        return f"golden passes its own _test.sv but {sem}"
    return None


# --------------------------------------------------------------------------- #
# (5) Tier-1 deterministic emit + iverilog VERIFY
# --------------------------------------------------------------------------- #
def deterministic_emit(prob: dict) -> Tuple[Optional[str], Optional[str]]:
    """(artifact_type, rtl) for one problem. NO AI; §4.05 SKIP-on-doubt.

    Two deterministic sources, registry-FIRST so the existing 125 verified Tier1
    are NEVER perturbed (the registry hit that already verifies short-circuits
    before the supplemental solver is even consulted):

      1. the shared `spec_artifact_registry.generate()` over the PROMPT — the
         canonical, mutual-exclusion-checked emitter (owns the 125);
      2. ONLY when the registry MISSES (no hit) OR its hit does NOT iverilog-pass
         the official _test.sv, the supplemental VE-HUMAN structural solver
         (`verilogeval_human_tier1_solvers.emit`) is tried; its emit replaces the
         registry's iff it iverilog-VERIFIES. This rescues (a) the gatesv
         neighbour-vector emit the registry mis-widths, and (b) the
         FSM-by-inspection / full-Moore-FSM table shapes the registry SKIPs.

    The supplemental solver is a STRICT improvement: it is consulted only on a
    registry miss/fail and adopted only on a verified pass, so it can add Tier1s
    but never remove one. Each adopted emit is independently iverilog-proven by
    the caller's tier1_verify (the SOLE Tier1 authority)."""
    try:
        reg_kind, reg_rtl = _registry.generate(prob.get("prompt") or "", "TopModule")
    except Exception:
        reg_kind, reg_rtl = None, None
    # registry hit that already passes ⇒ keep it verbatim (preserves the 125;
    # no supplemental call, no behavioural change for every currently-Tier1 emit).
    if reg_rtl:
        ok, _log = tier1_verify(prob, reg_rtl)
        if ok:
            return reg_kind, reg_rtl
    # registry missed or its hit failed — try the supplemental structural solver.
    try:
        sup_kind, sup_rtl = _supplemental_solvers.emit(prob)
    except Exception:
        sup_kind, sup_rtl = None, None
    if sup_rtl:
        ok, _log = tier1_verify(prob, sup_rtl)
        if ok:
            return sup_kind, sup_rtl
    # neither produced a verified emit — return the registry's original result
    # (possibly a fired-but-failing hit) so the caller's fall-through logic
    # (tier1_ruled_out) is unchanged.
    return reg_kind, reg_rtl


_VERIFY_CACHE: Dict[Tuple[str, str], Tuple[bool, str]] = {}


def tier1_verify(prob: dict, rtl: str) -> Tuple[bool, str]:
    """iverilog-VERIFY that `rtl` (a candidate TopModule) PASSES the official
    _test.sv. This is the SOLE authority for Tier1 — a registry hit that does not
    verify here is NOT Tier1.

    Memoized on (test_path, rtl): `deterministic_emit` now verifies internally to
    pick the registry-vs-supplemental emit, and `solve`/`classify` verify the same
    (prob, rtl) again — the cache makes that repeat free (the verdict is a pure
    function of the candidate RTL + the fixed official test). The cache is a pure
    speed-up; it never changes a verdict."""
    if not rtl:
        return False, "no rtl"
    key = (prob.get("test_path") or "", rtl)
    hit = _VERIFY_CACHE.get(key)
    if hit is not None:
        return hit
    res = _run_iverilog(rtl, prob.get("ref_path"), prob.get("test_path"))
    _VERIFY_CACHE[key] = res
    return res


# --------------------------------------------------------------------------- #
# (6) classify + solve
# --------------------------------------------------------------------------- #
def classify(prob: dict, gate: Optional[dict] = None,
             verify_tier1: bool = True, tier1_ruled_out: bool = False) -> int:
    """The tier integer for this problem.

    verify_tier1=True (default + the honest setting): a registry emit is Tier1
    ONLY when iverilog confirms it passes _test.sv. verify_tier1=False is a CHEAP
    pre-pass (registry-hit ⇒ Tier1-candidate) used only by --dist-fast; the
    authoritative --dist always verifies.

    tier1_ruled_out=True: the caller (solve) ALREADY ran the iverilog Tier1
    verify and it FAILED — do NOT re-trust the registry hit (that was a bug: with
    verify_tier1=False the fall-through would re-emit and wrongly return Tier1)."""
    if not isinstance(prob, dict):
        return TIER_UNGATED
    # Tier 1 — deterministic emit that iverilog-PASSES the official test.
    if not tier1_ruled_out:
        kind, rtl = deterministic_emit(prob)
        if rtl:
            if not verify_tier1:
                return TIER_PROGRAM
            ok, _log = tier1_verify(prob, rtl)
            # GATE PARITY: Tier-1 requires the emit to also survive the gate's
            # conformance (not iverilog alone) — else the blind run can't emit it.
            if ok and not conformance_emit_blocked(prob, rtl):
                return TIER_PROGRAM
            # emit fired but does NOT pass iverilog OR the gate would block it — NOT Tier1.

    # Tier 5 — genuine floor (golden fails its own test).
    if floor_evidence(prob):
        return TIER_FLOOR

    if gate is None:
        gate = build_gate(prob)
    gate_meaningful = bool(gate.get("module_name")) and bool(gate.get("ports"))
    if gate_meaningful:
        # Tier 2 — interface COMPLETE (ifc gives exact literal-width ports) ⇒
        # the AI authors from a complete structured spec + gate.
        if _interface_complete(prob, gate):
            return TIER_AI_EMIT
        # Tier 3 — meaningful interface gate but a width unresolved.
        return TIER_AI_GATED
    # Tier 4 — nothing to gate (no parseable interface).
    return TIER_UNGATED


def conformance_emit_blocked(prob: dict, rtl: str, timeout: int = 60) -> List[str]:
    """Run the SAME `spec_conformance_check` the real Shape-C gate runs on a Tier-1
    emit; return the EMIT-BLOCKING rules that fire ([] = the gate would emit it).

    Closes the stability-test-vs-blind-run gap for the VE-Human pipeline: an emit
    that iverilog-PASSES but the gate BLOCKS can never reach the host TB, so it is
    NOT genuinely Tier-1. Single source of truth for the rule set:
    spec_conformance_check.EMIT_BLOCKING_CONFORMANCE_RULES (the same set the gate
    consults). On any tool/IO error returns [] (never fabricates a block)."""
    if not rtl or not rtl.strip():
        return []
    try:
        from spec_conformance_check import EMIT_BLOCKING_CONFORMANCE_RULES as _BLOCK
    except Exception:
        return []
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        (tdp / "TopModule.sv").write_text(rtl)
        (tdp / "prompt.txt").write_text(prob.get("prompt") or "")
        outj = tdp / "conf.json"
        try:
            subprocess.run(
                [sys.executable, str(_HERE / "spec_conformance_check.py"),
                 "--rtl-dir", str(tdp), "--spec", str(tdp / "prompt.txt"),
                 "--top", "TopModule", "--json", str(outj)],
                capture_output=True, text=True, timeout=timeout)
        except Exception:
            return []
        if not outj.exists():
            return []
        try:
            findings = json.loads(outj.read_text())
        except Exception:
            return []
        return sorted({f.get("rule") for f in findings
                       if isinstance(f, dict) and f.get("rule") in _BLOCK})


def solve(prob: dict, verify_tier1: bool = True) -> dict:
    """The pipeline entry point. Returns {tier, rtl, gate, artifact_type,
    verify_log, floor_reason}."""
    if not isinstance(prob, dict):
        return {"tier": TIER_UNGATED, "rtl": None, "gate": {}}
    gate = build_gate(prob)
    kind, rtl = deterministic_emit(prob)
    verify_log = None
    tier1_ruled_out = False  # an emit fired but FAILED iverilog verify
    if rtl and verify_tier1:
        ok, verify_log = tier1_verify(prob, rtl)
        # GATE PARITY: a Tier-1 emit must also survive the gate's conformance, not
        # iverilog alone — else the real blind run BLOCKs it (no_sample).
        blocked = conformance_emit_blocked(prob, rtl) if ok else []
        if ok and not blocked:
            return {"tier": TIER_PROGRAM, "rtl": rtl, "gate": gate,
                    "artifact_type": kind, "verify_log": verify_log}
        if blocked:
            verify_log = (verify_log or "") + " | gate-blocked: " + ",".join(blocked)
        rtl = None  # fired but failed verify (or gate-blocked) — not Tier1
        tier1_ruled_out = True  # do NOT let the fall-through re-trust the hit
    elif rtl and not verify_tier1:
        return {"tier": TIER_PROGRAM, "rtl": rtl, "gate": gate,
                "artifact_type": kind, "verify_log": "UNVERIFIED"}

    floor = floor_evidence(prob)
    if floor:
        g = dict(gate)
        g["floor_reason"] = floor
        return {"tier": TIER_FLOOR, "rtl": None, "gate": g,
                "artifact_type": kind, "verify_log": verify_log}

    # tier1 already attempted above — never re-trust a failed/absent emit here.
    tier = classify(prob, gate=gate, verify_tier1=False,
                    tier1_ruled_out=True if (kind or tier1_ruled_out) else False)
    return {"tier": tier, "rtl": None, "gate": gate,
            "artifact_type": kind, "verify_log": verify_log}


# --------------------------------------------------------------------------- #
# (7) gate_check — the PROGRAM gate the Tier-2/3 author is held to
# --------------------------------------------------------------------------- #
def _parse_candidate_header(rtl: str) -> Optional[Tuple[str, List[dict]]]:
    """(module_name, ports[{name,dir,width}]) from the candidate's FIRST module
    header, or None."""
    m = _MODULE_HEADER_RE.search(rtl or "")
    if not m:
        return None
    name = m.group(1)
    ports_text = m.group("ports") or ""
    ports: List[dict] = []
    for pm in _PORT_RE.finditer(ports_text):
        d, hi, lo, pname = pm.groups()
        ports.append({"name": pname, "dir": d, "width": _range_width(hi, lo)})
    return name, ports


def gate_check(prob: dict, candidate_rtl: str) -> dict:
    """The PROGRAM GATE. Assert the candidate RTL CONFORMS to the gate built from
    the _ifc.txt interface + stated structures. Returns {pass, violations}.

    §4.05: ONLY enforces facts in the gate. An unstated fact is never demanded —
    a parameter-expression width is not checked against a literal; a structure
    the registry did not recover is not required; an EXTRA port the AI adds (e.g.
    a clk the harness also drives) is allowed."""
    return gate_check_spec(build_gate(prob), candidate_rtl)


def gate_check_spec(gate: dict, candidate_rtl: str) -> dict:
    violations: List[dict] = []
    gate = gate or {}
    parsed = _parse_candidate_header(candidate_rtl or "")
    if parsed is None:
        return {"pass": False, "violations": [{
            "kind": "no_module", "detail": "candidate has no parseable module header"}]}
    mod_name, cand_ports = parsed

    want_name = gate.get("module_name")
    if want_name and mod_name != want_name:
        violations.append({"kind": "module_name",
            "detail": f"module name `{mod_name}` != required TOPLEVEL `{want_name}`"})

    cand_by_name = {p["name"]: p for p in cand_ports}
    for sp in gate.get("ports", []):
        nm = sp.get("name")
        cp = cand_by_name.get(nm)
        if cp is None:
            violations.append({"kind": "missing_port",
                "detail": f"required port `{nm}` ({sp.get('dir')}) absent from candidate"})
            continue
        if sp.get("dir") and cp.get("dir") and sp["dir"] != cp["dir"]:
            violations.append({"kind": "port_dir",
                "detail": f"port `{nm}` dir `{cp['dir']}` != spec `{sp['dir']}`"})
        sw, cw = sp.get("width"), cp.get("width")
        if isinstance(sw, int) and isinstance(cw, int) and sw != cw:
            violations.append({"kind": "port_width",
                "detail": f"port `{nm}` width {cw} != spec width {sw}"})

    structures = gate.get("structures") or {}
    body = candidate_rtl or ""
    for kind, key in (("enum_mode", "enum_modes"),
                      ("fsm_state", "fsm_states"),
                      ("register", "register_names")):
        for tok in structures.get(key, []):
            if not _token_represented(body, tok):
                violations.append({"kind": f"missing_{kind}",
                    "detail": f"{kind} `{tok}` from the spec is not represented in the candidate"})
    return {"pass": not violations, "violations": violations}


def _token_represented(rtl: str, tok: str) -> bool:
    if not tok:
        return True
    return re.search(rf"\b{re.escape(tok)}\b", rtl) is not None


# --------------------------------------------------------------------------- #
# CLI — the tier distribution over the 156 problems
# --------------------------------------------------------------------------- #
def _tier_label(t: int) -> str:
    return {1: "Tier1 (program-solved, iverilog-verified)",
            2: "Tier2 (COMPLETE ifc spec + gate)",
            3: "Tier3 (interface gate-able)",
            4: "Tier4 (too-incomplete)",
            5: "Tier5 (floor: ref-fails-test)"}.get(t, f"Tier{t}")


def run_distribution(dataset_dir: str, verify_tier1: bool = True,
                     limit: Optional[int] = None) -> dict:
    stems = discover_problems(dataset_dir)
    if limit:
        stems = stems[:limit]
    counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    tier_ids: Dict[int, List[str]] = {1: [], 2: [], 3: [], 4: [], 5: []}
    floor_reasons: List[Tuple[str, str]] = []
    tier1_types: Dict[str, int] = {}
    for stem in stems:
        prob = load_problem(dataset_dir, stem)
        res = solve(prob, verify_tier1=verify_tier1)
        t = res["tier"]
        counts[t] = counts.get(t, 0) + 1
        tier_ids.setdefault(t, []).append(stem)
        if t == TIER_PROGRAM and res.get("artifact_type"):
            tier1_types[res["artifact_type"]] = tier1_types.get(res["artifact_type"], 0) + 1
        if t == TIER_FLOOR:
            floor_reasons.append((stem, res["gate"].get("floor_reason", "")))
    return {"total": len(stems), "counts": counts, "tier_ids": tier_ids,
            "floor_reasons": floor_reasons, "tier1_types": tier1_types}


def run_step_progression(dataset_dir: str, limit: Optional[int] = None) -> dict:
    """Materialize the owner's STEP-1→4 CONVERGE as four successive distributions
    over the SAME 156 problems, so the progression is visible.

    The converge is monotone-upward and is driven ENTIRELY by what the pipeline
    can PROVE, never by relabeling:

      BASELINE  every problem starts un-tiered (Tier4 = un-gated).
      STEP 1 (T5→T4)  the floor prover runs ref+test; a problem is Tier5 ONLY if
                      the GOLDEN fails its own test, else it leaves Tier5. For
                      VE-human EVERY golden passes ⇒ Tier5 = 0 (no real floor).
      STEP 2 (T4→T3)  recover the interface from _ifc.txt; the gate now binds ⇒
                      every problem with a parseable interface leaves Tier4.
      STEP 3 (T3→T2)  the _ifc.txt interface is literal-width COMPLETE ⇒ those
                      with a fully-resolved interface advance Tier3→Tier2.
      STEP 4 (T2→T1)  where the registry DETERMINISTICALLY emits AND iverilog
                      proves the emit passes _test.sv, advance Tier2→Tier1.

    Returns {steps:[{name, counts}], final_tier_ids, floor_reasons}."""
    stems = discover_problems(dataset_dir)
    if limit:
        stems = stems[:limit]
    probs = [load_problem(dataset_dir, s) for s in stems]
    gates = [build_gate(p) for p in probs]

    # per-problem facts computed once (the expensive iverilog runs)
    facts = []
    for p, g in zip(probs, gates):
        kind, rtl = deterministic_emit(p)
        tier1_ok = False
        verify_log = None
        if rtl:
            tier1_ok, verify_log = tier1_verify(p, rtl)
        floor = floor_evidence(p)  # None for all VE-human (golden always passes)
        iface_parses = bool(g.get("module_name")) and bool(g.get("ports"))
        iface_complete = _interface_complete(p, g)
        facts.append({"stem": p["stem"], "tier1_ok": tier1_ok, "floor": floor,
                      "iface_parses": iface_parses, "iface_complete": iface_complete,
                      "artifact_type": kind, "verify_log": verify_log})

    def _counts(assign) -> Dict[int, int]:
        c = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for f in facts:
            c[assign(f)] += 1
        return c

    # STEP 1 — only floor-proven problems are Tier5; everything else is Tier4.
    s1 = _counts(lambda f: TIER_FLOOR if f["floor"] else TIER_UNGATED)
    # STEP 2 — interface recovered ⇒ Tier3 (gate binds); non-parseable stays T4.
    s2 = _counts(lambda f: TIER_FLOOR if f["floor"]
                 else (TIER_AI_GATED if f["iface_parses"] else TIER_UNGATED))
    # STEP 3 — complete literal-width interface ⇒ Tier2; partial stays Tier3.
    s3 = _counts(lambda f: TIER_FLOOR if f["floor"]
                 else (TIER_AI_EMIT if f["iface_complete"]
                       else (TIER_AI_GATED if f["iface_parses"] else TIER_UNGATED)))
    # STEP 4 — verified deterministic emit ⇒ Tier1.
    def _final(f):
        if f["floor"]:
            return TIER_FLOOR
        if f["tier1_ok"]:
            return TIER_PROGRAM
        if f["iface_complete"]:
            return TIER_AI_EMIT
        if f["iface_parses"]:
            return TIER_AI_GATED
        return TIER_UNGATED
    s4 = _counts(_final)

    final_tier_ids: Dict[int, List[str]] = {1: [], 2: [], 3: [], 4: [], 5: []}
    for f in facts:
        final_tier_ids[_final(f)].append(f["stem"])
    floor_reasons = [(f["stem"], f["floor"]) for f in facts if f["floor"]]
    tier1_types: Dict[str, int] = {}
    for f in facts:
        if _final(f) == TIER_PROGRAM and f["artifact_type"]:
            tier1_types[f["artifact_type"]] = tier1_types.get(f["artifact_type"], 0) + 1
    return {
        "total": len(facts),
        "steps": [
            {"name": "STEP 1 (T5→T4): floor prover (ref+test)", "counts": s1},
            {"name": "STEP 2 (T4→T3): interface from _ifc.txt", "counts": s2},
            {"name": "STEP 3 (T3→T2): complete-spec literal width", "counts": s3},
            {"name": "STEP 4 (T2→T1): verified deterministic emit", "counts": s4},
        ],
        "final_tier_ids": final_tier_ids,
        "floor_reasons": floor_reasons,
        "tier1_types": tier1_types,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dataset", required=True,
                    help="dataset_code-complete-iccad2023 directory")
    ap.add_argument("--id", help="classify only this problem stem (prints tier+gate)")
    ap.add_argument("--dist", action="store_true",
                    help="print the tier distribution (iverilog-VERIFIES every Tier1 + Tier5)")
    ap.add_argument("--dist-fast", action="store_true",
                    help="cheap distribution — registry-hit ⇒ Tier1, no iverilog (preview only)")
    ap.add_argument("--verify-tier1", action="store_true",
                    help="iverilog-check every Tier1 emit and list any that DO NOT pass")
    ap.add_argument("--steps", action="store_true",
                    help="print the STEP-1→4 CONVERGE progression (the tier "
                         "distribution AFTER EACH converge step)")
    ap.add_argument("--limit", type=int, help="only the first N problems (debug)")
    a = ap.parse_args(argv)

    if a.steps:
        d = run_step_progression(a.dataset, limit=a.limit)
        total = d["total"]
        print(f"VerilogEval-HUMAN 5-TIER CONVERGE — {total} problems\n")
        print(f"{'step':46s}  T1   T2   T3   T4   T5")
        print("-" * 76)
        for st in d["steps"]:
            c = st["counts"]
            print(f"{st['name']:46s} {c[1]:4d} {c[2]:4d} {c[3]:4d} {c[4]:4d} {c[5]:4d}")
        final = d["steps"][-1]["counts"]
        stable = final[1] + final[2] + final[3]
        print("-" * 76)
        print(f"FINAL stable (T1+T2+T3) = {stable}  ({100.0*stable/total:.1f}%)")
        if d["tier1_types"]:
            print("\nTier1 (verified) by artifact type:")
            for k, v in sorted(d["tier1_types"].items(), key=lambda kv: -kv[1]):
                print(f"  {k:28s} = {v}")
        if d["floor_reasons"]:
            print("\nTier5 floors (golden-fails-test):")
            for i, why in d["floor_reasons"]:
                print(f"  {i}: {why}")
        else:
            print("\nTier5 floors: NONE — every golden _ref.sv PASSES its own _test.sv.")
        if d["final_tier_ids"][2]:
            print(f"\nTier2 (AI-authored under the complete _ifc gate), {len(d['final_tier_ids'][2])}:")
            print("  " + ", ".join(d["final_tier_ids"][2]))
        return 0

    if a.id:
        prob = load_problem(a.dataset, a.id)
        res = solve(prob, verify_tier1=True)
        print(json.dumps({"id": a.id, "tier": res["tier"],
                          "tier_label": _tier_label(res["tier"]),
                          "artifact_type": res.get("artifact_type"),
                          "verify_log": res.get("verify_log"),
                          "gate": res["gate"]}, indent=2, ensure_ascii=False))
        return 0

    if a.verify_tier1:
        stems = discover_problems(a.dataset)
        if a.limit:
            stems = stems[:a.limit]
        npass = nfail = 0
        for stem in stems:
            prob = load_problem(a.dataset, stem)
            kind, rtl = deterministic_emit(prob)
            if not rtl:
                continue
            ok, log = tier1_verify(prob, rtl)
            tag = "PASS" if ok else "FAIL"
            if ok:
                npass += 1
            else:
                nfail += 1
                print(f"  {tag}  {stem:34s} [{kind}]  {log.splitlines()[0]}")
        print(f"\nTier1 emits: {npass} VERIFIED-PASS, {nfail} fired-but-FAIL "
              f"(only the PASS set is Tier1)")
        return 0

    verify = not a.dist_fast
    d = run_distribution(a.dataset, verify_tier1=verify, limit=a.limit)
    counts = d["counts"]
    total = d["total"]
    stable = counts[1] + counts[2] + counts[3]
    mode = "iverilog-VERIFIED" if verify else "FAST/unverified-preview"
    print(f"TOTAL = {total}   [{mode}]")
    for t in (1, 2, 3, 4, 5):
        print(f"  {_tier_label(t):42s} = {counts[t]}")
    print(f"\nSTABLE BASELINE (Tier1+Tier2+Tier3) = {stable}  ({100.0*stable/total:.1f}%)")
    if d["tier1_types"]:
        print("\nTier1 emit by artifact type:")
        for k, v in sorted(d["tier1_types"].items(), key=lambda kv: -kv[1]):
            print(f"  {k:28s} = {v}")
    if d["floor_reasons"]:
        print("\nTier5 floor evidence (ref-fails-test):")
        for i, why in d["floor_reasons"]:
            print(f"  {i}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
