#!/usr/bin/env python3
"""rtllm_tier_pipeline.py — the RTLLM TIER-1->5 CONVERGE / AUTHORING-GATE PIPELINE.

The SAME 5-tier model the CVDP pipeline (cvdp_solve_pipeline.py) applies, mapped
onto the RTLLM benchmark (≈50 doc->RTL designs, each a directory with a prose
`design_description.txt` + a `testbench.v` + a verified golden `verified_*.v`).
This module MIRRORS cvdp_solve_pipeline's structure (classify / build_gate /
gate_check / solve + a `--dist` CLI) and COMPOSES the already-shipped, unmodified
pieces — it authors NO new RTL itself except by delegating to deterministic
solvers that are each iverilog-proven against the design's own testbench.

THE 5-TIER MODEL (RTLLM mapping):
  Tier 1  a canonical solver DETERMINISTICALLY emits RTL that PASSES the design's
          testbench under `iverilog -g2012 && vvp` (no AI). Verified, not assumed:
          tier-1 is asserted ONLY after the emit is compiled+run against the real
          testbench (cwd=design, so relative $readmemh paths resolve) and the RTLLM
          pass token appears.
  Tier 2  a program extracts a COMPLETE spec (module name + every port/width +
          stated structure) from design_description.txt; an AI authors from it and
          the conformance gate pins every testable fact.
  Tier 3  a MEANINGFUL conformance gate (interface recovered from the prose
          `Module name:` / `Input ports:` / `Output ports:` header) constrains an
          AI author; the spec is not fully COMPLETE.
  Tier 4  too-incomplete to gate meaningfully (no interface recoverable).
  Tier 5  genuine FLOOR — PROVED by running the GOLDEN reference RTL against the
          testbench under iverilog: only a design whose own golden FAILS its own
          test (an iverilog-incompatible testbench construct, or a golden that
          disagrees with the testbench's gold vectors) is a real floor. Cited with
          evidence (the compile/run failure of the golden).

§4.05 NO-LEAK / NO-CHEAT (binding):
  * The gate ONLY enforces facts the prose extractor recovered (module name +
    ports). It never demands an unstated port/width/structure — a false-reject of a
    correct author is the worst failure of a stabilizer.
  * The golden/reference RTL is NEVER fed to a solver and never read to BUILD the
    gate. The golden is read ONLY to PROVE a Tier-5 floor (run golden-vs-testbench),
    exactly as the owner directive prescribes — its TEXT never seeds an emit.
  * chip-AGNOSTIC: every decision keys on STRUCTURE (the prose interface shape +
    generic Verilog/arithmetic grammar + the testbench's own missing-module name),
    never on a design name or directory literal.

Public API
    classify(design_dir) -> int                 the tier integer (runs the gates)
    build_gate(design_dir) -> dict              conformance gate (module+ports)
    gate_check(design_dir, candidate_rtl)->dict {pass, violations}
    solve(design_dir) -> dict                   {tier, rtl, gate, evidence}
    required_module_name(design_dir) -> str|None the tb-bound DUT name (authoritative)
    golden_floor_evidence(design_dir) -> str|None cited Tier-5 reason or None
    iverilog_score(design_dir, rtl, top) -> (compiled, passed, log)

CLI
    python3 rtllm_tier_pipeline.py --root DIR [--dist] [--design NAME] [--step N]
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Reused (import, read — NOT modified) — the shipped pieces this pipeline composes.
import rtllm_port_bridge as _bridge          # noqa: E402  RTLLM prose -> bullet ports
import spec_artifact_registry as _registry   # noqa: E402  deterministic emit chain
try:
    import rtllm_iface_recover as _iface      # noqa: E402  header-dialect recoverer
except Exception:                              # pragma: no cover
    _iface = None
try:
    import arith_ext_synth as _arith_ext  # noqa: E402  iverilog-proven adder ext
except Exception:                              # pragma: no cover
    _arith_ext = None
try:
    import general_synth as _general     # noqa: E402  §4.05-approved structural bank
except Exception:                              # pragma: no cover
    _general = None
try:
    import port_parser as _pp                  # noqa: E402  shared interface reader
except Exception:                              # pragma: no cover
    _pp = None

TIER_PROGRAM = 1   # deterministic emit, iverilog-VERIFIED to pass the testbench
TIER_AI_EMIT = 2   # program extracted a COMPLETE spec; AI authors from it + gate
TIER_AI_GATED = 3  # meaningful interface gate constrains an AI author (not COMPLETE)
TIER_UNGATED = 4   # too-incomplete to gate (no interface recoverable)
TIER_FLOOR = 5     # golden fails its own testbench (cited evidence)

# CONVERGE-lever toggles (env-controlled) — let the CLI snapshot the tier
# distribution BEFORE/AFTER each of the owner's 4 converge steps without forking
# the code. All default ENABLED (the fully-converged pipeline).
#   RTLLM_DISABLE_FLOORPROOF=1  : skip the Tier-5 golden-vs-tb proof (floors stay
#                                 wherever they fall) — baseline for STEP 1.
#   RTLLM_DISABLE_IFACE=1       : skip the header-dialect interface recoverer
#                                 (T4->T3 / T3->T2) — baseline for STEP 2 & 3.
#   RTLLM_DISABLE_ARITHEXT=1    : skip the iverilog-proven arithmetic extension
#                                 (T2->T1) — baseline for STEP 4.
#   RTLLM_DISABLE_GENERAL=1     : skip the §4.05-approved general structural bank
#                                 (general_synth) — T2->T1 for the standard
#                                 structures (comparator/subtractor/bcd/multiplier/
#                                 divider/counters/shifters/detectors/pipe-adder).
def _flag(name: str) -> bool:
    return os.environ.get(name, "") not in ("", "0", "false", "False")


# --------------------------------------------------------------------------- #
# the TESTBENCH VERDICT CONTRACT — a STRUCTURED, ANCHORED observable
# --------------------------------------------------------------------------- #
# A bare `re.search(r"pass", re.I)` over the transcript is NOT a verdict: it
# fires on "byPASS_en = 1", "PASSthrough_mux", "PASSword" — any design whose TB
# happens to dump a signal or module name containing those letters scored PASS,
# and this feeds a PUBLISHED benchmark number. The verdict now keys on the
# testbench's OWN verdict statement, in the same shape verilogeval_tier_pipeline
# uses for `Mismatches: N in M samples`: prefer the STRUCTURED counted line,
# fall back to an ANCHORED whole-token banner, and FAIL-SAFE when neither is
# present (no recognisable verdict is NOT a pass).
#
# The forms below are the ones RTLLM's 50 shipped testbenches actually print
# (surveyed over the corpus's own `$display` strings) — a structural contract,
# not a per-design literal (§4.05 chip-AGNOSTIC).

# (1) STRUCTURED, COUNTED — the strongest form, carries its own failure count:
#     "===========Test completed with   7 /100 failures==========="
#     "=========== Test completed with 3 failures ==========="
#     "Test completed with 2 errors."
_COUNTED_VERDICT_RE = re.compile(
    r"Test\s+completed\s+with\s+(\d+)\s*(?:/\s*\d+\s*)?(?:failure|error)s?", re.I)

# (2) ANCHORED BANNER — RTLLM's canonical success/failure markers. The phrase
#     "Your Design Passed" cannot be produced by a signal name; the `Error` /
#     `Failed` banners are pinned to the `===` rule so a prose "error:" note
#     elsewhere in the transcript does not masquerade as the verdict.
_BANNER_PASS_RE = re.compile(r"={3,}\s*Your\s+Design\s+Passed\s*={3,}", re.I)
_BANNER_FAIL_RE = re.compile(r"={3,}\s*(?:Error|Failed)\s*={3,}", re.I)

# (3) ANCHORED FAILURE STATEMENT — line-anchored, word-boundary failure reports
#     ("Test failed: a = ...", "Failed at i=3, ...", "Error: dividend=..."). A
#     failure anywhere is authoritative even if a pass banner also appears.
_LINE_FAIL_RE = re.compile(
    r"^[\s=*-]*(?:test\s+)?(?:failed|failure|error)\b\s*[:@]|"
    r"^[\s=*-]*failed\s+at\b", re.I | re.M)

# (4) ANCHORED WHOLE-LINE PASS — a TB whose entire verdict line is a pass token
#     ("PASSED", "=== test passed ==="). `\bpass` has a WORD BOUNDARY, so
#     "bypass" / "passthrough" / "password" can never satisfy it.
_LINE_PASS_RE = re.compile(
    r"^[\s=*-]*(?:all\s+)?(?:tests?|simulation|design)?\s*"
    r"\bpass(?:ed)?\b[\s=*!.-]*$", re.I | re.M)


def testbench_verdict(out: str, returncode: Optional[int] = None) -> Tuple[bool, str]:
    """(passed, reason) from a simulation transcript, decided on the TB's own
    verdict statement. FAIL-SAFE: anything unrecognised is NOT a pass.

    Order: a non-zero simulator exit is never a pass -> the STRUCTURED counted
    line -> an anchored failure statement/banner -> an anchored pass banner or
    whole-line pass token -> no recognisable verdict (not a pass)."""
    out = out or ""
    if returncode is not None and returncode != 0:
        return False, f"simulator exited {returncode} (abnormal termination)"
    if not out.strip():
        return False, "no simulation output (silent transcript)"

    counted = _COUNTED_VERDICT_RE.search(out)
    fail_stmt = _BANNER_FAIL_RE.search(out) or _LINE_FAIL_RE.search(out)
    pass_stmt = _BANNER_PASS_RE.search(out) or _LINE_PASS_RE.search(out)

    # (1) the structured counted line is authoritative when present.
    if counted:
        n = int(counted.group(1))
        if n > 0:
            return False, f"testbench reported {n} failure(s)"
        # 0 failures counted — honour it unless a failure statement contradicts.
        if fail_stmt:
            return False, "0-failure count contradicted by a failure statement"
        return True, "testbench reported 0 failures"

    # (2) any anchored failure statement wins over a co-occurring pass token.
    if fail_stmt:
        return False, f"testbench failure statement: {fail_stmt.group(0).strip()[:60]}"

    # (3) an anchored pass statement.
    if pass_stmt:
        return True, f"testbench pass statement: {pass_stmt.group(0).strip()[:60]}"

    # (4) FAIL-SAFE — no verdict the contract recognises.
    return False, "no recognisable testbench verdict in transcript"
# data files a testbench may $readmemh / $readmemb at runtime (copied into the
# scratch build dir so relative paths resolve — the cwd=design rule).
_DATA_EXT = (".txt", ".hex", ".dat", ".mem", ".data", ".list", ".bin")


# --------------------------------------------------------------------------- #
# design-dir helpers
# --------------------------------------------------------------------------- #
def find_designs(root: str) -> List[str]:
    """Every RTLLM design directory under `root` (one per design_description.txt),
    sorted. A design dir holds design_description.txt + testbench.v + verified_*.v."""
    descs = sorted(glob.glob(os.path.join(root, "**", "design_description.txt"),
                            recursive=True))
    return [os.path.dirname(d) for d in descs]


def _read(path: str) -> str:
    try:
        return Path(path).read_text(errors="replace")
    except Exception:
        return ""


def design_prompt(design_dir: str) -> str:
    return _read(os.path.join(design_dir, "design_description.txt"))


def _golden_path(design_dir: str) -> Optional[str]:
    for f in sorted(os.listdir(design_dir)):
        if f.startswith("verified") and f.endswith(".v"):
            return os.path.join(design_dir, f)
    return None


def required_module_name(design_dir: str) -> Optional[str]:
    """The module name the testbench INSTANTIATES (binds) and does NOT itself
    define — the AUTHORITATIVE required top name. Recovered by compiling
    testbench.v ALONE: iverilog reports the missing module as
    'Unknown module type: NAME'. This is tb-driven (submitter-visible), robust
    against the makefile's TEST_DESIGN typos and the golden's internal
    `verified_*` name, and never reads the golden body."""
    tb = os.path.join(design_dir, "testbench.v")
    if not os.path.exists(tb):
        return None
    try:
        # watchdog-exempt: bounded single-file iverilog compile (elaboration/sim build); fixed budget adequate — not an open-ended EDA generator
        c = subprocess.run(["iverilog", "-g2012", "-o", os.devnull, tb],
                           capture_output=True, text=True, timeout=60)
    except Exception:
        return None
    m = re.search(r"Unknown module type:\s*([A-Za-z_]\w*)", c.stderr + c.stdout)
    if m:
        return m.group(1)
    # tb compiled alone (DUT defined inside tb, or none): fall back to the prose
    # `Module name:` token, else the makefile TEST_DESIGN.
    pm = re.search(r"Module name\s*[:：]\s*\n?\s*([A-Za-z_]\w*)",
                   design_prompt(design_dir))
    if pm:
        return pm.group(1)
    mk = _read(os.path.join(design_dir, "makefile"))
    mm = re.search(r"TEST_DESIGN\s*=\s*(\S+)", mk)
    return mm.group(1) if mm else None


# --------------------------------------------------------------------------- #
# (0) the iverilog scorer — RTLLM's pass/fail oracle (VCS -> iverilog disclosed)
# --------------------------------------------------------------------------- #
# vibe-ic#1745 — the verdict this function returns comes from searching the
# SIMULATOR'S COMBINED STDOUT, which the candidate shares with the testbench.
# A candidate that prints the harness's own verdict marker therefore scores a
# pass no matter what it computes (MEASURED on benchmark/score_iverilog_tb.py:
# two candidates with identical wrong logic, only one of them printing, scored
# differently). Refuse such a candidate BEFORE it is run. Applied to the
# CANDIDATE only — the golden-vs-its-own-test floor prover grades the
# benchmark's own reference, which is not a submission.
import harness_verdict_token_guard as _hvtg


def iverilog_score(design_dir: str, rtl_text: str, top: str,
                   timeout_run: int = 30) -> Tuple[bool, bool, str]:
    """Compile `rtl_text` (defining module `top`) together with the design's
    testbench.v in a SCRATCH COPY of the design dir (so relative $readmemh data
    files resolve — the cwd=design rule), run it under vvp, and apply RTLLM's
    own pass rule (the auto_run.py oracle: a 'pass'/'Pass' token present and no
    error/failure token). Returns (compiled, passed, tail_log).

    TOOL SUBSTITUTION (disclosed): RTLLM's makefile drives Synopsys VCS
    (`vcs -sverilog +v2k` + `simv`); we substitute the open Icarus Verilog
    (`iverilog -g2012` + `vvp`) — the same compile-then-simulate contract over the
    SAME unmodified testbench."""
    tb = os.path.join(design_dir, "testbench.v")
    if not os.path.exists(tb):
        return False, False, "no testbench.v"
    with tempfile.TemporaryDirectory() as td:
        for f in os.listdir(design_dir):
            src = os.path.join(design_dir, f)
            if os.path.isfile(src) and (f.endswith(_DATA_EXT) or f == "testbench.v"):
                try:
                    shutil.copy(src, td)
                except Exception:
                    pass
        cand = os.path.join(td, top + ".v")
        try:
            Path(cand).write_text(rtl_text)
        except Exception as e:
            return False, False, f"write-exc {e}"
        sim = os.path.join(td, "sim")
        try:
            # watchdog-exempt: bounded single-file iverilog compile (elaboration/sim build); fixed budget adequate — not an open-ended EDA generator
            c = subprocess.run(["iverilog", "-g2012", "-o", sim, cand,
                                os.path.join(td, "testbench.v")],
                               capture_output=True, text=True, timeout=60, cwd=td)
        except Exception as e:
            return False, False, f"compile-exc {e}"
        if c.returncode != 0:
            return False, False, "COMPILE-FAIL: " + (c.stderr[-400:] or c.stdout[-400:])
        rc: Optional[int] = None
        try:
            r = subprocess.run(["vvp", sim], capture_output=True, text=True,
                               timeout=timeout_run, cwd=td)
            out, rc = r.stdout + r.stderr, r.returncode
        except subprocess.TimeoutExpired as e:
            # a hang: keep whatever the run printed, but rc stays None — the
            # verdict contract must find a real verdict in it to score a pass.
            so = e.stdout or b""
            out = so.decode(errors="replace") if isinstance(so, bytes) else so
        except Exception as e:
            return True, False, f"run-exc {e}"
        passed, why = testbench_verdict(out, rc)
        return True, passed, f"[{why}] " + out[-400:]


# --------------------------------------------------------------------------- #
# (1) Tier-5 floor proof — run the GOLDEN against its OWN testbench
# --------------------------------------------------------------------------- #
def golden_floor_evidence(design_dir: str) -> Optional[str]:
    """Return a CITED reason iff the design is a GENUINE floor: its own GOLDEN
    reference RTL FAILS its own testbench under iverilog. This is the owner's
    Tier-5 definition — only a golden-fails-its-own-test design is a real floor.
    Conservative: returns None whenever the golden PASSES (the design is NOT a
    floor — it is gate-able / solvable at a higher tier).

    The golden's internal module is renamed to the tb-bound required name before
    scoring (RTLLM's official scoring substitution: the testbench instantiates the
    required name, while the golden file declares `verified_*`). The golden TEXT is
    used ONLY here, to prove the floor — never to seed a solver emit (§4.05)."""
    if _flag("RTLLM_DISABLE_FLOORPROOF"):
        return None
    gpath = _golden_path(design_dir)
    if not gpath:
        return None
    top = required_module_name(design_dir)
    if not top:
        return None
    gtext = _read(gpath)
    gmods = re.findall(r"^\s*module\s+([A-Za-z_]\w*)", gtext, re.M)
    if not gmods:
        return None
    # the golden's DUT module: a `verified_*` module if present, else the one
    # already named `top`, else the first declared module.
    target = next((g for g in gmods if g.startswith("verified")), None)
    if target is None:
        target = top if top in gmods else gmods[0]
    renamed = re.sub(rf"\bmodule\s+{re.escape(target)}\b", f"module {top}", gtext)
    compiled, passed, log = iverilog_score(design_dir, renamed, top)
    if passed:
        return None
    if not compiled:
        # the TESTBENCH itself rejected the golden -> iverilog-incompatible harness.
        snippet = log.replace("COMPILE-FAIL:", "").strip()[:160]
        return (f"golden fails its own testbench: iverilog could not build the "
                f"GOLDEN+testbench (tool-incompatible testbench construct) — {snippet}")
    return (f"golden fails its own testbench: the reference RTL runs but does NOT "
            f"pass the testbench's gold vectors — {log.strip()[:160]}")


# --------------------------------------------------------------------------- #
# (2) the conformance GATE — module name + interface from the prose header
# --------------------------------------------------------------------------- #
def build_gate(design_dir: str) -> dict:
    """The CONFORMANCE GATE for this design: the required module name + every port
    the prose `Input ports:` / `Output ports:` header states (name, dir, width).
    Recovered via the shipped rtllm_port_bridge (a GENERAL prose-port reader, not
    keyed to any design name). Every entry is a fact the extractor RECOVERED;
    nothing un-recovered is demanded (§4.05). A port whose width could not be
    reduced to a single integer is DROPPED by the bridge, so it is not falsely
    enforced."""
    prompt = design_prompt(design_dir)
    ins, outs = _bridge.parse_rtllm_ports(prompt)
    src = "rtllm_port_bridge"
    # CONVERGE lever (T4->T3 / T3->T2): also run the header-dialect recoverer
    # (Inputs:/Outputs:, paren-direction, parameter-expression widths, explicit-
    # range-authoritative). Adopt its result when it recovers a RICHER interface
    # (more ports) than the strict base bridge — e.g. it keeps an output whose
    # `[15:0]` range is explicit even though the prose also mentions the operands'
    # "8-bit" width (which the stricter base bridge drops as "ambiguous"). §4.05:
    # this only RECOVERS a port the prose STATES — it never fabricates one.
    if _iface is not None and not _flag("RTLLM_DISABLE_IFACE"):
        ri, ro = _iface.recover_ports(prompt)
        if len(ri) + len(ro) > len(ins) + len(outs):
            ins, outs, src = ri, ro, "rtllm_iface_recover"
    ports = ([{"name": n, "dir": "input", "width": w} for n, w in ins]
             + [{"name": n, "dir": "output", "width": w} for n, w in outs])
    return {
        "module_name": required_module_name(design_dir),
        "ports": ports,
        "ports_source": src,
        # completeness: COMPLETE iff the prose stated BOTH an input and an output
        # block AND the module name resolved — every testable interface fact pinned.
        "completeness": "COMPLETE" if (ins and outs) else "PARTIAL",
    }


_MODULE_HEADER_RE = re.compile(
    r"\bmodule\s+(\w+)\s*(?:#\s*\((?P<params>.*?)\)\s*)?\((?P<ports>.*?)\)\s*;", re.S)


def _parse_candidate_header(rtl: str) -> Optional[Tuple[str, List[dict]]]:
    """(module_name, ports[{name,dir,width}]) from the candidate's FIRST module
    header (ANSI form). Header-only interface parse; widths from a `[hi:lo]` literal
    range (None for a parameter-expression range — an unknown-but-present width
    the gate must NOT enforce as a literal, §4.05)."""
    m = _MODULE_HEADER_RE.search(rtl or "")
    if not m:
        return None
    name = m.group(1)
    ports_text = m.group("ports") or ""
    ports: List[dict] = []
    for pm in re.finditer(
            r"\b(input|output|inout)\b\s+(?:(?:wire|reg|logic)\b\s*)?(?:signed\b\s*)?"
            r"(?:\[\s*([^\]:]+)\s*:\s*([^\]]+)\s*\]\s*)?(\w+)", ports_text):
        d, hi, lo, pname = pm.groups()
        ports.append({"name": pname, "dir": d, "width": _range_width(hi, lo)})
    return name, ports


def _range_width(hi: Optional[str], lo: Optional[str]) -> Optional[int]:
    if hi is None or lo is None:
        return 1
    try:
        return abs(int(hi.strip()) - int(lo.strip())) + 1
    except ValueError:
        return None  # parameter-expression width — present but not a literal mismatch


def gate_check(design_dir: str, candidate_rtl: str) -> dict:
    """The PROGRAM GATE the Tier-2/3 author is held to: parse the candidate's
    module header and assert it CONFORMS to the gate (right module name; every
    spec port present, same direction, and — when both sides are literal — same
    width). A violation is a CONCRETE, fixable reason. §4.05: only facts the prose
    extractor recovered are enforced; an extra port the AI legitimately adds (e.g.
    a clk the harness also drives) is NOT a violation, and a parameterized width is
    never required to match a literal."""
    return gate_check_spec(build_gate(design_dir), candidate_rtl)


def gate_check_spec(gate: dict, candidate_rtl: str) -> dict:
    violations: List[dict] = []
    gate = gate or {}
    parsed = _parse_candidate_header(candidate_rtl or "")
    if parsed is None:
        return {"pass": False, "violations": [{
            "kind": "no_module", "detail": "candidate has no parseable module header"}]}
    mod_name, cand_ports = parsed
    want = gate.get("module_name")
    if want and mod_name != want:
        violations.append({"kind": "module_name",
                           "detail": f"module `{mod_name}` != required `{want}`"})
    by = {p["name"]: p for p in cand_ports}
    # case-insensitive fallback (RTLLM mixes a/A, Cin/cin) — match by name OR
    # by lowercased name, but report the spec's exact name in the violation.
    by_lower = {p["name"].lower(): p for p in cand_ports}
    for sp in gate.get("ports", []):
        nm = sp.get("name")
        cp = by.get(nm) or by_lower.get((nm or "").lower())
        if cp is None:
            violations.append({"kind": "missing_port",
                               "detail": f"required port `{nm}` ({sp.get('dir')}) absent"})
            continue
        if sp.get("dir") and cp.get("dir") and sp["dir"] != cp["dir"]:
            violations.append({"kind": "port_dir",
                               "detail": f"port `{nm}` dir `{cp['dir']}` != spec `{sp['dir']}`"})
        sw, cw = sp.get("width"), cp.get("width")
        if isinstance(sw, int) and isinstance(cw, int) and sw != cw:
            violations.append({"kind": "port_width",
                               "detail": f"port `{nm}` width {cw} != spec {sw}"})
    return {"pass": not violations, "violations": violations}


# --------------------------------------------------------------------------- #
# (3) Tier-1 deterministic emit — bridge the prose, run the registry + the
#     iverilog-proven arithmetic extension, then VERIFY against the testbench.
# --------------------------------------------------------------------------- #
def deterministic_emit(design_dir: str, top: Optional[str] = None
                       ) -> Tuple[Optional[str], Optional[str]]:
    """(kind, rtl) from the FIRST deterministic solver that fires on the bridged
    prose, or (None, None). Tries the iverilog-proven RTLLM arithmetic extension
    first (its FORMs are narrower + host-verified), then the shipped registry
    chain. The golden is NEVER read — input is the prompt only (§4.05)."""
    top = top or required_module_name(design_dir) or "TopModule"
    prompt = design_prompt(design_dir)
    bridged = _bridge.bridge_prompt(prompt)
    if _arith_ext is not None and _pp is not None and not _flag("RTLLM_DISABLE_ARITHEXT"):
        try:
            ins, outs = _pp.parse_ports(bridged)
            rtl = _arith_ext.synth(prompt, ins, outs, top)
        except Exception:
            rtl = None
        if rtl:
            return "arith_ext", rtl
    # the §4.05-approved general structural bank — same prose+interface contract as
    # the arith ext, after it (narrower forms first) and before the registry. The
    # caller still iverilog-VERIFIES the emit against the testbench (tier1_emit_verified)
    # so a structurally-matched-but-wrong emit is dropped, never shipped as Tier-1.
    if _general is not None and _pp is not None and not _flag("RTLLM_DISABLE_GENERAL"):
        try:
            ins, outs = _pp.parse_ports(bridged)
            rtl = _general.synth(prompt, ins, outs, top)
        except Exception:
            rtl = None
        if rtl:
            return "general", rtl
    try:
        kind, rtl = _registry.generate(bridged, top)
    except Exception:
        kind, rtl = None, None
    if rtl:
        return kind, rtl
    return None, None


def tier1_emit_verified(design_dir: str) -> Tuple[Optional[str], Optional[str], str]:
    """(kind, rtl, log) iff a deterministic solver emits RTL that is iverilog-VERIFIED
    to PASS the design's testbench; else (None, None, reason). Tier-1 is asserted
    ONLY on a real pass — never on emit alone."""
    top = required_module_name(design_dir)
    if not top:
        return None, None, "no required module name"
    kind, rtl = deterministic_emit(design_dir, top)
    if not rtl:
        return None, None, "no deterministic emit"
    refusal = _hvtg.refuse_or_none(rtl, _hvtg.registry_patterns("rtllm"))
    if refusal:
        return None, None, refusal
    compiled, passed, log = iverilog_score(design_dir, rtl, top)
    if passed:
        return kind, rtl, log
    return None, None, ("emit did not pass testbench: "
                        + ("compile-fail" if not compiled else "run-nopass"))


# --------------------------------------------------------------------------- #
# (4) classify + solve
# --------------------------------------------------------------------------- #
def classify(design_dir: str) -> int:
    return solve(design_dir)["tier"]


def solve(design_dir: str) -> dict:
    """The pipeline entry point. Returns {tier, rtl, gate, evidence}.

    Order of decision (each step is the owner's converge lever):
      Tier 1  a deterministic solver emits + iverilog-VERIFIES against the testbench.
      Tier 5  else, if the GOLDEN fails its own testbench -> genuine floor (cited).
      Tier 2  else, if the prose gate is COMPLETE (module + in + out blocks) -> the
              AI authors from a complete spec + the gate pins every interface fact.
      Tier 3  else, if the gate is MEANINGFUL (module name + >=1 port) -> the AI
              authors under a constraining interface gate.
      Tier 4  else -> too-incomplete to gate.
    """
    gate = build_gate(design_dir)

    kind, rtl, log = tier1_emit_verified(design_dir)
    if rtl:
        return {"tier": TIER_PROGRAM, "rtl": rtl, "gate": gate,
                "evidence": {"emit_kind": kind, "verify": "iverilog PASS"}}

    floor = golden_floor_evidence(design_dir)
    if floor:
        g = dict(gate); g["floor_reason"] = floor
        return {"tier": TIER_FLOOR, "rtl": None, "gate": g,
                "evidence": {"floor_reason": floor}}

    meaningful = bool(gate.get("module_name")) and bool(gate.get("ports"))
    if meaningful:
        if gate.get("completeness") == "COMPLETE":
            return {"tier": TIER_AI_EMIT, "rtl": None, "gate": gate, "evidence": {}}
        return {"tier": TIER_AI_GATED, "rtl": None, "gate": gate, "evidence": {}}
    return {"tier": TIER_UNGATED, "rtl": None, "gate": gate, "evidence": {}}


# --------------------------------------------------------------------------- #
# CLI — the tier distribution over a benchmark root
# --------------------------------------------------------------------------- #
def _tier_label(t: int) -> str:
    return {1: "Tier1 (program-solved, iverilog-verified)",
            2: "Tier2 (COMPLETE-spec + gate)",
            3: "Tier3 (interface-gate-able)",
            4: "Tier4 (too-incomplete)",
            5: "Tier5 (golden-fails-own-test floor)"}.get(t, f"Tier{t}")


def distribution(root: str) -> dict:
    designs = find_designs(root)
    counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    rows = []
    floors = []
    for d in designs:
        res = solve(d)
        t = res["tier"]
        counts[t] = counts.get(t, 0) + 1
        rows.append((os.path.basename(d), t, res))
        if t == TIER_FLOOR:
            floors.append((os.path.basename(d), res["gate"].get("floor_reason", "")))
    return {"counts": counts, "rows": rows, "floors": floors, "total": len(designs)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", required=True, help="RTLLM benchmark root directory")
    ap.add_argument("--design", help="classify only this design (basename match)")
    ap.add_argument("--dist", action="store_true", help="print the tier distribution")
    a = ap.parse_args(argv)

    if a.design:
        for d in find_designs(a.root):
            if os.path.basename(d) == a.design:
                res = solve(d)
                print(f"{a.design}: {_tier_label(res['tier'])}")
                print("  module :", res["gate"].get("module_name"))
                print("  ports  :", res["gate"].get("ports"))
                if res["tier"] == TIER_FLOOR:
                    print("  floor  :", res["gate"].get("floor_reason"))
                if res["tier"] == TIER_PROGRAM:
                    print("  emit   :", res["evidence"].get("emit_kind"),
                          "->", res["evidence"].get("verify"))
                return 0
        print(f"design not found: {a.design}", file=sys.stderr)
        return 2

    info = distribution(a.root)
    counts, total = info["counts"], info["total"]
    print(f"TOTAL = {total}")
    for t in (1, 2, 3, 4, 5):
        ids = [n for n, tt, _ in info["rows"] if tt == t]
        print(f"  {_tier_label(t):46s} = {counts[t]:2d}  {ids}")
    stable = counts[1] + counts[2] + counts[3]
    ceiling = total - counts[5]
    print(f"\nSTABLE (Tier1+2+3)           = {stable}  ({100.0*stable/total:.1f}%)")
    print(f"SOLVABLE CEILING (total-Tier5)= {ceiling}  ({100.0*ceiling/total:.1f}%)")
    if info["floors"]:
        print("\nTier5 floors (golden fails its own testbench):")
        for n, why in info["floors"]:
            print(f"  {n}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
