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

  FAIL (RECORD_ARTEFACT_MISMATCH) if the name-bearing final artefacts
  DISAGREE with each other about which recorded spares they contain. A
  spare survives, above, iff it is named in AT LEAST ONE artefact — so a
  single artefact that still names it certifies the whole set. The
  artefacts are resolved by NAME (`filled.def` > `routed.def` > `<top>.def`,
  `*_pnr.v`), with no check that they came from the same run: on a RESUMED
  project the previous run's `filled.def` is still on disk, and it will
  vouch for spares that this run's SHIPPED netlist no longer contains.
  Measured: shipped netlist and `routed.def` both missing `spare_inv_3`,
  a leftover `filled.def` naming all four -> PASS, survived 4/4. That is
  the defect — a preservation record certified against an artefact that
  does not describe the netlist being shipped — and disagreement between
  the artefacts is its direct, timestamp-free signature. See
  `_artefact_agreement`.

  NOT an mtime rule. A previous revision of this gate FAILed any artefact
  whose mtime predated `spare_cells.json`. The production runner emits
  `routed.def`, `<top>.def` and `<top>_pnr.v` from the OpenROAD tcl and
  only afterwards serialises `spare_cells.json` from Python in the SAME
  step, so on every correct single-pass run the shipped netlist is
  strictly older than the record: that rule false-FAILed every project the
  runner produces, and by returning early it stopped measuring
  preservation at all. Emission order is not provenance.

  WHERE THIS GATE BELONGS. Preservation is a property of the artefacts
  produced AFTER the optimisation passes that could strip a spare (CTS,
  hold fixing, routing, ECO, metal fill). It is therefore wired at step 34
  (metal fill), whose `blocks_on` closure contains all of them. It is NOT
  wired at step 18 (spare INSERTION): at step 18 none of those passes has
  run, so the only artefacts this gate could find are downstream ones —
  a dependency step 18 cannot declare (21 and 34 are its descendants, so
  the edge would be a cycle) and, on a resumed project, the previous run's.
  Step 18's own question — were enough spares inserted, distributed and
  tied off — is `spare_cell_coverage_check`'s, and that gate stays there.

Emits reports/spare_preservation.json:
  {inserted, survived, removed:[...], untagged:[...],
   all_keep_attr_intact:bool, verdict,
   artefact_read_status:{label: READ|BINARY_SKIPPED|TRUNCATED|EMPTY|
                                UNREADABLE},
   artefact_agreement:{status: COMPARED|SINGLE_WITNESS|NO_WITNESS,
                       witnesses:{label:{path,read,spares_named[]}},
                       excluded:{label:{path,read}},
                       disagreements:[...]}}

`artefact_agreement.status` is the disclosure that keeps this honest: with
fewer than two READ name-bearing artefacts the cross-check ran on nothing
and the report says SINGLE_WITNESS / NO_WITNESS rather than implying a
comparison that never happened.

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


# Read outcomes. Only READ artefacts may be used as cross-artefact
# witnesses below: a binary / truncated / unreadable artefact names ZERO
# spares for reasons that have nothing to do with preservation, and
# counting that zero would be reading an absence we never measured.
READ_OK = "READ"
READ_BINARY = "BINARY_SKIPPED"
READ_TRUNCATED = "TRUNCATED"
READ_EMPTY = "EMPTY"
READ_ERROR = "UNREADABLE"


def _read_text_with_status(path: Path) -> Tuple[str, str]:
    """Bounded, binary-safe text read plus WHY the text looks the way it
    does — one of READ / BINARY_SKIPPED / TRUNCATED / EMPTY / UNREADABLE.

    The status exists so a caller can tell "this artefact names none of the
    spares" apart from "this artefact was never actually read". Only the
    first is evidence. chip-AGNOSTIC."""
    try:
        size = path.stat().st_size
    except OSError:
        return "", READ_ERROR
    try:
        with open(path, "rb") as fh:
            head = fh.read(_BINARY_SNIFF_BYTES)
            if _looks_binary(head):
                # binary artefact — names never appear; skip.
                return "", READ_BINARY
            rest = b""
            if len(head) == _BINARY_SNIFF_BYTES:
                rest = fh.read(MAX_SCAN_BYTES - _BINARY_SNIFF_BYTES)
        raw = head + rest
    except Exception:
        return "", READ_ERROR
    try:
        text = raw.decode("utf-8", errors="ignore")
    except Exception:  # pragma: no cover - errors="ignore" cannot raise
        return "", READ_ERROR
    if size == 0:
        return text, READ_EMPTY
    if size > MAX_SCAN_BYTES:
        return text, READ_TRUNCATED
    return text, READ_OK


def _read_text(path: Path) -> str:
    """Bounded, binary-safe text read for the name-survival scan.
    Returns '' for a binary artefact (e.g. a streamed binary GDS) and a
    head-capped string for any text artefact larger than MAX_SCAN_BYTES.
    Never materializes a multi-GB file into a Python str. chip-AGNOSTIC."""
    return _read_text_with_status(path)[0]


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


# Labels whose format names EVERY placed instance by construction: a
# gate-level Verilog netlist instantiates each spare, and a DEF lists each
# in COMPONENTS. `gds` is deliberately excluded — a streamed binary GDS
# carries layout records, not ASCII identifiers, so "the GDS does not name
# this spare" is never evidence about the spare.
CROSS_CHECK_LABELS = ("netlist", "def")


def _spare_instance_names(plan: dict) -> List[str]:
    """Recorded spare INSTANCE names (placed cells only).

    Spare PADS are excluded from the cross-artefact comparison: a spare pad
    is an IO-ring RESERVATION, and whether a reservation shows up in a
    gate-level netlist, in a DEF, in both or in neither is a property of the
    emitter, not of preservation. Their survival is still evaluated by
    `evaluate_preservation` exactly as before. Pure, chip-AGNOSTIC."""
    out: List[str] = []
    for inst in plan.get("instances", []) or []:
        if isinstance(inst, dict) and inst.get("name"):
            out.append(str(inst["name"]))
    return out


def _rel_to(project: Path, path: Path) -> str:
    try:
        return str(path.relative_to(project))
    except ValueError:  # pragma: no cover - absolute fallback
        return str(path)


def _artefact_agreement(project: Path, plan: dict,
                        artefact_paths: Dict[str, Path],
                        artefact_texts: Dict[str, str],
                        read_status: Dict[str, str]) -> dict:
    """Do the name-bearing final artefacts describe the SAME netlist?

    THE DEFECT THIS MEASURES. `evaluate_preservation` calls a spare
    "survived" iff it is named in at least one artefact. That union is what
    lets a mixed-provenance artefact set produce a false clean: on a resumed
    project the previous run's `filled.def` is still on disk and still names
    every spare, so it vouches for spares the SHIPPED `<top>_pnr.v` and
    `routed.def` of this run no longer contain. Measured on the base gate:
    verdict PASS, survived 4/4, rc 0, with `spare_inv_3` absent from both
    shipped artefacts.

    Two artefacts that came from the same run cannot disagree about which
    recorded spares they contain. If they do, at least one of them does not
    describe the netlist being shipped, and the preservation record cannot be
    certified against the set. That is a CONTENT property — it needs no
    timestamp, no tool version and no PDK knowledge, and it is unaffected by
    the order in which the runner happens to write its files.

    A binary, empty or unreadable artefact names zero spares for reasons that
    are not preservation; counting that zero would turn an unmeasured absence
    into a defect. Such artefacts are listed under `excluded` so the report
    says what it did not measure.

    A TRUNCATED ARTEFACT IS A HALF-WITNESS, NOT A NON-WITNESS. Corrected
    2026-07-28: it used to be excluded outright, which restored the exact
    false clean this rule was built to catch. `audit` feeds every text it
    read — truncated ones included — to `evaluate_preservation`, where
    survival is a UNION over all texts, so a leftover `filled.def` above
    MAX_SCAN_BYTES still VOUCHED for a spare while being silently dropped
    from the check that would have caught the contradiction. MEASURED, same
    mixed-provenance tree, cap lowered in-process to model a >256 MiB fill
    DEF: rc 0, verdict PASS, survived 4/4, `disagreements []`,
    `status SINGLE_WITNESS`; at the production cap the identical tree gives
    rc 1 and names the separating spare.

    The asymmetry is what makes the repair sound. A truncated read is a
    PREFIX of the file, so a name FOUND in it is genuinely in the file — that
    fact is as good as any other. A name NOT found in it proves nothing,
    because the rest was never read. So a truncated artefact may appear on the
    PRESENT side of a disagreement and never on the ABSENT side, and it never
    upgrades `status` to COMPARED on its own. Its entry carries
    `partial: True` so the report never presents it as a full witness.

    Returns {status, recorded_spare_instances, witnesses, excluded,
    disagreements}. Pure, chip-AGNOSTIC."""
    recorded = _spare_instance_names(plan)
    witnesses: Dict[str, dict] = {}
    excluded: Dict[str, dict] = {}
    for label in CROSS_CHECK_LABELS:
        path = artefact_paths.get(label)
        if path is None:
            continue
        status = read_status.get(label, READ_ERROR)
        entry = {"path": _rel_to(project, path), "read": status}
        if status not in (READ_OK, READ_TRUNCATED):
            excluded[label] = entry
            continue
        tokens = set(_TOKEN_RE.findall(artefact_texts.get(label, "")))
        entry["spares_named"] = sorted(n for n in recorded if n in tokens)
        entry["partial"] = status != READ_OK
        witnesses[label] = entry

    disagreements: List[dict] = []
    labels = sorted(witnesses)
    for i, left in enumerate(labels):
        for right in labels[i + 1:]:
            s_left = set(witnesses[left]["spares_named"])
            s_right = set(witnesses[right]["spares_named"])
            # A partial read may only testify to PRESENCE; its silence is not
            # absence, so it is never named as `absent_from`.
            only_left = sorted(s_left - s_right)
            only_right = sorted(s_right - s_left)
            if only_left and not witnesses[right]["partial"]:
                disagreements.append({"present_in": left,
                                      "absent_from": right,
                                      "spares": only_left})
            if only_right and not witnesses[left]["partial"]:
                disagreements.append({"present_in": right,
                                      "absent_from": left,
                                      "spares": only_right})

    full = [lbl for lbl in witnesses if not witnesses[lbl]["partial"]]
    if len(full) >= 2:
        status = "COMPARED"
    elif len(witnesses) >= 2:
        # At least one side is a prefix read: presence claims were compared,
        # absence claims could not be. Say so rather than call it COMPARED.
        status = "COMPARED_PARTIAL"
    elif len(witnesses) == 1:
        status = "SINGLE_WITNESS"
    else:
        status = "NO_WITNESS"
    return {"status": status,
            "recorded_spare_instances": len(recorded),
            "witnesses": witnesses,
            "excluded": excluded,
            "disagreements": disagreements}


def _agreement_reasons(agreement: dict,
                       witnesses: Dict[str, dict]) -> List[str]:
    """One FAIL reason per disagreeing artefact pair, naming both files and
    the spares that separate them. Pure."""
    out: List[str] = []
    for dis in agreement["disagreements"]:
        present, absent = dis["present_in"], dis["absent_from"]
        out.append(
            f"RECORD_ARTEFACT_MISMATCH: {len(dis['spares'])} recorded "
            f"spare(s) are named in {present} "
            f"({witnesses[present]['path']}) but ABSENT from {absent} "
            f"({witnesses[absent]['path']}): "
            f"{', '.join(dis['spares'])}. Two artefacts of the same run "
            f"cannot disagree about which spares they contain, so at least "
            f"one of them does not describe the netlist being shipped — "
            f"most often a PREVIOUS run's DEF/netlist left in the project "
            f"tree, which would otherwise vouch for spares the shipped "
            f"netlist no longer has.")
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
    reads = {label: _read_text_with_status(p)
             for label, p in artefact_paths.items()}
    final_texts = {label: text for label, (text, _st) in reads.items()}
    read_status = {label: st for label, (_t, st) in reads.items()}

    # PRESERVATION IS ALWAYS MEASURED FIRST. The cross-artefact rule below
    # ADDS a failure mode; it must never short-circuit past
    # `evaluate_preservation`, or a project with a genuinely removed spare
    # would be reported only as an artefact-set problem and the removal —
    # the defect class this gate exists for — would never be named.
    result = evaluate_preservation(plan, final_texts)
    result.update(base)
    result["artefact_paths"] = {k: str(v)
                                for k, v in artefact_paths.items()}
    result["artefact_read_status"] = read_status

    agreement = _artefact_agreement(project, plan, artefact_paths,
                                    final_texts, read_status)
    result["artefact_agreement"] = agreement
    if agreement["disagreements"]:
        result["verdict"] = "FAIL"
        result["reasons"] = (list(result.get("reasons") or [])
                             + _agreement_reasons(agreement,
                                                  agreement["witnesses"]))
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


# ---------------------------------------------------------------------------
# vibe-ic#562 — RE-ADJUDICATION RULES for this gate's published records.
#
# THE DRIFT THAT MATTERS HERE is `keep_check_applied`. A PASS means "nothing was
# removed AND every survivor carries its keep attribute" — but the second half is
# only checked when some artefact CAN carry that attribute. On a run where none
# could, `all_keep_attr_intact` is vacuously true and the PASS says nothing about
# preservation intent, while looking identical on paper to a run that checked and
# found everything tagged.
#
# That is the same shape the rest of this project keeps meeting: an absence
# rendering as a pass. Re-adjudicated to VACUOUS_PASS so a reader can tell the two
# apart after the fact.
import _record_adjudication as _ra  # noqa: E402


def _keep_check_vacuity(record: dict):
    """Would this gate still call this a PASS, given what it actually checked?"""
    if record.get("verdict") != "PASS":
        return None
    if record.get("keep_check_applied"):
        return None                    # the keep half really was exercised
    return _ra.Supersession(
        would_issue="VACUOUS_PASS",
        because=("the record carries verdict PASS with keep_check_applied "
                 "false, so no artefact in that run could carry a keep "
                 "attribute and `all_keep_attr_intact` was vacuously true. The "
                 "PASS establishes only that no spare was REMOVED; it says "
                 "nothing about whether preservation intent survived, which is "
                 "the other half of what this gate exists to check"),
    )


RECORD_ADJUDICATION = _ra.declare(
    __file__,
    gate="spare_cell_preservation_check",
    # Where the verdict is decided; the fingerprint follows the module-local call
    # closure from here, so `_collect_present_and_tagged` and the tag helpers are
    # covered without being listed.
    decision_roots=("evaluate_preservation",),
    decision_digest="3ad46abb059ddf1a1654902fce8da157455b982722aab85ccaf47cfcafd7d1c1",
    rules=(
        _ra.Rule(
            rule_id="spare_cell_preservation_check.keep-check-was-vacuous",
            landed_in="#562",
            requires=("verdict", "keep_check_applied"),
            decide=_keep_check_vacuity,
            what=("a PASS from a run where no artefact could carry a keep "
                  "attribute never exercised the keep half of the check"),
        ),
    ),
)


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
