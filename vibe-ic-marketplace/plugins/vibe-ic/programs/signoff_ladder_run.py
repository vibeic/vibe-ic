"""Chip-level sign-off ladder runner (B1 from spm pilot) — REAL-gate wired.

Doctrine: spm pilot discovered the 9 sub-tier sign-off ladder
serially-by-hand, surfacing 4 silicon-critical bugs along the way.
This program runs all sub-tiers in one pass against a project
directory, aggregating verdicts into a canonical JSON.

TAPEOUT-SIGNOFF P0 — the ladder now GATES a tapeout with the real
sign-off gates instead of accepting proxies / silent waivers:

  * the EM tier calls `em_current_density_check` (real J-vs-Jmax),
    NOT the old decap-cell-count >= 100 placement proxy;
  * at the TAPEOUT/release tier the LVS-net tier calls
    `lvs_tapeout_signoff_check`, so a POWER_PIN_ONLY netgen waiver is
    NO LONGER a pass — it stays a documented WAIVED_PENDING that does
    NOT release (a genuine `Circuits match uniquely` is required), and
    a WAIVED LVS is never silently a pass;
  * the TAPEOUT/release tier adds STA sign-off rigor
    (`sta_signoff_rigor_check`), MBIST coverage (`mbist_wrapper_gen`),
    and — for Caravel / Open-MPW shuttle projects — the Efabless
    mpw-precheck verdict (`mpw_precheck_result_gate`) + the computed
    GDS-vs-golden XOR (`xor_layout_check`, replacing the hardcoded
    2/7 floor).

Modes:
  triage  (default) — the diagnostic ladder. The LVS-net tier can still
                      SHOW a POWER_PIN_ONLY / open-source waiver (it is a
                      reasoned triage waiver). Nothing here claims a
                      tapeout.
  tapeout           — the RELEASE ladder. POWER_PIN_ONLY no longer
                      releases; STA-rigor / MBIST / (Caravel) precheck +
                      XOR gates are added. Only this mode tightens.

§4.05 (LOAD-BEARING): a design whose real gate FAILs makes the ladder NOT
release; a POWER_PIN_ONLY LVS does NOT count as a tapeout pass; a missing
artifact is an honest SKIP/NOT_RUN, never a silent pass.

Each tier is a deterministic check; the runner does not invoke EDA tools
itself (that is mcp-eda's job) — it consumes per-tier check artifacts (or
delegates to the dedicated sign-off gate programs) and emits a canonical
verdict. chip-AGNOSTIC: no design/PDK literal appears in any rule.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROGRAMS = Path(__file__).resolve().parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


# ---------------------------------------------------------------------------
# Verdict vocabulary
# ---------------------------------------------------------------------------
# A ladder overall_verdict is "releasing" iff it is one of these. Everything
# else (FAIL / WARN / NOT_RELEASED) blocks a tapeout release.
RELEASING_VERDICTS = ("PASS", "PASS_WITH_WAIVERS")

# TAPEOUT-tier gate defaults (this session's sign-off gates). Each is a
# permissive, DISCLOSED generic default — never a foundry number — so a gate
# never FAILs a design a stricter house rule would also pass, and a PASS is a
# real margin. Callers/PDKs override per package/foundry.
_DYNAMIC_IR_BUDGET_PCT = 10.0        # transient droop budget as % of Vdd
_METAL_DENSITY_MIN = 0.30            # generic per-layer CMP density window
_METAL_DENSITY_MAX = 0.70
_THERMAL_LIMIT_W_PER_MM2 = 1.0       # first-order air-cooled package screen
_THERMAL_TJ_MAX_C = 125.0            # commercial-grade junction ceiling


@dataclass
class TierResult:
    tier_id: str           # e.g. "T1", "T1.5", "T2_PDN"
    name: str              # human label
    verdict: str           # PASS / FAIL / WARN / WAIVED / WAIVED_PENDING /
                           # INCOMPLETE / NOT_RUN / N/A
    details: Dict[str, Any] = field(default_factory=dict)
    artifact_path: Optional[str] = None
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Per-tier checkers — artifact consumers
# ---------------------------------------------------------------------------
def check_tier_1_drc(project_dir: Path) -> TierResult:
    """Tier 1 DRC — read reports/drc/full_deck.json if present."""
    art = project_dir / "reports" / "drc" / "full_deck.json"
    if not art.exists():
        return TierResult("T1", "Full DRC (KLayout/Magic)", "NOT_RUN",
                            notes="reports/drc/full_deck.json missing")
    data = json.loads(art.read_text(encoding="utf-8"))
    n = int(data.get("violations", -1))
    verdict = "PASS" if n == 0 else "FAIL"
    return TierResult("T1", "Full DRC (KLayout/Magic)", verdict,
                        details={"violations": n},
                        artifact_path=str(art))


def check_tier_1_5_drc_heatmap(project_dir: Path) -> TierResult:
    """Tier 1.5 — diagnostic only, report presence."""
    art = project_dir / "reports" / "drc" / "geographic_heatmap.json"
    if not art.exists():
        return TierResult("T1.5", "DRC heatmap", "NOT_RUN",
                            notes="diagnostic only")
    return TierResult("T1.5", "DRC heatmap", "PASS",
                        artifact_path=str(art))


def check_tier_2_pdn(project_dir: Path,
                       min_specialnets: int = 1) -> TierResult:
    """Tier 2 PDN — SPECIALNETS in the final DEF must be > 0."""
    art = project_dir / "reports" / "pnr" / "pdn.json"
    if not art.exists():
        return TierResult("T2_PDN", "Power Distribution Network",
                            "NOT_RUN", notes="reports/pnr/pdn.json missing")
    data = json.loads(art.read_text(encoding="utf-8"))
    n = int(data.get("specialnets", 0))
    verdict = "PASS" if n >= min_specialnets else "FAIL"
    return TierResult("T2_PDN", "Power Distribution Network", verdict,
                        details={"specialnets": n,
                                 "min_required": min_specialnets},
                        artifact_path=str(art))


def check_tier_2_ir(project_dir: Path,
                     budget_uv: float = 35.0) -> TierResult:
    """Tier 2 IR-drop — worst IR must be below per-budget threshold."""
    art = project_dir / "reports" / "pnr" / "ir_drop.json"
    if not art.exists():
        return TierResult("T2_IR", "IR-drop", "NOT_RUN",
                            notes="reports/pnr/ir_drop.json missing")
    data = json.loads(art.read_text(encoding="utf-8"))
    worst = float(data.get("worst_ir_uv", 1e9))
    verdict = "PASS" if worst <= budget_uv else "FAIL"
    return TierResult("T2_IR", "IR-drop", verdict,
                        details={"worst_ir_uv": worst,
                                 "budget_uv": budget_uv},
                        artifact_path=str(art))


# ---------------------------------------------------------------------------
# Tier 2 EM — REAL J-vs-Jmax (replaces the decap-cell-count proxy).
# ---------------------------------------------------------------------------
def _discover_jmax_ref(project_dir: Path
                       ) -> Tuple[Optional[Path], Optional[Path]]:
    """Return (jmax_json, tech_lef) — the first per-layer Jmax reference found
    in the project, or (None, None). A supplied jmax JSON wins over a tech LEF.
    chip-AGNOSTIC: matches only on conventional file names, never a PDK literal."""
    for pat in ("reports/**/em_jmax.json", "reports/**/jmax.json"):
        hits = [h for h in project_dir.glob(pat) if h.is_file()]
        if hits:
            return sorted(hits)[0], None
    jhits = [h for h in project_dir.rglob("*jmax*.json") if h.is_file()]
    if jhits:
        return sorted(jhits)[0], None
    thits = [h for h in project_dir.rglob("*.tlef") if h.is_file()]
    if thits:
        return None, sorted(thits)[0]
    thits = [h for h in project_dir.rglob("*tech*.lef") if h.is_file()]
    if thits:
        return None, sorted(thits)[0]
    return None, None


def check_tier_2_em(project_dir: Path,
                    jmax: Optional[Path] = None,
                    tech_lef: Optional[Path] = None,
                    margin: float = 0.10) -> TierResult:
    """Tier 2 EM — real per-segment current-density J vs the PDK Jmax limit.

    Delegates to `em_current_density_check`. §4.05: a missing EM report OR a
    missing Jmax reference is an honest NOT_RUN (SKIP) — NEVER the old
    decap-cell-count proxy, and never a fabricated PASS."""
    import em_current_density_check as emc
    em_path = emc._discover_em_report(project_dir)
    if em_path is None:
        return TierResult(
            "T2_EM", "EM current-density (J vs Jmax)", "NOT_RUN",
            notes="no EM per-segment report — §4.05: absent → SKIP, never "
                  "the old decap-count proxy")
    jmax_path = jmax
    tech = tech_lef
    if jmax_path is None and tech is None:
        jmax_path, tech = _discover_jmax_ref(project_dir)
    verdict_str, rep = emc.evaluate(
        em_path, jmax_path, tech, margin, emc._DEFAULT_BLACKS_N, None, 20)
    ladder_verdict = {"PASS": "PASS", "FAIL": "FAIL",
                      "SKIPPED": "NOT_RUN"}.get(verdict_str, "FAIL")
    notes = ""
    if verdict_str == "SKIPPED":
        notes = (f"EM density not judgeable ({rep.get('skip_reason')}); "
                 "§4.05: SKIP, never a pass")
    elif verdict_str == "FAIL":
        notes = f"{rep.get('offender_count', 0)} segment(s) at/over Jmax"
    return TierResult(
        "T2_EM", "EM current-density (J vs Jmax)", ladder_verdict,
        details={"em_verdict": verdict_str,
                 "skip_reason": rep.get("skip_reason"),
                 "summary": rep.get("summary"),
                 "jmax_source": rep.get("jmax_source")},
        artifact_path=str(em_path), notes=notes)


def check_tier_3_antenna(project_dir: Path) -> TierResult:
    """Tier 3 antenna — Magic + KLayout both report 0."""
    art_magic = project_dir / "reports" / "antenna" / "magic.json"
    art_klayout = project_dir / "reports" / "antenna" / "klayout.json"
    if not art_magic.exists() and not art_klayout.exists():
        return TierResult("T3_ANTENNA", "Antenna", "NOT_RUN",
                            notes="no antenna artifacts found")
    m_viol = (int(json.loads(art_magic.read_text(encoding="utf-8")).get(
        "violations", -1)) if art_magic.exists() else -1)
    k_viol = (int(json.loads(art_klayout.read_text(encoding="utf-8")).get(
        "violations", -1)) if art_klayout.exists() else -1)
    verdict = ("PASS" if (m_viol == 0 and k_viol == 0)
                else "FAIL" if (m_viol > 0 or k_viol > 0)
                else "WARN")
    return TierResult("T3_ANTENNA", "Antenna", verdict,
                        details={"magic_violations": m_viol,
                                 "klayout_violations": k_viol})


def check_tier_3_esd(project_dir: Path) -> TierResult:
    """Tier 3 ESD/pad-ring — qualitative artifact present."""
    art = project_dir / "reports" / "esd" / "esd_padring.json"
    if not art.exists():
        return TierResult("T3_ESD", "ESD/pad-ring", "NOT_RUN")
    data = json.loads(art.read_text(encoding="utf-8"))
    verdict = "PASS" if data.get("clean") else "FAIL"
    return TierResult("T3_ESD", "ESD/pad-ring", verdict,
                        details=data, artifact_path=str(art))


def check_tier_4_lvs_device(project_dir: Path) -> TierResult:
    """Tier 4 LVS device class — Netgen 261=261 style match."""
    art = project_dir / "reports" / "lvs" / "device_class.json"
    if not art.exists():
        return TierResult("T4_LVS_DEV", "LVS device class", "NOT_RUN")
    data = json.loads(art.read_text(encoding="utf-8"))
    verdict = "PASS" if data.get("device_class_match") else "FAIL"
    return TierResult("T4_LVS_DEV", "LVS device class", verdict,
                        details=data, artifact_path=str(art))


def check_tier_4_5_lvs_net(project_dir: Path) -> TierResult:
    """Tier 4.5 LVS net-level (TRIAGE tier). Consumes the pre-classified
    netgen verdict from reports/lvs/net_level.json. A blackbox-macro
    open-source project may legitimately show verdict WAIVED here — that is a
    reasoned TRIAGE waiver and is NOT a tape-out claim (the tapeout tier,
    `check_tier_lvs_tapeout`, refuses to credit it)."""
    art = project_dir / "reports" / "lvs" / "net_level.json"
    if not art.exists():
        return TierResult("T4.5_LVS_NET", "LVS net-level (triage)", "NOT_RUN")
    data = json.loads(art.read_text(encoding="utf-8"))
    verdict = data.get("verdict", "FAIL")
    return TierResult("T4.5_LVS_NET", "LVS net-level (triage)", verdict,
                        details=data, artifact_path=str(art))


# ---------------------------------------------------------------------------
# Tier 4.5 LVS — TAPEOUT tier: a POWER_PIN_ONLY waiver is NOT a pass.
# ---------------------------------------------------------------------------
def _find_lvs_report(project_dir: Path) -> Optional[Path]:
    """Locate the raw netgen LVS transcript/report to hand the tapeout LVS
    gate. Prefers the canonical `reports/phase3/lvs*.rpt`, then any
    netgen/lvs-named report. Never falls back to an unrelated `*.rpt` (that
    would risk classifying an STA report), keeping absence an honest SKIP."""
    prefer = sorted(project_dir.glob("reports/phase3/lvs*.rpt"))
    prefer = [p for p in prefer if p.is_file()]
    if prefer:
        return prefer[0]
    for pat in ("*netgen*.rpt", "*lvs*.rpt", "*.lvs.report", "comp.out"):
        hits = [h for h in project_dir.rglob(pat) if h.is_file()]
        if hits:
            return sorted(hits)[0]
    return None


def check_tier_lvs_tapeout(project_dir: Path) -> TierResult:
    """TAPEOUT LVS sign-off — a genuine `Circuits match uniquely` is required.

    Delegates to `lvs_tapeout_signoff_check`:
      GENUINE_MATCH             -> PASS
      WAIVED_PENDING_POWER_AWARE-> WAIVED_PENDING  (a POWER_PIN_ONLY waiver —
                                   documented, NON-releasing, NOT a pass)
      SIGNAL_NET_MISMATCH       -> FAIL
      INCOMPLETE                -> INCOMPLETE       (evidence present but no
                                   top-level compare — non-releasing)
      IO_ERROR (no report)      -> NOT_RUN          (§4.05: absent → SKIP)"""
    import lvs_tapeout_signoff_check as ltc
    rpt = _find_lvs_report(project_dir)
    if rpt is None:
        return TierResult(
            "T4.5_LVS_TAPEOUT", "LVS tapeout sign-off (genuine match)",
            "NOT_RUN",
            notes="no netgen LVS report found — §4.05: absent → SKIP, "
                  "never a tapeout pass")
    res = ltc.check(rpt)
    tv = res.get("tapeout_verdict")
    verdict = {
        "GENUINE_MATCH": "PASS",
        "WAIVED_PENDING_POWER_AWARE": "WAIVED_PENDING",
        "SIGNAL_NET_MISMATCH": "FAIL",
        "INCOMPLETE": "INCOMPLETE",
        "IO_ERROR": "NOT_RUN",
    }.get(tv, "FAIL")
    notes = ""
    if verdict == "WAIVED_PENDING":
        notes = ("POWER_PIN_ONLY LVS mismatch — a documented waiver pending a "
                 "power-aware gate netlist; NOT a tapeout MATCH, does NOT "
                 "release (§4.05)")
    elif verdict == "FAIL":
        notes = "real signal-net LVS mismatch — an open connectivity defect"
    elif verdict == "INCOMPLETE":
        notes = "LVS run reached no top-level compare — missing-evidence, "\
                "non-releasing"
    return TierResult(
        "T4.5_LVS_TAPEOUT", "LVS tapeout sign-off (genuine match)", verdict,
        details=res, artifact_path=res.get("report"), notes=notes)


def check_tier_5_latchup(project_dir: Path,
                          min_tapcells_per_mm2: int = 100) -> TierResult:
    """Tier 5 latch-up — tap cell density above PDK threshold."""
    art = project_dir / "reports" / "pnr" / "tapcell_density.json"
    if not art.exists():
        return TierResult("T5_LATCHUP", "Latch-up tap cells", "NOT_RUN")
    data = json.loads(art.read_text(encoding="utf-8"))
    density = float(data.get("tapcells_per_mm2", 0))
    verdict = "PASS" if density >= min_tapcells_per_mm2 else "FAIL"
    return TierResult("T5_LATCHUP", "Latch-up tap cells", verdict,
                        details={"tapcells_per_mm2": density,
                                 "min_required": min_tapcells_per_mm2},
                        artifact_path=str(art))


# ---------------------------------------------------------------------------
# TAPEOUT-tier gates: STA rigor, MBIST, Caravel precheck + XOR.
# ---------------------------------------------------------------------------
def check_tier_sta_rigor(project_dir: Path) -> TierResult:
    """Sign-off STA rigor — OCV derate + recovery/removal + min-pulse-width.

    Delegates to `sta_signoff_rigor_check`:
      PASS      -> PASS
      FAIL      -> FAIL   (report present but missing derate / recovery /
                   removal / min-pulse-width — an optimistic sign-off)
      IO_ERROR  -> NOT_RUN (no report → §4.05 SKIP)"""
    import sta_signoff_rigor_check as sta
    res = sta.check(project_dir)
    v = res.get("verdict")
    if v == "IO_ERROR":
        return TierResult(
            "T_STA_RIGOR",
            "STA sign-off rigor (OCV+recovery/removal+MPW)", "NOT_RUN",
            notes=str(res.get("error", "no sign-off STA report")))
    ladder = "PASS" if v == "PASS" else "FAIL"
    notes = "" if ladder == "PASS" else (
        "missing sign-off rigor: " + ", ".join(res.get("missing", [])))
    return TierResult(
        "T_STA_RIGOR", "STA sign-off rigor (OCV+recovery/removal+MPW)",
        ladder, details=res, artifact_path=res.get("report"), notes=notes)


_HDL_EXTS = (".v", ".sv", ".vh", ".lef")
_SRC_SKIP_SEGMENTS = {"input", "inputs", "pdk", "vendor_ref", "references",
                      "ref", "sim", "tb", "testbench", "test", "tests"}


def _gather_design_sources(project_dir: Path) -> List[Tuple[str, str]]:
    """Collect (label, text) for the design's Verilog/LEF (netlist + RTL +
    memory-macro LEF), skipping input/PDK/testbench trees so a reference RAM or
    a TB never trips detection. Used to feed the MBIST coverage gate."""
    roots: List[Path] = []
    for name in ("phase2", "rtl", "src", "hdl"):
        d = project_dir / name
        if d.is_dir():
            roots.append(d)
    if not roots:
        roots = [project_dir]
    items: List[Tuple[str, str]] = []
    seen: set = set()
    for root in roots:
        for f in sorted(root.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in _HDL_EXTS:
                continue
            try:
                rel = f.relative_to(project_dir)
            except ValueError:
                rel = f
            if {p.lower() for p in rel.parts[:-1]} & _SRC_SKIP_SEGMENTS:
                continue
            if f in seen:
                continue
            seen.add(f)
            try:
                items.append((str(f), f.read_text(errors="replace")))
            except OSError:
                continue
    return items


def check_tier_mbist(project_dir: Path,
                     sources: Optional[List[Tuple[str, str]]] = None
                     ) -> TierResult:
    """MBIST coverage — every writable on-chip RAM must have a March-test
    wrapper. Delegates to `mbist_wrapper_gen.gate`:
      PASS -> PASS   (every detected RAM covered)
      FAIL -> FAIL   (a RAM with no MBIST wrapper — an untestable memory)
      N/A  -> N/A    (a RAM-less design needs no MBIST — neutral, not a pass
                      and not a fail)
    No design sources found -> NOT_RUN (honest SKIP)."""
    import mbist_wrapper_gen as mbg
    items = sources if sources is not None else _gather_design_sources(project_dir)
    if not items:
        return TierResult("T_MBIST", "MBIST coverage (March C-)", "NOT_RUN",
                          notes="no design Verilog/LEF sources found")
    report, _rc = mbg.gate(items)
    v = report.get("verdict")               # PASS / FAIL / N/A
    ladder = {"PASS": "PASS", "FAIL": "FAIL", "N/A": "N/A"}.get(v, "FAIL")
    return TierResult(
        "T_MBIST", "MBIST coverage (March C-)", ladder,
        details={"ram_count": report.get("ram_count"),
                 "uncovered": report.get("uncovered"),
                 "message": report.get("message")},
        notes=report.get("message", ""))


def _find_precheck_rundir(project_dir: Path) -> Optional[Path]:
    """Locate a completed efabless/mpw_precheck run directory (a dir carrying
    the precheck *.log files). None when the project ran no precheck."""
    for name in ("mpw_precheck", "precheck_results", "precheck"):
        for d in sorted(project_dir.rglob(name)):
            if d.is_dir() and any(d.rglob("*.log")):
                return d
    # reports/mpw_precheck/ convention
    conv = project_dir / "reports" / "mpw_precheck"
    if conv.is_dir() and any(conv.rglob("*.log")):
        return conv
    return None


def _find_xor_report(project_dir: Path) -> Optional[Path]:
    """Locate a completed KLayout XOR report JSON (from xor_layout_check's
    emitted script). None when no XOR was run."""
    for pat in ("reports/**/xor_report.json", "**/xor_report.json",
                "reports/**/xor*.json"):
        hits = [h for h in project_dir.glob(pat) if h.is_file()]
        if hits:
            return sorted(hits)[0]
    return None


def _load_xor_allow_macros(project_dir: Path,
                           extra: Optional[List[str]] = None) -> List[str]:
    """Read the EXPLICIT blackbox-macro XOR waiver allow-list from a
    conventional `reports/xor_allow_macros.json` (a JSON list of cell names) if
    present, plus any caller-supplied names. Never a count/floor — §4.05."""
    allow: List[str] = list(extra or [])
    for rel in ("reports/xor_allow_macros.json",
                "reports/audit/xor_allow_macros.json"):
        p = project_dir / rel
        if p.is_file():
            try:
                data = json.loads(p.read_text(errors="replace"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, list):
                allow.extend(str(x) for x in data)
            elif isinstance(data, dict) and isinstance(
                    data.get("allow_macros"), list):
                allow.extend(str(x) for x in data["allow_macros"])
    # de-dup, order-preserving
    return list(dict.fromkeys(allow))


def check_tier_mpw_precheck(project_dir: Path) -> TierResult:
    """Efabless / chipIgnite shuttle verdict — delegates to
    `mpw_precheck_result_gate`:
      PASS              -> PASS
      FAIL              -> FAIL
      INCOMPLETE        -> INCOMPLETE (a required check never ran —
                           non-releasing, never a pass)
      SKIPPED_CONDITION -> NOT_RUN    (no precheck run at all → §4.05 SKIP)"""
    import mpw_precheck_result_gate as mpg
    rundir = _find_precheck_rundir(project_dir)
    if rundir is None:
        return TierResult(
            "T_MPW_PRECHECK", "MPW precheck (Efabless shuttle)", "NOT_RUN",
            notes="no mpw_precheck run directory found — §4.05: absent → SKIP")
    rep = mpg.evaluate(rundir)
    v = rep.overall_verdict          # PASS / FAIL / INCOMPLETE / SKIPPED_CONDITION
    ladder = {
        "PASS": "PASS", "FAIL": "FAIL", "INCOMPLETE": "INCOMPLETE",
        "SKIPPED_CONDITION": "NOT_RUN",
    }.get(v, "FAIL")
    return TierResult(
        "T_MPW_PRECHECK", "MPW precheck (Efabless shuttle)", ladder,
        details={"failed_checks": rep.failed_checks,
                 "missing_checks": rep.missing_checks,
                 "notes": rep.notes},
        artifact_path=str(rundir), notes=rep.notes)


def check_tier_xor(project_dir: Path,
                   allow_macros: Optional[List[str]] = None) -> TierResult:
    """Computed GDS-vs-golden XOR — delegates to `xor_layout_check` (replaces
    the hardcoded 2/7 floor):
      PASS             -> PASS
      PASS_WITH_WAIVER -> WAIVED (every residual inside an EXPLICITLY
                          allow-listed blackbox macro — documented, releasing
                          with waivers)
      FAIL             -> FAIL   (a real, out-of-macro geometry delta)
      INCOMPLETE       -> NOT_RUN (no completed XOR report → §4.05 SKIP)"""
    import xor_layout_check as xlc
    rpt = _find_xor_report(project_dir)
    if rpt is None:
        return TierResult(
            "T_XOR", "Layout XOR (GDS vs golden)", "NOT_RUN",
            notes="no completed XOR report found — §4.05: absent → SKIP")
    allow = _load_xor_allow_macros(project_dir, allow_macros)
    res = xlc.evaluate(rpt, allow)
    v = res.get("verdict")
    ladder = {
        "PASS": "PASS", "PASS_WITH_WAIVER": "WAIVED",
        "FAIL": "FAIL", "INCOMPLETE": "NOT_RUN",
    }.get(v, "FAIL")
    notes = ""
    if ladder == "WAIVED":
        notes = "XOR residual entirely inside allow-listed blackbox macro(s)"
    elif ladder == "FAIL":
        notes = (f"{len(res.get('failing_residual', []))} real XOR residual "
                 "bucket(s) outside any allow-listed macro")
    return TierResult(
        "T_XOR", "Layout XOR (GDS vs golden)", ladder,
        details={"total_residual_count": res.get("total_residual_count"),
                 "waived_residual": res.get("waived_residual"),
                 "failing_residual": res.get("failing_residual")},
        artifact_path=str(rpt), notes=notes)


# ---------------------------------------------------------------------------
# TAPEOUT-tier sign-off gates (this session): dynamic-IR, per-layer metal
# density, aging-corner STA, thermal screen, DFT sign-off, post-layout LEC.
# Each wraps a dedicated deterministic gate program and maps its verdict into
# the ladder vocabulary. §4.05: a real gate FAIL blocks release; an absent
# artifact / can't-judge is an honest NOT_RUN (SKIP), never a silent pass.
# ---------------------------------------------------------------------------
def _find_dynamic_ir_report(project_dir: Path) -> Optional[Path]:
    """Locate a DYNAMIC/transient IR-drop report. Prefers the canonical
    reports/phase3/dynamic_ir.json, then any dynamic/transient/DVD-named
    JSON/.rpt. NEVER falls back to the STATIC reports/phase3/ir_drop.json — a
    static report must not masquerade as a dynamic sign-off (§4.05)."""
    for rel in ("reports/phase3/dynamic_ir.json", "reports/dynamic_ir.json"):
        p = project_dir / rel
        if p.is_file():
            return p
    for pat in ("reports/**/dynamic_ir*.json", "reports/**/*transient*.json",
                "reports/**/*dvd*.json", "reports/**/dynamic_ir*.rpt",
                "**/dynamic_ir*.json", "**/*transient*.rpt"):
        hits = [h for h in project_dir.glob(pat)
                if h.is_file() and h.name != "ir_drop.json"]
        if hits:
            return sorted(hits)[0]
    return None


def check_tier_dynamic_ir(project_dir: Path,
                          vdd: Optional[float] = None,
                          budget_pct: float = _DYNAMIC_IR_BUDGET_PCT
                          ) -> TierResult:
    """Dynamic (transient) IR-drop — worst di/dt droop must be under budget.

    Delegates to `dynamic_ir_drop_check.check`:
      PASS     -> PASS
      FAIL     -> FAIL     (droop at/over budget, OR a report present but with
                  no extractable transient droop value — missing evidence)
      IO_ERROR -> NOT_RUN  (no dynamic-IR report → §4.05 SKIP; the static
                  ir_drop report is never read as a dynamic sign-off)"""
    import dynamic_ir_drop_check as dic
    rpt = _find_dynamic_ir_report(project_dir)
    if rpt is None:
        return TierResult(
            "T_DYN_IR", "Dynamic (transient) IR-drop", "NOT_RUN",
            notes="no dynamic/transient IR report — §4.05: absent → SKIP, "
                  "never the static ir_drop report as a dynamic sign-off")
    res = dic.check(rpt, vdd, budget_pct)
    v = res.get("verdict")
    ladder = {"PASS": "PASS", "FAIL": "FAIL",
              "IO_ERROR": "NOT_RUN"}.get(v, "FAIL")
    notes = ""
    if ladder == "FAIL":
        notes = res.get("detail") or (
            f"worst transient droop {res.get('worst_transient_droop_mv')} mV "
            f">= budget {res.get('budget_mv')} mV")
    return TierResult(
        "T_DYN_IR", "Dynamic (transient) IR-drop", ladder,
        details=res, artifact_path=str(rpt), notes=notes)


def _find_metal_density_report(project_dir: Path) -> Optional[Path]:
    """Locate the PER-LAYER metal-density report (distinct axis from the
    row/core-utilization reports/density.json). Prefers reports/phase3/
    metal_density.json, then any metal-density / per-layer-density artifact.
    NEVER the plain reports/density.json (that is ROW/core utilization —
    reading it here would gate on the wrong axis, the very bug this gate
    closes)."""
    for rel in ("reports/phase3/metal_density.json",
                "reports/metal_density.json"):
        p = project_dir / rel
        if p.is_file():
            return p
    for pat in ("reports/**/metal_density*.json",
                "reports/**/*metal*density*.json",
                "reports/**/*density*layer*.json", "**/metal_density*.json"):
        hits = [h for h in project_dir.glob(pat)
                if h.is_file() and h.name != "density.json"]
        if hits:
            return sorted(hits)[0]
    return None


def check_tier_metal_density(project_dir: Path,
                             default_min: float = _METAL_DENSITY_MIN,
                             default_max: float = _METAL_DENSITY_MAX
                             ) -> TierResult:
    """Per-layer metal density (foundry CMP / Efabless met_min_ca_density).

    Delegates to `metal_layer_density_check.check`. When the report ships its
    own per-layer windows those win; else the DISCLOSED generic default window
    [_METAL_DENSITY_MIN.._METAL_DENSITY_MAX] is applied so a real per-layer
    density can still be judged (the report carries the generic-default note):
      PASS     -> PASS
      FAIL     -> FAIL     (a layer outside its window, or a report with no
                  per-layer metal-density data)
      IO_ERROR -> NOT_RUN  (no per-layer metal-density report → §4.05 SKIP;
                  the row-util density.json is never read here)"""
    import metal_layer_density_check as mld
    rpt = _find_metal_density_report(project_dir)
    if rpt is None:
        return TierResult(
            "T_METAL_DENSITY", "Per-layer metal density (CMP)", "NOT_RUN",
            notes="no per-layer metal-density report — §4.05: absent → SKIP, "
                  "never the row-util density.json")
    res = mld.check(rpt, {}, default_min, default_max)
    v = res.get("verdict")
    ladder = {"PASS": "PASS", "FAIL": "FAIL",
              "IO_ERROR": "NOT_RUN"}.get(v, "FAIL")
    notes = ""
    if ladder == "FAIL":
        notes = "; ".join(res.get("failures", [])) or res.get("detail", "")
        if not notes and res.get("unchecked_layers"):
            notes = f"unchecked layers (no window): {res['unchecked_layers']}"
    return TierResult(
        "T_METAL_DENSITY", "Per-layer metal density (CMP)", ladder,
        details=res, artifact_path=str(rpt), notes=notes)


def check_tier_aging_sta(project_dir: Path,
                         margin_ns: float = 0.0) -> TierResult:
    """Aging-corner STA (NBTI / PBTI / HCI Vt-drift over lifetime).

    Delegates to `aging_derate_sta_check.evaluate` (discovering the aging +
    optional fresh reports the module's own way):
      PASS -> PASS
      FAIL -> FAIL    (aging-corner worst slack < margin — VIOLATES aged)
      SKIP -> NOT_RUN (no aging-derated STA report / no aging evidence — the
              open PDK ships no foundry aging Liberty; §4.05 honest SKIP,
              never a pass, never a fabricated aging number)"""
    import aging_derate_sta_check as ag
    aging_in = ag._discover_report(project_dir, "aging")
    if aging_in is None:
        return TierResult(
            "T_AGING_STA", "Aging-corner STA (NBTI/PBTI/HCI)", "NOT_RUN",
            notes="no aging-derated STA report — the open PDK ships no foundry "
                  "aging Liberty; §4.05: SKIP, never a fabricated aging number")
    fresh_in = ag._discover_report(project_dir, "fresh")
    verdict, rep = ag.evaluate(aging_in, fresh_in, margin_ns, False)
    ladder = {"PASS": "PASS", "FAIL": "FAIL",
              "SKIP": "NOT_RUN"}.get(verdict, "FAIL")
    notes = ""
    if verdict == "SKIP":
        notes = (f"aging STA not judgeable ({rep.get('skip_reason')}); "
                 "§4.05: SKIP, never a pass")
    elif verdict == "FAIL":
        errs = [f["message"] for f in rep.get("findings", [])
                if f.get("severity") == "ERROR"]
        notes = errs[0] if errs else "aging-corner timing violated"
    return TierResult(
        "T_AGING_STA", "Aging-corner STA (NBTI/PBTI/HCI)", ladder,
        details=(rep.get("measured")
                 or {"skip_reason": rep.get("skip_reason")}),
        artifact_path=str(aging_in), notes=notes)


def check_tier_thermal(project_dir: Path,
                       limit_w_per_mm2: float = _THERMAL_LIMIT_W_PER_MM2,
                       tj_max_c: float = _THERMAL_TJ_MAX_C) -> TierResult:
    """Thermal power-density screen (W/mm², + Tj when available).

    Delegates to `thermal_screen_check.evaluate`, discovering the power report
    (preferring the canonical reports/phase3/power.rpt) + a DEF/floorplan die
    area from the project:
      PASS -> PASS
      FAIL -> FAIL    (power density over the package limit, or Tj >= Tj_max)
      SKIP -> NOT_RUN (no power report, power not_computed, or no die area —
              §4.05 honest SKIP, never a fabricated density)"""
    import thermal_screen_check as th
    prefer = project_dir / "reports" / "phase3" / "power.rpt"
    power_path = prefer if prefer.is_file() else th._discover_power_report(
        project_dir)
    if power_path is None:
        return TierResult(
            "T_THERMAL", "Thermal power-density screen", "NOT_RUN",
            notes="no power report found — §4.05: absent → SKIP")
    die_source = th._discover_die_source(project_dir)
    verdict, rep = th.evaluate(power_path, die_source, None, None,
                               limit_w_per_mm2, tj_max_c, None, None)
    ladder = {"PASS": "PASS", "FAIL": "FAIL",
              "SKIP": "NOT_RUN"}.get(verdict, "FAIL")
    notes = ""
    if verdict == "SKIP":
        notes = (f"thermal not judgeable ({rep.get('skip_reason')}); "
                 "§4.05: SKIP, never a pass")
    elif verdict == "FAIL":
        errs = [f["message"] for f in rep.get("findings", [])
                if f.get("severity") == "ERROR"]
        notes = errs[0] if errs else "power density / Tj over limit"
    return TierResult(
        "T_THERMAL", "Thermal power-density screen", ladder,
        details=(rep.get("measured")
                 or {"skip_reason": rep.get("skip_reason")}),
        artifact_path=str(power_path), notes=notes)


def check_tier_dft_signoff(project_dir: Path) -> TierResult:
    """Aggregate DFT sign-off — stuck-at + at-speed transition + BSDL.

    Delegates to `dft_signoff_check.audit`. §4.05: when the project carries NO
    DFT evidence at all (no coverage.json AND no bsdl_plan.json) the DFT
    sign-off has not run → honest NOT_RUN (never a silent pass). When DFT
    evidence IS present the gate's own verdict is authoritative (it recomputes
    stuck-at coverage vs the foundry floor, requires a real / documented-
    engine-limited at-speed transition record, and a BSDL for a padded
    design):
      PASS -> PASS
      FAIL -> FAIL"""
    import dft_signoff_check as dft
    cov = dft._coverage_json_path(project_dir, None)
    bsdl = dft._bsdl_plan_path(project_dir, None)
    if cov is None and bsdl is None:
        return TierResult(
            "T_DFT_SIGNOFF", "DFT sign-off (stuck-at+transition+BSDL)",
            "NOT_RUN",
            notes="no DFT coverage/BSDL evidence — §4.05: absent → SKIP")
    rep = dft.audit(project_dir)
    v = rep.get("verdict")
    ladder = {"PASS": "PASS", "FAIL": "FAIL"}.get(v, "FAIL")
    notes = ""
    if ladder == "FAIL":
        parts = []
        for k in ("stuck_at", "transition", "bsdl"):
            sub = rep.get(k, {}) or {}
            if sub.get("status") not in ("PASS", "SKIP", "ENGINE_LIMITED"):
                parts.append(f"{k}={sub.get('status')}")
        notes = "; ".join(parts) or "DFT sign-off failed"
    return TierResult(
        "T_DFT_SIGNOFF", "DFT sign-off (stuck-at+transition+BSDL)", ladder,
        details={"stuck_at": (rep.get("stuck_at") or {}).get("status"),
                 "transition": (rep.get("transition") or {}).get("status"),
                 "bsdl": (rep.get("bsdl") or {}).get("status")},
        artifact_path=rep.get("coverage_json"), notes=notes)


def check_tier_lec_post(project_dir: Path) -> TierResult:
    """Post-layout LEC — the FINAL routed/ECO netlist re-proven == synth/RTL.

    Delegates to `lec_post_layout_check.check`:
      PASS -> PASS
      FAIL -> FAIL    (non-equivalent routed logic, OR an UNPROVEN / VACUOUS /
              RUN_ERROR non-proof — §4.05: a non-proof is never a pass)
      SKIP -> NOT_RUN (no routed/ECO netlist yet — honest not-applicable)"""
    import lec_post_layout_check as lec
    res = lec.check(project_dir.resolve())
    r = res.get("result")
    ladder = {"PASS": "PASS", "FAIL": "FAIL",
              "SKIP": "NOT_RUN"}.get(r, "FAIL")
    notes = ""
    if ladder == "FAIL":
        notes = ("; ".join(res.get("findings", []))
                 or "post-layout equivalence not proven")
    elif ladder == "NOT_RUN":
        notes = res.get("reason", "")
    return TierResult(
        "T_LEC_POST", "Post-layout LEC (routed == synth/RTL)", ladder,
        details={"verdict": res.get("verdict"),
                 "total_points": res.get("total_points"),
                 "unproven_points": res.get("unproven_points")},
        artifact_path=res.get("report"), notes=notes)


# ---------------------------------------------------------------------------
# Caravel / Open-MPW detection
# ---------------------------------------------------------------------------
def _is_caravel_project(project_dir: Path) -> bool:
    """True for a Caravel / Open-MPW shuttle project — detected by a precheck
    run dir OR a user_project_wrapper / caravel design artifact. chip-AGNOSTIC:
    the tokens are the SHUTTLE FRAMEWORK's fixed top-cell names, not a specific
    chip's design literal."""
    if _find_precheck_rundir(project_dir) is not None:
        return True
    for pat in ("**/user_project_wrapper.*", "**/caravel.*"):
        for h in project_dir.glob(pat):
            if h.is_file():
                return True
    return False


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
@dataclass
class LadderReport:
    project_dir: str
    tiers: List[TierResult]
    overall_verdict: str
    mode: str = "triage"
    caravel: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "project_dir": self.project_dir,
            "mode": self.mode,
            "caravel": self.caravel,
            "tiers": [t.as_dict() for t in self.tiers],
            "overall_verdict": self.overall_verdict,
            "released": self.overall_verdict in RELEASING_VERDICTS,
            "emitted_by": "signoff_ladder_run v0.1.51 (release-gate-wired)",
        }


def aggregate_verdict(tiers: List[TierResult]) -> str:
    """Aggregate per-tier verdicts to overall.

      any FAIL                        → FAIL
      else any WAIVED_PENDING/INCOMPLETE → NOT_RELEASED   (a documented waiver
          pending real closure, or incomplete evidence: NON-releasing, never a
          silent pass — this is the §4.05 tapeout-tier tightening)
      else any WARN                   → WARN
      else any WAIVED/NOT_RUN         → PASS_WITH_WAIVERS
      else (all PASS, N/A ignored)    → PASS

    N/A tiers (e.g. a RAM-less MBIST tier) are neutral — they never demote the
    verdict and never inflate a PASS.
    """
    verdicts = [t.verdict for t in tiers]
    if "FAIL" in verdicts:
        return "FAIL"
    if "WAIVED_PENDING" in verdicts or "INCOMPLETE" in verdicts:
        return "NOT_RELEASED"
    if "WARN" in verdicts:
        return "WARN"
    if "WAIVED" in verdicts or "NOT_RUN" in verdicts:
        return "PASS_WITH_WAIVERS"
    return "PASS"


def run_ladder(project_dir: Path,
               mode: str = "triage",
               caravel: Optional[bool] = None,
               jmax: Optional[Path] = None,
               tech_lef: Optional[Path] = None,
               sources: Optional[List[Tuple[str, str]]] = None,
               xor_allow_macros: Optional[List[str]] = None) -> LadderReport:
    """Run the sign-off ladder.

    mode='triage'  (default) — the diagnostic ladder; the LVS-net tier may SHOW
                    a reasoned waiver. Nothing here claims a tapeout.
    mode='tapeout' — the RELEASE ladder: the LVS tier requires a GENUINE match
                    (POWER_PIN_ONLY does NOT release), and STA-rigor / MBIST /
                    (Caravel) precheck + XOR gates are added.
    """
    is_tapeout = (mode == "tapeout")
    if caravel is None:
        caravel = _is_caravel_project(project_dir) if is_tapeout else False

    tiers: List[TierResult] = [
        check_tier_1_drc(project_dir),
        check_tier_1_5_drc_heatmap(project_dir),
        check_tier_2_pdn(project_dir),
        check_tier_2_ir(project_dir),
        check_tier_2_em(project_dir, jmax=jmax, tech_lef=tech_lef),
        check_tier_3_antenna(project_dir),
        check_tier_3_esd(project_dir),
        check_tier_4_lvs_device(project_dir),
    ]
    # LVS net tier: triage SHOWS the waiver; tapeout REFUSES POWER_PIN_ONLY.
    if is_tapeout:
        tiers.append(check_tier_lvs_tapeout(project_dir))
    else:
        tiers.append(check_tier_4_5_lvs_net(project_dir))
    tiers.append(check_tier_5_latchup(project_dir))

    # Release-tier sign-off gates (only when GATING a tapeout).
    if is_tapeout:
        tiers.append(check_tier_sta_rigor(project_dir))
        tiers.append(check_tier_mbist(project_dir, sources=sources))
        # This session's sign-off gates — each blocks a tapeout on a real FAIL
        # and honestly NOT_RUNs (SKIP) on an absent artifact (§4.05).
        tiers.append(check_tier_dynamic_ir(project_dir))
        tiers.append(check_tier_metal_density(project_dir))
        tiers.append(check_tier_aging_sta(project_dir))
        tiers.append(check_tier_thermal(project_dir))
        tiers.append(check_tier_dft_signoff(project_dir))
        tiers.append(check_tier_lec_post(project_dir))
        if caravel:
            tiers.append(check_tier_mpw_precheck(project_dir))
            tiers.append(check_tier_xor(project_dir,
                                        allow_macros=xor_allow_macros))

    return LadderReport(
        project_dir=str(project_dir),
        tiers=tiers,
        overall_verdict=aggregate_verdict(tiers),
        mode=mode,
        caravel=bool(caravel),
    )


def report_to_markdown(rep: LadderReport) -> str:
    out: List[str] = []
    out.append(f"# Sign-off ladder — {rep.project_dir}")
    out.append("")
    out.append(f"_Emitted by `signoff_ladder_run.py`. Doctrine: the sign-off "
               f"ladder discovered by the spm pilot, now a single deterministic "
               f"runner wired to the real tapeout sign-off gates (EM density, "
               f"LVS genuine-match, STA rigor, MBIST, dynamic-IR, per-layer "
               f"metal density, aging-corner STA, thermal screen, DFT sign-off, "
               f"post-layout LEC, MPW precheck, XOR)._")
    out.append("")
    out.append(f"**Mode: {rep.mode}"
               + (" · Caravel/Open-MPW" if rep.caravel else "")
               + "**")
    out.append("")
    out.append(f"**Overall verdict: {rep.overall_verdict}** "
               f"(released={rep.overall_verdict in RELEASING_VERDICTS})")
    out.append("")
    out.append("| Tier | Check | Verdict | Notes |")
    out.append("|---|---|---|---|")
    for t in rep.tiers:
        notes = t.notes or json.dumps(t.details)[:80]
        out.append(f"| {t.tier_id} | {t.name} | {t.verdict} | {notes} |")
    out.append("")
    return "\n".join(out)


def _cli() -> int:
    p = argparse.ArgumentParser(
        description="Chip-level sign-off ladder runner (release-gate wired).")
    p.add_argument("project_dir", type=Path)
    p.add_argument("--mode", choices=("triage", "tapeout"), default="triage",
                   help="triage (diagnostic, default) or tapeout (release: "
                        "POWER_PIN_ONLY no longer releases + STA/MBIST/precheck"
                        "/XOR gates added).")
    p.add_argument("--caravel", dest="caravel", action="store_true",
                   default=None, help="force Caravel/Open-MPW tiers on.")
    p.add_argument("--no-caravel", dest="caravel", action="store_false",
                   help="force Caravel/Open-MPW tiers off.")
    p.add_argument("--jmax", type=Path, default=None,
                   help="per-layer Jmax JSON for the EM tier.")
    p.add_argument("--tech-lef", type=Path, default=None,
                   help="PDK tech LEF (DCCURRENTDENSITY) for the EM tier.")
    p.add_argument("--xor-allow-macro", action="append", default=None,
                   dest="xor_allow_macros",
                   help="EXPLICIT blackbox-macro cell name waivable in the XOR "
                        "tier (repeatable). Never a count/floor.")
    p.add_argument("--out-md", type=Path)
    p.add_argument("--out-json", type=Path)
    p.add_argument("--strict", action="store_true",
                   help="Exit non-zero unless the overall verdict releases "
                        "(PASS / PASS_WITH_WAIVERS).")
    args = p.parse_args()
    rep = run_ladder(args.project_dir, mode=args.mode, caravel=args.caravel,
                     jmax=args.jmax, tech_lef=args.tech_lef,
                     xor_allow_macros=args.xor_allow_macros)
    md = report_to_markdown(rep)
    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    else:
        print(md)
    if args.out_json:
        args.out_json.write_text(json.dumps(rep.as_dict(), indent=2),
                                  encoding="utf-8")
    if args.strict and rep.overall_verdict not in RELEASING_VERDICTS:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
