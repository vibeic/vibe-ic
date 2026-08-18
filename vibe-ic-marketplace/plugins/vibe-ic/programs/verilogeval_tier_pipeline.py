#!/usr/bin/env python3
"""verilogeval_tier_pipeline.py — the VerilogEval-v2 (spec-to-rtl) TIER-1→5
CLASSIFY + CONVERGE pipeline.

This is the VerilogEval-v2 counterpart of cvdp_solve_pipeline.py. It mirrors that
file's STRUCTURE (classify -> tier{1..5}, build_gate, gate_check, _floor_evidence,
a `--dist` CLI) but binds to the VerilogEval dataset layout instead of the CVDP
jsonl: a "problem" is a directory triple

    ProbNNN_<name>_prompt.txt   the spec  (the ONLY solver-visible text)
    ProbNNN_<name>_ref.sv       the GOLDEN (NEVER fed to the solver; iverilog only)
    ProbNNN_<name>_test.sv      the official testbench (instantiates TopModule +
                                RefModule and reports `Mismatches: 0 in N samples`)

THE 5-TIER MODEL (VerilogEval mapping):
  Tier1  the registry/canonical solver DETERMINISTICALLY emits RTL that PASSES the
         official _test.sv under iverilog (program-solved, no AI). VERIFIED here by
         actually running iverilog+vvp on the emit — only an emit that scores
         `Mismatches: 0` is Tier1.
  Tier2  a program extracts a COMPLETE spec (module name + every port/width/dir +
         at least one recovered STRUCTURE: truth-table rows / kmap / fsm states or
         transitions / waveform) and an AI authors from it + a conformance gate.
  Tier3  a MEANINGFUL conformance gate (module name + a non-empty interface, +/-
         structure) constrains an AI author; the spec is not fully COMPLETE.
  Tier4  too-incomplete to gate (no interface recoverable from the prompt).
  Tier5  genuine dataset floor — the golden _ref.sv itself FAILS its own _test.sv
         under iverilog (cited with the iverilog evidence).

§4.05 NO-LEAK / NO-CHEAT (binding):
  * The golden _ref.sv is read ONLY to run iverilog (Tier1 emit verification +
    Tier5 floor proof). It is NEVER fed to the solver and never sourced for the
    gate spec — classification + gate come ONLY from the prompt + the testbench
    interface (both submitter-visible).
  * The gate ONLY enforces facts the extractor recovered. A port/width/structure
    the prompt did not carry is never demanded (no false-reject of a correct AI
    solve).
  * A Tier1 claim is kept ONLY when the deterministic emit actually scores
    `Mismatches: 0` against the official test under iverilog. An emit that does
    not score is DROPPED back to the gate tiers — never asserted on trust.

chip-AGNOSTIC: every decision keys on STRUCTURE (the extracted spec shape, the
deterministic registry recognizers, generic Verilog grammar, and the test's own
`Mismatches:` report), never on a design name or a problem id.

Public API
    classify(prob_dir, verify=False) -> int
    build_gate(spec_contract, structures) -> dict
    gate_check(gate, candidate_rtl) -> {pass, violations}
    tier_result(prob_dir, verify=False) -> dict   # full {tier, rtl, gate, ...}
    floor_evidence(prob_dir) -> str|None          # iverilog ref-fails-test proof
    iverilog_score(prob_dir, candidate_rtl) -> (ok: bool, detail: str)

CLI
    python3 verilogeval_tier_pipeline.py --dataset DIR --dist [--verify]
    python3 verilogeval_tier_pipeline.py --dataset DIR --id ProbNNN_name [--verify]
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

# Reused (import, read — NOT modified) — the shipped deterministic pieces.
import spec_artifact_registry as _registry       # noqa: E402  Tier-1 deterministic emit
import moore_arrow_fsm_synth as _moore_arrow      # noqa: E402  arrow-Moore-FSM fallback
import dff_primitive_synth as _dff_primitive      # noqa: E402  bare D-FF primitive fallback
from _specrtl_common import (                     # noqa: E402  the spec contract extractor
    extract_spec_contract, parse_rtl_ports, strip_comments,
)
import semantic_spec_floor_check as _semfloor     # noqa: E402  golden-vs-prompt semantic floor

# Extra deterministic emitters tried AFTER the shipped registry (so they can never
# hijack a problem an existing registry solver already handles). Each keys on
# STRUCTURE, returns None (SKIP) on any ambiguity, and its emit is iverilog-VERIFIED
# by tier_result(--verify) before being banked as Tier1. NEW solvers are added
# here (a thin fallback chain) without editing the shared registry file.
_FALLBACK_SYNTHS = (_moore_arrow.synth, _dff_primitive.synth)

TIER_PROGRAM = 1   # deterministic registry emit, VERIFIED to pass _test.sv
TIER_AI_EMIT = 2   # COMPLETE spec (module+interface+>=1 structure) + gate
TIER_AI_GATED = 3  # meaningful interface gate constrains the AI; not COMPLETE
TIER_UNGATED = 4   # no interface recoverable from the prompt
TIER_FLOOR = 5     # genuine floor: golden ref FAILS its own test under iverilog

# The official testbench's verdict line. A run PASSES iff it reports
# `Mismatches: 0 in N samples` with N > 0 (a real run that compared N samples and
# found none wrong). N is captured so a DEGENERATE `in 0 samples` (the TB never
# drove a comparison — e.g. an elaboration that produced no stimulus) is NOT read
# as a pass.
_MISMATCH_RE = re.compile(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples")
_TOPMODULE = "TopModule"


# --------------------------------------------------------------------------- #
# (0) dataset access — a problem is a directory + a stem (ProbNNN_name)
# --------------------------------------------------------------------------- #
class Problem:
    """The submitter-visible (+ for iverilog only, the golden) file triple."""

    def __init__(self, prompt: Path):
        self.prompt_path = prompt
        self.stem = prompt.name[: -len("_prompt.txt")]
        self.dir = prompt.parent
        self.ref_path = self.dir / f"{self.stem}_ref.sv"
        self.test_path = self.dir / f"{self.stem}_test.sv"

    @property
    def prompt_text(self) -> str:
        return self.prompt_path.read_text(errors="replace")

    def complete(self) -> bool:
        return self.ref_path.is_file() and self.test_path.is_file()


def discover(dataset_dir: str) -> List[Problem]:
    d = Path(dataset_dir)
    probs = [Problem(p) for p in sorted(d.glob("*_prompt.txt"))]
    return [p for p in probs if p.complete()]


# --------------------------------------------------------------------------- #
# (1) the conformance GATE built from the prompt-extracted spec
# --------------------------------------------------------------------------- #
def extract_spec(prob: Problem) -> dict:
    """The program-extracted spec from the PROMPT ONLY (never the golden).
    Returns {module_name, ports[{name,dir,width}], structures{...}}.

    * ports come from the interface bullets (`- input d (8 bits)`), via the
      shipped `_specrtl_common.extract_spec_contract` — the same extractor the
      conformance gate uses in production.
    * structures come from the shipped `spec_artifact_registry.detect`, which
      recognizes every canonical structured-artifact type (truth table / kmap /
      fsm transition table / state encoding / waveform / register map ...).
    """
    text = prob.prompt_text
    contract = extract_spec_contract(text, confirm=False)
    ports = [{"name": p.name, "dir": p.direction, "width": p.width}
             for p in contract.ports]
    # module name: the VerilogEval-v2 harness ALWAYS binds a module called
    # `TopModule` (the prompt says "a module named TopModule" and the testbench
    # instantiates `TopModule top_module1 (...)`). That is the AUTHORITATIVE name
    # the gate must require. The generic contract extractor mis-reads the prose
    # "module named TopModule" as module-name `named` (it greps `module\s+(\w+)`),
    # which would FALSE-REJECT a correct `TopModule` candidate (§4.05). Prefer the
    # name the prompt explicitly NAMES, then the harness default — never the
    # extractor's prose artifact.
    module_name = _named_module(text) or _TOPMODULE

    structures = _extract_structures(text)
    return {"module_name": module_name, "ports": ports, "structures": structures}


_NAMED_MODULE_RE = re.compile(
    r"module\s+named\s+([A-Za-z_]\w*)", re.I)
# A fenced/inline Verilog module HEADER in the prompt (the bug-fix problems quote
# `module TopModule ( ... );`). The name there is authoritative too.
_DECL_MODULE_RE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)\s*[#(]")


def _named_module(text: str) -> Optional[str]:
    """The module name the prompt explicitly NAMES — from a `module named X`
    sentence (the dataset's canonical phrasing) or a quoted `module X (` header.
    None when neither is present (caller falls back to the harness default)."""
    m = _NAMED_MODULE_RE.search(text)
    if m:
        return m.group(1)
    m = _DECL_MODULE_RE.search(text)
    if m and m.group(1).lower() != "named":
        return m.group(1)
    return None


def _extract_structures(text: str) -> dict:
    """Every recovered structured artifact, distilled to the gate-relevant counts/
    keys. Reuses the registry's recognizers (truth-table / kmap / fsm / waveform /
    …) — the same knowledge the deterministic solver and the IC-Expert ingestion
    share. SKIP-safe: a recognizer that does not fire contributes nothing."""
    out: dict = {
        "artifact_types": [],
        "truth_rows": 0,
        "kmap_cells": 0,
        "fsm_states": [],
        "fsm_transitions": 0,
        "waveform_edges": 0,
        "has_any": False,
    }
    try:
        found = _registry.detect(text)
    except Exception:
        found = []
    for art in found:
        out["artifact_types"].append(art.get("type"))
        s = art.get("structured") or {}
        if isinstance(s, dict):
            rows = s.get("rows")
            if isinstance(rows, dict):
                out["truth_rows"] = max(out["truth_rows"], len(rows))
            cells = s.get("cells") or s.get("kmap")
            if isinstance(cells, (list, dict)):
                out["kmap_cells"] = max(out["kmap_cells"], len(cells))
            states = s.get("states")
            if isinstance(states, (list, dict)):
                out["fsm_states"] = list(states) if isinstance(states, list) \
                    else list(states.keys())
            trans = s.get("transitions")
            if isinstance(trans, (list, dict)):
                out["fsm_transitions"] = max(out["fsm_transitions"], len(trans))
            edges = s.get("edges") or s.get("samples")
            if isinstance(edges, (list, dict)):
                out["waveform_edges"] = max(out["waveform_edges"], len(edges))
    out["has_any"] = bool(out["artifact_types"])
    return out


def build_gate(spec: dict) -> dict:
    """Distill the extracted spec into the CONFORMANCE GATE — the facts an AI
    output MUST satisfy. Every entry anchors to a fact the extractor RECOVERED;
    nothing un-extracted is demanded (§4.05). A port whose width could not be
    resolved to an integer literal carries width=None (presence+dir enforced, the
    literal width skipped)."""
    spec = spec or {}
    ports = [{"name": p.get("name"), "dir": p.get("dir"),
              "width": p.get("width") if isinstance(p.get("width"), int) else None}
             for p in (spec.get("ports") or []) if p.get("name")]
    structures = spec.get("structures") or {}
    return {
        "module_name": spec.get("module_name"),
        "ports": ports,
        "structures": {
            "fsm_states": [s for s in (structures.get("fsm_states") or [])
                           if isinstance(s, str) and s.strip()],
        },
    }


# --------------------------------------------------------------------------- #
# (2) gate_check — the conformance gate the Tier-3 author is held to
# --------------------------------------------------------------------------- #
_MODULE_HEADER_RE = re.compile(
    r"\bmodule\s+(\w+)\s*(?:#\s*\(.*?\)\s*)?\((?P<ports>.*?)\)\s*;", re.S)


def _parse_candidate_header(rtl: str) -> Optional[Tuple[str, List[dict]]]:
    """(module_name, ports[{name,dir,width}]) from the candidate's first module
    header. Reuses the shipped `parse_rtl_ports` so the gate's parse exactly
    matches the production conformance gate's parse (no second, drifting parser).
    Comments are stripped FIRST so a bare `module` word inside a comment
    (`// no module here`) is not mis-read as a real module declaration."""
    src = strip_comments(rtl or "")
    m = re.search(r"\bmodule\s+(\w+)\b", src)
    if not m:
        return None
    name = m.group(1)
    _nm, ports = parse_rtl_ports(src, name)
    return name, [{"name": p.name, "dir": p.direction, "width": p.width}
                  for p in ports]


def gate_check(gate: dict, candidate_rtl: str) -> dict:
    """The PROGRAM GATE. Parse the candidate's header + body and assert it
    CONFORMS to the gate. A violation is a CONCRETE, fixable reason. §4.05: only
    facts the extractor recovered are enforced; an unstated port/width/structure is
    never demanded."""
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
                           "detail": f"module `{mod_name}` != required `{want_name}`"})

    cand_by_name = {p["name"]: p for p in cand_ports}
    for sp in gate.get("ports", []):
        nm = sp.get("name")
        cp = cand_by_name.get(nm)
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

    body = candidate_rtl or ""
    for tok in (gate.get("structures") or {}).get("fsm_states", []):
        if not re.search(rf"\b{re.escape(tok)}\b", body):
            violations.append({"kind": "missing_fsm_state",
                               "detail": f"fsm state `{tok}` not represented"})
    return {"pass": not violations, "violations": violations}


# --------------------------------------------------------------------------- #
# (3) iverilog verification — score a candidate against the official test
# --------------------------------------------------------------------------- #
def iverilog_score(prob: Problem, candidate_rtl: str,
                   timeout: int = 60) -> Tuple[bool, str]:
    """Compile `candidate_rtl` (renamed to TopModule) + the golden ref (RefModule)
    + the official testbench and run vvp. Return (passed, detail) where passed is
    True iff the test reports `Mismatches: 0 in N samples`. The golden ref is used
    ONLY as the test's reference instance — it is NOT fed to the solver and never
    influences classification/gate. iverilog availability is required for --verify.
    """
    if not candidate_rtl or not candidate_rtl.strip():
        return False, "no candidate RTL"
    # Defend against a candidate that named its module something other than
    # TopModule: the harness binds `TopModule`. We DO NOT rename — a Tier1 emit
    # already targets TopModule; if it doesn't, that is a real failure to surface.
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        cand = tdp / "dut.sv"
        cand.write_text(candidate_rtl)
        sim = tdp / "sim.out"
        try:
            # watchdog-exempt: bounded single-file iverilog compile (elaboration/sim build); fixed budget adequate — not an open-ended EDA generator
            comp = subprocess.run(
                ["iverilog", "-g2012", "-o", str(sim),
                 str(cand), str(prob.ref_path), str(prob.test_path)],
                capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return False, "iverilog not installed"
        except subprocess.TimeoutExpired:
            return False, "compile timeout"
        if comp.returncode != 0:
            return False, "compile error: " + (comp.stderr.strip().splitlines()[0]
                                               if comp.stderr.strip() else "unknown")
        try:
            # run vvp FROM the temp dir (cwd=tdp) so a testbench `$dumpfile("wave.vcd")`
            # writes its dump INSIDE the auto-cleaned TemporaryDirectory, not into the
            # plugin's programs/ tree (which the waveform-hygiene gate forbids).
            run = subprocess.run(["vvp", str(sim)], capture_output=True,
                                 text=True, timeout=timeout, cwd=str(tdp))
        except subprocess.TimeoutExpired:
            return False, "vvp timeout"
        out = run.stdout + run.stderr
        # The AUTHORITATIVE verdict is the TB's own `Mismatches: M in N samples`
        # line, NOT the literal word "TIMEOUT". Many of these testbenches install
        # a `#1000000 $display("TIMEOUT"); $finish` END-OF-LIFE watchdog that fires
        # at the natural close of EVERY run (incl. a fully-PASSING one) — the design
        # ran for the whole sample window, scored 0 mismatches in its `final`
        # block, and the watchdog then printed "TIMEOUT" as the sim's end marker.
        # Treating that benign string as a failure FALSE-FLOORED Prob082/141/156
        # (each golden scores `Mismatches: 0 in 200000 samples`). A GENUINE hang
        # never reaches the `final` block, so it prints NO `Mismatches:` line at
        # all — caught below by the absent-line case (and by vvp's own timeout).
        m = _MISMATCH_RE.search(out)
        if m is None:
            # no verdict line: a real hang, an elaboration crash, or a TB that
            # produced no comparison. Distinguish a watchdog-only hang for clarity.
            if "TIMEOUT" in out:
                return False, "simulation hung (TIMEOUT, no Mismatches verdict)"
            return False, "no Mismatches verdict line (sim error)"
        mism, samples = int(m.group(1)), int(m.group(2))
        if samples == 0:
            return False, "degenerate run: 0 samples compared"
        if mism == 0:
            return True, f"Mismatches: 0 in {samples} samples"
        return False, f"Mismatches: {mism} in {samples} samples"


# --------------------------------------------------------------------------- #
# (4) Tier5 floor evidence — golden ref FAILS its own test under iverilog
# --------------------------------------------------------------------------- #
def floor_evidence(prob: Problem, timeout: int = 60) -> Optional[str]:
    """Return a CITED reason iff this is a GENUINE floor. TWO defect classes:

    (1) STRUCTURAL — the golden _ref.sv does not even pass its OWN _test.sv under
        iverilog (a broken golden/test pair). Proven by renaming RefModule->TopModule
        and scoring: a sound problem MUST score `Mismatches: 0` with the golden as DUT.
    (2) SEMANTIC — the golden PASSES its own (golden-derived) testbench yet
        CONTRADICTS the prompt's own machine-extractable spec (a Karnaugh map, or an
        embedded 'fix the bug' reference whose select polarity the golden inverts).
        The golden-derived TB can never catch this (it is generated FROM the golden);
        an INDEPENDENT prompt-derived oracle does (semantic_spec_floor_check). A
        spec-faithful blind answer then fails against a golden that is itself wrong.

    Returns None for every sound problem. (2) fires only on an unambiguous extraction
    + a cited contradiction, so it never false-floors a sound design.
    """
    ref_text = prob.ref_path.read_text(errors="replace")
    # (1) structural: rename golden RefModule -> TopModule and run its own test.
    golden_as_top = re.sub(r"\bRefModule\b", "TopModule", ref_text)
    ok, detail = iverilog_score(prob, golden_as_top, timeout=timeout)
    if not ok:
        return (f"golden _ref.sv fails its OWN _test.sv under iverilog "
                f"(golden-as-TopModule -> {detail}); no candidate can ever score")
    # (2) semantic: golden passes its own test but may contradict the prompt spec.
    sem = _semfloor.semantic_floor_evidence(prob.prompt_text, ref_text, timeout=timeout)
    if sem:
        return f"golden passes its own _test.sv but {sem}"
    return None


# --------------------------------------------------------------------------- #
# (5) classification + full result
# --------------------------------------------------------------------------- #
def _registry_emit(prob: Problem) -> Optional[str]:
    """The deterministic emit for a problem: the shipped registry FIRST (its
    ordered solver chain), then the extra fallback synths. Returns the first
    non-None emit, or None when nothing deterministically solves it."""
    text = prob.prompt_text
    try:
        _k, rtl = _registry.generate(text, _TOPMODULE)
    except Exception:
        rtl = None
    if rtl:
        return rtl
    for synth in _FALLBACK_SYNTHS:
        try:
            rtl = synth(text, _TOPMODULE)
        except Exception:
            rtl = None
        if rtl:
            return rtl
    return None


def _spec_is_complete(gate: dict, structures: dict) -> bool:
    """COMPLETE == the gate pins the module name AND a non-empty interface AND the
    extractor recovered at least one STRUCTURE (truth-table rows / kmap cells / fsm
    states or transitions / waveform edges). This is the Tier2 bar: every testable
    fact (interface + behavior structure) was program-pinned."""
    if not (gate.get("module_name") and gate.get("ports")):
        return False
    return bool(structures.get("truth_rows") or structures.get("kmap_cells")
                or structures.get("fsm_states") or structures.get("fsm_transitions")
                or structures.get("waveform_edges"))


_PROGRAMS_DIR = Path(__file__).resolve().parent


def conformance_emit_blocked(prob: Problem, emit: str, timeout: int = 60) -> List[str]:
    """Run the SAME `spec_conformance_check` the real Shape-C gate runs, on a
    Tier-1 candidate emit, and return the EMIT-BLOCKING rule names that fire
    (empty list = the gate would emit this RTL).

    This closes the stability-test-vs-blind-run gap (#why-not-history-high): an
    emit that iverilog-PASSES but the gate BLOCKS (e.g. a galois_lfsr wrap caught
    by shift-implemented-as-rotate, or a comb_advanced wrong-width caught by a
    width rule) is NOT genuinely Tier-1 — the blind run can never emit it. The
    blocking-rule set is the single source of truth in
    spec_conformance_check.EMIT_BLOCKING_CONFORMANCE_RULES (the same set the gate
    consults). chip-AGNOSTIC; on any tool/IO error returns [] (never fabricates a
    block — a missing checker must not silently demote a real Tier-1)."""
    if not emit or not emit.strip():
        return []
    try:
        from spec_conformance_check import EMIT_BLOCKING_CONFORMANCE_RULES as _BLOCK
    except Exception:
        return []
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        (tdp / "TopModule.sv").write_text(emit)
        outj = tdp / "conf.json"
        try:
            subprocess.run(
                [sys.executable, str(_PROGRAMS_DIR / "spec_conformance_check.py"),
                 "--rtl-dir", str(tdp), "--spec", str(prob.prompt_path),
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


def tier_result(prob: Problem, verify: bool = False,
                timeout: int = 60) -> dict:
    """Full per-problem result: {tier, rtl, gate, spec, verified, detail}.

    When `verify` is set, a registry emit is KEPT as Tier1 ONLY if it actually
    scores `Mismatches: 0` against the official test under iverilog; otherwise the
    problem falls through to the gate tiers (the emit is recorded but not trusted).
    Floor detection (Tier5) likewise runs iverilog on the golden. With verify off,
    Tier1 is the registry's deterministic-emit CLAIM (unverified) — useful for a
    fast BEFORE-promotion snapshot, but a Tier1 NUMBER must be reported verified.
    """
    spec = extract_spec(prob)
    structures = spec.get("structures") or {}
    gate = build_gate(spec)

    emit = _registry_emit(prob)
    verified = None
    detail = ""
    if emit:
        if verify:
            ok, detail = iverilog_score(prob, emit, timeout=timeout)
            verified = ok
            if ok:
                # GATE PARITY: a Tier-1 emit must survive the SAME conformance the
                # real blind run applies, not just iverilog. An emit that the gate
                # would BLOCK can never reach the host TB (no_sample) — it is NOT
                # Tier-1. Without this the tier pipeline reported "Tier-1 solved"
                # while the gate blocked the emit (galois_lfsr / comb_advanced).
                blocked = conformance_emit_blocked(prob, emit, timeout=timeout)
                if blocked:
                    verified = False
                    detail = ("iverilog PASS but gate conformance BLOCKS emit: "
                              + ",".join(blocked))
                    # fall through to the gate tiers (do not grant Tier-1)
                else:
                    return {"tier": TIER_PROGRAM, "rtl": emit, "gate": gate,
                            "spec": spec, "verified": True, "detail": detail}
            # emit did not score (or the gate would block it) — DROP to gate tiers.
        else:
            # unverified claim — count it as Tier1 for the BEFORE snapshot.
            return {"tier": TIER_PROGRAM, "rtl": emit, "gate": gate,
                    "spec": spec, "verified": None, "detail": "unverified emit"}

    # Tier5 — genuine floor (only checked when verifying; needs iverilog).
    if verify:
        floor = floor_evidence(prob, timeout=timeout)
        if floor:
            g = dict(gate)
            g["floor_reason"] = floor
            return {"tier": TIER_FLOOR, "rtl": None, "gate": g, "spec": spec,
                    "verified": verified, "detail": detail}

    gate_meaningful = bool(gate.get("module_name")) and bool(gate.get("ports"))
    if gate_meaningful:
        if _spec_is_complete(gate, structures):
            tier = TIER_AI_EMIT
        else:
            tier = TIER_AI_GATED
    else:
        tier = TIER_UNGATED
    return {"tier": tier, "rtl": None, "gate": gate, "spec": spec,
            "verified": verified, "detail": detail}


def classify(prob, verify: bool = False, timeout: int = 60) -> int:
    """The tier integer for a Problem (or a prompt-path/stem-dir resolvable one)."""
    if not isinstance(prob, Problem):
        prob = Problem(Path(prob))
    return tier_result(prob, verify=verify, timeout=timeout)["tier"]


# --------------------------------------------------------------------------- #
# CLI — the tier distribution over the dataset
# --------------------------------------------------------------------------- #
def _tier_label(t: int) -> str:
    return {1: "Tier1 (program-solved, iverilog-verified)",
            2: "Tier2 (COMPLETE spec + gate)",
            3: "Tier3 (interface-gate-able)",
            4: "Tier4 (too-incomplete)",
            5: "Tier5 (floor)"}.get(t, f"Tier{t}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dataset", required=True, help="dataset_spec-to-rtl directory")
    ap.add_argument("--id", help="classify only this stem (ProbNNN_name)")
    ap.add_argument("--dist", action="store_true", help="print the tier distribution")
    ap.add_argument("--verify", action="store_true",
                    help="iverilog-verify Tier1 emits + Tier5 floors (authoritative)")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--json", help="write per-problem rows as JSON")
    a = ap.parse_args(argv)

    probs = discover(a.dataset)
    if a.id:
        match = [p for p in probs if p.stem == a.id]
        if not match:
            print(f"id not found: {a.id}", file=sys.stderr)
            return 2
        res = tier_result(match[0], verify=a.verify, timeout=a.timeout)
        print(json.dumps({"id": a.id, "tier": res["tier"],
                          "tier_label": _tier_label(res["tier"]),
                          "verified": res["verified"], "detail": res["detail"],
                          "gate": res["gate"]}, indent=2, ensure_ascii=False))
        return 0

    counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    tier_ids: Dict[int, List[str]] = {1: [], 2: [], 3: [], 4: [], 5: []}
    floor_reasons: List[Tuple[str, str]] = []
    rows = []
    for p in probs:
        res = tier_result(p, verify=a.verify, timeout=a.timeout)
        t = res["tier"]
        counts[t] = counts.get(t, 0) + 1
        tier_ids.setdefault(t, []).append(p.stem)
        if t == TIER_FLOOR:
            floor_reasons.append((p.stem, res["gate"].get("floor_reason", "")))
        rows.append({"id": p.stem, "tier": t, "verified": res["verified"],
                     "detail": res["detail"]})

    total = len(probs)
    if a.dist or not a.json:
        stable = counts[1] + counts[2] + counts[3]
        print(f"TOTAL = {total}   (verify={'ON' if a.verify else 'OFF'})")
        for t in (1, 2, 3, 4, 5):
            print(f"  {_tier_label(t):42s} = {counts[t]}")
        print(f"\nGATED BASELINE (Tier1+Tier2+Tier3) = {stable}  "
              f"({100.0*stable/total:.1f}%)")
        if floor_reasons:
            print("\nTier5 floor evidence:")
            for i, why in floor_reasons:
                print(f"  {i}: {why}")
    if a.json:
        Path(a.json).write_text(json.dumps(
            {"total": total, "counts": counts, "rows": rows,
             "tier_ids": tier_ids, "floors": floor_reasons}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
