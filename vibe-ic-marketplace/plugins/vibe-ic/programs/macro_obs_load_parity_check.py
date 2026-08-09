#!/usr/bin/env python3
"""The obstructions the LEF DECLARES vs the obstructions the tool can LOAD.

THIS GATE BLOCKS (rc=1).

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
reader emits a single `undefined layer (...) referenced` warning, **discards the
whole OBS section, and returns success**. From that point on every stage treats
a fully-obstructed macro as fully routable: straps and vias are emitted across a
sealed footprint — metal that is illegal AND does not connect.

The trigger is routine, not exotic. The LEF spec defines layer TYPEs that a tech
LEF is NOT REQUIRED to declare, and a macro abstract may legitimately open its
OBS section on one of them. So this is a standing channel for silent geometry
loss, not a one-off bad file.

WHAT IT MEASURES
----------------
Per macro that declares an OBS:

    parsed_obs_rects    what THIS PLUGIN reads from the LEF text
    loadable_obs_rects  what a reader can accept    (0 for the whole section
                        when ANY entry in it names an undeclared layer)

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

    exit 0 = for every macro, what the LEF declares is what a reader can load
    exit 1 = at least one macro's OBS section would be discarded (BLOCKING)
    exit 2 = could not be determined — no LEF, or no macro declares an OBS.
             NEVER a vacuous pass: "no obstruction was lost" and "there was no
             obstruction to lose" are different sentences and do not share an
             exit code.
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
    _MACRO_RE, parse_macro_obs)

# A layer DECLARATION: `LAYER <name>` alone on its line, closed by `END <name>`.
# A layer REFERENCE inside a MACRO body is `LAYER <name> ;` — the semicolon is
# the whole difference, and MACRO blocks are stripped before this runs anyway.
_LAYER_DECL_RE = re.compile(r"^[ \t]*LAYER[ \t]+(\S+)[ \t]*$", re.M)

# An OBS body and the layers it references. `parse_macro_obs` deliberately drops
# `OVERLAP` rects (that layer states the macro's own extent, not metal), but the
# READER does not get to skip the entry — an unresolvable layer there is exactly
# what discards the section. So this scan keeps every referenced layer.
_OBS_BODY_RE = re.compile(r"^\s*OBS\s*$(.*?)(?=^\s*(?:PIN|END)\b)", re.S | re.M)
_LAYER_REF_RE = re.compile(r"^\s*LAYER\s+(\S+)\s*;", re.M)

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


def obs_layers_referenced(lef_text: str) -> Dict[str, List[str]]:
    """{master: [layer, ...]} for every layer named inside a MACRO's OBS.

    Includes layers whose rects `parse_macro_obs` drops, because the reader does
    not get to drop them: an unresolvable layer ANYWHERE in the section is what
    discards the section."""
    out: Dict[str, List[str]] = {}
    if not isinstance(lef_text, str):
        return out
    for mm in _MACRO_RE.finditer(lef_text):
        master, body = mm.group(1), mm.group(2)
        om = _OBS_BODY_RE.search(body)
        if not om:
            continue
        seen: List[str] = []
        for lm in _LAYER_REF_RE.finditer(om.group(1)):
            ly = lm.group(1)
            if ly not in seen:
                seen.append(ly)
        if seen:
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
    refs: Dict[str, List[str]] = {}
    for i, t in enumerate(lef_texts):
        label = str(lef_labels[i]) if i < len(lef_labels) else f"LEF#{i + 1}"
        for master, entry in parse_macro_obs(t).items():
            if entry["obs"]:
                parsed[master] = (label, len(entry["obs"]))
        for master, layers in obs_layers_referenced(t).items():
            refs.setdefault(master, [])
            for ly in layers:
                if ly not in refs[master]:
                    refs[master].append(ly)

    findings: List[Dict[str, Any]] = []
    for master in sorted(refs):
        unresolved = [ly for ly in refs[master]
                      if ly.lower() not in declared or ly.lower() in from_log]
        if not unresolved:
            continue
        label, n_parsed = parsed.get(master, ("(none)", 0))
        findings.append({
            "master": master,
            "lef": label,
            "parsed_obs_rects": n_parsed,
            # The reader discards the SECTION, not the entry. That is the
            # measured behaviour and it is why one bad layer costs everything.
            "loadable_obs_rects": 0,
            "obs_layers_referenced": refs[master],
            "unresolvable_layers": unresolved,
            "corroborated_by_tool_log": sorted(
                ly for ly in unresolved if ly.lower() in from_log),
        })

    return {
        "layers_declared_by_lef_set": sorted(declared),
        "masters_with_obs": sorted(refs),
        "obs_rects_parsed_total": sum(n for _l, n in parsed.values()),
        "obs_rects_lost_total": sum(f["parsed_obs_rects"] for f in findings),
        "undefined_layers_in_tool_log": sorted(from_log),
        "tool_logs_read": len(log_texts),
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
    out: List[Path] = []
    seen = set()
    for pat in ("input/pdk/**/*.lef", "phase3/**/*.lef", "**/*.lef"):
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
        print(f"[CANNOT DETERMINE] macro_obs_load_parity: no LEF under {proj}. "
              "A run with no LEF is not a run whose obstructions all loaded — "
              "it is one this gate could not read. NOT a pass.",
              file=sys.stderr)
        return 2

    logs = list(a.logs or [])
    if not logs:
        logs = discover_logs(proj)
    log_texts, _log_labels = _read(logs)

    rep = audit(lef_texts, lef_labels, log_texts)
    if a.json_out:
        a.json_out.parent.mkdir(parents=True, exist_ok=True)
        a.json_out.write_text(json.dumps(rep, indent=2) + "\n")

    if not rep["masters_with_obs"]:
        print("[CANNOT DETERMINE] macro_obs_load_parity: no macro in the "
              f"{len(lef_texts)} LEF(s) read declares an OBS. NOT a pass — "
              "nothing was compared.", file=sys.stderr)
        return 2

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
                  f"{x['loadable_obs_rects']} — OBS references "
                  f"{', '.join(x['obs_layers_referenced'])}; NOT declared by "
                  f"any LEF read: {', '.join(x['unresolvable_layers'])}{corr}")
        if len(f) > 12:
            print(f"   … {len(f) - 12} more")
        print("\n  A reader that meets an unresolvable layer inside an OBS "
              "section discards the\n  WHOLE section and returns SUCCESS. The "
              "cost is not the one entry that named\n  the layer — it is every "
              "obstruction the macro declares. Downstream, a sealed\n  "
              "footprint then reads as fully routable, and straps and vias are "
              "emitted\n  across it: metal that is illegal AND does not "
              "connect.")
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
