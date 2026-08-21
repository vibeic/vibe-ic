#!/usr/bin/env python3
"""An emitted analysis script that hard-codes the directory it was emitted in
is not reproducible anywhere else, which is the whole point of emitting it.

WHAT THIS CHECKS
================
The flow emits its own analysis scripts — the OpenSTA / OpenROAD / KLayout
decks it drives the tools with — into the run tree, so a reviewer can re-run
the measurement. MEASURED on one real run tree, `26 of 34` emitted scripts
carried an absolute path pointing back INTO the run directory they were
written for:

    reports/phase3/power_<top>.tcl
        read_verilog /<host>/<run>/trials/t001/phase2/stage2/synth/<top>_synth.v

Two consequences, and the second is the one that bites silently:

  * the script cannot be re-run anywhere else — not on another host, not from
    a copy of the run tree, not from an archive;
  * any hash-based identity over the script is defeated by the run directory.
    Two runs of a BYTE-IDENTICAL measurement configuration hash differently
    purely because they ran in different directories, so a comparison that
    requires "same analysis configuration" refuses two arms that are in fact
    identically configured.

THE RULE, AND WHY IT IS THIS RULE
=================================
An absolute path INSIDE the run root is a finding. An absolute path OUTSIDE it
is not.

That split is not a convenience. A path inside the run root names something
this run produced, and the run tree moves — so the script must reach it
relatively. A path outside the run root names the environment (the PDK, the
tool install, the container's own filesystem); it is not this run's to
relativise, and rewriting it would break the script rather than port it.

`/foss/pdks/...` in a container-canonical deck is therefore CLEAN here, and
that is deliberate: it is already portable across every host that runs the
same image.

THE REMEDY THE FLOW USES
========================
The emitter writes a prologue that resolves the run root from the script's
OWN location, and expresses every in-tree path against it:

    set RUN_ROOT [file normalize [file join [file dirname [info script]] .. ..]]
    read_verilog $RUN_ROOT/phase2/stage2/synth/<top>_synth.v

`info script` is set by every Tcl `source`, including the one `sta -no_init
-exit <file>` performs (verified in the pinned image), so the same script
resolves correctly under an identity bind-mount and under a canonical one.

EXIT CODES
==========
  0  every script in scope expresses its in-tree paths relatively
  1  at least one script hard-codes a path inside the run root  (a FINDING)
  2  [CANNOT CHECK] — nothing was in scope, or scope could not be read. This
     is NOT a pass: "I looked and it was clean" and "I could not look" must
     never produce the same answer.
  3  bad invocation

chip-, PDK- and vendor-AGNOSTIC: it knows about directories, not designs.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling imports
from _atomic_artefact import write_json as atomic_write_json  # noqa: E402

#: What the flow emits and drives a tool with.
SCRIPT_SUFFIXES = (".tcl", ".sh")

#: Staged INPUTS are not emitted by this flow, so their contents are not this
#: check's business.
SKIP_DIR_PARTS = frozenset({"input", ".git", "__pycache__"})

#: An absolute POSIX path as it appears in a Tcl / shell script. Deliberately
#: conservative about terminators: a path is ended by whitespace, a quote, or
#: a shell/Tcl metacharacter, never by a character that can legally sit in a
#: filename.
_ABS_PATH_RE = re.compile(r"/(?:[^\s\"'`;|<>(){}\[\]$]+)")


def _norm(p) -> str:
    return os.path.normpath(os.path.abspath(str(p)))


def host_paths_in(text: str, run_root) -> List[Tuple[int, str]]:
    """`(line_number, path)` for every absolute path in `text` that points
    INSIDE `run_root`. Empty list means the text is portable by this rule."""
    root = _norm(run_root)
    prefix = root.rstrip("/") + "/"
    out: List[Tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in _ABS_PATH_RE.finditer(line):
            cand = m.group(0).rstrip(".,")
            norm = os.path.normpath(cand)
            if norm == root or norm.startswith(prefix):
                out.append((lineno, cand))
    return out


def _discover(project: Path, under: Sequence[str]) -> Tuple[List[Path], Optional[str]]:
    """Scripts in scope, and a refusal reason if the scope could not be read."""
    if under:
        files: List[Path] = []
        for u in under:
            p = project / u if not os.path.isabs(u) else Path(u)
            if p.is_dir():
                files.extend(sorted(q for q in p.rglob("*")
                                    if q.suffix in SCRIPT_SUFFIXES and q.is_file()))
            elif p.is_file():
                files.append(p)
            else:
                return [], f"--under {u!r} does not exist under {project}"
        return sorted(set(files)), None
    files = []
    for p in sorted(project.rglob("*")):
        if p.suffix not in SCRIPT_SUFFIXES or not p.is_file():
            continue
        if SKIP_DIR_PARTS & set(p.relative_to(project).parts[:-1]):
            continue
        files.append(p)
    return files, None


def check(project: Path, under: Sequence[str] = ()) -> Dict[str, object]:
    project = Path(project)
    if not project.is_dir():
        return {"rc": 3, "reason": f"{project} is not a directory",
                "findings": [], "scripts_checked": 0}
    files, refusal = _discover(project, under)
    if refusal is not None:
        return {"rc": 3, "reason": refusal, "findings": [],
                "scripts_checked": 0}
    if not files:
        return {"rc": 2,
                "reason": ("no emitted script (%s) was in scope, so this run "
                           "makes NO claim about path portability"
                           % "/".join(SCRIPT_SUFFIXES)),
                "findings": [], "scripts_checked": 0}
    findings: List[Dict[str, object]] = []
    unreadable: List[str] = []
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError as exc:
            unreadable.append(f"{f}: {exc}")
            continue
        hits = host_paths_in(text, project)
        if hits:
            findings.append({
                "script": str(f.relative_to(project)),
                "count": len(hits),
                "first_line": hits[0][0],
                "example": hits[0][1],
            })
    if unreadable and not (len(files) - len(unreadable)):
        return {"rc": 2,
                "reason": "every script in scope was unreadable: "
                          + "; ".join(unreadable),
                "findings": [], "scripts_checked": 0}
    return {
        "rc": 1 if findings else 0,
        "reason": None,
        "findings": findings,
        "scripts_checked": len(files) - len(unreadable),
        "unreadable": unreadable,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="emitted scripts must not hard-code a path inside the "
                    "run root they were emitted into")
    ap.add_argument("project", help="the run root")
    ap.add_argument("--under", action="append", default=[],
                    help="limit the scope to this path, relative to the run "
                         "root (repeatable). Without it every emitted script "
                         "in the tree is checked.")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    res = check(Path(args.project), args.under)
    if args.json_out:
        # A DECLARED report destination goes through `_atomic_artefact`
        # (vibe-ic#1082): a reader that opens this path must never see a
        # half-written document, and `atomic_artifact_write_check.py` names
        # this exact file and line when it does not.
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(args.json_out, res, indent=2)

    rc = int(res["rc"])
    if rc == 3:
        print(f"[BAD INVOCATION] emitted_script_portability_check: "
              f"{res['reason']}")
        return 3
    if rc == 2:
        print(f"[CANNOT CHECK] emitted_script_portability_check: "
              f"{res['reason']}")
        return 2
    if rc == 0:
        print(f"[PASS] emitted_script_portability_check: "
              f"{res['scripts_checked']} emitted script(s) checked, none "
              f"hard-codes a path inside the run root")
        return 0
    print(f"[FAIL] emitted_script_portability_check: "
          f"{len(res['findings'])} of {res['scripts_checked']} emitted "
          f"script(s) hard-code a path inside the run root, so they cannot be "
          f"re-run from anywhere else and any hash over them is defeated by "
          f"the run directory")
    for f in res["findings"]:
        print(f"  {f['script']}: {f['count']} occurrence(s), first at line "
              f"{f['first_line']}: {f['example']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
