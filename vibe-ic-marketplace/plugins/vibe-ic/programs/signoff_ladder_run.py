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
                      tapeout — and so `released` is ALWAYS False in this
                      mode, whatever the overall verdict reads.
  tapeout           — the RELEASE ladder. POWER_PIN_ONLY no longer
                      releases; STA-rigor / MBIST / (Caravel) precheck +
                      XOR gates are added. Only this mode tightens, and
                      only this mode can set `released`.

§4.05 (LOAD-BEARING): a design whose real gate FAILs makes the ladder NOT
release; a POWER_PIN_ONLY LVS does NOT count as a tapeout pass; a missing
artifact is an honest SKIP/NOT_RUN, never a silent pass.

The §4.05 "never a silent pass" rule binds the AGGREGATE, not just the tier
label. Labelling a tier NOT_RUN and then aggregating it to a releasing verdict
IS the silent pass the rule forbids — the release decision, not the row in the
table, is what a reader acts on. So:

  * ABSENT evidence never releases. A release-gating tier that produced no
    artifact aggregates to `NOT_RELEASED_EVIDENCE_ABSENT`, alongside the
    already-non-releasing `WAIVED_PENDING` / `INCOMPLETE`. The reasoning the
    module already wrote for INCOMPLETE ("incomplete evidence: NON-releasing")
    applies more strongly to evidence that does not exist at all.
  * A REVIEWED WAIVER still releases, and stays distinguishable. `WAIVED` is a
    decision a human made and documented (an allow-listed blackbox-macro XOR
    residual, a reasoned triage LVS waiver, a reviewed ENV_UNAVAILABLE tier
    deferral read from the project's `waivers.json`); `NOT_RUN` is nobody
    deciding anything. They aggregate to different verdicts — collapsing them
    is what let an all-NOT_RUN design read as PASS_WITH_WAIVERS.
  * A tier that legitimately CANNOT run has a reviewed way out, and only that.
    See `apply_tier_waivers` — the ladder's ingestion of the project's reviewed
    waivers, built on the ONE shared reader (`_waiver_entries`, #519) and
    modelled on `flow_compliance_check._synthesise_fpga_skip_waivers`:
    disclosure buys deferral, silence buys failure, and a waiver naming a tier
    that RAN is refused out loud so it can never overwrite a real result.
  * `released` respects the MODE. `triage` is the diagnostic ladder and its own
    docstring says "Nothing here claims a tapeout", so triage NEVER sets
    `released`; only the `tapeout` release ladder can.

Each tier is a deterministic check; the runner does not invoke EDA tools
itself (that is mcp-eda's job) — it consumes per-tier check artifacts (or
delegates to the dedicated sign-off gate programs) and emits a canonical
verdict. chip-AGNOSTIC: no design/PDK literal appears in any rule.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROGRAMS = Path(__file__).resolve().parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _evidence_independence as _ev_ind  # noqa: E402  (path bootstrap above)
import _signoff_drc_format as _sdf  # noqa: E402  (ONE producer/dialect answer)
import _waiver_entries as _we  # noqa: E402  (#519's ONE waiver reader)
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


# ---------------------------------------------------------------------------
# Verdict vocabulary
# ---------------------------------------------------------------------------
# A ladder overall_verdict is "releasing" iff it is one of these. Everything
# else (FAIL / WARN / NOT_RELEASED / NOT_RELEASED_EVIDENCE_ABSENT) blocks a
# tapeout release.
RELEASING_VERDICTS = ("PASS", "PASS_WITH_WAIVERS")

# The overall verdict for "nothing was checked": at least one RELEASE-GATING
# tier produced no evidence at all. NON-releasing, for the reason the module
# already recorded for INCOMPLETE — evidence that does not exist cannot be a
# pass. Named with the `NOT_RELEASED` prefix so a consumer that only
# pattern-matches the blocking family still classifies it as blocking, and it
# carries no PASS/FAIL substring a text scanner could misread.
NOT_RELEASED_EVIDENCE_ABSENT = "NOT_RELEASED_EVIDENCE_ABSENT"

# The overall verdict for "every gate was deferred, none was executed": the
# ladder carries at least one reviewed waiver and NOT ONE release-gating tier
# reached a PASS. NON-releasing.
#
# #520 established that absence does not release. A reviewed waiver is not
# absence — somebody decided and owns it — and one, or several, correctly
# release a design whose other gates really ran. But a ladder where EVERY gate
# was deferred has run no sign-off at all, and a stack of paperwork over an
# empty ladder is the same claim #520 refused, re-entered through the front
# door. The line is not arbitrary: it is the difference between a sign-off with
# documented gaps and no sign-off. Same `NOT_RELEASED` prefix so a consumer
# matching the blocking family still classifies it correctly.
NOT_RELEASED_ALL_WAIVED = "NOT_RELEASED_ALL_WAIVED"

# Per-tier verdicts that block a release wherever they appear, gating or not.
# (`NOT_RUN` blocks too, but only from a release-GATING tier — see
# `TierResult.release_gating`.) Deliberately conservative: a non-gating tier can
# still block, it can just never be the SOLE reason a release is withheld.
BLOCKING_TIER_VERDICTS = ("FAIL", "WAIVED_PENDING", "INCOMPLETE", "WARN")

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
    # True  → a real sign-off gate: its ABSENCE (NOT_RUN) withholds the release,
    #         because a tapeout cannot be signed off on a check nobody ran.
    # False → an advisory/diagnostic row that is not part of the sign-off
    #         evidence set, so its absence alone never withholds a release. This
    #         is the ONLY way a NOT_RUN can be non-blocking, it is set in code
    #         (never from a design artifact, so no project can opt its own gates
    #         out), and a FAIL/WARN on such a tier still blocks.
    release_gating: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Report discovery — the SAME flexible discovery the new tapeout tiers use
# (`_discover_em_report`, `_find_lvs_report`, `_find_dynamic_ir_report`), so the
# OLD sign-off tiers stop reading DEAD legacy paths that NO runner program
# writes. Each old tier prefers the canonical `reports/phase3/<name>` the
# phase3 runner actually emits, then an rglob, then the legacy path — so a
# GENUINELY absent artifact still NOT_RUNs (§4.05) but a real one is parsed to
# its real verdict (which can only surface a masked FAIL, never fabricate a
# pass). chip-AGNOSTIC: matches only on conventional report names.
# ---------------------------------------------------------------------------
def _discover_signoff_report(project_dir: Path,
                             phase3_names: Tuple[str, ...],
                             rglob_pats: Tuple[str, ...] = (),
                             legacy_rels: Tuple[str, ...] = ()
                             ) -> Optional[Path]:
    """Prefer reports/phase3/<name> (the runner's canonical path), then any
    rglob match, then the legacy path. None → the artifact is genuinely
    absent (an honest NOT_RUN, never a silent pass)."""
    for name in phase3_names:
        p = project_dir / "reports" / "phase3" / name
        if p.is_file():
            return p
    for pat in rglob_pats:
        hits = sorted(h for h in project_dir.glob(pat) if h.is_file())
        if hits:
            return hits[0]
    for rel in legacy_rels:
        p = project_dir / rel
        if p.is_file():
            return p
    return None


_DRC_COUNT_RES = (
    re.compile(r"violation\s+report\s*[:=]?\s*(\d+)", re.I),
    re.compile(r"(\d+)\s+violation(?:s)?\s+(?:found|detected)", re.I),
    re.compile(r"(?:number\s+of\s+(?:DRC\s+)?violations|total\s+violations)"
               r"\s*[:=]?\s*(\d+)", re.I),
    re.compile(r"total\s+(?:DRC\s+)?(?:errors|violations)\s*[:=]?\s*(\d+)", re.I),
)


def _parse_drc_violations(art: Path) -> Tuple[Optional[int], str]:
    """Return (violation_count | None, source_note) from a DRC artifact.

    Handles the THREE real runner shapes: (1) a `full_deck`/`drc_signoff`
    JSON carrying a `violations` count (or `clean`/`verdict`), (2) a KLayout
    XML sign-off report (`drc_signoff.rpt` re-staged from `phase3/reports/
    drc.rpt`) where each `<item>` under `<items>` is one violation, and (3) a
    plain-text OpenROAD/Magic DRC report carrying an explicit
    `violation report: N` / `N violation(s) found` count. Returns
    (None, reason) only when the report is present but no count can be
    extracted — the caller keeps that honest (NOT_RUN), never a fabricated
    pass. chip-AGNOSTIC."""
    try:
        text = art.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, f"unreadable ({exc})"
    # (1) JSON count / clean / verdict.
    if art.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            for k in ("violations", "total_violations", "violation_count",
                      "count", "num_violations"):
                if data.get(k) is not None:
                    try:
                        return int(data[k]), k
                    except (TypeError, ValueError):
                        pass
            v = str(data.get("verdict", "")).upper()
            if v in ("PASS", "CLEAN"):
                return 0, "verdict=PASS"
            if v in ("FAIL", "DIRTY"):
                return None, "verdict=FAIL (no count)"
            if data.get("clean") is True:
                return 0, "clean=true"
            if data.get("clean") is False:
                return None, "clean=false (no count)"
    # (2) KLayout XML report — count <item> elements (violations), NOT the
    # <category> rule descriptions. An empty <items></items> = 0 = clean.
    if "<report-database" in text or "<items>" in text or "</item>" in text:
        return len(re.findall(r"<item>", text)), "klayout_items"
    # (2b) SVRF-native sign-off — a per-rule FAIL/PASS tally and NO summary
    # line. MEASURED before this branch existed: a clean 4533-PASS foundry-deck
    # sign-off returned (None, "no count pattern"), i.e. the HIGHEST-authority
    # producer was the one this release-gating tier could not judge, while the
    # router's projection below was judged PASS. Same grammar as
    # `signoff_audit` and `eda_report_audit`, imported rather than re-authored.
    _svrf = _sdf.svrf_fail_count(text)
    if _svrf is not None:
        return _svrf, "svrf_rule_fails"
    # (3) plain-text report — explicit count patterns; else "DRC clean: YES".
    for rx in _DRC_COUNT_RES:
        hits = rx.findall(text)
        if hits:
            try:
                return max(int(h) for h in hits), "text_count"
            except ValueError:
                pass
    if re.search(r"DRC\s+clean\s*[:=]?\s*YES", text, re.I):
        return 0, "text_clean_yes"
    if re.search(r"DRC\s+clean\s*[:=]?\s*NO", text, re.I):
        return None, "text_clean_no (no count)"
    return None, "no count pattern"


# ---------------------------------------------------------------------------
# Per-tier checkers — artifact consumers
# ---------------------------------------------------------------------------
def check_tier_1_drc(project_dir: Path) -> TierResult:
    """Tier 1 DRC — the runner writes `reports/phase3/drc_signoff.rpt` (a
    re-staged KLayout XML sign-off report), NOT the legacy
    `reports/drc/full_deck.json`. Discover the real report (phase3 → rglob →
    legacy) and count violations. §4.05: an absent report still NOT_RUNs; a
    discovered report is parsed to its REAL count so a masked DRC FAIL
    surfaces, never a fabricated pass."""
    art = _discover_signoff_report(
        project_dir,
        phase3_names=("drc_signoff.rpt", "drc_signoff.json",
                      "drc.rpt", "drc.json"),
        rglob_pats=("reports/**/drc_signoff.rpt",
                    "reports/**/drc_signoff.json"),
        legacy_rels=("reports/drc/full_deck.json",))
    if art is None:
        return TierResult("T1", "Full DRC (KLayout/Magic)", "NOT_RUN",
                            notes="no DRC sign-off report "
                                  "(reports/phase3/drc_signoff.rpt) — "
                                  "§4.05: absent → SKIP")
    # THE TIER IS NAMED FOR ITS PRODUCER AND MUST CHECK IT. MEASURED on
    # origin/main, handed a project whose `reports/phase3/drc_signoff.rpt` is
    # the router's own detailed-route projection::
    #
    #   check_tier_1_drc(proj) -> TierResult(tier_id='T1',
    #       name='Full DRC (KLayout/Magic)', verdict='PASS',
    #       details={'violations': 0, 'count_source': 'text_count'},
    #       release_gating=True)
    #
    # A release-gating tier literally named for KLayout/Magic issuing PASS from
    # an OpenROAD router log. The router's DRC is a routability measurement over
    # its own database, not a rule deck applied to a layout.
    #
    # THE RULE IS MONOTONE: router evidence can WITHHOLD credit, never grant it,
    # and it can never REMOVE a failure. A router-level violation is a real
    # defect and keeps its FAIL (FAIL is not waivable; downgrading it to NOT_RUN
    # would have made it deferrable through waivers.json — a weakening). Only
    # the router's CLEAN — the verdict it is not competent to give — becomes
    # NOT_RUN, which is the state the governed waiver channel exists for.
    _prod = _sdf.classify_file(art)
    if _prod.kind == _sdf.OPENROAD:
        _n, _src = _parse_drc_violations(art)
        if _n is None or _n == 0:
            return TierResult(
                "T1", "Full DRC (KLayout/Magic)", "NOT_RUN",
                details={"producer": _prod.kind, "evidence": _prod.evidence,
                         "router_violations": _n},
                artifact_path=str(art),
                notes="the sign-off DRC artifact is the ROUTER's own "
                      "detailed-route DRC projection, not a KLayout/Magic/SVRF "
                      "sign-off deck run — this tier did not run. §4.05: a "
                      "producer that cannot answer the question is a SKIP, "
                      "never a pass.")
        return TierResult(
            "T1", "Full DRC (KLayout/Magic)", "FAIL",
            details={"violations": _n, "count_source": _src,
                     "producer": _prod.kind},
            artifact_path=str(art),
            notes="ROUTER-level DRC violations. The sign-off deck did not run, "
                  "so this count is a floor, not the sign-off verdict.")
    n, src = _parse_drc_violations(art)
    if n is None:
        return TierResult(
            "T1", "Full DRC (KLayout/Magic)", "NOT_RUN",
            details={"parse": src}, artifact_path=str(art),
            notes=f"DRC report present but no count extractable ({src}) — "
                  "§4.05: not judgeable → SKIP, never a fabricated pass")
    verdict = "PASS" if n == 0 else "FAIL"
    return TierResult("T1", "Full DRC (KLayout/Magic)", verdict,
                        details={"violations": n, "count_source": src},
                        artifact_path=str(art))


def check_tier_1_5_drc_heatmap(project_dir: Path) -> TierResult:
    """Tier 1.5 — diagnostic only, report presence.

    NOT a sign-off gate: the heatmap is a where-are-the-violations visual aid
    over the SAME data tier T1 already signs off, so its absence is a missing
    convenience, not missing sign-off evidence. Hence `release_gating=False` —
    a design does not lose its release because nobody drew the picture. T1, the
    tier that actually judges the DRC result, remains fully gating.
    """
    art = project_dir / "reports" / "drc" / "geographic_heatmap.json"
    if not art.exists():
        return TierResult("T1.5", "DRC heatmap", "NOT_RUN",
                            notes="diagnostic only (not a release gate)",
                            release_gating=False)
    return TierResult("T1.5", "DRC heatmap", "PASS",
                        artifact_path=str(art), release_gating=False)


_SPECIALNETS_HDR_RE = re.compile(r"^\s*SPECIALNETS\s+(\d+)\s*;", re.M)


def _discover_pnr_dir(project_dir: Path) -> Optional[Path]:
    """Locate the P&R output dir that holds the routed *.def. Prefers the
    canonical phase3/stage3/pnr/, then any directory containing a *.def."""
    canonical = project_dir / "phase3" / "stage3" / "pnr"
    if canonical.is_dir() and any(canonical.glob("*.def")):
        return canonical
    for d in sorted({p.parent for p in project_dir.rglob("*.def")
                     if p.is_file()}):
        return d
    return None


def _def_specialnets_count(pnr: Path) -> Optional[int]:
    """Max SPECIALNETS header count declared across the DEFs in `pnr` (the
    real PDN signal). None → no DEF at all in the dir. A DEF with no
    SPECIALNETS section counts as 0 (PDN may still be strap/followpin-
    delivered — the caller then consults the PDN-strap TCL evidence)."""
    best: Optional[int] = None
    for defp in sorted(pnr.glob("*.def")):
        try:
            text = defp.read_text(errors="replace")
        except OSError:
            continue
        best = best if best is not None else 0
        m = _SPECIALNETS_HDR_RE.search(text)
        if m:
            best = max(best, int(m.group(1)))
    return best


def check_tier_2_pdn(project_dir: Path,
                       min_specialnets: int = 1) -> TierResult:
    """Tier 2 PDN — the real signal is the routed DEF's SPECIALNETS count, NOT
    the legacy `reports/pnr/pdn.json` (which no runner program writes). Read
    the DEF; a design that declares >= min SPECIALNETS PASSes. When the DEF
    carries NO SPECIALNETS section the PDN may be strap/followpin-delivered, so
    consult the PDN-strap TCL evidence (add_pdn_stripe / pdngen / add_pdn_ring)
    the flow's own `floorplan_pdn_check` uses — a design with strap commands
    PASSes (this is why subservient/caravel, whose routed DEF has 0
    SPECIALNETS, are not false-FAILed). §4.05: no DEF and no legacy pdn.json →
    honest NOT_RUN; a routed DEF with neither SPECIALNETS nor strap evidence is
    a REAL no-PDN FAIL (never fabricated)."""
    pnr = _discover_pnr_dir(project_dir)
    if pnr is not None:
        n = _def_specialnets_count(pnr)
        if n is not None:  # at least one DEF present
            if n >= min_specialnets:
                return TierResult(
                    "T2_PDN", "Power Distribution Network", "PASS",
                    details={"specialnets": n, "min_required": min_specialnets,
                             "source": "DEF SPECIALNETS"},
                    artifact_path=str(pnr))
            import floorplan_pdn_check as fpc
            tcl_found, tcl_name, tcl_tokens = fpc._pdn_tcl_evidence(pnr)
            if tcl_found:
                return TierResult(
                    "T2_PDN", "Power Distribution Network", "PASS",
                    details={"specialnets": n, "min_required": min_specialnets,
                             "source": "PDN-strap TCL",
                             "pdn_evidence": f"{tcl_name}: {tcl_tokens}"},
                    artifact_path=str(pnr),
                    notes="no DEF SPECIALNETS section, but PDN strap/ring "
                          "commands present — PDN delivered via straps/"
                          "followpins (matches floorplan_pdn_check)")
            return TierResult(
                "T2_PDN", "Power Distribution Network", "FAIL",
                details={"specialnets": n, "min_required": min_specialnets,
                         "source": "DEF SPECIALNETS"},
                artifact_path=str(pnr),
                notes="routed DEF carries no power/ground SPECIALNETS section "
                      "AND no add_pdn_stripe/pdngen/add_pdn_ring evidence — a "
                      "real missing-PDN defect (§4.05)")
    # Legacy fallback — a pre-written pdn.json specialnets count.
    art = project_dir / "reports" / "pnr" / "pdn.json"
    if art.is_file():
        data = json.loads(art.read_text(encoding="utf-8"))
        n = int(data.get("specialnets", 0))
        verdict = "PASS" if n >= min_specialnets else "FAIL"
        return TierResult("T2_PDN", "Power Distribution Network", verdict,
                            details={"specialnets": n,
                                     "min_required": min_specialnets,
                                     "source": "legacy pdn.json"},
                            artifact_path=str(art))
    return TierResult("T2_PDN", "Power Distribution Network", "NOT_RUN",
                        notes="no routed DEF and no reports/pnr/pdn.json — "
                              "§4.05: absent → SKIP")


_STATIC_IR_BUDGET_PCT = 5.0    # canonical static-IR sign-off budget (% of Vdd)
_DEFAULT_VDD_V = 1.8           # generic open-PDK nominal supply, only used
                               # when the report carries neither budget nor Vdd


def check_tier_2_ir(project_dir: Path,
                     budget_uv: Optional[float] = None) -> TierResult:
    """Tier 2 IR-drop — worst static IR must be below the sign-off budget.

    The runner writes `reports/phase3/ir_drop.json` (worst_ir_uv + its OWN
    budget_uv = 5%-of-Vdd) — NOT the legacy `reports/pnr/ir_drop.json`. Budget
    precedence: (1) an explicit caller budget_uv, else (2) the report's own
    budget_uv (the runner's %-of-Vdd sign-off budget), else (3) a defensible
    default = _STATIC_IR_BUDGET_PCT of the report's Vdd (fallback _DEFAULT_VDD_V).
    The OLD default of 35 µV was FAR too tight — real static IR is hundreds of
    µV (subservient 271, spm 136, sha256 228) all UNDER the true ~90 mV budget —
    so the dead-path + tight-default combination both never fired AND would have
    false-FAILed. §4.05: an absent report still NOT_RUNs; this can only correct
    a false-FAIL / masked-NOT_RUN into the real verdict, never fabricate a
    pass (a genuine over-budget IR still FAILs)."""
    art = _discover_signoff_report(
        project_dir,
        phase3_names=("ir_drop.json",),
        rglob_pats=("reports/**/ir_drop.json",),
        legacy_rels=("reports/pnr/ir_drop.json",))
    if art is None:
        return TierResult("T2_IR", "IR-drop", "NOT_RUN",
                            notes="no reports/phase3/ir_drop.json — "
                                  "§4.05: absent → SKIP")
    data = json.loads(art.read_text(encoding="utf-8"))
    worst = float(data.get("worst_ir_uv", data.get("worst_ir_drop_uv", 1e9)))
    if budget_uv is not None:
        budget = float(budget_uv)
        budget_src = "caller"
    elif data.get("budget_uv") is not None:
        budget = float(data["budget_uv"])
        budget_src = "report budget_uv"
    else:
        vdd = float(data.get("vdd_v") or data.get("supply_voltage_v")
                    or _DEFAULT_VDD_V)
        budget = (_STATIC_IR_BUDGET_PCT / 100.0) * vdd * 1e6
        budget_src = f"{_STATIC_IR_BUDGET_PCT}%-of-{vdd}V default"
    verdict = "PASS" if worst <= budget else "FAIL"
    return TierResult("T2_IR", "IR-drop", verdict,
                        details={"worst_ir_uv": worst,
                                 "budget_uv": budget,
                                 "budget_source": budget_src},
                        artifact_path=str(art))


# ---------------------------------------------------------------------------
# Tier 2 EM — REAL J-vs-Jmax (replaces the decap-cell-count proxy).
# ---------------------------------------------------------------------------
_REGISTRY_PATH = _PROGRAMS / "pdk_registry.json"


def _resolve_pdk_tech_lef() -> Optional[Path]:
    """Resolve the PDK tech-LEF (the `DCCURRENTDENSITY` Jmax source) from the
    environment — `$PDK_ROOT` (the parent holding the PDK variant dir) and
    `$PDK` (the variant name, e.g. sky130A). The tech-LEF is ALWAYS at
    `$PDK_ROOT/$PDK/...`, NEVER inside the project, so the EM tier's
    project-only rglob always missed it and the tier SKIPed
    'jmax_reference_absent' even though `em_current_density_check` gives a real
    PASS when handed the PDK tech-LEF.

    Uses `pdk_registry.json`'s per-PDK `tech_lef_glob` when the variant is
    known, else a generic `*.tlef` / `*tech*.lef` glob under the variant dir.
    §4.05: this is NOT a fabrication — the reference is genuinely resolvable,
    just outside the project; if `$PDK_ROOT` is unset/unresolvable, returns
    None so the EM tier keeps its honest SKIP."""
    pdk_root = os.environ.get("PDK_ROOT")
    if not pdk_root:
        return None
    root = Path(pdk_root)
    if not root.is_dir():
        return None
    pdk = os.environ.get("PDK") or os.environ.get("PDK_VARIANT")
    # 1) Registry-driven: $PDK_ROOT/<variant>/<tech_lef_glob>.
    try:
        reg = json.loads(_REGISTRY_PATH.read_text(errors="replace"))
        entries = reg.get("pdks", []) if isinstance(reg, dict) else []
    except (OSError, json.JSONDecodeError):
        entries = []
    for entry in entries:
        name = entry.get("name")
        glob = entry.get("tech_lef_glob")
        if not name or not glob:
            continue
        if pdk and name != pdk:
            continue
        base = root / name
        if base.is_dir():
            hits = sorted(h for h in base.glob(glob) if h.is_file())
            if hits:
                return hits[0]
    # 2) Generic glob under $PDK_ROOT/$PDK (variant known but not in registry).
    if pdk and (root / pdk).is_dir():
        for pat in ("**/*.tlef", "**/*tech*.lef"):
            hits = sorted(h for h in (root / pdk).glob(pat) if h.is_file())
            if hits:
                return hits[0]
    # 3) No variant given — a single tech-LEF anywhere under $PDK_ROOT.
    if not pdk:
        for pat in ("*/**/*.tlef", "*/**/*tech*.lef"):
            hits = sorted(h for h in root.glob(pat) if h.is_file())
            if hits:
                return hits[0]
    return None


def _discover_jmax_ref(project_dir: Path
                       ) -> Tuple[Optional[Path], Optional[Path]]:
    """Return (jmax_json, tech_lef) — the first per-layer Jmax reference found
    in the project, or (via the PDK env fallback) the PDK tech-LEF, or
    (None, None). A supplied jmax JSON wins over a tech LEF.
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
    # The PDK tech-LEF (Jmax source) lives at $PDK_ROOT/$PDK/..., NEVER in the
    # project — resolve it from the environment so the EM tier can judge J-vs-
    # Jmax instead of SKIPping 'jmax_reference_absent'. Honest SKIP is kept
    # when $PDK_ROOT is genuinely unresolvable.
    pdk_tlef = _resolve_pdk_tech_lef()
    if pdk_tlef is not None:
        return None, pdk_tlef
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
    """Tier 3 antenna — the runner writes `reports/phase3/antenna.json`
    (net_violations / pin_violations / clean / routing_incomplete / verdict),
    NOT the legacy `reports/antenna/{magic,klayout}.json`. Read the real
    report:

      * `routing_incomplete` is a FAIL — an "antenna clean" claim on an
        UNROUTED design is vacuous (this is the sha256-class masked FAIL the
        dead legacy path hid).
      * any net/pin violation > 0 (or verdict==FAIL) is a FAIL.
      * clean and routed is a PASS.

    §4.05: an absent report NOT_RUNs; a discovered report is parsed to its REAL
    verdict — surfacing the masked antenna FAIL is the whole point, and this
    can never fabricate a pass. Falls back to the legacy magic/klayout pair."""
    art = _discover_signoff_report(
        project_dir,
        phase3_names=("antenna.json",),
        rglob_pats=("reports/**/antenna.json",))
    if art is not None:
        data = json.loads(art.read_text(encoding="utf-8"))
        net = data.get("net_violations")
        pin = data.get("pin_violations")
        clean = data.get("clean")
        routing_incomplete = bool(data.get("routing_incomplete"))
        vfield = str(data.get("verdict", "")).upper()
        counts = [int(c) for c in (net, pin) if isinstance(c, (int, float))]
        if routing_incomplete:
            verdict, note = ("FAIL",
                             "routing incomplete — an 'antenna clean' verdict "
                             "on an unrouted design is vacuous (§4.05); real "
                             "FAIL")
        elif any(c > 0 for c in counts) or vfield == "FAIL":
            verdict, note = ("FAIL", "antenna violations present")
        elif vfield == "PASS" or clean is True or (counts and
                                                   all(c == 0 for c in counts)):
            verdict, note = ("PASS", "")
        else:
            verdict, note = ("WARN", "antenna report present but no "
                                     "violation count / clean flag")
        return TierResult(
            "T3_ANTENNA", "Antenna", verdict,
            details={"net_violations": net, "pin_violations": pin,
                     "clean": clean, "routing_incomplete": routing_incomplete,
                     "report_verdict": data.get("verdict")},
            artifact_path=str(art), notes=note)
    # Legacy fallback — Magic + KLayout both report 0.
    art_magic = project_dir / "reports" / "antenna" / "magic.json"
    art_klayout = project_dir / "reports" / "antenna" / "klayout.json"
    if not art_magic.exists() and not art_klayout.exists():
        return TierResult("T3_ANTENNA", "Antenna", "NOT_RUN",
                            notes="no antenna artifacts found — §4.05: "
                                  "absent → SKIP")
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
    """Tier 3 ESD/pad-ring — qualitative artifact present. Discover the real
    report (phase3 → rglob → legacy) instead of only the dead
    `reports/esd/esd_padring.json`. §4.05: genuinely absent → honest NOT_RUN
    (the open flow reports ESD as a MANUAL_REVIEW category in the PERC memo,
    so a dedicated automated ESD verdict is usually absent); a discovered
    report is parsed to its real clean/verdict."""
    art = _discover_signoff_report(
        project_dir,
        phase3_names=("esd_padring.json", "esd.json"),
        rglob_pats=("reports/**/esd_padring.json", "reports/**/esd*.json"),
        legacy_rels=("reports/esd/esd_padring.json",))
    if art is None:
        return TierResult("T3_ESD", "ESD/pad-ring", "NOT_RUN",
                            notes="no ESD/pad-ring report — §4.05: absent → "
                                  "SKIP")
    data = json.loads(art.read_text(encoding="utf-8"))
    vfield = str(data.get("verdict", "")).upper()
    verdict = ("PASS" if (data.get("clean") or vfield == "PASS")
               else "FAIL")
    return TierResult("T3_ESD", "ESD/pad-ring", verdict,
                        details=data, artifact_path=str(art))


def check_tier_4_lvs_device(project_dir: Path) -> TierResult:
    """Tier 4 LVS device class — Netgen 261=261 style match. Discover the real
    report (phase3 → rglob → legacy) instead of only the dead
    `reports/lvs/device_class.json`. §4.05: genuinely absent → honest NOT_RUN
    (the runner's LVS verdict lives in `lvs_verdict.json`/`lvs.rpt`, consumed
    by the net-level + tapeout LVS tiers, not a separate device_class.json);
    a discovered device-class report is parsed to its real match verdict."""
    art = _discover_signoff_report(
        project_dir,
        phase3_names=("device_class.json", "lvs_device_class.json"),
        rglob_pats=("reports/**/device_class.json",
                    "reports/**/lvs_device_class.json"),
        legacy_rels=("reports/lvs/device_class.json",))
    if art is None:
        return TierResult("T4_LVS_DEV", "LVS device class", "NOT_RUN",
                            notes="no LVS device-class report — §4.05: absent "
                                  "→ SKIP")
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
    """Tier 5 latch-up — tap cell density above PDK threshold. Discover the
    real report (phase3 → rglob → legacy) instead of only the dead
    `reports/pnr/tapcell_density.json`. §4.05: genuinely absent → honest
    NOT_RUN; a discovered tap-cell density report is parsed to its real
    density verdict, never a fabricated pass."""
    art = _discover_signoff_report(
        project_dir,
        phase3_names=("tapcell_density.json",),
        rglob_pats=("reports/**/tapcell_density.json",),
        legacy_rels=("reports/pnr/tapcell_density.json",))
    if art is None:
        return TierResult("T5_LATCHUP", "Latch-up tap cells", "NOT_RUN",
                            notes="no tap-cell density report — §4.05: absent "
                                  "→ SKIP")
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
    # Surface an inert waiver (allow-macro that matched no residual bucket, e.g.
    # a macro nested below the XOR --top) so it is visible in the ladder report.
    if res.get("inert_allow_macros"):
        inert = ", ".join(res["inert_allow_macros"])
        notes = (notes + " | " if notes else "") + \
            f"inert allow-macro(s) matched no residual (check --top): {inert}"
    return TierResult(
        "T_XOR", "Layout XOR (GDS vs golden)", ladder,
        details={"total_residual_count": res.get("total_residual_count"),
                 "waived_residual": res.get("waived_residual"),
                 "failing_residual": res.get("failing_residual"),
                 "inert_allow_macros": res.get("inert_allow_macros"),
                 "advisories": res.get("advisories")},
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


def _resolve_metal_density_pdk(report: Optional[Path],
                               pdk: Optional[str]) -> Optional[str]:
    """Which PDK's density rules should judge this measurement.

    Order: the caller's explicit answer, then the REPORT'S OWN declaration, then
    the environment. The report is preferred over the environment because it
    records the PDK the measurement was actually taken under, whereas the
    environment records whatever this shell happens to be pointed at — reading a
    stored report from a differently-configured shell must not silently rejudge
    it against another foundry's numbers.

    None is a real answer and the honest one for a report that predates the
    declaration and is read outside its run: no foundry window is supplied and
    the DISCLOSED generic default stands, exactly as before."""
    if pdk:
        return pdk
    if report is not None and report.is_file():
        try:
            doc = json.loads(report.read_text(errors="replace"))
        except (OSError, ValueError):
            doc = None
        if isinstance(doc, dict):
            declared = doc.get("pdk")
            if isinstance(declared, str) and declared.strip():
                return declared.strip()
    for var in ("PDK_VARIANT", "PDK"):
        v = os.environ.get(var)
        if v and v.strip():
            return v.strip()
    return None


def check_tier_metal_density(project_dir: Path,
                             default_min: float = _METAL_DENSITY_MIN,
                             default_max: float = _METAL_DENSITY_MAX,
                             pdk: Optional[str] = None
                             ) -> TierResult:
    """Per-layer metal density (foundry CMP / min-clear-area pattern density).

    Delegates to `metal_layer_density_check.check`, supplying THAT PDK'S OWN
    stated per-layer windows. Before this was wired the call passed `{}` and so
    every run on every process was judged by the gate's generic default, which
    is wider on both sides than at least one open PDK's own sign-off script —
    a design its foundry would reject could clear our gate. Precedence per
    layer: a window the report itself ships > the PDK's stated window > the
    DISCLOSED generic default, resolved BOUND BY BOUND so a foundry minimum
    beside a generic ceiling is reported as exactly that.
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
    resolved = _resolve_metal_density_pdk(rpt, pdk)
    windows: Dict[str, "mld.Window"] = {}
    provenance: Optional[Dict[str, object]] = None
    if resolved:
        windows, provenance = mld.pdk_windows_for(resolved)
    res = mld.check(rpt, windows, default_min, default_max, provenance)
    v = res.get("verdict")
    ladder = {"PASS": "PASS", "FAIL": "FAIL",
              "IO_ERROR": "NOT_RUN"}.get(v, "FAIL")
    notes = ""
    if ladder == "FAIL":
        notes = "; ".join(res.get("failures", [])) or res.get("detail", "")
        if not notes and res.get("unchecked_layers"):
            notes = f"unchecked layers (no window): {res['unchecked_layers']}"
    # Say WHOSE numbers produced this verdict, on a PASS as much as on a FAIL —
    # "density within window" means something different when the window is the
    # foundry's than when it is our generic stand-in, and a reader who cannot
    # tell them apart cannot weigh the tier.
    attribution = _metal_density_attribution(resolved, provenance)
    notes = f"{notes}; {attribution}" if notes else attribution
    return TierResult(
        "T_METAL_DENSITY", "Per-layer metal density (CMP)", ladder,
        details=res, artifact_path=str(rpt), notes=notes)


def _metal_density_attribution(resolved: Optional[str],
                               provenance: Optional[Dict[str, object]]) -> str:
    """One line naming which windows judged the run — never left implicit."""
    if not resolved:
        return ("windows: DISCLOSED generic default (the run declares no PDK "
                "and none was given, so no foundry window could be looked up)")
    status = (provenance or {}).get("status")
    if status == "stated":
        unstated = (provenance or {}).get("bounds_unstated") or []
        tail = (f"; that PDK states no bound for {', '.join(unstated)}, where "
                f"the generic default stands") if unstated else ""
        return f"windows: {resolved}'s own stated per-layer rules{tail}"
    if status == "states-none":
        return (f"windows: DISCLOSED generic default — {resolved} was read and "
                f"states no per-layer density rule")
    return (f"windows: DISCLOSED generic default — no stated density rules on "
            f"record for {resolved}")


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
# Reviewed tier waivers — "this tier cannot run here, it was reviewed, why"
# ---------------------------------------------------------------------------
# #520 made ABSENT evidence non-releasing, which is right: a check nobody ran is
# not a pass. It also made an existing gap load-bearing. Before this module, the
# ladder had exactly two sources of `WAIVED` — the XOR allow-list and a
# report-declared triage LVS waiver — and both are decided INSIDE a tier. There
# was no way for a reviewer to say "this tier cannot run in this environment,
# here is the review". `T_AGING_STA` is the plain case: its own note reads "the
# open PDK ships no foundry aging Liberty", a real environmental capability gap,
# and so that tier was permanently non-releasing for every project.
#
# THE PRECEDENT THIS FOLLOWS. `flow_compliance_check` already has this exact
# shape for the FPGA board steps and the analog PDK substitution: a DISCLOSED,
# reviewed ENV_UNAVAILABLE attestation converts a natural MISSING into
# WAIVED-DEFERRED, while an UNDISCLOSED missing artefact still hard-FAILs.
# Disclosure buys deferral; silence buys failure. The asymmetry is the whole
# design and it is reproduced here.
#
# ONE READER, NOT AN EIGHTH. The entries are read through `_waiver_entries`
# (#519), which owns "where a project's waiver entries live" — the union of the
# `waived_steps` and `waivers` keys, in one documented order. This module adds
# no second notion of that. What it does add is its own MATCHING and
# ELIGIBILITY rules, which `_waiver_entries` explicitly leaves to each consumer:
# reading a list and granting a permission are different jobs.
#
# WHY A LADDER WAIVER MUST NAME A LADDER TIER. A waiver in this file names a
# FLOW STEP ("drc", id 31, id 39). Those were reviewed against a different
# question — "did this flow step run" — and the corpus shows the difference is
# not academic: tracked entries include a `step: "drc"` waiver whose rationale
# is about accepting thousands of stdcell-library-internal DRC violations. That
# is a reviewed judgement about a RESULT, not a statement that a sign-off tier
# could not run, and silently spending it on a tapeout release tier would be a
# reviewer's decision applied to a question they were never asked. So a ladder
# waiver is addressed to the ladder, by TIER ID, and a flow-step waiver that
# does not name a tier is left alone for its own consumers — neither honoured
# nor reported here, because complaining about it would be a category error.
#
# WHAT IT CANNOT BECOME. `TierResult.release_gating` is set in code and never
# read from a design artefact, precisely so no project can opt its own gates
# out. This path must not become that back door, so:
#   * every review marker the waiver schema defines is REQUIRED — `ticket`,
#     `review_required: true`, a non-empty `evidence` list, and a substantive
#     `rationale` — the same quartet `flow_compliance_check` requires, and a
#     missing one refuses the waiver out loud;
#   * `verdict_tier` must be ENV_UNAVAILABLE. For a tier that produced NO
#     evidence, the only reviewable ground for releasing is that the evidence
#     COULD NOT be produced here. A result waiver relabelled at a tier with no
#     result is not that;
#   * ONLY a NOT_RUN tier can be waived. A tier that RAN keeps its own verdict
#     and the waiver is refused and named. This is also the staleness guard
#     `flow_compliance_check._refuse_stale_waivers` applies to the same shape:
#     positive execution evidence refuses a waiver, so a file that outlives the
#     condition it was written under can never excuse a real FAIL;
#   * an ADVISORY tier (`release_gating=False`) is refused too — its absence
#     never withheld a release, so waiving it buys nothing and would only
#     demote an otherwise-clean PASS to PASS_WITH_WAIVERS;
#   * nothing in the entry can set `release_gating`. The field is never read
#     from the document.
#
# EVIDENCE IS CLASSIFIED, NEVER DEMANDED. #524 established that an
# ENV_UNAVAILABLE attestation is UNCORROBORATED BY CONSTRUCTION: its claim is
# that a tool was absent, and no independent artefact can corroborate a
# non-execution. `_evidence_independence` classifies what the list actually
# holds and the result is DISCLOSED; requiring corroboration here would make an
# honest, correctly disclosed capability gap impossible to honour, i.e. would
# break "disclosure buys deferral" for the exact population the tier serves.
#
# chip-AGNOSTIC: every test is structural — key presence, a token compared to a
# ladder tier id, a string length, a verdict. No vendor, no SKU, no design name.
# ---------------------------------------------------------------------------

#: Every tier id the ladder can emit, across BOTH modes and with the shuttle
#: tiers on. Needed so a waiver naming a real tier that THIS mode does not run
#: ("T_AGING_STA" on a triage run) is told that, rather than being reported as
#: an unknown tier — two different mistakes with two different fixes.
#: `test_ladder_tier_ids_cover_every_tier_the_ladder_emits` re-derives this by
#: RUNNING both modes, so a new tier cannot drift away from the list.
LADDER_TIER_IDS: Tuple[str, ...] = (
    "T1", "T1.5", "T2_PDN", "T2_IR", "T2_EM", "T3_ANTENNA", "T3_ESD",
    "T4_LVS_DEV", "T4.5_LVS_NET", "T4.5_LVS_TAPEOUT", "T5_LATCHUP",
    "T_STA_RIGOR", "T_MBIST", "T_DYN_IR", "T_METAL_DENSITY", "T_AGING_STA",
    "T_THERMAL", "T_DFT_SIGNOFF", "T_LEC_POST", "T_MPW_PRECHECK", "T_XOR",
)

#: The ONLY `verdict_tier` a ladder-tier waiver may carry. A tier with no
#: evidence can be deferred because the evidence could not be produced here;
#: it cannot be "waived" on a judgement about a result that does not exist.
TIER_WAIVER_VERDICT_TIER = "ENV_UNAVAILABLE"

#: Minimum `rationale` length, matching `flow_compliance_check`'s ENV_UNAVAILABLE
#: bar. Short enough that a real sentence clears it, long enough that a token
#: ("n/a", "later") does not.
TIER_WAIVER_MIN_RATIONALE_CHARS = 40

#: Entry keys that may carry the tier a waiver is addressed to, in precedence
#: order. `tier` is the ladder-scoped spelling and is ALWAYS treated as
#: addressed to the ladder (so a typo is reported, not silently dropped);
#: `step`/`id` are the two existing dialects' identity keys and are treated as
#: addressed to the ladder only when they literally name a ladder tier.
TIER_WAIVER_ID_KEYS: Tuple[str, ...] = ("tier", "step", "id")


def _tier_token(value: Any) -> str:
    """A tier identifier normalised for comparison. Empty for anything that is
    not a scalar identifier (a dict, a list, None)."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ""
    return str(value).strip().upper()


def _addressed_tier(entry: Dict[str, Any]) -> Tuple[Optional[str], bool]:
    """`(token, explicit)` for the tier an entry is addressed to.

    `explicit` is True when the entry used the ladder-scoped `tier` key, which
    means the entry is talking to THIS ladder even if the token is wrong — so a
    misspelt tier is reported rather than silently ignored. `(None, False)`
    means the entry is not addressed to the ladder at all (a flow-step waiver),
    which is a different consumer's business and is left alone."""
    if "tier" in entry:
        return _tier_token(entry.get("tier")), True
    for key in TIER_WAIVER_ID_KEYS[1:]:
        if key in entry:
            token = _tier_token(entry.get(key))
            if token:
                return token, False
    return None, False


def _tier_waiver_rationale(entry: Dict[str, Any]) -> str:
    """The entry's rationale text. `rationale` and `reason` are used
    interchangeably by waiver authors and every consumer that read only one of
    them displayed a valid entry as "(no reason)" — normalise once, here."""
    for key in ("rationale", "reason"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def tier_waiver_review_defects(entry: Dict[str, Any]) -> List[str]:
    """Everything this entry is missing before it may defer a ladder tier.

    Empty list = reviewable. Each item is phrased as the thing that is ABSENT,
    so the disclosure reads as an instruction rather than a verdict."""
    missing: List[str] = []
    declared = str(entry.get("verdict_tier") or "").strip().upper()
    if declared != TIER_WAIVER_VERDICT_TIER:
        missing.append(
            f"`verdict_tier: \"{TIER_WAIVER_VERDICT_TIER}\"` (found "
            f"{entry.get('verdict_tier')!r}) — the only reviewable ground for "
            f"releasing on a tier that produced NO evidence is that the "
            f"evidence could not be produced in this environment")
    ticket = entry.get("ticket")
    if not (isinstance(ticket, str) and ticket.strip()):
        missing.append("a non-empty `ticket`")
    if entry.get("review_required") is not True:
        missing.append("`review_required: true`")
    evidence = entry.get("evidence")
    if not (isinstance(evidence, list) and evidence):
        missing.append("a non-empty `evidence` list")
    if len(_tier_waiver_rationale(entry)) < TIER_WAIVER_MIN_RATIONALE_CHARS:
        missing.append(
            f"a `rationale` (or `reason`) of at least "
            f"{TIER_WAIVER_MIN_RATIONALE_CHARS} characters naming the missing "
            f"capability, why it cannot be produced here, and what would close "
            f"the deferral")
    return missing


def load_tier_waiver_entries(project_dir: Path) -> List[Dict[str, Any]]:
    """Every dict-shaped waiver entry for the project, via the ONE shared
    reader. No second notion of where waivers live is created here."""
    return _we.dict_entries(_we.read_document(Path(project_dir)))


def apply_tier_waivers(project_dir: Path,
                       tiers: List[TierResult],
                       mode: Optional[str] = None) -> List[str]:
    """Honour the project's REVIEWED ladder-tier waivers, mutating `tiers`.

    A honoured waiver turns a release-gating tier's `NOT_RUN` into `WAIVED` —
    the ladder's existing word for a decision somebody made and owns — and
    records the whole attestation (ticket, rationale, evidence and what that
    evidence was made of) in the tier's `details["waiver"]`, with
    `deferred_from: "NOT_RUN"` so the report never loses the fact that no
    evidence exists. It is a DEFERRAL, not an executed pass, and the tier note
    says so.

    Returns the disclosure lines: every waiver that was refused and why, plus a
    named advisory for every honoured waiver that nothing independent
    corroborates (#524). Silence is never an outcome — a refusal is always
    reported, and the refused tier keeps its own verdict."""
    project_dir = Path(project_dir)
    entries = load_tier_waiver_entries(project_dir)
    if not entries:
        return []
    by_id: Dict[str, TierResult] = {t.tier_id.upper(): t for t in tiers}
    # Snapshot BEFORE any mutation: every eligibility test asks what the tier
    # reported ON ITS OWN, so an earlier honoured waiver can never make a later
    # entry look eligible. Today this is REDUNDANT with the `honoured` guard
    # below — the only in-loop write to a tier verdict is a honoured waiver,
    # and `honoured` short-circuits a second entry for that tier before the
    # verdict is consulted — so no reachable state distinguishes the snapshot
    # from a live read, and mutating it to a live read is not observable. It is
    # kept because the invariant it states ("eligibility is judged against what
    # the ladder measured") must survive a future reordering, and stating it
    # here costs one line.
    original = {key: t.verdict for key, t in by_id.items()}
    honoured: set = set()
    disclosures: List[str] = []

    for index, entry in enumerate(entries):
        token, explicit = _addressed_tier(entry)
        if token is None or (not explicit and token not in by_id):
            # Not addressed to this ladder. A flow-step waiver answers a
            # different question and is left to its own consumers.
            continue
        label = f"waiver entry #{index}"
        if token not in by_id:
            if token in {t.upper() for t in LADDER_TIER_IDS}:
                where = f" (mode={mode})" if mode else ""
                disclosures.append(
                    f"{label} names {token}, a ladder tier that THIS run{where} "
                    f"does not include — NOT applied here. The waiver is not "
                    f"malformed; it only applies to a run that reaches that "
                    f"tier.")
            else:
                disclosures.append(
                    f"{label} names tier {token!r}, which is not a tier this "
                    f"ladder runs — NOT applied. Tiers in this run: "
                    + ", ".join(sorted(by_id)) + ".")
            continue
        tier = by_id[token]
        if token in honoured:
            disclosures.append(
                f"{label} also names {tier.tier_id}, which an earlier entry "
                f"already deferred — NOT applied a second time.")
            continue
        if original[token] != "NOT_RUN":
            disclosures.append(
                f"{label} names {tier.tier_id}, but that tier RAN and reported "
                f"{original[token]}. A waiver defers a check that could not "
                f"run; it never overwrites a check that did — NOT applied, and "
                f"{tier.tier_id} keeps its own verdict.")
            continue
        if not tier.release_gating:
            disclosures.append(
                f"{label} names {tier.tier_id}, an ADVISORY tier whose absence "
                f"never withheld the release — NOT applied, because there is "
                f"nothing to defer.")
            continue
        defects = tier_waiver_review_defects(entry)
        if defects:
            disclosures.append(
                f"{label} for {tier.tier_id} was NOT applied — it is missing "
                + "; ".join(defects)
                + f". {tier.tier_id} stays {original[token]} until the waiver "
                  f"is completed and reviewed.")
            continue

        ticket = str(entry.get("ticket")).strip()
        rationale = _tier_waiver_rationale(entry)
        evidence = list(entry.get("evidence") or [])
        assessment = _ev_ind.assess(evidence, project_dir)
        tier.verdict = "WAIVED"
        tier.details = dict(tier.details or {})
        tier.details["waiver"] = {
            "source": _we.WAIVERS_FILENAME,
            "entry_index": index,
            "verdict_tier": TIER_WAIVER_VERDICT_TIER,
            "ticket": ticket,
            "review_required": True,
            "approver": entry.get("approver"),
            "rationale": rationale,
            "evidence": evidence,
            "evidence_assessment": assessment.as_dict(),
            # The tier produced nothing. Recording what was deferred keeps a
            # honoured waiver from reading like a check that ran and passed.
            "deferred_from": "NOT_RUN",
        }
        tier.notes = (
            f"WAIVED-DEFERRED on a reviewed {TIER_WAIVER_VERDICT_TIER} waiver "
            f"[ticket={ticket}, review_required=True, "
            f"evidence={assessment.describe()}"
            + ("" if assessment.corroborated
               else ", NO independent corroboration")
            + f"] — this tier produced NO evidence and is DEFERRED, not "
              f"executed-PASS: {rationale[:200]}")
        honoured.add(token)
        if not assessment.corroborated:
            disclosures.append(
                "HONOURED but UNCORROBORATED — "
                + _ev_ind.disclosure(tier.tier_id, assessment)
                + f" {tier.tier_id} remains WAIVED-DEFERRED on ticket "
                  f"{ticket}; review_required stays true.")
    return disclosures


def waived_tiers(tiers: List[TierResult]) -> List[TierResult]:
    """Every tier the ladder is carrying on a waiver rather than on a check
    that passed — in ladder order. A release that rests on these must name
    them, the way it already names every tier that withheld one."""
    return [t for t in tiers if t.verdict == "WAIVED"]


def _waiver_basis(tier: TierResult) -> str:
    """Where a WAIVED tier's waiver came from — a reviewed entry in the
    project's waiver document, or a decision the tier made internally (the XOR
    allow-list, a report-declared triage LVS waiver)."""
    waiver = (tier.details or {}).get("waiver")
    if isinstance(waiver, dict):
        return (f"reviewed {waiver.get('verdict_tier')} waiver in "
                f"{waiver.get('source')}")
    return "tier-internal waiver (allow-list / report-declared)"


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
    #: Every waiver this run refused and why, plus a named advisory for each
    #: honoured waiver nothing independent corroborates. Never silent.
    waiver_disclosures: List[str] = field(default_factory=list)

    @property
    def released(self) -> bool:
        """Mode-aware release flag — triage never releases (see `is_released`)."""
        return is_released(self.overall_verdict, self.mode)

    def release_note(self) -> str:
        """One line a human can act on: why the ladder is / is not releasing,
        and — symmetrically with the tiers that withheld it — which tiers it is
        resting on a waiver for rather than on a check that passed."""
        if self.released:
            note = "the tapeout release ladder is satisfied"
        elif self.mode != "tapeout":
            note = (f"mode '{self.mode}' is the diagnostic ladder and never "
                    f"releases — re-run with --mode tapeout to gate a release")
        elif self.overall_verdict == NOT_RELEASED_ALL_WAIVED:
            note = ("every release-gating tier was DEFERRED and not one was "
                    "executed — a ladder carried entirely by waivers has run "
                    "no sign-off, so it does not release")
        else:
            blockers = release_blockers(self.tiers)
            note = (f"{len(blockers)} tier(s) withhold the release: "
                    + ", ".join(f"{t.tier_id}={t.verdict}" for t in blockers)
                    ) if blockers else (
                f"overall verdict {self.overall_verdict} does not release")
        waived = waived_tiers(self.tiers)
        if waived:
            note += (f"; {len(waived)} tier(s) carried by a waiver, not by a "
                     f"check that ran: "
                     + ", ".join(t.tier_id for t in waived))
        return note

    def as_dict(self) -> Dict[str, Any]:
        return {
            "project_dir": self.project_dir,
            "mode": self.mode,
            "caravel": self.caravel,
            "tiers": [t.as_dict() for t in self.tiers],
            "overall_verdict": self.overall_verdict,
            "released": self.released,
            "release_note": self.release_note(),
            "release_blockers": [
                {"tier_id": t.tier_id, "name": t.name, "verdict": t.verdict}
                for t in release_blockers(self.tiers)],
            "evidence_absent_tiers": [
                t.tier_id for t in evidence_absent_tiers(self.tiers)],
            # A release that rests on waivers names them, exactly as it already
            # names every tier that withheld one. Each row says WHAT bought the
            # waiver, so a reviewed capability-gap deferral and a tier-internal
            # allow-list waiver are never read as the same thing.
            "waived_tiers": [
                {"tier_id": t.tier_id, "name": t.name,
                 "basis": _waiver_basis(t),
                 "ticket": ((t.details or {}).get("waiver") or {}).get(
                     "ticket"),
                 "deferred_from": ((t.details or {}).get("waiver") or {}).get(
                     "deferred_from")}
                for t in waived_tiers(self.tiers)],
            "waiver_disclosures": list(self.waiver_disclosures),
            "emitted_by": _pmd.emitted_by("signoff_ladder_run",
                                         "release-gate-wired"),
        }


def evidence_absent_tiers(tiers: List[TierResult]) -> List[TierResult]:
    """The release-GATING tiers that produced no evidence at all (NOT_RUN).

    Advisory tiers (`release_gating=False`) are excluded — their absence is a
    missing convenience, not missing sign-off evidence."""
    return [t for t in tiers
            if t.verdict == "NOT_RUN" and getattr(t, "release_gating", True)]


def executed_signoff_tiers(tiers: List[TierResult]) -> List[TierResult]:
    """The release-gating tiers that actually RAN and PASSED — the evidence a
    release rests on, as opposed to the deferrals it carries. A ladder with
    none of these has performed no sign-off, whatever its paperwork says."""
    return [t for t in tiers
            if t.verdict == "PASS" and getattr(t, "release_gating", True)]


def release_blockers(tiers: List[TierResult]) -> List[TierResult]:
    """Every tier that withholds the release, in ladder order — the actionable
    form of a non-releasing overall verdict."""
    absent = {id(t) for t in evidence_absent_tiers(tiers)}
    return [t for t in tiers
            if t.verdict in BLOCKING_TIER_VERDICTS or id(t) in absent]


def aggregate_verdict(tiers: List[TierResult]) -> str:
    """Aggregate per-tier verdicts to overall.

      any FAIL                           → FAIL
      else any WAIVED_PENDING/INCOMPLETE → NOT_RELEASED   (a documented waiver
          pending real closure, or incomplete evidence: NON-releasing, never a
          silent pass — this is the §4.05 tapeout-tier tightening)
      else any GATING tier NOT_RUN       → NOT_RELEASED_EVIDENCE_ABSENT
          (nothing was checked. §4.05 again, and harder: incomplete evidence
          already refuses to release, so evidence that was never produced
          cannot release either. This is the branch that used to hand an
          all-NOT_RUN design a PASS_WITH_WAIVERS.)
      else any WARN                      → WARN
      else any WAIVED and NO gating PASS → NOT_RELEASED_ALL_WAIVED  (every gate
          deferred, none executed: paperwork over an empty ladder is the claim
          #520 refused, re-entered through the front door)
      else any WAIVED                    → PASS_WITH_WAIVERS  (a REVIEWED,
          documented waiver is a decision somebody made and owns; it stays
          releasing, and it is no longer reachable by a tier nobody ran)
      else (all PASS, N/A ignored)       → PASS

    N/A tiers (e.g. a RAM-less MBIST tier) are neutral — they never demote the
    verdict and never inflate a PASS. Advisory tiers (`release_gating=False`)
    are neutral for ABSENCE only: a FAIL/WARN on one still blocks.
    """
    verdicts = [t.verdict for t in tiers]
    if "FAIL" in verdicts:
        return "FAIL"
    if "WAIVED_PENDING" in verdicts or "INCOMPLETE" in verdicts:
        return "NOT_RELEASED"
    if evidence_absent_tiers(tiers):
        return NOT_RELEASED_EVIDENCE_ABSENT
    if "WARN" in verdicts:
        return "WARN"
    if "WAIVED" in verdicts:
        if not executed_signoff_tiers(tiers):
            return NOT_RELEASED_ALL_WAIVED
        return "PASS_WITH_WAIVERS"
    return "PASS"


def is_released(overall_verdict: str, mode: str) -> bool:
    """Whether the ladder RELEASES — the mode-aware form of the flag.

    `triage` is the diagnostic ladder; its own docstring says "Nothing here
    claims a tapeout". So triage NEVER releases, however clean it reads: the
    diagnostic ladder does not run the release-tier gates (LVS genuine-match,
    STA rigor, MBIST, dynamic-IR, metal density, aging STA, thermal, DFT,
    post-layout LEC, and — for a shuttle project — precheck + XOR) at all, so a
    releasing triage verdict was never a statement about those checks. Only
    `tapeout`, which runs them, can set the flag."""
    return mode == "tapeout" and overall_verdict in RELEASING_VERDICTS


def run_ladder(project_dir: Path,
               mode: str = "triage",
               caravel: Optional[bool] = None,
               jmax: Optional[Path] = None,
               tech_lef: Optional[Path] = None,
               sources: Optional[List[Tuple[str, str]]] = None,
               xor_allow_macros: Optional[List[str]] = None,
               pdk: Optional[str] = None) -> LadderReport:
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
        tiers.append(check_tier_metal_density(project_dir, pdk=pdk))
        tiers.append(check_tier_aging_sta(project_dir))
        tiers.append(check_tier_thermal(project_dir))
        tiers.append(check_tier_dft_signoff(project_dir))
        tiers.append(check_tier_lec_post(project_dir))
        if caravel:
            tiers.append(check_tier_mpw_precheck(project_dir))
            tiers.append(check_tier_xor(project_dir,
                                        allow_macros=xor_allow_macros))

    # Reviewed tier waivers, LAST — after every tier has reported on its own
    # merits, so a waiver is only ever weighed against what the tier actually
    # produced. The aggregate is computed from the post-waiver tiers, which is
    # the point: a reviewed capability-gap deferral releases, an unrun tier
    # does not.
    disclosures = apply_tier_waivers(project_dir, tiers, mode=mode)

    return LadderReport(
        project_dir=str(project_dir),
        tiers=tiers,
        overall_verdict=aggregate_verdict(tiers),
        mode=mode,
        caravel=bool(caravel),
        waiver_disclosures=disclosures,
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
               f"(released={rep.released}) — {rep.release_note()}")
    out.append("")
    out.append("| Tier | Check | Verdict | Notes |")
    out.append("|---|---|---|---|")
    for t in rep.tiers:
        notes = t.notes or json.dumps(t.details)[:80]
        out.append(f"| {t.tier_id} | {t.name} | {t.verdict} | {notes} |")
    out.append("")
    absent = evidence_absent_tiers(rep.tiers)
    if absent:
        out.append(f"**{len(absent)} release-gating tier(s) produced no "
                   f"evidence** — §4.05: a check nobody ran is not a pass, so "
                   f"the ladder does not release on it: "
                   + ", ".join(t.tier_id for t in absent) + ".")
        out.append("")
    waived = waived_tiers(rep.tiers)
    if waived:
        out.append(f"**{len(waived)} tier(s) are carried by a WAIVER, not by a "
                   f"check that passed** — a waiver is a decision somebody made "
                   f"and owns, and it stays open work:")
        for t in waived:
            ticket = ((t.details or {}).get("waiver") or {}).get("ticket")
            tail = f", ticket {ticket}" if ticket else ""
            out.append(f"- `{t.tier_id}` — {_waiver_basis(t)}{tail}.")
        out.append("")
    if rep.waiver_disclosures:
        out.append("**Waiver disclosures** — every waiver this run refused, "
                   "and every honoured waiver nothing independent corroborates:")
        for line in rep.waiver_disclosures:
            out.append(f"- {line}")
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
    p.add_argument("--pdk", default=None,
                   help="PDK name — judge per-layer metal density against THAT "
                        "PDK's own stated windows. Default: the density "
                        "report's own declaration, else $PDK_VARIANT / $PDK, "
                        "else the DISCLOSED generic window.")
    p.add_argument("--out-md", type=Path)
    p.add_argument("--out-json", type=Path)
    p.add_argument("--strict", action="store_true",
                   help="Exit non-zero unless the ladder RELEASES — i.e. "
                        "--mode tapeout AND a releasing overall verdict "
                        "(PASS / PASS_WITH_WAIVERS). --mode triage is the "
                        "diagnostic ladder and never releases, so --strict "
                        "there always exits non-zero by design.")
    args = p.parse_args()
    rep = run_ladder(args.project_dir, mode=args.mode, caravel=args.caravel,
                     jmax=args.jmax, tech_lef=args.tech_lef,
                     xor_allow_macros=args.xor_allow_macros, pdk=args.pdk)
    md = report_to_markdown(rep)
    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    else:
        print(md)
    if args.out_json:
        args.out_json.write_text(json.dumps(rep.as_dict(), indent=2),
                                  encoding="utf-8")
    # `--strict` is the actionable form of the `released` flag, so it obeys the
    # SAME mode guard — a run that prints released=False must not exit 0 under
    # --strict, or the contradiction just moves down one level.
    if args.strict and not rep.released:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
