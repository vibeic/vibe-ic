#!/usr/bin/env python3
"""l12_sequences_in_consumed_layer_check.py — L12 CONSUMER-CONTRACT gate.

BLOCKS (exit 1).  Rationale: the L12 consumer chain is
``rtl_precheck_gate`` -> ``l12_sequence_implementation_check``, and that
program's whole job is to refuse RTL that has no module per declared
sequence.  It can only refuse what it can SEE.  When the sequences live
in a different layer, or under a key the consumer does not read, the
precheck reports "no L12 sequences declared" and returns PASS — so the
absence of an implementation is never raised at all.  Advising here
would be strictly worse than useless: it would print a warning next to a
green precheck, which is failure (b) of the motivating defect (a FAIL
the flow continues past) with extra steps.

THE PRINCIPLE THIS GATE ENFORCES
--------------------------------
A layer is complete when the requirement is present IN THE LAYER THAT
CONSUMES IT, in actionable form — not when it appears somewhere.

Measured instance of the failure, found on the fleet while authoring
this gate: the Phase-1 reject-rule synthesiser writes its
auto-synthesised sequences into ``L11_OTP_CONTENT.behavioral_sequences``
(where ``l11_sequence_covers_l6_reject_rules_check`` is happy to find
them, because that gate reads L11 OR L12), while
``L12_BEHAVIORAL_SEQUENCES.behavioral_sequences`` stays ``[]``.  The
reject-rule coverage gate goes green, the RTL precheck sees nothing, and
no RTL is ever required to implement the rejection path.  The sequences
are captured and simultaneously unconsumed.

THE CONTRACT
------------
A. STRANDING.  Harvest sequence arrays from every OTHER ``L*.json`` in
   the run.  If any other layer carries behavioural sequences while the
   consumed layer (L12) carries none, FAIL and name the stranding layer,
   the key, and the sequence names.  Derived entirely from the run's own
   documents — no design, PDK, or vendor token anywhere.

B. KEY REACHABILITY.  L12's sequences must sit under a key the consumer
   actually reads.  The accepted key set is not re-spelled here: it is
   READ OUT OF ``l12_sequence_implementation_check`` itself (its
   ``SEQUENCE_ARRAY_KEYS``), so the two can never drift apart again.
   A sequence array parked under an unread key is invisible for the same
   reason a stranded one is.

C. ACTIONABLE SHAPE.  Every sequence the consumer will see must carry:
     * a handle (``id`` or ``name``) — the implementation gate maps that
       handle to an RTL module basename; a sequence with no handle can
       never be matched, so it silently exempts itself;
     * an ORDERED ``steps[]`` of at least 2 typed steps, each with an
       action and at least one typed detail (expected_signal /
       latency_us / next_state / check / ...).  spec-to-rtl cannot
       replay a prose paragraph.
   Entries whose own ``category`` says ``info_only`` /
   ``documentation_only`` are skipped honestly — the same escape hatch
   ``l12_sequence_implementation_check`` already honours, granted by the
   DESIGN's declaration rather than by a waiver.

Usage:
    python3 l12_sequences_in_consumed_layer_check.py <project_dir> [--json OUT]

Exit codes:
    0 = PASS
    1 = FAIL (blocking)
    2 = SKIP / input missing

Honors waiver ``l12_sequences_in_consumed_layer_intentional`` (>=40 chars).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

WAIVER_KEY = "l12_sequences_in_consumed_layer_intentional"
WAIVER_MIN = 40

_CONSUMED_LAYER_PREFIX = "L12"

# Fallback only — the live value is imported from the consumer below.
_FALLBACK_SEQ_KEYS: Tuple[str, ...] = (
    "sequences", "behavioral_sequences", "behavioural_sequences",
    "scenarios", "flows", "handshakes", "behavioral_flows",
    "test_sequences",
)

_STEP_ARRAY_KEYS = ("steps", "phases", "stages", "transitions", "actions",
                    "sequence_steps")
_STEP_ACTION_KEYS = ("action", "do", "stimulus", "operation", "cmd")
_STEP_DETAIL_KEYS = ("expected_signal", "expected", "expected_response",
                     "latency_us", "latency_ms", "latency_ns", "next_state",
                     "check", "wait_for", "duration_us", "duration_ms",
                     "after", "before", "timing", "assert", "observe")
_HANDLE_KEYS = ("id", "name", "sequence_id", "seq_id")
_SKIP_CATEGORY_TOKENS = ("info_only", "documentation_only")

_MIN_STEPS = 2


def _waived(project: Path) -> Tuple[bool, str]:
    p = project / "waivers.json"
    if not p.exists():
        return False, ""
    try:
        d = json.loads(p.read_text(errors="replace"))
        v = d.get(WAIVER_KEY)
        if isinstance(v, str) and len(v.strip()) >= WAIVER_MIN:
            return True, v.strip()
    except Exception:
        pass
    return False, ""


def consumer_sequence_keys() -> Tuple[str, ...]:
    """The key set the L12 CONSUMER reads — imported, never re-spelled.

    Reading this out of ``l12_sequence_implementation_check`` is what
    makes clause B self-maintaining: if the consumer learns a new alias
    the gate learns it too, and if the consumer forgets one this gate
    starts failing the runs that use it.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import l12_sequence_implementation_check as consumer  # noqa: WPS433
        keys = getattr(consumer, "SEQUENCE_ARRAY_KEYS", None)
        if isinstance(keys, (tuple, list)) and keys:
            return tuple(str(k) for k in keys)
    except Exception:
        pass
    return _FALLBACK_SEQ_KEYS


def sequences_under_keys(doc, keys: Tuple[str, ...]) -> Dict[str, List[dict]]:
    """Top-level sequence arrays found under any of `keys`."""
    out: Dict[str, List[dict]] = {}
    if not isinstance(doc, dict):
        return out
    for k in keys:
        v = doc.get(k)
        if isinstance(v, list):
            rows = [x for x in v if isinstance(x, dict)]
            if rows:
                out[k] = rows
    return out


def _all_sequence_arrays(doc, out: Dict[str, List[dict]],
                         depth: int = 0) -> None:
    """Every array that LOOKS like a sequence list, under ANY key.

    Used only to detect clause-B unreachability: content parked under a
    key the consumer does not read.
    """
    if depth > 8:
        return
    if isinstance(doc, dict):
        for k, v in doc.items():
            if isinstance(v, list):
                rows = [x for x in v if isinstance(x, dict)]
                if rows and any(
                    any(hk in r for hk in _HANDLE_KEYS)
                    and any(sk in r for sk in _STEP_ARRAY_KEYS)
                    for r in rows
                ):
                    out.setdefault(str(k), []).extend(rows)
            _all_sequence_arrays(v, out, depth + 1)
    elif isinstance(doc, list):
        for it in doc:
            _all_sequence_arrays(it, out, depth + 1)


def _is_skipped_category(seq: dict) -> bool:
    for k in ("category", "kind", "type"):
        v = seq.get(k)
        if isinstance(v, str) and any(t in v.lower()
                                      for t in _SKIP_CATEGORY_TOKENS):
            return True
    return False


def _typed_steps(seq: dict) -> Tuple[Optional[list], int]:
    """Return (steps_array_or_None, count_of_typed_steps)."""
    for k in _STEP_ARRAY_KEYS:
        v = seq.get(k)
        if isinstance(v, list) and v:
            typed = 0
            for st in v:
                if not isinstance(st, dict):
                    continue
                if any(a in st for a in _STEP_ACTION_KEYS) and \
                        any(d in st for d in _STEP_DETAIL_KEYS):
                    typed += 1
            return v, typed
    return None, 0


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------
def audit(docs_dir: Path, keys: Optional[Tuple[str, ...]] = None) -> Dict:
    if keys is None:
        keys = consumer_sequence_keys()

    report: Dict = {
        "program": "l12_sequences_in_consumed_layer_check",
        "version": "1.0.0",
        "docs_dir": str(docs_dir),
        "summary": {
            "consumer_keys": list(keys),
            "l12_file": "",
            "l12_sequences_visible": 0,
            "l12_sequences_checked": 0,
            "l12_sequences_skipped_category": 0,
            "stranded_sequences": 0,
        },
        "findings": [],
    }

    if not docs_dir.is_dir():
        report["findings"].append({
            "severity": "INFO", "category": "NO_DOCS_DIR", "entity": "",
            "message": f"generated_docs directory absent: {docs_dir}"})
        return report

    l12_files = sorted(docs_dir.glob(f"{_CONSUMED_LAYER_PREFIX}_*.json"))
    if not l12_files:
        report["findings"].append({
            "severity": "INFO", "category": "NO_L12", "entity": "",
            "message": (f"no {_CONSUMED_LAYER_PREFIX}_*.json emitted — the "
                        "consumed layer does not exist in this run")})
        return report

    l12_path = l12_files[0]
    report["summary"]["l12_file"] = l12_path.name
    try:
        l12 = json.loads(l12_path.read_text(errors="replace"))
    except Exception as exc:
        report["findings"].append({
            "severity": "ERROR", "category": "INVALID_JSON",
            "entity": l12_path.name,
            "message": f"cannot parse {l12_path.name}: {exc}"})
        return report

    visible = sequences_under_keys(l12, keys)
    n_visible = sum(len(v) for v in visible.values())
    report["summary"]["l12_sequences_visible"] = n_visible

    # --- B. key reachability inside L12 ------------------------------------
    any_shaped: Dict[str, List[dict]] = {}
    _all_sequence_arrays(l12, any_shaped)
    for k, rows in sorted(any_shaped.items()):
        if k not in keys and rows:
            report["findings"].append({
                "severity": "ERROR", "category": "SEQUENCES_UNDER_UNREAD_KEY",
                "entity": f"{l12_path.name}.{k}",
                "message": (
                    f"{len(rows)} sequence-shaped entr(ies) sit under key "
                    f"{k!r}, which l12_sequence_implementation_check does not "
                    f"read (it reads {list(keys)}). The RTL precheck will "
                    "report 'no L12 sequences declared' and pass."),
            })

    # --- A. stranding in a non-consumed layer ------------------------------
    if n_visible == 0:
        for p in sorted(docs_dir.glob("L*.json")):
            if p.name.startswith(_CONSUMED_LAYER_PREFIX):
                continue
            try:
                other = json.loads(p.read_text(errors="replace"))
            except Exception:
                continue
            found = sequences_under_keys(other, keys)
            for k, rows in sorted(found.items()):
                report["summary"]["stranded_sequences"] += len(rows)
                names = [str(r.get("id") or r.get("name") or "?")
                         for r in rows][:5]
                report["findings"].append({
                    "severity": "ERROR", "category": "SEQUENCES_STRANDED",
                    "entity": f"{p.name}.{k}",
                    "message": (
                        f"{len(rows)} behavioural sequence(s) {names} are "
                        f"declared in {p.name} while {l12_path.name} — the "
                        "layer rtl_precheck_gate consumes — declares none. "
                        "The RTL precheck sees nothing, so no RTL is ever "
                        "required to implement them: captured, and "
                        "simultaneously unconsumed."),
                })

    # --- C. actionable shape ------------------------------------------------
    for key, rows in sorted(visible.items()):
        for i, seq in enumerate(rows):
            handle = None
            for hk in _HANDLE_KEYS:
                v = seq.get(hk)
                if isinstance(v, str) and v.strip():
                    handle = v.strip()
                    break
            label = handle or f"{key}[{i}]"

            if _is_skipped_category(seq):
                report["summary"]["l12_sequences_skipped_category"] += 1
                continue
            report["summary"]["l12_sequences_checked"] += 1

            if not handle:
                report["findings"].append({
                    "severity": "ERROR", "category": "NO_HANDLE",
                    "entity": label,
                    "message": ("sequence has no id/name — "
                                "l12_sequence_implementation_check maps a "
                                "handle to an RTL module basename, so a "
                                "handle-less sequence can never be matched "
                                "and silently exempts itself from the "
                                "implementation requirement."),
                })

            steps, typed = _typed_steps(seq)
            if steps is None:
                report["findings"].append({
                    "severity": "ERROR", "category": "NO_STEPS",
                    "entity": label,
                    "message": ("sequence declares no ordered steps[] — "
                                "spec-to-rtl cannot replay a prose "
                                "paragraph into a state machine."),
                })
                continue
            if len(steps) < _MIN_STEPS:
                report["findings"].append({
                    "severity": "ERROR", "category": "DEGENERATE_STEPS",
                    "entity": label,
                    "message": (f"steps[] has {len(steps)} entr(y/ies); a "
                                f"behavioural sequence needs at least "
                                f"{_MIN_STEPS} ordered steps to encode an "
                                "order at all."),
                })
            if typed == 0:
                report["findings"].append({
                    "severity": "ERROR", "category": "UNTYPED_STEPS",
                    "entity": label,
                    "message": ("no step pairs an action with a typed detail "
                                "(expected_signal / latency_us / next_state / "
                                "check). Every step is prose, so nothing in "
                                "the sequence is checkable."),
                })

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _docs_dir(project: Path) -> Path:
    cand = project / "phase1" / "generated_docs"
    if cand.is_dir():
        return cand
    if project.name == "generated_docs":
        return project
    hits = sorted(project.glob("**/generated_docs"))
    return hits[0] if hits else cand


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Assert behavioural sequences are present in the layer "
                    "the RTL precheck consumes, in replayable form.")
    ap.add_argument("project", help="project directory")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"[SKIP] l12_sequences_in_consumed_layer_check: "
              f"not a directory: {project}")
        return 2

    report = audit(_docs_dir(project))
    errs = [f for f in report["findings"] if f["severity"] == "ERROR"]
    report["summary"]["pass"] = not errs

    if args.json_out:
        outp = Path(args.json_out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    if any(f["category"] in ("NO_DOCS_DIR", "NO_L12")
           for f in report["findings"]):
        print("[SKIP] l12_sequences_in_consumed_layer_check: "
              "no L12 document in this run")
        return 2

    s = report["summary"]
    if errs:
        waived, _ = _waived(project)
        if waived:
            print(f"[PASS] l12_sequences_in_consumed_layer_check: waived "
                  f"({WAIVER_KEY}; {len(errs)} finding(s) suppressed)")
            return 0
        print(f"[FAIL] l12_sequences_in_consumed_layer_check: "
              f"{len(errs)} finding(s) "
              f"(visible_in_L12={s['l12_sequences_visible']}, "
              f"stranded_elsewhere={s['stranded_sequences']}):")
        for f in errs[:8]:
            print(f"  - [{f['category']}] {f['entity']}: {f['message']}")
        if len(errs) > 8:
            print(f"  ... {len(errs) - 8} more")
        return 1

    print(f"[PASS] l12_sequences_in_consumed_layer_check: "
          f"{s['l12_sequences_checked']} sequence(s) visible to the consumer "
          f"with typed ordered steps "
          f"({s['l12_sequences_skipped_category']} info_only skipped); "
          f"no sequences stranded in a non-consumed layer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
