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


    # END-STATE: instead of a SILENT {}, the misplaced ROOT sidecar is surfaced
    # via a one-line WARNING AND read for backward-compat.


# ════════════════════════════════════════════════════════════════════════════
# field-count gate loader: l_doc_structured_field_count_check
# ════════════════════════════════════════════════════════════════════════════


    # END-STATE: WARNING surfaced + the misplaced sidecar honoured (backward-compat)
    # instead of the prior SILENT {} that defeated the count floor.


# ── doc + docstring alignment guard (the Bucket-A doc fix) ───────────────────
    # The completeness loader docstring must not still advertise the ROOT path
    # as the sidecar home.


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
