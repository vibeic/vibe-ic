#!/usr/bin/env python3
"""l8_sta_clock_period_design_owned_check.py — L8 SEMANTIC completeness gate.

ENFORCEMENT: advisory

WHY THIS GATE EXISTS
--------------------
L8 is the ONLY design-owned source of the STA clock period. `programs/sdc_gen.py`
resolves it in a strict precedence chain and, when every tier misses, it
SILENTLY DEFAULTS:

    1. L8.clock_mhz
    2. sdc_gen._clock_mhz_from_l8_domains(L8)   (clock_domains[] freq/period)
    3. sdc_constraints.primary_clock(project)   (the design's OWN staged SDC)
    4. sdc_gen._DEFAULT_MHZ  ................... FABRICATED

Tier 4 writes the SDC that drives CTS and STA in phase3. Nothing downstream ever
learns the period was invented — the run closes timing against a number no
design input owns, and reports a green slack for it.

MEASURED ON PUBLISHED DATA (#316 salvage — the reproducible half)
------------------------------------------------------------------
The gate's original write-up cited "136 real converge runs on 5 fleet machines,
29 fabricating the period". #316's independent verification could not reproduce
ANY of the sweep counts the layer-gate batch reported (136/137/139/144/235/265/
645 against 138 findable run roots), so that number is NOT the justification
here — an unreproducible count is not evidence.

What IS reproducible, on the cells published in this repo:

    benchmark-data/ic/opentitan_aes
      L8_RTL_CONSTANTS.json : clock_mhz = null, clock_domains = []
      phase2/stage1/fpga/chip_top.sdc (PUBLISHED artefact):
          create_clock -name clk_main -period 20 [get_ports {clk}]
      20 ns = 1000/50 MHz = `sdc_gen._DEFAULT_MHZ` verbatim.

That cell closed timing against a period no design input owns, and the L8 gate
already on main (`l8_clock_period_actionability_check`) SKIPs it. Three further
published cells (`subservient`, and all three `spm` PDK variants) declare `clk`
twice with conflicting frequencies (50 vs 100; 100 vs 125) and sdc_gen silently
takes whichever the precedence walk reaches first — reported as an advisory.
Nine cells PASS. `programs/tests/test_issue316_layergates_on_published_cells.py`
pins the opentitan_aes finding and the SKIP that proves non-duplication.

THE CONSUMER CONTRACT THIS GATE ASSERTS
---------------------------------------
The gate IMPORTS sdc_gen's own resolver (`_clock_mhz_from_l8_domains`,
`_DEFAULT_MHZ`) and sdc_constraints' own staged-SDC reader, so gate and consumer
cannot drift (emitter/checker doctrine). It then asserts:

  L8-1  (rc=1)    The period sdc_gen will use must be DESIGN-OWNED — the
                  resolution must terminate at tier 1, 2 or 3, never at the
                  hardcoded default. Preferred terminus is L8 itself (tier 1/2);
                  terminating at tier 3 is reported as an advisory (the period
                  is design-owned but does not live in the layer that owns it).
  L8-2  (rc=1)    When L8 DOES own a period and the backend SDCs that drive
                  CTS/STA already exist, at least one `create_clock` in them
                  must carry that period (5% tolerance). Otherwise STA is
                  constrained on a clock set that does not contain L8's clock at
                  all — nothing else in the flow reconciles the two.
  L8-3  (rc=1)    Every `clock_domains[]` entry that declares a DERIVED
                  relationship (a `source`/`parent` naming another declared
                  clock, or a derived/divided/generated role) must carry a
                  `divider` or a resolvable frequency; otherwise CTS cannot
                  build the generated clock and STA has no ratio for it.
  L8-4  (ADVISES) Two `clock_domains[]` entries sharing a clock name but
                  declaring conflicting frequencies — the consumer silently
                  picks whichever the precedence walk reaches first. Reported;
                  never changes the exit code, because the ambiguity is a
                  phase-1 extraction artefact, not proof of a wrong period.

Everything is derived from the design's own inputs (its L-docs, its staged SDC,
its own RTL). No design name, PDK name, vendor part number or hardcoded
pin/signal literal appears anywhere in this file.

APPLICABILITY
-------------
SKIPs (rc=2) unless the design actually has a clocked digital backend, evidenced
by ANY of: a non-empty `L8.clock_domains[]`; a clock-role pin in
`L9.top_module_pins`; a `posedge`/`negedge` edge sensitivity in the design's own
RTL; or a `create_clock` in the design's own staged SDC. A pure-analog block with
no clock and no RTL is untouched.

WHAT ITS VERDICT ACTUALLY DOES — MEASURED, NOT CLAIMED (#316)
--------------------------------------------------------------
ADVISORY. Wired as `advisory_program_exit_zero` in
`flow/phase1_phase2_phase3.yaml` step 0, so it RUNS on every real project and
its findings are reported, and rc=1 does not fail the step.

This file previously declared "THIS GATE BLOCKS" and claimed registration in
`flow_compliance_check._STRUCTURAL_RTL_GATES`. It was registered nowhere and
could not run at all, let alone block — the same contradiction #316 found in 9
of its 30 gates and #306 found in 62 of 72. The line at the top of this
docstring is now the machine-readable declaration
`flow_gate_enforcement_audit.py` reads, and that audit FAILS if this file
declares blocking again without a runner invoking it inline.

Advisory is what the measurement supports, too: promoted to blocking today the
gate would fail `benchmark-data/ic/opentitan_aes` — a shipped campaign cell —
as a side effect of landing a gate. Whether a fabricated STA period should stop
a run is a flow-owner decision; making it VISIBLE on every run is not, and is
the prerequisite for taking that decision on evidence.

A design whose inputs genuinely never state an operating frequency is a real
case, so the escape hatch is a NAMED, REVIEWED disclosure rather than silence:
set `l8_sta_clock_period_not_design_owned` in `<project>/waivers.json` to a
>=40-char justification and the gate reports PASS_WITH_WAIVERS (rc=0) while
still printing the fabricated period. Disclosed beats invisible.

SINGLE DETERMINISTIC TRACK — NO AI BACKUP
-----------------------------------------
Deterministic only (schema walk + SDC grammar). It deliberately ships no "AI
second track": the completeness report that motivated this work shipped
`ai_captured_tokens_count: 0`, i.e. a dual-track that was really one track. One
honest track beats a second that produces nothing.

NOT A DUPLICATE OF
------------------
  * `l8_clock_domains_typed_check` — a TYPED-DEPTH gate that only fires when the
    vendor docs / L-docs mention >=2 distinct clock frequencies, so a
    single-clock design carrying no clock_mhz at all passes it clean. It never
    reaches the backend fabrication case. This gate strengthens that blind spot
    toward the consumer contract instead of restating the schema requirement.
  * `fpga_sdc_clock_constraint_check` — scoped to the Quartus/FPGA project under
    `<project>/fpga/`; asserts an SDC exists there and matches the RTL period.
    This gate is scoped to the ASIC backend SDCs that drive CTS/STA and to the
    FABRICATION case (no design-owned period at all), which that gate cannot see.
  * `clock_scale_consistency_check` / `threshold_range_contiguity_check` /
    `rx_classifier_thresholds_match_l8_check` — RX threshold-tick semantics,
    untouched here.
  * `derived_clock_sdc_required_check` — RTL divider vs `create_generated_clock`
    in the SDC; L8-3 is the L-doc-side obligation, not the RTL-side one.
  * `l8_clock_period_actionability_check` — the OTHER L8 clock gate, written in
    parallel with this one and already on main. #316 flagged the pair as a
    possible duplicate; measured on the published cells the overlap is a strict
    SUBSET, not an equality. That gate asks whether the clock records L8 DOES
    carry are unique and dereferenceable, so it SKIPs a design that carries no
    clock record at all — which is exactly the fabrication case (opentitan_aes:
    it skips, this one fails). Keep both; the subset direction is pinned by a
    test so the pair cannot be re-merged without re-measuring it.

USAGE
-----
    python3 l8_sta_clock_period_design_owned_check.py <project_dir> [--json OUT]

EXIT CODES
----------
    0 = PASS (or PASS_WITH_WAIVERS)
    1 = FAIL (blocks)
    2 = not applicable / input missing (SKIP)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # emitter/checker doctrine: reuse the CONSUMER's own resolver.
    from sdc_gen import (  # type: ignore
        _clock_mhz_from_l8_domains as _consumer_domains_mhz,
        _DEFAULT_MHZ as _CONSUMER_DEFAULT_MHZ,
    )
except Exception:  # pragma: no cover
    _consumer_domains_mhz = None  # type: ignore
    _CONSUMER_DEFAULT_MHZ = 50.0  # type: ignore

try:
    import sdc_constraints as _sdc  # type: ignore
except Exception:  # pragma: no cover
    _sdc = None  # type: ignore

try:
    from ic_class_profile import detect_ic_class  # type: ignore
except Exception:  # pragma: no cover
    detect_ic_class = None  # type: ignore

WAIVER_KEY = "l8_sta_clock_period_not_design_owned"
WAIVER_MIN = 40

# A bare-FPGA scaffold runs on the eval board's own oscillator and is
# constrained by the QSF/SDC in `<project>/fpga/`, which
# `fpga_sdc_clock_constraint_check` already owns. Same guard the sibling L8 gate
# uses, so the two never both fire on the same project.
_SKIP_CLASSES = ("bare_fpga",)

_L8_GLOB = "phase1/generated_docs/L8_RTL_CONSTANTS.json"
_L9_GLOB = "phase1/generated_docs/L9_INTEGRATION_SPEC.json"

# SDCs that drive the ASIC backend (synthesis constraints, PnR, CTS, STA).
_BACKEND_SDC_GLOBS: Tuple[str, ...] = (
    "phase2/stage2/constraints/*.sdc",
    "phase3/stage3/pnr/*.sdc",
    "phase3/stage3/cts/*.sdc",
    "phase3/stage3/sta/*.sdc",
)

_RTL_GLOBS: Tuple[str, ...] = (
    "phase2/stage1/rtl/**/*.v",
    "phase2/stage1/rtl/**/*.sv",
)

_CLOCK_PORT_RE = re.compile(r"^(clk|clock)([_0-9].*)?$|(_|\b)(clk|clock)(_|\b)",
                            re.IGNORECASE)
_EDGE_RE = re.compile(r"\b(pos|neg)edge\b", re.IGNORECASE)
_PERIOD_RE = re.compile(r"-period\s+([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_DERIVED_ROLE_RE = re.compile(
    r"deriv|divid|generat|pll|dll|scaled|child|slave", re.IGNORECASE)
_FREQ_KEYS = ("freq_mhz", "period_ns", "freq_hz")
_NAME_KEYS = ("name", "clock", "clk", "source_pin")
_PARENT_KEYS = ("source", "parent", "parent_clock", "source_clock", "master",
                "derived_from", "from")


def _load(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def _domains(l8: dict) -> List[dict]:
    d = l8.get("clock_domains")
    return [x for x in d if isinstance(x, dict)] if isinstance(d, list) else []


def _entry_mhz(rec: dict) -> Optional[float]:
    for key, conv in (("freq_mhz", lambda v: float(v)),
                      ("period_ns", lambda v: 1000.0 / float(v)),
                      ("freq_hz", lambda v: float(v) / 1e6)):
        v = rec.get(key)
        if v is None:
            continue
        try:
            f = conv(v)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if f > 0:
            return f
    return None


def _domains_mhz(l8: dict) -> Optional[float]:
    """Delegate to sdc_gen's own resolver; fall back to an equivalent walk."""
    if _consumer_domains_mhz is not None:
        try:
            return _consumer_domains_mhz(l8)
        except Exception:
            pass
    domains = _domains(l8)
    primary = [r for r in domains
               if r.get("domain_kind") == "primary" or r.get("role") == "master"]
    rest = [r for r in domains if not any(r is p for p in primary)]
    for rec in primary + rest:
        f = _entry_mhz(rec)
        if f is not None:
            return f
    return None


def _entry_name(rec: dict) -> Optional[str]:
    for k in _NAME_KEYS:
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip().lower()
    return None


def _staged_primary_mhz(project: Path) -> Tuple[Optional[float], Optional[str]]:
    """The design's OWN staged SDC period, via sdc_constraints (tier 3)."""
    if _sdc is None:
        return None, None
    try:
        rec = _sdc.primary_clock(project)
    except Exception:
        return None, None
    if not isinstance(rec, dict):
        return None, None
    p = rec.get("period_ns")
    try:
        p = float(p)
    except (TypeError, ValueError):
        return None, None
    if p <= 0:
        return None, None
    return 1000.0 / p, str(rec.get("source") or "staged SDC")


def _backend_sdc_periods(project: Path) -> List[Tuple[str, float]]:
    out: List[Tuple[str, float]] = []
    for pat in _BACKEND_SDC_GLOBS:
        for f in sorted(project.glob(pat)):
            if not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            text = re.sub(r"#[^\n]*", "", text)
            for line in text.splitlines():
                if "create_clock" not in line:
                    continue
                m = _PERIOD_RE.search(line)
                if not m:
                    continue
                try:
                    v = float(m.group(1))
                except ValueError:
                    continue
                if v > 0:
                    out.append((str(f.relative_to(project)), v))
    return out


def _has_clocked_backend(project: Path, l8: dict,
                         l9: Optional[dict]) -> Tuple[bool, str]:
    if _domains(l8):
        return True, "L8.clock_domains[] is non-empty"
    if isinstance(l9, dict):
        pins = l9.get("top_module_pins")
        if isinstance(pins, list):
            for p in pins:
                if not isinstance(p, dict):
                    continue
                nm = p.get("name")
                role = str(p.get("role") or p.get("function") or "")
                if isinstance(nm, str) and _CLOCK_PORT_RE.search(nm):
                    return True, f"L9.top_module_pins declares clock port {nm!r}"
                if "clock" in role.lower():
                    return True, f"L9.top_module_pins declares a clock role for {nm!r}"
    for pat in _RTL_GLOBS:
        for f in sorted(project.glob(pat))[:200]:
            if not f.is_file():
                continue
            try:
                if _EDGE_RE.search(f.read_text(encoding="utf-8",
                                               errors="ignore")):
                    return True, (f"RTL {f.relative_to(project)} is edge-"
                                  "sensitive (posedge/negedge)")
            except Exception:
                continue
    if _sdc is not None:
        try:
            if _sdc.collect_create_clocks(project):
                return True, "the design's own staged SDC declares a create_clock"
        except Exception:
            pass
    return False, ""


def _waived(project: Path) -> Tuple[bool, str]:
    p = project / "waivers.json"
    if not p.is_file():
        return False, ""
    try:
        doc = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return False, ""
    if not isinstance(doc, dict):
        return False, ""
    v = doc.get(WAIVER_KEY)
    if isinstance(v, str) and len(v.strip()) >= WAIVER_MIN:
        return True, v.strip()
    return False, ""


def _emit(path: Optional[Path], report: Dict[str, object]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="L8 STA-clock-period design-ownership semantic gate")
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(list(argv) if argv is not None else None)

    project = args.project.resolve()
    if not project.is_dir():
        print("[SKIP] l8_sta_clock_period_design_owned_check: "
              f"not a directory: {project}")
        return 2

    if detect_ic_class is not None:
        try:
            ic_class = (detect_ic_class(project) or {}).get("ic_class", "")
        except Exception:
            ic_class = ""
        if ic_class in _SKIP_CLASSES:
            print("[SKIP] l8_sta_clock_period_design_owned_check: "
                  f"ic_class={ic_class} (board-clocked FPGA scaffold; the SDC "
                  "contract there is owned by fpga_sdc_clock_constraint_check)")
            return 2

    l8 = _load(project / _L8_GLOB)
    if l8 is None:
        print("[SKIP] l8_sta_clock_period_design_owned_check: "
              f"no {_L8_GLOB} in this project.")
        return 2
    l9 = _load(project / _L9_GLOB)

    clocked, why = _has_clocked_backend(project, l8, l9)
    report: Dict[str, object] = {
        "gate": "l8_sta_clock_period_design_owned_check",
        "project": str(project),
        "findings": [],
        "advisories": [],
    }
    if not clocked:
        print("[SKIP] l8_sta_clock_period_design_owned_check: the design "
              "declares no clock (no clock_domains[], no clock-role top pin, "
              "no edge-sensitive RTL, no staged create_clock) — there is no "
              "STA clock period to own.")
        report["verdict"] = "SKIP"
        _emit(args.json, report)
        return 2
    report["applicability"] = why

    findings: List[Dict[str, str]] = []
    advisories: List[str] = []

    # ---------------- L8-1: the period must be design-owned ---------------- #
    tier = None
    resolved_mhz: Optional[float] = None
    explicit = l8.get("clock_mhz")
    if explicit is not None:
        try:
            v = float(explicit)
            if v > 0:
                resolved_mhz, tier = v, "L8.clock_mhz"
        except (TypeError, ValueError):
            pass
    if resolved_mhz is None:
        v = _domains_mhz(l8)
        if v:
            resolved_mhz, tier = v, "L8.clock_domains[]"
    l8_owned = resolved_mhz is not None
    staged_src = None
    if resolved_mhz is None:
        v, staged_src = _staged_primary_mhz(project)
        if v:
            resolved_mhz, tier = v, f"staged SDC ({staged_src})"

    report["resolved_mhz"] = resolved_mhz
    report["resolution_tier"] = tier
    report["l8_owned"] = l8_owned

    if resolved_mhz is None:
        n_dom = len(_domains(l8))
        shape = (f"L8.clock_domains[] has {n_dom} entr{'y' if n_dom == 1 else 'ies'} "
                 "but not one carries a resolvable freq_mhz/period_ns/freq_hz"
                 if n_dom else "L8.clock_domains[] is empty")
        findings.append({
            "rule": "L8-1",
            "message": (
                f"no design-owned STA clock period: L8.clock_mhz is "
                f"{l8.get('clock_mhz')!r}, {shape}, and the design stages no "
                "SDC with a create_clock. sdc_gen will therefore fall through "
                f"to its hardcoded default ({_CONSUMER_DEFAULT_MHZ} MHz => "
                f"period {1000.0 / float(_CONSUMER_DEFAULT_MHZ):.3g} ns) and "
                "write the SDC that drives CTS and STA in phase3 against a "
                "FABRICATED period. Every timing verdict downstream is then "
                "measured against a number no design input owns."),
        })
    elif not l8_owned:
        advisories.append(
            f"the STA period IS design-owned but not by L8: it resolves at "
            f"tier `{tier}` ({resolved_mhz:.6g} MHz). L8 — the layer whose "
            "declared purpose is to own it — carries neither clock_mhz nor a "
            "clock_domains[] entry with a frequency. Backfilling it into L8 "
            "removes the dependency on staged-SDC discovery order.")

    # ---------------- L8-2: reconcile L8 against the backend SDCs ---------- #
    backend = _backend_sdc_periods(project)
    report["backend_sdc_create_clocks"] = [
        {"file": f, "period_ns": p} for f, p in backend]
    if l8_owned and backend and resolved_mhz:
        want_ns = 1000.0 / resolved_mhz
        ok = any(abs(p - want_ns) <= 0.05 * max(want_ns, 1e-9)
                 for _f, p in backend)
        if not ok:
            findings.append({
                "rule": "L8-2",
                "message": (
                    f"L8 owns period {want_ns:.6g} ns "
                    f"({resolved_mhz:.6g} MHz, via {tier}) but NO create_clock "
                    "in the SDCs that drive CTS/STA carries it "
                    f"(found: {[f'{p}ns in {f}' for f, p in backend][:6]}). "
                    "STA is being constrained on a clock set that does not "
                    "contain L8's clock — nothing else in the flow reconciles "
                    "L8's clock set against the emitted SDC."),
            })

    # ---------------- L8-3: derived clocks must be actionable -------------- #
    domains = _domains(l8)
    declared_names = {n for n in (_entry_name(d) for d in domains) if n}
    for i, rec in enumerate(domains):
        role_blob = " ".join(
            str(rec.get(k) or "") for k in ("role", "domain_kind", "type",
                                            "kind"))
        parent = None
        for k in _PARENT_KEYS:
            v = rec.get(k)
            if isinstance(v, str) and v.strip().lower() in declared_names \
                    and v.strip().lower() != _entry_name(rec):
                parent = v.strip()
                break
        is_derived = bool(_DERIVED_ROLE_RE.search(role_blob)) or parent is not None
        if not is_derived:
            continue
        has_div = rec.get("divider") not in (None, "", 0)
        has_freq = _entry_mhz(rec) is not None
        if not has_div and not has_freq:
            findings.append({
                "rule": "L8-3",
                "message": (
                    f"clock_domains[{i}] "
                    f"({_entry_name(rec) or 'unnamed'}) declares a DERIVED "
                    f"clock (role/kind={role_blob.strip()!r}"
                    + (f", parent={parent!r}" if parent else "")
                    + ") but carries neither a `divider` nor a resolvable "
                      "frequency. CTS cannot build the generated clock and STA "
                      "has no ratio to constrain it with."),
            })

    # ---------------- L8-4: same-name conflicting frequencies (advisory) --- #
    by_name: Dict[str, List[float]] = {}
    for rec in domains:
        nm = _entry_name(rec)
        f = _entry_mhz(rec)
        if nm and f:
            by_name.setdefault(nm, []).append(f)
    for nm, fs in sorted(by_name.items()):
        if len(fs) > 1 and (max(fs) - min(fs)) > 0.01 * max(fs):
            advisories.append(
                f"clock `{nm}` is declared {len(fs)} times with conflicting "
                f"frequencies {sorted(set(round(x, 6) for x in fs))} MHz; "
                "sdc_gen silently uses whichever the precedence walk reaches "
                f"first ({resolved_mhz:.6g} MHz here).")

    report["findings"] = findings
    report["advisories"] = advisories

    if not findings:
        report["verdict"] = "PASS"
        _emit(args.json, report)
        print("[PASS] l8_sta_clock_period_design_owned_check: STA clock period "
              f"is design-owned via {tier} "
              f"({resolved_mhz:.6g} MHz = {1000.0 / resolved_mhz:.6g} ns)"
              + (f"; reconciled against {len(backend)} backend create_clock "
                 "directive(s)" if backend else "")
              + f". [{why}]")
        for a in advisories:
            print(f"  [note] {a}")
        return 0

    waived, reason = _waived(project)
    report["verdict"] = "PASS_WITH_WAIVERS" if waived else "FAIL"
    _emit(args.json, report)
    head = "PASS_WITH_WAIVERS" if waived else "[FAIL]"
    print(f"{head} l8_sta_clock_period_design_owned_check: "
          f"{len(findings)} L8 clock-contract finding(s). [{why}]")
    for f in findings:
        print(f"  - {f['rule']}: {f['message']}")
    for a in advisories:
        print(f"  [note] {a}")
    if waived:
        print(f"  waiver `{WAIVER_KEY}` set: {reason[:120]}")
        return 0
    print("  Fix: put the operating frequency in L8 (clock_mhz, or a "
          "clock_domains[] entry with freq_mhz/period_ns/freq_hz), or set "
          f"waiver `{WAIVER_KEY}` (>={WAIVER_MIN} chars) to DISCLOSE that the "
          "design's inputs state no frequency and STA closed against a "
          "fabricated one.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
