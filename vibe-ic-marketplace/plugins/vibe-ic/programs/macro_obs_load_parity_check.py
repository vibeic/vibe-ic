#!/usr/bin/env python3
"""The obstructions the LEF DECLARES vs the obstructions the tool can LOAD.

THIS GATE BLOCKS (rc=1) — a statement about this program's VERDICT SEVERITY,
not about where its verdict is consumed. Those are two different axes, and the
second one is declared immediately below: a gate that says nothing about it is
the defect `flow_gate_enforcement_audit` exists to catch, and silence there is
not a decision.

ENFORCEMENT: advisory — no runner spawns this gate inline, so it cannot stop
step 15 while step 15 is running. What it DOES have, and this is why `advisory`
here is not "ignorable": it is a gate leg of step 15 in the flow's BLOCKING
slot (`program_exit_zero`, never `advisory_program_exit_zero`), so when
`flow_compliance_check` evaluates that clause an rc=1 FAILs the step, and that
verdict reaches the run's headline through
`reports/audit/phase23_completion_audit.json`, which
`phase3_one_shot_runner._derive_headline_verdict` reads. MEASURED on a copy of
a published run-root: the evaluator's own step report lists this program under
step 15's `measures`. What `flow_gate_enforcement_audit` scores is the narrower
question "can this verdict stop the step it guards", and the answer there is
no; `advisory` is that audit's token for that answer.

WHY IT IS NOT PROMOTED TO INLINE-BLOCKING, MEASURED. The one inline pattern the
phase-3 runner has — `_DECLARED_SIGNOFF_GATES` / `_run_declared_signoff_gate` —
routes every rc other than 0 and 1 to BLOCKED (non-green), deliberately, because
for a sign-off gate "could not check" is not a pass. This gate's rc=2 means
something different: no LEF, or no macro declares an OBS, i.e. there was
legitimately no obstruction to lose. Over the 15 published phase-3 run-roots
under `benchmark-data/ic`, invoked exactly as a caller would: rc 2 on 12, rc 1
on 3, rc 0 on none. Wiring it into that table would therefore turn 12 of 15
published runs non-green for owning no macro obstruction, which is the false
alarm this gate's own rc-2 branch was written to avoid. The flow's
rc=2 -> VACUOUS_PASS encoding is the correct consumer; that table is not.
Promotion needs an inline consumer that PRESERVES rc=2 -> VACUOUS_PASS at the
step that owns the subject — a flow-owner change with its own blast radius, not
a side effect of recording this decision.

WHY IT EXISTS
-------------
Every other obstruction check in this plugin reads the LEF with the plugin's
own parser and then reasons about what it found. That parser is not the one the
flow runs on. When the two disagree, every downstream verdict is computed over
geometry the tool never had — and each verdict is individually correct, which is
why nothing catches it.

MEASURED, on a synthetic three-point control (`tests/`, and reproducible in
seconds against a real reader). One macro abstract, 64 `RECT` lines inside its
`OBS`, of which the FIRST names a LEF-spec layer type the tech LEF does not
declare:

    variant                                  tool loads    reader diagnostic
    as shipped                                        0    undefined layer (…)
    that one OBS entry removed                       63    none
    tech LEF given the layer declaration             64    none

One unresolvable layer costs ALL 64 rectangles, not the one that named it. The
reader emits a single `undefined layer (...) referenced` warning, **stops
reading the section there, and returns success**. From that point on every stage
treats a fully-obstructed macro as fully routable: straps and vias are emitted
across a sealed footprint — metal that is illegal AND does not connect.

THE COST IS TRUNCATION FROM THAT ENTRY ONWARD, and the position decides how much
it is. VERIFIED by moving one unresolvable entry within an otherwise identical
63-rect section:

    entry position      rects the reader kept
    first                                   0
    after 30 of 63                         30
    last                                   63

So "the section is discarded" over-reports whenever the entry is not first, and
"only that entry is dropped" under-reports whenever it is not last. This gate
models the walk rather than either slogan. The FIRST position is the common one
in practice — the layer stating a macro's own extent is conventionally declared
before the metal layers — which is why the measured field case lost everything.

The trigger is routine, not exotic. The LEF spec defines layer TYPEs that a tech
LEF is NOT REQUIRED to declare, and a macro abstract may legitimately open its
OBS section on one of them. So this is a standing channel for silent geometry
loss, not a one-off bad file.

WHAT IT MEASURES
----------------
Per macro that declares an OBS:

    parsed_obs_rects    what THIS PLUGIN reads from the LEF text
    loadable_obs_rects  what a reader keeps — the rects declared BEFORE the
                        first entry it cannot resolve
    obs_rects_lost      the difference, which is the finding

and it FAILS when those two disagree.

`parsed_obs_rects` is the plugin's own count, not the raw `RECT` line count, and
they are not always equal: `parse_macro_obs` drops rects on the layer type that
states a macro's own extent, so on the control above it reports 63 where the
text has 64. That is deliberate and it is the RIGHT denominator here — this gate
compares what the plugin believes it has against what the tool can load, which
is the disagreement that goes unnoticed. On the control the comparison is
63 vs 0.

That is the entire comparison, and it is
the one thing that makes this defect class un-repeatable rather than fixed once:
a future reader bug of the same shape moves `loadable` away from `parsed` again
and this gate says so.

TWO INDEPENDENT LEGS, and neither is trusted alone:

  * STATIC (always available). A layer referenced by an `OBS` entry is resolvable
    only if some LEF that was read DECLARES it. Layer declarations are
    distinguishable from layer references by LEF grammar alone: a declaration is
    `LAYER <name>` on its own, closed by `END <name>`; a reference inside a
    MACRO's PIN/OBS body is `LAYER <name> ;`. MACRO blocks are removed before
    the declaration scan, so a reference can never be mistaken for a declaration.

  * CORROBORATING (when a tool log exists). The reader announces the loss before
    swallowing it. Any logged `undefined layer (<name>) referenced` names a layer
    the run could not resolve, MEASURED rather than inferred. Logged names are
    unioned into the finding, so a layer this program's static leg could not
    reach — one referenced by a file the run read and the project no longer
    holds — is still reported.

chip-AGNOSTIC and PDK-AGNOSTIC. Pure LEF grammar plus a tool diagnostic string.
No design, PDK, vendor, layer or SKU literal appears in the detection logic:
the rule is "referenced but not declared", and the layer that trips it is
whatever the input names.

USAGE
-----
    macro_obs_load_parity_check.py <project_dir> [--json OUT]
                                   [--lef PATH ...] [--log PATH ...]

    Discovery reads BOTH `*.lef` and `*.tlef` under the project. `--lef` accepts
    either; pass the tech LEF explicitly when the PDK is mounted rather than
    vendored, because a mounted PDK is outside the project and no glob reaches
    it.

    exit 0 = for every macro, what the LEF declares is what a reader can load
    exit 1 = at least one macro's OBS section would be discarded (BLOCKING)
    exit 2 = could not be determined — no LEF, or no macro declares an OBS, or
             the LEF set that was read declares NO LAYER AT ALL (the tech LEF is
             outside the project tree, so nothing could resolve). NEVER a
             vacuous pass: "no obstruction was lost", "there was no obstruction
             to lose" and "nothing here could tell you either way" are three
             different sentences and do not share an exit code.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from macro_obs_geometry_intersect_check import (      # noqa: E402
    _MACRO_RE, _MACRO_DECLARATION_SITES, _typed_refusal,
    macro_declaration_sites, parse_macro_obs)
import _flow_reason_taxonomy as _reason_taxonomy  # noqa: E402  vibe-ic#1978

# A layer DECLARATION: `LAYER <name>` alone on its line, closed by `END <name>`.
# A layer REFERENCE inside a MACRO body is `LAYER <name> ;` — the semicolon is
# the whole difference, and MACRO blocks are stripped before this runs anyway.
_LAYER_DECL_RE = re.compile(r"^[ \t]*LAYER[ \t]+(\S+)[ \t]*$", re.M)

# An OBS body and the layers it references. `parse_macro_obs` deliberately drops
# `OVERLAP` rects (that layer states the macro's own extent, not metal), but the
# READER does not get to skip the entry — an unresolvable layer there is exactly
# what discards the section. So this scan keeps every referenced layer.
_OBS_BODY_RE = re.compile(r"^\s*OBS\s*$(.*?)(?=^\s*(?:PIN|END)\b)", re.S | re.M)
_LAYER_REF_RE = re.compile(r"^\s*LAYER\s+(\S+)\s*;")
_RECT_LINE_RE = re.compile(r"\s*RECT\s+[\d.eE+-]+\s+[\d.eE+-]+\s+"
                           r"[\d.eE+-]+\s+[\d.eE+-]+\s*;")

# The extent-layer exclusion `parse_macro_obs` applies, mirrored here so
# `parsed` and `loadable` are counted the same way and are comparable.
_EXTENT_LAYER = "OVERLAP"

# The reader's own announcement of WHICH LEF it loaded. Same doctrine as the
# undefined-layer match below: a TOOL diagnostic string, not a design, PDK or
# vendor literal — the path it yields is whatever the run happened to load. It
# exists so that when this gate cannot see a layer declaration, it can NAME the
# file that would have supplied one instead of asking the reader to guess.
_LEF_LOAD_RE = re.compile(r"LEF\s+file\s*:\s*(\S+?\.(?:tlef|lef))\b", re.I)


def tech_lefs_named_by_tool_log(log_texts) -> "Set[str]":
    """Absolute LEF paths the run's own tool logs record having loaded (PURE)."""
    out: Set[str] = set()
    for t in log_texts:
        for m in _LEF_LOAD_RE.finditer(t):
            out.add(m.group(1).rstrip(","))
    return out


# The reader's own announcement of the loss. Matched on the SEMANTIC text rather
# than only on a message ID, so a renumbered or reworded-but-equivalent
# diagnostic is still read.
_UNDEFINED_LAYER_RE = re.compile(
    r"undefined\s+layer\s*\(\s*([^)]+?)\s*\)\s*referenced", re.I)


def declared_layers(lef_text: str) -> Set[str]:
    """Every layer this LEF DECLARES, lower-cased.

    MACRO blocks are removed first: a macro's PIN and OBS bodies are full of
    `LAYER <name> ;` references, and counting one of those as a declaration
    would let a macro vouch for the very layer whose absence is the defect."""
    if not isinstance(lef_text, str):
        return set()
    body = _MACRO_RE.sub("", lef_text)
    out: Set[str] = set()
    for m in _LAYER_DECL_RE.finditer(body):
        name = m.group(1)
        if re.search(rf"^\s*END\s+{re.escape(name)}\s*$", body, re.M):
            out.add(name.lower())
    return out


def obs_entries(lef_text: str) -> Dict[str, List[Tuple[str, int]]]:
    """{master: [(layer, n_rects), ...]} for a MACRO's OBS, IN DECLARATION ORDER.

    ORDER IS THE WHOLE POINT. The reader walks the OBS geometry items in the
    order they are written and stops at the first it cannot resolve, so the
    cost of an unresolvable layer is everything from that entry ONWARD — not
    the section, and not just that entry. VERIFIED against the reader by moving
    one unresolvable entry within an otherwise identical 63-rect section:

        entry position      rects the reader kept
        first                                   0
        after 30 of 63                         30
        last                                   63

    A position-blind reading gets this wrong in both directions. "The section
    is discarded" over-reports whenever the entry is not first; "only that
    entry is dropped" under-reports whenever it is not last. The FIRST position
    is the common one in practice, because the layer that states a macro's own
    extent is conventionally declared before the metal layers — which is why
    the measured field case lost everything.

    Layers whose rects `parse_macro_obs` drops are still listed, because the
    reader does not get to drop them: an unresolvable layer is what stops the
    walk regardless of whether this plugin would have counted its rects."""
    out: Dict[str, List[Tuple[str, int]]] = {}
    if not isinstance(lef_text, str):
        return out
    for mm in _MACRO_RE.finditer(lef_text):
        master, body = mm.group(1), mm.group(2)
        om = _OBS_BODY_RE.search(body)
        if not om:
            continue
        entries: List[Tuple[str, int]] = []
        layer = None
        n = 0
        for line in om.group(1).splitlines():
            lm = _LAYER_REF_RE.match(line)
            if lm:
                if layer is not None:
                    entries.append((layer, n))
                layer, n = lm.group(1), 0
                continue
            if layer is not None and _RECT_LINE_RE.match(line):
                n += 1
        if layer is not None:
            entries.append((layer, n))
        if entries:
            out[master] = entries
    return out


def obs_layers_referenced(lef_text: str) -> Dict[str, List[str]]:
    """{master: [layer, ...]} — the layer names only, in declaration order."""
    out: Dict[str, List[str]] = {}
    for master, entries in obs_entries(lef_text).items():
        seen: List[str] = []
        for layer, _n in entries:
            if layer not in seen:
                seen.append(layer)
        out[master] = seen
    return out


def logged_undefined_layers(log_texts: Sequence[str]) -> Set[str]:
    """Layers the TOOL said it could not resolve. Measured, not inferred."""
    out: Set[str] = set()
    for t in log_texts:
        if not isinstance(t, str):
            continue
        for m in _UNDEFINED_LAYER_RE.finditer(t):
            out.add(m.group(1).strip().lower())
    return out


def audit(lef_texts: Sequence[str], lef_labels: Sequence[str] = (),
          log_texts: Sequence[str] = ()) -> Dict[str, Any]:
    """`parsed` vs `loadable`, per macro that declares an OBS."""
    declared: Set[str] = set()
    for t in lef_texts:
        declared |= declared_layers(t)

    from_log = logged_undefined_layers(log_texts)

    parsed: Dict[str, Tuple[str, int]] = {}      # master -> (label, rect count)
    entries_by_master: Dict[str, List[Tuple[str, int]]] = {}
    for i, t in enumerate(lef_texts):
        label = str(lef_labels[i]) if i < len(lef_labels) else f"LEF#{i + 1}"
        for master, entry in parse_macro_obs(t).items():
            if entry["obs"]:
                parsed[master] = (label, len(entry["obs"]))
        for master, entries in obs_entries(t).items():
            entries_by_master.setdefault(master, entries)

    def _unresolvable(layer: str) -> bool:
        return layer.lower() not in declared or layer.lower() in from_log

    findings: List[Dict[str, Any]] = []
    for master in sorted(entries_by_master):
        entries = entries_by_master[master]
        refs = []
        for ly, _n in entries:
            if ly not in refs:
                refs.append(ly)
        unresolved = [ly for ly in refs if _unresolvable(ly)]
        if not unresolved:
            continue
        label, n_parsed = parsed.get(master, ("(none)", 0))
        # TRUNCATION, NOT DELETION. The reader stops at the first entry it
        # cannot resolve, so what survives is everything BEFORE it. Counted the
        # same way `parse_macro_obs` counts — extent-layer rects excluded — so
        # `parsed` and `loadable` are the same kind of number and their
        # difference is the loss.
        kept = 0
        stop_at = None
        for pos, (ly, n) in enumerate(entries):
            if _unresolvable(ly):
                stop_at = pos
                break
            if ly.upper() != _EXTENT_LAYER:
                kept += n
        findings.append({
            "master": master,
            "lef": label,
            "parsed_obs_rects": n_parsed,
            "loadable_obs_rects": kept,
            "obs_rects_lost": max(0, n_parsed - kept),
            # Where the walk stops decides the cost, so it is reported.
            "truncated_at_entry": stop_at,
            "obs_entry_count": len(entries),
            "obs_layers_referenced": refs,
            "unresolvable_layers": unresolved,
            "corroborated_by_tool_log": sorted(
                ly for ly in unresolved if ly.lower() in from_log),
        })

    return {
        "layers_declared_by_lef_set": sorted(declared),
        "masters_with_obs": sorted(entries_by_master),
        "obs_rects_parsed_total": sum(n for _l, n in parsed.values()),
        "obs_rects_lost_total": sum(f["obs_rects_lost"] for f in findings),
        "undefined_layers_in_tool_log": sorted(from_log),
        "tool_logs_read": len(log_texts),
        # DEGRADE LOUDLY. When the LEF set that was read declares NO layers at
        # all, "referenced but not declared" is true of every layer by
        # construction and the comparison was never actually performed. That is
        # a different fact from a resolvable set with a gap in it, so it is
        # recorded rather than left to be inferred from an empty list.
        "layer_declarations_absent": not declared,
        "tech_lef_named_by_tool_log": sorted(
            tech_lefs_named_by_tool_log(log_texts)),
        "findings": findings,
    }


def _read(paths: Sequence[Path]) -> Tuple[List[str], List[str]]:
    texts, labels = [], []
    for p in paths:
        try:
            texts.append(p.read_text(errors="replace"))
        except OSError:
            continue
        labels.append(str(p))
    return texts, labels


def discover_lefs(proj: Path) -> List[Path]:
    """EVERY LEF under the project, in a stable order.

    NOT `discover_macro_lefs`. That helper filters to files whose content
    declares a MACRO, which is right for a gate that reads obstructions and
    exactly wrong for this one: the file that DECLARES THE LAYERS is the tech
    LEF, and a tech LEF declares no macro. Filtering on `MACRO` therefore drops
    the only evidence that a layer is resolvable, and every OBS layer then looks
    undeclared — this gate would FAIL every project on earth, which is the
    failure mode a blocking gate can least afford.

    Both roles are needed and neither file type can supply the other's half."""
    #
    # `.tlef` IS INCLUDED, and leaving it out was half of the defect this
    # function's own docstring warns about. The file that declares the layers is
    # conventionally named `<lib>__nom.tlef` — the PDK ships it that way — so a
    # glob of `*.lef` alone cannot see a tech LEF even when the design has
    # VENDORED one under `input/pdk/`, which is the remedy this gate prints.
    # Both suffixes, or the remedy is unreachable.
    out: List[Path] = []
    seen = set()
    for pat in ("input/pdk/**/*.lef", "input/pdk/**/*.tlef",
                "phase3/**/*.lef", "phase3/**/*.tlef",
                "**/*.lef", "**/*.tlef"):
        for p in sorted(proj.glob(pat)):
            rp = p.resolve()
            if rp in seen or not p.is_file():
                continue
            seen.add(rp)
            out.append(p)
    return out


def discover_logs(proj: Path) -> List[Path]:
    """Tool transcripts, if the project kept any. Absence is not a failure —
    the static leg stands alone; the log only ever ADDS evidence."""
    out: List[Path] = []
    seen = set()
    for pat in ("**/*.log", "**/*.rpt"):
        for p in sorted(proj.glob(pat)):
            rp = p.resolve()
            if rp in seen or not p.is_file():
                continue
            seen.add(rp)
            out.append(p)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--lef", dest="lefs", type=Path, action="append",
                    default=None)
    ap.add_argument("--log", dest="logs", type=Path, action="append",
                    default=None)
    ap.add_argument("--json", dest="json_out", type=Path, default=None)
    a = ap.parse_args(argv)

    proj = a.project_dir
    lefs = list(a.lefs or [])
    if not lefs:
        lefs = discover_lefs(proj)
    lef_texts, lef_labels = _read(lefs)
    if not lef_texts:
        # vibe-ic#2013 / #1978 — the refusal is TYPED, and which type depends
        # on a fact the LEF set cannot supply: does this design integrate a
        # macro at all? The flow's own declaration sites answer it (see
        # `_MACRO_DECLARATION_SITES` in the sibling gate). No site, no macro
        # declared, no abstract owed: the design's N/A. A site and still no
        # LEF: a declared macro whose abstract never reached this gate, which
        # is BLOCKED and never an N/A.
        declared = macro_declaration_sites(proj)
        reason = (f"no LEF under {proj}. A run with no LEF is not a run whose "
                  f"obstructions all loaded — it is one this gate could not "
                  f"read. NOT a pass.")
        if declared:
            reason += (f" The project DECLARES a macro at "
                       f"{', '.join(declared)} and no abstract was staged "
                       f"for this gate to read.")
            cls = _reason_taxonomy.BLOCKED_BY_UPSTREAM
        else:
            reason += (f" The project declares no macro at any of "
                       f"{', '.join(_MACRO_DECLARATION_SITES)}, so no abstract "
                       f"is owed: the design integrates no macro.")
            cls = _reason_taxonomy.DESIGN_DECLARED_NA
        print(f"[CANNOT DETERMINE] macro_obs_load_parity: {reason}",
              file=sys.stderr)
        return _typed_refusal(a.json_out, "macro_obs_load_parity", cls, reason)

    logs = list(a.logs or [])
    if not logs:
        logs = discover_logs(proj)
    log_texts, _log_labels = _read(logs)

    rep = audit(lef_texts, lef_labels, log_texts)
    if a.json_out:
        a.json_out.parent.mkdir(parents=True, exist_ok=True)
        a.json_out.write_text(json.dumps(rep, indent=2) + "\n")

    if not rep["masters_with_obs"]:
        # Every LEF under the project was read and none declares an OBS. That
        # is the design's own declaration set, examined in full — the design
        # integrates no obstruction-bearing macro — so the refusal is typed as
        # the design's N/A, not as an error of this gate.
        reason = (f"no macro in the {len(lef_texts)} LEF(s) read declares an "
                  f"OBS. NOT a pass — nothing was compared.")
        print(f"[CANNOT DETERMINE] macro_obs_load_parity: {reason}",
              file=sys.stderr)
        return _typed_refusal(a.json_out, "macro_obs_load_parity",
                              _reason_taxonomy.DESIGN_DECLARED_NA, reason, rep)

    # THE QUESTION COULD NOT BE PUT. `unresolvable` means "referenced by an OBS
    # and declared by no LEF that was read". When the LEF set that was read
    # declares NO layer at all, that predicate is true of EVERY layer for a
    # reason that has nothing to do with the abstract: the file that declares
    # layers is the TECH LEF, and a macro abstract never declares one. A run
    # whose PDK is MOUNTED (the tech LEF lives outside the project tree) rather
    # than VENDORED under `input/pdk/` therefore hands this gate a set with zero
    # declarations, and every OBS layer looks undeclared by construction.
    #
    # That is a measurement-scope failure, not a finding, and it must not be
    # reported as one — an rc=1 here says "this macro's obstructions would be
    # discarded" about geometry the gate never had the means to resolve.
    #
    # THE MEASURED LEG STILL WINS. If a tool log carries the reader's own
    # `undefined layer (...) referenced`, the loss was OBSERVED by the reader
    # and does not depend on this gate's static set at all — so that path keeps
    # its rc=1 below and this branch stands aside for it. Same two-leg doctrine
    # as the rest of this program: the static leg alone cannot convict when the
    # static leg had nothing to read.
    if (not rep["layers_declared_by_lef_set"]
            and not rep["undefined_layers_in_tool_log"]):
        named = rep["tech_lef_named_by_tool_log"]
        where = (" The run's own tool log records loading: "
                 + ", ".join(named[:4])
                 + (f" (+{len(named) - 4} more)" if len(named) > 4 else "")
                 + " — pass that file with --lef, or vendor it under"
                   " input/pdk/, and re-run."
                 if named else
                 " No tool log read here names a LEF that was loaded either, so"
                 " this gate cannot even say which file would answer it. Pass"
                 " the tech LEF the run loads with --lef, or vendor it under"
                 " input/pdk/, and re-run.")
        reason = (f"the {len(lef_texts)} LEF(s) read declare ZERO layers, so "
                  f"every OBS layer is unresolvable by construction and "
                  f"nothing was actually compared. A macro abstract declares "
                  f"no layers; the TECH LEF does.{where} NOT a pass, and NOT "
                  f"a finding.")
        print(f"[CANNOT DETERMINE] macro_obs_load_parity: {reason}",
              file=sys.stderr)
        # An abstract WAS read (the design declares a macro) and the
        # declaration set it must be resolved against is empty: 0 layers is
        # the denominator, and the remedy printed above is the follow-up.
        return _typed_refusal(a.json_out, "macro_obs_load_parity",
                              _reason_taxonomy.ZERO_DENOMINATOR, reason, rep)

    f = rep["findings"]
    if f:
        print(f"[FAIL] {len(f)} macro(s) declare obstruction geometry that a "
              f"reader CANNOT LOAD — {rep['obs_rects_lost_total']} of "
              f"{rep['obs_rects_parsed_total']} parsed OBS rect(s) would be "
              f"discarded:")
        for x in f[:12]:
            corr = (" [corroborated by tool log]"
                    if x["corroborated_by_tool_log"] else "")
            print(f"   macro {x['master']} ({x['lef']}): parsed "
                  f"{x['parsed_obs_rects']} OBS rect(s), loadable "
                  f"{x['loadable_obs_rects']} (lost {x['obs_rects_lost']}) — "
                  f"the read stops at OBS entry {x['truncated_at_entry']} of "
                  f"{x['obs_entry_count']}; OBS references "
                  f"{', '.join(x['obs_layers_referenced'])}; NOT declared by "
                  f"any LEF read: {', '.join(x['unresolvable_layers'])}{corr}")
        if len(f) > 12:
            print(f"   … {len(f) - 12} more")
        print("\n  A reader that meets an unresolvable layer inside an OBS "
              "section STOPS THERE and\n  returns SUCCESS. The cost is not the "
              "one entry that named the layer — it is\n  every obstruction "
              "from that entry ONWARD, including the ones on layers the\n  "
              "tech LEF does declare. When the unresolvable entry is FIRST — "
              "the common case,\n  since the layer stating a macro's own "
              "extent is conventionally declared before\n  the metal layers — "
              "the macro loads with NO obstruction at all. Downstream, a\n  "
              "sealed footprint then reads as fully routable, and straps and "
              "vias are emitted\n  across it: metal that is illegal AND does "
              "not connect.")
        print("\n  Remedy: declare the layer in the tech LEF that the run "
              "loads, or remove the\n  entry from the abstract. Either restores "
              "parity; only the first keeps the\n  obstruction.")
        return 1

    print(f"[PASS] macro_obs_load_parity: {len(rep['masters_with_obs'])} macro(s) "
          f"declare an OBS and every layer they reference is declared by the LEF "
          f"set that was read — {rep['obs_rects_parsed_total']} parsed OBS "
          f"rect(s), 0 lost.")
    print(f"  EVIDENCE: {len(lef_texts)} LEF(s) read declaring "
          f"{len(rep['layers_declared_by_lef_set'])} layer(s); "
          f"{rep['tool_logs_read']} tool log(s) scanned, "
          f"{len(rep['undefined_layers_in_tool_log'])} undefined-layer "
          f"diagnostic(s) found. This covers OBS sections only, and says "
          f"nothing about geometry lost for any other reason.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
