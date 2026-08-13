#!/usr/bin/env python3
"""
step_internal_fail_bubble_up_check.py — anti-fabrication gate (v1.6.44).

ENFORCEMENT: advisory — no runner spawns this gate inline, so it cannot stop
step 36 while step 36 is running. That single axis is all this token names, and
it is the one `flow_gate_enforcement_audit` measures. The `ENFORCEMENT` section
further down this docstring answers a DIFFERENT question — the verdict severity
of PROJECT mode versus CORPUS mode — and it is unchanged: an unacknowledged
FAIL is still rc 1. Two axes; this line is the one the audit was reading and
finding nothing on.

THE FLOW SLOT IS ALSO UNCHANGED AND BLOCKING. Step 36 wires this gate BARE in
`program_exit_zero`, never `advisory_program_exit_zero`, so an rc 1 FAILs the
step when `flow_compliance_check` evaluates the clause. The flow's own comment
at that row records the measurement behind the choice — 17 of 107 published
roots red, all 17 adjudicated by hand, 16 carrying at least one real
unacknowledged defect — and `advisory` here must never be cited as a reason to
move the clause. `test_issue1035_five_gates_declare_where_they_are_enforced`
pins the slot for exactly that reason.

Doctrine rule #4: a step-internal sub-gate `verdict: FAIL` (or MISSING)
MUST bubble up to the project's overall verdict — either by being
explicitly waived in `waivers.json`, or by causing the parent step's
`pass.flag` to be absent. Silently keeping `pass.flag` while a
`reports/**/*.json` declares FAIL is the fabrication shape this gate
catches.

Real-world inspiration (from v1.6.36 review):
  `flow_compliance_check.py` evaluates each step's `pass.flag` and
  classifies the project as PASS / PASS_WITH_WAIVERS / FAIL. It does
  NOT walk the per-step report JSON. So a step can ship pass.flag
  while one of its sub-reports declares verdict=FAIL — the project
  shows green but the substantive evidence says otherwise.

Audit shape (chip-AGNOSTIC, no per-step ID hardcoded)
-----------------------------------------------------
For every `reports/**/*.json` whose `verdict` field is in
{FAIL, MISSING}:

  1. Derive the report's IDENTITY from its path: the stem, the
     basename, and the project-relative path. Example for
     `reports/phase3/ir_drop.json`: {ir_drop, ir drop, ir_drop.json,
     reports/phase3/ir_drop.json}.

  2. Acknowledge the FAIL by either:

     (a) WAIVER MATCH — `waivers.json::waived_steps[*]` contains an
         entry whose `reason`, `ticket`, or `evidence` text names the
         report (case-insensitive, normalised across `_`/`-`/space).

     (b) BUBBLED — any other JSON under `reports/orchestrator/` or
         `reports/audit/` records a matching FAIL/MISSING verdict
         naming the same report.

  3. If neither (a) nor (b), flag `STEP_FAIL_NOT_BUBBLED`.

IDENTITY, NOT A FRAGMENT (vibe-ic#693)
--------------------------------------
The candidate set used to also carry the PARENT DIRECTORY NAME and every
`_`-split token of length >= 3. Those are categories, not identities, and a
word-bounded search for them hits ordinary prose.

MEASURED over the 46 run trees on a working checkout: 107 reports declare
verdict FAIL/MISSING and the previous matcher flagged 5. Identity matching
flags 33. The 28 it recovers were each "acknowledged" by a token that names a
CATEGORY rather than the report — measured, the granting token was `analog`
(7), `corner` (6), `gates` (5), `coverage` (4), `cell` (2), `phase3` (2),
`audit` (1), `signoff` (1).

The clearest instance, and the reason this is a defect rather than a tuning
preference — a published run's

    reports/phase2/gates/ip_integration.json   verdict=FAIL

was ACKNOWLEDGED by the candidate `gates`, matched against its own
orchestrator roll-up at

    reports/audit/phase23_completion_audit.json:9:    "gates": [],
    reports/audit/phase23_completion_audit.json:10:   "failed_gates": [],

An EMPTY gates list was read as evidence that the failure had been bubbled up.
A gate whose PASS can be granted by a line asserting the opposite is not
measuring acknowledgment; it is measuring vocabulary. So the match is now on
identity only.

`verdict_mode: ADVISES` IS AN ANSWER, NOT A SILENCE
---------------------------------------------------
A report that declares `"verdict_mode": "ADVISES"` alongside `FAIL` has
already said its verdict does not gate — that is the repo's own convention
(`flow_gate_enforcement_audit` parses exactly this key, and
`cross_layer_reference_check` / `dfm_screen_check` / three L-layer gates emit
it). Demanding a waiver for an advisory finding would require every run to
waive a gate that is not blocking. MEASURED: 10 of the 107 FAIL reports carry
it, all 10 of them `reports/phase1/cross_layer_reference_check.json`.

ENFORCEMENT
-----------
PROJECT mode is BLOCKING and stays that way: an unacknowledged FAIL is rc 1.
(`--strict` is accepted as an explicit spelling of the same thing. The
verdict -> exit-code mapping is the property
`test_an_unacknowledged_fail_exits_1` exists to hold, and weakening it would
reproduce, in this gate, the defect it audits.)

CORPUS mode is the non-blocking form, and it is non-blocking by RATCHET rather
than by being toothless. `--corpus <dir>` sweeps the PUBLISHED (git-tracked)
run trees and compares against a recorded baseline: the count may shrink
freely, growth is rc 1. That is what CI runs, because `--strict` over every run
tree on a working checkout reddens 16 of 46 on 33 findings this change did not
create.

Files audited:
  reports/**/*.json  (excluding files inside reports/audit/ which are
                     human-authored review artefacts)

Files used as evidence of bubble-up:
  reports/orchestrator/*.json
  reports/audit/*.json
  reports/phase23_completion_audit.json (if present)

NOT_EXAMINED conditions (rc=2, never a pass — vibe-ic#693 follow-up):
  * no `reports/` tree on disk → pre-output project
  * `reports/` exists but no file in it declares a verdict

Both mean NOTHING WAS EXAMINED. Through v1.9.62 they returned rc=0 printing
`VACUOUS_PASS`, which put them in the same exit class as a genuine clean run
over a hundred reports — and a step that crashed before writing any report
produces exactly this. The denominator is now disclosed on every pass, so
"no FAIL/MISSING reports" can no longer be read without knowing how many
reports that was over.

Usage:
    python3 step_internal_fail_bubble_up_check.py <project_dir>
                                                   [--json <out>] [--strict]
    python3 step_internal_fail_bubble_up_check.py --corpus benchmark-data/ic
                                                   [--baseline <f>] [--write-baseline]

Exit codes:
    0  PASS — reports were examined and every FAIL/MISSING one is
       acknowledged; also a report-only run, or a corpus at-or-below baseline
    1  FAIL — an unacknowledged FAIL in PROJECT mode (or under --strict), or
       corpus GROWTH
    2  NOT EXAMINED (nothing to look at), or argument / I/O error

chip-AGNOSTIC. No vendor / IC / specific filename hardcoded.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple  # noqa: F401


_FAIL_VERDICTS = {"FAIL", "MISSING"}

# Verdict tokens we treat as "honestly accounted for already" — don't
# flag them at all. These are explicit non-PASS but the report itself
# self-declares the gap; the runner-level enforcement is the gate's
# concern, not this audit.
_NEUTRAL_VERDICTS = {
    "INSUFFICIENT_DATA",  # honest "tool did not run / data missing"
    "VACUOUS_PASS",        # gate inapplicable
    "SKELETON_EMITTED",    # placeholder marker
    "FALLBACK",            # alt-path used; orthogonal to bubble-up
    "WARN", "WARNING",
    "WAIVED", "WAIVED_DEFERRED",
}


@dataclass
class BubbleFinding:
    rule: str
    report_file: str
    verdict: str
    name_candidates: List[str]
    detail: str = ""


def _normalise(s: str) -> str:
    """Lower-case + collapse `_` / `-` / whitespace to a single space."""
    return re.sub(r"[\s_\-]+", " ", s.strip().lower())


def _name_candidates(report_path: Path, project: Path) -> Set[str]:
    """The report's IDENTITY — the strings that name THIS report and no other.

    Deliberately NOT: the parent directory (`gates`, `phase3`, `safety`) or the
    `_`-split fragments (`check`, `cell`, `post`, `coverage`). Those are
    categories shared by dozens of reports, and a word-bounded search for them
    hits ordinary prose in any orchestrator blob — including, measured, the
    line `"failed_gates": []`, which asserts the OPPOSITE of an acknowledgment.
    See the module docstring for the full measurement.
    """
    cand: Set[str] = set()
    stem = report_path.stem
    cand.add(stem)
    cand.add(_normalise(stem))
    cand.add(report_path.name)
    try:
        cand.add(report_path.relative_to(project).as_posix())
    except ValueError:
        pass
    return {c for c in cand if c}


def _read_json(p: Path) -> Optional[Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _waiver_text_corpus(project: Path) -> str:
    """Concatenate searchable text from every waiver entry. Used to
    test name-candidate substring matches."""
    waivers_path = project / "waivers.json"
    if not waivers_path.is_file():
        return ""
    d = _read_json(waivers_path)
    if not isinstance(d, dict):
        return ""
    parts: List[str] = []
    parts.append(str(d.get("_doc", "")))
    for entry in d.get("waived_steps", []) or []:
        if not isinstance(entry, dict):
            continue
        for k in ("reason", "ticket", "evidence", "approver",
                  "rationale", "note", "notes"):
            v = entry.get(k)
            if isinstance(v, str):
                parts.append(v)
        # Step ID itself can match like "step29" / "step 29" / "step-29"
        sid = entry.get("id")
        if sid is not None:
            parts.append(f"step{sid} step {sid} step-{sid}")
    return _normalise(" | ".join(parts))


def _bubbled_corpus(project: Path) -> str:
    """Concatenate searchable text from orchestrator + completion-audit
    JSONs. A FAIL report is "bubbled up" if a top-level audit also
    records the failure for the same name."""
    parts: List[str] = []
    candidates: List[Path] = []
    odir = project / "reports" / "orchestrator"
    if odir.is_dir():
        candidates.extend(sorted(odir.rglob("*.json")))
    audit_dir = project / "reports" / "audit"
    if audit_dir.is_dir():
        candidates.extend(sorted(audit_dir.rglob("*.json")))
    cad = project / "reports" / "phase23_completion_audit.json"
    if cad.is_file():
        candidates.append(cad)
    for p in candidates:
        try:
            txt = p.read_text(encoding="utf-8")
        except OSError:
            continue
        # Only include lines that look like they reference a FAIL.
        for line in txt.splitlines():
            ll = line.lower()
            if "fail" in ll or "missing" in ll:
                parts.append(line)
    return _normalise("\n".join(parts))


def _candidate_in_corpus(cand: str, corpus: str) -> bool:
    """Word-bounded substring match. Avoids `ir` matching `dir`."""
    if len(cand) < 3:
        return False
    pat = r"(?<![a-z0-9])" + re.escape(cand) + r"(?![a-z0-9])"
    return re.search(pat, corpus) is not None


def _iter_report_files(project: Path) -> List[Path]:
    """All reports/**/*.json EXCEPT reports/audit/ (human-authored)
    and reports/orchestrator/ (top-level audit, used for bubble-up
    evidence — not a leaf report we audit)."""
    rdir = project / "reports"
    if not rdir.is_dir():
        return []
    out: List[Path] = []
    for p in sorted(rdir.rglob("*.json")):
        rel = p.relative_to(project)
        # Exclude human-authored / aggregation files
        if rel.parts[1] in ("audit", "orchestrator"):
            continue
        out.append(p)
    return out


def audit(project: Path) -> Tuple[str, List[BubbleFinding], int]:
    """Returns (verdict, findings, examined) — `examined` is the DENOMINATOR:
    how many report files actually carried a readable verdict.

    It is returned because without it "no FAIL/MISSING reports" is the same
    sentence whether a hundred reports were read and all were clean, or the
    step crashed before writing any report at all. The second is the state this
    gate exists to notice, and it was the one that read as a pass."""
    if not project.is_dir():
        return "NOT_EXAMINED", [], 0
    if not (project / "reports").is_dir():
        return "NOT_EXAMINED", [], 0

    waiver_text = _waiver_text_corpus(project)
    bubbled_text = _bubbled_corpus(project)

    findings: List[BubbleFinding] = []
    saw_any_fail = False
    examined = 0

    for rp in _iter_report_files(project):
        d = _read_json(rp)
        if not isinstance(d, dict):
            continue
        verdict_raw = d.get("verdict")
        if not isinstance(verdict_raw, str):
            continue
        examined += 1
        verdict = verdict_raw.strip().upper()
        if verdict in _NEUTRAL_VERDICTS:
            continue
        if verdict not in _FAIL_VERDICTS:
            continue
        # A report that declares itself advisory has ALREADY said its verdict
        # does not gate. Demanding a waiver for it would require every run to
        # waive a gate that is not blocking. `verdict_mode` is the repo's own
        # BLOCKS/ADVISES key (flow_gate_enforcement_audit parses it).
        if str(d.get("verdict_mode", "")).strip().upper() == "ADVISES":
            continue
        saw_any_fail = True

        cands = _name_candidates(rp, project)
        # (a) waiver match
        waiver_ok = any(_candidate_in_corpus(_normalise(c), waiver_text)
                        for c in cands)
        # (b) bubble-up match
        bubbled_ok = any(_candidate_in_corpus(_normalise(c), bubbled_text)
                         for c in cands)

        if waiver_ok or bubbled_ok:
            continue

        rel = rp.relative_to(project)
        findings.append(BubbleFinding(
            rule="STEP_FAIL_NOT_BUBBLED",
            report_file=str(rel),
            verdict=verdict,
            name_candidates=sorted(cands),
            detail=("report declares verdict=" + verdict +
                    " but no waivers.json entry references it AND no "
                    "orchestrator / completion-audit JSON records the "
                    "matching FAIL. Either: add a waivers.json entry "
                    "for this artefact, or remove the surrounding step's "
                    "pass.flag so the project's overall verdict reflects "
                    "the failure."),
        ))

    if examined == 0:
        # `reports/` exists but nothing in it declares a verdict. Nothing was
        # examined, so there is no result — not a clean one.
        return "NOT_EXAMINED", [], 0
    if not saw_any_fail:
        # A REAL pass over a REAL population: reports were read and none of
        # them declares a FAIL, so the property holds. Formerly returned as
        # VACUOUS_PASS, which is this repo's word for a verdict issued over
        # nothing — and it collapsed into the same rc as the genuinely empty
        # case above.
        return "PASS", [], examined
    return ("FAIL" if findings else "PASS"), findings, examined


BASELINE_NAME = "step_internal_fail_bubble_up_baseline.json"
_HERE = Path(__file__).resolve().parent


def _published_run_trees(corpus: Path) -> List[Path]:
    """The PUBLISHED run trees, not whatever this machine happens to hold.

    `.gitignore` excludes `benchmark-data/ic/*/clean_run_*/` and re-admits only
    `reports/`, `RESULT.md` and `.gitignore`. MEASURED at this commit: 46 run
    trees on a working checkout, 17 tracked. A baseline recorded against 46
    would fail in CI and for every fresh clone — the exact host-dependence
    `_published_tree` exists to remove. So the corpus is what git tracks.

    Outside a repository (a run tree handed over on its own) tracked-ness is
    not a question that applies, and the disk is the honest answer.
    """
    try:
        sys.path.insert(0, str(_HERE))
        import _published_tree                      # noqa: PLC0415
        published = _published_tree.published_paths(corpus)
    except Exception:                               # noqa: BLE001
        published = None
    # DEPTH-INSENSITIVE (vibe-ic#1025). This was `corpus.glob("*/clean_run_*")`,
    # which only ever matched run trees exactly ONE level below the corpus root.
    # The docstring's own example passes `benchmark-data/ic`, where that works;
    # passing `benchmark-data` — the obvious thing, and what the repo's other
    # instruments take — matched `benchmark-data/ic/clean_run_*`, which does not
    # exist, and the sweep reported reaching NOTHING. MEASURED at the commit this
    # was fixed on:
    #
    #     --corpus benchmark-data      ->  0 tree(s),  VACUOUS_PASS, rc 2
    #     --corpus benchmark-data/ic   -> 13 tree(s), 3 with reports/,
    #                                     5 unacknowledged step-internal FAIL(s)
    #
    # Same repo, same commit, same question — the answer depended on how many
    # path components the caller happened to type. A sweep whose population is a
    # function of the caller's phrasing is not a sweep, and the VACUOUS_PASS it
    # returned was honest about examining nothing while giving no hint that
    # anything was reachable at all.
    #
    # `rglob` makes the two invocations agree by construction rather than by the
    # caller remembering the right depth. The NAME pattern is unchanged: the
    # population is still `clean_run_*` trees and this commit does not widen it.
    on_disk = sorted(p for p in corpus.rglob("clean_run_*") if p.is_dir())
    if published is None:
        return on_disk
    root = corpus.resolve()
    keep = []
    for d in on_disk:
        rel = d.resolve().relative_to(root).as_posix()
        if any(t.startswith(rel + "/") for t in published):
            keep.append(d)
    return keep


def check_corpus(corpus: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {"gate": "step_internal_fail_bubble_up_check",
                           "mode": "corpus", "corpus": str(corpus),
                           "runs_swept": 0, "runs_with_reports": 0,
                           "findings_total": 0, "per_run": {}, "findings": []}
    for run in _published_run_trees(corpus):
        out["runs_swept"] += 1
        if not (run / "reports").is_dir():
            continue
        out["runs_with_reports"] += 1
        # 3-tuple: `audit` also returns the DENOMINATOR (how many reports
        # actually carried a verdict), so "no FAIL/MISSING" cannot be read
        # without knowing what it was over. The corpus sweep only needs the
        # findings, but it must not silently drop the arity.
        _v, fs, _examined = audit(run)
        rel = run.relative_to(corpus).as_posix()
        if fs:
            out["per_run"][rel] = len(fs)
            out["findings_total"] += len(fs)
            for f in fs:
                out["findings"].append({"run": rel, **asdict(f)})
    return out


def _load_baseline(p: Path) -> Optional[dict]:
    """The WHOLE recorded baseline, not just its total (vibe-ic#1025).

    This used to return `findings_total` alone. The file has always carried a
    `per_run` map and nothing ever read it back, so the ratchet compared one
    scalar against another and had no way to ask WHICH runs the difference came
    from — see :func:`_decompose_shrink` for why that distinction is the whole
    point of the rule.
    """
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d.get("findings_total"), int):
        return None
    per = d.get("per_run")
    d["per_run"] = per if isinstance(per, dict) else {}
    return d


def _run_key(rel: str) -> str:
    """`<design>/<run>`, whichever corpus root the caller happened to name.

    THE RECORDED BASELINE AND THE LIVE SWEEP HAVE NEVER AGREED ON THIS, and
    that is the second half of why the ratchet could not decide anything
    (vibe-ic#1025). The committed baseline keys read

        sha256/clean_run_v1422_20260715

    while a sweep of `benchmark-data` emits

        ic/sha256/clean_run_v1422_20260715

    because the run root is reported relative to the corpus argument, and the
    baseline was recorded against `benchmark-data/ic`. Compared verbatim, EVERY
    baseline run looks absent from EVERY sweep — so a comparison that reads
    `per_run` at all would have called all seven findings withdrawn, including
    the five sitting right there in the same output.

    Normalises by dropping a leading `ic/` corpus component. Deliberately only
    that one, and only at the front: matching on a bare tail would let
    `foo/clean_run_x` answer for `bar/clean_run_x`, which is a different run.
    """
    parts = [p for p in str(rel).strip("/").split("/") if p]
    if parts and parts[0] == "ic":
        parts = parts[1:]
    return "/".join(parts)


def _decompose_shrink(base: dict, rep: dict) -> dict:
    """Split a fall in the count into REPAIRED and WITHDRAWN.

    THE DEFECT THIS EXISTS TO REMOVE (vibe-ic#1025). The ratchet's doctrine is
    "the number MAY ONLY SHRINK", and on a shrink it printed

        [PASS] 7 -> 5; lower the baseline so the recorded number stops claiming
        debt that is paid.

    "debt that is paid" is a claim about WORK. A total can also fall because a
    run left the published corpus, and a withdrawal is not a repair — the
    reports still say FAIL, nobody looked at them, they are simply no longer
    published. MEASURED on this repo at `a38902d1`, which is exactly that case:

        sha256/clean_run_v1422_20260715   baseline 2 -> now 2   unchanged
        sha256/clean_run_v1427_20260715   baseline 3 -> now 3   unchanged
        u_hawaii_adc/clean_run_v1422...   baseline 1 -> WITHDRAWN
        u_hawaii_adc/clean_run_v1427...   baseline 1 -> WITHDRAWN

    7 -> 5, and **zero findings were repaired**. Recording that shrink as debt
    paid would credit a publishing decision as engineering, and — because the
    number may only ever go down — would permanently lower the bar on the
    strength of it.

    Returns the two populations by name. It decides no verdict; the caller
    reports them, because "which of these two happened" is the thing a reader
    needs and neither one is a failure on its own.
    """
    base_runs = {_run_key(k): v for k, v in (base.get("per_run") or {}).items()}
    now_runs = {_run_key(k): v for k, v in (rep.get("per_run") or {}).items()}

    repaired, withdrawn = {}, {}
    for run, was in sorted(base_runs.items()):
        if run in now_runs:
            is_now = int(now_runs[run])
            if is_now < int(was):
                repaired[run] = (int(was), is_now)
        else:
            withdrawn[run] = int(was)
    return {
        "repaired": repaired,
        "withdrawn": withdrawn,
        "repaired_total": sum(w - n for w, n in repaired.values()),
        "withdrawn_total": sum(withdrawn.values()),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Doctrine rule #4 — every step-internal "
                    "verdict=FAIL must be acknowledged (waivered or "
                    "bubbled up).")
    ap.add_argument("project_dir", nargs="?", default=None)
    ap.add_argument("--json", help="write JSON report to this path")
    ap.add_argument("--strict", action="store_true",
                    help="accepted and explicit; the project verdict is "
                         "ALREADY blocking (an unacknowledged FAIL is exit 1) "
                         "and this change does not weaken that. The "
                         "non-blocking form is --corpus, which ratchets.")
    ap.add_argument("--corpus", default=None, metavar="DIR",
                    help="sweep the PUBLISHED (git-tracked) run trees under "
                         "DIR and ratchet against the recorded baseline: the "
                         "count may shrink freely, growth is rc 1.")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--write-baseline", action="store_true")
    args = ap.parse_args(argv)

    if args.corpus:
        corpus = Path(args.corpus)
        if not corpus.is_dir():
            print(f"error: not a directory: {corpus}", file=sys.stderr)
            return 2
        rep = check_corpus(corpus)
        if args.json:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(rep, indent=2) + "\n")
        bl = Path(args.baseline) if args.baseline else _HERE / BASELINE_NAME
        now = rep["findings_total"]
        if args.write_baseline:
            prev = _load_baseline(bl)
            # CARRY THE WITHDRAWALS FORWARD (vibe-ic#1025). Without this the
            # rewrite drops any run that left the corpus, and the next reader
            # sees only a smaller number — indistinguishable from work. The
            # ledger accumulates, because a run withdrawn twice is still one
            # unexamined finding.
            withdrawn = dict((prev or {}).get("withdrawn_unexamined") or {})
            if prev:
                split = _decompose_shrink(prev, rep)
                for run, was in split["withdrawn"].items():
                    withdrawn[run] = was
            doc = {
                "_comment": (
                    "Unacknowledged step-internal FAIL/MISSING reports across "
                    "the PUBLISHED (git-tracked) run trees. MAY ONLY SHRINK — "
                    "each one is a report declaring FAIL that no waiver and no "
                    "orchestrator record names. The wrong repair is to loosen "
                    "the matcher until the number falls (vibe-ic#693)."),
                "_withdrawn_comment": (
                    "Runs whose findings left this count because the run left "
                    "the published corpus, NOT because anyone examined them "
                    "(vibe-ic#1025). Kept so a fall in findings_total can never "
                    "be read as debt paid. These reports still say FAIL."),
                "findings_total": now,
                "runs_swept": rep["runs_swept"],
                "runs_with_reports": rep["runs_with_reports"],
                "per_run": rep["per_run"],
                "withdrawn_unexamined": withdrawn,
            }
            bl.write_text(json.dumps(doc, indent=2) + "\n")
            print(f"wrote {bl} (findings_total={now}, "
                  f"withdrawn_unexamined={sum(withdrawn.values())})")
            return 0
        base_doc = _load_baseline(bl)
        print(f"corpus sweep: {rep['runs_swept']} published run tree(s), "
              f"{rep['runs_with_reports']} with a reports/ tree, "
              f"{now} unacknowledged step-internal FAIL(s)")
        if rep["runs_with_reports"] == 0:
            print("VACUOUS_PASS: no published run tree carries a reports/ "
                  "directory — the sweep examined nothing.")
            return 2
        if base_doc is None:
            print(f"[NOT CHECKED] no baseline at {bl} — record one with "
                  f"--write-baseline before this can ratchet.")
            return 2
        base = base_doc["findings_total"]
        for run, n in sorted(rep["per_run"].items()):
            print(f"   {run}: {n}")
        if now > base:
            print(f"[FAIL] unacknowledged step-internal FAILs GREW "
                  f"{base} -> {now}: a step shipped a verdict=FAIL report that "
                  f"no waiver and no orchestrator record names.")
            return 1
        if now < base:
            split = _decompose_shrink(base_doc, rep)
            # WHICH of the two happened is the finding, not the arithmetic.
            # A withdrawal is not a repair: the reports still say FAIL, nobody
            # looked at them, they are merely no longer published (vibe-ic#1025).
            for run, (was, is_now) in sorted(split["repaired"].items()):
                print(f"   REPAIRED  {run}: {was} -> {is_now}")
            for run, was in sorted(split["withdrawn"].items()):
                print(f"   WITHDRAWN {run}: {was} finding(s) left the published "
                      f"corpus without being examined")
            if split["withdrawn_total"] and not split["repaired_total"]:
                print(f"[PASS] {base} -> {now}, and NONE of it is repair: "
                      f"{split['withdrawn_total']} finding(s) left because their "
                      f"run was withdrawn from publication. Those reports still "
                      f"say FAIL. Lower the baseline only with "
                      f"`--write-baseline`, which records the withdrawal so the "
                      f"drop is not later read as work someone did.")
                return 0
            if split["withdrawn_total"]:
                print(f"[PASS] {base} -> {now}: {split['repaired_total']} "
                      f"repaired, {split['withdrawn_total']} withdrawn without "
                      f"being examined. Only the first is debt paid.")
                return 0
            print(f"[PASS] {base} -> {now}; lower the baseline so the recorded "
                  f"number stops claiming debt that is paid.")
            return 0
        print(f"[PASS] no NEW unacknowledged step-internal FAIL ({now} recorded)")
        return 0

    if args.project_dir is None:
        ap.error("give a project_dir or --corpus")
        return 2
    proj = Path(args.project_dir).resolve()
    if not proj.is_dir():
        print(f"error: not a directory: {proj}", file=sys.stderr)
        return 2

    verdict, findings, examined = audit(proj)
    report = {
        "gate": "step_internal_fail_bubble_up_check",
        "verdict": verdict,
        "project": str(proj),
        "reports_examined": examined,
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings[:200]],
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "NOT_EXAMINED":
        why = ("no reports/ tree (pre-output project)"
               if not (proj / "reports").is_dir()
               else "reports/ exists but no file in it declares a verdict")
        print(f"[CANNOT DETERMINE] step_internal_fail_bubble_up: {why}, so no "
              f"report was examined. NOT a pass — a step that crashed before "
              f"writing its report produces exactly this, and it is the state "
              f"this gate exists to notice.", file=sys.stderr)
        return 2
    if verdict == "PASS":
        print(f"PASS: {examined} report(s) examined; every FAIL/MISSING one is "
              f"acknowledged (waivered or bubbled up)")
        return 0
    print(f"FAIL: {len(findings)} unacknowledged step-internal "
          "FAIL(s):", file=sys.stderr)
    for f in findings[:10]:
        print(f"  [{f.rule}] {f.report_file}  verdict={f.verdict}",
              file=sys.stderr)
    if len(findings) > 10:
        print(f"  … and {len(findings) - 10} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
