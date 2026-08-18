#!/usr/bin/env python3
"""_analog_layout_matching.py — the block's own record of WHAT MATCHING
STRUCTURE its layout has, and the rules that record can be held to.

WHY THIS ARTEFACT EXISTS
------------------------
`analog-layout`'s headline technique is matching: common-centroid 2x2 / 4x4,
interdigitation ABAB / ABBA, at least two dummies on each side of a matching
row, guard rings. Its own opening line says matching and noise immunity live
or die on layout.

A6 (`analog_a6_block_pv_check`) grades DRC == 0 AND a netgen LVS match. LVS is
a TOPOLOGY compare. It does not see a centroid, it does not see a
interdigitated finger order, and dummies actively HURT it (an unmatched
device on one side of the compare — `lvs-triage` already records that they
need a waiver).

So a block can be laid out as N isolated devices in N slots, with no centroid,
no interleaving and no dummies at all, and close A6 exactly as green as a
fully matched one. Nothing in the tree distinguishes them. The skill's own
`Dummy / guard-ring list` output line is prose in a markdown file that no gate
reads, so "this block was laid out with no matching structure" was a fact a
reader could only INFER, and only by opening the layout.

This module makes it a FIELD.

THE ARTEFACT — `phase3/analog/<block>/layout_matching.json`
-----------------------------------------------------------
    {
      "block": "ota",
      "matching_style": "common_centroid" | "interdigitated" | "none" | ...,
      "matched_groups": [
        {"name": "input_pair", "devices": ["Mn1", "Mn2"],
         "style": "common_centroid", "dummies_per_side": 2}
      ],
      "lvs_dummy_waiver": "<ticket or waiver id>",
      "device_partitions": [
        {"schematic_device": "Mpass", "w_um": 6.0, "m": 120,
         "layout_devices": [{"w_um": 60.0, "nf": 1}, ...]}
      ],
      "note": "free text"
    }

`matching_style: "none"` is a LEGITIMATE, CERTIFYING answer. A level shifter,
a power switch, an ESD clamp and every block whose spec no mismatch term
reaches has no matching group to build, and a rule that failed them would be
teaching runs to invent a centroid to satisfy a gate. What is NOT legitimate
is a layout that answers nothing, and that is why the classification separates
`declared_none` from `undisclosed` and why both are printed.

WHAT IS A FAIL HERE AND WHAT IS ONLY A RECORD
---------------------------------------------
FAIL, and every one of them fires only on a disclosure that EXISTS — so the
fleet cost of adding them is exactly zero and the price of writing the file is
only that you have to mean it:

  * MALFORMED           — the file exists and answers nothing.
  * STYLE_GROUPS_CONTRADICT
                        — `none` with groups listed, or a matching style with
                          no group. The two fields must agree.
  * GROUP_DUMMIES_INSUFFICIENT
                        — a matched group declaring fewer than 2 dummies per
                          side. That threshold is the authoring skill's own
                          standing rule; this is that rule, executed.
  * DUMMIES_LVS_UNRECONCILED
                        — dummies declared and no `lvs_dummy_waiver` named. A
                          dummy is a device the schematic does not have; a
                          block cannot both carry dummies and claim a clean
                          LVS match with nothing recording how.
  * DEVICE_PARTITION_WIDTH_MISMATCH
                        — an N-way split of one schematic device whose layout
                          widths do not SUM to `w_um x m`. Pure arithmetic
                          over the declared list, PDK-independent.

RECORD ONLY, deliberately:

  * The `matching_disclosure` class per block, on every verdict path.
  * `multifinger_layout_devices` — declared layout devices with `nf > 1`.
    Whether a multi-finger gencell extracts with per-finger pins that break
    the compare is a property of ONE PDK's device generator, verified with one
    netgen command; a gate that failed it would be shipping one PDK's defect
    as a universal rule.

chip-AGNOSTIC: JSON field grammar and arithmetic. No PDK, vendor, design,
block or device-name literal anywhere in this file.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

#: The per-block artefact this module owns.
MATCHING_ARTEFACT = "layout_matching.json"

#: The disclosure token that means "this block was laid out with no matching
#: structure". Case-insensitive on read.
STYLE_NONE = "none"

#: The authoring skill's own standing rule for a matched row.
MIN_DUMMIES_PER_SIDE = 2

# ── the four classes, ranked the way every sibling on this track ranks ────
#: A matching discipline is declared and at least one group is named.
DISCLOSURE_MATCHED = "declared_matched"
#: An explicit, certifying "no matching structure in this block".
DISCLOSURE_NONE = "declared_none"
#: The record exists and answers nothing.
DISCLOSURE_MALFORMED = "malformed"
#: No record at all — the shape of every layout drawn before this field
#: existed, and the one a reader must not confuse with `declared_none`.
DISCLOSURE_UNDISCLOSED = "undisclosed"

#: The line-start stdout sentinel, the same shape as this repo's existing
#: `VACUOUS_PASS:` / `STRUCTURE_ONLY:` tokens, so a consumer can read the fact
#: from a gate that PASSED and from one that failed for an unrelated reason
#: without either changing its exit code.
MATCHING_TOKEN = "MATCHING:"

_REL_TOL = 1e-6


class Disclosure(NamedTuple):
    """One block's answer, and everything a gate needs from it."""
    klass: str
    doc: Optional[dict]
    findings: List[dict]
    multifinger: List[str]

    @property
    def declared(self) -> bool:
        return self.klass in (DISCLOSURE_MATCHED, DISCLOSURE_NONE)


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _style_is_none(style: Any) -> bool:
    return isinstance(style, str) and style.strip().lower() == STYLE_NONE


def _finding(block: str, rule: str, rel: str, detail: str,
             **extra: Any) -> dict:
    out = {"block": block, "rule": rule, "rel_path": rel, "detail": detail}
    out.update(extra)
    return out


def _check_groups(block: str, rel: str, doc: dict,
                  groups: List[dict]) -> List[dict]:
    """The rules over `matched_groups[]`. Every one fires only on a group the
    disclosure itself listed."""
    findings: List[dict] = []
    dummies_total = 0
    for idx, g in enumerate(groups):
        if not isinstance(g, dict):
            findings.append(_finding(
                block, "A5_MATCHING_DISCLOSURE_MALFORMED", rel,
                f"`matched_groups[{idx}]` is {type(g).__name__}, not an "
                f"object — a group that is not a record answers nothing "
                f"about the structure it claims to describe."))
            continue
        name = g.get("name") or f"matched_groups[{idx}]"
        per_side = _num(g.get("dummies_per_side"))
        if per_side is None:
            findings.append(_finding(
                block, "A5_MATCHING_GROUP_DUMMIES_INSUFFICIENT", rel,
                f"group `{name}` declares a matching structure and no "
                f"`dummies_per_side`. The edge device of a matched row sees a "
                f"different neighbourhood from an interior one, which is the "
                f"mismatch term the row was built to cancel; the authoring "
                f"skill's standing rule is at least "
                f"{MIN_DUMMIES_PER_SIDE} per side. Declare the number — "
                f"including 0, if that is what was drawn and the block's spec "
                f"can carry it.", group=name))
            continue
        # `dummies_per_side` is per SIDE and a matched row has two of them.
        dummies_total += 2 * int(per_side) if per_side > 0 else 0
        if per_side < MIN_DUMMIES_PER_SIDE:
            findings.append(_finding(
                block, "A5_MATCHING_GROUP_DUMMIES_INSUFFICIENT", rel,
                f"group `{name}` declares dummies_per_side={per_side:g}, "
                f"below the authoring skill's standing minimum of "
                f"{MIN_DUMMIES_PER_SIDE}. A matched row whose end devices "
                f"have no dummy neighbour is matched everywhere except at its "
                f"two ends, which is where the gradient is largest.",
                group=name, dummies_per_side=per_side))
    waiver = doc.get("lvs_dummy_waiver")
    if dummies_total > 0 and not (isinstance(waiver, str) and waiver.strip()):
        findings.append(_finding(
            block, "A5_MATCHING_DUMMIES_LVS_UNRECONCILED", rel,
            f"{dummies_total} dummy device(s) declared across "
            f"{len(groups)} group(s) and no `lvs_dummy_waiver` names how the "
            f"per-block LVS compare at A6 reconciles them. A dummy is a "
            f"device the schematic does not contain; the compare either sees "
            f"it and does not match, or it was suppressed and something has "
            f"to say what suppressed it.", dummies=dummies_total))
    return findings


def _check_partitions(block: str, rel: str,
                      partitions: List[Any]) -> tuple:
    """§ the arithmetic rule: an N-way split of one schematic device must SUM
    to `w_um x m`. Returns (findings, multifinger_device_names)."""
    findings: List[dict] = []
    multifinger: List[str] = []
    for idx, p in enumerate(partitions):
        if not isinstance(p, dict):
            findings.append(_finding(
                block, "A5_MATCHING_DISCLOSURE_MALFORMED", rel,
                f"`device_partitions[{idx}]` is {type(p).__name__}, not an "
                f"object."))
            continue
        dev = p.get("schematic_device") or f"device_partitions[{idx}]"
        w = _num(p.get("w_um"))
        m = _num(p.get("m"))
        if m is None:
            m = 1.0
        kids = p.get("layout_devices")
        if not isinstance(kids, list) or not kids:
            findings.append(_finding(
                block, "A5_MATCHING_DISCLOSURE_MALFORMED", rel,
                f"partition of `{dev}` lists no `layout_devices[]` — a "
                f"partition that names no parts is not a partition.",
                schematic_device=dev))
            continue
        widths = [_num(k.get("w_um")) if isinstance(k, dict) else None
                  for k in kids]
        for k in kids:
            if isinstance(k, dict) and (_num(k.get("nf")) or 1) > 1:
                multifinger.append(str(k.get("name") or dev))
        if w is None or any(x is None for x in widths):
            findings.append(_finding(
                block, "A5_MATCHING_DISCLOSURE_MALFORMED", rel,
                f"partition of `{dev}` carries a non-numeric width — the sum "
                f"rule cannot be evaluated, so the partition asserts nothing.",
                schematic_device=dev))
            continue
        want = w * m
        got = sum(x for x in widths if x is not None)
        if want == 0 or abs(got - want) > _REL_TOL * max(abs(want), 1.0):
            findings.append(_finding(
                block, "A5_DEVICE_PARTITION_WIDTH_MISMATCH", rel,
                f"`{dev}` is split into {len(kids)} layout device(s) whose "
                f"widths sum to {got:g} um against a schematic "
                f"{w:g} um x m={m:g} = {want:g} um. A partition that does not "
                f"sum is a different circuit from the one A4 measured, and "
                f"netgen merges parallel devices by ADDING their widths, so "
                f"the compare sees the sum and not the intent.",
                schematic_device=dev, w_layout_sum_um=got,
                w_schematic_total_um=want))
    return findings, multifinger


def read_disclosure(block_dir, block: str) -> Disclosure:
    """Read one block's matching record and hold it to the rules above.

    `block_dir` may be any path-like; a missing directory reads as
    `undisclosed`, which is the honest answer for every layout drawn before
    this field existed."""
    path = Path(block_dir) / MATCHING_ARTEFACT
    rel = f"{MATCHING_ARTEFACT}"
    if not path.is_file():
        return Disclosure(DISCLOSURE_UNDISCLOSED, None, [], [])
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return Disclosure(DISCLOSURE_MALFORMED, None, [_finding(
            block, "A5_MATCHING_DISCLOSURE_MALFORMED", rel,
            f"unreadable / not JSON: {exc}")], [])
    if not isinstance(doc, dict) or "matching_style" not in doc:
        return Disclosure(DISCLOSURE_MALFORMED, None, [_finding(
            block, "A5_MATCHING_DISCLOSURE_MALFORMED", rel,
            f"no `matching_style` field — the record exists and answers "
            f"nothing, which reads to every consumer exactly like the absence "
            f"the field was added to end.")], [])

    style = doc.get("matching_style")
    groups = doc.get("matched_groups")
    groups = groups if isinstance(groups, list) else []
    findings: List[dict] = []

    if not isinstance(style, str) or not style.strip():
        return Disclosure(DISCLOSURE_MALFORMED, doc, [_finding(
            block, "A5_MATCHING_DISCLOSURE_MALFORMED", rel,
            f"`matching_style` is {style!r} — declare a style, or the "
            f"sentinel {STYLE_NONE!r} for a block that has no matching "
            f"structure.")], [])

    is_none = _style_is_none(style)
    if is_none and groups:
        findings.append(_finding(
            block, "A5_MATCHING_STYLE_GROUPS_CONTRADICT", rel,
            f"`matching_style` is {STYLE_NONE!r} while {len(groups)} matched "
            f"group(s) are listed. The record disagrees with itself, so a "
            f"consumer reading either field alone reads a different layout."))
    if (not is_none) and not groups:
        findings.append(_finding(
            block, "A5_MATCHING_STYLE_GROUPS_CONTRADICT", rel,
            f"`matching_style` is {style!r} and `matched_groups` is empty. A "
            f"matching style with nothing matched is the same layout as "
            f"{STYLE_NONE!r} wearing a better word."))

    if not is_none:
        findings.extend(_check_groups(block, rel, doc, groups))

    parts = doc.get("device_partitions")
    multifinger: List[str] = []
    if isinstance(parts, list) and parts:
        pf, multifinger = _check_partitions(block, rel, parts)
        findings.extend(pf)

    klass = DISCLOSURE_NONE if is_none else DISCLOSURE_MATCHED
    return Disclosure(klass, doc, findings, multifinger)


def summarise(disclosures: Dict[str, Disclosure]) -> dict:
    """The machine-readable block of summary keys a gate merges into its own
    report. Emitted on EVERY verdict path — a step can fail for one block and
    still have recorded an unmatched layout for another, and a reader needs
    both facts."""
    by_class: Dict[str, List[str]] = {}
    multifinger: Dict[str, List[str]] = {}
    for block, d in sorted(disclosures.items()):
        by_class.setdefault(d.klass, []).append(block)
        if d.multifinger:
            multifinger[block] = d.multifinger
    out = {
        "matching_disclosure": {b: d.klass
                                for b, d in sorted(disclosures.items())},
        "blocks_matching_declared": by_class.get(DISCLOSURE_MATCHED, []),
        "blocks_no_matching_structure": by_class.get(DISCLOSURE_NONE, []),
        "blocks_matching_undisclosed": by_class.get(DISCLOSURE_UNDISCLOSED, []),
        "blocks_matching_malformed": by_class.get(DISCLOSURE_MALFORMED, []),
    }
    if multifinger:
        # RECORD, never a verdict — see the module docstring.
        out["multifinger_layout_devices"] = multifinger
    return out


def matching_disclosure(gate_name: str,
                        disclosures: Dict[str, Disclosure]) -> None:
    """Print the ONE line, LAST, and only when there is something to say.

    Same two properties `structure_only_disclosure` had to hold: called
    regardless of the gate's verdict, and kept short enough to survive the
    consumer's fixed-width tail."""
    none_blocks = [b for b, d in sorted(disclosures.items())
                   if d.klass == DISCLOSURE_NONE]
    undisclosed = [b for b, d in sorted(disclosures.items())
                   if d.klass == DISCLOSURE_UNDISCLOSED]
    if not none_blocks and not undisclosed:
        return
    bits = []
    if none_blocks:
        bits.append(f"{len(none_blocks)} laid out with NO matching structure "
                    f"({_names(none_blocks)})")
    if undisclosed:
        bits.append(f"{len(undisclosed)} did not say ({_names(undisclosed)})")
    print(f"{MATCHING_TOKEN} {'; '.join(bits)} [{gate_name}]")


def _names(blocks: List[str]) -> str:
    names = ", ".join(str(b) for b in blocks)
    return names if len(names) <= 48 else f"{names[:45]}..."


__all__ = [
    "MATCHING_ARTEFACT", "MATCHING_TOKEN", "STYLE_NONE",
    "MIN_DUMMIES_PER_SIDE",
    "DISCLOSURE_MATCHED", "DISCLOSURE_NONE", "DISCLOSURE_MALFORMED",
    "DISCLOSURE_UNDISCLOSED",
    "Disclosure", "read_disclosure", "summarise", "matching_disclosure",
]
