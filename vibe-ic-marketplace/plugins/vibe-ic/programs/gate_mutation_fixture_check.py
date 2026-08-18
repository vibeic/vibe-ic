#!/usr/bin/env python3
"""gate_mutation_fixture_check.py — every dispatcher gate must carry a fixture
in BOTH directions, and a gate carrying only one of the two is itself a finding.

WHY THIS FILE EXISTS
====================
A gate proven only to PASS on good input has not been shown to discriminate.
Every gate in `tools/ci/repo_hygiene_gates.sh` is driven over the real tree on
every landing, so the CAN-PASS direction is exercised continuously and by
construction. Nothing exercised the other direction as a REQUIREMENT: a gate
could be authored, wired, reviewed and landed while no stored input existed
that it rejects. Its unit test may well construct one — 73 of 83 do, measured
below — but nothing OBLIGED it to, so the tenth gate to be added without one
looked exactly like the first nine that had one.

This repo has found the stronger version of that failure twice: a check that
passes until someone FORGES its input (vibe-ic#1745), and a check that reports
a decided verdict over gates it never ran. Both are the same shape — a green
that was never made to go red.

WHAT A FIXTURE IS HERE
======================
Two directories per gate, under `gate_mutation_fixtures/<slug>/`:

    can_pass/     a known-good input tree the gate ACCEPTS (rc 0)
    mutate.py     applies ONE mutation to a COPY of can_pass, producing the
                  input the gate MUST REJECT
    fixture.json  expected rc on each side, and the message the rejection
                  MUST print

WHY THE MUTATED TREE IS GENERATED AND NEVER STORED
==================================================
A committed can_fail/ tree carries, by definition, the very thing its gate
looks for — so the gate finds it in the fixture while sweeping the real tree,
and the fixture reddens the gate it exists to prove. MEASURED on this tree
before the design was fixed: one file under
`gate_mutation_fixtures/_hazardprobe/` carrying the injected early return, and

    neutered_gate_tree_check .   ->  [FAIL] 1 finding(s) over 3819 module(s)
                                     — this checkout carries a gate that
                                     cannot fail

which is the gate working perfectly and the fixture being the defect. The same
holds for the NDA panel, whose every search token is a token this repo may not
carry in a tracked file at all. So the mutation is a PROGRAM, not bytes: it
runs against a disposable copy, and nothing violating is ever committed.

THE ARGV IS DERIVED, NOT RETYPED. The gate is driven with the command
`repo_hygiene_gates.sh` DECLARES for it, read through the one shared reader
(`gate_discloses_denominator_check.parse_declarations`), with the input roots
re-pointed at the fixture tree and the PROGRAM path left on the real tree.
Storing a copy of the argv in `fixture.json` would be the second
hand-maintained list this repo has spent three versions removing: the fixture
would keep passing against a command the dispatcher no longer runs.

WHY THE MESSAGE IS REQUIRED AND NOT JUST THE EXIT CODE
======================================================
A gate that rejects for the WRONG reason is indistinguishable, by exit code
alone, from one that rejects for the right one. A fixture that only pinned
`rc != 0` would stay green if the gate started refusing because the fixture
tree confused it — which is `NOT_CHECKED` wearing a `FAIL`'s clothes. So the
rejection has to NAME what it found.

BASELINE, AND WHY IT MAY ONLY SHRINK
====================================
Requiring both fixtures of all 83 gates on day one produces a gate people
route around, which is how a gate ends up reporting FAIL while blocking
nothing — the reasoning is `flow_step_can_fail_check`'s, and the shape is
copied from it deliberately. The gates that have no fixture yet are recorded
in `BASELINE` with the reason each has none. Anything NEW fails from its first
run, which is the property worth having.

A baseline entry that GAINS a fixture must be deleted from `BASELINE`: the
gate says so and fails until it is. Deleting an entry without giving the gate
a fixture is the one repair this file exists to prevent, and it cannot work —
the label lands straight back in the missing set.

chip-AGNOSTIC: shell declarations, fixture trees and exit codes only.

EXIT
    0  every declared gate has both fixtures, or is a recorded baseline entry
    1  a gate has neither or only one; or the baseline is stale, should shrink,
       or a fixture does not discriminate under --execute
    2  the hygiene script could not be read, or declares no gate at all. A
       requirement that enumerated nothing has not been met; see the rc=2
       convention used across this repo.
"""
from __future__ import annotations

import argparse
import filecmp
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from _atomic_artefact import write_json                # noqa: E402
from gate_discloses_denominator_check import (        # noqa: E402
    GateDecl, parse_declarations)

FIXTURES_DIRNAME = "gate_mutation_fixtures"

#: Gates with no mutation fixture yet, and WHY. MAY ONLY SHRINK.
#:
#: The reason is not decoration. It records which of the two shapes an entry
#: is — "no fixture has been written" versus "this gate's input is not a tree
#: a fixture can stand in for" — so a later reader can tell the work that is
#: outstanding from the work that is not worth doing, without re-deriving it
#: from the gate's source.
BASELINE: Dict[str, str] = {}


def _load_baseline(programs_dir: Optional[Path] = None) -> Dict[str, str]:
    """The baseline, read from the sidecar so it is data and not code.

    Kept beside the FIXTURES rather than inline because it starts at 70-odd
    entries and shrinks one landing at a time; a diff of a JSON object is
    reviewable, a diff of a 70-entry literal inside a docstringed module is
    not.

    IT IS READ FROM THE TREE UNDER AUDIT, not from beside this module. Those
    are the same path for the everyday run and different ones the moment the
    gate is pointed at another checkout — which is how the acceptance tests
    drive it. Reading its own copy would have made this gate report on the
    baseline of whatever tree it was INSTALLED in while claiming to have
    audited the tree it was HANDED; both baseline tests caught it.
    """
    base = programs_dir if programs_dir is not None else _HERE
    path = base / FIXTURES_DIRNAME / "baseline.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(BASELINE)
    entries = raw.get("gates_without_a_mutation_fixture", {})
    return {str(k): str(v) for k, v in entries.items()}


class Fixture:
    """One gate's fixture pair, as it sits on disk."""

    def __init__(self, directory: Path, spec: Dict):
        self.dir = directory
        self.spec = spec
        self.label = str(spec.get("gate_label", ""))
        self.can_pass = directory / "can_pass"
        self.can_fail = directory / "can_fail"
        self.mutate = directory / "mutate.py"

    @property
    def slug(self) -> str:
        return self.dir.name

    def structural_defects(self) -> List[str]:
        """What is missing or malformed, in the reader's words."""
        out: List[str] = []
        if not self.label:
            out.append("fixture.json names no gate_label")
        if not self.can_pass.is_dir():
            out.append("no can_pass/ tree — the direction the gate ACCEPTS is "
                       "undeclared")
        if self.can_fail.exists():
            out.append("a stored can_fail/ tree — the mutated input must be "
                       "GENERATED by mutate.py, because a committed tree "
                       "carrying what the gate looks for reddens that gate "
                       "over the real tree (measured; see the module "
                       "docstring)")
        if not self.mutate.is_file():
            out.append("no mutate.py — the direction the gate must REJECT is "
                       "undeclared, which is the one this gate exists to "
                       "require")
        msg = self.spec.get("expect_fail_message")
        if not (isinstance(msg, str) and msg.strip()):
            out.append("expect_fail_message is empty — a rejection that names "
                       "nothing cannot be told from a refusal to look")
        return out


def _differs(a: Path, b: Path) -> bool:
    """True when the two trees are not byte-identical."""
    cmp = filecmp.dircmp(str(a), str(b))

    def walk(c: filecmp.dircmp) -> bool:
        if c.left_only or c.right_only or c.funny_files:
            return True
        _, mismatch, errors = filecmp.cmpfiles(
            c.left, c.right, c.common_files, shallow=False)
        if mismatch or errors:
            return True
        return any(walk(sub) for sub in c.subdirs.values())

    return walk(cmp)


def load_fixtures(root: Path) -> Tuple[List[Fixture], List[str]]:
    """Every fixture on disk, plus the ones that would not parse."""
    base = root / FIXTURES_DIRNAME
    found: List[Fixture] = []
    broken: List[str] = []
    if not base.is_dir():
        return found, broken
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        spec_path = d / "fixture.json"
        if not spec_path.is_file():
            broken.append(f"{d.name}: no fixture.json")
            continue
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            broken.append(f"{d.name}: fixture.json does not parse ({exc})")
            continue
        found.append(Fixture(d, spec))
    return found, broken


def hygiene_script(repo_root: Path) -> Path:
    return repo_root / "tools" / "ci" / "repo_hygiene_gates.sh"


def _programs_dir(repo_root: Path) -> Path:
    return (repo_root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" /
            "programs")


def fixture_argv(decl: GateDecl, repo_root: Path,
                 tree: Path) -> Optional[List[str]]:
    """The gate's DECLARED command, re-pointed at a fixture tree.

    The program itself stays on the real tree — a fixture supplies the gate's
    INPUT, never its code; substituting the program path too would run
    whatever the fixture happened to contain, which is not this gate.

    Returns None when the declaration is one only bash can expand, so the
    caller can say "not driveable" rather than guess.
    """
    if decl.runtime_expansion:
        return None
    real_plugin = repo_root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    try:
        tokens = shlex.split(decl.cmd)
    except ValueError:
        return None
    if not tokens:
        return None

    def as_input(tok: str) -> str:
        tok = tok.replace("$PG", str(_programs_dir(repo_root)))
        tok = tok.replace("$PLUGIN", str(tree)).replace("$ROOT", str(tree))
        return tok

    out: List[str] = []
    program_seen = False
    for i, tok in enumerate(tokens):
        if not program_seen and tok.endswith(".py"):
            # The program: resolved against the REAL tree.
            p = tok.replace("$PG", str(_programs_dir(repo_root)))
            p = p.replace("$PLUGIN", str(real_plugin))
            p = p.replace("$ROOT", str(repo_root))
            if not os.path.isabs(p):
                base = (real_plugin if decl.cwd_token == "$PLUGIN"
                        else repo_root)
                p = str(base / p)
            out.append(p)
            program_seen = True
            continue
        out.append(tok if i == 0 and not program_seen else as_input(tok))
    if not program_seen:
        return None
    if out and out[0] == "python3":
        out[0] = sys.executable
    return out


def _build_can_fail(fx: Fixture, workdir: Path) -> Tuple[Optional[Path], str]:
    """The mutated tree, materialised. (path, note) — path None on failure."""
    dest = workdir / "can_fail"
    if not fx.mutate.is_file():
        return None, "no mutate.py"
    shutil.copytree(fx.can_pass, dest)
    proc = subprocess.run([sys.executable, str(fx.mutate), str(dest)],
                          capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        return None, (f"mutate.py exited {proc.returncode}: "
                      f"{(proc.stdout + proc.stderr).strip()[:200]}")
    if not _differs(fx.can_pass, dest):
        return None, "mutate.py changed nothing — there is no mutation"
    return dest, "mutate.py"


def execute_fixture(fx: Fixture, decl: GateDecl, repo_root: Path,
                    timeout: int = 300) -> List[str]:
    """Drive BOTH directions. Returns the findings, empty when it discriminates."""
    out: List[str] = []
    argv_tpl = fixture_argv(decl, repo_root, Path("/__TREE__"))
    if argv_tpl is None:
        return [f"{fx.slug}: the declaration is not driveable as written "
                f"({decl.runtime_expansion or 'no program token'}) — a fixture "
                f"cannot stand in for it"]
    with tempfile.TemporaryDirectory(prefix="gatefx-") as tmp:
        work = Path(tmp)
        good = work / "can_pass"
        shutil.copytree(fx.can_pass, good)
        expect_pass_rc = int(fx.spec.get("expect_pass_rc", 0))
        rc, good_text = _drive(decl, repo_root, good, timeout)
        if rc != expect_pass_rc:
            out.append(
                f"{fx.slug}: CAN-PASS fixture was not accepted — expected rc "
                f"{expect_pass_rc}, got {rc}. Last line: "
                f"{_last_line(good_text)!r}")
        # The message must SEPARATE the two arms. One that the accepting arm
        # already prints pins nothing: the fixture would stay green over a
        # gate that had stopped distinguishing them, which is this file's own
        # failure mode turned inward.
        pinned = str(fx.spec.get("expect_fail_message", ""))
        if pinned and pinned in good_text:
            out.append(
                f"{fx.slug}: expect_fail_message {pinned!r} is ALREADY in the "
                f"CAN-PASS output — it does not separate the two arms, so "
                f"the fixture would pass over a gate that stopped "
                f"discriminating")

        bad, note = _build_can_fail(fx, work)
        if bad is None:
            out.append(f"{fx.slug}: CAN-FAIL fixture could not be built "
                       f"({note})")
            return out
        rc, text = _drive(decl, repo_root, bad, timeout)
        want_rcs = fx.spec.get("expect_fail_rc", [1])
        if isinstance(want_rcs, int):
            want_rcs = [want_rcs]
        want_rcs = [int(r) for r in want_rcs]
        msg = str(fx.spec.get("expect_fail_message", ""))
        if rc == expect_pass_rc:
            out.append(
                f"{fx.slug}: CAN-FAIL fixture was ACCEPTED (rc {rc}) — the "
                f"gate does not discriminate. Mutation via {note}. Last "
                f"line: {_last_line(text)!r}")
        elif rc not in want_rcs:
            out.append(
                f"{fx.slug}: CAN-FAIL fixture rejected with rc {rc}, but the "
                f"fixture declares {want_rcs} — rejecting for an undeclared "
                f"reason is not the rejection this fixture pins. Last line: "
                f"{_last_line(text)!r}")
        elif msg not in text:
            out.append(
                f"{fx.slug}: CAN-FAIL fixture was rejected (rc {rc}) but the "
                f"output never says {msg!r} — a rejection that names nothing "
                f"cannot be told from a refusal to look. Last line: "
                f"{_last_line(text)!r}")
    return out


def _drive(decl: GateDecl, repo_root: Path, tree: Path,
           timeout: int) -> Tuple[int, str]:
    argv = fixture_argv(decl, repo_root, tree)
    assert argv is not None
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_programs_dir(repo_root)), env.get("PYTHONPATH", "")]).rstrip(
            os.pathsep)
    try:
        proc = subprocess.run(argv, cwd=str(tree), capture_output=True,
                              text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as exc:
        return 127, f"could not execute: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _last_line(text: str) -> str:
    lines = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1][:180] if lines else "(no output)"


def audit(repo_root: Path, execute: bool = False,
          only: Optional[str] = None, timeout: int = 300) -> Dict:
    """The whole verdict, as data."""
    script = hygiene_script(repo_root)
    decls = parse_declarations(script)
    programs = _programs_dir(repo_root)
    fixtures, broken = load_fixtures(programs)
    baseline = _load_baseline(programs)

    result: Dict = {
        "script": str(script),
        "declared": len(decls),
        "fixtures_on_disk": len(fixtures),
        "baseline_entries": len(baseline),
        "unreadable_fixtures": broken,
        "missing_both": [],
        "incomplete": [],
        "orphan_fixtures": [],
        "stale_baseline": [],
        "baseline_should_shrink": [],
        "executed": [],
        "execution_findings": [],
        "with_both": 0,
    }
    if not decls:
        result["refused"] = (
            f"no gate declaration read from {script} — a requirement that "
            f"enumerated nothing has not been met")
        return result

    by_label: Dict[str, Fixture] = {}
    for fx in fixtures:
        if fx.label:
            by_label.setdefault(fx.label, fx)
    declared_labels = [d.label for d in decls]
    decl_by_label = {d.label: d for d in decls}

    for label in declared_labels:
        fx = by_label.get(label)
        if fx is None:
            if label not in baseline:
                result["missing_both"].append(label)
            continue
        if label in baseline:
            result["baseline_should_shrink"].append(label)
        defects = fx.structural_defects()
        if defects:
            result["incomplete"].append({"gate": label, "slug": fx.slug,
                                         "defects": defects})
        else:
            result["with_both"] += 1

    for fx in fixtures:
        if fx.label and fx.label not in decl_by_label:
            result["orphan_fixtures"].append(
                {"slug": fx.slug, "gate_label": fx.label})
    for label in sorted(baseline):
        if label not in decl_by_label:
            result["stale_baseline"].append(label)

    if execute:
        for fx in fixtures:
            if only and fx.slug != only and fx.label != only:
                continue
            decl = decl_by_label.get(fx.label)
            if decl is None or fx.structural_defects():
                continue
            result["executed"].append(fx.slug)
            result["execution_findings"].extend(
                execute_fixture(fx, decl, repo_root, timeout))
    return result


def _print(result: Dict) -> int:
    if "refused" in result:
        print(f"[NOT CHECKED] gate_mutation_fixture_check: "
              f"{result['refused']}")
        return 2
    bad = False
    for label in result["missing_both"]:
        print(f"[FAIL] gate {label!r} carries NEITHER a can-pass nor a "
              f"can-fail fixture, and is not a recorded baseline entry. A "
              f"gate that has never been shown to reject anything has not "
              f"been shown to discriminate.")
        bad = True
    for item in result["incomplete"]:
        for d in item["defects"]:
            print(f"[FAIL] fixture {item['slug']!r} for gate "
                  f"{item['gate']!r}: {d}")
        bad = True
    for label in result["baseline_should_shrink"]:
        print(f"[FAIL] gate {label!r} now HAS a fixture but is still recorded "
              f"in the baseline — the baseline may only shrink; delete the "
              f"entry.")
        bad = True
    for label in result["stale_baseline"]:
        print(f"[FAIL] baseline records gate {label!r}, which "
              f"{Path(result['script']).name} no longer declares. A baseline "
              f"that outlives its gate hides the next gate that needs one.")
        bad = True
    for item in result["orphan_fixtures"]:
        print(f"[FAIL] fixture {item['slug']!r} names gate "
              f"{item['gate_label']!r}, which no gate declares — it proves "
              f"nothing about anything that runs.")
        bad = True
    for line in result["unreadable_fixtures"]:
        print(f"[FAIL] {line}")
        bad = True
    for line in result["execution_findings"]:
        print(f"[FAIL] {line}")
        bad = True

    scope = (f"{result['declared']} gate(s) declared; "
             f"{result['with_both']} carry BOTH fixtures; "
             f"{result['baseline_entries']} recorded in the shrink-only "
             f"baseline")
    if result["executed"]:
        scope += f"; {len(result['executed'])} fixture(s) EXECUTED"
    if bad:
        print(f"[FAIL] gate_mutation_fixture_check: {scope}")
        return 1
    print(f"[PASS] gate_mutation_fixture_check: {scope} — every declared gate "
          f"is accounted for in both directions or by a recorded reason")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=("Every gate in the hygiene dispatcher must carry a "
                     "CAN-PASS and a CAN-FAIL fixture."))
    ap.add_argument("repo_root", nargs="?", default=".",
                    help="repository root (default: %(default)s)")
    ap.add_argument("--execute", action="store_true",
                    help="drive both directions of every fixture, not just "
                         "check that they are declared")
    ap.add_argument("--gate", default=None,
                    help="with --execute, drive only this gate label or "
                         "fixture slug")
    ap.add_argument("--timeout", type=int, default=300,
                    help="per-run timeout in seconds (default: %(default)s)")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the full result to this path")
    a = ap.parse_args(list(argv) if argv is not None else None)

    root = Path(a.repo_root).resolve()
    if not hygiene_script(root).is_file():
        print(f"[NOT CHECKED] gate_mutation_fixture_check: no "
              f"tools/ci/repo_hygiene_gates.sh under {root}", file=sys.stderr)
        return 2
    result = audit(root, execute=a.execute, only=a.gate, timeout=a.timeout)
    if a.json_out:
        write_json(a.json_out, result)
    return _print(result)


if __name__ == "__main__":
    raise SystemExit(main())
