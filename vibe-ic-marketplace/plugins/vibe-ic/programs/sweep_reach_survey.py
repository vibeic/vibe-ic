#!/usr/bin/env python3
"""sweep_reach_survey.py — how many of this tree's sweeps can tell you they fired?

A ratio quoted in a PR body and derivable by nobody is the same class of claim as
a sweep that exits 0 having examined nothing. This program is the re-derivation
path for the number in the change that introduced ``_sweep_reach``: run it and
get today's ratio off today's tree, rather than trusting a snapshot.

WHAT IT MEASURES
================
1. Discovery (AST, no execution): a program is SWEEP-SHAPED when it has an
   argparse CLI and takes a SET of targets — a positional with ``nargs`` in
   ``* +``, or a repeatable target option. Config allowlists (``--allow-macro``,
   ``--define``, ``--tier``) are excluded by name: they are options, not corpora.

2. Drive it to a ZERO-REACH run. The corpus is three valid, readable, trivial
   Verilog modules (an inverter, an AND2, a buffer — invented names, no PDK)
   offered both as files and as directories. Every sweep can READ this corpus;
   essentially no sweep's rule APPLIES to anything in it.

   That distinction is the whole measurement. An EMPTY corpus tests "I was
   given nothing", which the shipped ``_gate_denominator`` / ``_vacuous_exit``
   work already made visible across this tree. A POPULATED corpus the sweep
   reads in full and judges none of tests "I looked and never decided" — the
   shape a 756-pair corpus sweep reported as ``exit 0, clean``.

3. Classify by the plugin's OWN consumer contract, not by prose. ``flow_
   compliance_check`` consumes exactly two signals from a program: the exit
   code, and the ``VACUOUS_PASS:`` line-start sentinel. So:

     DISCLOSES     rc 2 and/or the sentinel — an automated reader can tell
     SILENT        rc 0 with neither — reads exactly like a clean sweep
     NOT_DRIVABLE  argparse refused this arg shape, the program crashed, it
                   could not read the targets, or its rule FIRED (rc 1) so the
                   run was not zero-reach at all

WHY ``NOT_DRIVABLE`` IS PUBLISHED RATHER THAN QUIETLY DROPPED
=============================================================
A generic corpus cannot express every sweep's required argv, so the denominator
this survey reaches is smaller than the population it discovered. Reporting the
ratio over the sweeps it drove while hiding the ones it could not is the same
defect the survey exists to measure, one level up. Both numbers are published,
and when the survey drives NOTHING it returns rc 2 through ``_sweep_reach``
rather than printing a ratio over an empty denominator.

The verdict for a program is taken CONSERVATIVELY: if ANY drivable arg shape
produces a silent zero-reach run, the program is SILENT. One witness that a
sweep can report clean having judged nothing is enough; picking its most
flattering invocation would be measurement by selection.

ADVISORY BY DEFAULT
===================
Most sweeps in this tree are SILENT today, so failing on that would make this
permanently red and tell nobody anything. rc 0 = surveyed; rc 2 = surveyed
nothing. ``--silent-set PATH`` turns it into a ratchet for a caller that wants
one.

THE BOUND IS A NAMED SET, NOT A COUNT (vibe-ic#1410 follow-up)
==============================================================
``--max-silent N`` was the first bound and it was wrong in a way that took a
repair to expose. A COUNT cannot tell "a new sweep went silent" from "something
that legitimately grew", and it is blind the moment one member swaps for
another: 28 -> 28 with a different member is invisible to a number and obvious
to a set.

MEASURED, ONE FILE, BOTH DIRECTIONS. ``task_nature_route`` took the count from
27 to 28 without going silent. Until ``ebe08a870`` its CLI died on
``UnboundLocalError`` for every invocation without ``--json`` -- a defect present
since the file's first commit -- so this survey classified it NOT_DRIVABLE and
it never entered the denominator at all. Repairing the crash moved it into
``driven``, where a silence that had always been there became visible. Nothing
about its reporting changed. The tree got strictly better and the gate went red:
a ratchet that punishes tightening, which is a defect this repository has been
bitten by before.

So the bound is the SET OF NAMES in ``sweep_silence_register.json``:

  * a SILENT sweep named in NEITHER list is UNREGISTERED and FAILS (rc 1), even
    when the total has not moved -- which is the case no count can reach;
  * a registered sweep that STOPS being silent is reported as removable and is
    NEVER a failure. THE ASYMMETRY IS DELIBERATE AND IS WRITTEN HERE RATHER THAN
    LEFT TO BE INFERRED: the register records a defect, and a defect that has
    been repaired must not be the thing that reddens the gate. Shrinking it is
    the point of having it.

The register carries TWO lists because there are two different claims and
collapsing them is what would make it worthless later:

  ``permitted``               a claim that this sweep's silence is LEGITIMATE,
                              with the measurement that argues it: handed an
                              EMPTY corpus it REFUSES rather than returning the
                              same rc 0 it returns over a populated one, so its
                              clean exit cannot be reached without reading
                              input and is not confusable with a no-input run.
  ``known_silent_untriaged``  NOT a claim of legitimacy. Recorded, with the
                              measurement that DISQUALIFIES it, so the gate is
                              not born red over a backlog this change does not
                              triage -- the same reason the first bound chose a
                              ratchet over ``--strict``. Printed as debt on
                              every run and bounded by identity like the rest.

A ``permitted`` entry with no written argument is REFUSED (rc 2) rather than
honoured: an entry nobody can justify is precisely the thing that makes a
register worthless, so it may not silence this gate by sitting in the file.

Usage:
    python3 sweep_reach_survey.py                       # survey programs/
    python3 sweep_reach_survey.py --json report.json    # + machine-readable
    python3 sweep_reach_survey.py --only perc_corpus_sweep.py --only rom_init_lint.py
    python3 sweep_reach_survey.py --silent-set sweep_silence_register.json
    python3 sweep_reach_survey.py --empty-corpus dirs   # the CONTRAST number
    python3 sweep_reach_survey.py --empty-corpus none   # "I was given nothing"

THE AGGREGATION RULE IS THE MEASUREMENT
=======================================
The per-program verdict is decided by the LEAST flattering invocation, and on
this tree that rule is the difference between 8/35 and 14/35 — it changes 6 real
programs. It is a rule inside the instrument that moves the published number, so
it is controlled in ``tests/test_sweep_reach_aggregation_control.py`` against
both fixtures AND the real corpus, rather than only described here.
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _sweep_reach as _sr  # noqa: E402
import _vacuous_exit as _vx  # noqa: E402

GATE = "sweep_reach_survey"

#: Multi-valued CLI names that denote the CORPUS. Anything else repeatable is a
#: configuration list and does not make a program a sweep.
TARGET_POSITIONALS = frozenset({
    "paths", "files", "targets", "projects", "dirs", "inputs", "transcripts",
    "prompts", "script", "program"})
TARGET_OPTIONS = frozenset({
    "--rtl", "--rtl-file", "--rtl-files", "--files", "--paths", "--cov",
    "--under", "--doc", "--lef", "--tech-lef", "--spice", "--macro-lef",
    "--spec", "--mask", "--output", "--required"})

#: Tokens meaning the program never got as far as reading the targets. Such a
#: run says nothing about the program's zero-reach behaviour.
_UNREAD_TOKENS = ("errno", "is a directory", "no such file", "cannot read",
                  "cannot parse", "no file matches", "error reading",
                  "error parsing", "not found:")

_PROBES = {
    "probe_inv.v": ("// zero-reach probe: valid RTL carrying no construct a "
                    "rule keys on\nmodule probe_inv (input wire a, output wire y);\n"
                    "  assign y = ~a;\nendmodule\n"),
    "probe_and2.v": ("module probe_and2 (input wire a, input wire b, "
                     "output wire y);\n  assign y = a & b;\nendmodule\n"),
    "probe_buf.v": ("module probe_buf (input wire a, output wire y);\n"
                    "  assign y = a;\nendmodule\n"),
}


# ------------------------------------------------------------------ discovery
def sweep_shape(path: Path) -> Optional[Dict[str, Any]]:
    """The corpus-taking CLI shape of ``path``, or None if it is not a sweep."""
    try:
        tree = ast.parse(path.read_text(errors="ignore"))
    except (OSError, SyntaxError):
        return None
    has_parser = False
    positionals: List[str] = []
    options: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if fname == "ArgumentParser":
            has_parser = True
        if fname != "add_argument" or not node.args:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        name = first.value
        nargs = action = None
        for kw in node.keywords:
            if kw.arg == "nargs" and isinstance(kw.value, ast.Constant):
                nargs = kw.value.value
            if kw.arg == "action" and isinstance(kw.value, ast.Constant):
                action = kw.value.value
        multi = (nargs in ("*", "+")
                 or (isinstance(nargs, int) and nargs > 1)
                 or action == "append")
        if not multi:
            continue
        if name.startswith("-"):
            if name in TARGET_OPTIONS:
                options.append(name)
        elif name in TARGET_POSITIONALS:
            positionals.append(name)
    if not has_parser or not (positionals or options):
        return None
    return {"positionals": sorted(set(positionals)),
            "options": sorted(set(options))}


def discover(programs_dir: Path, only: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    """Every sweep-shaped program under ``programs_dir``, by filename."""
    out: Dict[str, Dict[str, Any]] = {}
    for p in sorted(programs_dir.glob("*.py")):
        if p.name.startswith("_"):
            continue                      # shared helper, not a CLI
        if only and p.name not in only:
            continue
        shape = sweep_shape(p)
        if shape:
            out[p.name] = shape
    return out


# -------------------------------------------------------------------- driving
#: The corpora this survey can be pointed at.
#:   ``populated``   three readable trivial modules — "I read every target and
#:                   judged none of them", the shape this work is about.
#:   ``empty:dirs``  three readable directories containing nothing — "I was
#:                   handed targets and there was nothing in them".
#:   ``empty:none``  no targets at all — "I was given nothing".
#: The last two are the CONTRAST the populated number is quoted against, so they
#: are produced by this instrument rather than described in a commit message.
CORPORA = ("populated", "dirs", "none")


def make_corpus(root: Path, empty: Optional[str] = None) -> Tuple[List[str], List[str]]:
    """Write the zero-reach probe corpus; return (file targets, dir targets).

    ``empty="dirs"`` writes the same three directories with no file in them;
    ``empty="none"`` writes nothing and returns no targets at all.
    """
    if empty == "none":
        return [], []
    files, dirs = [], []
    for i, (name, body) in enumerate(sorted(_PROBES.items())):
        d = root / f"p{i}"
        d.mkdir(exist_ok=True)
        dirs.append(str(d))
        if empty == "dirs":
            continue
        (root / name).write_text(body)
        files.append(str(root / name))
        (d / name).write_text(body)
    return files, dirs


def _invocations(program: Path, shape: Dict[str, Any],
                 files: List[str], dirs: List[str]) -> Dict[str, List[str]]:
    cmds: Dict[str, List[str]] = {}
    if shape["positionals"]:
        built = {"positional/files": [str(program)] + files,
                 "positional/dirs": [str(program)] + dirs}
    else:
        opt = shape["options"][0]
        built = {f"{opt}/files": [str(program)] + sum(([opt, t] for t in files), []),
                 f"{opt}/dirs": [str(program)] + sum(([opt, t] for t in dirs), [])}
    # An arg shape with no targets left in it is not that shape any more, it is
    # the no-targets shape wearing its label. Drop it UNLESS both are empty,
    # which is the deliberate `empty:none` corpus and must still be driven once.
    for label, cmd in built.items():
        if len(cmd) > 1 or not (files or dirs):
            cmds[label] = cmd
    return cmds


def classify_run(rc: Any, out: str, err: str) -> Tuple[str, str]:
    """``(verdict, why)`` for ONE invocation. Verdict in DISCLOSES/SILENT/skip."""
    both = f"{out}\n{err}"
    low = both.lower()
    if rc in ("TIMEOUT", "ERROR"):
        return "NOT_DRIVABLE", f"invocation {str(rc).lower()}"
    if "Traceback (most recent call last)" in both:
        return "NOT_DRIVABLE", "crashed on the probe corpus"
    if any(ln.startswith("usage:") for ln in both.splitlines()) and "error: " in both:
        return "NOT_DRIVABLE", "argparse refused this arg shape"
    if any(tok in low for tok in _UNREAD_TOKENS):
        return "NOT_DRIVABLE", "could not read the supplied targets"
    if rc == _vx.RC_FAIL:
        return "NOT_DRIVABLE", "the rule FIRED (rc 1) — this run was not zero-reach"
    if rc == _vx.RC_VACUOUS:
        return "DISCLOSES", "rc 2"
    if any(ln.lstrip().startswith(_vx.VACUOUS_STDOUT_SENTINEL)
           for ln in both.splitlines()):
        return "DISCLOSES", "VACUOUS_PASS sentinel"
    if rc == _vx.RC_PASS:
        return "SILENT", "rc 0 with no VACUOUS_PASS sentinel"
    return "NOT_DRIVABLE", f"unexpected rc {rc}"


def survey(programs_dir: Path, only: Optional[List[str]] = None,
           timeout: int = 90, empty_corpus: Optional[str] = None) -> Dict[str, Any]:
    """Discover, drive and classify. Returns the report document."""
    found = discover(programs_dir, only=only)
    reach = _sr.SweepReach(unit="sweep-shaped program",
                           decision_points=("zero_reach_run",))
    rows: List[Dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="sweep_reach_survey_") as tmp:
        files, dirs = make_corpus(Path(tmp), empty=empty_corpus)
        for name, shape in found.items():
            attempts = []
            verdicts = set()
            for label, cmd in _invocations(programs_dir / name, shape,
                                           files, dirs).items():
                try:
                    proc = subprocess.run([sys.executable] + cmd,
                                          cwd=str(programs_dir), text=True,
                                          capture_output=True, timeout=timeout)
                    rc: Any = proc.returncode
                    out, err = proc.stdout, proc.stderr
                except subprocess.TimeoutExpired:
                    rc, out, err = "TIMEOUT", "", ""
                except OSError as exc:
                    rc, out, err = "ERROR", "", str(exc)
                verdict, why = classify_run(rc, out, err)
                attempts.append({"invocation": label, "rc": rc,
                                 "verdict": verdict, "why": why,
                                 "first_line": (out + err).strip().splitlines()[:1]})
                verdicts.add(verdict)

            # Conservative: one witness of a silent zero-reach run decides it.
            if "SILENT" in verdicts:
                final = "SILENT"
            elif "DISCLOSES" in verdicts:
                final = "DISCLOSES"
            else:
                final = "NOT_DRIVABLE"

            # Name the attempt the verdict came FROM. Quoting the first
            # attempt's output beside a verdict another attempt decided is how
            # a reader gets shown evidence for a claim it does not support.
            deciding = next(a for a in attempts if a["verdict"] == final)

            if final == "NOT_DRIVABLE":
                reach.not_reached(
                    name, "the generic probe corpus could not drive this sweep "
                          "to a zero-reach run")
            else:
                reach.reached(name, point="zero_reach_run")
            rows.append({"program": name, "verdict": final,
                         "deciding_invocation": deciding["invocation"],
                         "evidence": deciding["first_line"],
                         "attempts": attempts})

    if not found:
        reach.declare_empty_corpus(
            f"no sweep-shaped program was discovered under {programs_dir}")

    driven = [r for r in rows if r["verdict"] != "NOT_DRIVABLE"]
    discloses = [r for r in driven if r["verdict"] == "DISCLOSES"]
    silent = [r for r in driven if r["verdict"] == "SILENT"]
    doc: Dict[str, Any] = {
        "survey": GATE,
        "programs_dir": str(programs_dir),
        # Which corpus produced this ratio. A populated-corpus number and an
        # empty-corpus number are answers to different questions and must never
        # be read off the same unlabelled field.
        "corpus": f"empty:{empty_corpus}" if empty_corpus else "populated",
        "discovered": len(found),
        "driven": len(driven),
        "discloses": len(discloses),
        "silent": len(silent),
        "not_drivable": len(rows) - len(driven),
        "ratio": (f"{len(discloses)}/{len(driven)}" if driven
                  else "UNDEFINED — no sweep was driven to a zero-reach run"),
        "rows": rows,
    }
    _sr.attach(doc, reach)
    doc["_reach"] = reach
    return doc


# ------------------------------------------------------------------ the bound
#: The two lists a register may carry. Both PERMIT today's silence; only the
#: first is a CLAIM about it. Kept as one tuple so a third list cannot be added
#: in the file and silently honoured by a reader that never heard of it.
REGISTER_LISTS = ("permitted", "known_silent_untriaged")


class RegisterRefused(Exception):
    """The register could not be used as a bound, so nothing was bounded.

    Raised rather than returned: "I could not read the bound" must not reach a
    caller on the same path as "I read it and nothing was unregistered", which
    is the vacuous pass this survey exists to remove one level down.
    """


def load_silent_set(path: Path) -> Dict[str, Dict[str, Any]]:
    """``{program: entry}`` from ``path``, or raise :class:`RegisterRefused`.

    A ``permitted`` entry MUST carry a non-empty ``why_permitted``. The rule is
    enforced here, at load, rather than at comparison time: an unjustified name
    must not be able to silence this gate merely by being present in the file.
    ``known_silent_untriaged`` entries make no claim, so they carry
    ``why_not_permitted`` instead and are held to that key.
    """
    try:
        doc = json.loads(path.read_text())
    except OSError as exc:
        raise RegisterRefused(f"cannot read {path}: {exc}") from exc
    except ValueError as exc:
        raise RegisterRefused(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise RegisterRefused(f"{path} must hold an object, not "
                              f"{type(doc).__name__}")
    unknown = [k for k in doc
               if k in ("permitted", "known_silent_untriaged", "permited")
               and k not in REGISTER_LISTS]
    if unknown:
        raise RegisterRefused(f"{path} carries unknown list(s): {unknown}")
    out: Dict[str, Dict[str, Any]] = {}
    for which in REGISTER_LISTS:
        block = doc.get(which, {})
        if not isinstance(block, dict):
            raise RegisterRefused(f"{path}: '{which}' must be an object")
        need = "why_permitted" if which == "permitted" else "why_not_permitted"
        for name, entry in block.items():
            if not isinstance(entry, dict):
                raise RegisterRefused(f"{path}: '{which}.{name}' must be an object")
            if not str(entry.get(need, "")).strip():
                raise RegisterRefused(
                    f"{path}: '{which}.{name}' carries no '{need}'. An entry "
                    f"nobody can justify may not silence this gate by sitting "
                    f"in the register -- write the argument or take the name out")
            if name in out:
                raise RegisterRefused(
                    f"{path}: '{name}' is in both lists; it cannot be both a "
                    f"claim of legitimacy and a refusal to make one")
            out[name] = dict(entry, _list=which)
    return out


def compare_to_register(doc: Dict[str, Any],
                        register: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """What the measured SILENT set and the register say about each other.

    ``unregistered`` is the only failing class. ``tightened`` is a registered
    name that is no longer silent, and it is deliberately NOT a failure: the
    register records a defect, and a repaired defect must never be the thing
    that reddens the gate.
    """
    silent = {r["program"] for r in doc["rows"] if r["verdict"] == "SILENT"}
    return {
        "unregistered": sorted(silent - set(register)),
        "tightened": sorted(set(register) - silent),
        "held": sorted(silent & set(register)),
        "permitted_now_silent": sorted(
            n for n in silent & set(register)
            if register[n].get("_list") == "permitted"),
        "untriaged_now_silent": sorted(
            n for n in silent & set(register)
            if register[n].get("_list") == "known_silent_untriaged"),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--programs-dir", default=str(Path(__file__).resolve().parent),
                    help="directory of programs to survey (default: this one)")
    ap.add_argument("--only", action="append", default=[], metavar="NAME.py",
                    help="restrict the survey to these filenames (repeatable)")
    ap.add_argument("--json", metavar="PATH",
                    help="write the report here ('-' = stdout)")
    ap.add_argument("--timeout", type=int, default=90,
                    help="per-invocation timeout in seconds")
    ap.add_argument("--silent-set", metavar="PATH", default=None,
                    help="ratchet: FAIL when a driven sweep is SILENT and is "
                         "named in NEITHER list of the register at PATH. The "
                         "bound is the SET, so a member swapped for another is "
                         "refused at an unchanged total; a member that stops "
                         "being silent is reported and is never a failure. "
                         "(default: advisory, never fails on this)")
    ap.add_argument("--empty-corpus", choices=("dirs", "none"), default=None,
                    help="drive the sweeps against an EMPTY corpus instead of "
                         "the populated probe corpus: 'dirs' = three readable "
                         "but empty directories, 'none' = no targets at all. "
                         "This is the contrast the populated ratio is quoted "
                         "against; it is a switch so the counter-number is "
                         "re-derivable rather than asserted.")
    args = ap.parse_args(argv)

    doc = survey(Path(args.programs_dir), only=args.only or None,
                 timeout=args.timeout, empty_corpus=args.empty_corpus)
    reach: _sr.SweepReach = doc.pop("_reach")

    passed = True
    cmp: Optional[Dict[str, Any]] = None
    if args.silent_set is not None:
        try:
            register = load_silent_set(Path(args.silent_set))
        except RegisterRefused as exc:
            # rc 2, never rc 0: the bound could not be applied, so NOTHING was
            # bounded, and that must not reach a reader as "nothing was
            # unregistered". Printed before the report so the refusal cannot be
            # lost under 28 rows of survey output.
            print(f"REFUSED: {exc}", file=sys.stderr)
            print(f"[VACUOUS] {GATE} — the silent-set bound could not be read, "
                  f"so no sweep was bounded; this is NOT a pass", file=sys.stderr)
            return _vx.RC_VACUOUS
        cmp = compare_to_register(doc, register)
        doc["silent_set"] = {"path": str(args.silent_set), **cmp}
        passed = not cmp["unregistered"]

    if args.json:
        text = json.dumps(doc, indent=2, sort_keys=True)
        if args.json == "-":
            print(text)
        else:
            Path(args.json).write_text(text + "\n")

    if args.json != "-":
        print(reach.verdict_line(GATE, passed))
        print(f"  {reach.line()}")
        print(f"  corpus: {doc['corpus']}")
        print(f"  discovered {doc['discovered']} sweep-shaped program(s); "
              f"drove {doc['driven']} to a zero-reach run "
              f"({doc['not_drivable']} not drivable by the probe corpus)")
        print(f"  can distinguish 'ran and found nothing' from 'never reached "
              f"the check': {doc['ratio']}")
        for row in sorted(doc["rows"], key=lambda r: (r["verdict"], r["program"])):
            if row["verdict"] == "NOT_DRIVABLE":
                continue
            ev = (row["evidence"] or [""])[0][:88]
            print(f"    [{row['verdict']:12s}] {row['program']}  "
                  f"({row['deciding_invocation']})")
            if ev:
                print(f"        | {ev}")
    if cmp is not None and args.json != "-":
        print(f"  silent-set bound: {len(cmp['held'])} of {doc['silent']} silent "
              f"sweep(s) are registered "
              f"({len(cmp['permitted_now_silent'])} permitted with a written "
              f"argument, {len(cmp['untriaged_now_silent'])} recorded UNTRIAGED "
              f"and blessed by nobody)")
        if cmp["tightened"]:
            # NOT a failure, and said in the words that make that unmistakable.
            # A register entry is a recorded defect; a repaired defect reddening
            # the gate is the exact shape this bound replaced.
            print(f"  [TIGHTENED] {len(cmp['tightened'])} registered sweep(s) "
                  f"are no longer SILENT and can be removed from the register — "
                  f"this is NOT a failure: "
                  f"{', '.join(cmp['tightened'])}")
    if not passed and cmp is not None:
        print(f"FAIL: {len(cmp['unregistered'])} driven sweep(s) are SILENT and "
              f"named in NEITHER list of {args.silent_set}:", file=sys.stderr)
        for name in cmp["unregistered"]:
            row = next(r for r in doc["rows"] if r["program"] == name)
            ev = (row["evidence"] or [""])[0][:88]
            print(f"   {name}  ({row['deciding_invocation']})  | {ev}",
                  file=sys.stderr)
        print("  A sweep that reads a populated corpus, judges none of it and "
              "exits 0 clean is indistinguishable from one that never reached "
              "its check. Give it the rc-2 / VACUOUS_PASS disclosure, or add it "
              "to the register WITH the argument for why its silence is "
              "legitimate. The bound is a SET: do not widen a number.",
              file=sys.stderr)

    reach.announce(GATE, passed=passed)
    return reach.exit_code(passed)


if __name__ == "__main__":
    raise SystemExit(main())
