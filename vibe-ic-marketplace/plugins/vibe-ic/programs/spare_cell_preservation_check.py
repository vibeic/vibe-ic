#!/usr/bin/env python3
"""spare_cell_preservation_check.py — Design-for-ECO PRESERVATION gate.

THE user's key concern: spare/ECO cells/gates/pads look exactly like
dead logic and WILL be stripped by any optimizer (yosys opt_clean,
post-DFT resynth, OpenROAD remove_buffers/repair_design/opt, metal
fill) unless they are protected. This checker proves they SURVIVED.

It takes the spare-cell set recorded at insertion time
(`phase3/stage3/pnr/spare_cells.json`) and compares it against the
FINAL artefacts — the post-PnR netlist, the routed / filled DEF, and
the GDS — asserting that EVERY spare instance (by name) is still
present, and that its dont_touch / keep tag is intact wherever the
artefact format carries one.

  FAIL if any spare/ECO cell/gate/pad:
    * was removed (name absent from every final artefact searched), or
    * lost its keep attribute (present in a netlist but no `keep`/
      `dont_touch` marker on it when at least one final artefact records
      such markers).

Emits reports/spare_preservation.json:
  {inserted, survived, removed:[...], untagged:[...],
   all_keep_attr_intact:bool, verdict}

Exit 0 PASS / 1 FAIL / 2 IO-arg error. chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import _path_layout as _pl  # type: ignore
except Exception:  # pragma: no cover
    _pl = None


def _load_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _spare_names_and_types(plan: dict) -> List[Tuple[str, str]]:
    """Return [(name, type), ...] for every inserted spare instance +
    spare pad. Pure."""
    out: List[Tuple[str, str]] = []
    for inst in plan.get("instances", []) or []:
        if isinstance(inst, dict) and inst.get("name"):
            out.append((str(inst["name"]), str(inst.get("type", ""))))
    for pad in plan.get("spare_pads", []) or []:
        if isinstance(pad, dict) and pad.get("name"):
            out.append((str(pad["name"]), "pad"))
    return out


# ──────────────────────────────────────────────────────────────────
# Token classes shared by the linear (single-pass) collectors below.
# A name "is present" iff it appears as a maximal [A-Za-z0-9_]+ run,
# which is EXACTLY the word-boundary-anchored test the old per-name
# regex did — so set membership over the token set is verdict-identical.
# ──────────────────────────────────────────────────────────────────
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_DONT_TOUCH_RE = re.compile(r"\bdont_touch\b")
_SET_DONT_TOUCH_RE = re.compile(r"set_dont_touch\b")
_KEEP_RE = re.compile(r"\bkeep\b")
_KEEP_ATTR_RE = re.compile(r"\(\*[^\n]*\bkeep\b[^\n]*\*\)")
_FIXED_RE = re.compile(r"\+\s*FIXED\b")
_COVER_RE = re.compile(r"\+\s*COVER\b")


def name_present_in_text(name: str, text: str) -> bool:
    """Word-boundary-anchored presence test for an instance name in a
    netlist / DEF / GDS-ascii blob. Pure, chip-AGNOSTIC.

    Retained for backward compatibility / standalone callers. NOTE: the
    hot path (evaluate_preservation) NO LONGER calls this per-spare —
    it builds ONE token set per artefact and tests membership, which is
    O(text + N_spares) instead of O(N_spares * text). Set membership is
    verdict-identical to this regex (a name matches the word-boundary
    pattern iff it is a maximal [A-Za-z0-9_]+ token)."""
    if not name or not text:
        return False
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(name)
                     + r"(?![A-Za-z0-9_])", text) is not None


def _keep_tagged_tokens_in_line(line: str) -> Set[str]:
    """Single-pass classifier: return the set of [A-Za-z0-9_]+ tokens on
    `line` that the original 7 keep/dont_touch patterns would associate
    with a keep marker. Direction-aware, equivalent to the per-name
    regexes (all of which were line-scoped via `[^\n]*`). Pure."""
    if ("dont_touch" not in line and "keep" not in line
            and "FIXED" not in line and "COVER" not in line):
        return set()
    toks = [(m.group(0), m.start(), m.end())
            for m in _TOKEN_RE.finditer(line)]
    if not toks:
        return set()
    tagged: Set[str] = set()

    def add_after(pos: int) -> None:
        for tk, ts, _te in toks:
            if ts >= pos:
                tagged.add(tk)

    def add_before(pos: int) -> None:
        for tk, _ts, te in toks:
            if te <= pos:
                tagged.add(tk)

    # pat 1: set_dont_touch ... NAME  (tokens after the directive)
    for m in _SET_DONT_TOUCH_RE.finditer(line):
        add_after(m.end())
    # pat 2: dont_touch ... NAME  (tokens after the word-bounded marker)
    # pat 3: NAME ... dont_touch  (tokens before it)
    for m in _DONT_TOUCH_RE.finditer(line):
        add_after(m.end())
        add_before(m.start())
    # pat 4: (* ... keep ... *) ... NAME  (tokens after the closing *) )
    for m in _KEEP_ATTR_RE.finditer(line):
        add_after(m.end())
    # pat 5: NAME ... keep  (tokens before the word-bounded keep)
    for m in _KEEP_RE.finditer(line):
        add_before(m.start())
    # pat 6: NAME ... + FIXED  (tokens before the placement status)
    for m in _FIXED_RE.finditer(line):
        add_before(m.start())
    # pat 7: NAME ... + COVER
    for m in _COVER_RE.finditer(line):
        add_before(m.start())
    return tagged


def _collect_present_and_tagged(
        final_texts: Dict[str, str]) -> Tuple[Set[str], Set[str], bool]:
    """ONE linear pass over each artefact. Returns
    (present_tokens, keep_tagged_tokens, any_keep_capable):
      * present_tokens  — every [A-Za-z0-9_]+ run seen anywhere (survival)
      * keep_tagged_tokens — tokens the 7 keep/dont_touch forms protect
      * any_keep_capable — does ANY artefact carry a keep marker at all
    Cost is O(total_text), NOT O(N_spares * total_text). Pure,
    chip-AGNOSTIC."""
    present: Set[str] = set()
    tagged: Set[str] = set()
    any_keep_capable = False
    for text in final_texts.values():
        if not text:
            continue
        # whole-artefact "keep-capable" probe (substring, matches old
        # any() that used plain `in`).
        if (not any_keep_capable
                and ("dont_touch" in text or "keep" in text
                     or "FIXED" in text or "COVER" in text)):
            any_keep_capable = True
        for line in text.splitlines():
            for m in _TOKEN_RE.finditer(line):
                present.add(m.group(0))
            tagged |= _keep_tagged_tokens_in_line(line)
    return present, tagged, any_keep_capable


def keep_attr_present_for(name: str, texts: Dict[str, str]) -> bool:
    """Return True iff at least one artefact records a keep / dont_touch
    marker associated with `name`. We accept several canonical forms:
      * a `set_dont_touch <name>` / `dont_touch ... <name>` directive,
      * a `(* keep *)` attribute on the same line as the instance,
      * a DEF `+ FIXED` placement status on the instance (a fixed spare
        is functionally protected from legalization), or
      * a `keep` / `dont_touch` token on the same line as the name.
    Pure, chip-AGNOSTIC.

    Retained for backward compatibility. The hot path uses the
    single-pass `_collect_present_and_tagged` collector instead (this
    function is verdict-identical but per-name)."""
    _present, tagged, _cap = _collect_present_and_tagged(texts)
    return name in tagged


def evaluate_preservation(plan: dict,
                          final_texts: Dict[str, str]) -> dict:
    """Pure evaluator. `plan` is spare_cells.json; `final_texts` maps an
    artefact label (e.g. 'netlist', 'def', 'gds') to its text content.

    For each spare: it SURVIVES iff its name is present in at least one
    final artefact. Its keep attr is INTACT iff a keep/dont_touch marker
    is found in some artefact (only required when at least one artefact
    carries any keep/dont_touch markers at all — a pure GDS-only set,
    which has no such concept, does not fail on the tag check).

    Returns {inserted, survived, removed[], untagged[],
    all_keep_attr_intact, verdict, artefacts}. chip-AGNOSTIC."""
    spares = _spare_names_and_types(plan)
    inserted = len(spares)
    removed: List[Dict[str, str]] = []
    untagged: List[Dict[str, str]] = []
    survived_names: Set[str] = set()

    # ── LINEAR PASS ────────────────────────────────────────────────
    # ONE scan per artefact builds (a) the set of every instance-name
    # token present and (b) the set of keep/dont_touch-protected tokens.
    # Per-spare verdicts then become O(1) set membership. This replaces
    # the old O(N_spares * artefact_size) regex-per-spare loops that blew
    # the program-budget on CPU/SoC-class designs (#471). Set membership
    # is verdict-identical to the previous word-boundary regex.
    present_tokens, tagged_tokens, any_keep_capable = \
        _collect_present_and_tagged(final_texts)

    for name, typ in spares:
        if name not in present_tokens:
            removed.append({"name": name, "type": typ})
            continue
        survived_names.add(name)
        if any_keep_capable and name not in tagged_tokens:
            untagged.append({"name": name, "type": typ})

    survived = len(survived_names)
    all_keep_attr_intact = (len(untagged) == 0)
    # PASS iff nothing removed AND (no tag-capable artefact OR all tagged)
    # AND there was actually something to preserve.
    verdict = "PASS" if (inserted > 0
                         and not removed
                         and all_keep_attr_intact) else "FAIL"
    return {
        "inserted": inserted,
        "survived": survived,
        "removed": removed,
        "untagged": untagged,
        "all_keep_attr_intact": all_keep_attr_intact,
        "keep_check_applied": any_keep_capable,
        "verdict": verdict,
        # v0.1.25+1: renamed `artefacts` (label list: ["def","gds",...]) to
        # `artefact_labels` so provenance_hash_audit does not misinterpret
        # these as project-root file paths. chip-AGNOSTIC.
        "artefact_labels": sorted(final_texts.keys()),
    }


# ── #686 robustness: never slurp a multi-GB binary artefact as text ──
# The survival scan only needs to find instance-NAME tokens, which only
# exist in the text artefacts (netlist / DEF). A streamed binary GDS
# never name-matches (it carries layout records, not ASCII identifiers),
# so loading it as text is pure dead work whose cost is O(GDS-bytes) in
# BOTH time and memory — a 2 GB streamout becomes a ~10 GB Python str +
# a 100M-element splitlines() that hangs flow_compliance_check for an
# hour. We therefore (1) binary-sniff the head and SKIP any artefact that
# is binary, and (2) hard-cap the bytes read for any (text) artefact so a
# pathologically large text file can never blow the time/RAM budget. The
# DEF + netlist already establish survival, so a skipped/capped GDS does
# not weaken a real violation verdict (a spare REMOVED from the netlist
# is still caught; the negative case stays detected). chip-AGNOSTIC.
_BINARY_SNIFF_BYTES = 8192
# Generous enough that any normal text netlist/DEF is read in full
# (the largest known-good flat DEFs are tens of MB); only a pathological
# multi-hundred-MB text artefact is head-capped. The binary GDS is
# skipped before this cap ever applies.
MAX_SCAN_BYTES = 256 * 1024 * 1024  # 256 MiB


def _looks_binary(head: bytes) -> bool:
    """A NUL byte in the head is the canonical binary marker (GDSII, OASIS,
    any packed-record format). ASCII netlists / DEF / TCL never contain
    NUL. Pure, chip-AGNOSTIC."""
    return b"\x00" in head


def _read_text(path: Path) -> str:
    """Bounded, binary-safe text read for the name-survival scan.
    Returns '' for a binary artefact (e.g. a streamed binary GDS) and a
    head-capped string for any text artefact larger than MAX_SCAN_BYTES.
    Never materializes a multi-GB file into a Python str. chip-AGNOSTIC."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(_BINARY_SNIFF_BYTES)
            if _looks_binary(head):
                return ""  # binary artefact — names never appear; skip.
            rest = b""
            if len(head) == _BINARY_SNIFF_BYTES:
                rest = fh.read(MAX_SCAN_BYTES - _BINARY_SNIFF_BYTES)
        raw = head + rest
    except Exception:
        return ""
    try:
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _collect_final_artefacts(project: Path) -> Dict[str, Path]:
    """Locate the final netlist / DEF / GDS to search. Prefers the
    most-final variant of each (filled.def > routed.def; <top>.gds in
    the canonical GDS dir; post-PnR netlist <top>_pnr.v). chip-AGNOSTIC.
    Returns label -> Path for files that exist."""
    if _pl is not None:
        pnr = _pl.pnr_dir(project)
        gds_dir = _pl.gds_dir(project)
    else:  # pragma: no cover
        pnr = project / "phase3/stage3/pnr"
        gds_dir = project / "phase3/stage4/gds"
    out: Dict[str, Path] = {}

    # Final netlist: post-PnR write_verilog, else canonicalized synth.
    for cand in sorted(pnr.glob("*_pnr.v")) if pnr.is_dir() else []:
        out["netlist"] = cand
        break

    # Final DEF: filled.def (post metal fill) preferred, else routed.def,
    # else the top-level <top>.def.
    if pnr.is_dir():
        for fname in ("filled.def", "routed.def"):
            cand = pnr / fname
            if cand.is_file():
                out["def"] = cand
                break
        if "def" not in out:
            top_defs = [d for d in sorted(pnr.glob("*.def"))
                        if d.name not in ("floorplan.def", "placed.def",
                                          "post_cts.def", "post_hold.def")]
            if top_defs:
                out["def"] = top_defs[0]

    # GDS (ASCII text scan only catches ascii-gds / oasis-text; binary
    # GDS will not name-match but DEF/netlist cover survival).
    if gds_dir.is_dir():
        for cand in sorted(gds_dir.glob("*.gds")):
            out["gds"] = cand
            break

    return out


def audit(project: Path) -> dict:
    if _pl is not None:
        spare_json = _pl.pnr_dir(project) / "spare_cells.json"
    else:  # pragma: no cover
        spare_json = project / "phase3/stage3/pnr/spare_cells.json"
    base = {
        "program": "spare_cell_preservation_check",
        "version": "1.1.0",
        "project_dir": str(project),
    }
    if not spare_json.is_file():
        return {**base, "verdict": "FAIL", "inserted": 0,
                "reasons": [f"spare_cells.json not found at {spare_json}"]}
    plan = _load_json(spare_json)
    if plan is None:
        return {**base, "verdict": "FAIL", "inserted": 0,
                "reasons": [f"spare_cells.json is not valid JSON: {spare_json}"]}

    artefact_paths = _collect_final_artefacts(project)
    if not artefact_paths:
        return {**base, "verdict": "FAIL", "inserted": len(
                    _spare_names_and_types(plan)),
                "reasons": ["no final netlist/DEF/GDS artefact found to "
                            "verify spare survival against"]}
    final_texts = {label: _read_text(p)
                   for label, p in artefact_paths.items()}
    result = evaluate_preservation(plan, final_texts)
    result.update(base)
    result["artefact_paths"] = {k: str(v)
                                for k, v in artefact_paths.items()}
    # v0.1.25+1: emit output_files[] so provenance_hash_audit can verify
    # the PASS verdict is backed by real artefacts on disk. chip-AGNOSTIC.
    try:
        result["output_files"] = [
            {"path": str(v.relative_to(project)) if v.is_relative_to(project) else str(v)}
            for v in artefact_paths.values()
        ]
    except Exception:
        result["output_files"] = [{"path": str(v)} for v in artefact_paths.values()]
    return result


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Design-for-ECO spare-cell preservation check")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    report = audit(project)

    # Canonical output: reports/spare_preservation.json (in addition to
    # any explicit --json path). Written to the literal flow-declared
    # path (NOT via the report auto-router, which would file an unknown
    # name under reports/audit/).
    canon = project / "reports" / "spare_preservation.json"
    out = json.dumps(report, indent=2, ensure_ascii=False)
    try:
        canon.parent.mkdir(parents=True, exist_ok=True)
        canon.write_text(out + "\n")
    except Exception:
        pass
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out + "\n")
    print(out)
    return 0 if report.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
