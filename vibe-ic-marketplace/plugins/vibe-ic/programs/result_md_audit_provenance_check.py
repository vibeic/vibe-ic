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
import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
# The gate that RENDERS a testbench into the project declares which paths it
# regenerates; this program must not restate them (see _FLOW_REGENERATED_PATHS).
import fmeda_fault_injection_coverage as _fmeda  # noqa: E402

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
# `PASS` used as an ASSERTION that something passed.
#
# The flow's own verdict vocabulary contains compounds that carry the token
# while asserting the OPPOSITE of a pass:
#
#   VACUOUS-PASS   the gate ran and found nothing applicable.
#                  flow_compliance_check excludes it from the executed-PASS
#                  count in the very line it prints it on.
#   PASS-VOIDED    a pass withdrawn because a dependency failed
#                  (_flow_verdict_tiers).
#
# Both appear in the tally line a RESULT.md is expected to quote VERBATIM as
# its evidence, so matching the bare token inside them reads an honest FAIL
# report as a claim of success — and then demands burn provenance for a burn
# the same document says never happened. Measured on a report whose text was
# `absent FPGA hardware; 1 VACUOUS-PASS (FS1 FMEDA)`: `hardware` and `PASS`
# fell within the 40-character window, from two unrelated clauses.
#
# Scope: this excludes the DISQUALIFYING COMPOUNDS only. The `[^\n]{0,40}`
# adjacency windows below are still adjacency tests, not claim parsers — a
# bare `PASS` from an unrelated clause inside the window still matches, and
# closing that would require reading the sentence rather than the span.
_PASS_CLAIM = r"(?<!VACUOUS-)(?<!NON-)(?<!NOT-)\bPASS\b(?!-VOID)"

_CLAIMS_PASS_PATTERNS = (
    r"\bPHASE\s*2\s*\+\s*3\b[^\n]{0,40}" + _PASS_CLAIM,
    r"\bsof[^\n]{0,40}\bsuccess\b",
    r"\bburn[^\n]{0,40}\b(?:success|completed|verified)\b",
    r"\bSOF[^\n]{0,40}\bprogrammed\b",
    r"\bhardware[^\n]{0,40}" + _PASS_CLAIM,
    r"\boverall\s*verdict\s*[:=]\s*" + _PASS_CLAIM,
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


# ---------------------------------------------------------------------------
# Self-reference guard — this program's OWN output is not a claim BY the report
# ---------------------------------------------------------------------------
# The diagnostics below quote the very tokens they detect. The SKIP line reads
# "RESULT.md does not claim <phase-2+3 success token> or a successful burn",
# and the first failure line reads "RESULT.md claims a successful burn /
# <same token> but does not cite ...".
#
# The anti-fabrication doctrine tells an agent to quote a tool's own output
# verbatim as evidence. Doing exactly that flips this gate on a report whose
# verdict line is FAIL: pasting the SKIP sentence into the report and re-running
# the gate over the SAME project turns `SKIP` / exit 0 into
# `FAIL — 3 provenance gap(s)` / exit 1, with nothing else changed.
#
# That is the failure mode this program exists to prevent, pointed at itself:
# the cheapest way to clear the new FAIL is to paste a burn SHA-256 and an
# `audit_verdict: PASS` into a report about a burn that never happened. A rule
# meant to make reports verifiable rewards making them falsely verifiable.
#
# SCOPE, deliberately narrow: exact-sentence removal of text THIS PROGRAM
# emits, and nothing else. Every pass claim outside these sentences still
# matches, so the guard cannot be used to hide one — quoting our SKIP line buys
# a fabricator nothing, because their own claim text is untouched. Matching is
# whitespace-flexible so a hard-wrapped quotation is still recognised.
_SELF_EMITTED_SENTENCES = (
    # Current wording (post-fix).
    "does not claim a successful Phase 2+3 outcome or a successful burn",
    "claims a successful burn / a successful Phase 2+3 outcome but does not "
    "cite the SHA-256",
    # Pre-fix wording, retained so a RESULT.md already written against an
    # older plugin is still read correctly rather than newly reddened.
    "does not claim Phase 2+3 PASS or a successful burn",
    "claims a successful burn / Phase 2+3 PASS but does not cite the SHA-256",
)

_SELF_EMITTED_RES = tuple(
    re.compile(r"\s+".join(re.escape(w) for w in s.split()), re.IGNORECASE)
    for s in _SELF_EMITTED_SENTENCES
)


#: The compliance tally a RESULT.md is asked to quote VERBATIM. Quoting it is
#: CITING the gate's output, not asserting a pass — the same reason this file
#: already blanks its own diagnostic sentences before the claim scan.
#:
#: MEASURED (#832): a report quoting `PASS=148 FAIL=3 MISSING=0` was read as
#: claiming a pass and returned rc=1, while three neighbouring shapes had
#: already been closed. The tally cannot be a pass claim by construction here —
#: it carries `FAIL=3` in the same breath — so reading it as one contradicts
#: the doctrine that asked for the quote.
_QUOTED_TALLY_RE = re.compile(
    r"PASS\s*=\s*\d+\s+FAIL\s*=\s*\d+\s+MISSING\s*=\s*\d+[^\n]*", re.I)


def _strip_self_emitted(text: str) -> str:
    """Blank out sentences THIS program emits, before scanning for a claim.

    Returns text of the same shape with only our own diagnostic sentences
    replaced by a space. Any other content — including a real pass claim
    sitting next to a quoted diagnostic — is left untouched.
    """
    for rx in _SELF_EMITTED_RES:
        text = rx.sub(" ", text)
    # A quoted tally is evidence the report cites, never a claim it makes.
    text = _QUOTED_TALLY_RE.sub(" ", text)
    return text


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
#: THE COMPLIANCE FLOW'S OWN OUTPUT — excluded from the freshness reference.
#:
#: The umbrella compliance check and its sub-checkers (re)write their gate and
#: audit DOCUMENTS on EVERY invocation, so the newest mtime under them advances
#: each run. A freshness judge must not read the documents IT regenerates as "a
#: newer round of the design": doing so made this gate's verdict depend on how
#: many times the gate had been run — PASS on run 1, FAIL(STALE) on run 2 and
#: after, on a tree nobody had touched in between.
#:
#: WHAT THE FLOW ACTUALLY WRITES — GROUND TRUTH, NOT INFERENCE.
#: `flow_compliance_check.py` run on an untouched copy of two real completed
#: run trees, censusing (mtime, size, md5) of EVERY file between runs::
#:
#:     ic/subservient  (369 files, 2 runs)   70 moved  .json 67  .md 3
#:         outside reports/                   0
#:         under reports/phase3/              9  (antenna_signoff, dfm_screen,
#:                                               drc_vacuous, em_signoff,
#:                                               foundry_handoff_audit,
#:                                               ir_drop_signoff, sta/*.json)
#:     ic/opentitan_aes (514 files, 1 run)   40 moved  .json 35  .md 3  .v 1  .vvp 1
#:         outside reports/                   2  phase2/stage2/safety/
#:                                               fmeda_fi_tb.v{,.vvp}
#:
#: THREE THINGS THAT CENSUS REFUTES, EACH OF WHICH WAS A CANDIDATE RULE:
#:
#:   1. "the flow writes nothing outside `reports/`" — FALSE. The fMEDA
#:      fault-injection gate renders its testbench into
#:      `phase2/stage2/safety/` and compiles it there on every run, so
#:      `phase2/` — explicitly in scope — carried the run-count-dependent
#:      verdict on `ic/opentitan_aes` (STALE=False before a re-run,
#:      STALE=True after, newest=`…/fmeda_fi_tb.v.vvp`, one fixed point over
#:      20 re-runs). Rule 3 below closes it, from the WRITER'S declaration.
#:   2. "a gate verdict document is identifiable by a top-level `program`
#:      key" — FALSE. Of the 35 flow-written JSONs on `ic/opentitan_aes`,
#:      only 10 carry one; 25 carry neither `program` nor `tool`
#:      (`nba_addr_race.json`, `bit_level_full_stack.json`, …). A content
#:      rule in that direction leaves 25 flow documents in the reference.
#:   3. "exempt `reports/phase3/**`" — FALSE. The flow writes 9 `.json`
#:      there on `ic/subservient`. That exemption reinstates the defect.
#:
#: SO THE EXCLUSION IS PATH-AND-SUFFIX, WHICH THE CENSUS SHOWS IS COMPLETE FOR
#: THE FLOW-OUTPUT DIRECTION (every one of the 110 measured rewrites is a
#: `.json`/`.md` under `reports/`, or one of the two declared fMEDA files) —
#: and the FALSE-POSITIVE direction is repaired by a narrow, SOUND rescue
#: (`_is_tool_measurement`) rather than by widening a hole in the exclusion.
#:
#:   * `reports/audit/` — the flow's own audit bucket. `_path_layout.
#:     report_path` files every unrecognised report name here, and it is where
#:     `phase23_completion_audit.json` and the `flow_compliance_check.log`
#:     transcript land. Measured: 0 of the corpus's tool-measurement documents
#:     live under it.
#:   * `.json` / `.md` anywhere under `reports/` — gate and audit documents,
#:     UNLESS the document identifies itself as an EDA tool's measurement.
#:   * the paths the compliance gates regenerate outside `reports/`, as
#:     declared by the gate that writes them.
#:
#: EVERYTHING ELSE STAYS IN SCOPE, INCLUDING TOOL REPORTS UNDER `reports/`.
#: `reports/phase3/drc_signoff.rpt` (phase3_one_shot_runner.py:22567, :28296)
#: and `reports/phase3/lvs.rpt` (:24241, :24705) are DESIGN-round sign-off
#: written by the tools and never re-stamped by the flow. Excluding all of
#: `reports/` — the first shape of this fix — made a sign-off-only re-run
#: invisible: it moves only `reports/` mtimes, so a stale RESULT.md beside it
#: went unseen. That is the founding failure shape this rule exists to catch,
#: so the wide exclusion disarmed the rule on its own motivating case::
#:
#:     case                                       wide excl.   this
#:     reports/phase3/drc_signoff.rpt newer       pass         FAIL(STALE)
#:     reports/phase3/lvs.rpt newer               pass         FAIL(STALE)
#:     reports/phase3/metal_density.json newer    pass         FAIL(STALE)
#:     reports/audit/*.json re-stamped by flow    pass         pass
#:     phase2/…/fmeda_fi_tb.v.vvp re-stamped      FAIL(STALE)  pass
#:
#: NOTE ON A CLAIM THIS REPLACES: the first shape of this change said the
#: reference was "phase1/2/3 + root" and that the flow "does not mutate the
#: project root". The walked set was `('phase1','phase2','phase3')` — the root
#: was never walked, then or now. Only `_EVIDENCE_ROOTS` are walked.
#: Sub-paths under `reports/` that hold the compliance flow's own regenerated
#: documents.
_FLOW_OUTPUT_SUBTREES = ("reports/audit",)
#: Suffixes that make a file under `reports/` a gate/audit DOCUMENT rather than
#: a tool artefact.
_FLOW_OUTPUT_SUFFIXES = (".json", ".md")
#: The root under which the two rules above apply.
_FLOW_OUTPUT_ROOT = "reports"
#: Project-relative paths OUTSIDE `reports/` that a compliance gate regenerates
#: on every run — taken from the GATE THAT WRITES THEM, not restated here, so
#: the two cannot drift apart. `fmeda_fault_injection_coverage` renders its
#: injection testbench into `phase2/stage2/safety/` and compiles it there,
#: which is why `phase2/` being "a design-round tree the flow never writes to"
#: was false.
_FLOW_REGENERATED_PATHS = frozenset(_fmeda.REGENERATED_PROJECT_PATHS)
#: Top-level keys that make a JSON document a GATE VERDICT rather than a tool
#: measurement. A gate names the program that produced it; when that name
#: resolves to a file in this plugin's `programs/` directory the document is
#: the flow's own, whatever else it carries. MEASURED, the collision this
#: catches: `reports/phase3/sta/hold_corner_coverage.json` is rewritten every
#: run AND carries `"tool": "hold_corner_coverage_check"` — the gate's own
#: name in the field an EDA tool would put `openroad` in.
_PRODUCER_NAME_KEYS = ("tool", "program", "gate", "generated_by", "checker",
                       "rule")
_PROGRAMS_DIR = Path(__file__).resolve().parent
#: A document written within this many seconds of the newest artefact is part
#: of the same round. Generous on purpose: the rule must fire on a stale
#: ROUND, never on the ordinary case of writing the report a few minutes after
#: the run that produced the artefacts.
_STALE_GRACE_S = 3600


def _names_a_flow_program(v) -> bool:
    """True when `v` names one of this plugin's own gate programs."""
    if not isinstance(v, str):
        return False
    stem = v.strip().split(":")[0].split()[0]
    return bool(stem) and (_PROGRAMS_DIR / f"{stem}.py").is_file()


def _is_tool_measurement(p: Path) -> bool:
    """True when a `.json` under `reports/` is an EDA TOOL's measurement, and
    so dates the DESIGN round even though it is a document by suffix.

    THE ONE PLACE CONTENT IS CONSULTED, AND IT IS CONSULTED IN THE SAFE
    DIRECTION. The path+suffix exclusion is measured COMPLETE for flow output
    (110 rewrites over two real trees, every one of them a `.json`/`.md` under
    `reports/` or a declared fMEDA path), so widening it is never needed and
    narrowing it is where the risk is. This predicate can only RESCUE a file
    into the reference, and it is deliberately conservative:

      * the document must carry a top-level `"tool"` STRING — the field an EDA
        tool's own emitter fills (`openroad`, `opensta`, `klayout`, `yosys`,
        `verilator`, `iverilog`); and
      * NONE of its producer-name fields may name a program in this plugin's
        `programs/` directory, which is what a gate document does.

    MEASURED against the ground-truth rewrite sets: 0 of the 110 files the
    flow rewrites are rescued (the one document that would have been —
    `hold_corner_coverage.json`, `"tool": "hold_corner_coverage_check"` — is
    vetoed by the second clause). Corpus-wide it rescues 161 tool measurements
    over 26 trees, including the 11 on `ic/sha256/clean_run_v1427_20260715`
    that carried the regression this repairs (`reports/phase3/
    metal_density.json` re-emitted alone, STALE no longer detected) and the 10
    on `ic/sha256/clean_run_v1461_0223`, a results-only clean-room re-run with
    no phase directories at all, which the suffix rule alone left with ZERO
    datable artefacts.
    """
    if p.suffix.lower() != ".json":
        return False
    try:
        d = json.loads(p.read_text(errors="replace"))
    except Exception:
        return False
    if not isinstance(d, dict):
        return False
    if not isinstance(d.get("tool"), str) or not d["tool"].strip():
        return False
    return not any(_names_a_flow_program(d.get(k))
                   for k in _PRODUCER_NAME_KEYS)


def _is_flow_output(rel: str, path: Optional[Path] = None) -> bool:
    """True when a project-relative path is something the COMPLIANCE FLOW
    regenerates, and so cannot date the DESIGN round.

    Three rules, all measured (see `_FLOW_OUTPUT_SUBTREES`): anything under
    the flow's own audit bucket; any gate/audit document (`.json` / `.md`)
    under `reports/` that is not an EDA tool's own measurement; and the paths
    the compliance gates regenerate outside `reports/`, as declared by the
    gate that writes them. Everything else — every tool sign-off report, and
    the rest of `phase1/`, `phase2/`, `phase3/` — dates the design round.
    """
    rel = rel.replace(os.sep, "/")
    if rel in _FLOW_REGENERATED_PATHS:
        return True
    for sub in _FLOW_OUTPUT_SUBTREES:
        if rel == sub or rel.startswith(sub + "/"):
            return True
    head = rel.split("/", 1)[0]
    if head != _FLOW_OUTPUT_ROOT or not rel.endswith(_FLOW_OUTPUT_SUFFIXES):
        return False
    return not (path is not None and _is_tool_measurement(path))


def _newest_evidence(project: Path) -> Tuple[Optional[float], Optional[str]]:
    """`(mtime, path)` of the newest DESIGN-round artefact.

    Walks every one of `_EVIDENCE_ROOTS` and skips only what `_is_flow_output`
    identifies as the compliance flow's own regenerated document. Including the
    flow's output made this gate's verdict depend on the run count (PASS on run
    1, FAIL on run 2+); excluding the whole of `reports/` instead removed the
    design round's own tool sign-off reports from the reference, which disarmed
    the rule on a sign-off-only re-run — the shape it exists to catch.

    Returns `(None, None)` when the tree holds no design-round artefact at all.
    That is an ABSTENTION, not a finding, and the caller must disclose it as
    one: "I could not look" must never be rendered as "there is nothing there".
    """
    newest: Optional[float] = None
    newest_p: Optional[str] = None
    for root in _EVIDENCE_ROOTS:
        d = project / root
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            try:
                rel = str(p.relative_to(project))
            except ValueError:
                continue
            if _is_flow_output(rel, p):
                continue
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if newest is None or m > newest:
                newest, newest_p = m, rel
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
    # ── the abstention must GATE, not merely be visible ──────────────────
    # `newest_evidence: null` alone reads as "there is nothing there", which
    # is a claim about the tree. When the document asserts the run's numbers
    # and this IS a run tree, a null reference means the opposite: the rule
    # could not find anything to date the round against, so it did not judge.
    # Silently returning null let the gate keep jurisdiction (`is_run_tree`
    # still true) while the STALE rule could never fire — a rule that cannot
    # fail, reported as a rule that passed.
    #
    # AND SAYING SO IS NOT ENOUGH. Disclosing it in `warnings` changed
    # nothing a consumer can see: `main()` returns rc 0 for warnings and
    # writes `"passed": true`, and the ONLY automated consumer —
    # `flow_compliance_check.__check_program_exit_zero` — is rc-ONLY (rc 0
    # PASS, rc 2 VACUOUS_PASS, rc 3+sentinel PASS_WITH_WAIVERS, else FAIL).
    # Nothing anywhere reads `warnings` or `freshness_evaluated`, so
    # `freshness_evaluated: false` was consumed as a plain PASS — the same
    # false green, now with a paper trail. It is a FAILURE, on the umbrella's
    # own doctrine that an unevaluated gate cannot pass (`__check_program_
    # exit_zero`: "a timeout is NOT a verdict … INCONCLUSIVE (still FAILs the
    # audit — an unevaluated gate cannot pass)"). The waiver remains the
    # escape hatch for a tree that legitimately has nothing to date.
    if tally and is_run_tree and newest_m is None:
        summary["freshness_evaluated"] = False
        summary["freshness_abstain_reason"] = (
            "no design-round artefact found: every file under the evidence "
            "roots is a document the compliance flow regenerates "
            f"(under {'/, '.join(_FLOW_OUTPUT_SUBTREES)}/, a "
            f"{'/'.join(_FLOW_OUTPUT_SUFFIXES)} under "
            f"{_FLOW_OUTPUT_ROOT}/ that is not an EDA tool's own measurement, "
            f"or a path a compliance gate regenerates)")
        failures.append(
            "RESULT_MD_FRESHNESS_NOT_EVALUATED — RESULT.md quotes a "
            f"compliance tally (PASS={tally.group(1)} FAIL={tally.group(2)} "
            f"MISSING={tally.group(3)}) and this IS a run tree, but nothing "
            "in it dates the design round: every file under the evidence "
            "roots is a document the compliance flow rewrites on every run. "
            "The staleness rule did NOT evaluate — this is an ABSTENTION, "
            "not a clean bill, and an unevaluated gate cannot pass. A tree "
            "whose only artefacts are the flow's own reports cannot "
            "substantiate the round the document reports."
        )
    elif tally and is_run_tree:
        summary["freshness_evaluated"] = True
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
    # Scan with this program's own diagnostic sentences blanked out: a report
    # QUOTING our verdict is citing evidence, not making the claim the quoted
    # sentence describes. See _strip_self_emitted.
    claims_pass = bool(claims_re.search(_strip_self_emitted(text)))
    summary["claims_pass"] = claims_pass

    if not claims_pass:
        # RESULT.md exists but does not claim a PASS — agent is being
        # honest about a FAIL outcome. SKIP.
        # Wording note: this sentence must NOT contain the token pair its own
        # pattern detects, or quoting it re-triggers the gate.
        summary["skip_reason"] = (
            "RESULT.md does not claim a successful Phase 2+3 outcome or a "
            "successful burn — provenance citation is not required for a "
            "FAIL report"
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
            # Wording note: as with the SKIP line above, this sentence must
            # NOT contain the token pair its own pattern detects.
            "RESULT_MD_MISSING_AUDIT_SHA — RESULT.md claims a "
            "successful burn / a successful Phase 2+3 outcome but does "
            "not cite the "
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
        # Wording note: this explanatory block is printed on every FAIL and
        # is routinely pasted into a report as evidence, so — like the SKIP
        # and failure lines — it must not contain the token pair the gate's
        # own pass-claim pattern detects.
        "  The Wave 33 burn guard (mcp-eda v0.99.9) refuses to burn\n"
        "  when phase23_completion_audit.json reports verdict=FAIL.\n"
        "  Therefore a RESULT.md claiming a successful burn or a\n"
        "  successful Phase 2+3 outcome implies (a) an audit JSON\n"
        "  with verdict=PASS, (b)\n"
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
