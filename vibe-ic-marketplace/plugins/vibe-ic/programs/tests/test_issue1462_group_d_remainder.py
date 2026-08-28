"""vibe-ic#1462 — the last two of group (d), converted and pinned.

WHAT #1462 LEFT OPEN
====================
#1462 reported group (d) as *17 programs newly writing a declared report
destination without `_atomic_artefact`*, and made two corrections to the brief:
the group attributes to FIFTEEN PRs rather than one, and two of the seventeen
(`hygiene_shard_plan.py`, `hygiene_shard_aggregate.py`) were already on main.
The gate's own half of the issue — that an ABSENT residual baseline is not a
measurement of zero — landed with `_load_baseline` returning None. The
CONVERSIONS did not all land with it. Measured on `2efa6af35`, thirteen had
arrived and two had not:

    [FAIL] 2 program(s) newly write a declared report destination without
    _atomic_artefact:
       generated_artifact_conflict_resolve.py:391  .write_text(...)
       hygiene_finding_delta.py:420  .write_text(...)

Both are landing-evidence writers: one records whether a merge was resolved or
REFUSED, the other records which hygiene findings a tree INTRODUCED. Those are
exactly the artefacts #1082 is about — a reader opens them to learn a verdict,
and under `.write_text` the final name is created before it is filled, so a
process that dies mid-write leaves a truncated record that no consumer can tell
from a complete one.

WHY THIS FILE IS NOT JUST `assert scan_program(...) == []`
==========================================================
That assertion is an AST fact about the source, and an AST fact can be bought
by editing the source into a shape the scanner does not recognise while the
artefact stays exactly as breakable as it was. So the load-bearing pair here is
a KILL pair on the REAL `main()` of each program, in the shape
`test_issue1082_atomic_artefact_naming` established:

    converted   kill mid-write -> the final name does NOT exist
    pre-fix     kill mid-write -> the final name DOES exist, truncated

The pre-fix arm is not a model of the old code. It is built by reverting THIS
REPO'S OWN FILE with the inverse of the edit that fixed it, asserted to apply
exactly once, so the red arm cannot rot into a no-op if the file moves. Only
the PAYLOAD is enlarged (the write site is what is under test, not the verdict
computation), because a two-hundred-byte write completes before any poll can
observe it and would make the pair prove nothing in either direction.

SIGKILL, not an exception: `writing()` catches `BaseException` and cleans up,
so an exception would be testing the cleanup path. SIGKILL is what no `finally`
covers and what an OOM kill or a torn-down process group actually sends — it
proves the guarantee comes from the RENAME.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

import json
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _atomic_artefact as AA  # noqa: E402
import atomic_artifact_write_check as G  # noqa: E402

#: The two sites #1462 left unconverted, each named with the call that now
#: carries it and the call `origin/main` carried before. The pre-fix text is
#: verbatim the idiom the gate flagged, re-wrapped onto one line.
CONVERSIONS = {
    "generated_artifact_conflict_resolve.py": (
        "write_json(a.json_out, v.to_dict(), ensure_ascii=True)",
        'Path(a.json_out).write_text(json.dumps(v.to_dict(), indent=2) + "\\n",'
        ' encoding="utf-8")',
    ),
    "hygiene_finding_delta.py": (
        "write_json(a.json, d, ensure_ascii=True)",
        'a.json.write_text(json.dumps(d, indent=2) + "\\n", encoding="utf-8")',
    ),
}

#: Big enough that the write is observably in progress. The kill is NOT timed:
#: the harness polls until a partial artefact is on disk and only then signals,
#: so this size sets how wide that window is, never whether the test is right.
PAYLOAD_MB = 64
PAYLOAD_BYTES = PAYLOAD_MB * 1024 * 1024

#: <= 60s: the landing harness runs --timeout=180 --timeout-method=thread, and
#: an inner bound at or above that turns one slow poll into a lost session.
POLL_BUDGET_S = 55


# --------------------------------------------------------------------------
# the pre-fix source, derived from the shipped file rather than transcribed
# --------------------------------------------------------------------------
def revert(name: str) -> str:
    """This repo's own file with the #1462 conversion undone.

    Every step asserts it applied. A revert that silently no-ops would make the
    red arm green for the wrong reason, which is the failure mode a red arm
    exists to be immune to.
    """
    src = (PROGRAMS / name).read_text(encoding="utf-8")
    atomic_call, pre_fix_call = CONVERSIONS[name]
    assert src.count(atomic_call) == 1, (
        f"{name} no longer carries the converted call {atomic_call!r}; this "
        f"control cannot be built from it")

    kept = [ln for ln in src.splitlines(keepends=True)
            if "from _atomic_artefact import" not in ln
            and "sys.path.insert(0, str(Path(__file__).resolve().parent))"
            not in ln]
    out = "".join(kept)
    assert len(out) < len(src), f"{name}: nothing was removed"
    assert "_atomic_artefact" not in out, f"{name}: helper import survived"

    out = out.replace(atomic_call, pre_fix_call)
    assert pre_fix_call in out, f"{name}: the pre-fix call was not restored"
    if "\nimport json\n" not in out:                 # only G dropped it
        out = out.replace("\nimport argparse\n", "\nimport argparse\nimport json\n", 1)
    assert "\nimport json\n" in out, f"{name}: json import missing"
    return out


#: `import _foo` / `from _foo import bar`, this repo's convention for a
#: sibling module in `programs/`. `_atomic_artefact` never matches through
#: this helper: it is excluded by name below, deliberately, so the isolation
#: `revert()` relies on cannot be reopened by a dependency that happens to sit
#: behind it in the import graph.
_SIBLING_IMPORT_RE = re.compile(r"^(?:import|from)\s+(_[A-Za-z0-9_]*)\b", re.MULTILINE)


def _stage_sibling_deps(src: str, moddir: Path, _seen: set[str] | None = None) -> None:
    """Copy every sibling `_*` module `src` (transitively) imports into moddir.

    #1462's isolation is specifically about `_atomic_artefact` — the reverted
    source must not be able to reach it. It says nothing about any OTHER
    sibling helper the module happens to import, and `_progress_run` (reached
    through `_watchdog`) is exactly that: a dependency `generated_artifact_
    conflict_resolve.py` gained after this fixture was written, absent from
    its one hand-typed exclusion, so the isolated child hit `ModuleNotFoundError`
    at import time — which the poll loop below could only see as "never
    observed a partial write", misattributing an import failure to the payload
    finishing too fast. Recursing (rather than copying one level) is what makes
    this survive the NEXT such addition too, instead of needing a second manual
    patch.
    """
    seen = _seen if _seen is not None else set()
    for m in _SIBLING_IMPORT_RE.finditer(src):
        mod = m.group(1)
        if mod == "_atomic_artefact" or mod in seen:
            continue
        seen.add(mod)
        dep = PROGRAMS / f"{mod}.py"
        if not dep.is_file():
            continue
        dep_src = dep.read_text(encoding="utf-8")
        shutil.copy2(dep, moddir / dep.name)
        _stage_sibling_deps(dep_src, moddir, seen)


# --------------------------------------------------------------------------
# GREEN ARM: the shipped tree
# --------------------------------------------------------------------------
def test_both_remaining_group_d_sites_are_converted():
    """The finding #1462 leaves open, gone — read through the gate's own
    scanner so this is the gate's opinion and not a grep's.

    Deliberately `scan_program` per name and NOT `main()` over the whole tree:
    a full audit parses 1168 programs (~52s wall measured, and far more on a
    loaded host), and running it twice here would add a second copy of
    `test_issue1082_atomic_tranche_40_gates::test_no_new_offender_and_the_
    ratchet_holds` that races the 180s harness bound. A test that TIMES OUT is
    neither a pass nor a failure, and one that can only be read as a verdict
    when the machine is quiet is not a verdict.
    """
    still = {n: G.scan_program(PROGRAMS / n) for n in CONVERSIONS}
    assert not any(still.values()), {k: v for k, v in still.items() if v}


# --------------------------------------------------------------------------
# RED ARM 1: the gate still refuses the pre-fix shape
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(CONVERSIONS))
def test_the_gate_still_refuses_the_pre_fix_shape(name, tmp_path, capsys):
    """Same gate, same baseline shape, source reverted -> rc 1 naming the file.

    Without this the green above is unfalsifiable: a gate that had been
    weakened into never firing would produce exactly the same PASS.
    """
    d = tmp_path / "programs"
    d.mkdir()
    (d / name).write_text(revert(name), encoding="utf-8")
    bl = tmp_path / "baseline.json"
    bl.write_text(json.dumps({"offenders": []}), encoding="utf-8")

    rc = G.main([str(d), "--baseline", str(bl)])
    err = capsys.readouterr().err
    assert rc == 1, f"the gate accepted the pre-fix shape of {name}"
    assert name in err and "_atomic_artefact" in err, err


# --------------------------------------------------------------------------
# RED/GREEN PAIR 2: the artefact itself, killed mid-write
# --------------------------------------------------------------------------
_PATCH = {
    # `main()` resolves the work tree, then the verdict. Both are replaced so
    # the run needs no git and no conflict; the WRITE is what is under test.
    "generated_artifact_conflict_resolve.py": (
        "import subprocess as _sp\n"
        "M._git = lambda root, *a, **k: _sp.CompletedProcess(\n"
        "    args=a, returncode=0, stdout=str(root) + '\\n', stderr='')\n"
        "M.resolve = lambda top, reg, dry_run=False: M.Verdict(0, PAYLOAD)\n"
    ),
    "hygiene_finding_delta.py": (
        "M.compare = lambda *a, **k: {'status': 'OK', 'pad': PAYLOAD}\n"
    ),
}


def _argv(name: str, tmp_path: Path, dest: Path) -> list[str]:
    if name == "generated_artifact_conflict_resolve.py":
        return ["--repo", str(tmp_path), "--json", str(dest)]
    return ["--base", str(tmp_path / "b.json"),
            "--candidate", str(tmp_path / "c.json"),
            "--base-host", "host-a", "--candidate-host", "host-a",
            "--json", str(dest)]


def _kill_mid_write(tmp_path: Path, name: str, arm: str):
    """Run the program's real `main()`, SIGKILL it once a partial is visible.

    Returns (final_exists, final_size, leftovers, killed_at).
    """
    mod = name[:-3]
    moddir = tmp_path / arm
    moddir.mkdir()
    # The GREEN arm imports the SHIPPED file itself — a copy could diverge and
    # the arm would then certify the copy. The RED arm imports the reverted
    # source, and imports ONLY it: `_atomic_artefact` is deliberately not
    # reachable from there, so the arm cannot silently fall back onto the
    # helper it is supposed to be running without.
    importdir = PROGRAMS if arm == "converted" else moddir
    if arm != "converted":
        reverted_src = revert(name)
        (moddir / name).write_text(reverted_src, encoding="utf-8")
        _stage_sibling_deps(reverted_src, moddir)

    dest = tmp_path / arm / "out" / "verdict.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    child = tmp_path / f"child_{arm}.py"
    child.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(importdir)!r})\n"
        f"import {mod} as M\n"
        f"assert M.__file__.startswith({str(importdir)!r}), M.__file__\n"
        f"PAYLOAD = 'x' * {PAYLOAD_BYTES}\n"
        + _PATCH[name]
        + f"raise SystemExit(M.main({_argv(name, tmp_path, dest)!r}))\n",
        encoding="utf-8")

    proc = subprocess.Popen([sys.executable, str(child)])
    watched = dest if arm == "pre_fix" else None
    killed_at = None
    deadline = time.time() + POLL_BUDGET_S
    try:
        while time.time() < deadline:
            if watched is None:
                cands = list(dest.parent.glob(dest.name + AA.TMP_SUFFIX + ".*"))
                if cands:
                    watched = cands[0]
            if watched is not None and watched.exists():
                size = watched.stat().st_size
                if 0 < size < PAYLOAD_BYTES:
                    proc.send_signal(signal.SIGKILL)
                    killed_at = size
                    break
            time.sleep(0.001)
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGKILL)
        proc.wait()

    # An empty result is not a zero: if the write finished before the poll
    # could signal, this run measured nothing and must say so rather than
    # report the absence (or presence) of a file as if it had been earned.
    assert killed_at is not None, (
        f"never observed a partial write for {name} arm={arm}; the "
        f"{PAYLOAD_MB}MB payload completed before the poll could signal, so "
        f"this run proves nothing either way")
    exists = dest.exists()
    return (exists,
            dest.stat().st_size if exists else None,
            sorted(p.name for p in
                   dest.parent.glob(dest.name + AA.TMP_SUFFIX + ".*")),
            killed_at)


@pytest.mark.timeout(120)
@pytest.mark.parametrize("name", sorted(CONVERSIONS))
def test_converted_a_killed_write_leaves_nothing_under_the_final_name(
        name, tmp_path):
    exists, size, leftovers, killed_at = _kill_mid_write(
        tmp_path, name, "converted")
    assert exists is False, (
        f"{name}: killed at {killed_at} bytes and the declared report still "
        f"exists (size={size})")
    # The partial is not merely invisible — it is NAMED, so a sweeper or a
    # human can attribute it instead of guessing from size or mtime.
    assert len(leftovers) == 1 and AA.is_temp_artefact(leftovers[0]), leftovers


@pytest.mark.timeout(120)
@pytest.mark.parametrize("name", sorted(CONVERSIONS))
def test_pre_fix_a_killed_write_leaves_a_truncated_report(name, tmp_path):
    """The red arm: the defect itself, on this repo's own reverted source.

    The declared report exists, is short, and is not parseable JSON — yet every
    presence predicate downstream reads it as "the step produced its output".
    """
    exists, size, leftovers, killed_at = _kill_mid_write(
        tmp_path, name, "pre_fix")
    assert exists is True, (
        f"{name}: expected the pre-fix idiom to leave a partial report "
        f"(killed at {killed_at} bytes)")
    assert size < PAYLOAD_BYTES, f"{name}: not actually truncated ({size})"
    assert leftovers == [], f"{name}: the pre-fix idiom writes no temp at all"
    with pytest.raises(ValueError):
        json.loads(dest_text(tmp_path, "pre_fix"))


def dest_text(tmp_path: Path, arm: str) -> str:
    return (tmp_path / arm / "out" / "verdict.json").read_text(
        encoding="utf-8", errors="replace")
