#!/usr/bin/env python3
"""Retain timestamped, independent per-step output versions.

`steps/<phase>/<stage>/<id>_<slug>_<UTC timestamp>/` contains actual copies,
not links to mutable working files. Every old folder remains available.
The canonical phaseN paths stay in place for existing EDA consumers.

`materialize` is a dashboard observation, never a new executed PASS.
`begin_step` / `finish_step` retain actual invocation evidence, including
failed attempts. `latest_pass.json` advances only after the existing complete
canonical consumer accepts the invocation. Input hashes come from the caller's
resolved manifest; historical PASS and current-input PASS remain distinct.

Scope: one local machine, one sequential runner. No candidate scheduler.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path


_ACTIVE_LOCAL_CALLS = set()
_ACTIVE_LOCAL_ENV = 'VIBEIC_LOCAL_ACTIVE_STEP_FOLDERS'


def _active_local_calls():
    """A sequential runner's child programs inherit its unfinished call stack."""
    try:
        inherited = json.loads(os.environ.get(_ACTIVE_LOCAL_ENV, '[]'))
    except ValueError:
        inherited = []
    return _ACTIVE_LOCAL_CALLS | {folder for folder in inherited if isinstance(folder, str)}


@contextmanager
def active_steps(project: Path, attempts):
    """A nested function call must not recover its still-running parent.

    This in-process call stack is local and sequential. After an exception or
    process exit, unfinished journals remain eligible for normal recovery.
    """
    project = Path(project).resolve()
    folders = {str((project / a.get('storage_root', 'steps') / a['folder']).resolve())
               for a in attempts}
    added = folders - _ACTIVE_LOCAL_CALLS
    _ACTIVE_LOCAL_CALLS.update(added)
    previous = os.environ.get(_ACTIVE_LOCAL_ENV)
    os.environ[_ACTIVE_LOCAL_ENV] = json.dumps(sorted(_active_local_calls()))
    try:
        yield
    finally:
        _ACTIVE_LOCAL_CALLS.difference_update(added)
        if previous is None:
            os.environ.pop(_ACTIVE_LOCAL_ENV, None)
        else:
            os.environ[_ACTIVE_LOCAL_ENV] = previous
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", name or "").strip("_").lower()
    return (s[:48] or "step")


def _safe_id(sid: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", sid or "") or "x"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _version_folder(steps_root: Path, phase: str, stage: str,
                    sid: str, name: str) -> str:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    base = Path(phase or 'phase') / (stage or 'stage') / f'{_safe_id(sid)}_{_slug(name)}_{stamp}'
    folder = base
    number = 0
    while (steps_root / folder).exists():
        number += 1
        folder = Path(str(base) + f'_{number}')
    (steps_root / folder).mkdir(parents=True)
    return str(folder)


def _copy_outputs(project: Path, sdir: Path, outputs) -> Tuple[list, list]:
    """Copy bytes, never aliases to a mutable working file. Keep empty files too."""
    present, errors = [], []
    for output in outputs:
        src = Path(str(output.get('abs') or ''))
        if not output.get('exists') or not src.is_file():
            continue
        target = sdir / src.name
        if target.exists():
            target = sdir / f'{src.parent.name}__{src.name}'
        number = 0
        base = target
        while target.exists():
            number += 1
            target = base.with_name(f'{base.name}__{number}')
        try:
            shutil.copy2(src, target)
            present.append({'rel': output.get('rel'), 'abs': str(src),
                            'size': target.stat().st_size,
                            'snapshot': target.name, 'sha256': _sha(target)})
        except OSError as exc:
            errors.append(f'{src}: {exc}')
    return present, errors


def _working_files(project: Path) -> dict:
    """One local sequential attempt: observe writes, excluding retained history."""
    records = {}
    for root, dirs, files in os.walk(project):
        dirs[:] = [name for name in dirs if name not in
                   ('steps', 'step_versions', '.git', '__pycache__', '.pytest_cache', 'node_modules')]
        for name in files:
            path = Path(root) / name
            if path.is_symlink():
                continue
            try:
                info = path.stat()
                records[str(path.relative_to(project))] = (
                    info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            except OSError:
                continue
    return records


def _freeze_legacy(steps_root: Path, rows) -> None:
    """Save the bytes still reachable through a pre-versioning view."""
    for row in rows:
        if not row.get('folder'):
            continue
        folder = steps_root / row['folder']
        if not folder.is_dir() or not folder.resolve().is_relative_to(steps_root):
            continue
        for alias in folder.iterdir():
            if alias.is_symlink() and alias.is_file():
                # Replace the alias atomically, not its mutable target.
                temporary = alias.with_name(alias.name + '.freeze')
                shutil.copy2(alias, temporary)
                os.replace(temporary, alias)


def _versions_root(project: Path) -> Path:
    """Keep outputs even when a legacy file blocks the optional steps/ view."""
    steps = project / 'steps'
    fallback = project / 'reports/step_versions'
    return fallback if fallback.exists() or (steps.exists() and not steps.is_dir()) else steps


def _recover_unfinished(project: Path) -> None:
    """Close the previous local invocation before ANY next producer writes."""
    steps_root = _versions_root(project)
    active = _active_local_calls()
    for journal in steps_root.glob('*/*/*/attempt.json'):
        if str(journal.parent.resolve()) in active:
            continue
        if (journal.parent / 'outputs.json').exists():
            continue
        unfinished = json.loads(journal.read_text())
        saved = finish_step(project, unfinished, verdict='INTERRUPTED',
                            result={'detail': 'previous local invocation did not finish'})
        if saved['capture_errors']:
            raise OSError('interrupted step output could not be retained: ' +
                          '; '.join(saved['capture_errors']))


def _copy_inputs(project: Path, sdir: Path, inputs) -> Tuple[list, list]:
    """Keep the bytes of the caller's resolved manifest, without resolving it again."""
    files, errors = [], []
    for rel, identity in (inputs or {}).items():
        source, target = project / rel, sdir / 'inputs' / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            digest = _sha(target)
            expected = identity.get('sha256') if isinstance(identity, dict) else identity
            if digest != expected:
                errors.append(f'input {rel}: copied bytes differ from resolved input hash')
            files.append({'rel': rel, 'snapshot': str(target.relative_to(sdir)),
                          'size': target.stat().st_size, 'sha256': digest})
        except OSError as exc:
            errors.append(f'input {rel}: {exc}')
    return files, errors


def _begin_step(project: Path, step_id: str, inputs=None) -> dict:
    """Allocate one member of an already-recovered local invocation."""
    project = Path(project).resolve()
    sid = str(step_id)
    record = next((r for r in _iter_step_records(project) if r[0] == sid), None)
    if record is None:
        raise ValueError(f'unknown canonical step: {sid}')
    _, name, _, phase, stage, outputs = record
    steps_root = _versions_root(project)
    steps_root.mkdir(parents=True, exist_ok=True)
    folder = _version_folder(steps_root, phase, stage, sid, name)
    attempt = {'id': sid, 'name': name, 'phase': phase, 'stage': stage,
               'folder': folder, 'status': 'RUNNING', 'inputs': dict(inputs or {}),
               'storage_root': str(steps_root.relative_to(project)),
               'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    # Preserve pre-existing declared bytes, including checkpoints predating
    # this policy. They remain input history, never a newly claimed output.
    previous = steps_root / folder / 'before'
    previous.mkdir()
    previous_outputs, errors = _copy_outputs(project, previous, outputs)
    write_json(previous / 'outputs.json', {'outputs': previous_outputs, 'capture_errors': errors})
    input_files, input_errors = _copy_inputs(project, steps_root / folder, inputs)
    attempt['input_files'] = input_files
    attempt['capture_errors'] = errors + input_errors
    attempt['_before'] = {rel: list(info) for rel, info in _working_files(project).items()}
    write_json(steps_root / folder / 'attempt.json', attempt)
    return attempt


def begin_steps(project: Path, steps) -> list:
    """Start one local call's rows together, without interrupting its own siblings.

    Each member is `(step_id, resolved_input_manifest)`. Recovery happens
    once before allocation, so a previous call's partial bytes are saved
    before this call can overwrite them.
    """
    project = Path(project).resolve()
    _recover_unfinished(project)
    # A following step can overwrite a preceding step's canonical working
    # file too. Freeze all reachable legacy aliases before any new call.
    _freeze_legacy(_versions_root(project), _read_index(project).get('steps', []))
    attempts = [_begin_step(project, sid, inputs) for sid, inputs in steps]
    errors = [error for attempt in attempts for error in attempt['capture_errors']]
    if errors:
        for attempt in attempts:
            finish_step(project, attempt, verdict='NOT_MEASURED',
                        result={'detail': 'invocation input/output history could not be retained'})
        raise OSError('step input/output history could not be retained: ' + '; '.join(errors))
    return attempts


def begin_step(project: Path, step_id: str, inputs=None) -> dict:
    """Start one local sequential row using the caller's resolved input manifest."""
    return begin_steps(project, [(step_id, inputs)])[0]


def _read_index(project: Path) -> dict:
    try:
        return json.loads((_versions_root(project) / 'index.json').read_text())
    except (OSError, ValueError):
        return {'steps': []}


def publish_producer_outputs(project: Path, attempt: dict) -> dict:
    """Give the consumer this attempt's observed writes before it runs.

    The existing ledger observes the declared files; the producer's current
    receipts still establish execution/content authority. Publishing a RUNNING
    index cannot advance latest_pass or replace an older version's record.
    """
    import step_write_ledger as ledger
    project = Path(project).resolve()
    steps_root = project / attempt.get('storage_root', 'steps')
    folder = steps_root / attempt['folder']
    if (folder / 'outputs.json').exists() or (folder / 'written.json').exists():
        raise ValueError('step producer outputs already published or finished')
    sid = str(attempt['id'])
    record = next(row for row in ledger.build(project)['steps'] if str(row['id']) == sid)
    write_json(folder / 'written.json', record)
    index = _read_index(project)
    row = {key: attempt[key] for key in ('id', 'name', 'phase', 'stage', 'folder', 'status')}
    row.update(versioned=True)
    index['steps'] = [row] + [r for r in index.get('steps', []) if str(r.get('id')) != sid]
    write_json(steps_root / 'index.json', index)
    return record


def finish_step(project: Path, attempt: dict, *, verdict: str,
                result=None, canonical_pass: bool = False) -> dict:
    """Retain every outcome. Only the existing complete step verdict advances PASS.

    Runner/component PASS alone is insufficient: its owner must supply
    `canonical_pass` after its unchanged canonical consumer has accepted it.
    """
    project = Path(project).resolve()
    steps_root = project / attempt.get('storage_root', 'steps')
    sdir = steps_root / attempt['folder']
    if (sdir / 'outputs.json').exists():
        raise ValueError('step version already finished')
    sid = attempt['id']
    outputs = next(r[5] for r in _iter_step_records(project) if r[0] == sid)
    present, errors = _copy_outputs(project, sdir, outputs)
    before = attempt.get('_before', {})
    changed = [rel for rel, info in _working_files(project).items()
               if before.get(rel) != list(info)]
    files = []
    for rel in changed:
        src, target = project / rel, sdir / 'files' / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            files.append({'rel': rel, 'snapshot': str(target.relative_to(sdir)),
                          'size': target.stat().st_size, 'sha256': _sha(target)})
        except OSError as exc:
            errors.append(f'{rel}: {exc}')
    record = {key: value for key, value in attempt.items() if not key.startswith('_')}
    record.update(status=str(verdict), outputs=present, written_files=files,
                  result=result, canonical_pass=bool(canonical_pass and verdict == 'PASS'),
                  capture_errors=attempt.get('capture_errors', []) + errors,
                  finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    if record['capture_errors']:
        record['canonical_pass'] = False
    write_json(sdir / 'outputs.json', record)
    index = _read_index(project)
    row = {key: record[key] for key in ('id', 'name', 'phase', 'stage', 'folder', 'status')}
    row.update(n_outputs=len(present), versioned=True)
    index['steps'] = [row] + [r for r in index.get('steps', []) if str(r.get('id')) != sid]
    write_json(steps_root / 'index.json', index)
    if record['canonical_pass']:
        path = steps_root / 'latest_pass.json'
        try:
            passes = json.loads(path.read_text())
        except FileNotFoundError:
            passes = {'steps': {}}
        passes['steps'][sid] = {'folder': attempt['folder'], 'inputs': record['inputs'],
                              'finished_at': record['finished_at']}
        write_json(path, passes)
    return record


def latest_pass(project: Path, step_id: str) -> dict | None:
    """Return historical PASS with an explicit current-input flag, not guessed freshness."""
    project = Path(project).resolve()
    try:
        steps_root = _versions_root(project)
        passes = json.loads((steps_root / 'latest_pass.json').read_text())
        pointer = passes['steps'][str(step_id)]
        record = json.loads((steps_root / pointer['folder'] / 'outputs.json').read_text())
    except (OSError, ValueError, KeyError):
        return None
    # No resolved input identity means freshness was not measured. A
    # historical canonical PASS must not become current by all({}) alone.
    record['current_inputs'] = bool(pointer.get('inputs')) and all(
        (project / rel).is_file() and _sha(project / rel) ==
        (value.get('sha256') if isinstance(value, dict) else value)
        for rel, value in pointer.get('inputs', {}).items())
    return record


def current_acceptance(project: Path, started_at: float) -> list:
    """Latest complete consumers since this sequential phase invocation began.

    Read the versions, not the view index: an enclosing partial observation
    can update that index after a complete consumer has already refused.
    The local sequential invocation window is the owner; dashboard phase
    labels do not determine which child process executed a fractional row.
    """
    latest = {}
    for path in _versions_root(Path(project).resolve()).glob('*/*/*/outputs.json'):
        record = json.loads(path.read_text())
        result = record.get('result') or {}
        if not isinstance(result, dict):
            continue
        consumer = result.get('canonical_consumer')
        if not isinstance(consumer, dict):
            consumer = result.get('canonical_step_result')
            if not isinstance(consumer, dict):
                continue
        began = datetime.datetime.fromisoformat(record['started_at']).timestamp()
        if began < started_at:
            continue
        ended = datetime.datetime.fromisoformat(record['finished_at']).timestamp()
        sid = str(record['id'])
        if sid not in latest or ended > latest[sid][0]:
            latest[sid] = (ended, record)
    return [item[1] for sid, item in sorted(latest.items())]


def _unchanged_invocation(project: Path, prior: dict, outputs) -> bool:
    """A dashboard refresh is not another invocation or another gate verdict."""
    try:
        record = json.loads((project / 'steps' / prior['folder'] / 'outputs.json').read_text())
    except (OSError, ValueError, KeyError):
        return False
    if 'canonical_pass' not in record:
        return False
    expected = {item['rel']: item['sha256'] for item in record['outputs']}
    current = {item.get('rel'): _sha(Path(item['abs'])) for item in outputs
               if item.get('exists') and Path(item.get('abs') or '').is_file()}
    return current == expected


def _iter_step_records(project: Path):
    """Yield (id, name, status, phase, stage, [output entries]) using the SAME
    data source as the dashboard (flow_dashboard_data.collect — never raises).
    `stage` is the step's own yaml stage id; a step lacking one (should not
    happen for a real flow node) falls back to "stage" so nesting never
    silently collapses two unrelated steps into the same directory.

    `live=False` IS LOAD-BEARING. Everything this module produces is a FILE --
    steps/index.json and a per-step outputs.json -- and a file is read later
    than it was written. `flow_dashboard_data`'s "running" is a claim about the
    instant of the query (an output touched within `_RUNNING_WINDOW_S`), so
    freezing it into a durable record produces a step that says "in progress"
    forever and can never say whether it finished or died. MEASURED on a
    3-problem VerilogEval-Human run whose runner had already exited: step D1
    was recorded "running" in two of the three projects -- both were missing
    exactly one of D1's nineteen declared outputs while a sibling output had
    been written seconds earlier, and the third, which wrote all nineteen, was
    recorded "pass". live=False makes the record state a finished observation
    ("partial", with the count) instead of an unfinishable one; it does NOT
    turn an incomplete step into a passing one."""
    import flow_dashboard_data as fdd
    data = fdd.collect(project, live=False)
    for ph in data.get("phases", []):
        pkey = ph.get("key", "")
        for st in ph.get("steps", []):
            yield (str(st.get("id", "")), str(st.get("name", "")),
                   str(st.get("status", "")), pkey,
                   str(st.get("stage") or "stage"),
                   st.get("retention_outputs", st.get("outputs", [])) or [])


def _prune_stale_folders(steps_root: Path, old_folders: List[str],
                          new_folders: set) -> None:
    """Compatibility entry point: historical step versions are never pruned."""
    return None


def materialize(project: Path, only_steps=None) -> Dict[str, Any]:
    """Build the steps view. `only_steps` (a set of canonical step ids) limits
    the REFRESH to those steps, for a run that declared a window.

    WHY A WINDOWED REFRESH IS NOT A WINDOWED VIEW. A run that dispatched step 4
    alone has nothing new to say about the other 69 steps, and rebuilding their
    folders spends the whole flow's collection cost to restate what was already
    on disk — MEASURED: 139 of the 432 files a `--entry-step 4 --exit-step 4`
    run wrote outside step 4 were this tree. But the VIEW must still describe
    the whole flow, because a reader opening `steps/` after a bounded run is
    entitled to the same tree they had before it. So a windowed call:
      * materializes folders ONLY for the steps in the window;
      * CARRIES every other row from the prior index unchanged, marked
        `refreshed_here: false`, instead of dropping it;
      * does NOT prune, because outside the window this call has no opinion
        about which folders are stale, and pruning on a partial view would
        delete the rest of the flow's tree.
    Whole-flow refreshes also preserve every earlier version. Observations do
    not advance the executed PASS selection."""
    project = Path(project).expanduser().resolve()
    steps_root = project / "steps"
    steps_root.mkdir(parents=True, exist_ok=True)
    window = None if only_steps is None else {str(s) for s in only_steps}

    prior_index_path = steps_root / "index.json"
    prior_folders: List[str] = []
    prior_rows: List[Dict[str, Any]] = []
    if prior_index_path.is_file():
        try:
            prior = json.loads(prior_index_path.read_text())
            prior_rows = [s for s in prior.get("steps", []) if isinstance(s, dict)]
            prior_folders = [s.get("folder", "") for s in prior_rows
                             if s.get("folder")]
        except Exception:
            prior_folders = []
            prior_rows = []

    index: List[Dict[str, Any]] = []
    new_folders: set = set()
    skipped_ids: List[str] = []
    _freeze_legacy(steps_root, [row for row in prior_rows
                               if window is None or str(row.get('id')) in window])
    prior_by_id = {str(row.get('id')): row for row in prior_rows}

    for sid, name, status, phase, stage, outputs in _iter_step_records(project):
        if window is not None and str(sid) not in window:
            skipped_ids.append(str(sid))
            continue
        prior = prior_by_id.get(sid)
        if prior and _unchanged_invocation(project, prior, outputs):
            index.append(dict(prior))
            new_folders.add(prior['folder'])
            continue
        # `phase` is drawn from flow_dashboard_data's fixed 6-entry _PHASES
        # table and `stage` defaults to "stage" in _iter_step_records — never
        # empty in practice — but a path built from external data must not
        # silently collapse a segment if it ever is.
        folder = _version_folder(steps_root, phase, stage, sid, name)
        new_folders.add(folder)
        sdir = steps_root / folder
        present, errors = _copy_outputs(project, sdir, outputs)

        (sdir / "outputs.json").write_text(json.dumps(
            {"id": sid, "name": name, "status": status, "phase": phase,
             "stage": stage, "folder": folder, "outputs": present,
             "versioned": True, "observation_only": True,
             "capture_errors": errors},
            indent=2) + "\n")
        index.append({"id": sid, "name": name, "status": status, "phase": phase,
                      "stage": stage, "folder": folder,
                      "n_outputs": len(present), "versioned": True})

    if window is None:
        _prune_stale_folders(steps_root, prior_folders, new_folders)
        payload: Dict[str, Any] = {"steps": index}
    else:
        # CARRY, do not drop. A row this call did not refresh is still a true
        # record of what is on disk for that step; saying nothing about it
        # would turn a bounded refresh into a deletion of the view.
        fresh_ids = {str(r.get("id")) for r in index}
        carried = [dict(r, refreshed_here=False) for r in prior_rows
                   if str(r.get("id")) not in fresh_ids]
        payload = {"steps": [dict(r, refreshed_here=True) for r in index] + carried,
                   "refreshed_steps": sorted(fresh_ids),
                   "not_refreshed_here": sorted(str(r.get("id")) for r in carried)}

    (steps_root / "index.json").write_text(
        json.dumps(payload, indent=2) + "\n")

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

    res: Dict[str, Any] = {
        "steps_root": str(steps_root), "n_steps": len(index),
        "n_with_outputs": sum(1 for s in index if s["n_outputs"] > 0),
        "write_ledger": ledger}
    if window is not None:
        res["bounded_to"] = sorted(window)
        res["n_not_refreshed"] = len(skipped_ids)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--only-steps", default=None,
                    help="Comma-separated canonical step ids: refresh ONLY "
                         "these steps' folders and carry every other row from "
                         "the prior index unchanged. For a run that declared "
                         "--entry-step/--exit-step. Omitted: whole-flow build.")
    a = ap.parse_args(argv)
    only = None
    if a.only_steps:
        only = {s.strip() for s in a.only_steps.split(",") if s.strip()}
        if not only:
            print("REFUSED: --only-steps was given but names no step id",
                  file=sys.stderr)
            return 2
    res = materialize(a.project, only_steps=only)
    txt = json.dumps(res, indent=2)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(txt + "\n")
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
