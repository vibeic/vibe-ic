#!/usr/bin/env python3
"""step_repro_bundle.py — everything one step reads, in one file, plus what it ran on.

WHY THIS FILE EXISTS (vibe-ic#1097, S7)
=======================================
ORFS ships this. `flow/util/utils.mk:158-167` + `flow/util/makeIssue.sh:13-45`
tar every input a stage needs (`SDC_FILE VERILOG_FILES LIB_FILES SC_LEF
TECH_LEF ADDITIONAL_LEFS PDN_TCL RCX_RULES` …) together with an environment
snapshot, so a failing stage travels as ONE artefact instead of as a
description of one.

Measured on this tree at `94754771` before writing a line:

    grep -rloE 'tarfile|shutil\\.make_archive|\\.tar\\.gz' programs/*.py  ->  0 files

Zero. `handoff_bundle_check.py` is a DIFFERENT unit — its own docstring calls
it the Field->Core completeness contract, "the WHOLE verified solution, not a
surface symptom". It is about what a fix must contain. This is about what a
STEP READ. The cost this removes is the field-agent/gatekeeper round trip spent
reconstructing what the failing host actually had.

WHAT IT DOES NOT DO, AND WHY
============================
It does not decide anything. It produces no verdict about the design, cannot
fail a step, and is never consulted by a gate. It is EVIDENCE. The one thing it
refuses to do is ship a bundle that quietly is not one — see the exit codes.

THE FILE LIST IS DERIVED, NEVER RESTATED
========================================
The inputs come from the flow's own `required_inputs`, resolved with the SAME
resolver the input contract uses: `expand()` from `step_required_inputs_check`
and `_glob_first()` from `flow_compliance_check`. A second notion of "this
artefact exists" is how the two halves of one contract end up disagreeing about
the same file, which is the reason `step_required_inputs_check` imports its
resolver rather than owning one, and this module does the same.

EXIT CODES — a partial bundle must not read as a bundle
=======================================================
    0   COMPLETE   every declared input resolved and is in the archive
    1   INCOMPLETE the archive was still written, and the manifest NAMES every
                   input that could not be resolved. A reproduction missing an
                   input is not a reproduction, and the caller has to be able
                   to tell the two apart without reading the tar.
    2   REFUSED    nothing could be bundled: unknown step id, no flow
                   definition, or the step declares NO `required_inputs` at
                   all. The last is `UNDECLARED`, not "has none" — the same
                   distinction `step_required_inputs_check` draws — and an
                   empty archive reported as success is the vacuous pass this
                   repo removes from instruments one at a time.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:                          # pragma: no cover
    sys.path.insert(0, str(_HERE))

try:
    from step_required_inputs_check import expand, load_flow  # type: ignore
    from flow_compliance_check import _glob_first, DEFAULT_FLOW_DEF  # type: ignore
except Exception as exc:                                # pragma: no cover
    print(f"step_repro_bundle: cannot import the input-contract resolvers: "
          f"{exc}", file=sys.stderr)
    sys.exit(2)

#: Where the bundle lands when the caller does not choose. Under `reports/` so
#: the run's own artefact conventions apply to it, and NOT under
#: `benchmark-data/`, which the hygiene tier's corpus-write guard watches.
DEFAULT_REL = "reports/repro"

#: Bytes. A repro bundle exists to be attached to an issue or copied between
#: hosts; a multi-GB layout defeats that. A file over the cap is RECORDED with
#: its size and left out, never silently included and never silently dropped.
DEFAULT_MAX_BYTES = 64 * 1024 * 1024


def _git(repo: Path, *args: str) -> Optional[str]:
    """`git -C repo args…`, or None. Best-effort: a bundle from a tarball with
    no `.git` is still a bundle, and saying "unknown" is the honest field."""
    try:
        r = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def environment(project: Path) -> Dict[str, Any]:
    """What this ran ON. The half a file list cannot carry.

    Every field is nullable and a null is written as null rather than omitted:
    a reader must be able to tell "we looked and there was no anchor" from "the
    snapshot did not have that field", which is the same distinction the exit
    codes above draw one level up.
    """
    plugin_root = _HERE.parent
    repo_root = plugin_root.parents[2] if len(plugin_root.parents) >= 3 else None
    anchor = None
    if repo_root is not None:
        vf = repo_root / "tools" / "vibeic-eda" / "VERSION"
        if vf.is_file():
            try:
                anchor = vf.read_text(encoding="utf-8").strip() or None
            except OSError:
                anchor = None
    return {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "plugin_commit": _git(plugin_root, "rev-parse", "HEAD"),
        "plugin_dirty": bool(_git(plugin_root, "status", "--porcelain")),
        "project_commit": _git(project, "rev-parse", "HEAD"),
        "eda_image_anchor": anchor,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        # The two the container backend actually keys on. Recorded verbatim,
        # never interpreted here.
        "env_PDK_ROOT": os.environ.get("PDK_ROOT"),
        "env_VIBEIC_PDKS_ROOT": os.environ.get("VIBEIC_PDKS_ROOT"),
    }


def collect(project: Path, step_ids: Sequence[str],
            flow_def: Optional[Path] = None,
            max_bytes: int = DEFAULT_MAX_BYTES) -> Dict[str, Any]:
    """What the bundle WOULD contain, without writing it.

    Separated from the writer so a caller (and a test) can ask "is this step
    reproducible from this tree" without producing a file.
    """
    steps, err = load_flow(Path(flow_def or DEFAULT_FLOW_DEF))
    if err:
        return {"ok": False, "verdict": "REFUSED", "error": err,
                "steps": [], "files": [], "missing": []}
    by_id = {str(s.get("id")): s for s in steps}

    unknown = [s for s in step_ids if s not in by_id]
    if unknown:
        return {"ok": False, "verdict": "REFUSED",
                "error": f"no such step id(s) in the flow: {', '.join(unknown)}",
                "steps": [], "files": [], "missing": []}

    files: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    undeclared: List[str] = []
    seen: set = set()
    rows: List[Dict[str, Any]] = []

    for sid in step_ids:
        step = by_id[sid]
        entries = step.get("required_inputs") or []
        rows.append({"id": sid, "name": step.get("name", ""),
                     "stage": step.get("stage", ""),
                     "declares_inputs": bool(entries),
                     "required_outputs": list(step.get("required_outputs") or [])})
        if not entries:
            # UNDECLARED, not "has none" — see the module docstring.
            undeclared.append(sid)
            continue
        for e in entries:
            if str(e.get("from")) == "external" and e.get("check") == "none":
                # No project-relative path to probe. Recorded so it is visible
                # and NOT counted as either bundled or missing.
                missing.append({"step": sid, "path": None,
                                "what": e.get("what"),
                                "why": "declared external input with no "
                                       "project-relative path to probe"})
                continue
            for producer, spec in expand(e, by_id):
                hits: List[str] = []
                for alt in (p.strip() for p in str(spec).split(" OR ")):
                    hits = _glob_first(project, alt)
                    if hits:
                        break
                if not hits:
                    missing.append({"step": sid, "from": producer,
                                    "path": spec, "what": e.get("what"),
                                    "why": "no file on this tree matches the "
                                           "declared path"})
                    continue
                for rel in hits:
                    if rel in seen:
                        continue
                    seen.add(rel)
                    p = project / rel
                    try:
                        size = p.stat().st_size
                    except OSError:
                        missing.append({"step": sid, "from": producer,
                                        "path": rel,
                                        "why": "matched the declaration but "
                                               "could not be stat'd"})
                        continue
                    if size > max_bytes:
                        # Named with its size. Not silently included (the
                        # bundle stops being portable) and not silently
                        # dropped (the reader would think it was there).
                        missing.append({"step": sid, "from": producer,
                                        "path": rel, "bytes": size,
                                        "why": f"over the {max_bytes}-byte "
                                               f"bundle cap"})
                        continue
                    files.append({"step": sid, "from": producer,
                                  "path": rel, "bytes": size})

    if undeclared and not files and not missing:
        return {"ok": False, "verdict": "REFUSED",
                "error": (f"step(s) {', '.join(undeclared)} declare NO "
                          f"required_inputs — their data dependency is "
                          f"UNKNOWN, not empty, so there is nothing to bundle "
                          f"and this is NOT an empty success"),
                "steps": rows, "files": [], "missing": [],
                "undeclared": undeclared}

    return {
        "ok": not missing,
        "verdict": "COMPLETE" if not missing else "INCOMPLETE",
        "steps": rows,
        "files": files,
        "missing": missing,
        "undeclared": undeclared,
        "environment": environment(project),
    }


def write_bundle(project: Path, step_ids: Sequence[str], out: Path,
                 flow_def: Optional[Path] = None,
                 max_bytes: int = DEFAULT_MAX_BYTES) -> Dict[str, Any]:
    """Write `out` (a .tar.gz) and return the manifest.

    The manifest goes INSIDE the archive as `MANIFEST.json` as well as being
    returned, so a bundle that gets copied without its caller's log still
    states its own completeness.
    """
    rep = collect(project, step_ids, flow_def, max_bytes)
    if rep["verdict"] == "REFUSED":
        return rep
    out.parent.mkdir(parents=True, exist_ok=True)
    rep["bundle"] = str(out)
    payload = json.dumps(rep, indent=2, sort_keys=True).encode("utf-8")
    with tarfile.open(out, "w:gz") as tf:
        for f in rep["files"]:
            tf.add(project / f["path"], arcname=f"inputs/{f['path']}")
        info = tarfile.TarInfo("MANIFEST.json")
        info.size = len(payload)
        info.mtime = int(time.time())
        import io
        tf.addfile(info, io.BytesIO(payload))
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=(__doc__ or "").strip().split("\n")[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--step", action="append", required=True, metavar="ID",
                    help="flow step id to bundle (repeatable)")
    ap.add_argument("--out", type=Path, default=None,
                    help=f"bundle path (default <project>/{DEFAULT_REL}/"
                         f"step-<ids>.tar.gz)")
    ap.add_argument("--json", dest="json_out", type=Path, default=None,
                    help="write the manifest here as well")
    ap.add_argument("--flow-def", type=Path, default=None)
    ap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    ap.add_argument("--collect-only", action="store_true",
                    help="report what would be bundled; write nothing")
    a = ap.parse_args(argv)

    if a.collect_only:
        rep = collect(a.project, a.step, a.flow_def, a.max_bytes)
    else:
        out = a.out or (a.project / DEFAULT_REL /
                        f"step-{'-'.join(a.step)}.tar.gz")
        rep = write_bundle(a.project, a.step, out, a.flow_def, a.max_bytes)

    if a.json_out:
        a.json_out.parent.mkdir(parents=True, exist_ok=True)
        a.json_out.write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")

    if rep["verdict"] == "REFUSED":
        print(f"[REFUSED] step_repro_bundle: {rep['error']}", file=sys.stderr)
        return 2

    for m in rep["missing"]:
        print(f"   MISSING  step {m['step']}  {m.get('path')}  — {m['why']}",
              file=sys.stderr)
    n_f, n_m = len(rep["files"]), len(rep["missing"])
    where = rep.get("bundle", "(not written: --collect-only)")
    if rep["verdict"] == "INCOMPLETE":
        print(f"[INCOMPLETE] step_repro_bundle: {n_f} input(s) bundled, "
              f"{n_m} NOT resolved (named above) for step(s) "
              f"{', '.join(a.step)} -> {where}. A reproduction missing an "
              f"input is not a reproduction.", file=sys.stderr)
        return 1
    print(f"[COMPLETE] step_repro_bundle: {n_f} input(s) bundled for step(s) "
          f"{', '.join(a.step)} -> {where}")
    return 0


if __name__ == "__main__":                              # pragma: no cover
    sys.exit(main())
