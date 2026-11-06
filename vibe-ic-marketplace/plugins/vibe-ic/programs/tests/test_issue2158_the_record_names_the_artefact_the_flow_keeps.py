"""vibe-ic#2158 — the run's record names the artefact the flow KEEPS.

MEASURED on run22 (8HD-6, sha256 x sky130A, DIE, pass 2, verdict FAIL): the
published `reports/orchestrator/phase2_one_shot.json` carried the SAME hand-off
sentence three times, and only two of the three had been translated out of the
deleted staging copy:

    steps[3].detail                     -> /home/.../run22/phase2/stage1/...   OK
    steps[3].extras.fallback_skill_path -> /home/.../run22/phase2/stage1/...   OK
    steps[3].waiver_rows[0].reason      -> /tmp/vibeic-rtl-step-bc6aoiqh/
                                           run22/phase2/stage1/fallback_skill.md  LEAK

The artefact itself was in the tree at `phase2/stage1/fallback_skill.md` the
whole time (44849 bytes). `project_outputs_in_tree_check` reads that dangling
reference and FAILs the P0 structural umbrella, so every WAIVE-route project was
blocked by a record that misstated where its own evidence lives.

WHY IT WAS ONE FIELD AND NOT THE OTHER TWO: `#2158`/`#2183` remapped `detail`,
`output_files` and `extras` by NAME. R-0915-85 later added `reason_class`,
`declared_by`, `waiver_rows`, `attribution` and `disclosures` beside the verdict,
and none of them was added to that list -- an enumerated list cannot cover a
field that does not exist yet. The population is now DERIVED from the dataclass.
"""
import importlib
import json
import sys
import tempfile
from dataclasses import fields
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

R = importlib.import_module("design_one_shot_runner")
_STAGE_MARK = "vibeic-rtl-step"


def _text_fields(row):
    """Every field of the row that can carry a pathname, DERIVED."""
    return [f.name for f in fields(row)
            if isinstance(getattr(row, f.name), (str, list, tuple, dict))]


def _stage_paths(value):
    out = []
    if isinstance(value, str):
        out += [t for t in value.replace('"', " ").replace("`", " ").split()
                if _STAGE_MARK in t]
    elif isinstance(value, dict):
        for v in value.values():
            out += _stage_paths(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            out += _stage_paths(v)
    return out


def _project(tmp: Path) -> Path:
    docs = tmp / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps({"part_name": "widget"}))
    (docs / "L2_FRS.json").write_text(json.dumps(
        {"notes": "A block that folds a message into a digest."}))
    return tmp


# ── (1) THE RUN22 SHAPE ITSELF ───────────────────────────────────────────────
def test_no_field_of_a_waive_route_step_names_the_staging_copy():
    """run22's class, run22's route, every field swept -- not the three the old
    remap happened to name."""
    with tempfile.TemporaryDirectory() as td:
        res = R.step_rtl_gen(_project(Path(td)), "crypto_accelerator")
        assert res.status == "PASS_WITH_WAIVERS", res.detail
        leaked = {name: _stage_paths(getattr(res, name))
                  for name in _text_fields(res)}
        leaked = {k: v for k, v in leaked.items() if v}
        assert leaked == {}, (
            "these field(s) still name the deleted staging copy: "
            + "; ".join(f"{k} -> {v[0]}" for k, v in sorted(leaked.items())))
        kept = (res.extras or {}).get("fallback_skill_path") or ""
        assert kept and Path(kept).is_file(), kept
        assert Path(kept).relative_to(td).as_posix() == (
            "phase2/stage1/fallback_skill.md")


# ── (2) THE POPULATION IS DERIVED, NOT ENUMERATED ────────────────────────────


# ── (3) THE WRITE SEAM REFUSES WHAT THE REMAP WOULD HAVE MISSED ──────────────
