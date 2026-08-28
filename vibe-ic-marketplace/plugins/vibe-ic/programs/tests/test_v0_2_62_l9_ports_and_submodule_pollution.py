"""v0.2.62 L9 port-propagation + submodule-pollution regressions.

Pins the #431 fix (ORGANIC-20260606-l9-ports-empty-submodule-pollution):
on a Path-B project whose external-interface doc fully defines the port
list, L9 emitted EMPTY top_ports and its submodules[] carried ~11 verbatim
markdown headings lifted from the verification-plan doc. Two root causes:

  1. the 4COL grid parser hard-coded the `signal | WIDTH | DIR | desc`
     column order — the equally common `signal | DIR | WIDTH | desc`
     ordering matched ZERO rows (only the suffix-heuristic fallback's
     1/5 lucky hit survived). New `_RE_L1_L9_RST_IFACE_4COL_DIR2`
     sibling covers that order; the L1→L9 cascade then carries all ports.
  2. `_l9_heading_submodule_extract`'s context regex armed on a
     verification-plan doc that merely SAYS "submodule-level verification"
     in prose, promoting every "## N.N <Stage>" heading to a phantom
     submodule. Two deny layers: doc-TYPE (verification/test-plan docs are
     never module sources) and entry (…Stage/…Test/…Phase/… titles).

chip-AGNOSTIC: fixtures use a generic multiplier-block doc set.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"

sys.path.insert(0, str(PROGRAMS))
import phase1_doc_one_shot_runner as D  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_L3_DOC = """# External Interface Specification

The multiplier block exposes the following ports:

| Port | Dir | Width | Description |
|------|-----|-------|-------------|
| clk | input | 1 | system clock |
| rst_n | input | 1 | async reset, active low |
| op_a | input | 32 | operand A bus |
| op_b | input | 32 | operand B bus |
| result | output | 64 | product result bus |
"""

_L7_DOC = """# Verification Plan

This document defines the submodule-level verification strategy.

## 1.1 Smoke Test Stage
Basic connectivity.

## 1.2 Random Operand Stage
Constrained random operands.

## 1.3 Corner Value Stage
Zero, max, sign boundaries.

## 1.4 Coverage Closure Stage
Functional coverage bins.
"""


# ── unit: column-order sibling regex ───────────────────────────────────────

def test_dir2col_regex_matches_all_rows():
    rows = [m.group("signal") for m in
            D._RE_L1_L9_RST_IFACE_4COL_DIR2.finditer(_L3_DOC)]
    assert rows == ["clk", "rst_n", "op_a", "op_b", "result"]


def test_legacy_width_first_order_still_matched_by_original():
    doc = "| data_o | 8 | output | data bus |\n"
    m = D._RE_L1_L9_RST_IFACE_4COL.search(doc)
    assert m and m.group("signal") == "data_o"


# ── unit: heading-pollution deny layers ───────────────────────────────────

def test_verification_plan_doc_yields_no_submodules():
    assert D._l9_heading_submodule_extract(_L7_DOC) == []


def test_entry_deny_kills_activity_titles():
    # context word present, doc NOT self-identified as a plan — entry-level
    # deny must still drop verification-activity titles
    doc = ("# Integration notes\n\nsubmodule inventory follows.\n\n"
           "## 2.1 ALU core\n\n## 2.2 Regression Gate Stage\n\n"
           "## 2.3 decoder unit\n")
    out = D._l9_heading_submodule_extract(doc)
    assert "ALU core" in out and "decoder unit" in out
    assert all("Stage" not in s for s in out)


def test_soc_numbered_heading_inventory_still_extracts():
    # the original v0.1.82 use case (SoC integration spec with numbered
    # submodule headings) must keep working — deny layers are narrow
    doc = ("# SoC submodule integration\n\n"
           "### 8.1 SERV core(必含)\n\n### 8.4 GPIO peripheral\n")
    out = D._l9_heading_submodule_extract(doc)
    assert "SERV core" in out and "GPIO peripheral" in out


# ── end-to-end: the filing's acceptance fixture ────────────────────────────

def test_path_b_project_five_ports_zero_phantom_submodules(tmp_path):
    proj = tmp_path / "proj"
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L3_external_interface.md").write_text(_L3_DOC)
    (docs / "L7_verification_plan.md").write_text(_L7_DOC)
    r = _pr.run(
        [sys.executable, str(PROGRAMS / "phase1_one_shot_runner.py"),
         str(proj), "--ic-name", "mul32"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-1200:] + r.stderr[-1200:]
    l9 = json.loads(
        (proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json")
        .read_text())
    ports = {p.get("name") for p in (l9.get("top_ports") or [])}
    assert ports == {"clk", "rst_n", "op_a", "op_b", "result"}, ports
    subs = [s.get("name") if isinstance(s, dict) else s
            for s in (l9.get("submodules") or [])]
    assert subs == [], f"phantom submodules: {subs}"
