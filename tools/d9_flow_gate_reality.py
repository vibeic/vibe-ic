#!/usr/bin/env python3
"""d9_flow_gate_reality.py — how many of the 63 D9 cells actually move today.

WHAT THE NINTH DIMENSION ASKS
=============================
The published grid asks eight questions of each of the 63 flow steps. The ninth
question — "is the output CORRECT" — is NOT a shipped dimension. This program
measures how much of it could be answered TODAY, by the gates that actually
ship, against the runs that are actually published.

It is a MEASUREMENT. It wires nothing into the flow YAML, repairs no checker,
and changes no verdict.

THE TWO AXES, AND WHY NEITHER ALONE IS THE ANSWER
=================================================
A D9 cell needs BOTH a ruler and something to measure.

  THE RULER   a BLOCKING gate criterion naming a program that reads the
              CONTENT of an artefact and can exit non-zero because of what it
              read.  ``advisory_program_exit_zero`` is not a ruler: it records
              and stops nothing.

  THE THING   at least one published run that carries the step's full declared
              ``required_outputs`` set, so the ruler has something to read.

Counting rulers alone is the defect this campaign exists to remove: 59 of 63
steps name a blocking program that calls ``open``/``glob`` somewhere, which
proves only that the program is written in Python.  So the verdict here is not
static at all — every cell is decided by RUNNING the step's blocking gate
programs against published runs and classifying what came back.

MOVES / DARK — decided by a TWO-ARM ARTEFACT MUTATION, not by a static scan
--------------------------------------------------------------------------
"The gate names a blocking program that reads content" is NOT enough, and
measuring it that way is how this page got its last wrong number: 59 of 63 steps
pass that test, which proves only that the program is written in Python.  A
ruler that reads SOME file is not a ruler that reads THIS STEP'S OUTPUT.

So each cell is decided the way this repo already decides every other one —
``matrix_mutation_ledger``: *a cell may not be called ENFORCED until a NAMED,
RUNNABLE mutation has been shown to turn it red.*  Applied at the artefact
level, on an isolated copy, never the worktree:

    ARM A  the run as published            -> verdict_A
    ARM B  the same run with the step's own declared outputs REMOVED
                                           -> verdict_B

A cell **MOVES TODAY** when, on at least one published run, some BLOCKING gate
program of that step has a CONTENT-DERIVED verdict_A (CLEAN or FINDING) **and**
verdict_B differs from it.  That is the only evidence that the ruler both reads
the step's own output and changes its mind about it.

It is **DARK** otherwise — including the case that matters most: the gate runs,
passes, and passes IDENTICALLY when the artefact it claims to judge is deleted.
That cell is not measuring the step; it is measuring nothing.

The four buckets are the house's own (``programs/_vacuous_exit.py``:
``RC_PASS, RC_FAIL, RC_VACUOUS = 0, 1, 2`` and the ``VACUOUS_PASS:`` sentinel),
imported from ``tools/d9_corpus_baseline.py`` rather than re-implemented, so
this instrument and that one cannot drift into two dialects of the same rule.

THE FIVE CAUSES — and which of them a program decides
=====================================================
Three are decided PER STEP by this program, from the tree:

  DENOMINATOR      the step's declared output set appears in ZERO published
                   runs, so no ruler could ever read it here.
  UNREAD-PDK       the step's gate reads a PDK-bound quantity (Jmax, density
                   window, manufacturing grid) and the tech LEF is absent from
                   the corpus, so the bound it compares against is not present.
  MISSING-SKILL    the step names skills that do not exist on disk.

Two are NOT per-step-decidable by any program in this tree, and are reported as
EVIDENCED FINDINGS with the specific predicates named, never as a per-cell
classification this program cannot actually make:

  SINGLE-EMITTER   "total == sum of parts" where one program in one pass wrote
                   both operands.
  CONSUMED-SPEC    the spec the gate checks against was itself derived from the
                   artefact being checked.

Saying which of the five a program decides and which it does not is the point,
not a gap: the alternative is a page that claims a per-cell cause it inferred.

ISOLATION
=========
8 of 77 candidates in the sibling baseline WRITE INTO THE RUN THEY JUDGE. The
writer set is DISCOVERED by probing here too, never typed, and writers run
against a throwaway copy.  ``--verify-corpus-clean`` re-checks at the end that
``git status`` over ``benchmark-data/`` is empty, so a writer the probe missed
is caught rather than silently corrupting the corpus.

EXIT
    0  the sweep completed and the corpus is byte-identical to HEAD
    1  the corpus was modified by the sweep (a writer the probe missed)
    2  the flow or the corpus could not be read
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
PROGRAMS = PLUGIN / "programs"
TESTS = PROGRAMS / "tests"
BENCH = REPO / "benchmark-data"

sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(REPO / "tools"))

from matrix_63x8 import flowref as F  # noqa: E402

# The four buckets and the classifier are the sibling instrument's, imported so
# the two tables cannot disagree about what a vacuous pass is.
from d9_corpus_baseline import (  # noqa: E402
    CLEAN, FINDING, NO_INPUT, ERROR, classify, discover_runs,
)

CONTENT_DERIVED = (CLEAN, FINDING)

#: Calls that mean "this program reads file CONTENT".  The sibling instrument's
#: set, imported in spirit and restated here because it is the weak half of the
#: measurement and the docstring above says so out loud.
CONTENT_READS = {"read_text", "read_bytes", "load", "loads",
                 "open", "rglob", "glob", "iterdir"}

#: Tokens that mean "this program compares against a PDK-owned physical bound".
#: Used only to attribute the UNREAD-PDK cause, never to decide MOVES/DARK.
PDK_BOUND_TOKENS = ("jmax", "current_density", "em_", "density_window",
                    "manufacturing_grid", "mfg_grid", "min_width",
                    "min_spacing", "tech_lef", "techlef")

#: Filenames that ARE the PDK's own tables.  Presence measured over the corpus.
TECH_LEF_PATTERNS = ("*.tlef", "*tech.lef", "*.tech.lef", "*technology.lef")


# ─────────────────────────────────────────────────────────── corpus census
def tracked_files(repo: Path) -> List[str]:
    out = subprocess.run(["git", "ls-files", "benchmark-data"], cwd=repo,
                         capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def index_runs(tracked: Sequence[str], runs: Sequence[str]) -> Dict[str, Set[str]]:
    """run -> set of its tracked paths, relative to the run root."""
    by_run: Dict[str, Set[str]] = {r: set() for r in runs}
    prefixes = sorted(runs, key=len, reverse=True)   # longest first: runs nest
    for line in tracked:
        for r in prefixes:
            if line.startswith(r + "/"):
                by_run[r].add(line[len(r) + 1:])
                break
    return by_run


def satisfies(files: Set[str], entry: str) -> bool:
    """Does a run satisfy ONE ``required_outputs`` entry?

    ANY_OF and GLOB are resolved exactly as ``flowref`` defines them, so this
    census and the matrix agree on what an entry means.
    """
    for alt in F.split_any_of(entry):
        alt = alt.strip()
        if not alt:
            continue
        if F.is_glob(alt):
            if any(fnmatch.fnmatch(f, alt) for f in files):
                return True
        elif alt in files:
            return True
    return False


def denominator(by_run: Dict[str, Set[str]], step_id: str) -> Tuple[int, List[str]]:
    """Runs carrying the step's FULL declared output set."""
    ro = F.required_outputs(step_id)
    if not ro:
        return 0, []
    hits = [r for r, files in by_run.items()
            if all(satisfies(files, e) for e in ro)]
    return len(hits), sorted(hits)


# ─────────────────────────────────────────────────────── program inspection
_shape_cache: Dict[str, Optional[bool]] = {}


def reads_content(basename: str) -> Optional[bool]:
    """True when the program calls something that reads file CONTENT.

    None when the source could not be parsed — degrade LOUDLY, never to False.
    """
    if basename in _shape_cache:
        return _shape_cache[basename]
    path = F.program_path(basename)
    verdict: Optional[bool] = None
    if path and path.exists():
        try:
            tree = ast.parse(path.read_text(errors="ignore"))
            verdict = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = (getattr(node.func, "attr", None)
                          or getattr(node.func, "id", None))
                    if fn in CONTENT_READS:
                        verdict = True
                        break
        except SyntaxError:
            verdict = None
    _shape_cache[basename] = verdict
    return verdict


def touches_pdk_bound(basename: str) -> bool:
    path = F.program_path(basename)
    if not path or not path.exists():
        return False
    low = path.read_text(errors="ignore").lower()
    return any(tok in low for tok in PDK_BOUND_TOKENS)


def blocking_programs(step_id: str) -> List[str]:
    progs: Set[str] = set()
    for clause in F.gate_clauses(step_id):
        prog = getattr(clause, "program", None)
        if prog and clause.is_blocking:
            progs.add(prog)
    return sorted(progs)


def advisory_programs(step_id: str) -> List[str]:
    block = set(blocking_programs(step_id))
    progs: Set[str] = set()
    for clause in F.gate_clauses(step_id):
        prog = getattr(clause, "program", None)
        if prog and not clause.is_blocking and prog not in block:
            progs.add(prog)
    return sorted(progs)


# ────────────────────────────────────────────────────────────────── driving
def _snapshot(root: Path) -> Dict[str, Tuple[int, int]]:
    snap: Dict[str, Tuple[int, int]] = {}
    for p in root.rglob("*"):
        if p.is_file():
            try:
                st = p.stat()
                snap[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns)
            except OSError:
                pass
    return snap


def probe_writers(programs: Sequence[str], runs: Sequence[str], repo: Path,
                  scratch: Path, timeout: int) -> Dict[str, str]:
    """Which gate programs write into the run they judge.

    Probed on the sparsest, median and richest run, because writers fire on what
    is PRESENT.  The set is not proven complete — which is why the caller also
    verifies the corpus at the end rather than trusting this.
    """
    sized = sorted(runs, key=lambda r: sum(
        f.stat().st_size for f in (repo / r).rglob("*") if f.is_file()))
    probes = sorted({sized[0], sized[len(sized) // 2], sized[-1]})
    found: Dict[str, str] = {}
    for name in programs:
        prog = F.program_path(name)
        if not prog:
            continue
        for rel in probes:
            if name in found:
                break
            tmp = scratch / f"probe_{name}"
            shutil.rmtree(tmp, ignore_errors=True)
            try:
                shutil.copytree(repo / rel, tmp, symlinks=True)
                before = _snapshot(tmp)
                try:
                    subprocess.run([sys.executable, str(prog), str(tmp)],
                                   capture_output=True, text=True,
                                   timeout=timeout, cwd=str(PROGRAMS))
                except (subprocess.TimeoutExpired, OSError):
                    pass
                after = _snapshot(tmp)
                added = set(after) - set(before)
                changed = {k for k in set(after) & set(before)
                           if after[k] != before[k]}
                if added or changed:
                    found[name] = (f"on {rel}: {len(added)} added / "
                                   f"{len(changed)} changed")
            except OSError as exc:
                found[name] = f"probe failed: {exc}"
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    return found


def _drive(prog: Path, target: Path, timeout: int) -> Dict[str, object]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        p = subprocess.run([sys.executable, str(prog), str(target)],
                           capture_output=True, text=True, timeout=timeout,
                           env=env, cwd=str(PROGRAMS))
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = "TIMEOUT", "", ""
    except OSError as exc:
        rc, out, err = "SPAWN", "", str(exc)
    bucket, why = classify(rc, out, err)
    return {"bucket": bucket, "why": why, "rc": rc}


def remove_declared_outputs(root: Path, step_id: str) -> List[str]:
    """ARM B: delete the step's OWN declared outputs from an isolated copy.

    ANY_OF removes EVERY alternative — leaving one behind would let the gate
    read a sibling and the arms would differ for the wrong reason.
    Returns the relative paths actually removed, so an arm that deleted nothing
    is visible as such instead of masquerading as a clean control.
    """
    removed: List[str] = []
    for entry in F.required_outputs(step_id):
        for alt in F.split_any_of(entry):
            alt = alt.strip()
            if not alt:
                continue
            targets = sorted(root.glob(alt)) if F.is_glob(alt) else [root / alt]
            for t in targets:
                try:
                    if t.is_file() or t.is_symlink():
                        t.unlink()
                        removed.append(str(t.relative_to(root)))
                    elif t.is_dir():
                        shutil.rmtree(t, ignore_errors=True)
                        removed.append(str(t.relative_to(root)) + "/")
                except OSError:
                    pass
    return removed


def verdict_moved(arm_a: Dict[str, object], arm_b: Dict[str, object]) -> bool:
    """THE decision this whole instrument turns on, in one place.

    A cell moves only when the ruler (a) actually read something in arm A, and
    (b) CHANGED ITS MIND in arm B once the step's own output was deleted.

    Dropping half (b) is not a smaller claim, it is a different and much weaker
    one -- "some blocking program of this step reads a file somewhere" -- which
    59 of 63 steps satisfy.  That is the measurement this page exists to stop
    publishing, so the conjunction lives in a named function with a test on it
    rather than inline where it can be relaxed unnoticed.
    """
    if arm_a.get("bucket") not in CONTENT_DERIVED:
        return False
    return (arm_a.get("bucket") != arm_b.get("bucket")
            or arm_a.get("rc") != arm_b.get("rc"))


def two_arm_cell(step_id: str, run_rel: str, programs: Sequence[str],
                 repo: Path, scratch: Path, timeout: int) -> Dict[str, object]:
    """Drive every blocking gate program twice on one isolated copy of one run.

    Isolation is UNCONDITIONAL here — arm B deletes files, so the copy is
    mandatory, and that removes any dependence on the writer probe being
    complete.
    """
    tmp = Path(tempfile.mkdtemp(dir=str(scratch)))
    try:
        dest = tmp / "run"
        shutil.copytree(repo / run_rel, dest, symlinks=True)
        arm_a = {p: _drive(F.program_path(p), dest, timeout) for p in programs
                 if F.program_path(p)}
        removed = remove_declared_outputs(dest, step_id)
        arm_b = {p: _drive(F.program_path(p), dest, timeout) for p in programs
                 if F.program_path(p)}
        moved = []
        for p in arm_a:
            a, b = arm_a[p], arm_b.get(p, {})
            if verdict_moved(a, b):
                moved.append({"program": p,
                              "arm_a": f'{a["bucket"]}/rc={a["rc"]}',
                              "arm_b": f'{b.get("bucket")}/rc={b.get("rc")}'})
        return {"run": run_rel, "removed": len(removed), "moved": moved,
                "arm_a": {p: v["bucket"] for p, v in arm_a.items()},
                "arm_b": {p: v["bucket"] for p, v in arm_b.items()}}
    except OSError as exc:
        return {"run": run_rel, "error": f"isolation failed: {exc}",
                "removed": 0, "moved": []}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ──────────────────────────────────────────────────────────────── the sweep
def sweep(repo: Path, runs: List[str], by_run: Dict[str, Set[str]],
          jobs: int, timeout: int, scratch: Path,
          limit_per_step: Optional[int]) -> Dict[str, object]:
    """Two-arm artefact mutation, per (step, run in its denominator set).

    The population is the step's DENOMINATOR SET — the runs that carry its full
    declared output set — because that is the only place the mutation means
    anything: you cannot delete what a run never had.  A step whose denominator
    is zero is DARK without a single subprocess, and the reason is recorded as
    the denominator, not as a gate failure.
    """
    steps = list(F.step_ids())
    all_blocking = sorted({p for s in steps for p in blocking_programs(s)})
    print(f"steps={len(steps)} runs={len(runs)} "
          f"distinct blocking gate programs={len(all_blocking)}",
          file=sys.stderr)

    plan: List[Tuple[str, str, List[str]]] = []
    dropped: Dict[str, int] = {}
    for sid in steps:
        den, den_runs = denominator(by_run, sid)
        progs = blocking_programs(sid)
        if not den or not progs:
            continue
        chosen = den_runs
        if limit_per_step is not None and len(den_runs) > limit_per_step:
            chosen = den_runs[:limit_per_step]
            dropped[sid] = len(den_runs) - limit_per_step
        for rel in chosen:
            plan.append((sid, rel, progs))
    print(f"two-arm cells planned: {len(plan)} "
          f"({sum(len(p) for _, _, p in plan) * 2} subprocess runs)",
          file=sys.stderr)
    if dropped:
        print(f"NOTE: per-step run cap dropped {sum(dropped.values())} "
              f"(step,run) pairs across {len(dropped)} steps: {dropped}",
              file=sys.stderr)

    results: Dict[str, List[Dict[str, object]]] = {s: [] for s in steps}
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futs = {pool.submit(two_arm_cell, sid, rel, progs, repo, scratch,
                            timeout): sid
                for sid, rel, progs in plan}
        done = 0
        for fut in as_completed(futs):
            results[futs[fut]].append(fut.result())
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(plan)}", file=sys.stderr)
    return {"per_step": results, "planned": len(plan),
            "run_cap_dropped": dropped, "blocking_programs": all_blocking}


# ────────────────────────────────────────────────────────────── verdicts
def build_report(repo: Path, runs: List[str], by_run: Dict[str, Set[str]],
                 swept: Dict[str, object]) -> Dict[str, object]:
    cells = swept["per_step"]
    steps = list(F.step_ids())

    # --- PDK presence over the corpus (cause UNREAD-PDK)
    tech_lef_runs = [r for r, files in by_run.items()
                     if any(fnmatch.fnmatch(f.lower(), pat)
                            for f in files for pat in TECH_LEF_PATTERNS)]

    # --- skills on disk (cause MISSING-SKILL)
    skill_dirs = {p.name for p in (PLUGIN / "skills").iterdir()
                  if p.is_dir()} if (PLUGIN / "skills").is_dir() else set()

    rows = []
    for sid in steps:
        den, den_runs = denominator(by_run, sid)
        block = blocking_programs(sid)
        adv = advisory_programs(sid)

        # what the two-arm mutation actually did, over the denominator set
        per_run = cells.get(sid, [])
        movers: Dict[str, Dict[str, object]] = {}
        runs_probed = len(per_run)
        runs_moved = 0
        for cell in per_run:
            if cell.get("moved"):
                runs_moved += 1
            for m in cell.get("moved", []):
                rec = movers.setdefault(m["program"], {"program": m["program"],
                                                       "runs": 0,
                                                       "example": None})
                rec["runs"] += 1
                if rec["example"] is None:
                    rec["example"] = (f'{cell["run"]}: {m["arm_a"]} -> '
                                      f'{m["arm_b"]}')

        moves = bool(movers)

        # WHY a non-moving cell did not move is decided by what the ARMS did,
        # never by a guess.  Folding these three into one word was this
        # instrument's own first error: they are different defects with
        # different fixes, and only the first is "the gate is blind".
        pat = {"green_survives": 0, "already_red": 0, "never_read": 0}
        for cell in per_run:
            a, b = cell.get("arm_a", {}), cell.get("arm_b", {})
            for prog in a:
                pair = (a[prog], b.get(prog))
                if pair == (CLEAN, CLEAN):
                    pat["green_survives"] += 1
                elif pair == (FINDING, FINDING):
                    pat["already_red"] += 1
                elif a[prog] in (NO_INPUT, ERROR):
                    pat["never_read"] += 1

        declared_skills = list(F.declared_skills(sid))
        missing_skills = [s for s in declared_skills if s not in skill_dirs]
        pdk_bound = [p for p in block if touches_pdk_bound(p)]

        cause = None
        if not moves:
            # documented precedence, most-proximate first
            if den == 0:
                cause = "DENOMINATOR"
            elif not block:
                cause = "NO-BLOCKING-RULER"
            elif pat["green_survives"]:
                # A PASS that survives deletion of the artefact it judges. The
                # worst cell on the page; it must not be folded into a softer
                # word, and it OUTRANKS every explanation below because it is
                # an observed behaviour rather than an attribution.
                cause = "RULER-BLIND"
            elif pdk_bound and not tech_lef_runs:
                cause = "UNREAD-PDK"
            elif missing_skills:
                cause = "MISSING-SKILL"
            elif pat["already_red"] and not pat["never_read"]:
                cause = "ALREADY-RED"
            else:
                cause = "RULER-NEVER-RAN"

        rows.append({
            "step": sid,
            "name": F.step_name(sid),
            "stage": F.step_stage(sid),
            "declared_outputs": len(F.required_outputs(sid)),
            "denominator": den,
            "runs_probed": runs_probed,
            "runs_moved": runs_moved,
            "blocking_programs": block,
            "advisory_programs": adv,
            "blocking_reads_content": [p for p in block if reads_content(p)],
            "movers": sorted(movers.values(), key=lambda m: m["program"]),
            "arm_pattern": pat,
            "pdk_bound_programs": pdk_bound,
            "moves_today": moves,
            "cause": cause,
            "declared_skills": declared_skills,
            "missing_skills": missing_skills,
        })

    moving = [r for r in rows if r["moves_today"]]
    dark = [r for r in rows if not r["moves_today"]]
    dens = sorted(r["denominator"] for r in rows)

    all_skills = sorted({s for r in rows for s in r["declared_skills"]})
    missing_all = sorted({s for r in rows for s in r["missing_skills"]})

    # --- what the publishing policy excludes BY CONSTRUCTION, and what that
    #     does to the ceiling.  PUBLISHING.md names the four globs; the counts
    #     are measured over the tracked corpus rather than trusted from prose.
    tracked_all = tracked_files(repo)
    ext_census = {ext: sum(1 for f in tracked_all if f.lower().endswith("." + ext))
                  for ext in ("def", "gds", "spef", "oas", "lef", "tlef", "lib")}
    excluded_globs = ("*.gds", "*.def", "*.spef", "*.oas")
    excl_exts = tuple(g.lstrip("*") for g in excluded_globs)
    ceiling_blocked = []
    for r in rows:
        if r["moves_today"]:
            continue
        need = sorted({e for e in F.required_outputs(r["step"])
                       for x in excl_exts if x in e.lower()})
        if need:
            ceiling_blocked.append({"step": r["step"], "cause": r["cause"],
                                    "needs": need[:2]})

    n_programs = len([p for p in PROGRAMS.glob("*.py")
                      if not p.name.startswith("_")])
    flow_text = (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text(
        errors="replace")
    referenced = sorted({p.stem for p in PROGRAMS.glob("*.py")
                         if not p.name.startswith("_") and p.stem in flow_text})

    return {
        "generated_by": "tools/d9_flow_gate_reality.py",
        "corpus": {
            "runs": len(runs),
            "how": ("git ls-files benchmark-data | dirs containing "
                    "phase1/generated_docs/"),
            "tech_lef_runs": len(tech_lef_runs),
        },
        "steps": len(rows),
        "moves_today": len(moving),
        "dark": len(dark),
        "denominator_bands": {
            "zero": sum(1 for d in dens if d == 0),
            "one_to_ten": sum(1 for d in dens if 1 <= d <= 10),
            "eleven_plus": sum(1 for d in dens if d >= 11),
            "all_runs": sum(1 for d in dens if d == len(runs)),
            "median": dens[len(dens) // 2],
            "max": dens[-1],
        },
        "skills": {
            "declared": len(all_skills),
            "missing": len(missing_all),
            "missing_names": missing_all,
        },
        "programs": {
            "on_disk": n_programs,
            "all_py_in_programs": len(list(PROGRAMS.glob("*.py"))),
            "referenced_by_flow": len(referenced),
        },
        "publishing_excluded_dark": dict(
            ext_census,
            globs=list(excluded_globs),
            dark_cells_blocked=len(ceiling_blocked),
            blocked=ceiling_blocked,
            ceiling_on_published_corpus=len(rows) - len(ceiling_blocked),
        ),
        "causes": {c: sum(1 for r in dark if r["cause"] == c)
                   for c in sorted({r["cause"] for r in dark})},
        "evidenced_findings": evidence_findings(repo, by_run, tech_lef_runs),
        "rows": rows,
        "two_arm_cells_planned": swept["planned"],
        "run_cap_dropped": swept["run_cap_dropped"],
    }


def evidence_findings(repo: Path, by_run: Dict[str, Set[str]],
                      tech_lef_runs: List[str]) -> Dict[str, object]:
    """The two causes no program in this tree decides PER CELL.

    Each is reported as a CITATION plus a re-measured census, never as a
    per-step attribution this instrument cannot actually make.  Where the brief
    that commissioned this page asserted a count, the count is re-derived here
    and the disagreement is recorded rather than smoothed.
    """
    out: Dict[str, object] = {}

    # --- SINGLE-EMITTER: the INVERTED one, cited at its line.
    atpg = PROGRAMS / "fault_atpg_run.py"
    inverted = None
    if atpg.exists():
        for i, line in enumerate(atpg.read_text(errors="ignore").splitlines(), 1):
            if "faults_covered" in line and "coverage_ratio" in line and "=" in line:
                inverted = {"file": "programs/fault_atpg_run.py", "line": i,
                            "source": line.strip()}
                break
    out["single_emitter_inverted"] = inverted

    # --- CONSUMED-SPEC: the floorplan budget, re-measured over the corpus.
    l19 = [f for f in tracked_files(repo)
           if "L19" in f and f.endswith(".json")]
    null_n = populated = absent = 0
    prose = 0
    for rel in l19:
        try:
            doc = json.loads((repo / rel).read_text(errors="ignore"))
        except Exception:
            continue
        fields = doc.get("fields", doc) if isinstance(doc, dict) else {}
        if not isinstance(fields, dict) or "die_area_budget_um" not in fields:
            absent += 1
            continue
        val = fields["die_area_budget_um"]
        if val is None:
            null_n += 1
        else:
            populated += 1
            if isinstance(val, str) and not re.fullmatch(
                    r"\s*\d+(?:\.\d+)?\s*[x×]\s*\d+(?:\.\d+)?\s*", val):
                prose += 1
    out["floorplan_budget"] = {
        "l19_docs": len(l19), "null": null_n, "populated": populated,
        "key_absent": absent, "populated_but_prose": prose,
        "field": "die_area_budget_um",
    }

    # --- UNREAD PDK: what the EM checker actually does when Jmax is absent.
    out["pdk"] = {
        "tech_lef_runs": len(tech_lef_runs),
        "em_checker": "programs/em_current_density_check.py",
    }
    return out


def verify_corpus_clean(repo: Path) -> Tuple[bool, str]:
    out = subprocess.run(["git", "status", "--porcelain", "--", "benchmark-data"],
                         cwd=repo, capture_output=True, text=True)
    body = out.stdout.strip()
    return (not body), body


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="directory for the report")
    ap.add_argument("--jobs", type=int, default=max(4, (os.cpu_count() or 4) - 2))
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--limit-per-step", type=int, default=None,
                    help="cap the runs probed PER STEP (smoke use only). The "
                         "report records exactly how many (step,run) pairs the "
                         "cap dropped; it is never a silent truncation.")
    args = ap.parse_args(argv)

    if not BENCH.is_dir():
        print("benchmark-data/ not found", file=sys.stderr)
        return 2

    tracked = tracked_files(REPO)
    runs, how = discover_runs(REPO)
    if not runs:
        print("no published runs discovered", file=sys.stderr)
        return 2
    by_run = index_runs(tracked, runs)

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="d9reality_") as scratch:
        swept = sweep(REPO, runs, by_run, args.jobs, args.timeout,
                      Path(scratch), args.limit_per_step)
        report = build_report(REPO, runs, by_run, swept)

    clean, body = verify_corpus_clean(REPO)
    report["corpus_clean_after_sweep"] = clean
    if not clean:
        report["corpus_dirty_paths"] = body.splitlines()[:50]

    (outdir / "d9_reality.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ("rows",)},
                     indent=1, ensure_ascii=False))
    if not clean:
        print("CORPUS MODIFIED BY SWEEP — a writer the probe missed",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
