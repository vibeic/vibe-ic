#!/usr/bin/env python3
"""ORGANIC #646 ROUND-2 — the explicit `**Project name:**` declaration must be
USED as ic_name (it was sitting below the folder-name tier, so the folder leaf
out-voted it and the declared project name was never delivered).

Field-agent reopen: the macro stoplist works (USE_POWER_PINS no longer hijacks
ic_name — good), but the fix's claimed explicit-declaration tier did not
deliver the project name on the real caravel. Round-2: the
`**Project name:**` / `**Top deliverable:**` declaration tier is promoted ABOVE
the folder-name corroboration tier so the DECLARED name wins.

ACCEPTANCE: a doc with `**Project name:** foo_chip` → ic_name == "foo_chip"
(never None, never an HDL/PDK macro), even when a folder name is present.

NEGATIVE no-leak: an HDL/PDK macro (USE_POWER_PINS/SYNTHESIS/...) is NEVER
selected as ic_name (the macro stoplist is preserved).

chip-AGNOSTIC: a generic vendor-doc bold-label grammar; no chip/SKU literal.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase1_doc_one_shot_runner as R  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402


def test_project_name_declaration_is_used():
    doc = {"L1.md": "# Spec\n\n- **Project name:** foo_chip\n"
                    "- **Top deliverable:** `foo_wrapper`\n"}
    assert R._ic_name_from_docs_impl(doc) == "foo_chip"


def test_declaration_wins_over_folder(tmp_path):
    """With BOTH a folder name AND an explicit `**Project name:**`, the
    DECLARATION wins (the round-2 reorder)."""
    proj = tmp_path / "my_folder_name"
    proj.mkdir()
    doc = {"L1.md": "- **Project name:** declared_chip\n"
                    "declared_chip appears in prose too.\n"}
    assert R._ic_name_from_docs_impl(doc, project=proj) == "declared_chip"


def test_declaration_never_a_macro_NOLEAK():
    """NO-LEAK: even if a declaration line somehow names a macro, the HDL/PDK
    stoplist rejects it; and a macro in RTL scope never becomes ic_name."""
    doc = {"L1.md": "- **Project name:** real_soc_top\n",
           "rtl.v": "module real_soc_top();\n`ifdef USE_POWER_PINS\n"
                    " inout vccd1;\n`endif\nendmodule\n"}
    name = R._ic_name_from_docs_impl(doc)
    assert name == "real_soc_top"
    assert name != "USE_POWER_PINS"
    assert not R._is_hdl_pdk_macro_token(name)


@pytest.mark.parametrize("label", [
    "Project name", "Top deliverable", "Chip name", "Design name"])
def test_all_declaration_labels(label):
    doc = {"L1.md": f"- **{label}:** my_design_top\n"}
    assert R._ic_name_from_docs_impl(doc) == "my_design_top"


def test_end_to_end_phase1_uses_declaration(tmp_path):
    """ORGANIC #646 round-2 — drive the REAL phase1 program end-to-end on a
    fixture shaped like the issue's 現象 (an L1 with `**Project name:**` + a
    folder leaf that differs) and assert the FINAL L1.ic_name end-state is the
    DECLARED project name, never None / a macro / the bare folder leaf."""
    import json
    import subprocess
    proj = tmp_path / "some_folder_leaf"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "L1_product_metadata.md").write_text(
        "# Product\n\n- **Project name:** declared_top_chip\n"
        "- **Top deliverable:** `declared_top_chip_wrapper`\n")
    (proj / "input" / "docs" / "L3_external_interface.md").write_text(
        "## External Interface\n\n| Signal | Direction | Width |\n"
        "|---|---|---|\n| clk_i | input | 1 |\n")
    runner = _PROGRAMS / "phase1_one_shot_runner.py"
    r = subprocess.run([sys.executable, str(runner), str(proj)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    # NOTE: the canonical L1 doc is L1_DATASHEET.json — a `L1*.json` glob would
    # spuriously match L10..L23 (e.g. L17_CHANNEL_SIGNAL_CATALOG.json), so we
    # target the datasheet explicitly.
    l1 = proj / "phase1" / "generated_docs" / "L1_DATASHEET.json"
    name = json.loads(l1.read_text()).get("ic_name")
    assert name == "declared_top_chip", name
    assert name is not None and not R._is_hdl_pdk_macro_token(name)


def test_real_caravel_ic_name_is_declared_project(tmp_path):
    """The real caravel: ic_name == caravel_user_project (the declared project
    name), never None / a macro / the bare folder leaf. SKIPs off-monorepo."""
    base = require_corpus("_bench7_caravel_v1034_cleanroom/caravel/input/docs")
    if not base.is_dir():
        pytest.skip("real caravel docs not on disk")
    ext = {p.name: p.read_text(errors="ignore") for p in base.glob("L*.md")}
    name = R._ic_name_from_docs_impl(ext)
    assert name == "caravel_user_project", name
    assert name is not None and not R._is_hdl_pdk_macro_token(name)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
