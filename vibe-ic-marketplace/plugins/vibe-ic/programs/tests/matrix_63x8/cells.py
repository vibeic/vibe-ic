"""matrix_63x8.cells — the 504-cell ledger.

63 flow steps x 8 audit dimensions = 504 cells. Every cell must end up in
exactly one of three machine-checkable states (ENFORCED / WAIVED / NA) — see
``README.md``. This module only *enumerates* the cells and carries the 2026-07
audit's finding as human-readable history. It decides nothing.

====================================================================
WHERE THE 63 COME FROM — AND WHERE THEY DELIBERATELY DO NOT
====================================================================
:data:`ALL_CELLS` is the cross product of

    flowref.step_ids()   x   DIMENSIONS

The step list is read **live from the flow yaml**, never from
``.audit_63x8.json``. That is the whole point: if someone adds a 64th step or
deletes one, the ledger changes with the repo and the meta-test
(``programs/tests/test_matrix_63x8_ledger.py``) notices immediately. A ledger
sourced from the audit JSON would keep reporting a tidy 504 while the flow
drifted underneath it — which is the exact failure mode this campaign exists to
stamp out.

====================================================================
``audit_verdict`` / ``audit_summary`` ARE HISTORY. DO NOT ASSERT ON THEM.
====================================================================
They exist so a human reading a failure knows what the July audit thought. A
test that asserts ``cell.audit_verdict == "OK"`` measures a JSON file, not the
repository, and is exactly the disease. Every predicate a sibling writes must
be recomputed live from the current source tree.

Verdict values:

    "OK" | "DEFECT" | "NA"    dimensions 1-7, taken verbatim from the audit
                              record's ``verdict`` field.
    "NOTE"                    dimension 8 with prose but no recorded defect.
    "DEFECT"                  dimension 8 when the audit's ``defects`` list
                              carries an entry at (step, 8).
    "ABSENT_FROM_AUDIT"       the step is not in the audit at all, OR the audit
                              has the step but that dimension's value is null,
                              OR no audit source could be located.

Two measured quirks of the audit data, recorded so nobody rediscovers them:

  * **Dimension 8 has no verdict field.** ``d8_missing_mechanism`` is a plain
    prose string on 62 steps and ``null`` on step 10. There is no
    ``{"verdict": ...}`` to read. Deriving OK/NA by grepping that prose for
    "N/A" would be a text-matching guess dressed as a finding, so this module
    refuses to: prose alone yields ``"NOTE"``, and only an explicit entry in
    the audit's own ``defects`` list promotes a d8 cell to ``"DEFECT"``.
  * **The per-dimension verdicts and the ``defects`` list disagree on 13
    cells** (e.g. D1/dim3 records ``OK`` while a LOW-severity defect is filed
    against it). For dimensions 1-7 the ``verdict`` field wins here, because it
    is the per-cell field. The disagreement is history noise; do not build
    anything on it.

    Audit step ids are ALL strings (``"1"``, ``"D1"``); flow step ids are
    mixed int/str. Lookup normalises through :func:`flowref.normalize_id`.

====================================================================
AUDIT SOURCE RESOLUTION
====================================================================
The raw audit lives at ``<repo>/.audit_63x8.json`` — **untracked, and outside
the plugin root**, so it is absent on any other checkout and on the flattened
install cache. Resolution order:

  1. ``$VIBE_IC_MATRIX_AUDIT_JSON`` if set and readable
  2. ``.audit_63x8.json`` walking up from the plugin root
  3. the vendored distilled snapshot ``audit_history.json`` beside this module
     — **not created by default.** Deliberately: a committed copy of the audit
     is a SECOND source of truth that silently diverges the moment the raw one
     is regenerated, and keeping the two reconciled is exactly the maintenance
     burden this package is supposed to avoid. Generate it only if the history
     is needed on a checkout that lacks the raw file.

If none resolves, every cell gets ``"ABSENT_FROM_AUDIT"`` and imports still
succeed. Losing the history must never break a live predicate.

Generate the (optional) vendored snapshot::

    python3 -m matrix_63x8.cells --write-snapshot
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from . import flowref
from .flowref import StepId

# ──────────────────────────────────────────────────────────────────────
# Dimensions
# ──────────────────────────────────────────────────────────────────────
DIMENSIONS: Tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8)

DIMENSION_NAMES: Dict[int, str] = {
    1: "wiring",
    2: "falsifiable",
    3: "outputs_produced",
    4: "criteria_match",
    5: "deps_correct",
    6: "skip_discipline",
    7: "outputs_list_complete",
    8: "missing_caught",
}

#: One line per dimension — the question the cell actually asks.
#:
#: Dimensions 1-7 ask about the GATE. Dimension 8 asks about the CATCHER: when
#: a declared output goes missing, which mechanism should have noticed. That is
#: a different KIND of question, so it sits last and the number equals display
#: order. The audit JSON is ALREADY in this numbering; there is no legacy
#: mapping to apply and none must be introduced.
DIMENSION_QUESTIONS: Dict[int, str] = {
    1: "Is the gate actually wired — does something real parse and execute it?",
    2: "Can the gate fail? Is there a reachable non-zero-exit branch?",
    3: "Are the declared required_outputs genuinely produced?",
    4: "Does the gate measure what its name and docstring claim it measures?",
    5: "Is blocks_on the true upstream set — no missing and no phantom edge?",
    6: "Is every skip / vacuous-pass disclosed rather than counted as a pass?",
    7: "Is required_outputs complete — does the step emit artefacts it never declares?",
    8: "When a declared output IS missing, which mechanism catches it?",
}

#: Field name each dimension occupies in ``.audit_63x8.json``. Index = dim - 1.
AUDIT_FIELDS: Tuple[str, ...] = (
    "d1_wiring",
    "d2_runnable",
    "d3_outputs_produced",
    "d4_criteria_match",
    "d5_deps_correct",
    "d6_skip_abuse",
    "d7_outputs_list_complete",
    "d8_missing_mechanism",
)

#: The dimension whose audit record is prose, not ``{"verdict": ...}``.
PROSE_ONLY_DIM = 8

ABSENT = "ABSENT_FROM_AUDIT"
NOTE = "NOTE"

VERDICTS: Tuple[str, ...] = ("OK", "DEFECT", "NA", NOTE, ABSENT)

SUMMARY_MAX = 200

_SNAPSHOT_PATH = Path(__file__).resolve().parent / "audit_history.json"
_AUDIT_BASENAME = ".audit_63x8.json"
_AUDIT_ENV = "VIBE_IC_MATRIX_AUDIT_JSON"


# ──────────────────────────────────────────────────────────────────────
# Cell
# ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Cell:
    """One (step, dimension) coordinate of the matrix.

    ``step_id`` keeps the yaml's raw type (``'D1'`` or ``12``). Compare with
    :func:`flowref.normalize_id` when you need a stable key.
    """

    step_id: Union[str, int]
    dim: int
    audit_verdict: str
    audit_summary: str

    @property
    def key(self) -> Tuple[str, int]:
        """Normalised, hashable coordinate: ``("12", 4)``."""
        return (flowref.normalize_id(self.step_id), self.dim)

    @property
    def dim_name(self) -> str:
        return DIMENSION_NAMES[self.dim]

    @property
    def label(self) -> str:
        """Human label used in test ids and failure messages: ``12/d4:criteria_match``."""
        return f"{flowref.normalize_id(self.step_id)}/d{self.dim}:{self.dim_name}"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.label


# ──────────────────────────────────────────────────────────────────────
# Audit source resolution + distillation
# ──────────────────────────────────────────────────────────────────────
def _candidate_raw_paths() -> Tuple[Path, ...]:
    out = []
    env = os.environ.get(_AUDIT_ENV)
    if env:
        out.append(Path(env))
    root = flowref.PLUGIN_ROOT
    for cand in (root, *root.parents):
        out.append(cand / _AUDIT_BASENAME)
    return tuple(out)


@lru_cache(maxsize=1)
def audit_source() -> Optional[Path]:
    """The audit file actually in use, or ``None`` when history is unavailable.

    Surfaced so a failure message can say WHICH history it is quoting.
    """
    for cand in _candidate_raw_paths():
        try:
            if cand.is_file():
                return cand
        except OSError:  # pragma: no cover - defensive
            continue
    if _SNAPSHOT_PATH.is_file():
        return _SNAPSHOT_PATH
    return None


def _distill(text: Any) -> str:
    """Collapse a multi-sentence audit note to <= SUMMARY_MAX chars."""
    if text is None:
        return ""
    s = re.sub(r"\s+", " ", str(text)).strip()
    if len(s) <= SUMMARY_MAX:
        return s
    cut = s[: SUMMARY_MAX - 1]
    space = cut.rfind(" ")
    if space > SUMMARY_MAX * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "…"


def _history_from_raw(doc: Dict[str, Any]) -> Dict[Tuple[str, int], Tuple[str, str]]:
    """Build ``{(step, dim): (verdict, summary)}`` from the RAW audit document."""
    out: Dict[Tuple[str, int], Tuple[str, str]] = {}

    d8_defects = {
        flowref.normalize_id(d.get("step_id"))
        for d in (doc.get("defects") or [])
        if d.get("dimension") == PROSE_ONLY_DIM
    }

    for rec in doc.get("steps") or []:
        sid = flowref.normalize_id(rec.get("step_id"))
        for dim in DIMENSIONS:
            value = rec.get(AUDIT_FIELDS[dim - 1])
            if value is None:
                # Present step, absent cell. Honest signal, not an error.
                out[(sid, dim)] = (ABSENT, "")
            elif isinstance(value, dict):
                verdict = str(value.get("verdict") or ABSENT)
                out[(sid, dim)] = (verdict, _distill(value.get("note")))
            else:
                # Prose-only (dimension 8). No verdict to read; only an explicit
                # defects-list entry promotes it above NOTE.
                verdict = "DEFECT" if sid in d8_defects else NOTE
                out[(sid, dim)] = (verdict, _distill(value))
    return out


def _history_from_snapshot(
    doc: Dict[str, Any]
) -> Dict[Tuple[str, int], Tuple[str, str]]:
    out: Dict[Tuple[str, int], Tuple[str, str]] = {}
    for sid, dims in (doc.get("cells") or {}).items():
        for dim_s, rec in (dims or {}).items():
            out[(str(sid), int(dim_s))] = (
                str(rec.get("verdict") or ABSENT),
                str(rec.get("summary") or ""),
            )
    return out


@lru_cache(maxsize=1)
def audit_history() -> Dict[Tuple[str, int], Tuple[str, str]]:
    """``{(normalized_step_id, dim): (verdict, summary)}``. Empty when absent."""
    src = audit_source()
    if src is None:
        return {}
    try:
        doc = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # pragma: no cover - defensive
        return {}
    if isinstance(doc, dict) and "cells" in doc and "steps" not in doc:
        return _history_from_snapshot(doc)
    if isinstance(doc, dict):
        return _history_from_raw(doc)
    return {}  # pragma: no cover - defensive


# ──────────────────────────────────────────────────────────────────────
# The ledger
# ──────────────────────────────────────────────────────────────────────
def _build() -> Tuple[Cell, ...]:
    history = audit_history()
    cells = []
    # Deterministic order: yaml declaration order for steps (NOT sorted — the
    # yaml order is the flow order and is what a human reads), dimension
    # ascending within each step.
    for sid in flowref.step_ids():
        key = flowref.normalize_id(sid)
        for dim in DIMENSIONS:
            verdict, summary = history.get((key, dim), (ABSENT, ""))
            cells.append(
                Cell(
                    step_id=sid,
                    dim=dim,
                    audit_verdict=verdict,
                    audit_summary=summary,
                )
            )
    return tuple(cells)


ALL_CELLS: Tuple[Cell, ...] = _build()

_BY_KEY: Dict[Tuple[str, int], Cell] = {c.key: c for c in ALL_CELLS}


def cells_for(dim: int) -> Tuple[Cell, ...]:
    """Every cell of one dimension, in flow order. 63 entries."""
    if dim not in DIMENSIONS:
        raise ValueError(f"dim must be one of {DIMENSIONS}, got {dim!r}")
    return tuple(c for c in ALL_CELLS if c.dim == dim)


def cell(step_id: StepId, dim: int) -> Cell:
    """The single cell at ``(step_id, dim)``. Accepts int or str step ids."""
    key = (flowref.normalize_id(step_id), int(dim))
    if key not in _BY_KEY:
        raise KeyError(
            f"no cell {key}; the flow declares "
            f"{len(flowref.step_ids())} steps x {len(DIMENSIONS)} dimensions"
        )
    return _BY_KEY[key]


def cells_for_step(step_id: StepId) -> Tuple[Cell, ...]:
    """All 8 cells of one step, dimension-ascending."""
    key = flowref.normalize_id(step_id)
    return tuple(c for c in ALL_CELLS if flowref.normalize_id(c.step_id) == key)


def absent_from_audit() -> Tuple[Cell, ...]:
    """Cells with no recorded history. A signal worth surfacing, not an error."""
    return tuple(c for c in ALL_CELLS if c.audit_verdict == ABSENT)


def rebuild() -> Tuple[Cell, ...]:
    """Recompute :data:`ALL_CELLS` from the CURRENT flow yaml.

    Falsifiability harness only, paired with :func:`flowref.set_flow_yaml`:
    ``ALL_CELLS`` is a module-level snapshot taken at import, so a test that
    mutates the yaml must call this or it will keep asserting against the
    pre-mutation ledger — a stale-snapshot false pass, which is the same
    disease at one remove.
    """
    global ALL_CELLS, _BY_KEY
    audit_source.cache_clear()
    audit_history.cache_clear()
    ALL_CELLS = _build()
    _BY_KEY = {c.key: c for c in ALL_CELLS}
    return ALL_CELLS


# ──────────────────────────────────────────────────────────────────────
# Snapshot maintenance
# ──────────────────────────────────────────────────────────────────────
def build_snapshot() -> Dict[str, Any]:
    """Distilled, committable form of the history currently resolved."""
    hist = audit_history()
    cells_out: Dict[str, Dict[str, Dict[str, str]]] = {}
    for (sid, dim), (verdict, summary) in sorted(hist.items()):
        cells_out.setdefault(sid, {})[str(dim)] = {
            "verdict": verdict,
            "summary": summary,
        }
    src = audit_source()
    return {
        "_comment": (
            "Distilled history from the 2026-07 63x8 audit. HISTORY ONLY - no "
            "test may assert on these values. Regenerate with "
            "`python3 -m matrix_63x8.cells --write-snapshot`."
        ),
        "generated_from": src.name if src else None,
        "dimension_names": {str(k): v for k, v in DIMENSION_NAMES.items()},
        "cells": cells_out,
    }


def _write_snapshot() -> Path:  # pragma: no cover - maintenance entry point
    _SNAPSHOT_PATH.write_text(
        json.dumps(build_snapshot(), ensure_ascii=False, indent=1, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return _SNAPSHOT_PATH


if __name__ == "__main__":  # pragma: no cover
    import sys

    if "--write-snapshot" in sys.argv:
        print(f"wrote {_write_snapshot()}")
    else:
        print(f"audit source: {audit_source()}")
        print(f"cells: {len(ALL_CELLS)}  absent-from-audit: {len(absent_from_audit())}")


__all__ = [
    "DIMENSIONS",
    "DIMENSION_NAMES",
    "DIMENSION_QUESTIONS",
    "AUDIT_FIELDS",
    "VERDICTS",
    "ABSENT",
    "NOTE",
    "PROSE_ONLY_DIM",
    "SUMMARY_MAX",
    "Cell",
    "ALL_CELLS",
    "cells_for",
    "cells_for_step",
    "cell",
    "absent_from_audit",
    "rebuild",
    "audit_source",
    "audit_history",
    "build_snapshot",
]
