#!/usr/bin/env python3
"""Record the DRV stage receipts `drv_capture_plan._stages` reads.

DRV sign-off standard section 1 (owner-approved 2026-09-28) judges every
implementation stage by what the TOOL applied there: synthesis by the
`buffer -N` in the ABC script ABC executed, each OpenROAD stage by a
`write_sdc` taken in the stage's own process on the line before the stage
command, by `sta::max_fanout_check_limit` read at that point, and by a DRV
census after it.  This module produces exactly that and nothing else:

* ``drv_stage_probe.tcl`` is installed as the OpenROAD / OpenSTA init file of
  every LibreLane chain that runs a DRV stage step (``librelane_contract.
  run_chain``).  It wraps the stage command in the process that runs it and
  writes the tool's own files into ``<step dir>/vibeic_drv_stage/``.
* :func:`record_step` turns one step folder's probe files into the stage
  receipt ``reports/phase3/drv_stages/<stage>.json``: the path and sha256 of
  every evidence file, never a value.  The values are derived later, by the
  plan reader, from those hashed bytes.
* :func:`claim` binds the directory to one run instance.  Phase 3 calls it
  when a run starts: the directory is emptied and ``run.json`` names a fresh
  run id that every receipt carries; :func:`read_receipt` refuses a receipt
  whose id is not the current claim's.

A stage the flow did not run gets no evidence, so the judge reports it FAIL
("required stage absent" / "did not run"), never N/A.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shlex
import shutil
import sys
import uuid
from pathlib import Path
from typing import Dict, Iterable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_text  # noqa: E402

#: Where the receipts live (`drv_capture_plan.STAGE_RECEIPT_DIR`).
RECEIPT_DIR = Path("reports/phase3/drv_stages")
#: The run-instance claim inside RECEIPT_DIR.
CLAIM = "run.json"
#: Concatenated multi-invocation evidence written by this module.
EVIDENCE_DIR = "evidence"
#: The probe's folder inside a step folder.
PROBE_DIR = "vibeic_drv_stage"
PROBE_TCL = Path(__file__).resolve().parent / "drv_stage_probe.tcl"

#: LibreLane step id -> (DRV stage, the stage command the probe wraps there).
STAGE_STEPS: Dict[str, tuple] = {
    "OpenROAD.RepairDesignPostGPL": ("placement_repair", "repair_design"),
    "OpenROAD.CTS": ("cts", "clock_tree_synthesis"),
    "OpenROAD.RepairDesignPostGRT": ("post_grt_repair", "repair_design"),
    "OpenROAD.STAPostPNR": ("signoff_sta", "report_check_types"),
    "Vibeic.PostRouteRepair": ("postroute_repair", "repair_design"),
}

#: A probe file name: <command>.<corner|all>.<sequence>.<kind>
_TAG = re.compile(r"^(?P<command>[A-Za-z_]+)\.(?P<corner>[^.]+)\.(?P<seq>\d+)\."
                  r"(?P<kind>pre\.sdc|behavior\.rpt|args|clock_fanout|fanout_limits\.rpt"
                  r"|pin_cells|error)$")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def _ref(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": _sha(path)}


def probe_lines() -> List[str]:
    """The init-file lines that install the probe (its text, inline: a stock
    LibreLane step mounts no vibe-ic file)."""
    return PROBE_TCL.read_text().splitlines()


def probe_digest() -> str:
    return _sha(PROBE_TCL)


def chain_needs_probe(step_ids: Iterable[str]) -> bool:
    return any(step in STAGE_STEPS for step in step_ids)


# --- run instance --------------------------------------------------------------

def claim(project: Path) -> str:
    """Start a fresh active receipt set; retain every earlier set as history."""
    root = project / RECEIPT_DIR
    if root.exists():
        archive = project / "reports/phase3/drv_stage_history" / (
            "fresh-" + _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ"))
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(root), str(archive))
    # One run, one id: reuse the id `drv_run_identity.record` took at run
    # start (R-0929-DRV-IDENTITY), which the capture plan also binds.
    import drv_run_identity
    run_id = drv_run_identity.load(project).get("run_id")
    if not (isinstance(run_id, str) and re.fullmatch(r"[0-9a-f]{32}", run_id)):
        run_id = uuid.uuid4().hex
    write_text(root / CLAIM, json.dumps({
        "run_id": run_id,
        "claimed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "pid": os.getpid()}, indent=2) + "\n")
    return run_id


def current_run(project: Path) -> Optional[str]:
    path = project / RECEIPT_DIR / CLAIM
    try:
        value = json.loads(path.read_text()).get("run_id")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) else None


def invalidate_from_steps(project: Path, step_ids: Iterable[str]) -> List[str]:
    """Retain preceding checkpoints; rerun affected stages in canonical order.

    The historical bytes remain in an archive. Their live receipt is removed
    before a producer starts, so a failed retry cannot credit old output.
    """
    import _flow_yaml
    order = [str(row["id"]) for row in _flow_yaml.load()["steps"]]
    selected = [order.index(str(sid)) for sid in step_ids]
    if not selected:
        return []
    owners = {"synth": "9", "placement_repair": "17", "cts": "19",
              "post_grt_repair": "21", "postroute_repair": "32", "signoff_sta": "23"}
    affected = [name for name, sid in owners.items() if order.index(sid) >= min(selected)]
    root = project / RECEIPT_DIR
    archive = (project / "reports/phase3/drv_stage_history" /
               f"{current_run(project)}-{uuid.uuid4().hex}")
    for name in affected:
        receipt = root / f"{name}.json"
        evidence = root / EVIDENCE_DIR / name
        if not receipt.is_file() and not evidence.is_dir():
            continue
        archive.mkdir(parents=True, exist_ok=True)
        if receipt.is_file():
            shutil.copy2(receipt, archive / receipt.name)
            receipt.unlink()
        if evidence.is_dir():
            shutil.copytree(evidence, archive / EVIDENCE_DIR / name)
            shutil.rmtree(evidence)
    return affected


def read_receipt(project: Path, name: str) -> tuple[Optional[dict], str]:
    """The receipt of stage `name` when it belongs to the current run."""
    path = project / RECEIPT_DIR / f"{name}.json"
    if not path.is_file():
        return None, "absent"
    try:
        doc = json.loads(path.read_text())
    except ValueError:
        doc = None
    if not isinstance(doc, dict) or doc.get("name") != name:
        return None, "unreadable or names another stage"
    run_id = current_run(project)
    if run_id is None:
        return None, "no run claim in the receipt directory"
    if doc.get("run_id") != run_id:
        return None, "recorded by another run"
    return doc, "recorded"


def _write_receipt(project: Path, name: str, doc: dict) -> Optional[Path]:
    run_id = current_run(project)
    if run_id is None:
        return None  # not inside a claimed run: nothing to bind the receipt to
    path = project / RECEIPT_DIR / f"{name}.json"
    write_text(path, json.dumps({"name": name, "run_id": run_id, **doc},
                                indent=2) + "\n")
    return path


# --- evidence ------------------------------------------------------------------

def _probe_files(folder: Path, command: str) -> Dict[str, List[Path]]:
    """The probe files of `command` in one step folder, by kind, in
    (corner, sequence) order."""
    rows = []
    for path in (folder / PROBE_DIR).glob("*"):
        match = _TAG.match(path.name)
        if match and match.group("command") == command:
            rows.append((match.group("corner"), int(match.group("seq")),
                         match.group("kind"), path))
    kinds: Dict[str, List[Path]] = {}
    for _, _, kind, path in sorted(rows):
        kinds.setdefault(kind, []).append(path)
    return kinds


def _one_file(project: Path, name: str, kind: str, paths: List[Path]) -> dict:
    """One evidence file for the receipt: the tool's own file when it wrote
    one, else the tool's files concatenated in order, each under a comment
    naming its source and sha256 (bytes only ever copied, never edited)."""
    if len(paths) == 1:
        return _ref(paths[0])
    out = project / RECEIPT_DIR / EVIDENCE_DIR / name / f"{name}.{kind}"
    parts = []
    for path in paths:
        parts.append(f"# vibe-ic DRV stage evidence: {path.resolve()} sha256 {_sha(path)}\n")
        body = path.read_text(errors="replace")
        parts.append(body if body.endswith("\n") else body + "\n")
    write_text(out, "".join(parts))
    return _ref(out)


def record_step(project: Path, step_id: str, folder: Path, *,
                reused: bool = False) -> Optional[Path]:
    """Write the receipt of the DRV stage step `step_id` ran in `folder`."""
    if step_id not in STAGE_STEPS:
        return None
    name, command = STAGE_STEPS[step_id]
    files = _probe_files(folder, command)
    doc: dict = {"ran": True, "command": command,
                 "tool_step": {"id": step_id, "folder": str(folder.resolve()),
                               "reused_cached_step": bool(reused)},
                 "evidence": [_ref(p) for kind in sorted(files) for p in files[kind]]}
    if files.get("error"):
        doc["probe_errors"] = [p.read_text(errors="replace") for p in files["error"]]
    if files.get("behavior.rpt"):
        doc["behavior_report"] = _one_file(project, name, "behavior.rpt",
                                           files["behavior.rpt"])
    if files.get("pre.sdc"):
        doc["sdc_snapshot"] = _one_file(project, name, "pre.sdc", files["pre.sdc"])
    if files.get("args"):
        doc["command_args"] = _one_file(project, name, "args", files["args"])
    if files.get("fanout_limits.rpt"):
        doc["fanout_limit_report"] = _one_file(project, name, "fanout_limits.rpt",
                                               files["fanout_limits.rpt"])
    if files.get("pin_cells"):
        doc["pin_cell_report"] = _one_file(project, name, "pin_cells", files["pin_cells"])
    if files.get("clock_fanout"):
        doc["clock_fanout_report"] = _one_file(project, name, "clock_fanout",
                                               files["clock_fanout"])
    if not files:
        doc["ran"] = False
        doc["reason"] = (f"{step_id} ran in {folder} but the probe recorded no "
                         f"`{command}` call there")
    return _write_receipt(project, name, doc)


def record_not_run(project: Path, name: str, reason: str) -> Optional[Path]:
    """A required stage the flow did not run: the receipt names why."""
    return _write_receipt(project, name, {"ran": False, "reason": reason})


def record_chain(project: Path, steps: Iterable[tuple]) -> List[Path]:
    """Receipts for every DRV stage step of one finished chain: (step id,
    folder, reused) triples, in order (a later run of a stage replaces an
    earlier one)."""
    written = []
    for step_id, folder, reused in steps:
        path = record_step(project, step_id, Path(folder), reused=reused)
        if path is not None:
            written.append(path)
    return written


def rebind_lane(project: Path, lane_dir, stages: Iterable[str],
                arm: str) -> List[Path]:
    """After an arm selection: the receipts of `stages` come from the SELECTED
    arm, never from whichever arm ran last (review wave 58 DRVSTACK: seed arms,
    21-route-pregrt and a dual direct arm each rewrote the same receipt).

    `lane_dir` is the selected LibreLane arm's own (step id, folder) pairs, or
    its chain folder (run_chain names each step folder `NN-<step id>`); the
    last folder of a stage's step is its run. A selected arm with no chain (a
    direct arm, which carries no probe) or whose chain lacks the stage records
    the stage as not run, naming the arm: section 1 then reads FAIL "did not
    run", never another arm's row."""
    by_folder = {sid.lower().replace(".", "-"): sid for sid in STAGE_STEPS}
    found: Dict[str, tuple] = {}
    if lane_dir is not None and not isinstance(lane_dir, (str, Path)):
        for sid, folder in lane_dir:
            if sid in STAGE_STEPS:
                found[STAGE_STEPS[sid][0]] = (sid, Path(folder))
        lane_dir = Path(next(iter(found.values()))[1]).parent if found else "the arm's chain"
    elif lane_dir is not None and Path(lane_dir).is_dir():
        for folder in sorted(Path(lane_dir).iterdir()):
            head, _, tail = folder.name.partition("-")
            sid = by_folder.get(tail)
            if folder.is_dir() and head.isdigit() and sid:
                found[STAGE_STEPS[sid][0]] = (sid, folder)
    written = []
    for name in stages:
        if name in found:
            path = record_step(project, found[name][0], found[name][1])
        else:
            where = (f"chain {Path(lane_dir).name}" if lane_dir is not None
                     else "a direct arm with no DRV stage probe")
            path = record_not_run(project, name,
                                  f"the selected arm {arm} ({where}) has no {name} step")
        if path is not None:
            written.append(path)
    return written


# --- synthesis -------------------------------------------------------------------

#: yosys `abc -showtmp` names the script ABC ran; `<abc-temp-dir>` is a run
#: whose directory yosys did not keep (e.g. `synth`'s own internal ABC pass).
_ABC_SCRIPT = re.compile(r"(?m)^Running ABC script: (?!<abc-temp-dir>)(\S+/abc\.script)\s*$")


def abc_script_path(project: Path) -> Path:
    """Where this run keeps the script its synthesis ABC call executed (inside
    the claimed directory, so an earlier run's copy cannot survive a claim)."""
    return project / RECEIPT_DIR / EVIDENCE_DIR / "synth" / "abc.script"


def abc_source_names(script: str) -> List[str]:
    """The source commands in a native ABC script, excluding echoed commands."""
    names = []
    for command in re.split(r"[;\n]", script):
        if not re.match(r"^\s*source\s+", command):
            continue
        words = shlex.split(command, comments=True)
        if len(words) == 2 and words[0] == "source":
            names.append(words[1])
    return names


def keep_abc_script(project: Path, synth_dir: Path, log_text: str) -> Optional[Path]:
    """Copy the script the mapping ABC call ran (the last one the yosys log
    names) into the run's evidence and drop yosys's kept temp folders."""
    target = abc_script_path(project)
    target.unlink(missing_ok=True)
    sources_index = target.with_name("abc_sources.json")
    sources_index.unlink(missing_ok=True)
    names = _ABC_SCRIPT.findall(log_text)
    kept = None
    if names and current_run(project) is not None:
        source = Path(names[-1])
        source = source if source.is_absolute() else synth_dir / source
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            # LibreLane's wrapper sources its generated mapping recipe. Keep
            # those exact bytes before cleaning up the Yosys temporary files.
            sources = []
            pending = abc_source_names(source.read_text())
            seen = set()
            while pending:
                name = pending.pop(0)
                if name in seen:
                    continue
                seen.add(name)
                leaf = Path(name)
                leaf = leaf if leaf.is_absolute() else synth_dir / leaf
                ref = None
                if leaf.is_file():
                    copy = target.with_name(f"abc_source_{len(sources)}.script")
                    shutil.copyfile(leaf, copy)
                    ref = _ref(copy)
                    pending.extend(abc_source_names(copy.read_text()))
                sources.append({"source": name, "script": ref})
            sources_index.write_text(json.dumps(sources, indent=2) + "\n")
            kept = target
    for folder in synth_dir.glob("_tmp_yosys-abc-*"):
        shutil.rmtree(folder, ignore_errors=True)
    return kept


def synth_census_tcl(*, liberties: List[str], netlist: str, top: str, sdc: str,
                     probe: str, out: str) -> str:
    """OpenSTA deck for the post-synthesis census (container paths)."""
    lines = [f"source {{{probe}}}"]
    lines += [f"read_liberty {{{lib}}}" for lib in liberties]
    lines += [f"read_verilog {{{netlist}}}", f"link_design {{{top}}}",
              f"read_sdc {{{sdc}}}", f"::vibeic_drv::synth_census {{{out}}}"]
    return "\n".join(lines) + "\n"


def record_synth(project: Path, *, abc_script: Optional[Path],
                 behavior: Optional[Path], netlist: Path, sdc: Path) -> Optional[Path]:
    """The synth receipt: the script ABC executed and the census of the
    netlist it produced."""
    doc: dict = {"ran": abc_script is not None,
                 "netlist": _ref(netlist) if netlist.is_file() else None,
                 "census_sdc": _ref(sdc) if sdc.is_file() else None}
    if abc_script is not None and abc_script.is_file():
        doc["abc_script"] = _ref(abc_script)
        sources_index = abc_script.with_name("abc_sources.json")
        if sources_index.is_file():
            doc["abc_sources"] = json.loads(sources_index.read_text())
    else:
        doc["reason"] = "the synthesis log names no ABC script ABC ran"
    if behavior is not None and behavior.is_file():
        doc["behavior_report"] = _ref(behavior)
    return _write_receipt(project, "synth", doc)


def synth_stage_supervised(project: Path, *, netlist: Path, top: str,
                           liberties: List[str], sdc: Path,
                           to_container, execute) -> Optional[Path]:
    """Bind supervision to the census producer's own generated deck and log.

    `execute(cmd, marker=..., log_path=...)` runs the tool through the caller's
    existing supervisor. The marker uses the mapped container deck path; the
    log remains a host Path. The underlying synth_stage API and receipts stay
    the same.
    """
    evidence = abc_script_path(project).parent
    return synth_stage(
        project, netlist=netlist, top=top, liberties=liberties, sdc=sdc,
        to_container=to_container,
        execute=lambda cmd: execute(
            cmd, marker=to_container(evidence / "census.tcl"),
            log_path=evidence / "census.log"))


def synth_stage(project: Path, *, netlist: Path, top: str, liberties: List[str],
                sdc: Path, to_container, execute) -> Optional[Path]:
    """Take the post-synthesis census in the EDA container (`execute(cmd)` ->
    (rc, out, err); `to_container(path)` maps a host path) and write the
    synth receipt.  Outside a claimed run nothing is written."""
    if current_run(project) is None:
        return None
    abc = abc_script_path(project)
    evidence = abc.parent
    evidence.mkdir(parents=True, exist_ok=True)
    behavior = evidence / "behavior.rpt"
    behavior.unlink(missing_ok=True)
    if netlist.is_file() and sdc.is_file():
        probe = evidence / "drv_stage_probe.tcl"
        probe.write_text(PROBE_TCL.read_text())
        deck = evidence / "census.tcl"
        deck.write_text(synth_census_tcl(
            liberties=[to_container(lib) for lib in liberties],
            netlist=to_container(netlist), top=top, sdc=to_container(sdc),
            probe=to_container(probe), out=to_container(behavior)))
        rc, out, err = execute(f"sta -no_init -no_splash -exit {to_container(deck)}")
        write_text(evidence / "census.log", f"rc={rc}\n{out}\n{err}")
        if rc:
            behavior.unlink(missing_ok=True)
    return record_synth(project, abc_script=abc if abc.is_file() else None,
                        behavior=behavior if behavior.is_file() else None,
                        netlist=netlist, sdc=sdc)


# --- step 32 ---------------------------------------------------------------------

def record_step32(project: Path, report: dict) -> List[Path]:
    """Re-bind sign-off STA and post-route repair to the state step 32 left:
    the final STAPostPNR folder, and the adopted candidate's repair folder."""
    written = []
    final = (report.get("final") or {}).get("sta_state")
    if final:
        path = record_step(project, "OpenROAD.STAPostPNR", Path(final).parent)
        if path is not None:
            written.append(path)
    adopted = report.get("adopted_state")
    if report.get("adopted") and adopted:
        path = record_step(project, "Vibeic.PostRouteRepair", Path(adopted).parent)
        if path is not None:
            written.append(path)
    return written
