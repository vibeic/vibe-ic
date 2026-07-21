#!/usr/bin/env python3
"""sta_corner_record_completeness_check.py — the timing RECORD-completeness gate.

The defect (measured, not hypothetical)
---------------------------------------
A campaign ledger carried NO STA column at all while two ICs violated setup at
the slow sign-off corner — worst setup slack -4.33 ns (TNS -259.13) and
-2.35 ns (TNS -10.36) — both persisting unchanged through the post-fix verify
runs. Because timing was simply ABSENT from the record, the campaign narrative
became "the phase-3 failures were LVS tooling artifacts": true of the LVS part,
but it was allowed to sound like the whole explanation while real timing
violations sat unreported.

The same shape recurs across the corpus: a run MET at the typ/nominal corner
while its slow corner VIOLATED. **A typ-only "MET" is a misleading pass.** A run
may not report timing as satisfied while a sign-off corner is violating or
unreported.

What this gate is (and what it deliberately is NOT)
--------------------------------------------------
This gate judges the COMPLETENESS and HONESTY of the timing record.
`post_route_signoff_corner_check` (#147) already FAILs on a negative worst-slack
inside the multicorner report, and that slack rule is NOT re-implemented here.
The hole this gate closes is that #147 is wired in the flow YAML as

    optional_program_exit_zero:
      command: "post_route_signoff_corner_check . --json ..."
      condition_files_exist: ["phase3/stage3/sta/sta_spef_multicorner.rpt"]

so when the report is ABSENT the condition is false, the gate never runs, and
Step 23 passes. An unreported corner is thereby indistinguishable from a met
one — which is exactly how -4.33 ns went unnoticed. This gate is UNCONDITIONAL:
it starts from the corners the flow DECLARED and fails when the record fails to
account for each of them.

Rules
-----
R1 REPORTED-CORNER COMPLETENESS — every corner appearing in the timing record
   must be identified BY NAME, and a corner report that carries no declared
   sign-off role (a bare per-corner characterisation) must carry BOTH a worst
   setup and a worst hold slack. Half a corner is an incomplete record.
   EXEMPT: the declared nominal/primary corner. It holds no sign-off role —
   setup is signed off at the slow corner and hold at the fast one — so its
   single-corner report legitimately carries setup only. Requiring hold from it
   would be a FABRICATED violation that fails every run in the corpus, the
   clean ones included. Its datapoint still appears in the evidence table, and
   R3 still uses it to expose the typ-MET-while-sign-off-VIOLATED shape.

R2 DECLARED-BUT-UNREPORTED — every (corner, role) the flow was CONFIGURED to
   analyse must have a slack datapoint for that role. A declared sign-off corner
   with no timing datapoint FAILs; it does not silently vanish. This is also the
   rule that makes a typ-only record fail rather than pass.
   R2 additionally covers the starkest form of the same defect: an STA artifact
   that CITES the report its numbers came from (`post_route_signoff_corner.json`
   and the two stance files all carry such a citation) while that report is
   gone. The citation proves corners were analysed; the missing target proves
   nothing survived to substantiate it. Measured in the corpus: a run carrying
   a `"verdict": "FAIL", "setup_worst_slack_ns": -52.48` verdict whose cited
   `sta_spef_multicorner.rpt` does not exist.

R3 NO TYP-ONLY PASS — if any SIGN-OFF corner violates, the run's timing verdict
   is VIOLATION regardless of what the primary/typ corner says. When the primary
   corner MET while a sign-off corner violated, the finding says so explicitly,
   because that combination is the misleading pass this gate exists to stop.

How sign-off corners are learned (READ from the flow, never hardcoded)
----------------------------------------------------------------------
This was determined by reading `phase3_one_shot_runner.py`, not assumed. The
flow declares sign-off roles EXPLICITLY, but on two axes with two different
corner vocabularies, and there is NO single unified corner registry:

  PROCESS axis — `reports/phase3/mcorner_ocv_stance.json`, emitted alongside
    `sta_mcorner_ocv.rpt`, names the roles outright:
        {"setup_process_corner": "SS", "hold_process_corner": "FF", ...}

  RC axis — `reports/phase3/multi_corner_spef_stance.json`, emitted alongside
    `sta_spef_multicorner.rpt`:
        {"setup_corner": "max", "hold_corner": "min",
         "corners_extracted": ["max", "min", "nom"], ...}
    with the same roles restated in the report header as
        `# SETUP corner: max-RC   HOLD corner: min-RC`
    which this gate falls back to parsing when the stance JSON is absent.

  NOMINAL — `phase2/stage2/constraints/pvt_matrix.json` carries a
    `primary_corner` field (e.g. "TT") naming the nominal corner, plus the
    `corners: [{name, label}]` matrix whose labels come from the runner's own
    `_classify_corner_from_name` (vocabulary SS/TT/FF/unknown).

Two consequences are load-bearing and are the reason this gate is not a naive
set-difference:

  * `corners_extracted` / `corners_available` / the `pvt_matrix` corner list are
    AVAILABILITY lists, not run lists. `nom` is extracted on every run and
    deliberately never analysed (setup is signed off at the slow corner and hold
    at the fast one — correct practice). Such corners are shown in the evidence
    table as `available_not_selected` and NEVER trigger R2. Treating availability
    as configuration would make this gate fire on every run in the corpus.

  * a corner is judged for the ROLE it was declared to serve. Demanding hold
    slack at the slow setup corner would be a fabricated violation, not a found
    one. A corner carrying NO declared role must still carry both.

A declared corner whose label is `unknown`, or a run that declares no primary,
is treated as SIGN-OFF, never as nominal: silently demoting an unclassifiable
corner to "informational" would be this very bug in a new costume.

If nothing at all is declared and nothing was recorded, the gate returns
NOT_APPLICABLE with `no_corner_declaration` in its findings — it says so out
loud rather than inventing a sign-off corner set.

Evidence emission (the absence of this table IS the defect)
-----------------------------------------------------------
The gate ALWAYS emits the full per-corner table it judged on — corner name,
axis, declared role(s), sign-off class, setup WNS, hold WNS, TNS and the source
artifact path for each — to stdout and into the verdict JSON, on PASS and FAIL
alike. A gate that reproduced the missing-table defect while policing it would
be absurd.

Exit: 0 PASS / NOT_APPLICABLE · 1 FAIL · 2 IO-or-arg error.

chip-AGNOSTIC / benchmark-AGNOSTIC: no design, IC, PDK, vendor or corner-name
literal drives any verdict; corner identity and sign-off role come from the
run's own declaration artifacts.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _path_layout as _pl  # noqa: E402
except Exception:  # pragma: no cover - defensive
    _pl = None

_PROGRAM = "sta_corner_record_completeness_check"

# Float-noise guard (ns): a slack this close to zero is met, so STA rounding
# never manufactures a phantom violation. Real misses are orders larger.
_DEFAULT_SLACK_TOL_NS = 0.001

AXIS_PROCESS = "process"
AXIS_RC = "rc"

# ── declaration artifacts ───────────────────────────────────────────────────
_PROCESS_STANCE_CANDIDATES = (
    "reports/phase3/mcorner_ocv_stance.json",
    "reports/phase3/sta/mcorner_ocv_stance.json",
)
_RC_STANCE_CANDIDATES = (
    "reports/phase3/multi_corner_spef_stance.json",
    "reports/phase3/sta/multi_corner_spef_stance.json",
)
_PVT_CANDIDATES = (
    "phase2/stage2/constraints/pvt_matrix.json",
    "constraints/pvt_matrix.json",
    "phase3/stage3/constraints/pvt_matrix.json",
)

# ── record artifacts ────────────────────────────────────────────────────────
_MULTICORNER_CANDIDATES = (
    "phase3/stage3/sta/sta_spef_multicorner.rpt",
    "reports/phase3/sta_spef_multicorner.rpt",
    "reports/phase3/sta/sta_spef_multicorner.rpt",
)
_MCORNER_OCV_CANDIDATES = (
    "phase3/stage3/sta/sta_mcorner_ocv.rpt",
    "reports/phase3/sta_mcorner_ocv.rpt",
    "reports/phase3/sta/sta_mcorner_ocv.rpt",
)
_NOMINAL_SPEF_CANDIDATES = (
    "phase3/stage3/sta/sta_spef_based.rpt",
    "reports/phase3/sta_spef_based.rpt",
    "reports/phase3/sta/sta_spef_based.rpt",
)
_PER_CORNER_DIRS = (
    "phase3/stage3/sta/per_corner",
    "reports/phase3/sta/per_corner",
)

# STA artifacts that CITE the report their numbers came from. A citation whose
# target is gone is a verdict that outlived its evidence — the record no longer
# substantiates the claim, so the cited corners are unreported by definition.
_CITING_ARTIFACTS = (
    ("reports/phase3/sta/post_route_signoff_corner.json", "report"),
    ("reports/phase3/post_route_signoff_corner.json", "report"),
    ("reports/phase3/mcorner_ocv_stance.json", "report"),
    ("reports/phase3/multi_corner_spef_stance.json", "multicorner_sta_report"),
)

# `worst slack max -1.71` / `worst slack min 0.54` (OpenSTA max=setup, min=hold)
_WORST_SLACK_RE = re.compile(
    r"worst\s+slack\s+(max|min)\s+(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_WNS_RE = re.compile(r"\bwns\s+(max|min)?\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_TNS_RE = re.compile(r"\btns\s+(max|min)?\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
# `=== SETUP (max-RC corner, SPEF=max) ===`  (multicorner SPEF report)
# `=== SETUP corner: process=SS liberty, SPEF=x.max.spef ===` (mcorner OCV)
_SECTION_RE = re.compile(r"===\s*(SETUP|HOLD)\b", re.IGNORECASE)
_SECTION_PROCESS_RE = re.compile(
    r"===\s*(SETUP|HOLD)\s+corner:\s*process=([\w.+-]+)", re.IGNORECASE)
# `# SETUP corner: max-RC   HOLD corner: min-RC`
_SIGNOFF_HEADER_RE = re.compile(
    r"#\s*SETUP\s+corner:\s*([\w.+-]+?)(?:-RC)?\s+HOLD\s+corner:\s*"
    r"([\w.+-]+?)(?:-RC)?\s*$", re.IGNORECASE)
_CORNERS_AVAIL_RE = re.compile(r"#\s*corners_available:\s*(.+)", re.IGNORECASE)
_PER_CORNER_RPT_RE = re.compile(r"^sta_(.+)\.rpt$", re.IGNORECASE)


# ── small helpers ──────────────────────────────────────────────────────────
def _first_existing(project: Path, rels: Tuple[str, ...]) -> Optional[Path]:
    for rel in rels:
        p = project / rel
        if p.is_file():
            return p
    return None


def _load_json(path: Optional[Path]) -> Optional[Dict[str, object]]:
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _rel(project: Path, p: Path) -> str:
    try:
        return str(p.relative_to(project))
    except ValueError:
        return str(p)


def _key(axis: str, corner: str) -> Tuple[str, str]:
    return (axis, str(corner).strip().lower())


def _merge_slack(cur: Optional[float], new: Optional[float]) -> Optional[float]:
    if new is None:
        return cur
    return new if cur is None else min(cur, new)


# ── slack extraction ───────────────────────────────────────────────────────
def extract_slacks(text: str) -> Dict[str, Optional[float]]:
    """Worst SETUP slack, worst HOLD slack and TNS from an OpenSTA report body.

    Setup is the `max` (late) analysis and hold the `min` (early) one, per
    OpenSTA convention. An UNLABELLED `wns`/`tns` is attributed to setup (the
    `report_checks` default is the max path) unless an enclosing HOLD section
    says otherwise — hold is then left None, which is honest: a report that
    never labelled a min analysis did not report hold, and the rules say so
    rather than inventing a number."""
    setup: Optional[float] = None
    hold: Optional[float] = None
    tns: Optional[float] = None
    section: Optional[str] = None

    for raw in text.splitlines():
        line = raw.strip()

        msec = _SECTION_RE.search(line)
        if msec:
            section = msec.group(1).upper()
            continue

        mws = _WORST_SLACK_RE.search(line)
        if mws:
            val = float(mws.group(2))
            if mws.group(1).lower() == "max":
                setup = _merge_slack(setup, val)
            else:
                hold = _merge_slack(hold, val)
            continue

        mwns = _WNS_RE.search(line)
        if mwns:
            val = float(mwns.group(2))
            mode = (mwns.group(1) or "").lower()
            if not mode:
                mode = "min" if section == "HOLD" else "max"
            if mode == "max":
                setup = _merge_slack(setup, val)
            else:
                hold = _merge_slack(hold, val)
            continue

        mtns = _TNS_RE.search(line)
        if mtns:
            tns = _merge_slack(tns, float(mtns.group(2)))

    return {"setup_wns_ns": setup, "hold_wns_ns": hold, "tns_ns": tns}


def _split_sections(text: str) -> List[Tuple[str, Optional[str], str]]:
    """Split a sectioned STA report into (kind, corner_or_None, body) chunks.
    `kind` is SETUP/HOLD; `corner` is the process corner when the section header
    names one (`process=SS`), else None."""
    out: List[Tuple[str, Optional[str], str]] = []
    kind: Optional[str] = None
    corner: Optional[str] = None
    buf: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        msec = _SECTION_RE.search(line)
        if msec:
            if kind is not None:
                out.append((kind, corner, "\n".join(buf)))
            kind = msec.group(1).upper()
            mproc = _SECTION_PROCESS_RE.search(line)
            corner = mproc.group(2) if mproc else None
            buf = []
            continue
        if kind is not None:
            buf.append(line)
    if kind is not None:
        out.append((kind, corner, "\n".join(buf)))
    return out


# ── declaration discovery ──────────────────────────────────────────────────
def read_declarations(project: Path) -> Dict[str, object]:
    """Collect every (axis, corner, role) the flow DECLARED it would analyse,
    plus the availability lists and the declared nominal corner. All read from
    the run's own artifacts — nothing is assumed about corner naming."""
    declared: List[Dict[str, str]] = []      # {axis, corner, role, source}
    available: List[Dict[str, str]] = []     # {axis, corner, source}
    aliases: Dict[Tuple[str, str], List[str]] = {}   # (axis, corner) -> names
    sources: Dict[str, Optional[str]] = {}
    primary: Optional[Dict[str, str]] = None

    # -- PROCESS axis: mcorner_ocv_stance.json names setup/hold process corners
    p_stance_path = _first_existing(project, _PROCESS_STANCE_CANDIDATES)
    p_stance = _load_json(p_stance_path)
    sources["process_stance"] = (_rel(project, p_stance_path)
                                 if p_stance_path else None)
    if p_stance:
        src = sources["process_stance"] or ""
        for field, role in (("setup_process_corner", "setup"),
                            ("hold_process_corner", "hold")):
            val = p_stance.get(field)
            if isinstance(val, str) and val.strip():
                declared.append({"axis": AXIS_PROCESS, "corner": val.strip(),
                                 "role": role, "source": src})

    # -- RC axis: multi_corner_spef_stance.json, else the report header
    rc_stance_path = _first_existing(project, _RC_STANCE_CANDIDATES)
    rc_stance = _load_json(rc_stance_path)
    sources["rc_stance"] = (_rel(project, rc_stance_path)
                            if rc_stance_path else None)
    rc_declared_any = False
    if rc_stance:
        src = sources["rc_stance"] or ""
        for field, role in (("setup_corner", "setup"),
                            ("hold_corner", "hold")):
            val = rc_stance.get(field)
            if isinstance(val, str) and val.strip():
                declared.append({"axis": AXIS_RC, "corner": val.strip(),
                                 "role": role, "source": src})
                rc_declared_any = True
        extracted = rc_stance.get("corners_extracted")
        if isinstance(extracted, list):
            for c in extracted:
                if isinstance(c, str) and c.strip():
                    available.append({"axis": AXIS_RC, "corner": c.strip(),
                                      "source": src})

    mc_path = _first_existing(project, _MULTICORNER_CANDIDATES)
    sources["multicorner_report"] = _rel(project, mc_path) if mc_path else None
    if mc_path is not None:
        try:
            head = mc_path.read_text(errors="replace")
        except OSError:
            head = ""
        for raw in head.splitlines():
            line = raw.strip()
            mso = _SIGNOFF_HEADER_RE.search(line)
            if mso and not rc_declared_any:
                src = sources["multicorner_report"] or ""
                declared.append({"axis": AXIS_RC, "corner": mso.group(1).strip(),
                                 "role": "setup", "source": src})
                declared.append({"axis": AXIS_RC, "corner": mso.group(2).strip(),
                                 "role": "hold", "source": src})
                rc_declared_any = True
            mav = _CORNERS_AVAIL_RE.search(line)
            if mav:
                src = sources["multicorner_report"] or ""
                for c in mav.group(1).split(","):
                    if c.strip():
                        available.append({"axis": AXIS_RC, "corner": c.strip(),
                                          "source": src})

    # -- NOMINAL + the process availability matrix: pvt_matrix.json
    pvt_path = _first_existing(project, _PVT_CANDIDATES)
    pvt = _load_json(pvt_path)
    sources["pvt_matrix"] = _rel(project, pvt_path) if pvt_path else None
    labels: Dict[str, str] = {}
    if pvt:
        src = sources["pvt_matrix"] or ""
        prim = pvt.get("primary_corner")
        if isinstance(prim, str) and prim.strip():
            primary = {"axis": AXIS_PROCESS, "corner": prim.strip(),
                       "source": src}
        corners = pvt.get("corners")
        if isinstance(corners, list):
            for c in corners:
                if isinstance(c, dict):
                    name = c.get("name")
                    label = c.get("label")
                    if isinstance(name, str) and name.strip():
                        # The matrix names each corner by its full Liberty stem
                        # while the sign-off stance and the report headers speak
                        # in LABELS (SS/TT/FF). Register availability under the
                        # label when one exists — carrying the Liberty stem as an
                        # alias — so the two vocabularies denote ONE corner row
                        # instead of two half-empty ones.
                        if isinstance(label, str) and label.strip():
                            lbl = label.strip()
                            labels[lbl.lower()] = lbl
                            aliases.setdefault(
                                _key(AXIS_PROCESS, lbl), []).append(name.strip())
                            available.append({"axis": AXIS_PROCESS,
                                              "corner": lbl, "source": src})
                        else:
                            available.append({"axis": AXIS_PROCESS,
                                              "corner": name.strip(),
                                              "source": src})
                elif isinstance(c, str) and c.strip():
                    available.append({"axis": AXIS_PROCESS, "corner": c.strip(),
                                      "source": src})

    # -- citations: an STA artifact naming the report its numbers came from.
    dangling: List[Dict[str, str]] = []
    for rel, field in _CITING_ARTIFACTS:
        art = project / rel
        if not art.is_file():
            continue
        data = _load_json(art)
        if not data:
            continue
        cited = data.get(field)
        if not isinstance(cited, str) or not cited.strip():
            continue
        target = Path(cited)
        if not target.is_absolute():
            target = project / cited
        if not target.is_file():
            dangling.append({"citing_artifact": rel, "cited_report": cited})

    return {
        "declared": declared, "available": available, "primary": primary,
        "labels": labels, "aliases": aliases, "sources": sources,
        "dangling_citations": dangling,
    }


# ── record discovery ───────────────────────────────────────────────────────
def read_records(project: Path,
                 decl: Dict[str, object]) -> Dict[Tuple[str, str], Dict[str, object]]:
    """Every per-corner timing datapoint the run actually produced, keyed by
    (axis, corner)."""
    recs: Dict[Tuple[str, str], Dict[str, object]] = {}

    def _put(axis: str, corner: str, source: str,
             vals: Dict[str, Optional[float]]) -> None:
        k = _key(axis, corner)
        rec = recs.setdefault(k, {"corner": corner, "axis": axis,
                                  "setup_wns_ns": None, "hold_wns_ns": None,
                                  "tns_ns": None, "source": source})
        for f in ("setup_wns_ns", "hold_wns_ns", "tns_ns"):
            rec[f] = _merge_slack(rec.get(f), vals.get(f))  # type: ignore[arg-type]
        if source not in str(rec["source"]).split(", "):
            rec["source"] = f"{rec['source']}, {source}"

    declared = decl.get("declared") or []
    rc_role_corner = {d["role"]: d["corner"] for d in declared  # type: ignore[index]
                      if d["axis"] == AXIS_RC}                  # type: ignore[index]
    proc_role_corner = {d["role"]: d["corner"] for d in declared  # type: ignore[index]
                        if d["axis"] == AXIS_PROCESS}            # type: ignore[index]

    # -- multicorner SPEF report (RC axis): sections carry the roles
    mc = _first_existing(project, _MULTICORNER_CANDIDATES)
    if mc is not None:
        try:
            text = mc.read_text(errors="replace")
        except OSError:
            text = ""
        src = _rel(project, mc)
        for kind, _corner, body in _split_sections(text):
            role = "setup" if kind == "SETUP" else "hold"
            corner = rc_role_corner.get(role)
            if corner is None:
                corner = kind.lower()
            vals = extract_slacks(body)
            # A SETUP section contributes the setup datapoint only, and a HOLD
            # section the hold datapoint only; TNS travels with its section.
            _put(AXIS_RC, corner, src, {
                "setup_wns_ns": vals["setup_wns_ns"] if role == "setup" else None,
                "hold_wns_ns": vals["hold_wns_ns"] if role == "hold" else None,
                "tns_ns": vals["tns_ns"],
            })

    # -- multi-corner OCV report (PROCESS axis): headers name the process corner
    ocv = _first_existing(project, _MCORNER_OCV_CANDIDATES)
    if ocv is not None:
        try:
            text = ocv.read_text(errors="replace")
        except OSError:
            text = ""
        src = _rel(project, ocv)
        for kind, corner, body in _split_sections(text):
            role = "setup" if kind == "SETUP" else "hold"
            name = corner or proc_role_corner.get(role) or kind.lower()
            vals = extract_slacks(body)
            _put(AXIS_PROCESS, name, src, {
                "setup_wns_ns": vals["setup_wns_ns"] if role == "setup" else None,
                "hold_wns_ns": vals["hold_wns_ns"] if role == "hold" else None,
                "tns_ns": vals["tns_ns"],
            })

    # -- per-corner sweep (PROCESS axis): one report per corner, name in filename
    for rel in _PER_CORNER_DIRS:
        pc_dir = project / rel
        if not pc_dir.is_dir():
            continue
        for rpt in sorted(pc_dir.glob("sta_*.rpt")):
            m = _PER_CORNER_RPT_RE.match(rpt.name)
            if not m:
                continue
            try:
                body = rpt.read_text(errors="replace")
            except OSError:
                body = ""
            _put(AXIS_PROCESS, m.group(1), _rel(project, rpt),
                 extract_slacks(body))

    # -- nominal single-corner SPEF report: the typ datapoint. Named from the
    #    flow's own RC availability list (the extracted corner that was NOT
    #    assigned the setup or hold role); falls back to a descriptive label
    #    rather than guessing a corner name.
    nom = _first_existing(project, _NOMINAL_SPEF_CANDIDATES)
    if nom is not None:
        avail_rc = [a["corner"] for a in (decl.get("available") or [])  # type: ignore[index]
                    if a["axis"] == AXIS_RC]                            # type: ignore[index]
        roled = {str(c).strip().lower() for c in rc_role_corner.values()}
        leftover = [c for c in dict.fromkeys(avail_rc)
                    if str(c).strip().lower() not in roled]
        name = leftover[0] if len(leftover) == 1 else "nominal"
        try:
            body = nom.read_text(errors="replace")
        except OSError:
            body = ""
        _put(AXIS_RC, name, _rel(project, nom), extract_slacks(body))

    return recs


# ── evaluation ─────────────────────────────────────────────────────────────
def evaluate(project: Path,
             slack_tol: float = _DEFAULT_SLACK_TOL_NS) -> Dict[str, object]:
    """Pure evaluator over a run dir. ALWAYS returns the full per-corner
    evidence table under `corners`, whatever the verdict."""
    decl = read_declarations(project)
    records = read_records(project, decl)

    declared: List[Dict[str, str]] = decl.get("declared") or []   # type: ignore[assignment]
    available: List[Dict[str, str]] = decl.get("available") or []  # type: ignore[assignment]
    primary = decl.get("primary")
    labels: Dict[str, str] = decl.get("labels") or {}              # type: ignore[assignment]
    aliases: Dict[Tuple[str, str], List[str]] = decl.get("aliases") or {}  # type: ignore[assignment]

    primary_names = set()
    if isinstance(primary, dict):
        pname = str(primary.get("corner", "")).strip().lower()
        if pname:
            primary_names.add(pname)
            for nm, lb in labels.items():
                if lb.strip().lower() == pname:
                    primary_names.add(nm)

    # Roles per (axis, corner).
    roles: Dict[Tuple[str, str], List[str]] = {}
    decl_src: Dict[Tuple[str, str], str] = {}
    for d in declared:
        k = _key(d["axis"], d["corner"])
        roles.setdefault(k, [])
        if d["role"] not in roles[k]:
            roles[k].append(d["role"])
        decl_src.setdefault(k, d.get("source", ""))

    # Build the union of every corner worth showing.
    all_keys: Dict[Tuple[str, str], str] = {}
    for d in declared:
        all_keys[_key(d["axis"], d["corner"])] = d["corner"]
    for a in available:
        all_keys.setdefault(_key(a["axis"], a["corner"]), a["corner"])
    for k, r in records.items():
        all_keys.setdefault(k, str(r["corner"]))

    findings: List[str] = []
    rules: List[str] = []
    table: List[Dict[str, object]] = []

    for k in sorted(all_keys, key=lambda x: (x[0], x[1])):
        axis, _lower = k
        name = all_keys[k]
        rec = records.get(k)
        corner_roles = roles.get(k, [])
        is_declared = k in roles
        if is_declared:
            role_class = "signoff"
        elif _lower in primary_names and axis == AXIS_PROCESS:
            role_class = "primary"
        elif rec is not None and not corner_roles:
            # Reported but never assigned a role: still evidence. If it is the
            # nominal corner name on the RC axis, call it primary.
            role_class = "primary" if _lower in {"nom", "nominal", "typ", "tt"} \
                else "unroled_reported"
        else:
            role_class = "available_not_selected"

        table.append({
            "corner": name,
            "axis": axis,
            "label": labels.get(_lower),
            "liberty_aliases": aliases.get(k) or [],
            "roles": corner_roles,
            "role_class": role_class,
            "declared": is_declared,
            "reported": rec is not None,
            "setup_wns_ns": rec.get("setup_wns_ns") if rec else None,
            "hold_wns_ns": rec.get("hold_wns_ns") if rec else None,
            "tns_ns": rec.get("tns_ns") if rec else None,
            "source": (rec.get("source") if rec else decl_src.get(k)) or None,
        })

    # ---- a verdict that outlived the report it cites -----------------------
    # This is R2 in its starkest form: the citation proves corners WERE
    # analysed, and the missing target proves nothing survived to substantiate
    # it. Judged BEFORE the not-applicable escape, so a run whose only STA
    # trace is a dangling verdict cannot exit as "nothing to judge".
    dangling: List[Dict[str, str]] = decl.get("dangling_citations") or []  # type: ignore[assignment]
    for dc in dangling:
        rules.append("R2_DECLARED_BUT_UNREPORTED")
        findings.append(
            f"R2 {dc['citing_artifact']} reports STA results but cites "
            f"'{dc['cited_report']}', which does NOT exist — the verdict has "
            f"outlived the evidence it rests on, so its corners are unreported")

    # ---- nothing declared and nothing recorded → say so, invent nothing -----
    if not declared and not records and not dangling:
        return {
            "verdict": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
            "reasons": ["no_corner_declaration: no stance file, pvt_matrix or "
                        "STA report declares or records any corner — there is "
                        "no timing record to judge (this gate does not invent "
                        "a sign-off corner set)"],
            "corners": table, "primary_corner": primary,
            "declaration_sources": decl.get("sources"),
            "slack_tol_ns": slack_tol, "rules_violated": [],
        }

    # ---- R2: every declared (corner, role) needs that role's datapoint -----
    for k, corner_roles in sorted(roles.items()):
        axis, _lower = k
        name = all_keys.get(k, k[1])
        rec = records.get(k)
        for role in corner_roles:
            field = "setup_wns_ns" if role == "setup" else "hold_wns_ns"
            if rec is None:
                rules.append("R2_DECLARED_BUT_UNREPORTED")
                findings.append(
                    f"R2 sign-off corner '{name}' ({axis} axis, declared as the "
                    f"{role.upper()} corner by {decl_src.get(k) or 'the flow'}) "
                    f"has NO timing datapoint anywhere in the record — an "
                    f"unreported corner is indistinguishable from a met one")
            elif rec.get(field) is None:
                rules.append("R2_DECLARED_BUT_UNREPORTED")
                findings.append(
                    f"R2 sign-off corner '{name}' ({axis} axis) was declared as "
                    f"the {role.upper()} corner but its record carries no worst "
                    f"{role} slack (source: {rec.get('source')})")

    # ---- R1: reported corners must be named + complete when unroled --------
    for row in table:
        if not row.get("reported"):
            continue
        if not str(row.get("corner") or "").strip():
            rules.append("R1_INCOMPLETE_CORNER_RECORD")
            findings.append(
                f"R1 a timing datapoint in {row.get('source')} is not "
                f"identified by corner name")
            continue
        if row.get("roles"):
            continue  # judged by R2 against its declared role(s)
        if row.get("role_class") == "primary":
            # The nominal/typ corner carries NO sign-off role: setup is signed
            # off at the slow corner and hold at the fast one, so the nominal
            # single-corner report legitimately reports setup only. Demanding
            # hold from it would be a FABRICATED violation — it would fail every
            # run in the corpus including the genuinely clean ones. The nominal
            # datapoint is still shown in the evidence table, and R3 still uses
            # it to expose the typ-MET-while-signoff-VIOLATED misleading pass.
            continue
        missing = [k for k in ("setup_wns_ns", "hold_wns_ns")
                   if row.get(k) is None]
        if missing:
            rules.append("R1_INCOMPLETE_CORNER_RECORD")
            pretty = " and ".join(
                {"setup_wns_ns": "setup", "hold_wns_ns": "hold"}[m]
                for m in missing)
            findings.append(
                f"R1 corner '{row['corner']}' ({row['axis']} axis) ran and is "
                f"reported but carries no declared sign-off role and omits "
                f"worst {pretty} slack — an incomplete corner characterisation "
                f"(source: {row.get('source')})")

    # ---- R3: a violated sign-off corner governs, whatever typ says ---------
    typ_met: List[str] = []
    signoff_violated: List[str] = []
    for row in table:
        if not row.get("reported"):
            continue
        vals = [float(row[f]) for f in ("setup_wns_ns", "hold_wns_ns")   # type: ignore[arg-type]
                if row.get(f) is not None]
        if not vals:
            continue
        worst = min(vals)
        if row.get("role_class") == "primary" and worst >= -slack_tol:
            typ_met.append(f"{row['corner']} ({row['axis']})")
        if row.get("role_class") != "signoff":
            continue
        if worst < -slack_tol:
            rules.append("R3_SIGNOFF_CORNER_VIOLATION")
            signoff_violated.append(str(row["corner"]))
            detail = []
            for f, tag in (("setup_wns_ns", "setup"), ("hold_wns_ns", "hold")):
                v = row.get(f)
                if v is not None and float(v) < -slack_tol:
                    detail.append(f"{tag} {float(v):+.3f} ns")
            tns_s = ("" if row.get("tns_ns") is None
                     else f", TNS {float(row['tns_ns']):.2f}")   # type: ignore[arg-type]
            findings.append(
                f"R3 SIGN-OFF corner '{row['corner']}' ({row['axis']} axis, "
                f"role {'/'.join(row.get('roles') or []) or 'signoff'}) is "
                f"VIOLATED: {', '.join(detail) or f'{worst:+.3f} ns'}{tns_s} "
                f"(source: {row.get('source')})")

    if signoff_violated and typ_met:
        findings.append(
            f"R3 the primary/typ corner(s) {', '.join(sorted(set(typ_met)))} "
            f"MET while sign-off corner(s) "
            f"{', '.join(sorted(set(signoff_violated)))} VIOLATED — a typ-only "
            f"'MET' is a MISLEADING PASS and does not satisfy this run's timing")

    ordered = [r for r in ("R1_INCOMPLETE_CORNER_RECORD",
                           "R2_DECLARED_BUT_UNREPORTED",
                           "R3_SIGNOFF_CORNER_VIOLATION") if r in rules]
    passed = not ordered
    return {
        "verdict": "PASS" if passed else "FAIL",
        "status": "PASS" if passed else "FAIL",
        "reasons": (findings if findings else
                    [f"timing record complete: every corner the flow declared "
                     f"is reported for the role it serves, and every sign-off "
                     f"corner MET (tol {slack_tol} ns)"]),
        "corners": table,
        "primary_corner": primary,
        "declaration_sources": decl.get("sources"),
        "slack_tol_ns": slack_tol,
        "rules_violated": ordered,
    }


def render_table(res: Dict[str, object]) -> str:
    """The per-corner evidence table. Emitted on PASS and FAIL alike — the
    absence of this table is the very defect this gate exists to prevent."""
    rows = res.get("corners") or []
    hdr = (f"{'corner':<38} {'axis':<8} {'role':<22} {'rep':<4} "
           f"{'setup_wns':>10} {'hold_wns':>10} {'tns':>12}  source")
    lines = [hdr, "-" * len(hdr)]
    if not rows:
        lines.append("(no corners declared or reported)")
    for r in rows:  # type: ignore[union-attr]
        def _f(key: str) -> str:
            v = r.get(key)
            return "n/a" if v is None else f"{float(v):+.3f}"
        tns = r.get("tns_ns")
        role = str(r.get("role_class") or "")
        if r.get("roles"):
            role = f"{role}:{'/'.join(r['roles'])}"
        lines.append(
            f"{str(r.get('corner'))[:38]:<38} {str(r.get('axis')):<8} "
            f"{role[:22]:<22} {'yes' if r.get('reported') else 'NO':<4} "
            f"{_f('setup_wns_ns'):>10} {_f('hold_wns_ns'):>10} "
            f"{('n/a' if tns is None else f'{float(tns):.2f}'):>12}  "
            f"{r.get('source') or '-'}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir")
    p.add_argument("--slack-tol", type=float, default=_DEFAULT_SLACK_TOL_NS,
                   help="float-noise guard (ns); a slack below -slack_tol is a "
                        "violation (default 0.001)")
    p.add_argument("--json", default=None, help="write the verdict JSON here")
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"{_PROGRAM}: not a directory: {project}", file=sys.stderr)
        return 2

    res = evaluate(project, slack_tol=args.slack_tol)

    out_path = None
    if args.json:
        out_path = Path(args.json)
        if not out_path.is_absolute():
            out_path = project / args.json
    elif _pl is not None:
        try:
            out_path = _pl.report_path(
                project, "phase3/sta/sta_corner_record_completeness.json")
        except Exception:
            out_path = None
    if out_path is not None:
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(res, indent=2) + "\n")
        except OSError as e:
            print(f"{_PROGRAM}: cannot write {out_path}: {e}", file=sys.stderr)
            return 2

    tag = str(res["verdict"])
    print(f"[{'PASS' if tag in ('PASS', 'NOT_APPLICABLE') else tag}] "
          f"{_PROGRAM}: {tag}")
    print(render_table(res))
    for reason in res.get("reasons", []):  # type: ignore[union-attr]
        print(f"  - {reason}")
    return 0 if tag in ("PASS", "NOT_APPLICABLE") else 1


if __name__ == "__main__":
    sys.exit(main())
