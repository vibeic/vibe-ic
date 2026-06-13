#!/usr/bin/env python3
"""Wave 75 — tests for eda_doctor pre-flight health probe.

Static-shape coverage. The live behavior (docker_reachable, tool
version probes) requires the iic-osic-tools container to be running.

Positive: probe enumeration includes all expected EDA tools.
Negative: SOFT-tagged tools (magic, fault) MUST NOT fail allOk.
Edge   : skip_versions=true short-circuits per-tool version queries.
SKIP   : when docker is unreachable, doc_* probes are still skipped.
"""
from pathlib import Path

INDEX_JS = Path(__file__).resolve().parent.parent / "src" / "index.js"


def _slice():
    src = INDEX_JS.read_text()
    idx = src.find('"eda_doctor"')
    assert idx > 0
    # eda_doctor body extends ~4500 lines; capture through the end of
    # the tool registration so summary line at the closing wrapResult
    # is included.
    return src[idx: idx + 8000]


def test_tool_registered():
    assert '"eda_doctor"' in INDEX_JS.read_text()


def test_probes_canonical_tool_set():
    """Positive: must probe yosys + openroad + klayout + iverilog +
    verilator + magic + netgen + ngspice + fault. A regression that
    drops one of these silently breaks the pre-flight check."""
    w = _slice()
    for tool in ("yosys", "openroad", "klayout", "iverilog",
                 "verilator", "magic", "netgen", "ngspice", "fault"):
        assert f'"{tool}"' in w, f"eda_doctor must probe {tool}"


def test_soft_tools_marked_to_not_break_allok():
    """Negative: magic + fault are listed as SOFT — their absence
    must not flip allOk to false. v0.26.5 codified this."""
    w = _slice()
    assert "SOFT_TOOLS" in w
    assert "magic" in w and "fault" in w
    # The contract is: `if (!ok && !soft) allOk = false;`
    assert "if (!ok && !soft)" in w, (
        "SOFT tool fail must short-circuit before allOk=false"
    )


def test_skip_versions_short_circuits_probes():
    """Edge: skip_versions=true must avoid invoking getToolVersion
    so doctor stays cheap on slow networks."""
    w = _slice()
    assert "skip_versions" in w
    assert 'skip_versions ? "skipped"' in w


def test_doc_probes_only_when_skip_versions_false():
    """SKIP-equivalent: pdftotext / libreoffice / openpyxl probes
    must be guarded by `if (!skip_versions)` so the cheap path is
    truly cheap."""
    w = _slice()
    # docProbes appears inside the `if (!skip_versions)` block
    assert "if (!skip_versions)" in w
    # pdftotext is the canonical first probe
    assert "pdftotext" in w
    assert "libreoffice" in w
    assert "openpyxl" in w


def test_pdk_check_skipped_when_docker_unreachable():
    """Edge: PDK file probes are guarded behind `probe.ok`; agents
    on a host without docker should still get useful health output
    rather than dockerExec spam."""
    w = _slice()
    assert "if (probe.ok && custom_pdk)" in w


def test_summary_format_x_of_y():
    """Positive: summary line is `${passed}/${total} checks passed`
    so log scrapers / dashboards can extract a score."""
    w = _slice()
    assert "checks passed" in w
