#!/usr/bin/env python3
"""step_output_collector.py — materialize a per-STEP output subfolder view.

For ANY Vibe-IC run, this gathers every flow step's resolved output artifacts
into `<project>/steps/<phase>/<stage>/<id>_<slug>/` (SYMLINKS to the canonical
files — which stay in their inter-step-contract locations, e.g.
phase2/stage1/rtl/) plus an `outputs.json` manifest per step, and writes
`<project>/steps/index.json` (the ordered step list + folder + status + output
count).

NESTED BY PHASE THEN STAGE (owner directive): a flat `steps/<id>_<slug>/`
made every step look like a peer of every other, with no visual sense of
"where in the flow" a step sits. `flow_dashboard_data.collect()` already
carries both `phase` (its own key: phase1/phase2/phase3/analog/mixed/
manufacturing) and `stage` (the flow yaml's stage id: stage1/stage2/.../
stage_analog/stage_mixed_signal/stage5_manufacturing) per step, so no new
classification is invented here — `folder` is just their existing values
joined with `/`. `folder` is stored as a relative PATH STRING throughout
(steps/index.json, each outputs.json, the dashboard's directory-listing
route), and `Path(root) / folder` nests correctly on a multi-segment string
with no caller change needed — verified against flow_dashboard_web.py's
`_steps_root(project) / folder`.

Non-invasive by design: the canonical `phaseN/…` tree remains authoritative and
is NEVER moved (downstream steps read each other by fixed path); `steps/` is a
convenience VIEW the dashboard links to. Idempotent — re-running refreshes the
symlinks + manifests to the current on-disk state, and prunes now-empty
phase/stage directories left over from a prior layout.

chip-AGNOSTIC: derives everything from the flow YAML + the project's own files.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", name or "").strip("_").lower()
    return (s[:48] or "step")


def _safe_id(sid: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", sid or "") or "x"


def _iter_step_records(project: Path):
    """Yield (id, name, status, phase, stage, [output entries]) using the SAME
    data source as the dashboard (flow_dashboard_data.collect — never raises).
    `stage` is the step's own yaml stage id; a step lacking one (should not
    happen for a real flow node) falls back to "stage" so nesting never
    silently collapses two unrelated steps into the same directory."""
    import flow_dashboard_data as fdd
    data = fdd.collect(project)
    for ph in data.get("phases", []):
        pkey = ph.get("key", "")
        for st in ph.get("steps", []):
            yield (str(st.get("id", "")), str(st.get("name", "")),
                   str(st.get("status", "")), pkey,
                   str(st.get("stage") or "stage"),
                   st.get("outputs", []) or [])


def _clear_old(sdir: Path) -> None:
    """Drop stale symlinks + the manifest so a refresh reflects current state."""
    if not sdir.is_dir():
        return
    for old in sdir.iterdir():
        if old.is_symlink() or old.name == "outputs.json":
            try:
                old.unlink()
            except OSError:
                pass


def _prune_stale_folders(steps_root: Path, old_folders: List[str],
                          new_folders: set) -> None:
    """Remove step folders (and now-empty phase/stage parents) from a PRIOR
    run's index.json that the current run no longer produces.

    Handles two real cases, not just a hypothetical one: (a) a step whose
    name changed re-slugs to a different folder, orphaning the old one, and
    (b) migrating an EXISTING flat `<id>_<slug>/` run to this nested
    `<phase>/<stage>/<id>_<slug>/` layout — every old flat folder is stale
    under the new scheme and would otherwise sit next to the new tree
    forever, one becoming an increasingly misleading duplicate of the other.
    """
    for rel in old_folders:
        if rel in new_folders:
            continue
        old_dir = steps_root / rel
        # TRAVERSAL GUARD. `rel` comes from a PRIOR index.json — a file on
        # disk, not a value this call computed — and this loop DELETES. A
        # stale, hand-edited or copied-in index.json carrying `../../x` made
        # `steps_root / rel` resolve outside the project; measured before this
        # guard, that unlinked a symlink and an `outputs.json` in an unrelated
        # directory and then rmdir'd it. Bounded damage is still damage, and
        # deletion code does not get to rely on its input being well formed.
        try:
            resolved = old_dir.resolve()
            if not resolved.is_relative_to(steps_root.resolve()):
                continue
        except (OSError, ValueError):
            continue
        if not old_dir.is_dir():
            continue
        for child in old_dir.iterdir():
            if child.is_symlink() or child.name == "outputs.json":
                try:
                    child.unlink()
                except OSError:
                    pass
        try:
            old_dir.rmdir()
        except OSError:
            continue
        # Walk back up: drop now-empty phase/stage parents this folder's
        # removal left behind, but never above steps_root itself.
        parent = old_dir.parent
        while parent != steps_root and parent.is_relative_to(steps_root):
            try:
                parent.rmdir()   # only succeeds if truly empty
            except OSError:
                break
            parent = parent.parent


def materialize(project: Path) -> Dict[str, Any]:
    project = Path(project).expanduser().resolve()
    steps_root = project / "steps"
    steps_root.mkdir(parents=True, exist_ok=True)

    prior_index_path = steps_root / "index.json"
    prior_folders: List[str] = []
    if prior_index_path.is_file():
        try:
            prior = json.loads(prior_index_path.read_text())
            prior_folders = [s.get("folder", "") for s in prior.get("steps", [])
                             if s.get("folder")]
        except Exception:
            prior_folders = []

    index: List[Dict[str, Any]] = []
    new_folders: set = set()

    for sid, name, status, phase, stage, outputs in _iter_step_records(project):
        # `phase` is drawn from flow_dashboard_data's fixed 6-entry _PHASES
        # table and `stage` defaults to "stage" in _iter_step_records — never
        # empty in practice — but a path built from external data must not
        # silently collapse a segment if it ever is.
        folder = "/".join((phase or "phase", stage or "stage",
                          f"{_safe_id(sid)}_{_slug(name)}"))
        new_folders.add(folder)
        sdir = steps_root / folder
        sdir.mkdir(parents=True, exist_ok=True)
        _clear_old(sdir)

        present: List[Dict[str, Any]] = []
        for o in outputs:
            if not o.get("exists"):
                continue
            src = Path(str(o.get("abs") or ""))
            if not src.exists():
                continue
            link = sdir / src.name
            if link.exists() or link.is_symlink():   # basename collision
                link = sdir / f"{src.parent.name}__{src.name}"
            try:
                link.symlink_to(src)                  # absolute → mount-stable
            except OSError:
                pass
            present.append({"rel": o.get("rel"), "abs": str(src),
                            "size": int(o.get("size") or 0)})

        (sdir / "outputs.json").write_text(json.dumps(
            {"id": sid, "name": name, "status": status, "phase": phase,
             "stage": stage, "folder": folder, "outputs": present},
            indent=2) + "\n")
        index.append({"id": sid, "name": name, "status": status, "phase": phase,
                      "stage": stage, "folder": folder,
                      "n_outputs": len(present)})

    _prune_stale_folders(steps_root, prior_folders, new_folders)

    (steps_root / "index.json").write_text(
        json.dumps({"steps": index}, indent=2) + "\n")

    # Everything above this line is DERIVED FROM `required_outputs` — it is a
    # restatement of the declaration and cannot witness anything the
    # declaration does not already claim. step_write_ledger observes what the
    # run ACTUALLY WROTE (lstat walk: size, mtime, kind) and residuals it
    # against the declaration, writing reports/write_ledger.json plus a
    # per-step written.json beside each outputs.json above.
    # Best-effort by construction: emit() never raises, and a failure is
    # reported in the return value rather than allowed to kill a run.
    # MEASURED cost: ~13 ms on a 748-entry run dir, ~104 ms on a 16k-entry one.
    ledger: Dict[str, Any] = {"ok": False, "error": "not attempted"}
    try:
        import step_write_ledger as _swl
        ledger = _swl.emit(project)
    except Exception as exc:                      # noqa: BLE001
        ledger = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    return {"steps_root": str(steps_root), "n_steps": len(index),
            "n_with_outputs": sum(1 for s in index if s["n_outputs"] > 0),
            "write_ledger": ledger}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)
    res = materialize(a.project)
    txt = json.dumps(res, indent=2)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(txt + "\n")
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
