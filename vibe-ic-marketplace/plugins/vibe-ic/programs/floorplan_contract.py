"""G-FIXED-DIE-1 — shared design-PROVIDED fixed-floorplan-contract helpers.

A design can MANDATE a fixed floorplan: an exact die area, `FP_SIZING =
absolute`, a fixed DEF template, a fixed pin order, and fixed power-source
locations. Before this module, phase1 dropped that contract entirely — L19
carried `die_area_budget_um: null`, `floorplan_hints: []`,
`constraints_present: false` even when the design shipped an OpenLane-style
`config.json` with `DIE_AREA`/`FP_SIZING`/`FP_DEF_TEMPLATE` AND a prose
`DIE_AREA = [x0,y0,x1,y1] µm` statement — so phase3 auto-sized a die the
design had already fixed.

This module extracts that contract chip-AGNOSTICally from whatever the design
provides:
  - an OpenLane-style ``config.json`` (JSON) or classic ``config.tcl`` under
    ``input/**`` — ``DIE_AREA`` (rect [llx lly urx ury] → W×H), ``FP_SIZING``,
    ``FP_DEF_TEMPLATE``, ``FP_PIN_ORDER_CFG``;
  - the L9/constraint/floorplan prose docs — ``DIE_AREA = [x0,y0,x1,y1]``,
    ``FP_SIZING = <mode>``;
  - discovered fixed-floorplan aux files — ``pin_order*.cfg`` and
    power-source ``vsrc/*.loc`` files.

§4.05 / no-fabricate: only a real, positive numeric ``DIE_AREA`` rect (or an
unambiguous ``DIE_WIDTH`` + ``DIE_HEIGHT`` pair) counts. Everything is derived
from the design's own INPUT at runtime — NO chip name, vendor, SKU, or die
number is ever hardcoded. Both consumers (phase1 → L19, phase3 die-sizing)
read the same contract so they cannot drift.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import _reference_flow_boundary as _rfb

# Canonical DEF/OpenLane DIE_AREA rect: "llx lly urx ury" (4 numbers, any of
# the JSON-array / prose / TCL separators). W = urx-llx, H = ury-lly.
_DIE_AREA_RECT_RE = re.compile(
    r"DIE_AREA\b[)\s:=|({}'\"`\[]{0,8}"
    r"(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)[\s,]+"
    r"(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)",
    re.IGNORECASE)
_DIE_WIDTH_RE = re.compile(
    r"DIE_WIDTH`?\s*[:=|]\s*\*{0,2}\s*(\d+(?:\.\d+)?)\s*(?:um|µm)?",
    re.IGNORECASE)
_DIE_HEIGHT_RE = re.compile(
    r"DIE_HEIGHT`?\s*[:=|]\s*\*{0,2}\s*(\d+(?:\.\d+)?)\s*(?:um|µm)?",
    re.IGNORECASE)
# A LABELLED `W x H <length-unit>` row — the form real design documents use:
#
#     | Die size | **2400 x 2400 um (5.76 mm2)** (1.4M cells + 20 macros; L1) |
#     | Core die (no seal ring) | 1300 x 1300 um |
#
# MEASURED (vibe-ic#376 instance 3): 194 of 194 tracked L19 documents carry
# `die_area_budget_um: null`, because every recogniser above needs a
# `DIE_AREA` / `DIE_WIDTH` keyword and none of these rows has one. The
# extractor therefore returned "no mandated floorplan", the emitter returned
# early, and `phase3_one_shot_runner`'s documented precedence
# (`... > L19-mandated die_area_budget_um > 'auto'`) never reached its middle
# rung on any design.
#
# TWO DISCRIMINATORS, both load-bearing and both measured:
#   * the LABEL must name a die — without it, `1024x768` and `16x16` match;
#   * the VALUE must carry a LENGTH unit — without it, an array shape matches.
# Over the published input documents the labelled form hits 16 occurrences
# across 2 ICs; dropping the label requirement takes it to 24. Those 8 extra
# are exactly what this must not read as a die.
_DIE_LABELLED_WXH_RE = re.compile(
    r"([^\n|]{0,40}\bdie\b[^\n|]{0,30})[|:\s]+[^\n|]{0,20}?"
    r"(\d{2,5}(?:\.\d+)?)\s*[x\u00d7]\s*(\d{2,5}(?:\.\d+)?)"
    r"\s*(?:um|\u00b5m|micron)",
    re.IGNORECASE)

_FP_SIZING_PROSE_RE = re.compile(
    r"FP_SIZING\b[\s:=|`'\")(]{0,6}(absolute|relative)", re.IGNORECASE)

# Text-file suffixes worth scanning for prose / TCL floorplan facts.
_TEXT_SUFFIXES = {"", ".md", ".txt", ".rst", ".json", ".tcl", ".cfg",
                  ".yaml", ".yml", ".sdc"}
_SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".pdf", ".gds", ".zip", ".gz",
                  ".def", ".lef", ".v", ".sv", ".vh", ".lib", ".spef"}
_MAX_FILES = 400
_MAX_BYTES_PER_FILE = 400_000

# §4.05 (TIGHT / no-oracle-read): a fixed-floorplan contract is a DESIGN
# statement (design_src config + spec docs). NEVER derive it from a golden /
# oracle / expected-solution tree — those are off-limits end to end, and their
# vocabulary is defined ONCE in `_reference_flow_boundary` so no two programs
# can disagree about what "oracle" means.
#
# The reference-flow segments below are an ADDITIONAL, DELIBERATELY STRICTER
# rule that belongs to THIS program only, and it is not a claim that the whole
# tree is oracle — measured over the tracked corpus a reference flow is MIXED
# (recipe config + one QoR-rules oracle artifact; see the module docstring of
# `_reference_flow_boundary`). This program stays stricter than that boundary
# because a floorplan contract has an independent source in `design_src`, so
# skipping the tree wholesale costs it nothing and keeps the read trivially
# provable. A program that genuinely needs the recipe (phase-3 knob ingest)
# sits exactly on the boundary instead.
#
# Any input file whose relative path carries one of these directory segments is
# skipped. chip-AGNOSTIC (pure directory-name vocabulary).
_OFF_LIMITS_SEGMENTS = set(_rfb.ORACLE_TREE_SEGMENTS) | {
    "reference_flow", "ref_flow", "reference",
}


def _rel(project: Path, p: Path) -> str:
    try:
        return str(p.relative_to(project))
    except ValueError:
        return p.name


def _rect_to_wxh(llx: float, lly: float, urx: float, ury: float
                 ) -> Optional[str]:
    w, h = urx - llx, ury - lly
    if w > 0 and h > 0:
        return f"{int(round(w))}x{int(round(h))}"
    return None


def _strip_dir_macro(val: str) -> str:
    """Drop OpenLane path macros (``dir::`` / ``refg::``) so the stored hint
    is the design-relative path the design author wrote."""
    return re.sub(r"^\s*(?:dir|refg|ref)::", "", str(val)).strip()


def _ci_get(d: Dict[str, Any], key: str) -> Any:
    """Case-insensitive dict lookup (OpenLane keys are UPPER but a design may
    lower-case them). Returns None if absent."""
    if key in d:
        return d[key]
    lk = key.lower()
    for k, v in d.items():
        if isinstance(k, str) and k.lower() == lk:
            return v
    return None


def _die_area_from_value(v: Any) -> Optional[str]:
    """A config ``DIE_AREA`` value is either a JSON list of 4 numbers or a
    string of 4 whitespace/comma-separated numbers. Returns 'WxH' or None."""
    nums: List[float] = []
    if isinstance(v, (list, tuple)):
        for x in v:
            try:
                nums.append(float(x))
            except (TypeError, ValueError):
                return None
    elif isinstance(v, str):
        for tok in re.split(r"[\s,]+", v.strip()):
            if not tok:
                continue
            try:
                nums.append(float(tok))
            except ValueError:
                return None
    else:
        return None
    if len(nums) != 4:
        return None
    return _rect_to_wxh(nums[0], nums[1], nums[2], nums[3])


def _iter_input_files(project: Path) -> List[Tuple[str, Path, str]]:
    """Yield (rel_path, abs_path, text) for scannable design-input files under
    the canonical input roots. Capped (large-doc doctrine)."""
    out: List[Tuple[str, Path, str]] = []
    seen = set()
    roots = [
        project / "input",
        project / "phase1" / "input_doc",
        project / "input_doc",
    ]
    n = 0
    for base in roots:
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if n >= _MAX_FILES:
                break
            if not f.is_file():
                continue
            # §4.05 — skip any golden / oracle / reference-flow / solution tree.
            if _OFF_LIMITS_SEGMENTS.intersection(
                    part.lower() for part in f.parts):
                continue
            suf = f.suffix.lower()
            if suf in _SKIP_SUFFIXES:
                continue
            if suf not in _TEXT_SUFFIXES:
                # Unknown suffix: allow config/loc/cfg-ish names only.
                if f.name.lower() not in (
                        "config", "config.json", "config.tcl") \
                        and not f.name.lower().endswith(".loc"):
                    continue
            try:
                rp = f.resolve()
            except OSError:
                rp = f
            if rp in seen:
                continue
            seen.add(rp)
            try:
                text = f.read_text(errors="replace")[:_MAX_BYTES_PER_FILE]
            except OSError:
                continue
            out.append((_rel(project, f), f, text))
            n += 1
    return out


def _parse_openlane_config(rel: str, text: str) -> Optional[Dict[str, Any]]:
    """Return the design-mandated floorplan facts from ONE OpenLane-style
    config file (JSON or classic TCL), or None if it declares nothing.

    Keys returned (any subset): design_name, die_wxh, fp_sizing,
    def_template, pin_order_cfg, source(rel)."""
    facts: Dict[str, Any] = {"source": rel}
    parsed_json = False
    if text.lstrip().startswith("{"):
        try:
            cfg = json.loads(text)
            parsed_json = True
        except (json.JSONDecodeError, ValueError):
            cfg = None
        if isinstance(cfg, dict):
            dn = _ci_get(cfg, "DESIGN_NAME")
            if isinstance(dn, str) and dn.strip():
                facts["design_name"] = dn.strip()
            da = _ci_get(cfg, "DIE_AREA")
            wxh = _die_area_from_value(da) if da is not None else None
            if wxh:
                facts["die_wxh"] = wxh
            fps = _ci_get(cfg, "FP_SIZING")
            if isinstance(fps, str) and fps.strip():
                facts["fp_sizing"] = fps.strip().lower()
            dft = _ci_get(cfg, "FP_DEF_TEMPLATE")
            if isinstance(dft, str) and dft.strip():
                facts["def_template"] = _strip_dir_macro(dft)
            poc = _ci_get(cfg, "FP_PIN_ORDER_CFG")
            if isinstance(poc, str) and poc.strip():
                facts["pin_order_cfg"] = _strip_dir_macro(poc)
    if not parsed_json:
        # Classic OpenLane config.tcl: `set ::env(DIE_AREA) "0 0 W H"`, etc.
        m = _DIE_AREA_RECT_RE.search(text)
        if m:
            wxh = _rect_to_wxh(*(float(m.group(i)) for i in (1, 2, 3, 4)))
            if wxh:
                facts["die_wxh"] = wxh
        mfp = _FP_SIZING_PROSE_RE.search(text)
        if mfp:
            facts["fp_sizing"] = mfp.group(1).lower()
        mdn = re.search(
            r"DESIGN_NAME\)?\s*[\"'{]?\s*([A-Za-z_]\w*)", text)
        if mdn:
            facts["design_name"] = mdn.group(1)
        mdt = re.search(
            r"FP_DEF_TEMPLATE\)?\s*[\"'{]?\s*([^\s\"'}]+)", text)
        if mdt:
            facts["def_template"] = _strip_dir_macro(mdt.group(1))
        mpo = re.search(
            r"FP_PIN_ORDER_CFG\)?\s*[\"'{]?\s*([^\s\"'}]+)", text)
        if mpo:
            facts["pin_order_cfg"] = _strip_dir_macro(mpo.group(1))
    # Only meaningful if it carried at least one floorplan fact.
    if any(k in facts for k in
           ("die_wxh", "fp_sizing", "def_template", "pin_order_cfg")):
        return facts
    return None


def _looks_like_openlane_config(name: str, text: str) -> bool:
    if name.lower() in ("config.json", "config.tcl"):
        return True
    head = text[:4000]
    return ("FP_SIZING" in head or "DIE_AREA" in head) and (
        "DESIGN_NAME" in head or "VERILOG_FILES" in head
        or "::env(" in head)


def _prose_die_area(project: Path,
                    files: List[Tuple[str, Path, str]]
                    ) -> Optional[Tuple[str, str]]:
    """The authoritative design-doc statement of the mandated die. Reads the
    L9/constraint/floorplan prose docs first, then any input doc. Returns
    (die_wxh, source_rel) or None."""
    def _scan(text: str) -> Optional[str]:
        for m in _DIE_AREA_RECT_RE.finditer(text):
            wxh = _rect_to_wxh(*(float(m.group(i)) for i in (1, 2, 3, 4)))
            if wxh:
                return wxh
        mw, mh = _DIE_WIDTH_RE.search(text), _DIE_HEIGHT_RE.search(text)
        if mw and mh:
            return _rect_to_wxh(0.0, 0.0, float(mw.group(1)),
                                float(mh.group(1)))
        m = _DIE_LABELLED_WXH_RE.search(text)
        if m:
            return _rect_to_wxh(0.0, 0.0, float(m.group(2)), float(m.group(3)))
        return None

    prose = [(r, t) for (r, p, t) in files
             if p.suffix.lower() in ("", ".md", ".txt", ".rst")]
    # Prefer L9/constraint/floorplan-named prose docs.
    def _is_l9(rel: str) -> bool:
        base = rel.rsplit("/", 1)[-1].lower()
        return (base.startswith("l9") or "constraint" in base
                or "floorplan" in base)
    for r, t in sorted(prose, key=lambda rt: (not _is_l9(rt[0]), rt[0])):
        wxh = _scan(t)
        if wxh:
            return wxh, r
    return None


def extract_floorplan_contract(project: Path,
                               top_module: Optional[str] = None
                               ) -> Dict[str, Any]:
    """Extract a design-PROVIDED mandated fixed-floorplan contract.

    Returns a dict:
      {
        "constraints_present": bool,   # any mandated value found
        "die_area_budget_um": "WxH"|None,
        "die_area_source": <rel>|None,
        "floorplan_hints": [ {kind, value, source, ...}, ... ],
      }

    die_area_budget_um precedence (all design-input, §4.05):
      1. authoritative prose DIE_AREA (L9/constraint/floorplan docs);
      2. the OpenLane config whose DESIGN_NAME == top_module (if given);
      3. the SINGLE absolute-sizing config (unambiguous);
      4. else None (ambiguous → safe null; hints still captured).
    chip-AGNOSTIC — every value derives from the input at runtime."""
    result: Dict[str, Any] = {
        "constraints_present": False,
        "die_area_budget_um": None,
        "die_area_source": None,
        "floorplan_hints": [],
    }
    if not isinstance(project, Path):
        project = Path(project)
    files = _iter_input_files(project)
    if not files:
        return result

    hints: List[Dict[str, Any]] = []

    # --- OpenLane config.json / config.tcl floorplan facts ---
    configs: List[Dict[str, Any]] = []
    for rel, path, text in files:
        if not _looks_like_openlane_config(path.name, text):
            continue
        facts = _parse_openlane_config(rel, text)
        if facts:
            configs.append(facts)

    for facts in configs:
        dn = facts.get("design_name")
        src = facts["source"]
        if facts.get("die_wxh"):
            hints.append({
                "kind": "die_area", "value": facts["die_wxh"],
                "source": src,
                **({"design_name": dn} if dn else {}),
            })
        if facts.get("fp_sizing"):
            hints.append({
                "kind": "fp_sizing", "value": facts["fp_sizing"],
                "source": src,
                **({"design_name": dn} if dn else {}),
            })
        if facts.get("def_template"):
            hints.append({
                "kind": "def_template", "value": facts["def_template"],
                "source": src,
                **({"design_name": dn} if dn else {}),
            })
        if facts.get("pin_order_cfg"):
            hints.append({
                "kind": "pin_order", "value": facts["pin_order_cfg"],
                "source": src,
                **({"design_name": dn} if dn else {}),
            })

    # --- discovered fixed-floorplan aux files (pin order + power sources) ---
    have_pin_hint = any(h["kind"] == "pin_order" for h in hints)
    for rel, path, _text in files:
        nm = path.name.lower()
        if nm.endswith(".loc") and "vsrc" in rel.lower().replace("\\", "/"):
            hints.append({
                "kind": "power_source_location", "value": rel, "source": rel})
        elif (not have_pin_hint and nm.endswith(".cfg")
              and "pin_order" in nm):
            hints.append({
                "kind": "pin_order", "value": rel, "source": rel})

    # --- prose DIE_AREA + FP_SIZING (authoritative design statement) ---
    prose = _prose_die_area(project, files)
    prose_fp_sizing = None
    for rel, path, text in files:
        if path.suffix.lower() not in ("", ".md", ".txt", ".rst"):
            continue
        m = _FP_SIZING_PROSE_RE.search(text)
        if m:
            prose_fp_sizing = (m.group(1).lower(), rel)
            break
    if prose_fp_sizing and not any(
            h["kind"] == "fp_sizing" for h in hints):
        hints.append({"kind": "fp_sizing", "value": prose_fp_sizing[0],
                      "source": prose_fp_sizing[1]})

    # --- resolve the mandated die (precedence above) ---
    die_wxh: Optional[str] = None
    die_src: Optional[str] = None
    if prose:
        die_wxh, die_src = prose
    if die_wxh is None and top_module:
        for facts in configs:
            if (facts.get("die_wxh")
                    and facts.get("design_name") == top_module):
                die_wxh, die_src = facts["die_wxh"], facts["source"]
                break
    if die_wxh is None:
        abs_cfgs = [f for f in configs
                    if f.get("die_wxh")
                    and (f.get("fp_sizing") == "absolute"
                         or f.get("fp_sizing") is None)]
        # Unique die → unambiguous; use it.
        uniq = {f["die_wxh"] for f in abs_cfgs}
        if len(uniq) == 1 and abs_cfgs:
            f0 = abs_cfgs[0]
            die_wxh, die_src = f0["die_wxh"], f0["source"]
        elif len(uniq) > 1:
            # Multiple candidate dies: pick the config whose DESIGN_NAME is
            # STRICTLY most-referenced across the design's prose/input docs
            # (the top-level integration design is named more than its
            # sub-macros). No strict winner → stay null (safe / ambiguous).
            corpus = "\n".join(t for (_r, _p, t) in files)
            ranked = []
            for f in abs_cfgs:
                dn = f.get("design_name")
                if not dn:
                    continue
                cnt = len(re.findall(
                    r"\b" + re.escape(dn) + r"\b", corpus))
                ranked.append((cnt, f))
            ranked.sort(key=lambda cf: cf[0], reverse=True)
            if len(ranked) >= 2 and ranked[0][0] > ranked[1][0]:
                die_wxh, die_src = (ranked[0][1]["die_wxh"],
                                    ranked[0][1]["source"])

    result["die_area_budget_um"] = die_wxh
    result["die_area_source"] = die_src
    # Dedup hints (kind+value+source) preserving order.
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for h in hints:
        key = (h["kind"], h["value"], h.get("source"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(h)
    result["floorplan_hints"] = deduped
    result["constraints_present"] = bool(die_wxh or deduped)
    return result
