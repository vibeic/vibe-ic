#!/usr/bin/env python3
"""Provenance rows for artefacts imported from an external flow's own step logs.

WHY THIS EXISTS (plan W19, owner decision 4a, 2026-09-28)
--------------------------------------------------------
Under ``--librelane`` the layout is produced by LibreLane, not by a vibe-ic
session, and vibe-ic IMPORTS the step outputs into its canonical tree. The
provenance ledger then needs a row per imported step, and there are only two
honest shapes for it:

* **A back-fill.** The runner hashes a file it did not watch being written.
  Doctrine #365 (``phase3_one_shot_runner._restamp_provenance_output``) says
  that row is ``reconstructed: true`` with ``duration_ms: None``. Nothing here
  changes that: a back-fill is still a back-fill.
* **A witnessed run.** The owner ruled (decision 4a) that LibreLane's OWN step
  record is a witness. Such a row is ``reconstructed: false``, is attributed to
  LibreLane, and CITES its evidence by path and sha256 so any later reader can
  re-check it.

WHAT A WITNESS MUST SHOW, AND HOW EACH PART IS CHECKED
------------------------------------------------------
LibreLane prints ``Running '<id>' at '<dir>'`` in ``Step.start``, BEFORE the
step decides to skip and before ``run()`` succeeds, so a started step proves
nothing. A witness holds only when ALL of these re-verify:

1. **The run's own log, pinned.** ``flow.log`` is append-only and a run tag can
   be reused, so the witness cites the PREFIX the row was written against
   (``bytes`` + the sha256 of those bytes), never the whole file. Later
   appends leave the witness valid.
2. **The step ran a tool and did not skip.** In that prefix, the step's block
   (from its ``Running`` line to the next step outside its folder) must not
   print ``Skipping '<id>'`` or ``Returning state unaltered``, and it must
   name at least one ``Logging subprocess to '<path>'``: the transcript of a
   real tool process. A pure-Python step names none, so it can never be
   witnessed, whatever its step-id prefix.
3. **The cited logs are those transcripts.** Each cited log is named by one of
   the block's ``Logging subprocess`` lines, lies inside the step folder, and
   still has its cited sha256.
4. **The step finished.** Its ``state_out.json``, which LibreLane writes only
   after ``run()`` returns, is cited by sha256.
5. **The declared bytes are that step's bytes.** Every declared output names
   its source file in the step folder (``sources``), and the source's sha256,
   the file on disk, and the row's output digest are all equal.

``tool`` is the UNDERLYING tool (``openroad``, ``yosys``, ``magic``,
``klayout``, ``netgen``, ``verilator``), derived from the step id and never
taken from the caller, so the flow's existing ``provenance_check --tool``
allow-lists judge the row unchanged (decision 4a, not 4b). ``exit_code`` is 0
because of points 2 and 4, not because a caller said so.

Every path in the witness is relative to ``run_dir`` (itself project-
relative), the same convention as the W0 import manifest (lane llf).

THE ONE READER
--------------
`flow_log_steps` and `step_block` read the native flow log. Missing or
malformed output remains unmeasured.

It writes no ``measurement`` record; see ``_runner_measurement``.

chip-AGNOSTIC: no design, PDK or corner literal. The only literals are
LibreLane's own flow-log grammar and its step-id prefixes.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: The external flows whose step logs count as a witness. ORFS joins with its
#: own importer (plan W12 / the ORFS half of W19); until then an ``orfs`` row
#: claiming a witness is refused, not guessed at.
SUPPORTED_FLOWS = ("librelane",)

WITNESS_KIND = "tool_step_log"
WITNESS_SCHEMA = 2

#: ``verify_witness``'s answer when its flow-log reader may not judge.
UNCALIBRATED = "uncalibrated"

#: LibreLane step-id prefix -> the tool the step's subprocess is. ``Odb.*``
#: steps run inside OpenROAD's Python. Whether a step ran a tool at all is
#: decided by its flow-log block (point 2), not by this table.
_STEP_PREFIX_TOOL = {
    "OpenROAD": "openroad",
    "Odb": "openroad",
    "Yosys": "yosys",
    "Magic": "magic",
    "KLayout": "klayout",
    "Netgen": "netgen",
    "Verilator": "verilator",
}

#: LibreLane's flow.log grammar (librelane/steps/step.py): a step starting,
#: a step logging its subprocess, and a step declining to run.
_RUNNING_RE = re.compile(r"^Running '([^']+)' at '([^']+)'…$", re.M)
_SUBPROCESS_RE = re.compile(
    r"^Logging subprocess to (?:\[repr\.filename\])?'([^']+)'"
    r"(?:\[/repr\.filename\])?…$")
_SKIPPING_RE = re.compile(r"Skipping '([^']+)'…$")
_UNALTERED = "Returning state unaltered…"


class WitnessRefused(ValueError):
    """The caller asked for a witnessed row the evidence does not support."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _bare(value: Any) -> str:
    s = str(value or "")
    return s[7:] if s.startswith("sha256:") else s


def underlying_tool(step_id: str) -> Optional[str]:
    """The tool a LibreLane step's subprocess is, or None for no tool."""
    return _STEP_PREFIX_TOOL.get(str(step_id).split(".", 1)[0])


def _parts(path: str) -> Tuple[str, ...]:
    return tuple(p for p in Path(path).parts if p not in ("", "."))


def _ends_with(parts: Tuple[str, ...], want: Tuple[str, ...]) -> bool:
    return bool(want) and len(parts) >= len(want) and parts[-len(want):] == want


def flow_log_steps(flow_log: str) -> List[Tuple[str, Tuple[str, ...]]]:
    """Every step the flow's own log says it started, in the order it did.

    Each item is ``(step_id, folder parts)`` exactly as LibreLane printed them:
    the step id is the INSTANCE id (``OpenROAD.STAMidPNR-3`` for the fourth
    run of a class), and the folder is relative to LibreLane's working
    directory (``runs/<tag>/<dir>``, nested sub-steps included).
    """
    return [(m.group(1), _parts(m.group(2)))
            for m in _RUNNING_RE.finditer(flow_log or "")]


def step_block(flow_log: str, step_id: str,
               step_dir: str) -> Optional[Dict[str, Any]]:
    """What the flow's own log says about ONE step run, or None if it never
    started ``step_id`` in ``step_dir``.

    The block runs from the step's ``Running`` line to the next ``Running``
    line of a step outside its folder (a nested sub-step stays inside). When a
    reused run tag started the same step in the same folder twice, the LAST
    block is the one described. Returns ``{"skipped": bool,
    "subprocess_logs": [folder parts, ...]}``.
    """
    want = _parts(step_dir)
    lines = (flow_log or "").splitlines()
    found: Optional[Dict[str, Any]] = None
    i = 0
    while i < len(lines):
        m = _RUNNING_RE.match(lines[i])
        if not (m and m.group(1) == step_id
                and _ends_with(_parts(m.group(2)), want)):
            i += 1
            continue
        here = _parts(m.group(2))
        block: Dict[str, Any] = {"skipped": False, "subprocess_logs": []}
        j = i + 1
        while j < len(lines):
            n = _RUNNING_RE.match(lines[j])
            if n and _parts(n.group(2))[:len(here)] != here:
                break
            s = _SKIPPING_RE.search(lines[j])
            if (s and s.group(1) == step_id) or lines[j].endswith(_UNALTERED):
                block["skipped"] = True
            p = _SUBPROCESS_RE.match(lines[j])
            if p:
                block["subprocess_logs"].append(_parts(p.group(1)))
            j += 1
        found = block
        i = j
    return found


def _inside(project: Path, path: Path, what: str) -> str:
    """``path`` relative to ``project``; refuses symlinks and escapes."""
    raw = path if path.is_absolute() else project / path
    try:
        rel = raw.relative_to(project)
    except ValueError:
        raise WitnessRefused(f"{what} {raw} is outside the project {project}")
    if ".." in rel.parts:
        raise WitnessRefused(f"{what} {raw} escapes the project")
    cur = project
    for part in rel.parts:
        cur = cur / part
        if cur.is_symlink():
            raise WitnessRefused(f"{what} {raw} passes through a symlink ({cur})")
    return rel.as_posix()


def _run_rel(project: Path, run_abs: Path, path: Path, what: str,
             within: Optional[Path] = None) -> str:
    """``path`` relative to the run directory, inside ``within`` if given."""
    _inside(project, path, what)
    if within is not None:
        try:
            path.relative_to(within)
        except ValueError:
            raise WitnessRefused(f"{what} {path} is not inside the step "
                                 f"directory {within}")
    return path.relative_to(run_abs).as_posix()


def witnessed_row(project: Path, *, flow: str, step_id: str, run_dir: Path,
                  step_dir: str, outputs: Dict[str, Path],
                  duration_ms: Optional[int] = None,
                  version: Optional[str] = None,
                  timestamp: Optional[str] = None) -> Dict[str, Any]:
    """Build the provenance row for one step's outputs.

    ``outputs`` maps each CANONICAL path (project-relative, already copied)
    to the file the step wrote in its own folder. Every digest is computed
    here from disk. Raises ``WitnessRefused`` whenever the evidence does not
    support a witnessed row, including when the flow-log reader may not
    judge; the caller then writes a #365 back-fill, never a weaker witness.
    """
    project = Path(project).resolve()
    if flow not in SUPPORTED_FLOWS:
        raise WitnessRefused(f"flow {flow!r} has no witness rule "
                             f"(supported: {', '.join(SUPPORTED_FLOWS)})")
    tool = underlying_tool(step_id)
    if tool is None:
        raise WitnessRefused(f"step {step_id!r} runs no tool, so it writes no "
                             "tool log to witness it")
    run_rel = _inside(project, Path(run_dir), "run directory")
    run_abs = project / run_rel
    step_rel = Path(step_dir).as_posix()
    step_abs = run_abs / step_rel
    _inside(project, step_abs, "step directory")
    if not step_abs.is_dir():
        raise WitnessRefused(f"step directory {step_abs} does not exist")
    flow_log = run_abs / "flow.log"
    _inside(project, flow_log, "flow log")
    if not flow_log.is_file():
        raise WitnessRefused(f"{flow_log} is missing: nothing names the step")
    prefix = flow_log.read_bytes()
    block = step_block(prefix.decode("utf-8", errors="replace"),
                       step_id, step_rel)
    if block is None:
        raise WitnessRefused(f"flow.log never started {step_id!r} in "
                             f"{step_rel!r}")
    if block["skipped"]:
        raise WitnessRefused(f"flow.log reports {step_id!r} skipped or "
                             "returning its state unaltered")
    logs: List[Dict[str, str]] = []
    tail = _parts(step_rel)
    for parts in block["subprocess_logs"]:
        k = next((n for n in range(len(parts))
                  if parts[n:n + len(tail)] == tail), None)
        if k is None:
            continue
        log = step_abs.joinpath(*parts[k + len(tail):])
        if log.is_file():
            logs.append({"path": _run_rel(project, run_abs, log, "step log",
                                          step_abs),
                         "sha256": _sha256(log)})
    if not logs:
        raise WitnessRefused(f"flow.log names no subprocess transcript of "
                             f"{step_id!r} that is on disk: no tool ran")
    state_out = step_abs / "state_out.json"
    if not state_out.is_file():
        raise WitnessRefused(f"{step_rel}/state_out.json is missing: the step "
                             "did not finish")
    sources: Dict[str, Dict[str, str]] = {}
    outs: Dict[str, str] = {}
    for rel_name, src in outputs.items():
        canon = _inside(project, project / rel_name, "output")
        if canon != Path(rel_name).as_posix():
            raise WitnessRefused(f"output key {rel_name!r} is not a "
                                 "project-relative path")
        if not (project / canon).is_file():
            raise WitnessRefused(f"output {canon} does not exist")
        src = Path(src)
        src_rel = _run_rel(project, run_abs, src, "output source", step_abs)
        if not src.is_file():
            raise WitnessRefused(f"output source {src_rel} does not exist")
        sha = _sha256(src)
        if _sha256(project / canon) != sha:
            raise WitnessRefused(f"{canon} is not the bytes {step_id!r} wrote "
                                 f"({src_rel})")
        outs[canon] = sha
        sources[canon] = {"path": src_rel, "sha256": sha}
    if not outs:
        raise WitnessRefused("a row must declare at least one output")
    row: Dict[str, Any] = {
        "timestamp": timestamp or _dt.datetime.now(_dt.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": tool,
        "attributed_to": flow,
        "step": step_id,
        "exit_code": 0,
        "duration_ms": duration_ms,
        "outputs": outs,
        "reconstructed": False,
        "witness": {
            "kind": WITNESS_KIND,
            "schema": WITNESS_SCHEMA,
            "flow": flow,
            "step_id": step_id,
            "run_dir": run_rel,
            "step_dir": step_rel,
            "flow_log": {"path": "flow.log", "bytes": len(prefix),
                         "sha256": "sha256:"
                         + hashlib.sha256(prefix).hexdigest()},
            "completion": {"path": f"{step_rel}/state_out.json",
                           "sha256": _sha256(state_out)},
            "logs": logs,
            "sources": sources,
        },
    }
    if version:
        row["version"] = version
    return row


def claims_witness(entry: Dict[str, Any]) -> bool:
    """Does this row claim anything beyond a plain logged run?"""
    return isinstance(entry, dict) and (
        "witness" in entry or "attributed_to" in entry)


def verify_witness(entry: Dict[str, Any], project: Path) -> Tuple[Any, str]:
    """Re-read a row's witness.

    ``(None, "")`` when the row claims none; ``(True, "")`` only when every
    point in the module docstring still holds; ``(UNCALIBRATED, reason)`` when
    every check that needs no flow-log reader holds and the reader may not
    judge the rest (NOT_MEASURED, never a FAIL);
    ``(False, reason)`` for every way a claimed witness fails.
    """
    if not claims_witness(entry):
        return None, ""
    project = Path(project).resolve()
    w = entry.get("witness")
    if not isinstance(w, dict):
        return False, "attributed_to is set but the row cites no witness"
    if entry.get("reconstructed") is True:
        return False, ("the row is a runner back-fill (reconstructed: true, "
                       "#365) and also claims a witness")
    if w.get("kind") != WITNESS_KIND:
        return False, f"unknown witness kind {w.get('kind')!r}"
    flow = w.get("flow")
    if flow not in SUPPORTED_FLOWS or entry.get("attributed_to") != flow:
        return False, (f"witness flow {flow!r} / attributed_to "
                       f"{entry.get('attributed_to')!r} is not a supported "
                       "matching pair")
    step_id = str(w.get("step_id") or "")
    tool = underlying_tool(step_id)
    if tool is None or entry.get("tool") != tool:
        return False, (f"tool {entry.get('tool')!r} is not the tool step "
                       f"{step_id!r} runs ({tool!r})")
    try:
        run_rel = _inside(project, Path(str(w.get("run_dir") or "")),
                          "run directory")
        run_abs = project / run_rel
        step_rel = str(w.get("step_dir") or "")
        step_abs = run_abs / step_rel
        _inside(project, step_abs, "step directory")
    except WitnessRefused as exc:
        return False, str(exc)
    if not step_rel or not step_abs.is_dir():
        return False, f"step directory {step_rel!r} does not exist"

    def _cited(obj: Any, what: str, within: Path) -> Tuple[Optional[Path], str]:
        if not isinstance(obj, dict) or not obj.get("path") \
                or not obj.get("sha256"):
            return None, f"{what} citation is missing its path or sha256"
        p = run_abs / str(obj["path"])
        try:
            _run_rel(project, run_abs, p, what, within)
        except WitnessRefused as exc:
            return None, str(exc)
        if not p.is_file():
            return None, f"cited {what} {obj['path']} does not exist"
        if _sha256(p) != str(obj["sha256"]):
            return None, (f"cited {what} {obj['path']} no longer has the "
                          "sha256 the row cites")
        return p, ""

    fl = w.get("flow_log")
    if not isinstance(fl, dict) or fl.get("path") != "flow.log":
        return False, "the cited flow log is not the run directory's flow.log"
    size = fl.get("bytes")
    log_path = run_abs / "flow.log"
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        return False, "the flow-log citation pins no byte length"
    if not log_path.is_file() or log_path.is_symlink():
        return False, "the run directory's flow.log is missing"
    with log_path.open("rb") as fh:
        prefix = fh.read(size)
    if len(prefix) != size or "sha256:" + hashlib.sha256(prefix).hexdigest() \
            != str(fl.get("sha256")):
        return False, ("flow.log no longer begins with the bytes the row "
                       "cites")
    # Every check that needs no flow-log reader runs FIRST, so a reader that
    # may not judge can never turn a witness whose evidence is gone or
    # rewritten into NOT_MEASURED: that is a FAIL whatever the reader says.
    comp = w.get("completion")
    if not isinstance(comp, dict) or \
            comp.get("path") != f"{step_rel}/state_out.json":
        return False, "the witness cites no state_out.json of the step"
    p, why = _cited(comp, "completion record", step_abs)
    if p is None:
        return False, why
    logs = w.get("logs")
    if not isinstance(logs, list) or not logs:
        return False, "the witness cites no tool log"
    for obj in logs:
        p, why = _cited(obj, "step log", step_abs)
        if p is None:
            return False, why
    sources = w.get("sources")
    outputs = entry.get("outputs") or {}
    if not isinstance(sources, dict) or set(sources) != set(outputs):
        return False, "the witness does not name a source for every output"
    for canon, obj in sources.items():
        p, why = _cited(obj, "output source", step_abs)
        if p is None:
            return False, why
        if _bare(obj["sha256"]) != _bare(outputs[canon]):
            return False, (f"{canon} is declared with bytes other than its "
                           f"source {obj['path']}")
    # Only what the flow's own log says is left: started, not skipped, and
    # each cited log a transcript it names.
    block = step_block(prefix.decode("utf-8", errors="replace"),
                       step_id, step_rel)
    if block is None:
        return False, (f"the flow's own log never started {step_id!r} in "
                       f"{step_rel!r}")
    if block["skipped"]:
        return False, f"the flow's own log reports {step_id!r} skipped"
    named = block["subprocess_logs"]
    for obj in logs:
        if not any(_ends_with(parts, _parts(str(obj["path"])))
                   for parts in named):
            return False, (f"cited step log {obj['path']} is not a transcript "
                           "the flow's own log names for this step")
    return True, ""


def is_witnessed(entry: Dict[str, Any], project: Path) -> bool:
    """True only for a row whose witness re-verifies. A back-fill never is."""
    ok, _ = verify_witness(entry, project)
    return ok is True
