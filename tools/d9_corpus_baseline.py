#!/usr/bin/env python3
"""d9_corpus_baseline.py — the D9 Phase-0 corpus baseline instrument.

WHAT THIS MEASURES
==================
For every PUBLISHED run directory in ``benchmark-data/`` and every candidate
content-reading checker that the flow does NOT yet drive, record what the
checker did when pointed at that run.

WHY THE FOUR BUCKETS ARE NOT THREE
----------------------------------
An ``rc 0`` because the artefact was absent is a DIFFERENT FACT from an ``rc 0``
because the content was read and found clean.  A baseline that folds them
together over-counts safety: it reports a checker as quiet on 107 runs when it
actually looked at 3.  Promoting on that number turns published projects red for
a ruler nobody measured.  So every cell carries one of:

    CLEAN     it read content and found nothing wrong        (rc 0, not vacuous)
    FINDING   it read content and found something            (rc 1)
    NO-INPUT  the artefact it needs is not in this run       (rc 2 / vacuous /
                                                              pre-flight miss)
    ERROR     it crashed, timed out, or refused the arg shape

The NO-INPUT rule is the REPO'S OWN, not one invented here:
``programs/_vacuous_exit.py`` defines ``RC_PASS, RC_FAIL, RC_VACUOUS = 0, 1, 2``
and the ``VACUOUS_PASS:`` stdout sentinel, and
``gate_zero_denominator_refuses_check`` enforces it.  This instrument reads that
convention rather than asserting a private one.

DISCOVERY, NOT ENUMERATION
--------------------------
* Run dirs are scraped from ``git ls-files`` (published == tracked), not typed.
* Checkers are scraped by AST from ``programs/*.py``: a program qualifies when it
  has an ``ArgumentParser``, takes a directory-shaped positional, and reads file
  CONTENT -- intersected with "the flow does not DRIVE it".

WIRED MEANS DRIVEN, NOT MENTIONED
---------------------------------
"The flow drives it" is decided STRUCTURALLY, by walking the parsed gate spec
and reading the program name out of each gate clause's command string.  It is
NOT a substring test over the YAML text, and the difference is not academic:

* vibe-ic#1012.  A step-36 comment naming ``l20_dft_scan_topology_actionable_check``
  -- written to explain why that checker was NOT wired -- made the substring test
  call it wired, so ``--only l20_…`` REFUSED with a zero denominator.  Documenting
  a hold made the held checker invisible to the instrument that measures holds.
* A gate clause's PATH ARGUMENT counted too: the string
  ``reports/analog/mixed_signal/signoff_audit.json`` inside a
  ``mixed_signal_signoff_check`` command made ``signoff_audit`` read as wired.
* So did being a PREFIX of a wired name: ``si_mcf_sta`` matched because
  ``si_mcf_sta_check`` is wired.

A step-level ``programs:`` roster is deliberately NOT wiring either.  It is a
declaration of what a step runs, not a gate that can fail -- and this
instrument's whole output column is "would redden if PROMOTED TO BLOCKING",
which is a question about gates.  Producers already populate the baseline
(``lec_run``, ``qsf_gen``, ``analog_mc_yield_run``, ``l21_to_upf_emit``), so
keeping the roster-only programs in the denominator is consistent with the
existing population, not a new class of entrant.

The wiring predicate is the HOUSE one -- ``flow_compliance_check
._declared_gate_commands``, the same walk the flow runner itself uses to decide
which gate programs a step declares -- imported rather than re-implemented, so
the instrument and the flow can never drift into two dialects of "wired".
* A small BESPOKE table covers the candidates whose CLI is not run-dir shaped
  (they take a report path, or require ``--spec``).  Each bespoke entry declares
  its own pre-flight locator, so "the artefact is not here" is decided by this
  harness EXPLICITLY and is never confused with a quiet exit code.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not repair a checker, wire anything into the flow YAML, or change a
verdict.  It is a measurement.  A checker that cannot run in this environment is
reported as ERROR with its reason and stays in the denominator.

Usage:
    python3 tools/d9_corpus_baseline.py --out <dir> [--jobs N] [--timeout S]
    python3 tools/d9_corpus_baseline.py --out <dir> --only spec_conformance_check
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import shlex
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import yaml

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
PROGRAMS = PLUGIN / "programs"
FLOW_YAML = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
BENCH = REPO / "benchmark-data"

CLEAN, FINDING, NO_INPUT, ERROR = "CLEAN", "FINDING", "NO-INPUT", "ERROR"

# The house disclosure predicate, imported so this table and
# gate_discloses_denominator_check can never drift into two dialects of the
# same rule.  Degrades LOUDLY: if the import ever breaks, every CLEAN cell is
# marked `discloses=None` ("not measured") rather than silently `False`.
sys.path.insert(0, str(PROGRAMS))

# The shared isolation harness (#996). NOT wrapped in a soft try/except like
# the disclosure import below: a degraded `discloses` costs a column, and a
# degraded isolation harness costs the published corpus. If this import breaks
# the sweep must not start.
import _run_isolation                                        # noqa: E402

# The HOUSE wiring predicate (#1012). Also a hard import, and for the same
# reason as `_run_isolation`: a degraded wiring test does not cost a column, it
# silently re-decides the DENOMINATOR of every number this instrument prints.
# There is deliberately no substring fallback -- the substring test IS the bug.
from flow_compliance_check import _declared_gate_commands    # noqa: E402

try:
    from gate_discloses_denominator_check import discloses as _discloses
except Exception as _exc:                                    # pragma: no cover
    _discloses = None
    print(f"WARNING: house discloses() unavailable ({_exc}); "
          "disclosure column will read 'not measured'", file=sys.stderr)


def _house_discloses(text: str) -> Optional[bool]:
    return None if _discloses is None else bool(_discloses(text))

# The repo's own verdict tiers -- read, not re-declared.  See
# programs/_vacuous_exit.py.
RC_PASS, RC_FAIL, RC_VACUOUS = 0, 1, 2
VACUOUS_SENTINEL = "VACUOUS_PASS:"

#: Positional names that mean "point me at a run/project directory".
DIR_POSITIONALS = {
    "run_dir", "project", "project_dir", "design_dir",
    "rundir", "root", "run", "project_root",
}
#: Calls that mean "this program reads file CONTENT", as opposed to merely
#: testing for existence.
CONTENT_READS = {"read_text", "read_bytes", "load", "loads",
                 "open", "rglob", "glob", "iterdir"}


# --------------------------------------------------------------- run discovery
def discover_runs(repo: Path) -> Tuple[List[str], str]:
    """Published run dirs, scraped from git.

    PUBLISHED == git-tracked.  ``.gitignore`` excludes some working run trees,
    so "on disk" and "published" are not the same set and the difference is
    reported by the caller rather than quietly resolved.

    A run dir is a tracked directory holding ``phase1/generated_docs/`` -- i.e.
    Phase 1 actually produced layer documents there.
    """
    out = subprocess.run(["git", "ls-files", "benchmark-data"],
                         cwd=repo, capture_output=True, text=True, check=True)
    marker = "/phase1/generated_docs/"
    runs = sorted({line[: line.index(marker)]
                   for line in out.stdout.splitlines() if marker in line})
    return runs, ("git ls-files benchmark-data | dirs containing "
                  "phase1/generated_docs/")


# ----------------------------------------------------------- checker discovery
#: A CHECKER is verdict-shaped: it can NAME a failure and it can EXIT non-zero
#: because of one.  Both halves are required -- a program that prints "FAIL" in
#: a docstring but always exits 0 cannot be promoted to a blocking gate, and a
#: generator or a dashboard server is not a candidate at all.  This is the
#: filter that keeps `flow_dashboard_web` (a server that never returns) out of
#: a baseline it would otherwise pollute with timeouts.
_VERDICT_WORD = re.compile(r'["\'](FAIL|VIOLATION)')
_NONZERO_EXIT = re.compile(r"return\s+(1|RC_FAIL)|exit\(1\)")


def program_shape(path: Path) -> Optional[Dict[str, object]]:
    """Shape of a CLI program, or None when it is not one."""
    try:
        src = path.read_text(errors="ignore")
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return None
    has_parser = False
    positionals: List[str] = []
    required_opts: List[str] = []
    reads = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if fname == "ArgumentParser":
            has_parser = True
        if fname in CONTENT_READS:
            reads = True
        if fname == "add_argument" and node.args:
            first = node.args[0]
            if not (isinstance(first, ast.Constant)
                    and isinstance(first.value, str)):
                continue
            is_required = any(
                kw.arg == "required"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in node.keywords)
            if first.value.startswith("-"):
                if is_required:
                    required_opts.append(first.value)
            else:
                positionals.append(first.value)
    if not has_parser or not reads:
        return None
    return {"positionals": sorted(set(positionals)),
            "required_opts": sorted(set(required_opts)),
            "verdict_shaped": bool(_VERDICT_WORD.search(src)
                                   and _NONZERO_EXIT.search(src))}


def flow_driven_programs(flow_yaml: Path) -> Set[str]:
    """Program names the flow ACTUALLY DRIVES — read from the parsed gate spec.

    Wiring lives in exactly two places in this YAML and nowhere else:

      * a per-step gate clause -- ``program_exit_zero`` /
        ``optional_program_exit_zero`` / ``advisory_program_exit_zero``,
        each holding either a bare command string or a ``{command: ...}`` dict,
        nested under ``all_of`` / ``any_of``;
      * the ``final_gate``, whose shape is ``{program: …, args: …}``.

    Only the FIRST token of a command string is a program name.  Everything
    else in that string is an argument, and an argument that happens to contain
    a program's name (``reports/analog/mixed_signal/signoff_audit.json``) is not
    a wiring.  Comments never reach here at all -- PyYAML has already dropped
    them by the time this walks the document, which is the structural reason
    #1012 cannot recur rather than a promise that it will not.

    Raises on an unparseable flow YAML.  Degrading to "nothing is wired" would
    silently inflate the denominator by the whole program directory; degrading
    to "everything is wired" would silently empty it.  Both are worse than a
    stack trace.
    """
    doc = yaml.safe_load(flow_yaml.read_text(errors="replace")) or {}
    names: Set[str] = set()
    for step in doc.get("steps") or []:
        if isinstance(step, dict):
            names.update(_declared_gate_commands(step.get("gate")))
    final_gate = doc.get("final_gate")
    if isinstance(final_gate, dict):
        # `final_gate` may carry gate clauses AND/OR the {program, args} shape.
        names.update(_declared_gate_commands(final_gate))
        prog = final_gate.get("program")
        if isinstance(prog, str) and prog.strip():
            names.add(shlex.split(prog)[0])
    return names


def discover_checkers(programs: Path, flow_yaml: Path) -> List[Dict[str, object]]:
    """Verdict-shaped, content-reading, run-dir-drivable programs that no gate
    clause in the canonical flow YAML drives.

    Programs carrying an extra REQUIRED option are KEPT.  The generic run-dir
    invocation cannot satisfy them, so they land in ERROR with argparse's own
    reason -- which is the honest record.  Dropping them here would shrink the
    denominator to flatter the result, the exact move
    ``extraction_coverage_denominator_audit`` exists to catch.
    """
    driven = flow_driven_programs(flow_yaml)
    found: List[Dict[str, object]] = []
    for p in sorted(programs.glob("*.py")):
        if p.name.startswith("_"):
            continue                      # shared helper, not a CLI
        if p.stem in driven:
            continue                      # a gate clause really invokes it
        shape = program_shape(p)
        if not shape or not shape["verdict_shaped"]:
            continue
        dir_pos = [x for x in shape["positionals"] if x in DIR_POSITIONALS]
        if not dir_pos:
            continue
        found.append({"name": p.stem, "kind": "rundir-positional",
                      "positional": dir_pos[0],
                      "required_opts": shape["required_opts"]})
    return found


# ------------------------------------------------------------ artefact locators
def _first_dir_with(run: Path, pattern: str, exts: Sequence[str]) -> Optional[Path]:
    """First directory under ``run`` matching ``pattern`` that holds ``exts``."""
    for d in sorted(run.rglob(pattern)):
        if d.is_dir() and any(f.suffix in exts for f in d.iterdir() if f.is_file()):
            return d
    return None


def locate_rtl_dir(run: Path) -> Optional[Path]:
    """The GENERATED RTL of this run -- never the vendor RTL under ``input/``.

    MEASURED, and the reason this is not a bare rglob: on a run that ships
    third-party sources, plain alphabetical order returns
    ``input/design_src/verilog/rtl`` before ``phase2/stage1/rtl``.  Pairing the
    generated spec against the INPUT RTL makes the checker fail a comparison
    nobody asked it to make -- a wrong ruler introduced by the instrument
    rather than by the checker, which is the worst kind because it is invisible
    in the checker's own output.
    """
    cands = [d for d in sorted(run.rglob("rtl"))
             if d.is_dir()
             and "input" not in d.relative_to(run).parts
             and any(f.suffix in (".v", ".sv") for f in d.iterdir() if f.is_file())]
    if not cands:
        return None
    # Prefer the canonical Phase-2 stage-1 output, then any phase2 path, then
    # whatever is left -- shallowest first, so a vendored `.../vendor/*/rtl`
    # never outranks the run's own.
    for pref in ("phase2/stage1/rtl", "phase2"):
        hit = [d for d in cands if pref in str(d.relative_to(run))]
        if hit:
            return min(hit, key=lambda d: len(d.relative_to(run).parts))
    return min(cands, key=lambda d: len(d.relative_to(run).parts))


def locate_spec(run: Path) -> Optional[Path]:
    """The design INPUT the spec-conformance contract is read from.

    §4.05: this is the design INPUT only -- a prompt or an input document.  It
    is never an oracle, a golden, or a generated L-doc.
    """
    for rel in ("input/phase1_prompt.md", "input/docs/prompt.md",
                "input/prompt.md", "README.md"):
        c = run / rel
        if c.is_file():
            return c
    docs = run / "input" / "docs"
    if docs.is_dir():
        cands = [f for f in sorted(docs.iterdir())
                 if f.is_file() and f.suffix in (".md", ".txt")]
        if cands:
            return max(cands, key=lambda f: f.stat().st_size)
    return None


def locate_layout(run: Path) -> Optional[Path]:
    for f in sorted(run.rglob("*.gds")) + sorted(run.rglob("*.gds.gz")):
        if f.is_file():
            return f
    return None


def locate_analog(run: Path) -> Optional[Path]:
    d = run / "analog"
    return d if d.is_dir() and any(d.iterdir()) else None


# --------------------------------------------------------------- bespoke table
# Candidates whose CLI is NOT run-dir shaped.  Each declares its own pre-flight
# so an absent artefact is recorded as NO-INPUT by THIS harness, explicitly,
# instead of being inferred from a quiet exit code.
def _bespoke(run: Path) -> Dict[str, Tuple[Optional[List[str]], str]]:
    """name -> (argv-after-program | None, pre-flight reason when None)."""
    rtl = locate_rtl_dir(run)
    spec = locate_spec(run)
    layout = locate_layout(run)
    analog = locate_analog(run)
    r = str(run)
    return {
        # positional is a report path OR a project/report dir -- the program
        # does its own discovery, so hand it the run and let it decide.
        "em_current_density_check": ([r], ""),
        "metal_layer_density_check": ([r], ""),
        # manual argv parsing, no ArgumentParser -> AST filter cannot see it.
        "extraction_coverage_denominator_audit": ([r], ""),
        # dir positional but NAMED in the flow YAML; measured anyway because the
        # brief lists it, and the discrepancy is reported rather than hidden.
        "l8_sta_clock_period_design_owned_check": ([r], ""),
        "dfm_screen_check": ([r], ""),
        # RTL-shaped: `paths` positional, not a run dir.
        "spec_rtl_port_fidelity_check": (
            (["--rtl-dir", str(rtl)] if rtl else None),
            "no directory named rtl/ holding .v/.sv"),
        # canonical invocation copied from programs/phase2_verify_aggregate.py
        # and programs/verilogeval_tier_pipeline.py: --rtl-dir + --spec.
        "spec_conformance_check": (
            (["--rtl-dir", str(rtl), "--spec", str(spec)]
             if (rtl and spec) else None),
            "needs BOTH an rtl/ dir with .v/.sv AND a design-input spec doc; "
            f"rtl={'yes' if rtl else 'no'} spec={'yes' if spec else 'no'}"),
        "xor_layout_check": (
            (["--report", str(layout)] if layout else None),
            "no .gds/.gds.gz layout in this run"),
        "analog_oracle_compare": (
            ([r] if analog else None), "no analog/ block dir in this run"),
    }


#: Not measurable per (run, checker) AT ALL, with the reason.  Kept in the
#: denominator: "could not measure" is a result, not an omission.
UNMEASURABLE: Dict[str, str] = {
    "dual_track_select": (
        "not a run-dir checker -- it is a SELECTOR over --candidate "
        "(name=path) pairs supplied by a caller, with an optional "
        "--verify-cmd. It reads no artefact of a published run and has no "
        "run-dir invocation, so there is no (run, checker) cell to fill."),
}


# --------------------------------------------------------------- classification
# THE EXIT CODE IS NOT ENOUGH, and the corpus proves it.
#
# MEASURED on the first pass of this instrument: a set of gates exit rc 0 while
# their own stdout says they read nothing --
#     crc_residue_settle_state_required_check -> "[SKIP] ... files scanned: 0"
#     phy_counter_audit                       -> {"verdict":"SKIP", "pass":true}
#     em_current_density_check                -> {"severity":"SKIPPED", ...} rc 3
# Classifying those as CLEAN would report a checker as quiet across 107 runs
# when it examined nothing in any of them -- the precise conflation this
# deliverable exists to prevent, one level up.  So the SELF-DISCLOSURE the gate
# already prints OUTRANKS its exit code.
#
# Every token below was harvested from real corpus output, not guessed; the
# counts that produced each are in the run log beside this table.
_SKIP_LINE = re.compile(
    r"^\s*(?:\[SKIP\]|PASS_SKIP\b|SKIP\s*[-—:])"
    # NO_CONTRACT is NOT line-anchored: the gate that emits it prefixes its own
    # name -- "spec_declaration_emit: NO_CONTRACT — ...". Anchoring it cost a
    # 100-cell misclassification on the first pass of this instrument.
    r"|\bNO_CONTRACT\b", re.M)
_SKIP_JSON = re.compile(
    r'"(?:verdict|severity|status)"\s*:\s*"(?:SKIP|SKIPPED|NOT_APPLICABLE)"')
_SKIP_PROSE = re.compile(
    r"\bgate (?:skipped|not applicable)\b|\bnot applicable\b", re.I)
#: rc values whose meaning a self-disclosed skip token is allowed to override.
#: rc 1 is EXCLUDED on purpose -- a gate that fired is a FINDING even if some
#: unrelated sub-item in its report was skipped.
_SKIP_OVERRIDABLE = (RC_PASS, RC_VACUOUS, 3)


def _denominator_examined(out: str) -> Optional[int]:
    """``denominator.examined`` when the gate emitted the house block.

    ``programs/_gate_denominator.py`` is the repo's own disclosure contract:
    ``examined == 0`` with a reason IS "I judged nothing".  Where a gate
    already speaks it, that is authoritative and nothing here second-guesses it.
    """
    text = out.strip()
    if not text.startswith("{"):
        return None
    try:
        doc = json.loads(text)
    except (ValueError, TypeError):
        return None
    block = doc.get("denominator") if isinstance(doc, dict) else None
    if isinstance(block, dict) and isinstance(block.get("examined"), int):
        return block["examined"]
    return None


def classify(rc, out: str, err: str) -> Tuple[str, str]:
    """(bucket, why) for ONE invocation.

    Order matters: could-not-run beats self-disclosure, self-disclosure beats
    the exit code, and the exit code decides only what is left.
    """
    both = f"{out}\n{err}"
    if rc == "TIMEOUT":
        return ERROR, "timed out"
    if rc == "SPAWN":
        return ERROR, "could not spawn"
    if "Traceback (most recent call last)" in both:
        line = [l for l in both.splitlines() if l.strip()][-1][:160]
        return ERROR, f"crashed: {line}"
    if (any(l.startswith("usage:") for l in both.splitlines())
            and "error: " in both):
        line = [l for l in both.splitlines() if "error: " in l][:1]
        return ERROR, ("could not measure -- argparse refused the run-dir arg "
                       f"shape: {(line or [''])[0][:140]}")

    examined = _denominator_examined(out)
    if examined == 0 and rc in _SKIP_OVERRIDABLE:
        return NO_INPUT, f"house denominator block: examined 0 -- {_head(both)}"

    if rc in _SKIP_OVERRIDABLE:
        if any(l.lstrip().startswith(VACUOUS_SENTINEL) for l in both.splitlines()):
            return NO_INPUT, "VACUOUS_PASS sentinel -- examined nothing"
        for rx, label in ((_SKIP_LINE, "self-disclosed SKIP line"),
                          (_SKIP_JSON, "self-disclosed SKIP verdict in JSON"),
                          (_SKIP_PROSE, "self-disclosed not-applicable")):
            if rx.search(both):
                return NO_INPUT, f"{label}: {_head(both)}"

    if rc == RC_VACUOUS:
        return NO_INPUT, f"rc 2 (RC_VACUOUS): {_head(both)}"
    if rc == RC_FAIL:
        return FINDING, _head(both)
    if rc == RC_PASS:
        return CLEAN, _head(both)
    if isinstance(rc, int) and rc < 0:
        return ERROR, f"killed by signal {-rc}"
    return ERROR, f"unexpected rc {rc}: {_head(both)}"


def _head(text: str, n: int = 200) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:n]
    return ""


# --------------------------------------------------------------------- isolation
# MEASURED, and the reason this instrument is not a plain loop: 8 of 77
# candidates WRITE INTO THE RUN THEY JUDGE.  `phase1_one_shot_runner` rewrites
# `phase1/generated_docs/*`; `qsf_gen` emits FPGA project files; `ip_catalog_pull`
# drops vendor RTL into `phase2/stage1/rtl/`.  The first sweep left 2336 tracked
# files modified in benchmark-data.
#
# That is two separate problems.  It edits published data, and -- worse for the
# NUMBERS -- it CONTAMINATES the sweep: a checker that runs after the rewrite
# reads different content from one that ran before, so the table would depend on
# scheduling order.  Every writer therefore runs against a THROWAWAY COPY.
#
# The writer set is DISCOVERED by probing, never typed, so a program that starts
# writing tomorrow is caught tomorrow rather than silently corrupting a rerun.
def _snapshot(root: Path) -> Dict[str, Tuple[int, int]]:
    """DELEGATED to :func:`_run_isolation.snapshot` (#996).

    Narrowed to the ``(size, mtime_ns)`` pair the comparisons below use, so
    they keep meaning exactly what they did. The shared helper also records
    ``dev``/``ino`` — dropped here because this probe asks "did the program
    write?", not "is this a hardlink of something else"; that second question
    is asked by :func:`_run_isolation.copy_run` when the copy is made.
    """
    return {k: (s.size, s.mtime_ns) for k, s in _run_isolation.snapshot(root).items()}


def probe_mutators(runs: List[str], checkers: List[Dict[str, object]],
                   repo: Path, scratch: Path, timeout: int) -> Dict[str, str]:
    """Which checkers write into the run they are pointed at."""
    # Probe on the SPARSEST and the RICHEST run, because writers fire on what is
    # PRESENT: `dfm_screen_check` writes only where a `phase3/` exists,
    # `ip_catalog_pull` only where it can resolve IP.  A one-run probe found 3
    # writers; adding the richest run found 8; the true set is still not proven
    # complete -- which is precisely why isolation is unconditional and this
    # census is published as a FINDING rather than relied on for safety.
    by_size = sorted(runs, key=lambda r: sum(
        f.stat().st_size for f in (repo / r).rglob("*") if f.is_file()))
    probe_rels = {by_size[0], by_size[-1], by_size[len(by_size) // 2]}
    found: Dict[str, str] = {}
    for ch in checkers:
        name = ch["name"]
        if name in UNMEASURABLE:
            continue
        for probe_rel in sorted(probe_rels):
            if name in found:
                break
            tmp = scratch / f"probe_{name}"
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            shutil.copytree(repo / probe_rel, tmp, symlinks=True)
            try:
                before = _snapshot(tmp)
                argv, _ = _bespoke(tmp).get(name, ([str(tmp)], ""))
                if argv is None:
                    continue
                try:
                    subprocess.run([sys.executable, str(PROGRAMS / f"{name}.py")]
                                   + argv, capture_output=True, text=True,
                                   timeout=timeout, cwd=str(PROGRAMS))
                except (subprocess.TimeoutExpired, OSError):
                    pass
                after = _snapshot(tmp)
                added = set(after) - set(before)
                changed = {k for k in set(after) & set(before)
                           if after[k] != before[k]}
                if added or changed:
                    sample = sorted(added or changed)[:3]
                    found[name] = (f"on {probe_rel}: {len(added)} added / "
                                   f"{len(changed)} changed, e.g. {sample}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    return found


# ---------------------------------------------------------------------- driving
def _kill_process_group(proc: "subprocess.Popen") -> None:
    """SIGTERM then SIGKILL the timed-out cell's whole process group.

    Best-effort by construction: the group may already be gone (ESRCH), and a
    platform without ``killpg`` falls back to killing the direct child, which
    is exactly the pre-existing behaviour rather than a new failure mode.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except (OSError, AttributeError):
        proc.kill()
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except (OSError, AttributeError):
            break
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            continue


def _rmtree_stubborn(path: Path, tries: int = 4) -> Optional[str]:
    """Remove a throwaway copy.  Returns None, or the REASON it survived.

    A leaked scratch directory is a FINDING, not a crash and not a silence: it
    costs disk under ``--scratch`` and says an orphan outlived its cell, but it
    cannot touch the corpus (that is what `assert_corpus_pristine` proves), so
    withdrawing 9202 measured cells over it would be the wrong trade.
    """
    last: Optional[BaseException] = None
    for attempt in range(tries):
        try:
            shutil.rmtree(path)
            return None
        except OSError as exc:
            last = exc
            time.sleep(0.25 * (attempt + 1))
    return f"{type(last).__name__}: {last}"


def run_cell(program: Path, argv: List[str], timeout: int) -> Dict[str, object]:
    """Drive ONE cell, and on timeout kill the whole PROCESS GROUP.

    `subprocess.run(timeout=…)` kills the direct child and nothing below it.
    That was survivable while the population was checkers; it is not once the
    population is honest, because the corrected wiring test (#1012) admitted
    the runner-class programs — every one of which had been excluded by a
    substring hit — and a runner spawns children.

    MEASURED: a timed-out runner left grandchildren writing into the throwaway
    copy, and the copy's cleanup then raised
    ``OSError: [Errno 39] Directory not empty: 'reports'`` — which propagated
    out of the worker and killed the sweep at cell 8500 of 9202. So the cell
    is started in its OWN session and the group is signalled, which ends the
    orphans rather than leaving them racing the cleanup.
    """
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cmd = [sys.executable, str(program)] + argv
    t0 = time.time()
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, env=env, cwd=str(PROGRAMS),
                             start_new_session=True)
    except OSError as exc:
        rc, out, err = "SPAWN", "", str(exc)
    else:
        try:
            out, err = p.communicate(timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            _kill_process_group(p)
            # Drain, so the pipes close and no writer is left mid-write. The
            # group is already signalled, so this cannot block on the timeout
            # again -- but it is bounded anyway rather than trusted.
            try:
                out, err = p.communicate(timeout=15)
            except subprocess.TimeoutExpired:      # pragma: no cover
                p.kill()
                out, err = "", ""
            rc = "TIMEOUT"
    bucket, why = classify(rc, out, err)
    cell = {"rc": rc, "bucket": bucket, "why": why,
            "secs": round(time.time() - t0, 2)}
    if bucket == CLEAN:
        # "A PASS must say how much it looked at" is the HOUSE rule, and the
        # house owns the predicate -- imported, not re-implemented, so this
        # table and gate_discloses_denominator_check cannot drift apart.
        cell["discloses"] = _house_discloses(f"{out}\n{err}")
    return cell


def build_cells(runs: List[str], checkers: List[Dict[str, object]],
                repo: Path) -> List[Dict[str, object]]:
    cells: List[Dict[str, object]] = []
    for rel in runs:
        run = repo / rel
        bespoke = _bespoke(run)
        for ch in checkers:
            name = ch["name"]
            if name in UNMEASURABLE:
                continue
            if name in bespoke:
                argv, reason = bespoke[name]
            else:
                argv, reason = [str(run)], ""
            cells.append({"run": rel, "checker": name,
                          "argv": argv, "preflight_reason": reason})
    return cells


def render_markdown(doc: Dict[str, object], n_runs: int, how: str) -> str:
    """The per-(run, checker) table, emitted by the instrument, not pasted."""
    import collections
    per: Dict[str, "collections.Counter"] = collections.defaultdict(
        collections.Counter)
    undisclosed: "collections.Counter" = collections.Counter()
    for c in doc["table"]:
        per[c["checker"]][c["bucket"]] += 1
        if c["bucket"] == CLEAN and c.get("discloses") is False:
            undisclosed[c["checker"]] += 1

    tot = collections.Counter()
    for v in per.values():
        tot.update(v)
    out = [
        "# D9 Phase 0 / Deliverable 0.2 — corpus baseline",
        "",
        "Generated by `tools/d9_corpus_baseline.py`. Regenerate with:",
        "",
        "```",
        "python3 tools/d9_corpus_baseline.py --out <dir>",
        "```",
        "",
        f"* published run dirs: **{n_runs}** — discovered by `{how}`",
        f"* checkers: **{len(per)}** measurable "
        f"+ {len(doc['unmeasurable'])} not measurable per (run, checker)",
        f"* cells: **{doc['cells']}**  ·  wall clock **{doc['elapsed_secs']}s**",
        "",
        f"| bucket | cells |", "|---|---|",
        f"| CLEAN (read content, nothing wrong) | {tot[CLEAN]} |",
        f"| FINDING (read content, found something) | {tot[FINDING]} |",
        f"| NO-INPUT (artefact absent) | {tot[NO_INPUT]} |",
        f"| ERROR (crashed / could not run) | {tot[ERROR]} |",
        "",
        "## Would-redden-if-promoted, per checker",
        "",
        "`RED` = FINDING + ERROR: the published projects that would go red if "
        "this checker were promoted to BLOCKING today.",
        "",
        "| checker | RED | FINDING | ERROR | CLEAN | NO-INPUT | PASS w/o denominator |",
        "|---|--:|--:|--:|--:|--:|--:|",
    ]
    for name, v in sorted(per.items(),
                          key=lambda kv: (-(kv[1][FINDING] + kv[1][ERROR]),
                                          kv[0])):
        out.append(f"| `{name}` | {v[FINDING] + v[ERROR]} | {v[FINDING]} | "
                   f"{v[ERROR]} | {v[CLEAN]} | {v[NO_INPUT]} | "
                   f"{undisclosed.get(name, 0)} |")
    out += ["", "## Not measurable per (run, checker)", ""]
    for name, reason in sorted(doc["unmeasurable"].items()):
        out.append(f"* `{name}` — {reason}")
    out.append("")
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True,
                    help="output directory for the table + summary")
    ap.add_argument("--jobs", type=int, default=min(16, (os.cpu_count() or 4)))
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--scratch", type=Path,
                    # NOT a home directory: this default named one machine's
                    # scratch tree, so every other host wrote into a path that
                    # did not exist. `shutil.copytree` (not `cp -l`) makes the
                    # copies, so a different filesystem costs nothing here --
                    # there are no hardlinks to break across devices.
                    default=Path(tempfile.gettempdir()) / "d9_corpus_scratch",
                    help="where throwaway run copies are made for WRITERS "
                         "(default: $TMPDIR/d9_corpus_scratch; leaked copies "
                         "are left here on purpose, so it must persist)")
    ap.add_argument("--only", action="append", default=None,
                    help="restrict to these checker names (repeatable)")
    ap.add_argument("--max-runs", type=int, default=None,
                    help="pilot mode: first N runs only (NOT a baseline)")
    args = ap.parse_args(argv)

    t_start = time.time()
    runs, how = discover_runs(REPO)
    discovered = discover_checkers(PROGRAMS, FLOW_YAML)
    names = {c["name"] for c in discovered}

    # The bespoke candidates the AST filter cannot see are ADDED, not swapped in.
    for extra in sorted(_bespoke(REPO).keys()):
        if extra not in names and (PROGRAMS / f"{extra}.py").is_file():
            discovered.append({"name": extra, "kind": "bespoke-arg-shape",
                               "positional": None})
            names.add(extra)
    for name, reason in UNMEASURABLE.items():
        if name not in names and (PROGRAMS / f"{name}.py").is_file():
            discovered.append({"name": name, "kind": "unmeasurable",
                               "positional": None, "reason": reason})

    if args.only:
        discovered = [c for c in discovered if c["name"] in set(args.only)]
    if args.max_runs:
        runs = runs[: args.max_runs]

    if not runs or not discovered:
        print("REFUSE — zero denominator: "
              f"{len(runs)} runs x {len(discovered)} checkers. "
              "A baseline over nothing is not a baseline.", file=sys.stderr)
        return RC_VACUOUS

    scratch = args.scratch
    scratch.mkdir(parents=True, exist_ok=True)
    # Reported as a FINDING, not relied on for safety: every cell is isolated
    # unconditionally, so this census is free to be incomplete without putting
    # the corpus or the numbers at risk.
    mutators = probe_mutators(runs, discovered, REPO, scratch, args.timeout)
    print(f"checkers observed WRITING into the run they judge: "
          f"{len(mutators)} -> {sorted(mutators)}")

    cells = build_cells(runs, discovered, REPO)
    print(f"corpus: {len(runs)} published run dirs ({how})")
    print(f"checkers: {len(discovered)} "
          f"({len(UNMEASURABLE & names) if False else ''}"
          f"{sum(1 for c in discovered if c['kind'] == 'unmeasurable')} unmeasurable)")
    print(f"cells to drive: {len(cells)}  jobs={args.jobs} timeout={args.timeout}s")

    results: List[Dict[str, object]] = []
    todo = []
    for cell in cells:
        if cell["argv"] is None:
            cell.update({"rc": None, "bucket": NO_INPUT,
                         "why": f"pre-flight: {cell['preflight_reason']}",
                         "secs": 0.0})
            results.append(cell)
        else:
            todo.append(cell)

    #: Throwaway copies an orphaned grandchild kept alive past its cell.
    #: Reported, never swallowed -- see `_rmtree_stubborn`.
    leaked: List[Dict[str, str]] = []

    def drive(cell: Dict[str, object]) -> Dict[str, object]:
        """Run ONE cell against a pristine throwaway copy of the run.

        UNCONDITIONAL, and that is the point.  An earlier version isolated only
        the checkers a probe had caught writing, and it still left 40 tracked
        files modified: a probe on one run cannot reveal a writer that only
        fires when a richer artefact is present (`dfm_screen_check` writes only
        where a `phase3/` exists; `ip_catalog_pull` only where it can resolve
        IP).  Isolating conditionally makes corpus safety depend on the probe
        being complete, which is unfalsifiable from inside the probe.
        Isolating everything makes it depend on nothing.

        It also removes ORDER from the result: with writers loose, a cell's
        verdict depends on which cells the scheduler ran first.  Measured cost
        of the bug: 116 cells changed bucket between the contaminated and the
        isolated sweep.
        """
        name = cell["checker"]
        cell["isolated"] = True
        # mkdtemp + explicit teardown, NOT `with TemporaryDirectory(...)`: its
        # cleanup raises out of the worker, and one raised cleanup killed a
        # 9202-cell sweep at cell 8500 (see `_rmtree_stubborn`).
        td = Path(tempfile.mkdtemp(dir=str(scratch)))
        try:
            dst = td / "run"
            shutil.copytree(REPO / cell["run"], dst, symlinks=True)
            argv, _reason = _bespoke(dst).get(name, ([str(dst)], ""))
            if argv is None:
                return {"rc": None, "bucket": NO_INPUT, "secs": 0.0,
                        "why": "pre-flight (isolated): required artefact absent"}
            return run_cell(PROGRAMS / f"{name}.py", argv, args.timeout)
        finally:
            why = _rmtree_stubborn(td)
            if why:
                leaked.append({"checker": name, "run": cell["run"],
                               "scratch": str(td), "why": why})

    done = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = {pool.submit(drive, c): c for c in todo}
        for fut in as_completed(futs):
            cell = futs[fut]
            try:
                cell.update(fut.result())
            except Exception as exc:            # noqa: BLE001 -- see below
                # ONE cell that the HARNESS could not drive is one ERROR cell,
                # not a dead sweep. It stays in the denominator carrying the
                # harness's own reason, which is the same rule this instrument
                # already applies to a checker that cannot run.
                cell.update({"rc": None, "bucket": ERROR, "secs": 0.0,
                             "why": f"could not measure: harness raised "
                                    f"{type(exc).__name__}: {exc}"})
            results.append(cell)
            done += 1
            if done % 500 == 0:
                print(f"  ... {done}/{len(todo)} driven "
                      f"({time.time() - t_start:.0f}s)", flush=True)

    args.out.mkdir(parents=True, exist_ok=True)
    elapsed = round(time.time() - t_start, 1)
    doc = {
        "corpus": {"runs": len(runs), "discovered_by": how, "run_dirs": runs},
        "checkers": sorted(discovered, key=lambda c: c["name"]),
        "unmeasurable": UNMEASURABLE,
        "writers_isolated": mutators,
        "scratch_copies_leaked": leaked,
        "cells": len(results),
        "elapsed_secs": elapsed,
        "table": sorted(results, key=lambda c: (c["checker"], c["run"])),
    }
    (args.out / "corpus_baseline.json").write_text(json.dumps(doc, indent=1))

    (args.out / "corpus_baseline.md").write_text(
        render_markdown(doc, len(runs), how))

    tally: Dict[str, int] = {CLEAN: 0, FINDING: 0, NO_INPUT: 0, ERROR: 0}
    for c in results:
        tally[c["bucket"]] += 1
    if leaked:
        print(f"\n[FINDING] {len(leaked)} throwaway copy(ies) survived their "
              f"cell -- an orphan was still writing. The CORPUS is unaffected "
              f"(the tripwire below proves it); the scratch dirs are left in "
              f"place under --scratch so the orphan is inspectable:",
              file=sys.stderr)
        for lk in leaked[:10]:
            print(f"    {lk['checker']} on {lk['run']}: {lk['why']}",
                  file=sys.stderr)
        if len(leaked) > 10:
            print(f"    ... and {len(leaked) - 10} more (see "
                  f"corpus_baseline.json:scratch_copies_leaked)", file=sys.stderr)

    print(f"\nCLEAN={tally[CLEAN]} FINDING={tally[FINDING]} "
          f"NO-INPUT={tally[NO_INPUT]} ERROR={tally[ERROR]}  "
          f"(denominator {len(results)} = {len(runs)} runs x "
          f"{len({c['checker'] for c in results})} measurable checkers)")
    print(f"elapsed {elapsed}s -> {args.out / 'corpus_baseline.json'}")

    # THE TRIPWIRE (#996). This sweep drove every measurable checker over every
    # published run; if isolation held, the corpus it read is byte-identical to
    # the corpus it started from. The first version of this sweep left 2336
    # tracked files modified, and nothing said so until somebody ran
    # `git status` by hand. It is not left to somebody.
    #
    # A CONTAMINATED SWEEP IS NOT A SWEEP WITH A CAVEAT. The verdicts above
    # depend on scheduling order once anything has been rewritten underneath
    # them, so the numbers are withdrawn rather than published with a warning.
    try:
        st = _run_isolation.assert_corpus_pristine(
            REPO, what="the corpus baseline sweep")
    except _run_isolation.Perturbation as exc:
        print(f"\n[FAIL] {exc}", file=sys.stderr)
        print("The table above is WITHDRAWN: a checker that ran after a "
              "rewrite read different content from one that ran before, so "
              "these verdicts depend on scheduling order.", file=sys.stderr)
        return RC_FAIL
    print(f"tripwire: {st.describe()}")
    return RC_PASS


if __name__ == "__main__":
    sys.exit(main())
