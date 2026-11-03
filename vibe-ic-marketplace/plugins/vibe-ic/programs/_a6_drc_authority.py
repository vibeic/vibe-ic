#!/usr/bin/env python3
"""_a6_drc_authority.py — whose word stands for an A6 DRC rule (q1, T109).

A6 runs two engines on an analog block: the PDK's KLayout sign-off decks and
Magic. They disagree, and until this module the disagreement was settled by
which rules the ONE KLayout deck that ran happened to grade. On ihp-sg13g2
that deck (`ihp-sg13g2.drc`, the "main" table) grades neither `MIM.e` nor
`M2.d`; both live only in the PDK's extra-rules deck
(`rule_decks/sg13g2_maximal.drc`), which IHP's own `run_drc.py` runs by
default and neither A6 arm ran. So Magic's `MIM.e` on the GDS was blocking
with no engine to contradict it, and its `M2.d` was excused as the PDK's own
gencell with no engine to confirm it.

THE AUTHORITY RULE (owner decision q1, 2026-09-26)
  * The PDK's KLayout decks — the main runset AND every extra runset the PDK
    ships beside it (`rule_decks/*_maximal.drc`, found by glob, never by a
    literal name: it is `sg13cmos5l_maximal.drc` on ihp-sg13cmos5l) — are
    authoritative for every rule EITHER deck grades. Anything they fire on the
    block GDS is a FAIL, inside a PDK device cell or not: the foundry deck
    will see it too, so `DEVICE_CELL` no longer excuses it.
  * Magic is authoritative only for rules NEITHER deck grades.
  * Deferring a rule the two engines DISAGREE on (Magic fires, the deck graded
    it and fired 0) needs a CAPABILITY CONTROL: the same deck must fire that
    rule on the PDK's own unit FAIL testcase
    (`testing/testcases/unit/*.gds`, matched by the rule labels the testcase
    carries). Without it the rule blocks as
    `A6_ENGINE_DISAGREEMENT_UNCONTROLLED` — a deck that cannot fire a rule
    proves nothing by not firing it.
  * `ENGINE_ARTEFACT` names a deferred rule for which all four hold: the
    violation is Magic-only; it reproduces, rectangle for rectangle, on the
    bare device's own GDS round trip; the authoritative deck reports 0 for it
    on that device GDS and on the block GDS; and the capability control
    passed. It is excused and ALWAYS reported.

Nothing here names a rule, a layer or a PDK: the join key is the rule id the
PDK itself writes in both engines' output. chip-AGNOSTIC.
"""
from __future__ import annotations

import os as _os
import sys as _sys

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

#: The extra-rules runsets a PDK ships beside its main KLayout deck, relative
#: to the directory holding the main deck. A GLOB: the file is named after the
#: PDK (`sg13g2_maximal.drc`, `sg13cmos5l_maximal.drc`).
EXTRA_RUNSET_GLOB = "rule_decks/*_maximal.drc"
#: The PDK's antenna deck, relative to the main deck's dir. The default DRC run
#: leaves it out on both PDKs that ship one (#3798). `antenna.drc` is a complete
#: runset (ihp-sg13g2); `antenna.rb` is a fragment of the main deck, selected
#: with `decks=antenna` (gf180mcuD).
ANTENNA_RUNSET = "rule_decks/antenna.drc"
ANTENNA_FRAGMENT = "rule_decks/antenna.rb"
#: The PDK's per-table DRC unit testcases, relative to the main deck's dir.
UNIT_TESTCASE_DIR = "testing/testcases/unit"

ENGINE_DISAGREEMENT_UNCONTROLLED = "A6_ENGINE_DISAGREEMENT_UNCONTROLLED"
EXTRA_RUNSET_GRADED_NOTHING = "A6_EXTRA_RUNSET_GRADED_NOTHING"

#: Capability-control outcomes. Only PASS lets a disagreement be deferred.
CAP_PASS = "PASS"
CAP_SILENT = "SILENT"              # the deck ran on the testcase, never fired R
CAP_NO_TESTCASE = "NO_TESTCASE"    # no PDK unit testcase names R
CAP_NOT_MEASURED = "NOT_MEASURED"  # a testcase exists and could not be run

ENGINE_ARTEFACT = "ENGINE_ARTEFACT"


def extra_runsets(drc_dir: Path) -> List[Path]:
    """The extra-rules runsets beside a main KLayout deck, on THIS host."""
    return sorted(Path(drc_dir).glob(EXTRA_RUNSET_GLOB))


def antenna_decks(drc_dir: Path) -> List[Path]:
    """The antenna deck files beside a main KLayout deck, on THIS host."""
    return [Path(drc_dir) / rel for rel in (ANTENNA_RUNSET, ANTENNA_FRAGMENT)
            if (Path(drc_dir) / rel).is_file()]


def is_antenna_fragment(deck: object) -> bool:
    return Path(str(deck)).name == Path(ANTENNA_FRAGMENT).name


def is_antenna_deck(deck: object) -> bool:
    return Path(str(deck)).name in (Path(ANTENNA_RUNSET).name,
                                    Path(ANTENNA_FRAGMENT).name)


def antenna_record(decks: Iterable[object]) -> Dict[str, object]:
    """Say whether this DRC result covers antenna. A PDK that ships no antenna
    deck leaves it out, and the record says so."""
    found = [str(d) for d in decks]
    if found:
        return {"result": "MEASURED", "decks": found}
    return {"result": "NOT_MEASURED",
            "reason": "the PDK ships no antenna deck beside its main KLayout deck"}


def _name(raw: Optional[str]) -> str:
    return (raw or "").strip().strip("'\"").strip()


def lyrdb_text_rules(text: str) -> Dict[str, object]:
    """`{"graded": [...], "violations": {rule: n}}` from a KLayout report
    database's text. Each `<categories>/<category>` is a rule the engine
    GRADED; each `<items>/<item>` one violation of the rule it names. Parsed
    as XML; an unreadable database grades nothing (never "graded, clean")."""
    try:
        root = ET.fromstring(text or "")
    except ET.ParseError:
        return {"graded": [], "violations": {}}
    graded: Set[str] = set()
    for cats in root.iter("categories"):
        for c in cats.iter("category"):
            graded.add(_name(c.findtext("name")))
    graded.discard("")
    hits: Dict[str, int] = {}
    for items in root.iter("items"):
        for i in items.iter("item"):
            r = _name(i.findtext("category"))
            if r:
                hits[r] = hits.get(r, 0) + 1
    return {"graded": sorted(graded), "violations": dict(sorted(hits.items()))}


def merge_passes(passes: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    """One graded set and one violation tally out of several deck passes.

    The graded set is the UNION (a rule is graded if any authoritative deck
    grades it); violations are summed per rule. Each pass is kept by name so
    a reader can take the total apart again."""
    graded: Set[str] = set()
    viol: Dict[str, int] = {}
    for rec in passes.values():
        graded |= set(rec.get("graded") or [])
        for r, n in (rec.get("violations") or {}).items():
            viol[r] = viol.get(r, 0) + int(n)
    return {"graded": sorted(graded), "violations": dict(sorted(viol.items())),
            "passes": {k: {"graded": len(v.get("graded") or []),
                           "violations": dict(v.get("violations") or {})}
                       for k, v in passes.items()}}


# ── the PDK's unit testcases, and which rule each one exercises ──────────
#: A testcase label as the PDK writes it: `Mim.a/d`, `M2.d/e`, `TM1.b_fil`,
#: `Mim.gR (Full chip)` — a rule-family prefix, a dot, and one or more rule
#: suffixes separated by `/`.
_LABEL_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\.([A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*)")


def label_rule_ids(label: str) -> Set[str]:
    """The rule ids one testcase label names, lower-cased (the testcases
    spell the family `Mim` where the decks write `MIM`)."""
    m = _LABEL_RE.match(label or "")
    if not m:
        return set()
    fam = m.group(1).lower()
    return {f"{fam}.{s.lower()}" for s in m.group(2).split("/") if s}


def testcases_for_rule(labels: Dict[str, Dict[str, object]], rule: str
                       ) -> List[str]:
    """The unit testcases whose own labels name `rule`, sorted."""
    want = (rule or "").lower()
    return sorted(tc for tc, rec in labels.items()
                  if any(want in label_rule_ids(str(lb))
                         for lb in (rec or {}).get("labels") or []))


#: Run inside the tool image: `{testcase: {"top": [...], "labels": [...]}}`
#: for every `*.gds` in the directory given as argv[1]. KLayout's own reader,
#: so the labels are what the deck's engine sees.
UNIT_LABEL_SCRIPT = r'''
import glob, json, os, sys
import klayout.db as db
out = {}
for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.gds"))):
    ly = db.Layout()
    try:
        ly.read(f)
    except Exception as exc:
        out[os.path.basename(f)] = {"error": str(exc)}
        continue
    labels = set()
    for li in ly.layer_indexes():
        for c in ly.top_cells():
            it = c.begin_shapes_rec(li)
            while not it.at_end():
                s = it.shape()
                if s.is_text():
                    labels.add(s.text_string)
                it.next()
    out[os.path.basename(f)] = {"top": [c.name for c in ly.top_cells()],
                                "labels": sorted(labels)}
print("A6UNITLABELS " + json.dumps(out))
'''


def parse_unit_labels(stdout: str) -> Optional[Dict[str, Dict[str, object]]]:
    for line in (stdout or "").splitlines():
        if line.startswith("A6UNITLABELS "):
            try:
                return json.loads(line[len("A6UNITLABELS "):])
            except ValueError:
                return None
    return None


def disagreements(klayout: Dict[str, object], magic_violations: Dict[str, int]
                  ) -> Dict[str, int]:
    """Rules Magic fired that an authoritative deck graded and fired 0 on."""
    graded = set(klayout.get("graded") or [])
    kv = klayout.get("violations") or {}
    return {r: int(n) for r, n in sorted(magic_violations.items())
            if int(n) > 0 and r in graded and int(kv.get(r, 0)) == 0}


def capability_record(rule: str, testcases: List[str],
                      results: Dict[str, Optional[Dict[str, object]]]
                      ) -> Dict[str, object]:
    """The capability control for one rule, from the deck's runs on the
    PDK's unit testcases that name it. `results[tc]` is the merged
    `{graded, violations}` of the authoritative decks on `tc`, or None when
    that run could not be made."""
    fired = {tc: int(((results.get(tc) or {}).get("violations") or {})
                     .get(rule, 0)) for tc in testcases if results.get(tc)}
    if not testcases:
        res = CAP_NO_TESTCASE
    elif sum(fired.values()) > 0:
        res = CAP_PASS
    elif any(results.get(tc) is None for tc in testcases):
        res = CAP_NOT_MEASURED
    else:
        res = CAP_SILENT
    return {"rule": rule, "result": res, "testcases": testcases,
            "fired": fired}


def engine_artefact(rule: str, klayout_block: Dict[str, object],
                    roundtrip: Optional[Dict[str, object]],
                    capability: Optional[Dict[str, object]]
                    ) -> Tuple[bool, Dict[str, object]]:
    """Do all four ENGINE_ARTEFACT conditions hold for `rule`? Each condition
    is reported by name with what decided it; an unmeasured one is False."""
    graded = set(klayout_block.get("graded") or [])
    kv = klayout_block.get("violations") or {}
    rt = ((roundtrip or {}).get("rules") or {}).get(rule) or {}
    device_kl = rt.get("klayout_on_device_gds") or {}
    reproducing = [c for c, n in (rt.get("cells") or {}).items() if n]
    cond = {
        "magic_only": rule in graded and int(kv.get(rule, 0)) == 0,
        "reproduces_on_device_gds_roundtrip": bool(rt.get("reproduced")),
        "authoritative_deck_zero_on_device_and_block": (
            rule in graded and int(kv.get(rule, 0)) == 0 and bool(reproducing)
            and all(isinstance(device_kl.get(c), int) and device_kl[c] == 0
                    for c in reproducing)),
        "capability_control": (capability or {}).get("result") == CAP_PASS,
    }
    if roundtrip is None:
        cond["roundtrip_not_measured"] = True
    elif roundtrip.get("result") == "NOT_MEASURED":
        cond["roundtrip_not_measured"] = roundtrip.get("reason", True)
    holds = all(v is True for k, v in cond.items()
                if k != "roundtrip_not_measured") and \
        "roundtrip_not_measured" not in cond
    return holds, cond


def authority(klayout: Dict[str, object], magic_violations: Dict[str, int],
              device_cell_rules: Iterable[str],
              capability: Optional[Dict[str, Dict[str, object]]] = None,
              roundtrip: Optional[Dict[str, object]] = None
              ) -> Dict[str, object]:
    """The A6 verdict between the authoritative decks and Magic.

    `klayout` is the merged `{graded, violations}` of every authoritative
    deck on the block GDS; `magic_violations` Magic's per-rule counts;
    `device_cell_rules` the rules A6's own attribution classes as the PDK's
    gencell (they excuse ONLY rules no authoritative deck grades)."""
    capability = capability or {}
    graded = set(klayout.get("graded") or [])
    kv = {r: int(n) for r, n in (klayout.get("violations") or {}).items()}
    dc = set(device_cell_rules or ())
    blocking: Dict[str, int] = {r: n for r, n in kv.items() if n}
    codes: Dict[str, str] = {}
    agreeing: Dict[str, int] = {}
    controlled: Dict[str, int] = {}
    artefacts: Dict[str, dict] = {}
    not_artefacts: Dict[str, dict] = {}
    uncontrolled: Dict[str, dict] = {}
    excused: Dict[str, int] = {}
    for r, n in sorted(magic_violations.items()):
        n = int(n)
        if not n:
            continue
        if r in graded:
            if kv.get(r, 0) > 0:
                agreeing[r] = n
                continue
            cap = capability.get(r) or {"rule": r, "result": CAP_NOT_MEASURED,
                                        "testcases": [], "fired": {}}
            if cap.get("result") == CAP_PASS:
                controlled[r] = n
                holds, cond = engine_artefact(r, klayout, roundtrip, cap)
                (artefacts if holds else not_artefacts)[r] = {
                    "count": n, "conditions": cond}
            else:
                uncontrolled[r] = {"count": n, "capability": cap}
                blocking[f"magic:{r}"] = n
                codes[f"magic:{r}"] = ENGINE_DISAGREEMENT_UNCONTROLLED
        elif r in dc:
            excused[r] = n
        else:
            blocking[f"magic:{r}"] = n
    return {
        "authoritative_rules_graded": len(graded),
        "authoritative_violations": {r: n for r, n in kv.items() if n},
        "deferred_engines_agree": agreeing,
        "deferred_by_capability_control": controlled,
        "engine_artefact": artefacts,
        "deferred_not_engine_artefact": not_artefacts,
        "uncontrolled_disagreements": uncontrolled,
        "excused_as_pdk_device_cell_ungraded": excused,
        "blocking": dict(sorted(blocking.items())),
        "blocking_codes": codes,
        "rule": ("KLayout (main + extra decks) is authoritative for every "
                 "rule either grades — a hit there FAILs even inside a PDK "
                 "device cell; Magic is authoritative only for rules no deck "
                 "grades; a disagreement is deferred only when the deck fires "
                 "the rule on the PDK's unit FAIL testcase"),
    }

