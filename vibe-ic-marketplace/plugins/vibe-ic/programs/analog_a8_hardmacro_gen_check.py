#!/usr/bin/env python3
"""analog_a8_hardmacro_gen_check.py — A8 deterministic gate.

Verifies that the upstream `analog-hardmacro-gen` skill has emitted
the canonical per-block A8 artefact triple (LEF + Liberty + Verilog):

    analog/hardmacro/<block>/<block>.lef
    analog/hardmacro/<block>/<block>.lib
    analog/hardmacro/<block>/<block>.v

with substance (matching the v1.6.30 thresholds enforced by
`analog_artefact_substance_check`):

  * .lef ≥ 250 bytes
  * .lib ≥ 200 bytes
  * .v   ≥ 150 bytes
  * none of the three contains a v1.6.30 stub-marker phrase.

Failure rules:
  A8_HARDMACRO_LEF_MISSING    — analog/hardmacro/<block>/<block>.lef absent
  A8_HARDMACRO_LIB_MISSING    — .lib absent
  A8_HARDMACRO_V_MISSING      — .v absent
  A8_HARDMACRO_TOO_SMALL      — present but below per-ext threshold
  A8_HARDMACRO_LEF_NO_PINS    — the LEF has no PIN for any declared port
  A8_HARDMACRO_LEF_PIN_MISSING — a declared port is not a LEF PIN
  A8_HARDMACRO_RAIL_NOT_PG    — a declared rail PIN is not USE POWER/GROUND
  A8_HARDMACRO_PIN_LAYER_MISMATCH — a PIN is not on the layer A5 drew it on
  A8_HARDMACRO_PIN_NOT_ROUTING_LAYER — a PIN is on a cut layer, or a signal
                                  PIN on the lowest routing layer
  A8_HARDMACRO_SIGNAL_PIN_NOT_ON_EDGE — a signal PIN touches no macro edge
  A8_HARDMACRO_PG_PIN_UNREACHABLE — the PnR PDN planner cannot reach a
                                  supply PIN (or it cannot be asked)
                                  (the last four only for a block whose A5
                                  layout declares its pins)
  A8_HARDMACRO_STUB_MARKER    — file matches stub-marker panel
                                  (`ai_authored_methodology_stub`,
                                  `behavioral stub`, `placeholder
                                  hardmacro`, `do not tape out`, ...)

Project-level verdicts (no `--block`):
  VACUOUS_PASS — no `analog_block_list.json` under `phase3/analog/` or
                 `phase1/analog/`, or it declares no blocks; or EVERY
                 declared block is still missing the whole hardmacro triple
                 (the step has not run at all → defer to
                 `analog-hardmacro-gen`).
  INCOMPLETE   — SOME declared blocks were packaged and others produced no
                 hardmacro at all (exit 1). Step 14 (floorplan) consumes
                 these LEF abstracts, so an unpackaged declared block is a
                 macro the digital floorplan cannot reserve area for; the
                 gate names it instead of certifying the step.
  PASS         — every declared block cleared every check.
  PASS_STRUCTURE_ONLY
               — every certified block's package models a LIBRARY TOPOLOGY,
                 and the artefact chain says so. It certifies, in its own
                 tier, never as a design-bound pass.
chip-AGNOSTIC.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import sys
import json
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    BLOCK_LIST_ABSENT_REASON, CONTENT_GATE_OF_RECORD_ARTEFACT,
    CONTENT_STRUCTURE_ONLY, CONTENT_UNDISCLOSED, STRUCTURE_ONLY_TOKEN,
    hardmacro_content,
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    artefact_missing_for_block, emit_pass, emit_fail,
    emit_incomplete,
)

GATE = "analog_a8_hardmacro_gen_check"
SKILL = "analog-hardmacro-gen"

# ── A PACKAGE IS A PACKAGE OF SOMETHING ───────────────────────────────────
# THE RULE, with no tool, step or block name in it, and it is the same rule
# the sibling gates on this track already apply:
#
#   A gate that certifies an artefact for downstream consumption is certifying
#   a claim about what that artefact contains. An artefact chain that declines
#   to say what it contains must not certify the step it is the evidence for.
#
# WHY IT REACHES THIS GATE. The hardmacro is what digital PnR INSTANTIATES and
# what integration STA CLOSES ON. MEASURED, over one complete synthetic package
# (.gds + .lef + .lib + .v) on three trees identical in every artefact except
# the one recorded `design_content` value:
#
#   analog_a8_hardmacro_gen_check      PASS / PASS / PASS
#   analog_hardmacro_check             PASS / PASS / PASS
#   analog_liberty_nonzero_delay_check PASS / PASS_STRUCTURE_ONLY / FAIL
#
# Three gates over ONE package; the two that answer for the STEP could not tell
# the trees apart and the one that reads the field could. (The pair does NOT
# reproduce on a `.lib`-only fixture: both A8 gates exit 1 on the missing
# `.lef`/`.v`/`.gds` first and the disagreement is masked. It needs a complete
# package, which is what `test_two_gates_over_one_hardmacro_agree` builds.)
#
# WHERE THE ANSWER IS READ. Nothing writes `design_content` into a LEF, a
# Liberty, a GDS or a behavioural Verilog, so the whole answer is the corner
# artefact's — the gate of record's own subject. One shared site,
# `_analog_a_check_common.hardmacro_content`, for every gate over this package.
#
# ASKED LAST, after every deliverable and substance rule (missing / too small /
# stub marker), each of which names a deeper cause and answers this one as a
# side effect.
_CONTENT_BASELINE = CONTENT_GATE_OF_RECORD_ARTEFACT

# Per-ext thresholds (aligned with v1.6.30
# analog_artefact_substance_check defaults).
_MIN_BYTES = {".lef": 250, ".lib": 200, ".v": 150}

# Substring markers (lower-cased) — chip-AGNOSTIC. Mirrors the panel
# in `analog_artefact_substance_check._STUB_MARKERS_DEFAULT`.
_STUB_MARKERS = (
    "ai_authored_methodology_stub", "ai_authored_stub",
    "methodology_stub", "methodology placeholder",
    "behavioral stub", "behavioural stub",
    "placeholder netlist", "placeholder layout",
    "placeholder hardmacro",
    "stub: do not tape out", "do not tape out",
    "todo implement", "todo: implement",
    "__stub__", "@stub",
)


def _lef_pin_blocks(text: str) -> dict:
    """`{pin name (lower): USE value (upper) or None}` over a LEF MACRO body.
    LEF is a formal grammar (`PIN <n> ... END <n>`), read structurally."""
    pins: dict = {}
    current = None
    for raw in text.splitlines():
        tok = raw.split()
        if not tok:
            continue
        if tok[0] == "PIN" and len(tok) > 1:
            current = tok[1].lower()
            pins[current] = None
        elif current is not None and tok[0] == "USE" and len(tok) > 1:
            pins[current] = tok[1].rstrip(";").upper()
        elif current is not None and tok[0] == "END" and len(tok) > 1 \
                and tok[1].lower() == current:
            current = None
    return pins


def _declared_ports(project: Path, block: str) -> tuple:
    """`(ports, rails)` from the block's A2 topology IR, or `(None, None)`."""
    import json as _json
    ir = project / "phase3" / "analog" / block / "topology.json"
    try:
        doc = _json.loads(ir.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    ports = [str(p).lower() for p in (doc.get("ports") or [])]
    rails = {str(v).lower() for v in (doc.get("rails") or {}).values()}
    return ports, rails & set(ports)


def _lef_pin_findings(project: Path, block: str, lef_path: Path) -> List[dict]:
    """A MACRO IS PLACED BY ITS PINS (T94, A8 harvest #1). MEASURED on
    vibeic-eda 0.3.77 / u_hawaii_adc/ldo: the emitted LEF carried SIZE and OBS
    and zero PIN statements (A5's port labels sit on a cut layer, which
    Magic's `lef write` does not turn into a pin), while the emitter printed
    "4 pin(s)" from the topology and this gate PASSED it on size alone.

    Every port the block's topology declares must be a LEF PIN; a declared
    rail that is a PIN must carry USE POWER or USE GROUND, or pdngen reads
    the supply as a signal. No topology IR → nothing to compare, no finding.
    """
    ports, rails = _declared_ports(project, block)
    if not ports:
        return []
    pins = _lef_pin_blocks(lef_path.read_text(encoding="utf-8",
                                              errors="replace"))
    rel = str(lef_path.relative_to(project))
    missing = [p for p in ports if p not in pins]
    out: List[dict] = []
    if missing:
        out.append({"block": block, "rule": ("A8_HARDMACRO_LEF_NO_PINS"
                                             if not pins else
                                             "A8_HARDMACRO_LEF_PIN_MISSING"),
                    "rel_path": rel,
                    "detail": (f"declared port(s) {missing} are not PINs of "
                               f"the macro LEF ({len(pins)} PIN(s) present); "
                               f"digital PnR has nothing to connect them to")})
    bad = sorted(r for r in rails if r in pins
                 and pins[r] not in ("POWER", "GROUND"))
    if bad:
        out.append({"block": block, "rule": "A8_HARDMACRO_RAIL_NOT_PG",
                    "rel_path": rel,
                    "detail": (f"declared rail pin(s) {bad} carry USE "
                               f"{[pins[r] for r in bad]}, not POWER/GROUND")})
    return out


# ── WHERE THE PINS ARE, AND WHETHER A ROUTER AND A GRID CAN REACH THEM ──────
# (analog decision q2-pin-layer). A PIN is not enough: a pin on a cut layer is
# refused by every router, a signal pin inside the abstract's obstruction has
# no path to it (Magic's `lef write -hide` says so in its own source), and a
# supply pin the PDN planner cannot cross is a macro with no power. These are
# asked of the LEF against what A5 DECLARED each pin to be
# (`layout_provenance.json` `pins`). A block whose layout declares no pins is
# judged by the rules above alone, exactly as before.

#: LEF geometry is on a 0.005 um manufacturing grid at the coarsest; a pin
#: edge within it of the boundary is ON the boundary.
_EDGE_TOL_UM = 0.005


def _lef_geometry(text: str) -> tuple:
    """`((W, H) or None, {pin: {layer: [rects]}})` from a LEF MACRO."""
    size = None
    pins: dict = {}
    cur = None
    layer = None
    for raw in text.splitlines():
        tok = raw.replace(";", " ").split()
        if not tok:
            continue
        if tok[0] == "SIZE" and len(tok) >= 4 and size is None:
            try:
                size = (float(tok[1]), float(tok[3]))
            except ValueError:
                size = None
        elif tok[0] == "PIN" and len(tok) > 1:
            cur, layer = tok[1].lower(), None
            pins.setdefault(cur, {})
        elif tok[0] == "OBS":
            cur = None
        elif cur is not None and tok[0] == "LAYER" and len(tok) > 1:
            layer = tok[1]
            pins[cur].setdefault(layer, [])
        elif cur is not None and layer and tok[0] == "RECT" and len(tok) >= 5:
            try:
                pins[cur][layer].append(tuple(float(v) for v in tok[1:5]))
            except ValueError:
                pass
        elif cur is not None and tok[0] == "END" and len(tok) > 1 \
                and tok[1].lower() == cur:
            cur = None
    return size, pins


def _declared_pins(project: Path, block: str) -> tuple:
    """`(pins, tech_layers)` A5 recorded for this block, or `([], None)`."""
    import json as _json
    prov = project / "phase3" / "analog" / block / "layout_provenance.json"
    try:
        doc = _json.loads(prov.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], None
    pins = [p for p in (doc.get("pins") or []) if isinstance(p, dict)]
    layers = (doc.get("pins_basis") or {}).get("tech_lef_layers")
    return pins, (layers if isinstance(layers, list) and layers else None)


def _tech_lef_text(rows: list) -> str:
    """The PDK layer table A5 read, re-serialised as the LEF it came from, so
    the PDN planner reads it through its own parser."""
    out = []
    for r in rows:
        out.append(f"LAYER {r.get('name')}")
        out.append(f"  TYPE {r.get('type')} ;")
        if r.get("direction"):
            out.append(f"  DIRECTION {r['direction']} ;")
        if r.get("pitch"):
            out.append(f"  PITCH {r['pitch']} ;")
        if r.get("width"):
            out.append(f"  WIDTH {r['width']} ;")
        out.append(f"END {r.get('name')}")
    return "\n".join(out) + "\n"


def _normal_core_followpin(project: Path, block: str,
                           routing: List[str]) -> tuple:
    """Re-read A5's captured stdcell LEF with the normal-core PG parser.

    Neither tech-LEF order nor Magic metal order identifies a stdcell rail.
    Read the selected standard-cell LEF with the normal-core PG parser;
    its measured layer must exist in the selected technology LEF.
    """
    prov = project / "phase3" / "analog" / block / "layout_provenance.json"
    try:
        doc = json.loads(prov.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "A5 layout provenance is unreadable"
    basis = doc.get("pins_basis") if isinstance(doc, dict) else None
    pg = basis.get("core_pg") if isinstance(basis, dict) else None
    if not isinstance(pg, dict) or pg.get("result") != "MEASURED":
        return None, "A5 standard-cell LEF PG facts are absent or not measured"
    snapshot = project / "phase3" / "analog" / block / "a5_stdcell_pg.lef"
    source = pg.get("source")
    original = Path(source) if isinstance(source, str) and source else snapshot
    selected = original if original.is_file() else snapshot
    if not selected.is_file():
        return None, "A5 standard-cell LEF is unreadable"
    prefix = pg.get("metal_prefix")
    if not isinstance(prefix, str) or not prefix:
        return None, "A5 standard-cell LEF metal prefix is absent"
    import phase3_one_shot_runner as p3
    measured = p3._discover_pg_from_lef(str(selected), prefix)
    if measured is None:
        return None, "the selected standard-cell LEF has no measurable PG rails"
    followpin = measured[2]
    if followpin not in routing:
        return None, "the measured stdcell follow-pin layer is absent from the tech LEF"
    return followpin, str(selected)


def _pin_access_findings(project: Path, block: str, lef_text: str,
                         rel: str) -> List[dict]:
    declared, tech = _declared_pins(project, block)
    if not declared:
        return []
    size, geo = _lef_geometry(lef_text)
    out: List[dict] = []

    def find(rule: str, detail: str) -> None:
        out.append({"block": block, "rule": rule, "rel_path": rel,
                    "detail": detail})

    ttype = {str(r.get("name")).lower(): str(r.get("type") or "").upper()
             for r in (tech or [])}
    routing = [str(r.get("name")) for r in (tech or [])
               if str(r.get("type") or "").upper() == "ROUTING"]
    for p in declared:
        net = str(p.get("net", "")).lower()
        want = str(p.get("lef_layer") or "")
        got = geo.get(net, {})
        if not got:
            continue            # a missing PIN is LEF_PIN_MISSING's finding
        if want and set(got) != {want}:
            find("A8_HARDMACRO_PIN_LAYER_MISMATCH",
                 f"port {net} was drawn as a {want} pin by A5, and the LEF "
                 f"declares it on {sorted(got)}")
        for layer in got:
            kind = ttype.get(layer.lower())
            if kind is None and tech is None:
                kind = str(p.get("lef_type") or "").upper() or None
            if kind != "ROUTING" or (not p.get("rail") and routing
                                     and layer == routing[0]):
                find("A8_HARDMACRO_PIN_NOT_ROUTING_LAYER",
                     f"port {net} is a PIN on {layer} "
                     f"({kind or 'a layer the PDK table does not declare'}"
                     f"{', the lowest routing layer' if kind == 'ROUTING' else ''}"
                     f"); a macro pin must be on a routing layer a signal "
                     f"router may use")
        if not p.get("rail"):
            if size is None:
                find("A8_HARDMACRO_SIGNAL_PIN_NOT_ON_EDGE",
                     f"the LEF states no SIZE, so whether port {net} touches "
                     f"the macro boundary is NOT MEASURED")
                continue
            w, h = size
            t = _EDGE_TOL_UM
            if not any(r[0] <= t or r[1] <= t or r[2] >= w - t
                       or r[3] >= h - t
                       for rs in got.values() for r in rs):
                find("A8_HARDMACRO_SIGNAL_PIN_NOT_ON_EDGE",
                     f"no rectangle of signal pin {net} touches the macro "
                     f"boundary (0 0 {w} {h}); an abstract written with "
                     f"`-hide` obstructs everything inside it, so a router "
                     f"has no path to an interior pin")
    rails = [p for p in declared if p.get("rail")]
    if not rails:
        return out
    if tech is None:
        find("A8_HARDMACRO_PG_PIN_UNREACHABLE",
             "A5 recorded no PDK layer table, so whether the PDN planner can "
             "reach the supply pins is NOT MEASURED")
        return out
    try:
        import phase3_one_shot_runner as _p3
    except Exception as exc:  # noqa: BLE001 — named, never a pass
        find("A8_HARDMACRO_PG_PIN_UNREACHABLE",
             f"the PDN planner could not be loaded ({type(exc).__name__}); "
             f"supply-pin reach is NOT MEASURED")
        return out
    tech_text = _tech_lef_text(tech)
    followpin, followpin_source = _normal_core_followpin(
        project, block, routing)
    if not followpin:
        find("A8_HARDMACRO_PG_PIN_UNREACHABLE",
             "the normal-core follow-pin layer is NOT MEASURED: "
             f"{followpin_source}; refusing to infer it from tech LEF "
             "declaration order")
        return out
    straps = _p3._auto_pdn_straps_from_techlef(tech_text, followpin) or {}
    outcome = _p3._macro_pdn_grid_outcome([lef_text], tech_text,
                                          straps.get("stripes") or [],
                                          followpin)
    for ref in outcome.get("refusals") or []:
        find("A8_HARDMACRO_PG_PIN_UNREACHABLE",
             f"the PnR PDN planner refuses this macro's supply pins: "
             f"{ref.get('reason')} — {ref.get('detail')}")
    plan = outcome.get("plan") or {}
    unreachable = sorted({str(u[1]) for u in plan.get("unreachable") or []})
    if unreachable:
        find("A8_HARDMACRO_PG_PIN_UNREACHABLE",
             f"supply pin(s) {unreachable} are narrower across the "
             f"{plan.get('strap_layer')} macro strap than its smallest legal "
             f"pitch {plan.get('pitch_floor')} um, so no strap is guaranteed "
             f"to cross them")
    if outcome.get("plan") is None and not outcome.get("refusals"):
        find("A8_HARDMACRO_PG_PIN_UNREACHABLE",
             "the LEF carries no POWER/GROUND pin for the PDN planner to "
             "reach, although A5 drew supply pins")
    return out




def _check_block(project: Path, block: str
                 ) -> tuple[Optional[str], List[dict]]:
    hdir = project / "phase3" / "analog" / "hardmacro" / block
    triples = (
        (".lef", hdir / f"{block}.lef", "A8_HARDMACRO_LEF_MISSING"),
        (".lib", hdir / f"{block}.lib", "A8_HARDMACRO_LIB_MISSING"),
        (".v",   hdir / f"{block}.v",   "A8_HARDMACRO_V_MISSING"),
    )
    findings: List[dict] = []
    missing_count = 0
    for ext, path, missing_rule in triples:
        if not path.is_file():
            findings.append({
                "block": block, "rule": missing_rule,
                "rel_path": str(path.relative_to(project))
                            if path.exists()
                            else f"analog/hardmacro/{block}/{block}{ext}",
                "detail": f"hardmacro {ext} not found",
            })
            missing_count += 1
            continue
        try:
            size = path.stat().st_size
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError as exc:
            findings.append({
                "block": block, "rule": "A8_HARDMACRO_TOO_SMALL",
                "rel_path": str(path.relative_to(project)),
                "detail": f"OSError: {exc}",
            })
            continue
        if size < _MIN_BYTES[ext]:
            findings.append({
                "block": block, "rule": "A8_HARDMACRO_TOO_SMALL",
                "rel_path": str(path.relative_to(project)),
                "detail": f"{size}B < min {_MIN_BYTES[ext]}B for {ext}",
            })
        hits = [m for m in _STUB_MARKERS if m in text]
        if hits:
            findings.append({
                "block": block, "rule": "A8_HARDMACRO_STUB_MARKER",
                "rel_path": str(path.relative_to(project)),
                "detail": f"file matches stub marker(s): "
                          f"{', '.join(hits)}",
            })
    # All three missing → MISSING (per-block --block mode → WAIVED).
    if missing_count == 3:
        return "MISSING", findings
    lef_path = hdir / f"{block}.lef"
    if lef_path.is_file():
        findings.extend(_lef_pin_findings(project, block, lef_path))
        findings.extend(_pin_access_findings(
            project, block,
            lef_path.read_text(encoding="utf-8", errors="replace"),
            str(lef_path.relative_to(project))))
    if findings:
        return "FAIL", findings

    # ── the certification question, asked LAST ────────────────────────────
    adir = project / "phase3" / "analog" / block
    bounded = hardmacro_content(adir)
    if bounded.klass == CONTENT_UNDISCLOSED:
        # `ceiling_source is None` covers BOTH "the artefact is absent" and
        # "the artefact is present and silent". Those send a reader to two
        # different places, so the message asks the filesystem rather than
        # inferring from a None.
        said = (f"`{_CONTENT_BASELINE}` records no answer to"
                if (adir / _CONTENT_BASELINE).is_file()
                else "no corner artefact exists to say")
        return "FAIL", [{
            "block": block, "rule": "A8_DESIGN_CONTENT_UNDECLARED",
            "rel_path": f"phase3/analog/hardmacro/{block}/",
            "detail": (f"the LEF / Liberty / Verilog triple is complete and "
                       f"substantive, and {said} what circuit this package "
                       f"models (`design_content`). Digital PnR will "
                       f"instantiate this macro as this design's and "
                       f"integration STA will close on its timing; a package "
                       f"that will not name its subject must not be signed "
                       f"off for it. Declaring `{CONTENT_STRUCTURE_ONLY}` is "
                       f"not a penalty — it certifies, in its own disclosed "
                       f"tier; declining to answer does not, or saying "
                       f"nothing would cost less than saying so."),
        }]
    if bounded.klass == CONTENT_STRUCTURE_ONLY:
        return "PASS_STRUCTURE_ONLY", [{
            "block": block, "rule": "A8_HARDMACRO_STRUCTURE_ONLY",
            "rel_path": f"phase3/analog/hardmacro/{block}/",
            "content_source": (str(bounded.source)
                               if bounded.source is not None else None),
            "detail": ("the triple is complete and substantive, and the "
                       "artefact chain records that the packaged circuit came "
                       "from a topology library with no bound input reaching "
                       "any device parameter — the package is real and it is "
                       "the default's, not this design's"),
        }]
    return "PASS", []


def main(argv: Optional[List[str]] = None) -> int:
    ap = make_argparser(GATE, __doc__)
    args = ap.parse_args(argv)
    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 2

    blocks_all = load_block_list(project)
    if blocks_all is None or (not blocks_all and not args.block):
        return vacuous_pass(GATE, args,
                            BLOCK_LIST_ABSENT_REASON)

    blocks = select_blocks(blocks_all or [], args.block)
    if not blocks:
        return vacuous_pass(GATE, args, "no blocks selected.")

    findings: List[dict] = []
    blocks_pass = 0
    missing_seen: List[dict] = []
    structure_only: List[str] = []
    design_bound: List[str] = []
    disclosures: List[dict] = []
    for block in blocks:
        status, fs = _check_block(project, block)
        if status == "PASS":
            blocks_pass += 1
            design_bound.append(block)
        elif status == "PASS_STRUCTURE_ONLY":
            # Certified, in its own tier: the block cleared every deliverable
            # and substance rule, and it is named separately because the
            # package it cleared them with is a library default's.
            blocks_pass += 1
            structure_only.append(block)
            disclosures.extend(fs)
        elif status == "MISSING":
            missing_seen.extend(fs)
        else:
            findings.extend(fs)

    # Same ranking as every sibling on this track: the tier reaches the verdict
    # word only when NO block was certified design-bound.
    pass_token = ("PASS_STRUCTURE_ONLY"
                  if (structure_only and not design_bound) else "PASS")
    summary = {
        "blocks_checked": len(blocks),
        "blocks_pass": blocks_pass,
        "blocks_design_bound_pass": len(design_bound),
        "blocks_structure_only": len(structure_only),
        "structure_only_blocks": structure_only,
        "blocks_missing": len(missing_seen),
        "blocks_fail": len({f["block"] for f in findings}),
    }
    if disclosures:
        summary["structure_only_findings"] = disclosures

    def _disclose() -> None:
        """LAST, SHORT, and on every path the gate can leave by — the
        disclosure the A-track runner and the flow auditor read from a
        fixed-width TAIL of this stream, whatever the verdict was."""
        if not structure_only:
            return
        names = ", ".join(structure_only)
        if len(names) > 60:
            names = f"{names[:57]}..."
        print(f"{STRUCTURE_ONLY_TOKEN} {len(structure_only)} hardmacro "
              f"package(s) ({names}) model a library default, not a bound "
              f"input [{GATE}]")

    if args.block:
        if findings:
            rc = emit_fail(GATE, args, findings, summary)
            _disclose()
            return rc
        if missing_seen:
            return artefact_missing_for_block(
                GATE, args, args.block,
                missing_seen[0]["rel_path"], SKILL)
        rc = emit_pass(GATE, args, summary, pass_token=pass_token)
        _disclose()
        return rc

    if findings:
        rc = emit_fail(GATE, args, findings, summary)
        _disclose()
        return rc
    if missing_seen and blocks_pass == 0:
        return vacuous_pass(GATE, args,
                            f"all blocks missing hardmacro triple; "
                            f"defer to skill `{SKILL}`.")
    if missing_seen:
        # PARTIAL block coverage — see the A7 note. A8's declared outputs are
        # the globs `phase3/analog/hardmacro/*/*.lef|lib|gds|v`, each satisfied
        # by its FIRST match, so one packaged block used to certify the step
        # for every declared block. That matters more at A8 than anywhere
        # else on this track: Step 14 (floorplan) consumes the LEF abstracts,
        # and a declared block with no LEF is a macro the digital floorplan
        # cannot reserve area for.
        rc = emit_incomplete(GATE, args, missing_seen, summary, SKILL)
        _disclose()
        return rc
    rc = emit_pass(GATE, args, summary, pass_token=pass_token)
    _disclose()
    return rc


if __name__ == "__main__":
    sys.exit(main())
