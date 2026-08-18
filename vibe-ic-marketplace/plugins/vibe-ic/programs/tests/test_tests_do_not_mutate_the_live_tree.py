#!/usr/bin/env python3
"""A test may not write into the tree its neighbours are reading.

THE DEFECT
==========
Thirteen shipped test files created files inside the live ``programs/`` tree
while they ran — a probe gate, a crashing helper, a throwaway program, a test
module, a scratch directory — and one of them moved a SHIPPED program aside for
the length of its body. Every one cleaned up in a ``finally`` or a fixture, so
run serially none of it is observable.

The landing gate does not run them serially. ``pytest_per_file_junit.py``'s
recovery path runs one pytest session per file, many at a time, over ONE shared
checkout. For the whole body of such a test every concurrent session sees a
``programs/`` tree that is not the commit's, and the suite is full of gates
whose entire job is to ENUMERATE that tree and compare the count against a
recorded one:

    tools/gen_programs_index.py --check      INDEX.md vs programs/*.py
    plugin_full_audit.py                     every program has a test (D1)
    gate_skip_routing_check.py               inventory vs measured
    gate_discloses_denominator_check.py      every programs/*_check.py
    flow_gate_enforcement_audit.py           every gate in the flow
    ci_targeted_test_select.py               the glob-consumer edge

Those gates then report the difference as a finding about the BRANCH. It is the
same defect class they exist to catch, one level up: whether this tree is the
commit's could not be determined, the answer was assumed, and the assumption
was published as a measurement.

WHY IT WAS SO HARD TO SEE
=========================
The cleanup. An earlier explanation for a set of parallel-only failures — "the
parallel wave dirties the tree" — was WITHDRAWN because ``git status
--porcelain`` came back empty after a 16-wide run. It comes back empty by
construction: the plant is created and removed inside one test body, so the
window in which it exists is a window in which nothing samples git. A plant
that git never sees and a scanner does is exactly the shape that fits both
observations.

WHAT THIS TEST DOES
===================
It re-runs each formerly-planting file in a child pytest whose interpreter
carries a ``sys.addaudithook`` recording every write BELOW ``programs/``, and
requires zero. The hook is installed through ``sitecustomize`` on ``PYTHONPATH``
so it also covers the child processes those tests spawn, which is where several
of the plants actually happened.

NEGATIVE CONTROL, first and mandatory: a synthetic test file that DOES plant is
run through the same instrument and must be caught. Without it a broken hook
would report "no plants" over a tree full of them, which is this file's own
version of the defect it is about.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
_PLUGIN = _PROGRAMS.parent

#: The files repaired when this guard landed. A file is listed here because it
#: USED to plant, so the entry is a standing statement that it no longer does —
#: not a permission. Adding a name here does not silence anything: the
#: assertion is the same for every file, which is zero writes.
FORMERLY_PLANTED = (
    "test_ensure_extracted_docs.py",
    "test_flow_compliance_check_gate.py",
    "test_gate_discloses_denominator.py",
    "test_gate_skip_routing_check.py",
    "test_issue1387_glob_consumers_are_selected.py",
    "test_issue538_merge_gate_covers_ci_hygiene.py",
    "test_issue546_corpus_gates_enumerate_the_commit.py",
    "test_issue559_drift_check_rule_b_blindspot.py",
    "test_matrix_d2_falsifiable.py",
    "test_not_verified_tier.py",
    "test_phase2a_gate_contract_check.py",
    "test_rtl_gen_preserves_authored_rtl.py",
    "test_v1_4_74_issue184_lvs_flush_invariants.py",
)

_HOOK_SRC = '''
import os, sys, json, threading
_P = os.environ.get("VIBEIC_TREE_WATCH_ROOT")
_O = os.environ.get("VIBEIC_TREE_WATCH_OUT")
if _P and _O:
    _R = os.path.realpath(_P)
    _lock = threading.Lock()

    def _rel(p):
        try:
            raw = os.fspath(p)
        except Exception:
            return None
        # ABSOLUTE ONLY: shutil.rmtree passes bare entry names with a dir_fd,
        # and resolving those against this process's cwd invents paths the
        # call never touched. A plant is always built from an absolute root.
        if not os.path.isabs(raw):
            return None
        try:
            s = os.path.realpath(raw)
        except Exception:
            return None
        if not s.startswith(_R + os.sep):
            return None
        r = s[len(_R) + 1:]
        if "__pycache__" in r or r.endswith(".pyc"):
            return None
        return r

    def _rec(kind, r):
        try:
            with _lock, open(_O, "a") as fh:
                fh.write(json.dumps({"kind": kind, "rel": r}) + "\\n")
        except Exception:
            pass

    def _hook(event, args):
        try:
            if event == "open":
                if len(args) > 1 and args[1] and any(c in str(args[1]) for c in "wax+"):
                    r = _rel(args[0])
                    if r:
                        _rec("open", r)
            elif event in ("os.mkdir", "os.remove", "os.rmdir", "os.unlink"):
                r = _rel(args[0])
                if r:
                    _rec(event, r)
            elif event in ("os.rename", "os.replace"):
                for a in args[:2]:
                    r = _rel(a)
                    if r:
                        _rec(event, r)
            elif event in ("os.link", "os.symlink"):
                # DESTINATION only. Reading a shipped file as the SOURCE of a
                # hardlink is how a private farm is built and is not a
                # mutation of the tree the neighbours are scanning.
                if len(args) > 1:
                    r = _rel(args[1])
                    if r:
                        _rec(event, r)
            elif event in ("shutil.copyfile", "shutil.copymode", "shutil.copystat"):
                r = _rel(args[1])
                if r:
                    _rec(event, r)
        except Exception:
            pass

    sys.addaudithook(_hook)
'''


def _instrument(tmp_path: Path) -> Path:
    site = tmp_path / "watch_site"
    site.mkdir(parents=True, exist_ok=True)
    (site / "sitecustomize.py").write_text(_HOOK_SRC, encoding="utf-8")
    return site


def _writes_into_programs(tmp_path: Path, target: Path, tag: str,
                          timeout: int = 900):
    """Run *target* in a child pytest and return the writes it made below
    `programs/`, excluding this repository's own test-run caches."""
    site = _instrument(tmp_path)
    out = tmp_path / f"{tag}.jsonl"
    env = dict(os.environ)
    env["VIBEIC_TREE_WATCH_ROOT"] = str(_PROGRAMS)
    env["VIBEIC_TREE_WATCH_OUT"] = str(out)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(site)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(target), "-q", "-p", "no:randomly",
         "-p", "no:cacheprovider"],
        cwd=str(_PLUGIN), env=env, capture_output=True, text=True,
        timeout=timeout)
    events = []
    if out.exists():
        for line in out.read_text().splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    return r, events


def test_the_instrument_catches_a_plant(tmp_path):
    """NEGATIVE CONTROL, and it runs first on purpose.

    A synthetic test file that writes a module into the live `programs/` dir
    exactly the way the repaired files used to — write, use, unlink in a
    `finally` — must be CAUGHT. If it is not, every assertion below is a
    silent pass over an instrument that measures nothing, which is the same
    shape as the defect this file exists to prevent.
    """
    planter = tmp_path / "test_zz_synthetic_planter.py"
    planter.write_text(textwrap.dedent(f'''
        from pathlib import Path

        _PROGRAMS = Path({str(_PROGRAMS)!r})


        def test_plants_and_tidies_up():
            p = _PROGRAMS / "_zz_synthetic_plant_probe.py"
            p.write_text("# planted\\n")
            try:
                assert p.is_file()
            finally:
                p.unlink(missing_ok=True)
    '''), encoding="utf-8")

    r, events = _writes_into_programs(tmp_path, planter, "control", timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert any(e["rel"] == "_zz_synthetic_plant_probe.py" for e in events), (
        f"the watcher saw no write for a file that certainly planted one — it "
        f"is not measuring, so nothing below it means anything. Events: "
        f"{events}")
    # And the plant really is invisible afterwards, which is why this class
    # was so hard to attribute.
    assert not (_PROGRAMS / "_zz_synthetic_plant_probe.py").exists()
    dirty = subprocess.run(
        ["git", "-C", str(_PLUGIN), "status", "--porcelain", "--",
         "programs/_zz_synthetic_plant_probe.py"],
        capture_output=True, text=True, timeout=60)
    assert dirty.stdout.strip() == "", (
        "the control left a trace git can see; the class this file is about "
        "is the one git CANNOT see, so the control is not reproducing it")


@pytest.mark.parametrize("name", FORMERLY_PLANTED)
def test_a_repaired_file_writes_nothing_into_the_live_programs_tree(
        name, tmp_path):
    """Zero writes below `programs/`, for a file that used to make several."""
    target = _HERE / name
    if not target.is_file():
        pytest.skip(f"{name} is not in this tree")
    r, events = _writes_into_programs(tmp_path, target, name)
    # NON-VACUITY, not a pass requirement. The subject here is what the file
    # WROTE, and a file whose tests fail for an unrelated reason still wrote
    # what it wrote. What would make a zero-write result meaningless is a
    # session that never ran: pytest's rc 2/3/4/5 are usage, internal,
    # interrupted and no-tests-collected. rc 0 and rc 1 both mean the tests
    # executed, which is the condition this measurement needs.
    assert r.returncode in (0, 1), (
        f"{name} did not execute (pytest rc {r.returncode}), so a zero-write "
        f"result would say nothing:\n{r.stdout[-4000:]}\n{r.stderr[-2000:]}")
    assert not events, (
        f"{name} wrote into the live programs tree: "
        f"{sorted({e['rel'] for e in events})}. A concurrent pytest session "
        f"enumerating programs/ counts those as this branch's, and the "
        f"cleanup that removes them removes the evidence with them.")
