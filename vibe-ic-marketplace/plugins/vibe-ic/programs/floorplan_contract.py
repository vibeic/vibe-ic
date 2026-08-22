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

import fnmatch
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

# A prose die statement can be NEGATED, and until this guard the extractor could
# not tell. Measured on a real retarget: a design moving to a different process
# wrote, in its own L9 constraints document,
#
#     "The origin project's fixed die rectangle of <W> x <H> um is the die of an
#      external harness on a different process. It has NO meaning here and is
#      REMOVED, not translated."
#
# `_DIE_LABELLED_WXH_RE` matched "die ... <W> x <H> um" inside that statement and
# the extractor published <W>x<H> as `L19.fields.die_area_budget_um` — i.e. as
# that design's MANDATED fixed die, which `phase3_one_shot_runner` then treats as
# an absolute floorplan. The document said the opposite of what was recorded, and
# nothing in the flow could notice: a run would have been hard-sized onto a die
# belonging to a different chip on a different process. The design had no way to
# say "this die does not apply" — every phrasing of the denial re-declared it.
#
# THE SAME DEFECT WAS ALREADY FIXED ONCE, ELSEWHERE. `pdk_target` extraction
# carries `_FOUNDRY_NEGATION_RE` + `_foundry_match_trustworthy` for exactly this
# ("prose like 'fabbed at <foundry> but NOT as a process target' mis-extracts").
# That hardening was never extended to the floorplan contract, so the identical
# polarity blindness survived in the neighbouring field of the same document.
#
# WHY NOT A PLAIN NEGATION SEARCH — two ways that goes wrong, both handled:
#
#   * Real die statements carry harmless negations as PARENTHETICAL qualifiers:
#     "1300 x 1300 um (no seal ring)", "2200 x 1600 um (not including scribe)".
#     Vetoing those would turn a silent wrong value into a silent missing value,
#     which is no better. So bracketed spans that do NOT contain the matched
#     dimensions are blanked before looking for a negation.
#
#   * The denial usually does not live in the same SENTENCE as the number — it
#     follows it ("... is the die of an external harness. It has NO meaning
#     here."). Sentence scope therefore misses the common case. But paragraph
#     scope would over-trigger on a markdown TABLE, where an unrelated row
#     ("| Status | not final |") sits in the same block as a real die row. So
#     the scope is the LINE for a table row and the PARAGRAPH for prose.
#
# Chip-, PDK- and vendor-AGNOSTIC: the vocabulary is structural negation only.
# vibe-ic#712 — shared with `phase1_doc_one_shot_runner`; see `_prose_polarity`.
# This field needs BOTH tiers: a die can be denied ("no fixed die") or RETIRED
# while still printed in full ("removed, not translated"), which is the case
# #711 measured.
from _prose_polarity import NEGATION_RE as _DIE_NEGATION_RE  # noqa: E402
_BRACKETED_RE = re.compile(r"\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}")


def _die_statement_scope(text: str, start: int, end: int) -> Tuple[int, int]:
    """The span of text whose polarity governs the die figure at [start, end).

    A markdown TABLE ROW is a self-contained record, so its scope is its own
    line — otherwise an unrelated cell in a neighbouring row would veto a valid
    die. Prose is scoped to its PARAGRAPH, because a denial is normally written
    as the sentence AFTER the one carrying the number.
    """
    line_lo = text.rfind("\n", 0, start) + 1
    line_hi = text.find("\n", end)
    line_hi = len(text) if line_hi < 0 else line_hi
    if "|" in text[line_lo:line_hi]:
        return line_lo, line_hi
    para_lo = text.rfind("\n\n", 0, start)
    para_lo = 0 if para_lo < 0 else para_lo + 2
    para_hi = text.find("\n\n", end)
    para_hi = len(text) if para_hi < 0 else para_hi
    return para_lo, para_hi


def _die_statement_negated(text: str, start: int, end: int) -> bool:
    """True when the die VALUE spanning [start, end) sits in a statement that
    denies it — so the document states what the design is NOT, and the figure
    must not be recorded as a mandate.

    `start`/`end` must bound the NUMERIC VALUE, not the whole regex match, so
    that a bracket sitting inside the match but beside the number (a label such
    as "Core die (no seal ring)") is still recognised as a qualifier.
    """
    lo, hi = _die_statement_scope(text, start, end)
    span = text[lo:hi]
    rel_s, rel_e = start - lo, end - lo

    def _blank(m):
        # Keep any bracket that CONTAINS the value (e.g. "DIE_AREA = [0,0,W,H]");
        # blank the ones that merely sit beside it.
        if m.start() <= rel_s and m.end() >= rel_e:
            return m.group(0)
        return " " * (m.end() - m.start())

    return bool(_DIE_NEGATION_RE.search(_BRACKETED_RE.sub(_blank, span)))


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
_OFF_LIMITS_SEGMENTS = set(_rfb.OFF_LIMITS_TREE_SEGMENTS)


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
        # Every recogniser below iterates ALL of its matches and skips the
        # negated ones, so a statement that denies a die ("... is REMOVED, not
        # translated") can neither be recorded as a mandate nor poison a genuine
        # affirmative statement later in the same document. Same doctrine as the
        # #457 pdk_target loop. The span handed to the guard is the NUMERIC
        # VALUE, not the whole match — see `_die_statement_negated`.
        for m in _DIE_AREA_RECT_RE.finditer(text):
            wxh = _rect_to_wxh(*(float(m.group(i)) for i in (1, 2, 3, 4)))
            if wxh and not _die_statement_negated(text, m.start(1), m.end(4)):
                return wxh
        mw, mh = _DIE_WIDTH_RE.search(text), _DIE_HEIGHT_RE.search(text)
        if (mw and mh
                and not _die_statement_negated(text, mw.start(1), mw.end(1))
                and not _die_statement_negated(text, mh.start(1), mh.end(1))):
            return _rect_to_wxh(0.0, 0.0, float(mw.group(1)),
                                float(mh.group(1)))
        for m in _DIE_LABELLED_WXH_RE.finditer(text):
            if _die_statement_negated(text, m.start(2), m.end(3)):
                continue
            return _rect_to_wxh(0.0, 0.0, float(m.group(2)),
                                float(m.group(3)))
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
        # POLARITY, THE SAME QUESTION THE DIE_AREA PATH ALREADY ASKS
        # (vibe-ic#712). This file guards its die figure with
        # `_die_statement_negated` and did not guard the sizing beside it, so
        #
        #     FP_SIZING absolute is no longer used for this block.
        #
        # was recorded as a mandated hint. Two readers of one document
        # disagreeing about a denial is #711 itself, and here they are in the
        # same function.
        #
        # `finditer`, not `search`: a denied statement must not END the search.
        # A document that retires one sizing and then states another would
        # otherwise yield nothing, which is the false refusal this trade keeps
        # producing in the other direction.
        for m in _FP_SIZING_PROSE_RE.finditer(text):
            if _die_statement_negated(text, m.start(1), m.end(1)):
                continue
            prose_fp_sizing = (m.group(1).lower(), rel)
            break
        if prose_fp_sizing:
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


# ---------------------------------------------------------------------------
# Fixed-pinout wrapper detection (DFT boundary-scan applicability)
# ---------------------------------------------------------------------------
# A design whose TOP-LEVEL PORT GEOMETRY is fixed by an external parent — an
# OpenLane ``FP_DEF_TEMPLATE`` copies the die outline AND every pin position out
# of a template DEF the parent (harness / management SoC) handed down — is a
# *fixed-pinout wrapper*: its ports connect to that parent BY NAME, not to chip
# pads. `fault chain` defaults to inserting a boundary-scan register wrapping
# every top-level port; on such a wrapper that register is BOTH wrong DFT (the
# pins are not pads, so there is nothing at the chip boundary to scan) AND a
# physical hazard — MEASURED on caravel_user_project × sky130A: the 606-cell
# boundary register routed across a fixed 2920×3520 µm die at the functional
# 25 ns clock produced an SS-corner setup violation of −0.73 ns (TNS −11.63) and
# a +707 % instance blow-up. `fault chain --skip-boundary` inserts the internal
# scan chain only, which is the correct DFT for this class. This predicate is
# the deterministic, chip-AGNOSTIC selector for it — no agent chooses the flag.
#
# THE SIGNAL is ``FP_DEF_TEMPLATE`` (a template DEF that fixes the pin
# placement), NOT a chip name. A standalone padframe chip defines its own pads
# via a padring; it does NOT take its outline/pins from a parent's template DEF.
# So the presence of a fixed pin-placement template for the top module is a
# specific, sound marker of "ports are not chip pads". ``FP_PIN_ORDER_CFG`` /
# ``pin_order*.cfg`` alone is weaker (any design may order its own pins) and is
# reported as CORROBORATION, never as the sole trigger.
def is_fixed_pinout_wrapper(project: Path,
                            top_module: Optional[str] = None
                            ) -> Tuple[bool, Dict[str, Any]]:
    """Is ``top_module`` (or the design, if unnamed) a fixed-pinout wrapper?

    Returns ``(is_fixed_pinout, evidence)``. ``is_fixed_pinout`` is True only
    when a fixed pin-placement DEF template (``FP_DEF_TEMPLATE``) governs the
    top — the load-bearing marker that the ports are a parent interface, not
    chip pads. ``evidence`` records exactly what was read, so the decision is
    auditable and never a bare boolean.

    chip-AGNOSTIC: derives entirely from the design's own staged input via
    ``extract_floorplan_contract`` — no chip / vendor / SKU literal.
    """
    if not isinstance(project, Path):
        project = Path(project)
    contract = extract_floorplan_contract(project, top_module)
    hints = contract.get("floorplan_hints") or []
    def_hints = [h for h in hints if h.get("kind") == "def_template"]
    # A def_template for THIS top (or one carrying no DESIGN_NAME, which the
    # extractor leaves unset when the config omitted it) governs the top's
    # pins. A def_template that names a DIFFERENT module is a sub-macro's
    # template and does not, on its own, make the top fixed-pinout.
    # AN UNNAMED TEMPLATE IS ONLY THE TOP'S WHEN THERE IS NOTHING ELSE IT COULD
    # BE (gatekeeper, landing #625). `design_name` is unset whenever the config
    # omitted `DESIGN_NAME`, and `extract_floorplan_contract` collects configs
    # from the whole input tree — so a SUB-MACRO config that declares
    # `FP_DEF_TEMPLATE` and omits `DESIGN_NAME` produced an unnamed hint that
    # matched any top. DRIVEN before this line was written:
    #
    #     sub_blk config, FP_DEF_TEMPLATE set, DESIGN_NAME omitted
    #     is_fixed_pinout_wrapper(project, "padframe_chip") -> True
    #
    # and True here means `--skip-boundary`, so a padframe chip whose ports ARE
    # pads would silently lose its boundary-scan register. That is the unsafe
    # direction: the opposite error is a loud timing violation, this one is a
    # silent DFT loss. The named negative control above cannot see it, because
    # its sub-macro names itself.
    #
    # So an unnamed template counts only when it is the ONLY one — then there
    # is no other design it could belong to. With several and one unnamed, which
    # governs the top is not established, and not established means the default
    # (keep the boundary register) rather than a guess.
    if top_module:
        named = [h for h in def_hints if h.get("design_name") == top_module]
        unnamed = [h for h in def_hints if h.get("design_name") is None]
        matched = named or (unnamed if len(def_hints) == 1 else [])
    else:
        matched = def_hints
    is_fixed = bool(matched)
    fp_sizing = next((h["value"] for h in hints
                      if h.get("kind") == "fp_sizing"), None)
    pin_order = [h for h in hints if h.get("kind") == "pin_order"]
    evidence: Dict[str, Any] = {
        "is_fixed_pinout": is_fixed,
        "top_module": top_module,
        "def_template": (matched[0]["value"] if matched else None),
        "def_template_source": (matched[0].get("source") if matched else None),
        "def_template_design_name": (
            matched[0].get("design_name") if matched else None),
        "fp_sizing": fp_sizing,
        "die_area_um": contract.get("die_area_budget_um"),
        "pin_order_cfg": (pin_order[0]["value"] if pin_order else None),
        # Every def_template seen, so a reader can tell a top template from a
        # sub-macro one without re-deriving.
        "all_def_templates": [
            {"value": h.get("value"), "source": h.get("source"),
             "design_name": h.get("design_name")}
            for h in def_hints],
        "reason": (
            "FP_DEF_TEMPLATE fixes the top's pin placement → ports are a "
            "parent interface, not chip pads → boundary-scan register is "
            "incorrect DFT here; insert the internal scan chain only "
            "(--skip-boundary)"
            if is_fixed else
            "no FP_DEF_TEMPLATE governs the top → not a fixed-pinout wrapper; "
            "default boundary-scan behaviour is unchanged"),
    }
    return is_fixed, evidence


# ---------------------------------------------------------------------------
# Design-declared DRV limits (max-fanout / max-transition)
# ---------------------------------------------------------------------------
# A fixed-floorplan design ships an OpenLane-style config, and this module
# already reads it for DIE_AREA / FP_SIZING / FP_DEF_TEMPLATE /
# FP_PIN_ORDER_CFG. The SAME file routinely also states the design's DRV
# limits — `MAX_FANOUT_CONSTRAINT`, `SYNTH_MAX_FANOUT`,
# `MAX_TRANSITION_CONSTRAINT` — and the phase-3 SDC builder looked for them
# ONLY in the L9 markdown, with a regex shaped for a markdown TABLE ROW. A
# design that declares its cap in JSON therefore read as "declares no cap",
# no `set_max_fanout` was emitted, `repair_design` never split the
# high-fanout nets, and the sign-off max-fanout table came back empty BY
# CONSTRUCTION — UNMEASURED, which is not the same claim as zero.
#
# PER-PDK / PER-SCL SCOPING IS LOAD-BEARING, not a nicety. An OpenLane
# config carries caps for PDKs and cell libraries a given run is NOT
# building for, under `pdk::<glob>` / `scl::<name>` blocks. Reading the cap
# WITHOUT the PDK is precisely how a foreign library's tighter cap gets
# applied to the wrong run. Resolution order, most specific last:
#     top-level keys
#       -> `pdk::<glob>` block whose glob matches the active PDK
#         -> `scl::<name>` block whose name matches the active cell library
# A block that matches neither contributes NOTHING.
#
# §4.05 / no-fabricate: only a real positive numeric declaration counts; a
# missing, zero or non-numeric value yields None so the caller keeps its own
# default. Off-limits (golden / oracle / reference-flow) trees are skipped by
# `_iter_input_files`, so a cap that only exists in one is never read.
#
# chip-AGNOSTIC: pure OpenLane config-key grammar. The PDK and cell-library
# names are supplied BY THE CALLER; no chip, PDK or design literal appears.

_DRV_FANOUT_KEYS = ("MAX_FANOUT_CONSTRAINT", "SYNTH_MAX_FANOUT")
_DRV_SLEW_KEYS = ("MAX_TRANSITION_CONSTRAINT",)
# The SAME config states the design's routing-layer envelope. OpenLane names
# them `RT_MAX_LAYER` / `RT_MIN_LAYER` (v1 spelled them `GLB_RT_MAXLAYER` /
# `GLB_RT_MINLAYER`, and `RT_CLOCK_MIN_LAYER` scopes the clock separately).
# They are DESIGN INPUT — a declared ceiling on where this design may route —
# and the phase-3 `global_route` was emitted bare, so the declaration reached
# no tool. Same per-(pdk, scl) scoping as the caps above: a routing ceiling
# stated under `pdk::sky130*` must not be applied to a gf180 run.
_DRV_ROUTE_MAX_LAYER_KEYS = ("RT_MAX_LAYER", "GLB_RT_MAXLAYER")
_DRV_ROUTE_MIN_LAYER_KEYS = ("RT_MIN_LAYER", "GLB_RT_MINLAYER")
_DRV_ROUTE_CLK_MIN_LAYER_KEYS = ("RT_CLOCK_MIN_LAYER", "GLB_RT_CLOCK_MINLAYER")


def _scope_matches(prefix: str, spec: str, actual: str) -> bool:
    """Does an OpenLane `<prefix>::<spec>` block apply to `actual`?

    `spec` is an fnmatch glob (`sky130*`), matched case-insensitively. An
    empty `actual` matches nothing — an unknown PDK must not inherit a
    scoped cap.
    """
    if not actual:
        return False
    del prefix  # the caller has already split on it; kept for call-site clarity
    return fnmatch.fnmatchcase(actual.lower(), spec.strip().lower())


def _collect_scoped(cfg: Dict[str, Any], pdk: str, scl: str
                    ) -> List[Dict[str, Any]]:
    """Config dicts that apply to (pdk, scl), least specific first."""
    layers: List[Dict[str, Any]] = [cfg]
    for key, val in cfg.items():
        if not isinstance(key, str) or not isinstance(val, dict):
            continue
        low = key.lower()
        if low.startswith("pdk::"):
            if _scope_matches("pdk", key[5:], pdk):
                layers.append(val)
                for k2, v2 in val.items():
                    if (isinstance(k2, str) and isinstance(v2, dict)
                            and k2.lower().startswith("scl::")
                            and _scope_matches("scl", k2[5:], scl)):
                        layers.append(v2)
        elif low.startswith("scl::"):
            if _scope_matches("scl", key[5:], scl):
                layers.append(val)
    return layers


def _positive_int(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v > 0 else None
    if isinstance(v, float) and float(v).is_integer():
        return int(v) if v > 0 else None
    if isinstance(v, str):
        try:
            n = int(v.strip())
        except (TypeError, ValueError):
            return None
        return n if n > 0 else None
    return None


def _positive_float(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if float(v) > 0 else None
    if isinstance(v, str):
        try:
            n = float(v.strip())
        except (TypeError, ValueError):
            return None
        return n if n > 0 else None
    return None


def _layer_name(v: Any) -> Optional[str]:
    """A LEF routing-layer NAME as declared in a flow config, or None.

    Accepts only a bare identifier (`met4`, `Metal4`, `M4`) — the shape a LEF
    `LAYER <name>` carries. A number, a list, an empty string or anything with
    whitespace/punctuation is refused, so a mis-typed key can never be spliced
    into a `set_routing_layers` argument.
    """
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", s):
        return None
    return s


def declared_drv_limits(project: Path, pdk: str = "", scl: str = ""
                        ) -> Dict[str, Any]:
    """The design's OWN DRV limits, read from its staged flow config(s).

    Returns ``{"max_fanout": int|None, "max_fanout_source": rel|None,
    "max_transition_ns": float|None, "max_transition_source": rel|None}``.

    Scoped per (``pdk``, ``scl``) — see the module note above. Never raises;
    a project that declares nothing yields all-None so the caller's own
    default stands unchanged.
    """
    out: Dict[str, Any] = {"max_fanout": None, "max_fanout_source": None,
                           "max_transition_ns": None,
                           "max_transition_source": None,
                           "route_max_layer": None,
                           "route_max_layer_source": None,
                           "route_min_layer": None,
                           "route_min_layer_source": None,
                           "route_clock_min_layer": None,
                           "route_clock_min_layer_source": None}
    if not project or not Path(project).is_dir():
        return out
    try:
        files = _iter_input_files(Path(project))
    except Exception:                                        # noqa: BLE001
        return out
    for rel, _abs, text in files:
        if not _looks_like_openlane_config(Path(rel).name, text):
            continue
        if not text.lstrip().startswith("{"):
            continue
        try:
            cfg = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(cfg, dict):
            continue
        for layer in _collect_scoped(cfg, pdk, scl):
            for key in _DRV_FANOUT_KEYS:
                n = _positive_int(_ci_get(layer, key))
                if n is not None:
                    out["max_fanout"] = n
                    out["max_fanout_source"] = f"{rel}:{key}"
            for key in _DRV_SLEW_KEYS:
                f = _positive_float(_ci_get(layer, key))
                if f is not None:
                    out["max_transition_ns"] = f
                    out["max_transition_source"] = f"{rel}:{key}"
            for field, keys in (("route_max_layer", _DRV_ROUTE_MAX_LAYER_KEYS),
                                ("route_min_layer", _DRV_ROUTE_MIN_LAYER_KEYS),
                                ("route_clock_min_layer",
                                 _DRV_ROUTE_CLK_MIN_LAYER_KEYS)):
                for key in keys:
                    name = _layer_name(_ci_get(layer, key))
                    if name is not None:
                        out[field] = name
                        out[f"{field}_source"] = f"{rel}:{key}"
    return out
