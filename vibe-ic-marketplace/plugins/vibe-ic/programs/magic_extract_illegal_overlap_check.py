#!/usr/bin/env python3
"""magic_extract_illegal_overlap_check.py — read the EXTRACTOR'S ERROR CHANNEL.

ENFORCEMENT: advisory — no runner spawns this gate inline, so its exit status
cannot stop a live Step-22 run; it stops the step when `flow_compliance_check`
evaluates the `program_exit_zero` clause this gate is wired into. Declaring
`blocking` here would be the contradiction `flow_gate_enforcement_audit`
records in its `known` register, because `phase3_one_shot_runner`'s
`step_declared_signoff_gates` table does not carry this gate.

THE DEFECT THIS CLOSES
======================
The plugin talked to the extraction tool and never listened to it.

`magic_extract_spice_emit` validates that the TCL we EMIT contains `extract
all` and `ext2spice lvs` — the commands we SENT. Nothing in the plugin read
what came BACK. Measured on the tree this program was written against
(`grep -rEil 'illegal.{0,3}overlap'` over
`vibe-ic-marketplace/plugins/vibe-ic/`): 0 files. The four LVS-side programs
(`lvs_report_check`, `lvs_tapeout_signoff_check`, `lvs_verdict_tokens`,
`lvs_power_aware_extract_tcl`) all read netgen's verdict; none reads the
extractor's.

That gap has a specific consequence. When magic's hierarchical extraction hits
geometry it cannot resolve it does NOT abort and does NOT poison the netlist
with a marker — it writes a feedback entry, prints `N error(s)`, and emits a
`.ext`/`.spice` anyway. Netgen is then handed a netlist built over geometry
magic said it could not interpret, and a `netlist match` verdict over it is a
certificate about a structure that does not correspond to the layout. The LVS
gate answers its own question correctly; nobody asked the extractor's.

WHAT THE ERROR CHANNEL IS, MEASURED — NOT ASSUMED
=================================================
Magic's error channel for extraction is its FEEDBACK list, serialised by
`feedback save <file>`. The format below was measured, in this repo's own
container image, by running a real hierarchical extraction over a layout built
to contain an unresolvable overlap (recipe reproduced verbatim in
`programs/tests/test_magic_extract_illegal_overlap_check.py`), magic 8.3.681,
magic's own bundled generic academic (lambda-scaled, node-free) technology::

    Extracting t1 into t1.ext:
    t1: 1 error
    Total of 1 error (check feedback entries).

and the file `feedback save` wrote::

    box 0 0 4 4
    feedback add "Illegal overlap between ndiffusion and pdiffusion (types do not connect)" medium

So a feedback file is a REPLAYABLE TCL SCRIPT, two lines per entry:

    box <llx> <lly> <urx> <ury>          integers, magic internal units
    feedback add "<text>" [<style>]      text is Tcl-quoted, `\"` escapes

The style token is optional (magic omits it when the entry carries explicit
polygon points — also measured). The message string itself is magic's own
format string, confirmed verbatim in the shipped binary::

    $ strings .../tcl/tclmagic.so | grep -i 'illegal overlap'
    Illegal overlap between %s and %s (types do not connect)

TWO INDEPENDENT READINGS, AND THEY MUST AGREE
=============================================
This gate counts the violation TWICE, from two different objects, and treats
a disagreement as a FAILURE rather than picking a winner:

  STRING  the number of occurrences of the literal `Illegal overlap` in the
          RAW BYTES of the feedback file. This is the upstream reading
          (LibreLane `steps/magic.py:642`, `count_occurences`). It knows
          nothing about the file's grammar.
  PARSED  the number of parsed `(bbox, message)` RECORDS whose message
          classifies as an illegal overlap. This reading knows nothing about
          the raw bytes: it sees only records the grammar above produced.

On a well-formed file the two are equal by construction — each record carries
the phrase exactly once, and a `box` line can never carry it. They come apart
exactly when one of the readings is wrong about the file, and THAT is the
event worth failing on:

  * PARSED < STRING — the phrase is in the file somewhere the grammar did not
    produce a record for: a truncated write, a message split across lines, an
    entry whose `box` line was lost. Records were dropped; the string count is
    the floor.
  * PARSED > STRING — a record classified as an illegal overlap without
    carrying the literal phrase (a case variant, a reworded message from
    another magic build). The string reading is blind to it.

A gate that silently reported one of the two would be reporting a number it
could not defend. This one reports both, gates on `max(STRING, PARSED)` so
neither reading can lower the count, and FAILS on the disagreement itself with
its own rule id.

ABSENCE IS NOT ZERO
===================
`count_occurences` over a file that is not there returns 0, and 0 passes a
threshold of 0. "I could not look" and "I looked and it was clean" would then
be the same word — the exact defect this repo keeps closing. So:

  * extraction evidence present + feedback file ABSENT  -> FAIL, rule
    `EXTRACTION_FEEDBACK_ABSENT`. The extractor ran and its error channel was
    not captured; nothing about this extraction is certified.
  * feedback file present but unreadable                -> FAIL, rule
    `EXTRACTION_FEEDBACK_UNREADABLE`.
  * feedback file present, structurally malformed       -> FAIL, rule
    `EXTRACTION_FEEDBACK_MALFORMED`. A grammar this gate cannot parse means
    the PARSED reading is not a reading at all.
  * feedback file present and EMPTY, with extraction evidence -> PASS at 0.
    This is magic's real clean output: `feedback save` over an empty feedback
    list writes a 0-byte file (measured).
  * NO extraction evidence anywhere in scope            -> rc 2, disclosed
    VACUOUS. Nothing was extracted, so there is no extractor verdict to read.
    This is not an excuse for a missing file: it is reachable only when the
    extraction output directory holds nothing at all, which Step 22's own
    `required_outputs` already fails on.

rc 2 IS NEVER SPENT ON A MISSING FEEDBACK FILE, and that is deliberate:
`flow_compliance_check._check_program_exit_zero` credits rc 2 from a
`program_exit_zero` gate as a VACUOUS_PASS unconditionally, so routing "the
error channel was not captured" to rc 2 would turn the step GREEN — a cheaper
false certificate than the one this gate exists to prevent.

THE METRIC
==========
Published through `step_metrics.emit` under Step 22 as

    22__magic__illegal_overlap__count

The tail `magic__illegal_overlap__count` is upstream's metric name, kept
verbatim so the two are greppable against each other; the leading `22__` is
this repo's schema requirement (`step_metrics.key_defect`: a key that does not
lead with its step is not attributable in a merge). Companions:
`__string_count`, `__parsed_count`, `__records`, `__feedback_present`.

DISCLOSED, so a green run is not read as coverage: `step_metrics.DIRECTIONS`
has no entry for the `count` tail, so the run-to-run differ reports this
metric as `undeclared` rather than `worse` when it rises. `step_metrics.py` is
a protected path and this change does not touch it.

NOT DETERMINED, stated rather than guessed
==========================================
* BLAST RADIUS over the published run corpus. The corpus lives in its own
  repository (`_corpus_location`) and is absent from this checkout with
  `$VIBE_IC_BENCHMARK_DATA` unset, so the count of run trees this gate turns
  red could not be measured here. What IS determined: no producer in this
  plugin writes a magic feedback file today, so on any tree that carries
  extraction output and no feedback file this gate is RED until the extraction
  step captures `feedback save`. That is the honest state of the evidence —
  the extractor's error channel was never read — and reading absence as zero
  is the thing being fixed, not a workaround for it.
* Whether magic emits more than one feedback entry per extracted cell for
  multiple unresolvable overlaps in that cell. Measured: three disjoint
  overlaps between one parent/child pair produced ONE entry. This gate
  therefore treats its count as a FLOOR on the number of overlaps, never as
  the total, and says so in the report.

chip-AGNOSTIC: no vendor, foundry, process, PDK or cell literal appears or can
affect the verdict. The only strings this gate knows are magic's own command
grammar and its own message format string.

CLI
===
    python3 magic_extract_illegal_overlap_check.py <project_dir> [--json OUT]
    python3 magic_extract_illegal_overlap_check.py --feedback <feedback.txt>

Exit codes:
    0 = PASS      feedback read, illegal-overlap count == threshold (0)
    1 = FAIL      count over threshold, readings disagree, or the channel
                  could not be read (absent / unreadable / malformed)
    2 = VACUOUS   no extraction output in scope; disclosed, nothing claimed

Unit-tested in `programs/tests/test_magic_extract_illegal_overlap_check.py`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_text as _atomic_write_text  # noqa: E402

_GATE_NAME = "magic_extract_illegal_overlap_check"
_STEP = "22"

RC_PASS = 0
RC_FAIL = 1
RC_VACUOUS = 2

#: Upstream's threshold, and the only defensible one: an extraction that could
#: not resolve geometry has not produced a netlist that means anything.
DEFAULT_THRESHOLD = 0

#: The literal upstream counts (LibreLane `steps/magic.py:642`). Case-sensitive
#: ON PURPOSE — it is one of two INDEPENDENT readings, and making it agree with
#: the parsed reading by construction would delete the disagreement this gate
#: is built to surface.
ILLEGAL_OVERLAP_LITERAL = "Illegal overlap"

#: The parsed reading's classifier, applied to a PARSED record's message only.
_ILLEGAL_OVERLAP_RE = re.compile(r"illegal\s+overlap", re.IGNORECASE)

#: Magic's own format string, for the layer pair when the full form is present:
#: "Illegal overlap between %s and %s (types do not connect)".
_OVERLAP_TYPES_RE = re.compile(
    r"illegal\s+overlap\s+between\s+(\S+)\s+and\s+(\S+)", re.IGNORECASE)

#: The two-line grammar `feedback save` writes. Measured, not assumed — see the
#: module docstring for the run that produced it.
_BOX_RE = re.compile(r"^\s*box\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*$")
_FEEDBACK_ADD_RE = re.compile(
    r"""^\s*feedback\s+add\s+"((?:[^"\\]|\\.)*)"\s*(.*)$""")

#: Where the extraction step's feedback channel is expected. The FIRST entry is
#: canonical: it sits in Step 22's own declared output directory, mirroring the
#: upstream convention of writing `feedback.txt` into the extraction step's own
#: directory.
FEEDBACK_CANDIDATES = (
    "phase3/stage3/extracted/feedback.txt",
    "phase3/stage3/extracted/magic_extract_feedback.txt",
    "reports/phase3/magic_extract_feedback.txt",
)

#: The directory whose contents prove an extraction produced something. Step 22
#: declares `phase3/stage3/extracted/*.spef` as its required output.
EXTRACTED_DIR = "phase3/stage3/extracted"


# --------------------------------------------------------------------------- #
# Parsing — the second, independent reading
# --------------------------------------------------------------------------- #
def _unescape_tcl(text: str) -> str:
    """`\\"` -> `"`, `\\\\` -> `\\`. Magic quotes the message as Tcl does."""
    return re.sub(r"\\(.)", r"\1", text)


def parse_feedback(text: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Parse a magic `feedback save` file into records + structural defects.

    Returns ``(records, defects)``. A record is
    ``{"bbox": [llx, lly, urx, ury], "style": str, "message": str}``.
    ``defects`` names every line the grammar could not account for; a non-empty
    ``defects`` means the PARSED reading is not a reading and the caller must
    refuse rather than report its number.
    """
    records: List[Dict[str, Any]] = []
    defects: List[str] = []
    pending_box: Optional[List[int]] = None
    pending_line = 0

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        m_box = _BOX_RE.match(line)
        if m_box:
            if pending_box is not None:
                defects.append(
                    f"line {pending_line}: `box` entry has no "
                    f"`feedback add` — the entry it delimits was lost")
            pending_box = [int(g) for g in m_box.groups()]
            pending_line = lineno
            continue
        m_add = _FEEDBACK_ADD_RE.match(line)
        if m_add:
            if pending_box is None:
                defects.append(
                    f"line {lineno}: `feedback add` with no preceding `box` — "
                    f"the entry has no geometry")
            records.append({
                "bbox": pending_box,
                "style": m_add.group(2).strip() or None,
                "message": _unescape_tcl(m_add.group(1)),
            })
            pending_box = None
            continue
        defects.append(f"line {lineno}: not `box` and not `feedback add`: "
                       f"{line.strip()[:120]!r}")

    if pending_box is not None:
        defects.append(f"line {pending_line}: trailing `box` with no "
                       f"`feedback add` — the file ends mid-entry")
    return records, defects


def count_literal(text: str) -> int:
    """The RAW reading: occurrences of the literal phrase in the file bytes."""
    return text.count(ILLEGAL_OVERLAP_LITERAL)


def illegal_overlap_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The PARSED reading: records whose message classifies as the violation."""
    out = []
    for rec in records:
        if not _ILLEGAL_OVERLAP_RE.search(rec["message"] or ""):
            continue
        types = _OVERLAP_TYPES_RE.search(rec["message"] or "")
        out.append({**rec,
                    "types": [types.group(1), types.group(2)] if types else None})
    return out


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def find_feedback(project: Path) -> Optional[Path]:
    for rel in FEEDBACK_CANDIDATES:
        cand = project / rel
        if cand.is_file():
            return cand
    extracted = project / EXTRACTED_DIR
    if extracted.is_dir():
        hits = sorted(extracted.glob("*feedback*.txt"))
        if hits:
            return hits[0]
    return None


def extraction_evidence(project: Path) -> List[str]:
    """Files that prove an extraction produced output, as project-relative paths.

    Deliberately broad: ANY file the extraction directory holds counts. The
    question this answers is "did the extractor run", not "did it run well" —
    narrowing it to `*.spef` would let an extraction that emitted only a
    netlist reach the disclosed-vacuous rc 2.
    """
    extracted = project / EXTRACTED_DIR
    if not extracted.is_dir():
        return []
    return sorted(str(p.relative_to(project)) for p in extracted.rglob("*")
                  if p.is_file())


# --------------------------------------------------------------------------- #
# Verdict
# --------------------------------------------------------------------------- #
def evaluate(project: Optional[Path], feedback_path: Optional[Path],
             threshold: int = DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """Produce the report payload. Pure — no I/O beyond reading the inputs."""
    findings: List[Dict[str, str]] = []
    metrics: Dict[str, Any] = {
        "illegal_overlap_count": None,
        "illegal_overlap_string_count": None,
        "illegal_overlap_parsed_count": None,
        "feedback_records": None,
        "feedback_present": False,
        "threshold": threshold,
    }
    evidence = extraction_evidence(project) if project is not None else []
    out: Dict[str, Any] = {
        "gate": _GATE_NAME,
        "step": _STEP,
        "verdict": "FAIL",
        "rc": RC_FAIL,
        "project": str(project) if project is not None else None,
        "feedback_file": str(feedback_path) if feedback_path else None,
        "extraction_evidence": evidence[:20],
        "extraction_evidence_count": len(evidence),
        "metrics": metrics,
        "findings": findings,
        "honest_notes": [
            "The count is a FLOOR, not a total: magic was measured emitting "
            "ONE feedback entry for three disjoint unresolvable overlaps "
            "between one parent/child pair.",
            "A feedback file that exists and is empty is magic's real clean "
            "output and passes at 0; a feedback file that is ABSENT is not.",
        ],
    }

    # ---- the channel could not be read -----------------------------------
    if feedback_path is None:
        if not evidence:
            out["verdict"] = "VACUOUS"
            out["rc"] = RC_VACUOUS
            findings.append({
                "severity": "INFO", "rule": "NO_EXTRACTION_IN_SCOPE",
                "message": f"no file under {EXTRACTED_DIR}/ — nothing was "
                           f"extracted, so there is no extractor verdict to "
                           f"read. NOTHING IS CLAIMED about this project's "
                           f"extraction.",
            })
            return out
        findings.append({
            "severity": "FAIL", "rule": "EXTRACTION_FEEDBACK_ABSENT",
            "message": f"the extraction produced {len(evidence)} file(s) under "
                       f"{EXTRACTED_DIR}/ but its feedback channel was not "
                       f"captured: none of {', '.join(FEEDBACK_CANDIDATES)} "
                       f"exists. ABSENCE IS NOT ZERO — the extractor's errors "
                       f"were never read, so no count exists and this "
                       f"extraction is NOT certified. Capture it with "
                       f"`feedback save {FEEDBACK_CANDIDATES[0]}` at the end "
                       f"of the extraction TCL.",
        })
        return out

    try:
        text = feedback_path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        findings.append({
            "severity": "FAIL", "rule": "EXTRACTION_FEEDBACK_UNREADABLE",
            "message": f"{feedback_path} exists but could not be read "
                       f"({exc.__class__.__name__}: {exc}); the extractor's "
                       f"errors were not read, so no count exists.",
        })
        return out

    metrics["feedback_present"] = True

    # ---- reading 1: the raw bytes ----------------------------------------
    string_count = count_literal(text)
    metrics["illegal_overlap_string_count"] = string_count

    # ---- reading 2: the parsed structure ---------------------------------
    records, defects = parse_feedback(text)
    metrics["feedback_records"] = len(records)
    if defects:
        findings.append({
            "severity": "FAIL", "rule": "EXTRACTION_FEEDBACK_MALFORMED",
            "message": f"{feedback_path} does not conform to magic's "
                       f"`feedback save` grammar (`box <4 ints>` then "
                       f"`feedback add \"<text>\" [<style>]`), so the parsed "
                       f"reading is not a reading: "
                       f"{len(defects)} defect(s); "
                       f"{'; '.join(defects[:5])}. The raw-string reading "
                       f"found {string_count} occurrence(s) of "
                       f"{ILLEGAL_OVERLAP_LITERAL!r} in a file this gate "
                       f"cannot account for.",
        })
        return out

    overlaps = illegal_overlap_records(records)
    parsed_count = len(overlaps)
    metrics["illegal_overlap_parsed_count"] = parsed_count

    # ---- the two readings must agree -------------------------------------
    # max(), not either one: a disagreement means one reading is blind, and the
    # blind one must not be allowed to lower the number the gate reports.
    count = max(string_count, parsed_count)
    metrics["illegal_overlap_count"] = count
    out["illegal_overlaps"] = [
        {"bbox": r["bbox"], "types": r["types"], "message": r["message"]}
        for r in overlaps[:20]]

    if string_count != parsed_count:
        which = ("the parsed structure found FEWER than the raw text — "
                 "records were dropped by a truncated or malformed write"
                 if parsed_count < string_count else
                 "the parsed structure found MORE than the raw text — an entry "
                 "classifies as an illegal overlap without carrying the "
                 "literal phrase (case variant or reworded message)")
        findings.append({
            "severity": "FAIL", "rule": "ILLEGAL_OVERLAP_COUNT_DISAGREEMENT",
            "message": f"the two independent readings of {feedback_path} "
                       f"DISAGREE: raw-string count={string_count}, "
                       f"parsed-record count={parsed_count} over "
                       f"{len(records)} record(s) — {which}. Neither number "
                       f"can be defended, so this gate reports both and "
                       f"refuses; gated count is max()={count}.",
        })
        return out

    # ---- the gate ---------------------------------------------------------
    if count > threshold:
        shown = "; ".join(
            f"{r['message']} @ box {r['bbox']}" for r in overlaps[:5])
        findings.append({
            "severity": "FAIL", "rule": "ILLEGAL_OVERLAP_NONZERO",
            "message": f"the extraction reported {count} illegal overlap(s) "
                       f"(threshold {threshold}) in {feedback_path}: {shown}"
                       + (" …" if len(overlaps) > 5 else "")
                       + ". Magic could not resolve this geometry, so the "
                         "netlist it emitted does not correspond to the "
                         "layout; an LVS `match` over it certifies a "
                         "structure that was never extracted. This count is a "
                         "FLOOR on the number of overlaps.",
        })
        return out

    out["verdict"] = "PASS"
    out["rc"] = RC_PASS
    findings.append({
        "severity": "INFO", "rule": "EXTRACTION_FEEDBACK_CLEAN",
        "message": f"the extractor's feedback channel was READ "
                   f"({feedback_path}, {len(records)} entry/entries) and both "
                   f"independent readings agree on {count} illegal overlap(s) "
                   f"<= threshold {threshold}.",
    })
    if records:
        findings.append({
            "severity": "INFO", "rule": "EXTRACTION_FEEDBACK_OTHER_ENTRIES",
            "message": f"{len(records)} feedback entry/entries carry no "
                       f"illegal overlap and are NOT gated here: "
                       + "; ".join(r["message"][:80] for r in records[:5]),
        })
    return out


# --------------------------------------------------------------------------- #
# Metric publication
# --------------------------------------------------------------------------- #
def publish_metrics(project: Optional[Path], out: Dict[str, Any]) -> Optional[str]:
    """Emit the metric under Step 22. Best-effort: a metrics-sink failure must
    not change this gate's verdict, which is about the extraction, not about
    bookkeeping. Returns the path written, or None."""
    if project is None:
        return None
    m = out.get("metrics") or {}
    # `.get`, not `[...]`: a metric this run could not determine is published as
    # null — "NOT DETERMINED" — and must never be silently absent or zero.
    payload = {
        f"{_STEP}__magic__illegal_overlap__count":
            m.get("illegal_overlap_count"),
        f"{_STEP}__magic__illegal_overlap__string_count":
            m.get("illegal_overlap_string_count"),
        f"{_STEP}__magic__illegal_overlap__parsed_count":
            m.get("illegal_overlap_parsed_count"),
        f"{_STEP}__magic__feedback__records": m.get("feedback_records"),
        f"{_STEP}__magic__feedback__present": bool(m.get("feedback_present")),
    }
    try:
        import step_metrics as _sm  # noqa: PLC0415
        return str(_sm.emit(project, _STEP, payload))
    except Exception:  # noqa: BLE001 — see the docstring above
        return None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Read magic's extraction feedback channel, publish the "
                    "illegal-overlap count as a metric, and gate it at zero.")
    ap.add_argument("project_dir", nargs="?", default=None,
                    help="Project directory; discovers "
                         + FEEDBACK_CANDIDATES[0])
    ap.add_argument("--feedback", default=None,
                    help="Feedback file to read instead of discovering one")
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                    help="Maximum tolerated illegal-overlap count (default 0)")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="Write the JSON report here")
    args = ap.parse_args(list(argv) if argv is not None else None)

    if args.project_dir is None and args.feedback is None:
        print(f"{_GATE_NAME}: ERROR — give a project directory or --feedback",
              file=sys.stderr)
        return RC_FAIL

    project = Path(args.project_dir) if args.project_dir else None
    if project is not None and not project.is_dir():
        print(f"{_GATE_NAME}: ERROR — {project} is not a directory; NOTHING "
              f"was checked.", file=sys.stderr)
        return RC_FAIL

    if args.feedback is not None:
        feedback = Path(args.feedback)
        if not feedback.is_file():
            # An EXPLICITLY named channel that is not there is the loudest
            # form of the same defect: somebody said where it is and was
            # wrong. It is never a zero.
            out = {
                "gate": _GATE_NAME, "step": _STEP, "verdict": "FAIL",
                "rc": RC_FAIL, "project": str(project) if project else None,
                "feedback_file": str(feedback),
                "metrics": {"feedback_present": False,
                            "illegal_overlap_count": None,
                            "threshold": args.threshold},
                "findings": [{
                    "severity": "FAIL", "rule": "EXTRACTION_FEEDBACK_ABSENT",
                    "message": f"--feedback named {feedback}, which is not a "
                               f"file. ABSENCE IS NOT ZERO: the extractor's "
                               f"errors were never read, so no count exists.",
                }],
            }
            return _emit(args, out, project)
    else:
        feedback = find_feedback(project)

    out = evaluate(project, feedback, args.threshold)
    return _emit(args, out, project)


def _emit(args, out: Dict[str, Any], project: Optional[Path]) -> int:
    metrics_file = publish_metrics(project, out)
    if metrics_file:
        out["metrics_file"] = metrics_file

    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if args.json_out:
        try:
            _atomic_write_text(Path(args.json_out), text)
        except OSError as exc:
            print(f"{_GATE_NAME}: NO REPORT WRITTEN to {args.json_out} "
                  f"({exc.__class__.__name__}: {exc}) — the verdict below was "
                  f"produced but could not be persisted.", file=sys.stderr)
            return RC_FAIL

    print(f"=== {_GATE_NAME} ===")
    print(f"  verdict: {out['verdict']}")
    m = out.get("metrics", {})
    print(f"  {_STEP}__magic__illegal_overlap__count="
          f"{m.get('illegal_overlap_count')} "
          f"(string={m.get('illegal_overlap_string_count')}, "
          f"parsed={m.get('illegal_overlap_parsed_count')}, "
          f"records={m.get('feedback_records')}, "
          f"feedback_present={m.get('feedback_present')})")
    print(f"  feedback_file: {out.get('feedback_file')}")
    for f in out.get("findings", []):
        if f["severity"] in ("FAIL", "WARNING"):
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    return int(out["rc"])


if __name__ == "__main__":
    sys.exit(main())
