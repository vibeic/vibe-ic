#!/usr/bin/env python3
"""DRC report check — wrapper for eda_report_audit --mode drc.

TWO flow steps declare this program, and BOTH declare a ``--json`` audit path:

    Step 21 (routing)   drc_report_check . --mode drc --json reports/phase3/drc_router.json
    Step 31 (PV)        drc_report_check . --mode drc --json reports/phase3/drc_signoff.json

#490 — THE ARGV WAS DISCARDED ENTIRELY, so neither audit was ever written. The
old body was one line::

    sys.exit(main([sys.argv[1] if len(sys.argv) > 1 else ".", "--mode", "drc"]))

The list literal has no ``*passthrough``: every token after the first was
dropped on the floor. ``--json`` never reached ``eda_report_audit``, so the
DRC sign-off audit trail was never produced on any run.

MEASURED, before anything was changed, on a clean fixture project (a
tool-authentic KLayout report with a real ``total violations: 0``)::

    $ drc_report_check.py proj --mode drc --json out/drc_signoff.json
    rc=0                                  # gate GREEN
    $ ls out/drc_signoff.json
    No such file or directory             # and NO audit trail at all

and across the tracked corpus — 119 project snapshots under ``benchmark-data/``
— ``reports/phase3/drc_signoff.json`` appears **0** times and
``reports/phase3/drc_router.json`` **0** times, against 9 tracked
``reports/phase3/lvs.json`` and 28 tracked ``reports/phase3/sta*`` as controls.
The file has never been written, not "sometimes missing".

WHY THAT MATTERS BEYOND A MISSING FILE — a step that declares an output and
then exits 0 without producing it hands the tapeout checklist "there is no such
evidence" where it should hand it "the evidence says X". Those read completely
differently to a reviewer, and only one of them is true.

TWO FURTHER VECTORS THIS SHAPE CARRIED, both measured on the same fixture:

* ``--mode=power`` / ``--mode power`` from a caller were SILENTLY DISCARDED. A
  DRC audit was run and rc 0 returned with nothing said about the mode the
  caller actually asked for. That is the mirror image of #489's defect (where
  the caller's mode was silently HONOURED): both answer a question nobody
  asked, and neither says so.
* ``--json <path> <proj>`` — the ``--json`` value landing where the wrapper
  expected the project dir — reached argparse as ``["--json", "--mode", "drc"]``
  and exited **2**. rc 2 is credited by
  ``flow_compliance_check._check_program_exit_zero`` as a VACUOUS_PASS,
  returning ``passed=True`` UNCONDITIONALLY, so a command line argparse itself
  REJECTED turned the Step-21 and Step-31 DRC gates GREEN with no DRC audited.

WHAT REPLACES IT — the split now comes from the shared, value-aware
``_report_check_argv`` helper landed by #489 (a per-wrapper hand-rolled
splitter is exactly how this defect propagated across the family; this is an
adoption, not a fourth copy), plus the sign-off policy this domain owes:

* Both ``--mode drc`` and ``--mode=drc`` pin the drc audit.
* Any OTHER mode — either spelling, and a valueless ``--mode`` too — is
  REFUSED with a stated reason. Nothing is certified and the refusal is
  written to the declared ``--json`` path, so the artefact says why.
* The audit is ALWAYS emitted when ``--json`` is declared: if
  ``eda_report_audit`` could not write it, this wrapper writes it from the
  payload it captured; if even that fails, the run exits non-zero and SAYS the
  audit was not written.
* A PASS must disclose its denominator: rc 0 is re-checked against the audit's
  own ``summary.files_found`` and the disclosure — files found, how many of
  them yielded a determinable violation count, and the real violation total —
  is printed to STDERR.
* NO exit path returns 2. argparse's own rejections are caught and turned into
  rc 1.

WHY REFUSALS EXIT 1 AND NOT 2 — rc 2 is the repo's general "input does not
apply, NOT CHECKED" contract, and it is the wrong answer here for a mechanical
reason: ``_check_program_exit_zero`` credits rc 2 as a VACUOUS_PASS and returns
``passed=True`` unconditionally (unlike rc 3, which additionally requires a
stdout sentinel). A refusal exiting 2 would turn Steps 21 and 31 GREEN — a
cheaper false certificate than the one this change closes. A refused DRC
sign-off is not "this project has no DRC to check"; it is "nothing was
certified", which on a blocking gate is a FAIL. The unconditional rc-2 credit
is a separate defect with its own blast radius and is reported separately.

STDOUT IS THE AUDIT JSON AND NOTHING ELSE. Every disclosure goes to stderr,
which ``_check_program_exit_zero`` also captures into its evidence snippet.

``--signoff`` — THE SIGN-OFF SCOPE (this is a TIGHTENING; read the numbers)
--------------------------------------------------------------------------
Step 31 is the PHYSICAL-VERIFICATION sign-off. Step 21 is the router's own DRC.
They share this program and they must not share this policy, because the
producer that is exactly right for one is disqualifying for the other.

MEASURED on ``origin/main``, on a project containing ZERO GDS files, whose
``reports/phase3/drc_signoff.rpt`` is a 19,162-byte OpenROAD ``detailed_route``
projection re-staged by the runner's own alias writer::

    drc_report_check . --mode drc --under reports/phase3/drc_signoff.rpt
        -> rc=0   passed:true  tool_authentic:true
                  determined_files:1  real_violation_total:0

That is a sign-off DRC certificate issued by the router over a layout that was
never streamed. ``--signoff`` refuses it, on two independent grounds:

* THE PRODUCER. A sign-off DRC verdict is a RULE DECK applied to a LAYOUT.
  Accepted: a KLayout report database that names its deck in ``<generator>``;
  an SVRF-native per-rule tally (the foundry's own deck); a Magic DRC
  transcript. Refused: the router's detailed-route projection
  (``DRC_SIGNOFF_PRODUCER_NOT_A_SIGNOFF_DECK``) and anything with no
  recognised producer signature (``DRC_SIGNOFF_PRODUCER_UNRECOGNISED``).
* THE LAYOUT. ``summary.layout_evidence_tier`` is one of ``invocation`` (a
  measured tool run naming the streamout), ``declared`` (a provenance
  declaration of it), ``on_disk``, or ``none``. ``none`` is
  ``DRC_SIGNOFF_NO_LAYOUT_EVIDENCE`` and rc 1. The tier is DISCLOSED even when
  it passes, because "declared" and "measured" are very different claims and a
  reader is entitled to know which one this run earned.

``--signoff`` is consumed by THIS WRAPPER and never forwarded: ``eda_report_
audit`` has no such option and would ``SystemExit(2)`` on it — measured, the
wrapper then reports NOT CHECKED and the gate goes red on every project. The
anti-drift test that derives ``VALUE_FLAGS`` from that program's real parser
(``value_taking <= set(VALUE_FLAGS)``) is a SUBSET assertion and cannot catch a
wrapper-only flag, so the strip is explicit here and pinned by its own test.

BLAST RADIUS, measured over every published run carrying the Step-31 artefact
(13 project roots; the extraction reads git objects, never a working tree):
**0**. The 6 runs green on this gate today stay green — each is a KLayout
report database naming a PDK deck, and each reaches layout tier ``invocation``
or ``declared``. The one run at tier ``none`` is already rc 1 today.

WIRING — Steps 21 and 31 invoke this program in ``gate.all_of`` and a non-zero
exit fails the step. Only Step 31 passes ``--signoff``. No ``ENFORCEMENT:``
intent line is declared, and that is
deliberate rather than an oversight: ``flow_gate_enforcement_audit`` classifies
a gate as ENFORCED only when a one-shot runner invokes it INLINE, and
``phase3_one_shot_runner._DECLARED_SIGNOFF_GATES`` carries ``sta_report_check``
and ``em_report_check`` but NOT this one (nor ``lvs_report_check``). Measured:
the audit reports this gate as AUDIT_ONLY. So the DRC gate stops a run only
when the compliance audit runs it, not during the run itself. Claiming
blocking here would be a contradiction the audit correctly exits 1 on — the
claim is the thing that would be wrong, not the audit.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _signoff_drc_format as _sdf  # noqa: E402
import _die_level_attribution_consult as _dlac  # noqa: E402
import die_level_deck_rule_attribution as _dla  # noqa: E402
from _report_check_argv import json_target, split_and_pin  # noqa: E402
from eda_report_audit import main as _audit_main  # noqa: E402

MODE = "drc"

#: Options this WRAPPER owns. They are stripped from the passthrough before the
#: audit sees them: `_report_check_argv._split` forwards every unrecognised
#: option verbatim, and `eda_report_audit`'s parser rejects an unknown one with
#: `SystemExit(2)`, which this wrapper maps to "NOT CHECKED", rc 1 — an outage
#: on every project rather than a policy. Boolean only; a value-taking wrapper
#: option would additionally need `_report_check_argv.VALUE_FLAGS`.
WRAPPER_FLAGS = ("--signoff",)

#: Wrapper-owned options that TAKE A VALUE, repeatable. Each names a report
#: path (project-relative) that this invocation asserts MUST EXIST. Registered
#: in `_report_check_argv.VALUE_FLAGS` too, or the splitter would read the
#: value as the positional project dir.
#:
#: WHY A DECLARATION IS NEEDED AT ALL. A report can be ABSENT, EMPTY or
#: POPULATED, and those are three different answers: absent means the question
#: could not be put, empty means it was put and the answer is zero, populated
#: means it was put and the answer is whatever it parses to. The audit can
#: tell empty from populated by reading the bytes. It cannot tell ABSENT from
#: "never expected" by itself -- an undiscovered file leaves no trace -- so the
#: caller has to say which reports it required. Without this the two collapse
#: and absence reads as a clean pass.
WRAPPER_VALUE_FLAGS = ("--require-report",)

#: rc contract of this wrapper. 2 is deliberately absent — see the module
#: docstring (``_check_program_exit_zero`` credits rc 2 as a vacuous PASS).
RC_PASS = 0
RC_FAIL = 1


def denominator_of(payload: object) -> tuple:
    """``(ok, files_found, determined_files, real_total)`` for a drc payload.

    A PASS may only stand when the audit can name how many reports it actually
    read. ``_check_drc`` cannot currently return ``passed=True`` with
    ``files_found == 0`` — it returns early on an empty discovery, and its
    ``passed`` additionally requires ``determined_files > 0`` — so this is a
    TRIPWIRE, not a live filter, and its measured blast radius over the 119
    tracked snapshots is 0. It exists because four of the seven sibling modes
    DO have a ``_waived_for_pdk`` path that sets ``passed=True`` with a summary
    carrying no ``files_found`` at all (``power`` / ``em`` / ``ir_drop`` /
    ``antenna``). If ``drc`` ever grows one, a denominator-less PASS on a
    sign-off gate must not slip through unannounced.
    """
    summary = {}
    if isinstance(payload, dict) and isinstance(payload.get("summary"), dict):
        summary = payload["summary"]
    files_found = summary.get("files_found")
    determined = summary.get("determined_files")
    real_total = summary.get("real_violation_total")
    ok = isinstance(files_found, int) and not isinstance(files_found, bool) \
        and files_found >= 1
    return ok, files_found, determined, real_total


def _not_checked_payload(rule: str, message: str, project_dir: str) -> dict:
    """An eda_report_audit-shaped record saying NOTHING was certified.

    Schema-compatible with the audit it replaces (``program`` / ``passed`` /
    ``findings`` / ``summary``) so every downstream reader keyed on ``passed``
    sees ``False``. It can never manufacture a pass.
    """
    return {
        "program": "drc_report_check",
        "audited_program": f"eda_report_audit:{MODE}",
        "passed": False,
        "findings": [{"rule": rule, "severity": "ERROR",
                      "message": message, "file": ""}],
        "summary": {"files_found": 0, "checked": False,
                    "pinned_mode": MODE, "project_dir": project_dir,
                    "terminal_verdict": "NOT_CHECKED"},
    }


def take_wrapper_flags(passthrough) -> tuple:
    """``(flags_present, passthrough_without_them)``.

    Explicit, because the shared splitter forwards every unrecognised option
    verbatim and the wrapped program rejects it with ``SystemExit(2)``. See
    ``WRAPPER_FLAGS``.
    """
    present = {t for t in passthrough if t in WRAPPER_FLAGS}
    return present, [t for t in passthrough if t not in WRAPPER_FLAGS]


def take_required_reports(passthrough) -> tuple:
    """``(required_paths, passthrough_without_them)``.

    Strips `--require-report <path>` pairs. Kept separate from
    `take_wrapper_flags` so that function's `(set, list)` contract -- which
    callers and tests already depend on -- is unchanged.
    """
    required, rest, i = [], [], 0
    toks = list(passthrough)
    while i < len(toks):
        t = toks[i]
        if t in WRAPPER_VALUE_FLAGS:
            if i + 1 < len(toks):
                required.append(toks[i + 1])
                i += 2
                continue
            # A value-taking flag with no value: drop it rather than forward
            # it, and let `required_report_verdict` see an empty list. The
            # caller learns from the audit that nothing was required.
            i += 1
            continue
        if t.startswith(tuple(f"{f}=" for f in WRAPPER_VALUE_FLAGS)):
            required.append(t.split("=", 1)[1])
            i += 1
            continue
        rest.append(t)
        i += 1
    return required, rest


def required_report_verdict(project_dir: str, required) -> tuple:
    """``(findings, summary_additions)`` for reports the caller REQUIRED.

    THE THIRD STATE. `eda_report_audit._check_drc` distinguishes EMPTY from
    POPULATED by reading the file. This distinguishes ABSENT from both, and
    it REFUSES: a required report that does not exist means the question was
    never put, and a gate that reported enforcement over a measurement nobody
    took is the defect this closes.

    BLOCKING. An ERROR finding here is one of the caller's rc-1 reasons; rc 2
    is deliberately not used, because `_check_program_exit_zero` credits rc 2
    as a VACUOUS PASS -- measured on this host 2026-08-30: a gate exiting 2
    is graded `passed=True`. Refusal must therefore spend rc 1.

    An EMPTY required report is NOT a finding here: it exists, so the question
    was put, and `_check_drc` credits it as a zero.

    chip-AGNOSTIC: path existence only; the paths come from the caller.
    """
    findings, absent = [], []
    for rel in required:
        if not (Path(project_dir) / rel).is_file():
            absent.append(rel)
    if absent:
        findings.append({
            "rule": "DRC_REPORT_REQUIRED_ABSENT", "severity": "ERROR",
            "message": (
                f"{len(absent)} report(s) this invocation REQUIRED do not "
                f"exist, so nothing measured what they were to answer -- "
                f"this is NOT an empty report (which is a measured zero) and "
                f"NOT a clean pass: {', '.join(absent)}"),
            "file": absent[0]})
    return findings, {"required_reports": list(required),
                      "required_reports_absent": absent}


def _recorded_layout_evidence(project: Path, producers: list):
    """Bind a report to its measured input bytes, independently of filenames.

    None preserves the legacy evidence path when no invocation binds this report.
    An explicit but invalid binding returns NONE evidence and cannot fall back to
    a coincidentally matching filename. No directory glob supplies an identity.
    """
    from digital_hardmacro_check import gds_top_cells

    project = project.resolve()
    entries = _sdf._prov_entries(project)
    found = []

    def path_for(value):
        path = Path(value)
        path = (path if path.is_absolute() else project / path).resolve()
        path.relative_to(project)  # external paths are not this run's artifacts
        return path

    def digest(path):
        value = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(chunk)
        return "sha256:" + value.hexdigest()

    def invalid(reason):
        return {"tier": _sdf.TIER_NONE, "topcell_match": False, "witness": reason}

    for producer in producers:
        rel = producer.get("file")
        if not rel:
            continue
        try:
            report = path_for(rel)
        except (ValueError, OSError):
            return invalid("report path is outside the project")
        for entry in reversed(entries):
            if entry.get("record") != "invocation":
                continue
            outputs = entry.get("outputs") or {}
            if not isinstance(outputs, dict):
                continue
            bound = []
            for name, expected in outputs.items():
                try:
                    if path_for(name) == report:
                        bound.append(expected)
                except (ValueError, OSError, TypeError):
                    continue
            if not bound:
                continue
            try:
                if entry.get("measured") is not True or entry.get("exit_code") != 0:
                    return invalid("report invocation was not measured successfully")
                if entry.get("tool") != producer.get("producer"):
                    return invalid("report invocation tool differs from report producer")
                if any(expected != digest(report) for expected in bound):
                    return invalid("recorded DRC report hash differs from current report")
                inputs = entry.get("inputs") or {}
                if not isinstance(inputs, dict):
                    return invalid("invocation inputs are not an artifact mapping")
                layouts = []
                for name, expected in inputs.items():
                    path = path_for(name)
                    relative = path.relative_to(project).as_posix()
                    if _sdf._STREAMOUT_RE.fullmatch(relative):
                        layouts.append((path, expected))
                if len(layouts) != 1:
                    return invalid("report invocation must identify one canonical layout input")
                layout, expected = layouts[0]
                if digest(layout) != expected:
                    return invalid("recorded layout hash differs from current layout")
                tops = gds_top_cells(layout.read_bytes())
                top = producer.get("top_cell")
                if not tops or (top and tops != [top]):
                    return invalid(f"recorded layout top cells {tops!r} differ from report top {top!r}")
                found.append({"tier": _sdf.TIER_INVOCATION,
                              "topcell_match": True if top else None,
                              "witness": f"{rel} -> {layout.relative_to(project)} ({expected})"})
                # The ledger is append-only. Once the newest binding is read,
                # older observations cannot override this report's identity.
                break
            except (OSError, ValueError, TypeError) as exc:
                return invalid(f"recorded layout binding unreadable: {exc}")
    return found[0] if found else None


def signoff_verdict(payload: object, project_dir: str) -> tuple:
    """``(findings, summary_additions)`` for the sign-off scope.

    Judges TWO claims the base audit does not and must not judge, because the
    same audit serves the router-DRC gate where the answers are different:

      1. the PRODUCER is a rule deck applied to a layout, not the router
         reporting on its own routing database;
      2. a streamed design LAYOUT is evidenced at all.

    Findings at ERROR severity are the caller's rc-1 reasons. Everything else
    is disclosure and never gates.
    """
    findings = []
    summary = {}
    if isinstance(payload, dict) and isinstance(payload.get("summary"), dict):
        summary = payload["summary"]
    producers = summary.get("producers")
    add: dict = {"signoff_scope": True}

    if not isinstance(producers, list) or not producers:
        findings.append({
            "rule": "DRC_SIGNOFF_PRODUCER_UNRECOGNISED", "severity": "ERROR",
            "file": "",
            "message": ("the audit disclosed no producer for any scoped report, "
                        "so nothing establishes that a sign-off rule deck ran; "
                        "a sign-off gate must not pass on an unattributed "
                        "report")})
        add["signoff_producers"] = []
        add["layout_evidence_tier"] = _sdf.TIER_NONE
        add["layout_topcell_match"] = None
        add["layout_evidence_witness"] = ""
        return findings, add

    add["signoff_producers"] = [
        {k: p.get(k) for k in ("file", "producer", "deck", "is_signoff_deck")}
        for p in producers]

    top_cell = next((p.get("top_cell") for p in producers if p.get("top_cell")),
                    None)
    for p in producers:
        kind, rel = p.get("producer"), p.get("file", "")
        if kind == _sdf.OPENROAD:
            findings.append({
                "rule": "DRC_SIGNOFF_PRODUCER_NOT_A_SIGNOFF_DECK",
                "severity": "ERROR", "file": rel,
                "message": (
                    f"{rel!r} is the ROUTER's own detailed-route DRC "
                    f"({p.get('evidence')}), not a sign-off rule deck applied "
                    f"to a layout. The router's DRC is a routability "
                    f"measurement over its own database — it is what step 21 "
                    f"gates on, and it cannot certify physical verification. "
                    f"Produce the sign-off report from the PDK/foundry deck, "
                    f"or declare the gap through waivers.json so the waiver "
                    f"gates can see it.")})
        elif kind is None:
            findings.append({
                "rule": "DRC_SIGNOFF_PRODUCER_UNRECOGNISED",
                "severity": "ERROR", "file": rel,
                "message": (
                    f"{rel!r} carries no recognised sign-off DRC producer "
                    f"signature ({p.get('evidence')}) — neither a KLayout "
                    f"report database, an SVRF-native per-rule tally, nor a "
                    f"Magic DRC transcript. Nothing is certified.")})
        elif kind == _sdf.KLAYOUT and not p.get("deck"):
            findings.append({
                "rule": "DRC_SIGNOFF_PRODUCER_DECK_UNNAMED",
                "severity": "ERROR", "file": rel,
                "message": (
                    f"{rel!r} is a KLayout report database that declares no "
                    f"<generator> deck script, so it does not say WHICH rules "
                    f"produced it — and which rules ran is the whole content "
                    f"of a sign-off claim.")})
        if p.get("attribution_disagreement"):
            findings.append({
                "rule": "DRC_SIGNOFF_ATTRIBUTION_DISAGREEMENT",
                "severity": "WARNING", "file": rel,
                "message": (
                    f"{rel!r} declares '# Tool: {p.get('header_tool')}' but its "
                    f"content reads as {kind!r}; the CONTENT decides. The "
                    f"header is written by the same code path that re-stages "
                    f"the report, so it is a claim about the file, not "
                    f"evidence from it.")})

    ev = _recorded_layout_evidence(Path(project_dir), producers)
    if ev is None:
        ev = _sdf.layout_evidence(Path(project_dir), top_cell)
    add["layout_evidence_tier"] = ev["tier"]
    add["layout_topcell_match"] = ev["topcell_match"]
    add["layout_evidence_witness"] = ev["witness"]
    add["layout_topcell"] = top_cell
    if ev["tier"] == _sdf.TIER_NONE:
        findings.append({
            "rule": "DRC_SIGNOFF_NO_LAYOUT_EVIDENCE", "severity": "ERROR",
            "file": "",
            "message": (
                "nothing in this project evidences a streamed design layout "
                "for the deck to have read: no measured tool invocation naming "
                "the streamout, no provenance declaration of it, and no "
                "streamout on disk at phase3/stage3/pnr/ or phase3/stage4/gds/"
                + (f" with stem {top_cell!r}" if top_cell else "")
                + ". A DRC certificate over a layout that was never streamed "
                  "certifies nothing.")})
    return findings, add


def _attribution_scope(payload: dict, project_dir: str,
                       required_reports) -> Optional[dict]:
    """The die-level attribution verdict for this audit, or None when the
    audit found nothing to attribute.

    Returns `{"credit", "summary", "finding"}`. `None` only when the audit
    itself reports no real violations — then there is nothing to re-judge and
    this clause must not add a finding saying so.
    """
    summary = payload.get("summary") if isinstance(payload, dict) else None
    if not isinstance(summary, dict):
        return None
    total = summary.get("real_violation_total")
    if isinstance(total, bool) or not isinstance(total, int) or total <= 0:
        return None
    # THE RULE NAMES THIS CHECKER MEASURED, from the reports IT scoped to and
    # from nothing else. Reading the run's attribution record for them would
    # be letting the record grade itself.
    measured: dict = {}
    scoped = [str(s) for s in (summary.get("scoped_under") or [])]
    scoped += [str(s) for s in (required_reports or [])]
    root = Path(project_dir)
    for rel in dict.fromkeys(scoped):
        for cand in (root / rel, Path(rel)):
            try:
                text = cand.read_text(errors="replace")
            except OSError:
                continue
            for rid, n in _dla.rdb_rule_counts(text).items():
                measured[rid] = measured.get(rid, 0) + n
            break
    got = _dlac.consult(root, total, sorted(measured) or None)
    out = {"credit": bool(got.get("credit")),
           "summary": {"die_level_attribution": got,
                       "die_level_attribution_measured_rules": measured},
           "finding": {
               "rule": ("DRC_SIGNOFF_DIE_LEVEL_ATTRIBUTED" if got.get("credit")
                        else "DRC_SIGNOFF_DIE_LEVEL_NOT_ATTRIBUTED"),
               # DISCLOSURE, never an ERROR: when it is credited the run is
               # not clean and must not read as clean; when it is refused the
               # base audit's own ERROR is already the refusal and a second
               # one would double-count it.
               "severity": "WARNING", "file": "",
               "message": _dlac.disclosure(got)}}
    return out


def _write_json(target: str, text: str) -> bool:
    try:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return True
    except OSError:
        return False


def run(caller_argv, _audit=None) -> int:
    """Drive the drc audit for ``caller_argv``; return this wrapper's rc.

    ``_audit`` is a seam for tests that need to exercise a payload shape
    ``eda_report_audit`` cannot currently produce; production always uses
    ``eda_report_audit.main``.
    """
    audit = _audit or _audit_main
    project_dir, passthrough, refusal = split_and_pin(caller_argv, mode=MODE)
    wrapper_flags, passthrough = take_wrapper_flags(passthrough)
    required_reports, passthrough = take_required_reports(passthrough)
    signoff = "--signoff" in wrapper_flags
    target = json_target(passthrough)

    if refusal:
        message = (
            f"REFUSED: {refusal}. This is the DRC sign-off auditor; an auditor "
            "whose audit domain a caller can change — or silently lose — by "
            "flag spelling is a false-certificate vector. NOTHING was "
            "certified."
        )
        payload = _not_checked_payload("DRC_MODE_PIN_REFUSED", message,
                                       project_dir)
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        wrote = _write_json(target, text) if target else False
        print(text)
        print(f"drc_report_check: {message}", file=sys.stderr)
        if target and not wrote:
            print(f"drc_report_check: NO AUDIT WRITTEN to {target}",
                  file=sys.stderr)
        return RC_FAIL

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = audit([project_dir, "--mode", MODE, *passthrough])
    except OSError as exc:
        # e.g. --json naming an existing directory. Before #490 the argv never
        # got this far, so the failure mode was invisible rather than absent.
        print(f"drc_report_check: NOT CHECKED — the audit could not be "
              f"written to {target!r} ({exc.__class__.__name__}: {exc}); no "
              f"DRC verdict was produced.", file=sys.stderr)
        return RC_FAIL
    except SystemExit as exc:
        # argparse ended the run without producing an audit — a rejected
        # command line or an early-exit action. EVERY such exit is mapped to
        # rc 1 here, INCLUDING argparse's own 2 and `--help`'s 0: rc 2 is
        # credited as a VACUOUS_PASS and rc 0 is a sign-off credit, so an
        # invocation that certified nothing must spend neither. Measured at
        # v1.7.66: `drc_report_check --json out.json proj` exited 2 and the
        # real gate runner recorded the step as PASSED.
        sys.stdout.write(buf.getvalue())
        print(f"drc_report_check: NOT CHECKED — eda_report_audit exited "
              f"without producing an audit (exit {exc.code}); no DRC verdict "
              f"was produced.", file=sys.stderr)
        return RC_FAIL

    payload_text = buf.getvalue()
    try:
        payload = json.loads(payload_text)
    except ValueError:
        payload = None

    # --- the sign-off scope ------------------------------------------------
    # Applied BEFORE stdout and BEFORE the artefact is persisted, so the audit
    # JSON a reviewer reads carries the sign-off verdict rather than the base
    # audit's verdict plus a stderr line contradicting it. Only a would-be PASS
    # is re-judged: a FAIL is already a FAIL, and re-deciding it here would
    # relabel someone else's finding.
    # --- the REQUIRED-REPORT scope ----------------------------------------
    # Applied before the sign-off scope and before persistence, on the same
    # only-re-judge-a-would-be-PASS rule: a FAIL is already a FAIL.
    required_absent = False
    if required_reports and rc == RC_PASS:
        rf, radd = required_report_verdict(project_dir, required_reports)
        rerrors = [f for f in rf if f.get("severity") == "ERROR"]
        if isinstance(payload, dict):
            payload.setdefault("findings", []).extend(rf)
            if isinstance(payload.get("summary"), dict):
                payload["summary"].update(radd)
            else:
                payload["summary"] = radd
            if rerrors:
                payload["passed"] = False
                payload["summary"]["terminal_verdict"] = "REQUIRED_REPORT_ABSENT"
            payload_text = json.dumps(payload, indent=2,
                                      ensure_ascii=False) + "\n"
        required_absent = bool(rerrors)
        for f in rf:
            print(f"drc_report_check: [{f['severity']}] {f['rule']}: "
                  f"{f['message']}", file=sys.stderr)

    signoff_refused = False
    # WHETHER THE CERTIFICATE IS ONE is independent of what it counted.
    # This read `signoff and rc == RC_PASS and not required_absent`, so the
    # producer questions -- is this a recognised sign-off deck, does it name
    # its rule set, is there layout evidence -- were only ever asked of a
    # report that had ALREADY passed the count check. v1.20.61 then made an
    # uncorroborated zero NOT_MEASURED (correctly), which drops rc below
    # RC_PASS, and with it every one of those refusals became unreachable:
    # the seven tests in test_signoff_drc_producer_is_a_signoff_deck.py
    # stopped seeing the token they exist to demand. A guard no input can
    # reach is not a guard. A report from an unrecognised producer is
    # refused whether it claims zero violations or five hundred.
    if signoff and not required_absent:
        sf, sadd = signoff_verdict(payload, project_dir)
        errors = [f for f in sf if f.get("severity") == "ERROR"]
        if isinstance(payload, dict):
            payload.setdefault("findings", []).extend(sf)
            if isinstance(payload.get("summary"), dict):
                payload["summary"].update(sadd)
            else:
                payload["summary"] = sadd
            if errors:
                payload["passed"] = False
                # Never overwrite a MORE SPECIFIC terminal verdict the
                # count half already reached.
                payload["summary"].setdefault(
                    "terminal_verdict", "SIGNOFF_REFUSED")
            payload_text = json.dumps(payload, indent=2,
                                      ensure_ascii=False) + "\n"
        signoff_refused = bool(errors)
        for f in sf:
            print(f"drc_report_check: [{f['severity']}] {f['rule']}: "
                  f"{f['message']}", file=sys.stderr)
        print(f"drc_report_check: signoff layout evidence tier="
              f"{sadd.get('layout_evidence_tier')!r} "
              f"topcell_match={sadd.get('layout_topcell_match')!r} "
              f"witness={sadd.get('layout_evidence_witness')!r}",
              file=sys.stderr)

    # ── the DIE-LEVEL ATTRIBUTION scope ────────────────────────────────────
    # RE-JUDGING A WOULD-BE FAIL, AND THE ONLY PLACE THIS FILE DOES.
    # Everything above re-judges a would-be PASS only, on the stated rule that
    # "a FAIL is already a FAIL, and re-deciding it here would relabel someone
    # else's finding". This clause does not relabel anyone's finding: the base
    # audit's DRC_REAL_VIOLATIONS_FOUND stays in the document, at ERROR, word
    # for word. What it adds is the question the base audit has no way to ask,
    # because `eda_report_audit` is a report reader and this is a property of
    # the DELIVERY.
    #
    # MEASURED 2026-09-15 on `subservient` x gf180mcuD, a HARDMACRO that had
    # passed 9 of 9 declared phase-3 sign-off gates:
    #     phase 3's own `drc` STEP        PASS_WITH_ATTRIBUTION, remainder 0
    #     this checker, step 31           FAIL, "2 real DRC violation(s)"
    #     tapeout_signoff_check, step 36  FAIL, "2 at design level"
    # Three checkers, ONE quantity, two of them never told what the delivery
    # is. The two violations are M2.4/M3.4 metal-density MINIMUMS whose
    # measurement window, in the deck's own block, is the WHOLE DIE — which a
    # 413 um macro placed inside somebody else's die cannot move.
    #
    # NOTHING IS TAKEN ON THE RUN'S WORD: `_dlac.consult` re-establishes the
    # declared deliverable, re-runs the producer's own die-level predicate over
    # the deck evidence, requires the handoff record to name every attributed
    # rule, requires the arithmetic to close against THE COUNT AND THE RULE
    # NAMES THIS CHECKER MEASURED FOR ITSELF, and requires the unattributed
    # remainder to be zero. Five refusals this path did not have. A DIE
    # delivery is `applicable: False` and nothing changes for it.
    attribution_credited = False
    if signoff and isinstance(payload, dict):
        sadd2 = _attribution_scope(payload, project_dir, required_reports)
        if sadd2:
            if isinstance(payload.get("summary"), dict):
                payload["summary"].update(sadd2["summary"])
            payload.setdefault("findings", []).append(sadd2["finding"])
            if sadd2["credit"]:
                payload["passed"] = True
                payload["summary"]["terminal_verdict"] = _dlac.TIER
                # `signoff_refused` IS DELIBERATELY NOT CLEARED. It carries the
                # sign-off scope's OTHER refusals — an unrecognised producer,
                # a router-DRC report masquerading as a sign-off deck, a deck
                # that does not name its rule set, no streamed layout at all.
                # Those are about WHETHER THIS IS A CERTIFICATE; the
                # attribution is about WHOSE the violations are, and it must
                # not answer a question it was not asked. An early draft did
                # clear it, and this file's own R arm caught it: the fixture
                # report carried no `<generator>` deck, the base tree refused
                # it for that reason, and the fixed tree returned 0 — a real
                # refusal suppressed by a change that has nothing to do with
                # it. The refusal below still runs first.
                # AND THE EXIT CODE, or the persisted audit and the rc would
                # disagree — the very state the `--json` re-emit above exists
                # to prevent. `rc` is the base audit's, and the base audit was
                # answering "are there violations", which is still YES; this
                # answers "are any of them THIS DELIVERY'S", which is NO.
                attribution_credited = True
            payload_text = json.dumps(payload, indent=2,
                                      ensure_ascii=False) + "\n"
            print(f"drc_report_check: [{sadd2['finding']['severity']}] "
                  f"{sadd2['finding']['rule']}: {sadd2['finding']['message']}",
                  file=sys.stderr)

    sys.stdout.write(payload_text)          # stdout stays pure audit JSON

    # `eda_report_audit` writes `--json` itself, so the artefact on disk holds
    # the BASE payload. Under `--signoff` it must be overwritten with the
    # enriched one, or the persisted audit and the exit code disagree.
    # `required_reports` joins `signoff` here: both ENRICH the payload, and a
    # persisted audit saying passed=true beside an rc-1 refusal is the
    # disagreement this branch exists to prevent.
    if target and (signoff or required_reports
                   or not Path(target).is_file()):
        if _write_json(target, payload_text.strip() + "\n"):
            if not signoff:
                print(f"drc_report_check: audit re-emitted to {target} by the "
                      f"wrapper (eda_report_audit left it absent).",
                      file=sys.stderr)
        else:
            print(f"drc_report_check: NO AUDIT WRITTEN to {target} — the "
                  f"verdict below was produced but could not be persisted.",
                  file=sys.stderr)
            return RC_FAIL

    if required_absent:
        print("drc_report_check: REFUSED a PASS — a REQUIRED DRC report does "
              "not exist, so the question it answers was never put. An absent "
              "report is not an empty one: empty is a measured zero, absent "
              "is NOT MEASURED. See DRC_REPORT_REQUIRED_ABSENT above.",
              file=sys.stderr)
        return RC_FAIL

    if signoff_refused:
        print("drc_report_check: REFUSED a sign-off PASS — see the "
              "DRC_SIGNOFF_* finding(s) above. NOTHING was certified for "
              "step 31.", file=sys.stderr)
        return RC_FAIL

    if attribution_credited:
        print("drc_report_check: PASS_WITH_ATTRIBUTION — every violation this "
              "sign-off deck reported is a die-level rule handed to the "
              "INTEGRATOR, re-derived here from the declaration, the deck "
              "evidence, the handoff record and this checker's own count. "
              "The design's unattributed remainder is 0. See "
              "DRC_SIGNOFF_DIE_LEVEL_ATTRIBUTED above.", file=sys.stderr)
        return RC_PASS

    if rc == RC_PASS:
        ok, files_found, determined, real_total = denominator_of(payload)
        if not ok:
            print(f"drc_report_check: REFUSED a PASS that cannot name its "
                  f"denominator (summary.files_found={files_found!r}) — a "
                  f"sign-off gate must disclose how much it read.",
                  file=sys.stderr)
            return RC_FAIL
        # A PASS states how much it looked at — and, since #997-D9, how much of
        # that it was able to CHECK AGAINST THE TOOL rather than against the
        # runner's summary of the tool. `tool_corroborated` is the second
        # denominator: a report with no tool transcript beneath its summary is
        # passed on the summary alone, and a reader is entitled to see that
        # said out loud instead of inferring it from a single count.
        summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
        print(f"drc_report_check: PASS over files_found={files_found} "
              f"determined_files={determined} "
              f"real_violation_total={real_total} "
              f"tool_corroborated_files={summary.get('tool_corroborated_files')} "
              f"tool_uncorroborated_files="
              f"{summary.get('tool_uncorroborated_files')} "
              f"project={project_dir}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
