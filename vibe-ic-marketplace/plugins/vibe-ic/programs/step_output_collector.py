#!/usr/bin/env python3
"""step_output_collector.py — materialize a per-STEP output subfolder view.

For ANY Vibe-IC run, this gathers every flow step's resolved output artifacts
into `<project>/steps/<id>_<slug>/` (SYMLINKS to the canonical files — which
stay in their inter-step-contract locations, e.g. phase2/stage1/rtl/) plus an
`outputs.json` manifest per step, and writes `<project>/steps/index.json` (the
ordered step list + folder + status + output count).

Non-invasive by design: the canonical `phaseN/…` tree remains authoritative and
is NEVER moved (downstream steps read each other by fixed path); `steps/` is a
convenience VIEW the dashboard links to. Idempotent — re-running refreshes the
symlinks + manifests to the current on-disk state.

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
    """Yield (id, name, status, phase, [output entries]) using the SAME data
    source as the dashboard (flow_dashboard_data.collect — never raises)."""
    import flow_dashboard_data as fdd
    data = fdd.collect(project)
    for ph in data.get("phases", []):
        pkey = ph.get("key", "")
        for st in ph.get("steps", []):
            yield (str(st.get("id", "")), str(st.get("name", "")),
                   str(st.get("status", "")), pkey, st.get("outputs", []) or [])


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


def materialize(project: Path) -> Dict[str, Any]:
    project = Path(project).expanduser().resolve()
    steps_root = project / "steps"
    steps_root.mkdir(parents=True, exist_ok=True)
    index: List[Dict[str, Any]] = []

    for sid, name, status, phase, outputs in _iter_step_records(project):
        folder = f"{_safe_id(sid)}_{_slug(name)}"
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
             "folder": folder, "outputs": present}, indent=2) + "\n")
        index.append({"id": sid, "name": name, "status": status, "phase": phase,
                      "folder": folder, "n_outputs": len(present)})

    (steps_root / "index.json").write_text(
        json.dumps({"steps": index}, indent=2) + "\n")
    return {"steps_root": str(steps_root), "n_steps": len(index),
            "n_with_outputs": sum(1 for s in index if s["n_outputs"] > 0)}


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
