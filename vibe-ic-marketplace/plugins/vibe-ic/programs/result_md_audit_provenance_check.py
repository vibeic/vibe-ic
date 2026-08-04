#!/usr/bin/env python3
"""result_md_audit_provenance_check.py — Wave 33 (v0.119.65).

When an agent ships a `RESULT.md` claiming Phase 2+3 completion (and
in particular claiming a successful SOF burn against the lab rig),
that document must cite verifiable provenance for the burn:

  * `audit_sha256` — SHA-256 of the
    `phase23_completion_audit.json` artifact the agent ran their
    self-audit against.
  * `program_response.error_code` — the mcp-eda program-tool's
    response error_code (must be a PASS-class value, e.g.
    `program_succeeded` / `success`; OR the response object must
    carry `success: true`). Equivalent: presence of a
    `burn_provenance.json` reference whose `audit_verdict` is
    `PASS` / `PASS_WITH_WAIVERS`.
  * `audit_verdict` — `PASS` or `PASS_WITH_WAIVERS`.

Rationale (Wave 32 forensic): if the agent claims the SOF burned,
they had to invoke a guarded burn tool (Wave 33: only path that
reaches silicon). The guard refuses to burn when the audit JSON
verdict is FAIL. So the program-tool response must carry a PASS
indicator AND the agent must have read the audit JSON they cited.
RESULT.md citing these three things is verifiable provenance —
fabrication forces the agent to invent a SHA that matches an audit
JSON they can't actually have.

Detection
=========
1. If `<project>/RESULT.md` does not exist → SKIP (agent has not
   claimed completion yet).
2. Read RESULT.md.
3. Look for the three required citations:
     a. SHA-256 of audit JSON — token `audit_sha256` followed by a
        64-hex-char string (or shorter if you write `sha256:<64hex>`).
        Synonym: `phase23_completion_audit.json` filename + a hex
        SHA on the same or next line.
     b. Program-response evidence — token `program_response`,
        `mcp_program_response`, OR `burn_provenance.json` with a
        success-class indicator nearby (`success: true`,
        `error_code: ... succeeded`, `error_code: success`).
     c. Audit verdict — token `audit_verdict` with value `PASS` or
        `PASS_WITH_WAIVERS`. Synonym: a quoted block citing
        `\"verdict\": \"PASS\"` from the audit JSON.
4. If RESULT.md claims a successful burn / hardware PASS / Phase
   2+3 PASS BUT any of the three citations is missing → FAIL.

Chip-AGNOSTIC: pure schema check on RESULT.md content; no
chip / pin / vendor name hardcoded.

Exit codes
==========
0 — PASS / SKIP / PASS_WITH_WAIVER
1 — FAIL
2 — usage error
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

WAIVER_KEY = "result_md_audit_provenance_intentional"
WAIVER_MIN_LEN = 40

# Detect whether RESULT.md actually claims completion. We trigger only
# when the doc claims a successful burn or Phase 2+3 PASS — pure
# in-progress drafts (e.g. "FAIL across 5/5 runs") get a SKIP since
# the agent is being honest.
# Wave 36 (v0.119.68) — chip-AGNOSTIC claim patterns only. The
# `<half-duplex-tester> / 0xF2 / byte[6]` literals were <chip-class>-specific and have
# been removed from the default set. Projects that need additional
# success-claim patterns (e.g. their own host-tester PASS sentinel)
# can provide them via `<project>/result_pass_signature.json`:
#
#   {"pass_patterns": ["MD-?905 .* 0xF2", "byte\\[6\\]=0xF2"]}
#
_CLAIMS_PASS_PATTERNS = (
    r"\bPHASE\s*2\s*\+\s*3\b[^\n]{0,40}\bPASS\b",
    r"\bsof[^\n]{0,40}\bsuccess\b",
    r"\bburn[^\n]{0,40}\b(?:success|completed|verified)\b",
    r"\bSOF[^\n]{0,40}\bprogrammed\b",
    r"\bhardware[^\n]{0,40}\bPASS\b",
    r"\boverall\s*verdict\s*[:=]\s*PASS\b",
    r"\baudit[_\s]*verdict\s*[:=]\s*['\"]?PASS",
)


def _load_project_pass_signature(project: Path) -> tuple[str, ...]:
    """Wave 36 — load per-project chip-specific PASS-claim regexes
    from `<project>/result_pass_signature.json`.

    Returns an empty tuple when the file is absent or malformed; the
    chip-agnostic default patterns above remain active.
    """
    p = project / "result_pass_signature.json"
    if not p.is_file():
        return ()
    try:
        d = json.loads(p.read_text(errors="ignore"))
    except Exception:
        return ()
    raw = d.get("pass_patterns")
    if not isinstance(raw, list):
        return ()
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    return tuple(out)


def _build_claims_re(project: Path) -> "re.Pattern[str]":
    extras = _load_project_pass_signature(project)
    return re.compile(
        "|".join(list(_CLAIMS_PASS_PATTERNS) + list(extras)),
        re.IGNORECASE,
    )


_CLAIMS_PASS_RE = re.compile(
    "|".join(_CLAIMS_PASS_PATTERNS), re.IGNORECASE,
)

# Citation patterns.
_AUDIT_SHA_RE = re.compile(
    r"audit[_\s]*sha(?:[_\s]*256)?\s*[:=]\s*"
    r"(?:sha256:)?([0-9a-fA-F]{32,64})",
    re.IGNORECASE,
)
_AUDIT_SHA_GENERIC_RE = re.compile(
    r"phase23_completion_audit\.json[^\n]{0,200}?"
    r"(?:sha256:)?([0-9a-fA-F]{40,64})",
    re.IGNORECASE | re.DOTALL,
)
_PROGRAM_RESPONSE_RE = re.compile(
    r"(?:program[_\s]*response|mcp[_\s]*program[_\s]*response|"
    r"burn[_\s]*provenance(?:\.json)?)\b",
    re.IGNORECASE,
)
_PROGRAM_SUCCESS_RE = re.compile(
    r'(?:"success"\s*:\s*true|'
    r'success\s*[:=]\s*true|'
    r"error[_\s]*code\s*[:=]\s*['\"]?(?:success|program[_\s]*succeeded|"
    r"programmed_ok|burn[_\s]*ok|ok)['\"]?|"
    r"\bguard[_\s]*invoked\s*[:=]\s*true)",
    re.IGNORECASE,
)
_AUDIT_VERDICT_RE = re.compile(
    r"audit[_\s]*verdict\s*[:=]\s*['\"]?"
    r"(PASS_WITH_WAIVERS|PASS)\b",
    re.IGNORECASE,
)

# ── two rules that apply to ANY RESULT.md, PASS-claiming or not ───────────
# Both come from the same measured failure shape: a document reporting on a
# run tree that is not the tree it sits in.
#
# THE RULE, with no tool or step name in it:
#
#   A directory presented as the evidence for a result must not contain a
#   document that contradicts that evidence. A number a document quotes as
#   proof must be recomputable from the directory the document sits in, and a
#   document that reports on artefacts older than itself is reporting on a
#   different run.
#
# (a) STALE. Measured: a run directory carried a report written at 05:55
#     asserting one tally and describing a step as having produced nothing,
#     while the artefacts in the same directory were written at 10:12 and that
#     step had produced them. Four sibling directories carried byte-identical
#     copies of that one document. Nothing in the tree said which run it
#     described, and a reader opening the directory it was told to open got
#     the wrong round's numbers with no way to notice.
#
# (b) UNVERIFIED DIGEST. The audit-SHA citation below was checked for
#     PRESENCE and never against the artefact it names, so a 64-hex string
#     copied from any other run satisfied it. A digest quoted as proof that
#     nobody recomputes is not proof; it is a shape.
_TALLY_RE = re.compile(
    r"PASS\s*=\s*(\d+)\s+FAIL\s*=\s*(\d+)\s+MISSING\s*=\s*(\d+)",
    re.IGNORECASE,
)
#: Directories that MAY hold a run tree — used to decide `_is_run_tree`.
_EVIDENCE_ROOTS = ("reports", "phase1", "phase2", "phase3")
#: The compliance flow's OWN output root. The umbrella compliance check and its
#: sub-checkers (re)write their gate/audit JSONs under `reports/` on EVERY
#: invocation, so the newest mtime under `reports/` advances each run. A
#: freshness judge must not treat the reports IT regenerates as "a newer round
#: of the design": doing so made this gate's verdict depend on how many times
#: the gate had been run.
#:
#: Measured (subservient_gf180mcuD, plugin 1.9.76): a fresh run tree passed on
#: run 1 (newest evidence `reports/phase2/gates/cdc_reset_dep.json` sat 8s after
#: RESULT.md, within grace) and FAILED on run 2+ (the umbrella re-stamped
#: `reports/phase2/gates/spec_required_artifacts.json` to now, 7251s after
#: RESULT.md's preserved mtime). Across 3 runs, 100% of the umbrella's file
#: mutations — content AND mtime — landed under `reports/`; zero under phase*/
#: or the project root. Excluding `reports/` from the freshness reference makes
#: the newest-evidence mtime stable across runs, so the verdict no longer
#: depends on the run count, while every DESIGN-round artefact (phase1/2/3 +
#: root) a stale RESULT.md would actually contradict stays in scope.
_FLOW_OUTPUT_ROOTS = ("reports",)
#: Roots whose newest file dates the DESIGN round this document reports on —
#: the evidence roots minus the flow's own regenerated output tree.
_DESIGN_EVIDENCE_ROOTS = tuple(
    r for r in _EVIDENCE_ROOTS if r not in _FLOW_OUTPUT_ROOTS)
#: A document written within this many seconds of the newest artefact is part
#: of the same round. Generous on purpose: the rule must fire on a stale
#: ROUND, never on the ordinary case of writing the report a few minutes after
#: the run that produced the artefacts.
_STALE_GRACE_S = 3600


def _newest_evidence(project: Path) -> Tuple[Optional[float], Optional[str]]:
    """`(mtime, path)` of the newest DESIGN-round artefact.

    Walks `_DESIGN_EVIDENCE_ROOTS` — the evidence roots MINUS the compliance
    flow's own output tree (`reports/`). The flow re-stamps `reports/` on every
    run, so including it made this gate's verdict depend on the run count (PASS
    on run 1, FAIL on run 2+). The design round's real artefacts live under
    phase1/2/3 and the project root, which the flow does not mutate; keying the
    freshness reference on those makes the verdict run-count-invariant.
    """
    newest: Optional[float] = None
    newest_p: Optional[str] = None
    for root in _DESIGN_EVIDENCE_ROOTS:
        d = project / root
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if newest is None or m > newest:
                newest, newest_p = m, str(p.relative_to(project))
    return newest, newest_p


def _find_audit_json(project: Path) -> Optional[Path]:
    """The audit artefact a RESULT.md cites by digest, in THIS tree."""
    for cand in sorted(project.rglob("phase23_completion_audit.json")):
        if cand.is_file():
            return cand
    return None


def _is_run_tree(project: Path) -> bool:
    """True when this directory is a RUN TREE — one that holds the artefacts a
    report would be reporting on.

    Both rules below are about an evidence DIRECTORY: a document that
    contradicts the evidence beside it, and a digest that cannot be recomputed
    from the tree that published it. A directory holding a document and no
    evidence is not that; there is nothing there for the document to
    contradict, and inventing an obligation for it would be a different rule
    wearing this one's name."""
    return any((project / r).is_dir() for r in _EVIDENCE_ROOTS)
_VERDICT_QUOTED_RE = re.compile(
    r'"verdict"\s*:\s*"(PASS_WITH_WAIVERS|PASS)"',
    re.IGNORECASE,
)


def _waived(project: Path) -> Tuple[bool, str]:
    waivers = project / "waivers.json"
    if not waivers.exists():
        return False, ""
    try:
        d = json.loads(waivers.read_text())
    except Exception:
        return False, ""
    raw = d.get(WAIVER_KEY)
    if isinstance(raw, str) and len(raw.strip()) >= WAIVER_MIN_LEN:
        return True, raw.strip()
    if isinstance(raw, dict):
        rationale = raw.get("rationale") or raw.get("reason") or ""
        if isinstance(rationale, str) and \
           len(rationale.strip()) >= WAIVER_MIN_LEN:
            return True, rationale.strip()
    return False, ""


def inspect(project: Path) -> Tuple[List[str], List[str], dict]:
    failures: List[str] = []
    warnings: List[str] = []
    summary: dict = {}

    result_md = project / "RESULT.md"
    if not result_md.exists():
        summary["skip_reason"] = (
            "RESULT.md not present — agent has not yet claimed "
            "completion; nothing to audit"
        )
        return failures, warnings, summary

    try:
        text = result_md.read_text(errors="ignore")
    except OSError as e:
        failures.append(
            f"RESULT_MD_UNREADABLE — {result_md}: {e}"
        )
        return failures, warnings, summary

    summary["result_md_path"] = str(result_md.relative_to(project))
    summary["result_md_bytes"] = len(text.encode("utf-8"))

    # ── (a) the document must not predate the evidence it reports on ──────
    # Checked BEFORE the PASS-claim gate below, on purpose. The measured
    # failure was a document that claimed a FAIL — so every rule that fires
    # only on a PASS claim skipped it — while asserting the WRONG ROUND's
    # numbers inside the directory a reader had been pointed at. A stale
    # report is a trap whatever verdict it carries.
    is_run_tree = _is_run_tree(project)
    summary["is_run_tree"] = is_run_tree
    tally = _TALLY_RE.search(text) if is_run_tree else None
    summary["quotes_compliance_tally"] = bool(tally)
    if tally:
        summary["quoted_tally"] = {
            "PASS": int(tally.group(1)), "FAIL": int(tally.group(2)),
            "MISSING": int(tally.group(3))}
    # Only walked when the document actually asserts the run's NUMBERS. This
    # checker is wired into the umbrella that runs on every compliance check,
    # and the roots it walks hold the whole run — a tree scan on every
    # invocation to answer a question no document asked is a cost nobody
    # asked for either.
    newest_m, newest_p = _newest_evidence(project) if tally else (None, None)
    try:
        doc_m: Optional[float] = result_md.stat().st_mtime
    except OSError:
        doc_m = None
    summary["result_md_mtime"] = doc_m
    summary["newest_evidence"] = newest_p
    summary["newest_evidence_mtime"] = newest_m
    if (tally and doc_m is not None and newest_m is not None
            and newest_m - doc_m > _STALE_GRACE_S):
        failures.append(
            f"RESULT_MD_STALE_VS_EVIDENCE — RESULT.md quotes a compliance "
            f"tally (PASS={tally.group(1)} FAIL={tally.group(2)} "
            f"MISSING={tally.group(3)}) and was written "
            f"{int(newest_m - doc_m)}s BEFORE the newest artefact in the "
            f"evidence it sits in ({newest_p}). It is reporting a different "
            f"round than the one this directory now holds, and a reader sent "
            f"to this directory reads that round's numbers as this round's. "
            f"Regenerate it against this tree or remove it — an evidence "
            f"directory must not contain a document that contradicts its own "
            f"evidence."
        )

    # ── (b) a digest quoted as proof must recompute in THIS tree ─────────
    # The citation rule below checked that a 64-hex string was PRESENT. It
    # never compared it to the artefact it names, so a digest copied from any
    # other run satisfied it. Recompute and compare.
    cited = ((_AUDIT_SHA_RE.search(text) or _AUDIT_SHA_GENERIC_RE.search(text))
             if is_run_tree else None)
    if cited:
        cited_sha = cited.group(1).lower()
        audit_json = _find_audit_json(project)
        summary["audit_json_in_tree"] = (
            str(audit_json.relative_to(project)) if audit_json else None)
        if audit_json is None:
            failures.append(
                f"RESULT_MD_AUDIT_SHA_UNVERIFIABLE — RESULT.md cites "
                f"audit sha {cited_sha[:16]}… and this tree carries no "
                f"`phase23_completion_audit.json` to compare it against. A "
                f"digest quoted as proof of a run must be recomputable from "
                f"that run's own tree."
            )
        else:
            actual = hashlib.sha256(audit_json.read_bytes()).hexdigest()
            summary["audit_sha_actual"] = actual
            if not actual.startswith(cited_sha) and \
                    not cited_sha.startswith(actual):
                failures.append(
                    f"RESULT_MD_AUDIT_SHA_MISMATCH — RESULT.md cites audit "
                    f"sha {cited_sha} while "
                    f"{audit_json.relative_to(project)} in THIS tree digests "
                    f"to {actual}. The reported digest and the reported run "
                    f"are not the same thing: the citation was produced by a "
                    f"different run."
                )

    # Wave 36 — combine chip-agnostic defaults with per-project
    # signature regexes (if any).
    claims_re = _build_claims_re(project)
    claims_pass = bool(claims_re.search(text))
    summary["claims_pass"] = claims_pass

    if not claims_pass:
        # RESULT.md exists but does not claim a PASS — agent is being
        # honest about a FAIL outcome. SKIP.
        summary["skip_reason"] = (
            "RESULT.md does not claim Phase 2+3 PASS or a successful "
            "burn — provenance citation is not required for a FAIL "
            "report"
        )
        return failures, warnings, summary

    # Citation a — audit_sha256 (or `phase23_completion_audit.json`
    # accompanied by a SHA hex on the same / nearby line).
    audit_sha = None
    m = _AUDIT_SHA_RE.search(text)
    if m:
        audit_sha = m.group(1)
    else:
        m2 = _AUDIT_SHA_GENERIC_RE.search(text)
        if m2:
            audit_sha = m2.group(1)
    summary["audit_sha_present"] = bool(audit_sha)
    summary["audit_sha"] = audit_sha

    # Citation b — program response / burn provenance reference + a
    # success indicator nearby.
    has_program_ref = bool(_PROGRAM_RESPONSE_RE.search(text))
    has_program_success = bool(_PROGRAM_SUCCESS_RE.search(text))
    summary["program_response_referenced"] = has_program_ref
    summary["program_response_success_marker"] = has_program_success

    # Citation c — audit_verdict explicitly PASS or PASS_WITH_WAIVERS.
    verdict_m = _AUDIT_VERDICT_RE.search(text)
    quoted_m = _VERDICT_QUOTED_RE.search(text)
    audit_verdict_ok = bool(verdict_m or quoted_m)
    audit_verdict_value = (
        (verdict_m.group(1) if verdict_m else None)
        or (quoted_m.group(1) if quoted_m else None)
    )
    summary["audit_verdict_present"] = audit_verdict_ok
    summary["audit_verdict_value"] = audit_verdict_value

    if not audit_sha:
        failures.append(
            "RESULT_MD_MISSING_AUDIT_SHA — RESULT.md claims a "
            "successful burn / Phase 2+3 PASS but does not cite the "
            "SHA-256 of `phase23_completion_audit.json`. Add a line "
            "like `audit_sha256: sha256:<64-hex>` (or the full "
            "`reports/burn_provenance.json` block emitted by "
            "device_fpga_de10lite_program / eda_fpga_program). "
            "Without it the burn is not provenance-backed."
        )
    if not (has_program_ref and has_program_success):
        failures.append(
            "RESULT_MD_MISSING_PROGRAM_RESPONSE — RESULT.md does not "
            "cite the mcp-eda program-tool response (or "
            "`burn_provenance.json`) carrying a PASS-class "
            "`error_code` / `success: true` / `guard_invoked: true`. "
            "The Wave 33 burn guard refuses to burn when the audit "
            "JSON verdict is FAIL, so any successful burn implies a "
            "specific tool response — paste it (or the provenance "
            "JSON path)."
        )
    if not audit_verdict_ok:
        failures.append(
            "RESULT_MD_MISSING_AUDIT_VERDICT — RESULT.md does not "
            "cite `audit_verdict: PASS` (or `PASS_WITH_WAIVERS`). "
            "If the audit JSON's verdict was actually FAIL, this "
            "RESULT.md is fabrication — the burn guard would have "
            "refused. Include the verdict value verbatim."
        )

    summary["failures"] = list(failures)
    return failures, warnings, summary


def main(argv: List[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(
            "Usage: result_md_audit_provenance_check.py "
            "<project_dir> [--json <out>]"
        )
        return 0 if (len(argv) >= 2 and argv[1] in ("-h", "--help")) \
            else 2

    project = Path(argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    json_out: Optional[Path] = None
    if "--json" in argv:
        idx = argv.index("--json")
        if idx + 1 < len(argv):
            json_out = Path(argv[idx + 1])

    failures, warnings, summary = inspect(project)
    is_waived, rationale = _waived(project)

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps({
            "program": "result_md_audit_provenance_check",
            "passed": not failures,
            "warnings": warnings,
            "summary": summary,
            "failures": failures,
            "waived": is_waived,
        }, indent=2))

    if "skip_reason" in summary and not failures and not warnings:
        print(f"SKIP — {summary['skip_reason']}")
        return 0

    if not failures and not warnings:
        verdict = summary.get("audit_verdict_value", "PASS")
        print(
            f"PASS — RESULT.md cites audit_sha256, program_response, "
            f"and audit_verdict={verdict}. Provenance verifiable."
        )
        return 0

    if not failures and warnings:
        for w in warnings:
            print(f"WARN — {w}")
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        for fmsg in failures:
            print(f"  • {fmsg}")
        return 0

    print(f"FAIL — {len(failures)} RESULT.md provenance gap(s):")
    for fmsg in failures:
        print(f"  • {fmsg}")
    print()
    print("Why this matters:")
    print(
        "  The Wave 33 burn guard (mcp-eda v0.99.9) refuses to burn\n"
        "  when phase23_completion_audit.json reports verdict=FAIL.\n"
        "  Therefore a RESULT.md claiming a successful burn / Phase\n"
        "  2+3 PASS implies (a) an audit JSON with verdict=PASS, (b)\n"
        "  a guarded program-tool response with success=true, and (c)\n"
        "  a SHA-256 the agent computed against the audit JSON they\n"
        "  cite. Missing any of the three indicates either an\n"
        "  unguarded burn (closed in Wave 33) or RESULT.md\n"
        "  fabrication."
    )
    print()
    print("Fix recipe:")
    print(
        "  Append a `## Burn provenance` block citing the three\n"
        "  values, OR copy `<project>/reports/burn_provenance.json`\n"
        "  verbatim into RESULT.md. The mcp-eda burn-tool response\n"
        "  contains all three already."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
