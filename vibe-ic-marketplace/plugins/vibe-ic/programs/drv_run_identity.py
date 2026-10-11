#!/usr/bin/env python3
"""The run identity an in-flow DRV capture binds (ruling R-0929-DRV-IDENTITY).

An in-flow capture (step 23, step 32, pre-stream) can bind only identity that
exists at that point: the digests of the design state it judges (the plan
records those), the run's code identity recorded when the run started, and
the specification version.  This module holds the last two:

* :func:`record` is called when a Phase-3 run starts.  It writes
  ``reports/phase3/drv_run_identity.json``: a fresh run id, the plugin's git
  commit (the flow's existing source identity, ``_plugin_source_sha``'s
  answer) and a content digest of the installed plugin tree, which exists
  whether or not the plugin is git-backed.
* :func:`spec_version` is the content digest of the Phase-1 documents the run
  implements (``phase1/generated_docs``).  Absent documents give None, which
  the judge reports NOT_MEASURED.

GDS and LVS-netlist identity are not here: they exist only after stream-out
and are bound by the final post-stream capture.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_text  # noqa: E402

RECORD = Path("reports/phase3/drv_run_identity.json")
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SPEC_DOCS = Path("phase1/generated_docs")


def _tree_digest(root: Path) -> str:
    """sha256 over every file's relative path and bytes (caches excluded)."""
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        if "__pycache__" in rel.parts or path.suffix == ".pyc":
            continue
        h.update(str(rel).encode() + b"\0")
        h.update(hashlib.sha256(path.read_bytes()).hexdigest().encode() + b"\n")
    return h.hexdigest()


def _git_commit(root: Path) -> Optional[str]:
    try:
        cp = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = (cp.stdout or "").strip()
    return sha if cp.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", sha) else None


def record(project: Path, *, plugin_root: Path = PLUGIN_ROOT) -> dict:
    """Record this run's identity at run start (replaces any earlier run's)."""
    doc = {"run_id": uuid.uuid4().hex,
           "recorded_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
           "plugin_source_commit": _git_commit(plugin_root),
           "plugin_tree_sha256": _tree_digest(plugin_root),
           "plugin_root": str(plugin_root),
           "spec_version": spec_version(project)}
    write_text(project / RECORD, json.dumps(doc, indent=2) + "\n")
    return doc


def start(project: Path, *, continue_steps=None) -> dict:
    """Start a fresh run, or continue one local Default run's checkpoints.

    A fresh run claims its own receipts. An explicit Default continuation
    retains the logical run ID and preceding tool evidence, records the current
    code identity, and withdraws the selected and downstream stage receipts.
    Original start time and code identity remain available for provenance.
    """
    import drv_stage_receipts
    if continue_steps is not None:
        previous = load(project)
        run_id = previous.get("run_id")
        if (isinstance(run_id, str) and re.fullmatch(r"[0-9a-f]{32}", run_id)
                and drv_stage_receipts.current_run(project) == run_id):
            # Use the same consumer that will judge these receipts. A directory
            # claim or a 'not run' row alone is not a completed checkpoint.
            import drv_capture_plan
            rows, _ = drv_capture_plan._stages(project, True)
            # Step 9 keeps ABC's executed script before Step 15's SDC exists.
            # Its census is completed at Step 15, so that mapping checkpoint
            # must survive even though there is not yet a synth-stage row.
            abc = drv_stage_receipts.abc_script_path(project)
            mapped = abc.is_file() and abc.stat().st_size > 0
            if mapped or any(row.get("ran") for row in rows):
                current_spec = spec_version(project)
                if (previous.get("spec_version") is not None
                        and previous["spec_version"] != current_spec):
                    raise ValueError("Default checkpoint specification changed; "
                                     "preceding stages cannot be reused")
                doc = dict(previous)
                doc.setdefault("initial_code_identity", {k: previous.get(k) for k in (
                    "plugin_source_commit", "plugin_tree_sha256", "recorded_at")})
                doc.update(plugin_source_commit=_git_commit(PLUGIN_ROOT),
                           plugin_tree_sha256=_tree_digest(PLUGIN_ROOT),
                           plugin_root=str(PLUGIN_ROOT), spec_version=current_spec,
                           continued_at=_dt.datetime.now(_dt.timezone.utc).isoformat())
                drv_stage_receipts.invalidate_from_steps(project, continue_steps)
                write_text(project / RECORD, json.dumps(doc, indent=2) + "\n")
                return doc
    doc = record(project)
    drv_stage_receipts.claim(project)
    return doc


def load(project: Path) -> dict:
    try:
        doc = json.loads((project / RECORD).read_text())
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def spec_version(project: Path) -> Optional[str]:
    """Content digest of the Phase-1 documents the run implements."""
    root = project / SPEC_DOCS
    files = sorted(p for p in root.glob("*.json") if p.is_file()) if root.is_dir() else []
    if not files:
        return None
    h = hashlib.sha256()
    for path in files:
        h.update(path.name.encode() + b"\0")
        h.update(hashlib.sha256(path.read_bytes()).hexdigest().encode() + b"\n")
    return "phase1-docs-sha256:" + h.hexdigest()
