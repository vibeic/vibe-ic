"""Canonical backend consumer seam used after ULTRACORE adoption."""
from __future__ import annotations
# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

from pathlib import Path
import json

import execution_modes as em
from execution_backend_gates import evaluate
from execution_adapters_backend import ROWS


def import_selected(project, context, controller, run, adopted):
    """Re-read current canonical gates without importing another runner stack."""
    project, run = Path(project), Path(run)
    if adopted.get("status") != "PROVISIONAL":
        raise em.Refusal("BACKEND_ADOPTION_UNBOUND", str(project))
    generation = adopted.get("selected_generation") or {}
    selected_dir = Path(generation.get("directory", ""))
    if not selected_dir.is_dir() or selected_dir.is_symlink():
        raise em.Refusal("BACKEND_SELECTED_GENERATION_UNBOUND", context.step_id)
    manifest = selected_dir / "manifest.json"
    if not manifest.is_file() or manifest.is_symlink():
        raise em.Refusal("BACKEND_SELECTED_MANIFEST_MISSING", context.step_id)
    try:
        bound = em._issued(manifest)
    except (OSError, ValueError, KeyError, em.Refusal) as exc:
        raise em.Refusal("BACKEND_SELECTED_MANIFEST_UNBOUND", str(exc)) from exc
    if (bound.get("status") != "PROVISIONAL" or bound.get("binding") != context.binding() or
            bound.get("directory") != str(selected_dir) or project != selected_dir or
            selected_dir.parent != run / "selected"):
        raise em.Refusal("BACKEND_PROVISIONAL_GENERATION_UNBOUND", context.step_id)
    if bound.get("run_id") != adopted.get("run_id") or bound.get("arm_id") != adopted.get("selected"):
        raise em.Refusal("BACKEND_SELECTED_MANIFEST_MISMATCH", context.step_id)
    result_path = selected_dir / "backend_result.json"
    if not result_path.is_file():
        raise em.Refusal("BACKEND_SELECTED_SUBSTANCE_REFUSED", context.step_id)
    result = json.loads(result_path.read_text())
    expected = (bound.get("outputs") or {}).get("backend_result.json")
    if not expected or em.digest(result_path) != expected:
        raise em.Refusal("BACKEND_SELECTED_DIGEST_MISMATCH", context.step_id)
    if result.get("verdict") == "FAIL":
        raise em.Refusal("GATE_FAIL", context.step_id)
    if result.get("verdict") != "PASS":
        raise em.Refusal("BACKEND_CANONICAL_CONSUMER_REFUSED", context.step_id)
    # The selected generation is the production consumer's source of truth;
    # never fall back to the mutable run root or the original project tree.
    # Re-run the exact row-owned consumer against the immutable generation.
    # Passing an empty synthetic row would turn the consumer into a census
    # call; the canonical row carries the declared gate and output semantics.
    gates = evaluate(selected_dir, ROWS[str(context.step_id)]["canonical_row"])
    if gates.get("status") == "FAIL":
        raise em.Refusal("GATE_FAIL", context.step_id)
    return {"status": "CONSUMED", "step_id": context.step_id,
            "source_sha": context.source_sha, "consumer": gates,
            "design_verdict": "PASS"}


__all__ = ["import_selected"]
