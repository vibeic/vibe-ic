#!/usr/bin/env python3
"""
l20_dft_scan_topology_actionable_check.py — SEMANTIC gate for
L20_DFT_SCAN_TOPOLOGY (batch layergate-7).

BLOCKS or ADVISES?
==================
MIXED, and deliberately so. Three independent findings, two of which
BLOCK (rc=1) and one of which ADVISES (rc=0 + ``[ADVISE]``):

  F1 VACUOUS_DFT_ASSERTION ................................ BLOCKS
      L20 asserts DFT exists — ``dft_present: true``, or a non-null
      ``jtag_tap`` / ``test_compression``, or a non-empty
      ``bist_mbist[]`` — but ``scan_chains[]`` is empty, or its entries
      lack the fields a DFT-insertion step and the ATPG coverage gate
      must reconcile against. This is a claim the layer itself cannot
      back: an asserted scan topology no downstream step can falsify.
      Exactly the checks-that-lie family, and it is self-contained
      inside L20, so blocking costs nothing but a fabricated PASS.

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
    asserts_dft = (
        _truthy_assertion(present)
        or _truthy_assertion(tap)
        or _truthy_assertion(compression)
        or bool(bist)
        or bool(chains)
        or is_extraction_claimed(l20)
    )
    result["evidence"]["asserts_dft"] = asserts_dft

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
    doc_hits = framed_hits(input_doc_texts(project), _DFT_VOCAB_RE)
    sib_hits = framed_hits(sibling_l_doc_texts(project, _SIBLING_CODES),
                           _DFT_VOCAB_RE)
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
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[SKIP] {GATE}: {project} is not a directory")
        return 2

    result = inspect(project)

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
