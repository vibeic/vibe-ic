#!/usr/bin/env python3
"""ORGANIC #735 (P2) — deep-review sidecar doc-path mismatch (silent drop).

DEFECT SHAPE: a skill/doc instructed writing the durable AI deep-review sidecar
to the PROJECT ROOT (`<project>/ai_deep_review_patches.json`) while the canonical
`_path_layout` resolver + every consuming gate read
`<project>/phase1/ai_deep_review_patches.json`. A fresh agent following the doc
wrote to the wrong path; the gates' sidecar loaders resolved the phase1/ path,
found nothing, and SILENTLY returned {} → the MANDATORY AI-recovery channel was
defeated with no diagnostic.

FIX (Bucket A, chip-AGNOSTIC):
  (1) align the SKILL.md doc + the stale docstring to `phase1/...`;
  (2) defense-in-depth — in the sidecar loaders of BOTH phase-1 doc-floor gates
      (`phase1_doc_input_completeness_check`, `l_doc_structured_field_count_check`),
      when the canonical phase1/ file is absent but a same-named ROOT copy exists,
      emit a one-line WARNING (stderr) and read the ROOT copy for backward-compat
      instead of silently dropping it.

END-STATE asserted (per loader), via 3 fixtures:
  (1) sidecar at phase1/  → loaded, NO warning   (PASS / canonical path)
  (2) identical at ROOT   → loaded, WITH warning (backward-compat surfacing)
  (3) no sidecar          → empty, NO warning    (unchanged behaviour)

chip-AGNOSTIC: structural filename + path-resolution only; no chip/vendor literal.
"""
import io
import json
import sys
from contextlib import redirect_stderr
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _path_layout as _pl  # noqa: E402
import phase1_doc_input_completeness_check as COMP  # noqa: E402
import l_doc_structured_field_count_check as CNT  # noqa: E402

_AI = "ai_deep_review_patch"

# A typed, doc-traceable patch payload that BOTH loaders accept:
#  - completeness loader merges any patches.<layer> list (text serialised);
#  - field-count loader credits L4 entries carrying name + a substantive shape.
_PATCHES = {
    "L4_REGMAP": [
        {
            "literal": "CTRL @ 0x10",
            "name": "CTRL",
            "offset": "0x10",
            "fields": ["EN", "MODE"],
            "kind": "indexed_register_address",
            "extraction_strategy": _AI,
        }
    ]
}


def _phase1_sidecar(proj: Path) -> Path:
    return _pl.phase1_ai_deep_review_patches_file(proj)


def _root_sidecar(proj: Path) -> Path:
    return proj / "ai_deep_review_patches.json"


def _write_sidecar(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"patches": _PATCHES}), encoding="utf-8")


# ── canonical path resolver must NOT have drifted to ROOT ────────────────────
def test_resolver_path_is_under_phase1(tmp_path):
    proj = tmp_path / "p"
    side = _pl.phase1_ai_deep_review_patches_file(proj)
    # END-STATE: resolver still returns the phase1/ location (the gates read it).
    assert side == proj / "phase1" / "ai_deep_review_patches.json"
    assert side.parent.name == "phase1"


# ════════════════════════════════════════════════════════════════════════════
# completeness gate loader: phase1_doc_input_completeness_check
# ════════════════════════════════════════════════════════════════════════════
def _comp_load(proj: Path):
    buf = io.StringIO()
    with redirect_stderr(buf):
        out = COMP._load_ai_patches_sidecar(proj)
    return out, buf.getvalue()


def test_comp_fixture1_phase1_path_loaded_no_warning(tmp_path):
    proj = tmp_path / "p"
    _write_sidecar(_phase1_sidecar(proj))
    out, warn = _comp_load(proj)
    # END-STATE: phase1/ sidecar is loaded (PASS path) and no misplacement warned.
    assert "L4_REGMAP" in out and out["L4_REGMAP"]
    assert "CTRL" in out["L4_REGMAP"]
    assert "WARNING" not in warn


def test_comp_fixture2_root_path_warns_and_backward_compat_loads(tmp_path):
    proj = tmp_path / "p"
    _write_sidecar(_root_sidecar(proj))  # WRONG path — the 現象
    assert not _phase1_sidecar(proj).exists()
    out, warn = _comp_load(proj)
    # END-STATE: instead of a SILENT {}, the misplaced ROOT sidecar is surfaced
    # via a one-line WARNING AND read for backward-compat.
    assert "WARNING" in warn
    assert "ai_deep_review_patches.json" in warn
    assert "L4_REGMAP" in out and "CTRL" in out["L4_REGMAP"]


def test_comp_fixture3_no_sidecar_empty_no_warning(tmp_path):
    proj = tmp_path / "p"
    (proj).mkdir(parents=True, exist_ok=True)
    out, warn = _comp_load(proj)
    # END-STATE: absence is still a clean empty merge — no spurious warning.
    assert out == {}
    assert "WARNING" not in warn


def test_comp_phase1_wins_when_both_present(tmp_path):
    """A canonical phase1/ file present alongside a ROOT copy → phase1/ wins,
    NO warning (the misplacement path is the fallback only)."""
    proj = tmp_path / "p"
    _write_sidecar(_phase1_sidecar(proj))
    # ROOT copy with a DIFFERENT marker so we can prove which one loaded.
    root = _root_sidecar(proj)
    root.parent.mkdir(parents=True, exist_ok=True)
    root.write_text(json.dumps(
        {"patches": {"L4_REGMAP": [{"name": "ROOTONLY",
                                    "offset": "0xFF",
                                    "extraction_strategy": _AI}]}}),
        encoding="utf-8")
    out, warn = _comp_load(proj)
    assert "CTRL" in out.get("L4_REGMAP", "")
    assert "ROOTONLY" not in out.get("L4_REGMAP", "")
    assert "WARNING" not in warn


# ════════════════════════════════════════════════════════════════════════════
# field-count gate loader: l_doc_structured_field_count_check
# ════════════════════════════════════════════════════════════════════════════
def _cnt_load(proj: Path):
    buf = io.StringIO()
    with redirect_stderr(buf):
        out = CNT._load_field_count_sidecar(proj)
    return out, buf.getvalue()


def test_cnt_fixture1_phase1_path_loaded_no_warning(tmp_path):
    proj = tmp_path / "p"
    _write_sidecar(_phase1_sidecar(proj))
    out, warn = _cnt_load(proj)
    # END-STATE: L4 (regmap) floor layer credited from the phase1/ sidecar.
    assert 4 in out and out[4]
    assert out[4][0].get("name") == "CTRL"
    assert "WARNING" not in warn


def test_cnt_fixture2_root_path_warns_and_backward_compat_loads(tmp_path):
    proj = tmp_path / "p"
    _write_sidecar(_root_sidecar(proj))  # WRONG path — the 現象
    assert not _phase1_sidecar(proj).exists()
    out, warn = _cnt_load(proj)
    # END-STATE: WARNING surfaced + the misplaced sidecar honoured (backward-compat)
    # instead of the prior SILENT {} that defeated the count floor.
    assert "WARNING" in warn
    assert "ai_deep_review_patches.json" in warn
    assert 4 in out and out[4][0].get("name") == "CTRL"


def test_cnt_fixture3_no_sidecar_empty_no_warning(tmp_path):
    proj = tmp_path / "p"
    (proj).mkdir(parents=True, exist_ok=True)
    out, warn = _cnt_load(proj)
    # END-STATE: unchanged — absence is a clean empty merge, no warning.
    assert out == {}
    assert "WARNING" not in warn


# ── doc + docstring alignment guard (the Bucket-A doc fix) ───────────────────
def test_skill_doc_and_docstring_use_phase1_path():
    """Guard the prior behaviour regression: the SKILL.md Step-3 sidecar
    instruction and the completeness gate's loader docstring must point at the
    canonical phase1/ path, not the ROOT path that caused the silent drop."""
    skill = (_PROGRAMS.parents[0] / "skills"
             / "phase1-completeness-deep-review" / "SKILL.md")
    text = skill.read_text(encoding="utf-8")
    # The canonical write-target instruction must name phase1/.
    assert "<project>/phase1/ai_deep_review_patches.json" in text
    # The completeness loader docstring must not still advertise the ROOT path
    # as the sidecar home.
    doc = COMP._load_ai_patches_sidecar.__doc__ or ""
    assert "phase1/ai_deep_review_patches.json" in doc
    assert "<project>/ai_deep_review_patches.json" not in doc


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
