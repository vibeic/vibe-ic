"""tests/test_pnr_via_stack_completeness_check.py — v1.6.54

PnR via-stack completeness audit: PDK declared layers vs PnR-used
layers. WARN (not FAIL) when PDK ships more layers than PnR could
use due to single-cut via gaps."""
from __future__ import annotations

import json
from pathlib import Path

from programs.pnr_via_stack_completeness_check import audit


def _write_orchestrator(project: Path, pnr_detail: str) -> None:
    rep = project / "reports" / "orchestrator" / "phase3_one_shot.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps({
        "verdict": "PASS_WITH_WAIVERS",
        "steps": [
            {"name": "synth", "status": "PASS"},
            {"name": "pnr", "status": "PASS", "detail": pnr_detail},
            {"name": "gds", "status": "PASS"},
        ],
    }))


def _write_tech_lef(project: Path, n_routing: int = 6,
                    metal_prefix: str = "M") -> None:
    """Synthesise a minimal tech.lef with N TYPE ROUTING layer
    declarations matching `<prefix><N>` for each."""
    lef_dir = project / "input" / "pdk" / "lef"
    lef_dir.mkdir(parents=True, exist_ok=True)
    body = ["VERSION 5.8 ;\n"]
    for i in range(1, n_routing + 1):
        body.append(
            f"LAYER {metal_prefix}{i}\n"
            f"  TYPE ROUTING ;\n"
            f"END {metal_prefix}{i}\n\n")
    (lef_dir / "tech.lef").write_text("".join(body))


# ---------------------------------------------------------------------------
# VACUOUS_PASS — Phase 3 has not run.
# ---------------------------------------------------------------------------

def test_vacuous_pass_when_no_orchestrator_report(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    verdict, findings, summary = audit(p)
    assert verdict == "VACUOUS_PASS"
    assert findings == []


# ---------------------------------------------------------------------------
# SKIP — orchestrator present but no tech.lef.
# ---------------------------------------------------------------------------

def test_skip_when_no_tech_lef(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _write_orchestrator(p, "def=top.def sta=sta.rpt")
    verdict, findings, _ = audit(p)
    assert verdict == "SKIP"
    assert any(f.rule == "NO_TECH_LEF" for f in findings)


def test_skip_when_pdk_has_fewer_than_2_routing_layers(tmp_path: Path):
    p = tmp_path / "proj"
    _write_orchestrator(p, "def=top.def")
    _write_tech_lef(p, n_routing=1)
    verdict, _, summary = audit(p)
    assert verdict == "SKIP"
    assert summary["pdk_metal_layers_total"] == 1


# ---------------------------------------------------------------------------
# PASS — PnR used every routing layer the PDK declared.
# ---------------------------------------------------------------------------

def test_pass_when_pnr_uses_all_pdk_layers(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _write_orchestrator(p, "def=top.def sta=sta.rpt")
    _write_tech_lef(p, n_routing=6)
    # Without a "routing restricted" note, the audit assumes PnR
    # used all declared layers.
    verdict, findings, summary = audit(p)
    assert verdict == "PASS"
    assert findings == []
    assert summary["pdk_metal_layers_total"] == 6
    assert summary["pnr_routing_layers_used"] == 6


# ---------------------------------------------------------------------------
# WARN — PDK declares more layers than PnR used.
# ---------------------------------------------------------------------------

def test_warn_when_routing_restricted_below_pdk_total(
        tmp_path: Path) -> None:
    """v10648 case: PDK ships M1-M6, PnR routed M1-M5 due to single-
    cut via missing on cut layers above M5."""
    p = tmp_path / "proj"
    detail = ("def=chip_top_asic.def sta=sta.rpt | via_audit: "
              "single-cut via missing above M5; routing restricted to M1-M5")
    _write_orchestrator(p, detail)
    _write_tech_lef(p, n_routing=6)
    verdict, findings, summary = audit(p)
    assert verdict == "WARN"
    assert len(findings) == 1
    assert findings[0].rule == "PDK_LAYERS_UNUSED"
    assert summary["pdk_metal_layers_total"] == 6
    assert summary["pnr_routing_layers_used"] == 5
    # Reviewer guidance must point at PDK update + design-density check.
    assert "PDK update" in findings[0].detail
    assert "density" in findings[0].detail


def test_warn_with_sky130_style_via_message(tmp_path: Path) -> None:
    """Alternative phrasing — `single-cut via missing above M3`
    without a 'routing restricted to' clause."""
    p = tmp_path / "proj"
    detail = ("via_audit: single-cut via missing above M3 — workaround "
              "applied")
    _write_orchestrator(p, detail)
    _write_tech_lef(p, n_routing=5)
    verdict, _, summary = audit(p)
    assert verdict == "WARN"
    assert summary["pnr_routing_layers_used"] == 3


def test_warn_with_met_prefix(tmp_path: Path) -> None:
    """Sky130 uses `met` prefix, not `M`."""
    p = tmp_path / "proj"
    detail = ("via_audit: single-cut via missing above met4; "
              "routing restricted to met1-met4")
    _write_orchestrator(p, detail)
    _write_tech_lef(p, n_routing=5, metal_prefix="met")
    verdict, _, summary = audit(p)
    assert verdict == "WARN"
    assert summary["metal_prefix"] == "met"
    assert summary["pdk_metal_layers_total"] == 5
    assert summary["pnr_routing_layers_used"] == 4


# ---------------------------------------------------------------------------
# Canonical report emission.
# ---------------------------------------------------------------------------

def test_audit_emits_canonical_report(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _write_orchestrator(p, "def=top.def")
    _write_tech_lef(p, n_routing=6)
    audit(p)
    # audit() itself does not write the report — the CLI does.
    # Run the CLI entry point.
    import subprocess
    import sys as _sys
    PROG = (Path(__file__).resolve().parent.parent / "pnr_via_stack_completeness_check.py")
    r = subprocess.run(
        [_sys.executable, str(PROG), str(p)],
        capture_output=True, text=True)
    assert r.returncode == 0
    canonical = (p / "reports" / "phase3"
                 / "pnr_via_stack_completeness.json")
    assert canonical.is_file()
    data = json.loads(canonical.read_text())
    assert data["gate"] == "pnr_via_stack_completeness_check"
    assert data["verdict"] in ("PASS", "WARN", "SKIP")
