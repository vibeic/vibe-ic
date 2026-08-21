#!/usr/bin/env python3
"""
l20_dft_scan_topology_actionable_check.py — SEMANTIC gate for
L20_DFT_SCAN_TOPOLOGY (batch layergate-7).

BLOCKS or ADVISES?
==================
MIXED, and deliberately so. Three independent findings, two of which
BLOCK (rc=1) and one of which ADVISES (rc=0 + ``[ADVISE]``):

  F1 VACUOUS_DFT_ASSERTION ................................ BLOCKS
      An EXTRACTED L20 asserts DFT exists — ``dft_present: true``, or a
      non-null ``jtag_tap`` / ``test_compression``, or a non-empty
      ``bist_mbist[]`` — but ``scan_chains[]`` is empty; or a
      ``scan_chains[]`` of any provenance carries entries lacking the
      fields a DFT-insertion step and the ATPG coverage gate must
      reconcile against. This is a claim the layer itself cannot back:
      an asserted scan topology no downstream step can falsify.
      Exactly the checks-that-lie family, and it is self-contained
      inside L20, so blocking costs nothing but a fabricated PASS.

      "EXTRACTED" IS LOAD-BEARING (vibe-ic#1003). Without it F1 read the
      emitter's skeleton default as the design's claim and reddened 48
      of 106 published roots for a value 50 protocol emitters write
      unconditionally. See the guard at the F1 site for the
      cross-tabulation that settles which side was lying.

  F2 REQUIREMENT_OUTSIDE_CONSUMING_LAYER .................. BLOCKS
      The design's OWN inputs state a DFT requirement (its input docs
      demand scan insertion / ATPG coverage / boundary scan / MBIST
      with requirement framing, or a sibling L-doc — L7 test-debug,
      L24 signoff — carries that requirement) but L20, the layer a DFT
      step consumes, carries none of it. This is the L21 defect
      verbatim: the requirement is present SOMEWHERE, absent from the
      layer that consumes it. Blocking is the whole point — the L21
      failure's third compounding fault was that a FAIL verdict was
      issued and the flow continued anyway.

  F3 BACKEND_INSERTED_UNDECLARED_TOPOLOGY ................. ADVISES
      The flow's own backend artifacts prove scan insertion actually
      RAN (``phase2/stage2/dft/scan_netlist*.v`` and friends) while L20
      declares ``dft_present: false`` with zero chains. Nothing can
      reconcile the inserted chains against a declared intent. This is
      real and measured today; it ADVISES rather than blocks for one
      honest reason: **nothing reads L20**. Verified — programs/
      dft_signoff_check.py, programs/dft_atpg_coverage_check.py,
      programs/dft_signoff_common.py and the eda_dft MCP tool all read
      coverage.json / bsdl_plan.json, never L20. A consumer-less layer
      cannot break the backend today, so promoting F3 to a blocker
      would stop runs for a defect that has no downstream victim yet.
      The moment DFT insertion is wired to L20, F3 must be promoted to
      BLOCKS — the docstring is the tripwire, and the finding is
      emitted as JSON so the promotion is a one-line change, not an
      archaeology exercise.

WHY THIS LAYER AT ALL
=====================
L20 is L21's exact shape one step behind: a declared backend-flow layer
with a consumer-less, emitter-less skeleton. SWEPT: ``scan_chains``
empty and ``extraction_status = NOT_YET_EXTRACTED`` in 136/136 real
runs across all 5 fleet machines. It cannot break the backend TODAY
only because nothing reads it. The gate exists so that when DFT
insertion IS wired to L20, the L21 failure does not reproduce verbatim.

DERIVED, NOT RECOGNISED
=======================
Every trigger reads the design's OWN inputs: its own input docs, its
own sibling L-docs, its own emitted DFT artifacts. No design name, no
PDK name, no vendor part number, no design-specific pin literal. The
only literals are DFT industry vocabulary ("scan chain", "ATPG",
"JTAG") — the same class of technology literal
``l8_clock_domains_typed_check`` uses for "MHz" and
``frontend_backend_handoff_check`` already uses for "scan_en".

SINGLE DETERMINISTIC TRACK
==========================
No AI second track. The L21 completeness report advertised a dual
track and recorded ``ai_captured_tokens_count: 0`` — one track wearing
two hats. This gate claims one track and delivers one track.

Usage:
    python3 l20_dft_scan_topology_actionable_check.py <project_dir> [--json PATH]

Exit codes:
    0 = PASS (or ADVISE-only findings)
    1 = FAIL (F1 and/or F2) — BLOCKS
    2 = SKIP (no L20, L20 not applicable to this IC class, or no DFT
        requirement derivable from the design's own inputs)

Honors waiver ``l20_dft_topology_deferred_to_soc_integration`` (>=40
chars) — the honest escape when scan insertion is genuinely an SoC
integrator's job.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from l_doc_consumer_contract import (  # noqa: E402
    applicability_of,
    framed_hits,
    input_doc_texts,
    is_extraction_claimed,
    l_doc_fields,
    load_l_doc,
    numeric_target,
    nonempty_str,
    sibling_l_doc_texts,
    waiver_rationale,
    write_report,
)

GATE = "l20_dft_scan_topology_actionable_check"
WAIVER_ID = "l20_dft_topology_deferred_to_soc_integration"

# DFT technology vocabulary. Requirement framing is applied on top by
# framed_hits(), so a bare mention never triggers on its own.
_DFT_VOCAB_RE = re.compile(
    r"\b(?:scan[ _-]?chain(?:s)?|scan[ _-]?insertion|scan[ _-]?path|"
    r"atpg|automatic\s+test\s+pattern|stuck[- ]at\s+coverage|"
    r"transition\s+fault\s+coverage|boundary[ _-]?scan|bsdl|"
    r"m?bist|memory\s+bist|logic\s+bist|"
    r"test\s+compression|compressor|decompressor|"
    r"jtag|ieee\s*1149|tap\s+controller|test\s+access\s+port|"
    r"design[- ]for[- ]test(?:ability)?|\bdft\b)\b",
    re.IGNORECASE,
)

# A TEST STRUCTURE IS NOT A MESSAGE NAME (vibe-ic#1021)
# =====================================================
# `m?bist` above matches the token BIST wherever it appears, and two published
# roots' own inputs spend it on the name of a PROTOCOL MESSAGE rather than on a
# built-in self-test. In their own words:
#
#   "The <controller> shall transport the following frame types: 0x27
#    <name>, ... 0x46 Data, 0x58 BIST Activate, 0x5F <name>, ..."
#   "BIST (B): When '1', indicates that the command that software built is for
#    sending a BIST <frame>."
#   "0x03  BIST                 Built-In Self Test"      (a message-type table)
#
# Quoted with the roots' own protocol nouns replaced by <placeholders>, the
# same convention #1020 used in this file: the SHAPE is the evidence and the
# standard's name is not part of it.
#
# A frame information structure and a message type are PAYLOADS A PROTOCOL
# DEFINES ON THE WIRE. Neither says anything about whether this design has a
# built-in self-test, which is the only question L20 asks — and both sit inside
# a `shall` sentence, so requirement framing is genuinely present and cannot
# discriminate. This is a VOCABULARY defect, so it is fixed in the vocabulary's
# owner and nowhere else: `framed_hits` is shared by four programs asking four
# different questions, and none of the other three has a DFT vocabulary to
# collide.
#
# TWO STRUCTURAL SIGNALS, BOTH OF WHICH NAME AN ENCODING RATHER THAN A DESIGN:
#   (a) the token is preceded by a WIRE CODE POINT — `0x58 BIST`, `0b0011
#       BIST`, `type 3 BIST`. A number that identifies the token on the wire is
#       a message identifier; a scan chain does not have one.
#   (b) the token is followed by a PROTOCOL-OBJECT NOUN — `BIST <frame>`,
#       `BIST message`, `BIST frame`, `BIST primitive`. The noun says what KIND
#       of thing the token names, and every noun in the set is a thing that is
#       TRANSMITTED. The set includes two standards' own words for a frame
#       alongside the generic ones — the same class of technology literal
#       `_DFT_VOCAB_RE` above already spends on `jtag`, `bsdl` and `ieee 1149`,
#       and for the same reason: the vocabulary of the technology is not a
#       design, PDK, vendor or part identity.
#
# SCOPED TO THE SENTENCE, the same reach `framed_hits` now uses for framing and
# for both of its drop predicates (#1021). That is what reaches "BIST (B): ...
# for sending a BIST FIS", where the FIRST occurrence carries neither signal
# and the sentence that defines it carries both. Within one sentence a token is
# one thing; across a document it is not, which is why this is not run over the
# whole line.
_BIST_TOKEN_RE = re.compile(r"\bm?bist\b", re.IGNORECASE)
_BIST_IS_A_MESSAGE_NAME_RE = re.compile(
    #   (a) a wire code point standing immediately in front of the token
    r"(?:0x[0-9a-f]+|0b[01]+|\btype\s+\d+|\bcode\s+\d+)\s*[-:.]?\s*m?bist\b"
    #   (b) a protocol-object noun standing immediately behind it
    r"|\bm?bist\b[\s-]+(?:fis|message|msg|frame|packet|pdu|primitive|"
    r"ordered\s+set|payload|dword|opcode|command\s+type|message\s+type)\b",
    re.IGNORECASE)


def _bist_is_a_message_name(matched: str, sentence: str) -> bool:
    """True when THIS match spends the BIST token on a protocol message name.

    The ``reject`` hook `framed_hits` calls, so the decision is made INSIDE the
    hit loop — before dedup and before the limit. A post-filter on the returned
    records would be wrong twice: the limit would truncate before it ran, and
    the ``context`` field those records carry is truncated for reporting, so
    the "BIST (B) ... for sending a BIST FIS" sentence loses its own second
    half.

    A match that is not a BIST token is never touched: this narrows ONE
    alternative of the vocabulary and leaves the other fifteen as they were.
    """
    if not _BIST_TOKEN_RE.fullmatch((matched or "").strip()):
        return False
    return bool(_BIST_IS_A_MESSAGE_NAME_RE.search(sentence or ""))


# Sibling layers that legitimately carry a DFT requirement upstream of
# L20. If the requirement lives here and not in L20, that IS the defect.
_SIBLING_CODES = ("L7", "L24", "L19", "L2")

# Keys under which the emitter (phase1_post_process.emit_l_doc_skeleton)
# and the protocol synthesizers write the same concepts.
_CHAIN_KEYS = ("scan_chains", "scan_chain", "chains", "scan_chain_topology")
_TAP_KEYS = ("jtag_tap", "tap", "jtag", "test_access_port")
_COMPRESSION_KEYS = ("test_compression", "compression", "edt")
_BIST_KEYS = ("bist_mbist", "bist", "mbist")
_PRESENT_KEYS = ("dft_present", "dft_required", "scan_required",
                 "standard_scan_chain_present")

# What a DFT-insertion step and the ATPG coverage gate must be able to
# reconcile a chain against.
_CHAIN_NAME_KEYS = ("name", "chain", "id", "chain_name")
_CHAIN_LEN_KEYS = ("length", "len", "flop_count", "ff_count", "depth",
                   "num_flops", "cells")
_CHAIN_SI_KEYS = ("scan_in", "scan_in_port", "si", "input_port", "sin")
_CHAIN_SO_KEYS = ("scan_out", "scan_out_port", "so", "output_port", "sout")
_CHAIN_CLK_KEYS = ("clock", "clk", "shift_clock", "scan_clock",
                   "clock_domain", "frequency_mhz", "shift_freq_mhz")


def _get(fields: dict, keys) -> Any:
    for k in keys:
        if k in fields:
            return fields[k]
    return None


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _truthy_assertion(value: Any) -> bool:
    """A positive DFT assertion. Strings that only describe absence
    ("N/A", "none", "not exposed") are NOT assertions."""
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, str):
        t = value.strip().lower()
        if not t:
            return False
        for neg in ("n/a", "na", "none", "not ", "no ", "absent", "false",
                    "deferred", "unknown", "tbd"):
            if t.startswith(neg):
                return False
        return True
    return value is not None and value is not False


def _chain_missing_fields(entry: Any) -> List[str]:
    """What this chain entry lacks for a consumer to reconcile it."""
    if not isinstance(entry, dict):
        return ["name", "length", "scan_in", "scan_out", "clock"]
    missing: List[str] = []
    if not any(nonempty_str(entry.get(k)) for k in _CHAIN_NAME_KEYS):
        missing.append("name")
    if numeric_target(_get(entry, _CHAIN_LEN_KEYS)) is None:
        missing.append("length")
    if not any(nonempty_str(entry.get(k)) for k in _CHAIN_SI_KEYS):
        missing.append("scan_in")
    if not any(nonempty_str(entry.get(k)) for k in _CHAIN_SO_KEYS):
        missing.append("scan_out")
    clk = _get(entry, _CHAIN_CLK_KEYS)
    if not (nonempty_str(clk) or numeric_target(clk) is not None):
        missing.append("clock")
    return missing


def _dft_hits(texts) -> List[Dict[str, Any]]:
    """Framed DFT-requirement hits from ``texts``, this gate's three policies
    applied: a denial is not a statement, a scope-deferral is not a statement,
    and a protocol message name is not this vocabulary. One helper so the two
    call sites below cannot drift into two policies (#1021)."""
    return framed_hits(texts, _DFT_VOCAB_RE,
                       drop_denied=True,
                       drop_out_of_scope=True,
                       reject=_bist_is_a_message_name)


def _backend_dft_artifacts(project: Path) -> List[str]:
    """The flow's OWN evidence that scan insertion ran.

    Reads only artifact PATHS the flow itself emitted — no design
    identity involved.
    """
    found: List[str] = []
    dft_dir = project / "phase2" / "stage2" / "dft"
    for pat in ("scan_netlist*.v", "atpg_coverage*.rpt",
                "*scan_chain*.json", "*scan_chain*.rpt"):
        for p in sorted(dft_dir.glob(pat)):
            if p.is_file() and p.stat().st_size > 0:
                found.append(str(p))
    return found


def inspect(project: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "gate": GATE,
        "project": str(project),
        "verdict": "SKIP",
        "blocking_findings": [],
        "advisory_findings": [],
        "evidence": {},
    }

    l20_path, l20 = load_l_doc(project, "L20")
    if l20_path is None:
        result["reason"] = "no L20 doc in phase1/generated_docs"
        return result
    result["evidence"]["l20_path"] = str(l20_path)

    if l20 is None:
        result["verdict"] = "FAIL"
        result["blocking_findings"].append({
            "id": "UNPARSEABLE_LAYER",
            "detail": f"{l20_path} is not parseable JSON; no consumer "
                      f"can read a DFT topology out of it.",
        })
        return result

    applicability = applicability_of(l20)
    result["evidence"]["applicability"] = applicability
    if applicability in ("NOT_APPLICABLE", "N/A", "NA"):
        result["reason"] = (f"L20 applicability={applicability} for "
                            f"ic_class={l20.get('ic_class')}")
        return result

    fields = l_doc_fields(l20)
    chains = _as_list(_get(fields, _CHAIN_KEYS))
    tap = _get(fields, _TAP_KEYS)
    compression = _get(fields, _COMPRESSION_KEYS)
    bist = _as_list(_get(fields, _BIST_KEYS))
    present = _get(fields, _PRESENT_KEYS)

    typed_chains = [c for c in chains if not _chain_missing_fields(c)]
    result["evidence"]["scan_chain_count"] = len(chains)
    result["evidence"]["typed_scan_chain_count"] = len(typed_chains)

    # ── F1 VACUOUS_DFT_ASSERTION (BLOCKS) ────────────────────────────
    #
    # AN UN-EXTRACTED LAYER'S FIELD VALUES ARE THE EMITTER'S SKELETON, NOT THE
    # DESIGN'S CLAIM (vibe-ic#1003).
    #
    # F1 used to read `dft_present` as "the layer asserts a DFT topology
    # exists". MEASURED across the 106 tracked L20 documents, cross-tabulating
    # `dft_present` against `scan_chains`:
    #
    #     dft_present truthy  (partial 54 / true 5 / yes 1)  ->  0 carry chains
    #     dft_present falsy   (false 45 / null 1)            ->  1 carries chains
    #
    # The single design in the whole corpus that HAS a scan topology is the one
    # whose `dft_present` is null. The field is not merely uninformative for
    # this question; on this corpus it points the wrong way. It cannot carry the
    # answer F1 asked it for.
    #
    # AND THE PRODUCER IS NOT LYING, which is why this is fixed here and not
    # there. `dft_present = "partial"` is written unconditionally by 50 protocol
    # emitters, and read in context it is TRUE: each one pairs it with an
    # enumerated non-scan test surface (`in_band_test_facilities` /
    # `exposed_dft_features` — measured, 48 of the 60 assertive documents carry
    # one) and prose that says in so many words that the protocol exposes no
    # scan path. "Partial DFT" is a correct statement about a protocol that has
    # in-band test facilities and no scan chain. F1 demanded `scan_chains[]` as
    # the only admissible backing for any DFT statement whatsoever.
    #
    # THE RULE IS THE HOUSE'S, NOT A NEW ONE. `l_doc_consumer_contract.
    # is_extraction_claimed` names the producer state as THREE-valued — NOT-RUN
    # / RAN-AND-EMPTY / RAN-AND-FOUND — and `dft_atpg_coverage_check` already
    # applies it to THIS EXACT FIELD, in the opposite direction, with the same
    # sentence: "its `dft_present: false` is the emitter's field default, not a
    # decision". A default is a default whichever way it points. Corpus:
    # `extraction_status` is NOT_YET_EXTRACTED on 80 documents and absent on the
    # other 26 — ZERO of 106 claim extraction, so on today's corpus no L20 field
    # value is a design's assertion at all.
    #
    # CONTENT IS STILL SELF-EVIDENCING. A non-empty `scan_chains[]` is a
    # topology somebody wrote down, and it is held to the typing contract below
    # exactly as before, extracted or not. Only the assertion-WITHOUT-content
    # arm now requires that extraction actually ran.
    #
    # ALSO CORRECTED, same disjunct: `is_extraction_claimed` used to be an
    # assertion on its own, so a layer that ran extraction and honestly found
    # NOTHING (RAN-AND-EMPTY — the one state that IS a design saying "I need no
    # DFT") was reported as making a claim it could not back. It now asserts
    # nothing, which is what it says.
    #
    # F1 CAN STILL FIRE, and on today's corpus it fires nowhere — because no L20
    # has ever been extracted. That is the honest reading of a layer nothing has
    # populated, and it is a tripwire rather than a silence: the moment
    # extraction runs and writes `dft_present` beside an empty `scan_chains[]`,
    # this reddens.
    extracted = is_extraction_claimed(l20)
    asserted_fields = (
        _truthy_assertion(present)
        or _truthy_assertion(tap)
        or _truthy_assertion(compression)
        or bool(bist)
    )
    asserts_dft = bool(chains) or (asserted_fields and extracted)
    result["evidence"]["asserts_dft"] = asserts_dft
    result["evidence"]["extraction_claimed"] = extracted
    result["evidence"]["asserted_fields_present"] = asserted_fields

    if asserts_dft:
        if not chains:
            result["blocking_findings"].append({
                "id": "VACUOUS_DFT_ASSERTION",
                "detail": (
                    "L20 asserts a DFT topology exists "
                    f"(dft_present={present!r}, jtag_tap={'set' if _truthy_assertion(tap) else 'unset'}, "
                    f"test_compression={'set' if _truthy_assertion(compression) else 'unset'}, "
                    f"bist_mbist={len(bist)} entries, "
                    f"extraction_claimed={is_extraction_claimed(l20)}) "
                    "but scan_chains[] is EMPTY. A DFT-insertion step has "
                    "nothing to build and the ATPG coverage gate has "
                    "nothing to reconcile against: the assertion cannot "
                    "be falsified by anything downstream."),
            })
        else:
            bad: List[str] = []
            for i, c in enumerate(chains):
                miss = _chain_missing_fields(c)
                if miss:
                    label = None
                    if isinstance(c, dict):
                        for k in _CHAIN_NAME_KEYS:
                            if nonempty_str(c.get(k)):
                                label = str(c[k])
                                break
                    bad.append(f"{label or f'scan_chains[{i}]'}: "
                               f"missing {','.join(miss)}")
            if bad:
                result["blocking_findings"].append({
                    "id": "VACUOUS_DFT_ASSERTION",
                    "detail": (
                        f"{len(bad)}/{len(chains)} scan_chains[] entries "
                        f"lack the fields a DFT-insertion step and the "
                        f"ATPG coverage gate must reconcile against "
                        f"(name/length/scan_in/scan_out/clock). "
                        f"Examples: {'; '.join(bad[:5])}"),
                })

    # ── F2 REQUIREMENT_OUTSIDE_CONSUMING_LAYER (BLOCKS) ──────────────
    # `drop_denied=True` — THIS GATE OPTS IN (vibe-ic#1011). Of the 25 F2
    # findings this gate had over the 107 published run dirs, 16 were roots
    # whose own L7 / L19 notes say the requirement is not there — "does NOT
    # specify JTAG / scan-chain / on-chip BIST", "There is no scan chain, no
    # JTAG", "no PDK, floor-plan, SDC, UPF, or DFT artifact at the protocol
    # level". A denial is not a statement of the requirement it denies.
    #
    # DFT vocabulary is the case where this is safe, and that is why the flag
    # is per-consumer rather than global: a real DFT requirement is written
    # POSITIVELY ("support for scan, JTAG (IEEE 1149.1)"), so this gate loses
    # nothing by declining denials. L23's security vocabulary is the opposite
    # — its real requirements are prohibitions — and it deliberately does not
    # opt in. Measured both ways before either was wired.
    #
    # `drop_out_of_scope=True` — THIS GATE OPTS IN TOO (vibe-ic#1021). Two
    # roots' L7 notes hand chip-level JTAG/scan/BIST to a different party's
    # silicon, in a sentence carrying no negation word at all, so no denial
    # ruler can reach them. Same per-consumer reasoning as above and the same
    # measurement: L22's two consumers and L23 move by 0 hits, so neither is
    # switched on.
    doc_hits = _dft_hits(input_doc_texts(project))
    sib_hits = _dft_hits(sibling_l_doc_texts(project, _SIBLING_CODES))
    result["evidence"]["dft_requirement_hits_input_docs"] = len(doc_hits)
    result["evidence"]["dft_requirement_hits_sibling_l_docs"] = len(sib_hits)

    l20_actionable = bool(typed_chains) or (
        _truthy_assertion(tap) and bool(chains))

    if (doc_hits or sib_hits) and not l20_actionable:
        srcs = (doc_hits + sib_hits)[:4]
        result["blocking_findings"].append({
            "id": "REQUIREMENT_OUTSIDE_CONSUMING_LAYER",
            "detail": (
                f"The design's own inputs state a DFT requirement in "
                f"{len(doc_hits)} input-doc location(s) and "
                f"{len(sib_hits)} sibling-L-doc location(s), but L20 — "
                f"the layer a DFT-insertion step and the ATPG coverage "
                f"gate consume — carries no actionable scan topology "
                f"({len(typed_chains)} typed chains of {len(chains)}). "
                f"This is the L21 defect shape: the requirement is "
                f"present somewhere, absent from the layer that "
                f"consumes it."),
            "evidence": srcs,
        })

    # ── F3 BACKEND_INSERTED_UNDECLARED_TOPOLOGY (ADVISES) ────────────
    artifacts = _backend_dft_artifacts(project)
    result["evidence"]["backend_dft_artifacts"] = artifacts[:6]
    if artifacts and not chains:
        result["advisory_findings"].append({
            "id": "BACKEND_INSERTED_UNDECLARED_TOPOLOGY",
            "severity": "ADVISE",
            "detail": (
                f"Scan insertion demonstrably RAN — {len(artifacts)} "
                f"backend DFT artifact(s) present, e.g. "
                f"{Path(artifacts[0]).name} — while L20 declares "
                f"dft_present={present!r} with 0 scan_chains[]. The "
                f"inserted chains have no declared intent to reconcile "
                f"against. ADVISE not BLOCK because nothing currently "
                f"reads L20 (dft_signoff_check / dft_atpg_coverage_check "
                f"/ dft_signoff_common / eda_dft all read coverage.json "
                f"and bsdl_plan.json). Promote to BLOCKS the moment DFT "
                f"insertion is wired to L20."),
            "evidence": artifacts[:6],
        })

    if result["blocking_findings"]:
        result["verdict"] = "FAIL"
    elif result["advisory_findings"]:
        result["verdict"] = "PASS_WITH_ADVISORY"
    elif asserts_dft or doc_hits or sib_hits:
        result["verdict"] = "PASS"
    else:
        result["verdict"] = "SKIP"
        result["reason"] = ("no DFT requirement derivable from the "
                            "design's own inputs and L20 asserts none")
    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[1]
                                 if __doc__ else "")
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None, metavar="PATH")
    # SHOULD A GATE'S OWN FAIL REPORT FEED A DOWNSTREAM BUBBLE-UP GATE?
    # ==================================================================
    # YES — a gate finding IS a step-internal finding, and suppressing the
    # whole class would let a real blocking FAIL hide from the step that signs
    # off. What must never happen is the OTHER thing: a finding the flow
    # deliberately wired ADVISORY becoming BLOCKING by travelling through a
    # report file into a blocking gate. That is not enforcement, it is a
    # declaration being overridden by a side effect.
    #
    # MEASURED, on isolated copies of two roots that are clean today:
    #   evaluation/phase1_parity/afdx   step_internal_fail_bubble_up rc 0 -> 1
    #   evaluation/phase1_parity/jtag   step_internal_fail_bubble_up rc 0 -> 1
    # after running this gate ONCE, with no `--json`: `write_report` publishes
    # `reports/phase1/<gate>.json` unconditionally, and the Step-36 gate scans
    # `reports/**/*.json` for `verdict`. So the "wire it BARE" mitigation that
    # protects l6/l9 does not protect this one — those two only write under
    # `--json`; this one always writes.
    #
    # THE RULE, and it is the repo's own vocabulary rather than a new one:
    # EVERY GATE THAT WRITES A VERDICT-BEARING REPORT MUST DECLARE IN THAT
    # REPORT THE ENFORCEMENT MODE IT IS WIRED AT. `verdict_mode: ADVISES` is
    # already honoured by `step_internal_fail_bubble_up_check` ("a report that
    # declares ADVISES alongside FAIL has already said its verdict does not
    # gate"), already parsed by `flow_gate_enforcement_audit`, and already
    # emitted by `cross_layer_reference_check`, `dfm_screen_check` and the
    # L16/L17/L18 gates. Nothing new is invented; this gate simply joins them.
    #
    # THE DEFAULT IS `BLOCKS`, deliberately. It preserves today's behaviour
    # exactly for every existing caller — a bare invocation still cascades —
    # so this flag can only ever narrow the cascade where a wiring site asks
    # it to, and never widen it. The declaration then lives ON the flow row
    # next to the `advisory_` verb, where the two cannot drift apart silently:
    # promoting the row to blocking means deleting the flag on the same line.
    ap.add_argument("--verdict-mode", choices=("BLOCKS", "ADVISES"),
                    default="BLOCKS", metavar="MODE",
                    help="enforcement mode to DECLARE in the emitted report. "
                         "ADVISES tells step_internal_fail_bubble_up_check "
                         "that this finding does not gate, which is what a "
                         "row wired advisory_program_exit_zero means.")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[SKIP] {GATE}: {project} is not a directory")
        return 2

    result = inspect(project)
    result["verdict_mode"] = args.verdict_mode

    waiver = waiver_rationale(project, WAIVER_ID)
    if waiver and result["verdict"] == "FAIL":
        result["verdict"] = "WAIVED"
        result["waiver"] = waiver

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2,
                                              ensure_ascii=False))
    write_report(project, GATE, result)

    for f in result["advisory_findings"]:
        print(f"[ADVISE] {GATE}: {f['id']} — {f['detail']}")

    verdict = result["verdict"]
    if verdict == "SKIP":
        print(f"[SKIP] {GATE}: {result.get('reason', 'not applicable')}")
        return 2
    if verdict == "WAIVED":
        print(f"[SKIP] {GATE}: waived via {WAIVER_ID} — {result['waiver'][:90]}")
        return 2
    if verdict == "FAIL":
        for f in result["blocking_findings"]:
            print(f"[FAIL] {GATE}: {f['id']} — {f['detail']}")
        return 1
    print(f"[PASS] {GATE}: L20 carries an actionable scan topology "
          f"({result['evidence'].get('typed_scan_chain_count', 0)} typed "
          f"chains) or asserts none while the design requires none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
