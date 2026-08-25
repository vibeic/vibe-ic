#!/usr/bin/env python3
"""signoff_cell_aware_feol_cfg.py -- BUILD the opt-in `--cell-aware-feol` config
for the native `svrfdrc` sign-off engine (vibeic-eda image >= 0.2.19).

The engine's `--cell-aware-feol=<cfg>` (fork fix #2) exempts an FEOL space/notch
OVER-FIRE iff its error bridge lies strictly interior to a SINGLE standalone-
qualified master's exact placed footprint AND no top-level FEOL shape forms it --
a CONSERVATIVE, provably-never-false-clean exemption done INSIDE the DRC engine
(where per-shape cell provenance is known exactly). WITHOUT the flag the report
is byte-identical to the stock (no-exemption) run.

This program is the PLUGIN half: it only SUPPLIES a correct cfg. It NEVER waives a
violation itself -- the engine does the conservative geometry. Its ONE safety duty
is the qualified-master set: a master goes in `qualified` ONLY if it PASSES the
sign-off deck STANDALONE (verify, never assume). "Passes standalone" means the
`svrfdrc <deck> <lib> <rpt> --cell=<master>` run has ZERO non-DENSITY fails -- a
lone cell CANNOT hit the chip-level metal/active fill-density floors, so DENSITY
fires are inherent to isolation and irrelevant; ANY geometry / space / notch /
marker fail means the master's OWN geometry is dirty -> it is NOT qualified (so
the engine can never exempt a violation formed by a dirty master). If in doubt,
qualify nothing.

The cfg the engine consumes (keys, one per line, `#` comments):
    lib   <library GDS>              # per-master master geometry (footprints)
    def   <placed DEF>               # placements (master -> transform)
    qualified <m1> <m2> ...          # STANDALONE-qualified masters (>=1)
    feol_rule <r1> <r2> ...          # exact rule NAMES to filter (>=1)
    feol_gds  <l/d> ...              # raw FEOL device layers (>=1, MANDATORY guard)
    strict_dbu <n>                   # boundary-touch strictness (default 1)

`feol_gds` (the FEOL device layers) is the SAFETY GUARD: the engine keeps ANY
violation formed by geometry outside a qualified master's raw FEOL, so listing a
non-FEOL layer here (e.g. metal) would be UNSAFE -> the FEOL layers come ONLY from
the design's own sign-off config (`cell_aware_feol.feol_gds`), never guessed.
`feol_rule` is expanded from config-declared rule-name prefixes against the deck's
own rule blocks (`<NAME> {` ... `}`), so no vendor / IC / SKU literal appears here.

chip-AGNOSTIC: every deck-specific fact (FEOL layers, FEOL-rule prefixes) is a
DESIGN INPUT read from the sign-off config + the deck; masters come from the DEF;
this file hardcodes no chip / vendor / cell / layer literal.

Usage (library / injected-runner form is the runner's path; a CLI is provided for
standalone use + reproduction):
    python3 signoff_cell_aware_feol_cfg.py \
        --deck <deck.rule> --lib <lib.gds> --def <placed.def> \
        --feol-gds 2/0,3/0,4/0,5/0 --feol-rule-prefix NW.S,OD.S,PO.S,NP.S,PP.S \
        --container <name> [--strict-dbu 1] [--out cell_aware_feol.cfg] [--json]

Exit codes:
    0  cfg written (>=1 qualified master) OR nothing-to-do (gate not met) with --json
    3  gate not met / no qualified master and no --json (nothing written)
    2  argument or I/O error
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# ── the HOST reference oracle, and the ONE definition of what it and this file
#    both parse ────────────────────────────────────────────────────────────────
# `signoff_cell_aware_feol_attribution` is the host-side reference oracle for the
# SAME attribution the engine's `--cell-aware-feol` performs: given the placed DEF
# and the qualified-master set, which firing FEOL over-fires lie inside a
# qualified footprint. This file is the ENGINE half and that one is the ORACLE
# half, and until now they shared their inputs' grammar by having TWO COPIES of it
# and no import between them -- the oracle was reached by nothing but its own unit
# test, so the copies could only be kept equal by remembering to.
#
# THEY ALREADY CAME APART ONCE, and the comment on `_COMP_RE` below is the record
# of it: the placement regex was fixed HERE for the `+ SOURCE DIST` filler/decap
# undercount and had to be fixed AGAIN, separately, over there. Two definitions of
# one grammar have one true value and one that is only sometimes true, so the
# grammar now has a single home and this file imports it. Nothing about the
# engine-side behaviour changes: `parse_layerlist` and the imported `_COMP_RE`
# are byte-for-byte what this file defined, and the COMPONENTS-block scoping in
# `parse_placed_masters` stays here, where it belongs.
#
# The oracle's own `attribute()` defers its `pya` import to call time, so this
# import costs nothing on a host without KLayout.
import signoff_cell_aware_feol_attribution as _oracle
# ── DEF COMPONENTS parse ─────────────────────────────────────────────────────
# `- <inst> <master> [+ EEQMASTER ..] [+ SOURCE {DIST|NETLIST|USER|TIMING}] +
#  (PLACED|FIXED|COVER) ( x y ) <orient> ... ;`  — the placement status may be
# preceded by optional `+ SOURCE ...` / `+ EEQMASTER ...` clauses, so match
# non-greedily up to the placement WITHOUT crossing the record `;` terminator.
# (The stock attributor regex required PLACED to immediately follow the master and
# silently dropped every `+ SOURCE DIST` filler/decap component -> undercount.)
#: THE one placement grammar, owned by the oracle module (see the import note
#: above). Bound here under the name this file already used, so every reader and
#: every caller below is unchanged.
_COMP_RE = _oracle._COMP_RE


def parse_placed_masters(def_text: str) -> Dict[str, int]:
    """Return {master_name: placed_instance_count} for every PLACED/FIXED/COVER
    component. Robust to intervening `+ SOURCE ...` clauses."""
    out: Dict[str, int] = {}
    # restrict to the COMPONENTS block so a MACRO/PIN line can never match
    cb = def_text.find("COMPONENTS")
    ce = def_text.find("END COMPONENTS")
    scope = def_text[cb:ce] if (cb != -1 and ce != -1 and ce > cb) else def_text
    for m in _COMP_RE.finditer(scope):
        master = m.group(2)
        out[master] = out.get(master, 0) + 1
    return out


# ── deck rule-name enumeration ───────────────────────────────────────────────
# A rule block opens with `<NAME> {` on its own logical position; the NAME is the
# last token before `{`. Match names that START WITH any configured prefix (so a
# family like `PO.S` expands to PO.S.1.3 / PO.S.2 / PO.S.2_2 / ...). An exact rule
# name is just a zero-extension prefix.
_RULE_OPEN_RE = re.compile(r"(?m)^[ \t]*([A-Za-z0-9_.]+)[ \t]*\{[ \t]*$")


def enumerate_feol_rules(deck_text: str, prefixes: Sequence[str]) -> List[str]:
    """Exact rule names in `deck_text` whose name starts with any of `prefixes`.
    Deterministic (sorted, de-duplicated). A prefix match is anchored at the name
    start and, when it does not consume the whole name, must break on a `.`/`_`
    boundary so `PO.S` matches `PO.S.2` but never `PO.SOMETHING`-style siblings
    that merely share a leading run."""
    pref = [p for p in (prefixes or []) if p]
    if not pref:
        return []
    hits = set()
    for m in _RULE_OPEN_RE.finditer(deck_text):
        name = m.group(1)
        for p in pref:
            if name == p:
                hits.add(name)
                break
            if name.startswith(p) and name[len(p)] in "._":
                hits.add(name)
                break
    return sorted(hits)


# ── standalone qualification classifier ──────────────────────────────────────
# A svrfdrc report result line: `FAIL <rule> <OP> <expr...> -> <count>`. The OP
# (3rd token) is EXTERNAL / INTERNAL / DENSITY / ... . A lone cell inherently
# fails only DENSITY (chip-level metal/active fill floors); any OTHER fail is the
# master's own geometry -> not qualified.
_RESULT_RE = re.compile(r"^(FAIL|PASS|SKIP)\s+(\S+)\s+(\S+)\s+", re.M)


def standalone_nondensity_fails(report_text: str) -> List[str]:
    """Rule names of every FAIL whose OP is NOT DENSITY (the disqualifiers)."""
    bad: List[str] = []
    for m in _RESULT_RE.finditer(report_text or ""):
        verdict, rule, op = m.group(1), m.group(2), m.group(3)
        if verdict == "FAIL" and op.upper() != "DENSITY":
            bad.append(rule)
    return bad


def standalone_qualified(report_text: str) -> bool:
    """True iff the standalone report has ZERO non-DENSITY fails (and is a real
    report — an empty / missing report is NEVER qualified)."""
    if not report_text or "tally:" not in report_text:
        return False
    return not standalone_nondensity_fails(report_text)


# ── feol_gds parse ───────────────────────────────────────────────────────────
def parse_feol_gds(specs: Sequence[str]) -> List[Tuple[int, int]]:
    """['2/0','3/0','4'] -> [(2,0),(3,0),(4,0)]; datatype defaults to 0. Accepts a
    comma-joined single string too."""
    # One layer-list grammar, owned by the oracle module: `parse_layerlist`
    # takes ONE comma-joined string and applies exactly this partition-on-"/",
    # datatype-defaults-to-0, skip-empty rule. Mapping it over the sequence is
    # what this function did by hand.
    out: List[Tuple[int, int]] = []
    for spec in specs or []:
        out.extend(_oracle.parse_layerlist(str(spec)))
    return out


def feol_gds_from_config(caf: Dict) -> List[Tuple[int, int]]:
    """Extract the FEOL device layers from a `cell_aware_feol` config block.
    Accepts either `feol_gds` (list of 'L/D') or, when absent, the same layer
    values a tap-latch-up config would declare — a dict of name->'L/D'. Values
    only; the NAMES are ignored (chip-AGNOSTIC)."""
    fg = caf.get("feol_gds")
    if isinstance(fg, dict):
        return parse_feol_gds(list(fg.values()))
    if isinstance(fg, (list, tuple)):
        return parse_feol_gds([str(x) for x in fg])
    if isinstance(fg, str):
        return parse_feol_gds([fg])
    return []


# ── cfg render ───────────────────────────────────────────────────────────────
def render_cfg(lib_c: str, def_c: str, qualified: Sequence[str],
               feol_rules: Sequence[str], feol_gds: Sequence[Tuple[int, int]],
               strict_dbu: int = 1) -> str:
    """Render the `--cell-aware-feol` cfg text (paths are CONTAINER paths — the
    svrfdrc engine reads them inside the image)."""
    ql = " ".join(sorted(set(qualified)))
    rl = " ".join(sorted(set(feol_rules)))
    gl = " ".join(f"{l}/{d}" for (l, d) in feol_gds)
    return (
        "# vibe-ic cell-aware-feol cfg (opt-in, engine-side conservative "
        "exemption)\n"
        f"lib {lib_c}\n"
        f"def {def_c}\n"
        f"qualified {ql}\n"
        f"feol_rule {rl}\n"
        f"feol_gds {gl}\n"
        f"strict_dbu {int(strict_dbu) if int(strict_dbu) >= 1 else 1}\n")


class CfgResult:
    """Outcome of build_cfg. `written` False => gate not met / nothing qualified
    => the caller MUST omit --cell-aware-feol (byte-identical stock run)."""

    def __init__(self):
        self.written: bool = False
        self.cfg_path: Optional[str] = None
        self.qualified: List[str] = []
        self.placed_masters: List[str] = []
        self.feol_rules: List[str] = []
        self.feol_gds: List[str] = []
        self.reason: str = ""

    def to_json(self) -> Dict:
        return {
            "written": self.written, "cfg_path": self.cfg_path,
            "qualified_masters": self.qualified,
            "n_qualified": len(self.qualified),
            "placed_masters": self.placed_masters,
            "n_placed_unique": len(self.placed_masters),
            "feol_rules": self.feol_rules, "feol_gds": self.feol_gds,
            "reason": self.reason}


def build_cfg(*, deck_text: str, def_text: str, lib_container: str,
              def_container: str, feol_gds: Sequence[Tuple[int, int]],
              feol_rule_prefixes: Sequence[str],
              run_standalone: Callable[[str], str], cfg_out: Path,
              strict_dbu: int = 1) -> CfgResult:
    """Build the cfg. `run_standalone(master)` MUST run
    `svrfdrc <deck> <lib> <rpt> --cell=<master>` (against the master LIBRARY) and
    return the report TEXT (empty string on failure). Only masters that pass
    standalone (0 non-DENSITY fails) are qualified. Writes `cfg_out` and returns
    written=True iff >=1 master qualifies AND >=1 feol rule AND >=1 feol_gds layer;
    otherwise written=False (caller omits the flag -> byte-identical)."""
    res = CfgResult()
    feol_gds = list(feol_gds)
    res.feol_gds = [f"{l}/{d}" for (l, d) in feol_gds]
    placed = parse_placed_masters(def_text)
    res.placed_masters = sorted(placed)
    feol_rules = enumerate_feol_rules(deck_text, feol_rule_prefixes)
    res.feol_rules = feol_rules
    if not feol_gds:
        res.reason = "no feol_gds (FEOL device layers) — gate not met"
        return res
    if not feol_rules:
        res.reason = "no feol_rule matched the deck for the configured prefixes"
        return res
    if not placed:
        res.reason = "DEF has no placed masters"
        return res
    qualified: List[str] = []
    for master in sorted(placed):
        rpt = run_standalone(master)
        if standalone_qualified(rpt):
            qualified.append(master)
    res.qualified = qualified
    if not qualified:
        res.reason = ("no master passed standalone qualification "
                      "(all had non-DENSITY fails or failed to run)")
        return res
    cfg_txt = render_cfg(lib_container, def_container, qualified,
                         feol_rules, feol_gds, strict_dbu)
    cfg_out.parent.mkdir(parents=True, exist_ok=True)
    cfg_out.write_text(cfg_txt)
    res.written = True
    res.cfg_path = str(cfg_out)
    res.reason = f"cfg written: {len(qualified)} qualified master(s)"
    return res


# ── CLI (standalone / reproduction; runs svrfdrc via docker) ─────────────────
def _docker_standalone_runner(container: str, bin_c: str, deck_c: str,
                              lib_c: str, workdir_c: str
                              ) -> Callable[[str], str]:
    def _run(master: str) -> str:
        rpt_c = f"{workdir_c}/_caf_q_{re.sub(r'[^A-Za-z0-9_.]', '_', master)}.rpt"
        # bash -lc: the vibeic-eda image's /etc/profile.d setup script uses bash
        # syntax; a POSIX `sh` login shell aborts on it before svrfdrc ever runs.
        cmd = (f"docker exec {container} bash -lc "
               f"'{bin_c} {deck_c} {lib_c} {rpt_c} --cell={master} "
               f">/dev/null 2>&1; cat {rpt_c} 2>/dev/null'")
        try:
            p = subprocess.run(cmd, shell=True, capture_output=True,
                               text=True, timeout=600)
            return p.stdout or ""
        except Exception:
            return ""
    return _run


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deck", required=True, help="host path to the .rule deck")
    ap.add_argument("--lib", required=True,
                    help="host path to the master library GDS")
    ap.add_argument("--def", dest="def_path", required=True,
                    help="host path to the placed DEF")
    ap.add_argument("--feol-gds", required=True,
                    help="FEOL device layers, e.g. 2/0,3/0,4/0,5/0")
    ap.add_argument("--feol-rule-prefix", required=True,
                    help="comma list of deck rule-name prefixes, e.g. "
                         "NW.S,OD.S,PO.S,NP.S,PP.S")
    ap.add_argument("--container", required=True,
                    help="running vibeic-eda container name")
    ap.add_argument("--svrfdrc-bin", default="svrfdrc")
    ap.add_argument("--lib-container", default=None,
                    help="container path of the lib GDS (default: same as --lib)")
    ap.add_argument("--def-container", default=None,
                    help="container path of the DEF (default: same as --def)")
    ap.add_argument("--workdir-container", default="/tmp")
    ap.add_argument("--strict-dbu", type=int, default=1)
    ap.add_argument("--out", default="cell_aware_feol.cfg")
    ap.add_argument("--json", action="store_true")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    ap = _build_argparser()
    a = ap.parse_args(argv)
    try:
        deck_text = Path(a.deck).read_text(errors="ignore")
        def_text = Path(a.def_path).read_text(errors="ignore")
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    lib_c = a.lib_container or a.lib
    def_c = a.def_container or a.def_path
    # CLI convenience: the container sees the deck at its own path. The vibeic-eda
    # image mounts /home/reyerchu identically, so a host deck path resolves as-is;
    # pass an explicit container path via a mounted location when they differ.
    deck_c = a.deck
    runner = _docker_standalone_runner(a.container, a.svrfdrc_bin, deck_c,
                                       lib_c, a.workdir_container)
    res = build_cfg(
        deck_text=deck_text, def_text=def_text, lib_container=lib_c,
        def_container=def_c, feol_gds=parse_feol_gds([a.feol_gds]),
        feol_rule_prefixes=[p.strip() for p in a.feol_rule_prefix.split(",")],
        run_standalone=runner, cfg_out=Path(a.out), strict_dbu=a.strict_dbu)
    if a.json:
        print(json.dumps(res.to_json(), indent=2))
    else:
        print(f"cell-aware-feol cfg: written={res.written} "
              f"qualified={len(res.qualified)}/{len(res.placed_masters)} "
              f"rules={len(res.feol_rules)} feol_gds={res.feol_gds} "
              f"-> {res.reason}")
    return 0 if (res.written or a.json) else 3


if __name__ == "__main__":
    raise SystemExit(main())
