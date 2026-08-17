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

WHERE THE CORPUS IS, NOW THAT IT IS NOT HERE (vibe-ic#1710's treatment)
-----------------------------------------------------------------------
`tools/ci/repo_hygiene_gates.sh` sweeps `--corpus "$ROOT/benchmark-data/ic"`.
v1.10.56 moved the published corpus to its own repository, so that directory is
gone from this repo and the gate answered

    error: not a directory: <repo>/benchmark-data/ic                     rc 2

`_corpus_location` resolves it now, the override is ANNOUNCED, and the four
outcomes stay distinct (see that module). The population key follows the corpus:
the baseline records `corpus_population: benchmark-data/ic` and the tree that
name refers to is the `ic/` directory at the ROOT of the clone, so a sweep
reached through the pointer is normalised back to that spelling rather than
being refused as "a different population" (vibe-ic#1223 is about not comparing
DIFFERENT sets, not about not renaming the same one).

AND THE REGISTER IS NOT EXCUSED WITH THE SWEEP
----------------------------------------------
`step_internal_fail_bubble_up_baseline.json` lives beside this program and did
NOT move with the corpus, so a NO_CORPUS that returned rc 0 without opening it
would leave the ratchet free to be widened by hand — the same hole the corpus
fix is meant to close, entered from the other side.

What is still checkable with no corpus is the register's own arithmetic:
`findings_total` is the sum of `per_run` BY CONSTRUCTION (`check_corpus` adds
`len(fs)` to both in the same breath), so a `findings_total` raised by hand to
buy headroom contradicts the map printed beside it. Under NO_CORPUS:

    register absent / unparseable / malformed        -> UNDETERMINED (rc 2)
    `findings_total` != sum(`per_run`)               -> FAIL (rc 1)
    consistent                                       -> rc 0, printing what it
                                                        holds and stating that
                                                        nothing was re-measured

Usage:
    python3 step_internal_fail_bubble_up_check.py <project_dir>
                                                   [--json <out>] [--strict]
    python3 step_internal_fail_bubble_up_check.py --corpus benchmark-data/ic
                                                   [--baseline <f>] [--write-baseline]
                                                   [--corpus-may-be-absent]

Exit codes:
    0  PASS — reports were examined and every FAIL/MISSING one is
       acknowledged; also a report-only run, or a corpus at-or-below baseline,
       or NO_CORPUS (opted in, and it says 0 run trees were swept)
    1  FAIL — an unacknowledged FAIL in PROJECT mode (or under --strict), or
       corpus GROWTH, or a register whose own numbers contradict each other
    2  NOT EXAMINED (nothing to look at), UNDETERMINED (the corpus could not be
       resolved, or a corpus pointer that is set and wrong), or argument / I/O
       error

chip-AGNOSTIC. No vendor / IC / specific filename hardcoded.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _corpus_location as _cloc                    # noqa: E402

GATE = "step_internal_fail_bubble_up_check"

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
    # `rglob` made the two invocations agree by construction rather than by the
    # caller remembering the right depth. That fixed the DEPTH and said in its
    # own words that it "does not widen" the NAME.
    #
    # THE NAME IS THE REST OF THE SAME DEFECT (vibe-ic#1015, consolidated in
    # vibe-ic#1223). A run tree was recognised by its directory being CALLED
    # `clean_run_*`. A run's name is not what makes it published evidence — the
    # tracked `reports/` tree under it is, because that is the only thing
    # :func:`audit` can read. MEASURED on 1adbf3444 (v1.10.42):
    #
    #     tracked dirs owning a reports/**/*.json under benchmark-data/ic : 16
    #       matching clean_run_*  (the population the ratchet swept) :  3
    #       NOT matching          (invisible to it)                  : 13
    #
    #     findings over benchmark-data/ic   name-based:  5   artefact-based: 22
    #
    # The three largest published trees in the repo — two `ic/spm` version
    # trees at 164 tracked reports each and one `ic/caravel_user_project`
    # version tree at 148 — were outside the population entirely. A ratchet
    # whose denominator is a naming convention holds no line over the runs that
    # do not follow it.
    #
    # THE COMPETING PROPOSAL AND WHY IT LOSES (vibe-ic#1223). The other PR on
    # this function kept the name pattern, arguing a widening would let both
    # `ic/<design>` and `ic/<design>/<version>` be admissible and DOUBLE-COUNT
    # the same artefacts. That objection is true of the admissibility rule IT
    # measured (`provenance.jsonl` / `reports/orchestrator/` presence) and is
    # MEASURABLY FALSE of this one: an owner is the directory before the FIRST
    # `reports` component, so every tracked report file maps to exactly ONE
    # owner, and `audit` reads only `<owner>/reports/**`, which is disjoint from
    # any nested owner's. Verified over the whole corpus, not argued:
    #
    #     report files audited across 117 owners : 1926
    #     counted by more than one owner        :    0
    #
    # `ic/caravel_user_project` (1 finding) and its versioned sub-tree (2) are
    # BOTH admitted and are not the same findings — different report trees,
    # different files, no overlap. Pinned by
    # `test_issue1223_...::test_a_nested_run_root_does_not_double_count`.
    #
    # Returned as `corpus / <owner>`, NOT as a resolved absolute path: the
    # caller keys every run by `run.relative_to(corpus)`, so a resolved return
    # against a relative `--corpus` raises ValueError and takes the whole sweep
    # down. Both `published_paths` and the disk walk speak the same
    # corpus-relative dialect, so this is the one spelling that works for both.

    def _owner(rel_parts: Sequence[str]) -> Optional[str]:
        """The run root that OWNS a path, or None if the path is not in one.

        Keyed on the FIRST `reports` component — the same one `audit` walks —
        so `a/reports/x/reports/y.json` belongs to `a` and to nothing else.
        A path whose owner would be the corpus root itself is not a run in a
        CORPUS of runs; auditing one tree is what the positional mode is for.
        """
        if "reports" not in rel_parts:
            return None
        head = rel_parts[:list(rel_parts).index("reports")]
        return "/".join(head) if head else None

    if published is None:
        # Outside a repository, tracked-ness is not a question that applies and
        # the disk is the honest answer — the same rule the docstring states,
        # applied to the new predicate.
        keep = set()
        for d in corpus.rglob("reports"):
            if not d.is_dir():
                continue
            owner = _owner(d.relative_to(corpus).parts)
            if owner:
                keep.add(corpus / owner)
        return sorted(keep)
    # From the TRACKED list, so the population is what a fresh clone would see.
    # Restricted to `*.json` because that is what `audit` reads: a `reports/`
    # tree that publishes no JSON has nothing for this gate to examine, and
    # admitting it would inflate the denominator with runs no verdict came from.
    keep = set()
    for t in published:
        if not t.endswith(".json"):
            continue
        owner = _owner(tuple(t.split("/")))
        if owner:
            keep.add(corpus / owner)
    return sorted(keep)


def check_corpus(corpus: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {"gate": "step_internal_fail_bubble_up_check",
                           "mode": "corpus", "corpus": str(corpus),
                           "runs_swept": 0, "runs_with_reports": 0,
                           "findings_total": 0, "per_run": {},
                           "examined_runs": [], "findings": []}
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
        # WHICH RUNS WERE LOOKED AT, not merely which ones had something to say
        # (vibe-ic#1202). `per_run` is populated only when `fs` is non-empty, so
        # a run absent from it is ambiguous by construction: it may have been
        # examined and found clean, or it may not have been examined at all.
        # That is exactly the distinction `_decompose_shrink` has to make, and
        # `per_run` alone cannot make it. Recorded here, at the one place that
        # knows, rather than re-derived later from a second walk of the tree.
        out["examined_runs"].append(rel)
        if fs:
            out["per_run"][rel] = len(fs)
            out["findings_total"] += len(fs)
            for f in fs:
                out["findings"].append({"run": rel, **asdict(f)})
    return out


def _load_baseline(p: Path) -> Optional[Dict[str, Any]]:
    """The WHOLE recorded baseline, not just its total (vibe-ic#1202).

    This returned `findings_total` alone. The file has always carried a
    `per_run` map and nothing ever read it back, so the ratchet compared one
    scalar against another and had no way to ask WHICH runs a difference came
    from — see :func:`_decompose_shrink` for why that question is the whole
    point of the rule.

    Still `None` on an unreadable or malformed file, and still keyed on
    `findings_total` being an int, so every caller's existing "no baseline"
    branch keeps its exact meaning.
    """
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("findings_total"), int):
        return None
    for key in ("per_run", "withdrawn_unexamined"):
        d[key] = d[key] if isinstance(d.get(key), dict) else {}
    return d


def _population_key(corpus: Path, origin: str = _cloc.NAMED) -> str:
    """WHICH population a count was taken over, as a repo-relative path.

    THE INTEGER IS MEANINGLESS WITHOUT THE SET IT COUNTED (vibe-ic#1223). The
    `--corpus` argument names a population, and `_published_run_trees` honours
    it — `test_a_narrower_root_still_narrows_the_population` pins that a
    narrower root SWEEPS LESS, deliberately. So two invocations of this gate
    against the same commit legitimately answer different numbers. MEASURED on
    1adbf3444 with the artefact predicate:

        --corpus benchmark-data/ic    16 swept, 16 with reports/, 22 finding(s)
        --corpus benchmark-data      117 swept, 117 with reports/, 45 finding(s)

    Same file, same commit, same question — the answer depends on which root
    the caller typed, and while the name-based population happened to make the
    two agree (nothing outside `ic/` was called `clean_run_*`), that agreement
    was an accident of a naming convention and nothing checked it. Comparing a
    live count against a baseline taken over a DIFFERENT root is not a bigger
    or smaller number, it is a different question, and answering it PASS or
    FAIL would be a verdict over a population never examined.

    Recorded in the baseline and compared, rather than assumed equal.

    THE SAME SET ACQUIRED A SECOND SPELLING WHEN THE CORPUS MOVED OUT
    (v1.10.56). `benchmark-data/ic` in this repository and `ic` at the root of
    the published-corpus clone are the SAME cells — the split moved the tree,
    it did not change the population. Refusing to ratchet one against the other
    would be #1223 applied to a case it is not about, and the effect would be
    that supplying a corpus makes the gate answer NOT CHECKED forever. So the
    ENV origin is normalised back to the canonical name, in
    `_corpus_location.population_key`, where the two spellings are reconciled
    once instead of per gate.
    """
    return _cloc.population_key(corpus, origin)


def _run_key(rel: str) -> str:
    """`<design>/<run>`, whichever corpus root the caller happened to name.

    THE RECORDED BASELINE AND THE LIVE SWEEP DO NOT AGREE ON THIS, and until
    something compared the two maps nothing could notice. MEASURED at
    `75776dbbb`, the shipped baseline keys read

        ic/sha256/clean_run_v1422_20260715

    while `tools/ci/repo_hygiene_gates.sh` — the only caller that runs this
    gate in anger — sweeps `--corpus "$ROOT/benchmark-data/ic"` and emits

        sha256/clean_run_v1422_20260715

    because a run is keyed relative to the corpus argument. The prefix flipped
    in `94c7572aa`, which re-recorded the baseline from `benchmark-data`. So a
    comparison of the two maps VERBATIM would call every baseline run absent
    from every CI sweep — and therefore withdrawn, including the two sitting
    right there in the same output with unchanged counts.

    Normalises by dropping a leading `ic/` corpus component. Deliberately only
    that component and only at the front: matching on a bare tail would let
    `foo/clean_run_x` answer for `bar/clean_run_x`, which is a different run
    and would silently absolve a real withdrawal.

    THE BASELINE FILE IS NOT REWRITTEN TO SUIT THIS. Its keys are validated
    against the tree by `test_issue1025_baseline_names_runs_that_exist`, which
    resolves the corpus as `benchmark-data` — so the `ic/` prefix is correct
    THERE, and stripping it on disk would break that guard. The disagreement is
    between two legitimate spellings of the same run, so it is reconciled on
    read, where both spellings are in hand.
    """
    parts = [p for p in str(rel).strip("/").split("/") if p]
    if parts and parts[0] == "ic":
        parts = parts[1:]
    return "/".join(parts)


def _decompose_shrink(base: Dict[str, Any],
                      rep: Dict[str, Any]) -> Dict[str, Any]:
    """Split a fall in the count into REPAIRED and WITHDRAWN.

    THE DEFECT THIS EXISTS TO REMOVE (vibe-ic#1202). The ratchet's doctrine is
    "the number MAY ONLY SHRINK", and on any shrink it says

        [FAIL] ... N of them are PAID and still on the register ...
               Re-record it with --write-baseline

    "PAID" is a claim about WORK. A total can also fall because a run left the
    published corpus, or kept its place and lost its `reports/` tree — and a
    withdrawal is not a repair. Those reports still declare FAIL, nobody looked
    at them, they are simply no longer published. The prescribed re-record then
    drops the run from `per_run` entirely, so the last trace of the debt is
    erased by the very command the gate told the operator to run.

    MEASURED IN THIS REPO, not hypothesised. `94c7572aa` moved the baseline
    7 -> 5 and the diff is the whole story::

        sha256/clean_run_v1422_20260715        2 -> 2   unchanged
        sha256/clean_run_v1427_20260715        3 -> 3   unchanged
        u_hawaii_adc/clean_run_v1422_20260715  1 -> gone
        u_hawaii_adc/clean_run_v1427_20260715  1 -> gone

    Zero findings were repaired. `u_hawaii_adc/clean_run_v1422_20260715` is
    still a published run tree at `75776dbbb` and still carries its `input/`;
    what it no longer carries is `reports/`, so the sweep walks straight past
    it. Because the ratchet may only ever go down, crediting that as debt paid
    lowers the bar permanently on the strength of a publishing decision.

    HOW THE TWO ARE TOLD APART, and why `per_run` cannot do it alone.
    `check_corpus` writes a `per_run` entry only when a run HAS findings, so a
    run that fell to zero and a run nobody read are both simply absent from the
    map. The discriminator is `examined_runs`: the sweep swept it AND it
    carried a `reports/` tree.

        in `examined_runs`, count fell   -> REPAIRED. Somebody looked and it
                                            is better. That is debt paid.
        not in `examined_runs`           -> WITHDRAWN. Nobody looked. The
                                            reports, wherever they are, still
                                            say FAIL.

    A baseline recorded before `examined_runs` existed has no such list. That
    is UNKNOWN, not "repaired": absent evidence of examination is not evidence
    of examination, and the safe reading of a fall we cannot attribute is the
    one that does not hand out credit. Reported under its own name so a reader
    is never told a decomposition is complete when it is not.

    Decides no verdict. The caller reports the populations, because "which of
    these happened" is what a reader needs and the rc is a separate question.
    """
    base_runs = {_run_key(k): int(v) for k, v in base["per_run"].items()}
    now_runs = {_run_key(k): int(v) for k, v in rep["per_run"].items()}
    examined = rep.get("examined_runs")
    examined_keys = ({_run_key(k) for k in examined}
                     if isinstance(examined, list) else None)

    repaired: Dict[str, Any] = {}
    withdrawn: Dict[str, int] = {}
    unknown: Dict[str, int] = {}
    for run, was in base_runs.items():
        now = now_runs.get(run, 0)
        if now >= was:
            continue
        if examined_keys is None:
            unknown[run] = was - now
        elif run in examined_keys:
            repaired[run] = (was, now)
        else:
            withdrawn[run] = was - now
    return {
        "repaired": repaired,
        "withdrawn": withdrawn,
        "unknown": unknown,
        "repaired_total": sum(was - now for was, now in repaired.values()),
        "withdrawn_total": sum(withdrawn.values()),
        "unknown_total": sum(unknown.values()),
    }


def _adjudicate_register_without_a_corpus(bl: Path) -> int:
    """NO_CORPUS has been decided; now answer for the ratchet register itself.

    The corpus moved to its own repository; this register did not. Returning
    rc 0 without opening it would leave the one number that gates this gate
    free to be raised by hand, which is the same false certificate the corpus
    fix exists to remove, entered from the other side.

    ONE INVARIANT IS STILL CHECKABLE WITH NO CORPUS, and it is not a proxy:
    `check_corpus` adds `len(fs)` to `findings_total` and writes it into
    `per_run[rel]` in the same breath, so `findings_total == sum(per_run)` for
    every document `--write-baseline` can produce. Raising the ceiling by hand
    to make a NEW finding stop being new breaks it.

    WHAT THIS DOES NOT CLAIM. It does not say the recorded findings are still
    there, or still unacknowledged — that needs the corpus, and this run did
    not have one. The printed verdict says so in those words.
    """
    if not bl.is_file():
        print(f"[NOT CHECKED] {GATE}: no corpus was swept, so the baseline "
              f"register is the only thing left to adjudicate, and there is no "
              f"file at {bl}. An absent ratchet is not an empty one: this run "
              f"has judged NOTHING and that is not a pass.", file=sys.stderr)
        return 2
    doc = _load_baseline(bl)
    if doc is None:
        print(f"[NOT CHECKED] {GATE}: no corpus was swept, and {bl} could not "
              f"be read as a register (missing or non-integer "
              f"`findings_total`). Unreadable is not empty; this run has "
              f"judged NOTHING.", file=sys.stderr)
        return 2
    total = doc["findings_total"]
    per_run = doc["per_run"]
    summed = sum(v for v in per_run.values() if isinstance(v, int))
    pop = doc.get("corpus_population")
    if not isinstance(pop, str) or not pop:
        print(f"[NOT CHECKED] {GATE}: no corpus was swept, and {bl} records no "
              f"`corpus_population`, so there is no statement of WHICH set "
              f"{total} was counted over. An integer with no population is not "
              f"a ratchet (vibe-ic#1223).", file=sys.stderr)
        return 2
    if total != summed:
        print(f"[FAIL] {GATE}: no corpus was swept, and the register "
              f"contradicts itself — findings_total={total} while `per_run` "
              f"sums to {summed} across {len(per_run)} run(s). The writer "
              f"produces those two numbers from the same counter, so they "
              f"cannot disagree in a document --write-baseline wrote. A "
              f"ceiling raised by hand is headroom for a finding nobody "
              f"measured; re-record {bl} with --write-baseline over a corpus "
              f"that reaches.", file=sys.stderr)
        return 1
    carried = sum(v for v in doc["withdrawn_unexamined"].values()
                  if isinstance(v, int))
    print(f"[{GATE}] register: findings_total={total} over "
          f"'{pop}' ({len(per_run)} run(s) named, sum agrees), plus "
          f"{carried} withdrawn_unexamined still declaring FAIL.",
          file=sys.stderr)
    print(f"[{GATE}] NO_CORPUS: 0 published run tree(s) swept, 0 report(s) "
          f"examined. The register's numbers were NOT RE-MEASURED and nothing "
          f"is claimed about whether those {total} finding(s) are still "
          f"unacknowledged — only that the register is internally consistent "
          f"and was not widened by hand. Point ${_cloc.CORPUS_ENV} at a clone "
          f"to re-measure.", file=sys.stderr)
    return 0


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
    ap.add_argument("--corpus-may-be-absent", action="store_true",
                    help="the caller asserts this repo need not carry the "
                         "published corpus. Turns 'no corpus discoverable "
                         "anywhere' from UNDETERMINED into NO_CORPUS (rc 0), "
                         "which STATES that 0 run trees were swept. It does "
                         f"NOT excuse a ${_cloc.CORPUS_ENV} that is set and "
                         "broken, and it does NOT excuse the baseline "
                         "register: that lives in this repo, did not move with "
                         "the corpus, and its own arithmetic is still checked.")
    args = ap.parse_args(argv)

    # A POSITIONAL BESIDE --corpus IS A CONTRADICTION, AND IT USED TO BE SILENT.
    #
    # `project_dir` is `nargs="?"`, so an extra path is absorbed with no error
    # even though `--corpus` already chose the other mode. The two are mutually
    # exclusive: one audits ONE project, the other sweeps the published corpus.
    # Accepting both meant one of the operator's two inputs was ignored without
    # a word.
    #
    # MEASURED on a38902d16, and this is the shape that makes it matter. The
    # operator's intent is unmistakable: write the baseline to a scratch file.
    #
    #     $ ...check.py --corpus <empty> --write-baseline <scratch.json>
    #     rc=0
    #     wrote programs/step_internal_fail_bubble_up_baseline.json (findings_total=0)
    #
    # `--write-baseline` is `store_true`, so `<scratch.json>` landed in
    # `project_dir` and was dropped; the write went to the DEFAULT path. The
    # scratch file was untouched and the REAL record was zeroed — the exact
    # destruction vibe-ic#1025 says must never happen, reached by an operator
    # who believed they had aimed somewhere safe. The correct spelling is
    # `--baseline <scratch.json> --write-baseline`.
    #
    # vibe-ic#1098 makes the ZERO-REACH write refuse, which closes the case
    # above. It does not close this one: with a NON-empty corpus the same
    # command still writes the default baseline and still ignores the path the
    # operator named. That is why this is a separate refusal and not a
    # duplicate of that fix.
    #
    # rc 2, not 1: this is "the request was not understood", not "the design
    # failed" — the same tri-state the rest of this program uses.
    if args.corpus and args.project_dir:
        print(f"[REFUSED] both a project_dir ({args.project_dir!r}) and "
              f"--corpus ({args.corpus!r}) were given; they are mutually "
              f"exclusive modes. If you meant to aim the baseline write, that "
              f"is --baseline <path> --write-baseline (--write-baseline is a "
              f"flag and takes no path).", file=sys.stderr)
        return 2

    if args.corpus:
        named = Path(args.corpus)
        bl = Path(args.baseline) if args.baseline else _HERE / BASELINE_NAME
        corpus, origin = _cloc.resolve(named, subdir="ic", gate=GATE,
                                       announce=True)
        if not corpus.is_dir():
            # WAS: `error: not a directory` at rc 2 — one word for three
            # different facts (the corpus moved, the pointer is wrong, nobody
            # said whether it has to be here). See `_corpus_location`.
            rc = _cloc.refuse(GATE, named, corpus, origin,
                              args.corpus_may_be_absent,
                              "published run tree(s)")
            if rc != 0:
                return rc
            if args.write_baseline:
                # A write from a scan that did not happen is the vibe-ic#1025
                # destruction with a friendlier banner: `findings_total` would
                # be rewritten to 0 and the recorded reference point lost.
                print(f"[REFUSED] {GATE}: --write-baseline with no corpus "
                      f"would record findings_total=0 as a measurement and "
                      f"destroy {bl}. NOTHING WAS SWEPT (vibe-ic#1025).",
                      file=sys.stderr)
                return 2
            # NO_CORPUS EXCUSES THE SWEEP, NEVER THE REGISTER.
            return _adjudicate_register_without_a_corpus(bl)
        if origin == _cloc.ENV:
            # `_published_run_trees` reads git's INDEX via `_published_tree`
            # and FALLS BACK TO A DISK WALK when it cannot. Over a corpus that
            # is present but not a checkout, the sweep silently changes
            # population and then ratchets the result against a baseline
            # recorded over the tracked one.
            why = _cloc.not_a_checkout_reason(corpus, "published run trees")
            if why is None:
                # A CHECKOUT THAT TRACKS NOTHING IS THE SAME EMPTY RESULT WITH
                # a `.git` beside it: `_published_tree.published_paths` returns
                # None for "git could not answer" AND for "the index is empty",
                # and `_published_run_trees` sends both to the disk.
                sys.path.insert(0, str(_HERE))
                import _published_tree                  # noqa: PLC0415
                if _published_tree.published_paths(corpus) is None:
                    why = (f"{corpus} is a git checkout that tracks NOTHING, "
                           f"so the published population is empty and "
                           f"`_published_run_trees` would fall back to a disk "
                           f"walk.")
            if why:
                print(f"[{GATE}] UNDETERMINED: {why} `_published_run_trees` "
                      f"would fall back to a disk walk, and a count from that "
                      f"population is not a line to hold against a baseline "
                      f"measured over the tracked one (vibe-ic#1223).",
                      file=sys.stderr)
                return 2
        rep = check_corpus(corpus)
        if args.json:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(rep, indent=2) + "\n")
        now = rep["findings_total"]
        if args.write_baseline:
            # vibe-ic#1025. REFUSE to record a number a sweep did not measure.
            #
            # This check used to live 14 lines BELOW, after the write and its
            # `return 0`, so `--write-baseline` against a corpus this gate
            # cannot reach rewrote the record to zero and reported success.
            # MEASURED on 947547716, real baseline copied to a temp file:
            #
            #     before: findings_total=7 runs_swept=17 per_run=4
            #     $ ... --corpus <empty> --baseline <copy> --write-baseline
            #     rc=0   "wrote <copy> (findings_total=0)"
            #     after:  findings_total=0 runs_swept=0  per_run=0
            #
            # The issue names this danger in prose — "would record a
            # shrink-to-zero that measured nothing ... and would permanently
            # destroy the 7 recorded findings as a reference point" — and prose
            # was the ONLY thing preventing it. The ratchet's own doctrine is
            # MAY ONLY SHRINK; a zero written from zero reach satisfies that
            # rule while proving the opposite of what the rule exists to prove.
            #
            # No `--force`. An escape hatch here would put the same destroy one
            # flag away and make the refusal advisory, which is the shape this
            # gate exists to argue against. The way to write a baseline is to
            # fix the reach first — that is what makes the number a measurement.
            if rep["runs_with_reports"] == 0:
                print(f"REFUSED: the sweep reached {rep['runs_swept']} published "
                      f"run tree(s) and {rep['runs_with_reports']} with a "
                      f"reports/ directory, so it examined NOTHING. Writing a "
                      f"baseline from it would record findings_total={now} as a "
                      f"measurement and destroy the recorded reference point. "
                      f"Fix the corpus/reach first, then re-run "
                      f"--write-baseline (vibe-ic#1025).", file=sys.stderr)
                return 2
            # CARRY THE WITHDRAWALS FORWARD (vibe-ic#1202).
            #
            # This rewrite is the erasure. The shrink branch below tells the
            # operator to run exactly this command, and as written it drops any
            # run that left the published corpus straight out of `per_run`. The
            # next reader sees only a smaller number, indistinguishable from
            # work somebody did. MEASURED at `94c7572aa`: 7 -> 5, both missing
            # runs withdrawn rather than repaired, nothing left in the file to
            # say so.
            #
            # The ledger is SEPARATE from `per_run` and is NOT summed into
            # `findings_total`, deliberately. `findings_total` is the ceiling
            # over the PUBLISHED corpus; folding unpublished debt into it would
            # keep the ceiling high on runs the sweep cannot reach, which is
            # the stale-entry defect vibe-ic#1025 part 3 removed and
            # `test_issue1025_baseline_names_runs_that_exist` now pins. So this
            # register does not gate. It refuses to let the number be read as
            # work, which is the only thing #1202 asks of it.
            #
            # It ACCUMULATES, because a run withdrawn twice is still one
            # unexamined finding — and it FORGETS a run that comes back, below,
            # because a run the sweep can reach again is counted in `per_run`
            # and would otherwise be carried in both registers at once.
            prev = _load_baseline(bl)
            withdrawn = dict(prev["withdrawn_unexamined"]) if prev else {}
            if prev:
                split = _decompose_shrink(prev, rep)
                for run, n in split["withdrawn"].items():
                    withdrawn[run] = withdrawn.get(run, 0) + n
            live = {_run_key(k) for k in rep["per_run"]}
            withdrawn = {k: v for k, v in sorted(withdrawn.items())
                         if _run_key(k) not in live}
            doc = {
                "_comment": (
                    "Unacknowledged step-internal FAIL/MISSING reports across "
                    "the PUBLISHED (git-tracked) run trees — a run tree being "
                    "any directory that owns a tracked reports/**/*.json, "
                    "which is what the gate can read, NOT a directory whose "
                    "name matches a convention (vibe-ic#1223). MAY ONLY SHRINK "
                    "UNDER A FIXED POPULATION — each one is a report declaring "
                    "FAIL that no waiver and no orchestrator record names. The "
                    "wrong repair is to loosen the matcher until the number "
                    "falls (vibe-ic#693). `corpus_population` is the root this "
                    "count was taken over and is part of the record: the gate "
                    "refuses to ratchet a count from one population against a "
                    "sweep of another."),
                "_withdrawn_comment": (
                    "Findings that left findings_total because their run left "
                    "the published corpus (or stopped carrying a reports/ "
                    "tree), NOT because anyone examined them (vibe-ic#1202). "
                    "Recorded so a fall in findings_total can never be read as "
                    "debt paid. These reports still declare FAIL. NOT part of "
                    "findings_total and not a ceiling on anything — the "
                    "ratchet is over the published corpus only."),
                "findings_total": now,
                # vibe-ic#1223 — WHICH population produced this count. Without
                # it the integer below is comparable to anything.
                "corpus_population": _population_key(corpus, origin),
                "runs_swept": rep["runs_swept"],
                "runs_with_reports": rep["runs_with_reports"],
                "per_run": rep["per_run"],
                "withdrawn_unexamined": withdrawn,
            }
            # A HAND-WRITTEN PROVENANCE NOTE IS PART OF THE RECORD TOO
            # (vibe-ic#1202, same rule as the ledger above). The shipped
            # baseline carries `_withdrawn_provenance`, which explains how its
            # two withdrawn entries were derived; the writer does not author
            # that key, so the command the gate TELLS the operator to run
            # deleted it. Any `_`-prefixed key this writer does not itself
            # produce is carried forward instead of dropped. Only `_` keys, so
            # a stale MEASUREMENT can never survive a re-record.
            if prev:
                for k, v in prev.items():
                    if k.startswith("_") and k not in doc:
                        doc[k] = v
            bl.write_text(json.dumps(doc, indent=2) + "\n")
            print(f"wrote {bl} (findings_total={now}, "
                  f"population={_population_key(corpus, origin)}, "
                  f"withdrawn_unexamined={sum(withdrawn.values())})")
            return 0
        base_doc = _load_baseline(bl)
        base = base_doc["findings_total"] if base_doc else None
        print(f"corpus sweep: {rep['runs_swept']} published run tree(s), "
              f"{rep['runs_with_reports']} with a reports/ tree, "
              f"{now} unacknowledged step-internal FAIL(s)")
        if rep["runs_with_reports"] == 0:
            print("VACUOUS_PASS: no published run tree carries a reports/ "
                  "directory — the sweep examined nothing.")
            return 2
        if base is None:
            print(f"[NOT CHECKED] no baseline at {bl} — record one with "
                  f"--write-baseline before this can ratchet.")
            return 2
        # vibe-ic#1223 — a recorded count is only a line to hold over the set it
        # was measured on. See :func:`_population_key`: 22 over
        # `benchmark-data/ic` and 45 over `benchmark-data`, same commit. rc 2,
        # the "could not determine" tier this program already uses, because
        # neither PASS nor FAIL is an honest answer about a population that was
        # never examined. A baseline written before this key existed carries
        # None, which means "I do not know what it was measured over" and is
        # left to ratchet exactly as it did — silently reinterpreting an old
        # record as agreeing would be the assumption this guard removes.
        want_pop = _population_key(corpus, origin)
        have_pop = base_doc.get("corpus_population")
        if isinstance(have_pop, str) and have_pop != want_pop:
            print(f"[NOT CHECKED] the baseline at {bl} was measured over "
                  f"'{have_pop}' and this sweep covered '{want_pop}' — a count "
                  f"over one population is not a line to hold over another. "
                  f"Sweep the recorded population, or re-record with "
                  f"--corpus <root> --write-baseline (vibe-ic#1223).")
            return 2
        for run, n in sorted(rep["per_run"].items()):
            print(f"   {run}: {n}")
        # DISCLOSE THE LEDGER ON EVERY SWEEP (vibe-ic#1202). A register only
        # ever written and never printed is a register nobody reads, and this
        # one exists precisely so a past shrink cannot be mistaken for work.
        # It carries no rc — see the write branch for why it must not gate.
        carried = base_doc["withdrawn_unexamined"]
        if carried:
            print(f"   (plus {sum(carried.values())} finding(s) in "
                  f"withdrawn_unexamined across {len(carried)} run(s) that "
                  f"left the sweep WITHOUT being examined; not counted above, "
                  f"still declaring FAIL)")
            for run, n in sorted(carried.items()):
                print(f"      withdrawn {run}: {n}")
        if now > base:
            print(f"[FAIL] unacknowledged step-internal FAILs GREW "
                  f"{base} -> {now}: a step shipped a verdict=FAIL report that "
                  f"no waiver and no orchestrator record names.")
            return 1
        if now < base:
            # A PAID DEBT THAT STAYS ON THE REGISTER IS SLACK, NOT A PASS
            # (vibe-ic#1025). This used to print the same sentence and return
            # 0, so nothing ever forced the number down: the baseline sat at 7
            # while the sweep measured 5, and the gate would then have called a
            # regrowth back to 7 "no NEW". Two findings of permission, granted
            # by a suggestion nobody was obliged to act on.
            #
            # This repo has already ruled on the shape one gate over.
            # `evidence_citation_resolves_check` FAILS on "entries the baseline
            # claims are broken but that now resolve — the debt was paid and
            # the register must be updated, else the register slowly turns into
            # permission". Same register, same rule.
            #
            # Non-zero, and it names the one action that clears it. The
            # ratchet may only shrink, and now it must.
            #
            # WHICH OF THE TWO HAPPENED IS THE FINDING, NOT THE ARITHMETIC
            # (vibe-ic#1202). `{base - now} of them are PAID` is a claim about
            # work, and a fall earns it only when somebody looked. A run that
            # left the published corpus, or kept its place and lost its
            # `reports/` tree, subtracts from this number without anyone having
            # read a line of it — those reports still declare FAIL. The rc is
            # unchanged (1) and the required action is unchanged: the ratchet
            # must still come down, because a paid debt left on the register is
            # permission for the number to grow back. What changes is that the
            # re-record now WRITES THE WITHDRAWAL DOWN instead of erasing it,
            # and this text stops calling it work.
            split = _decompose_shrink(base_doc, rep)
            for run, (was, is_now) in sorted(split["repaired"].items()):
                print(f"   REPAIRED  {run}: {was} -> {is_now}")
            for run, n in sorted(split["withdrawn"].items()):
                print(f"   WITHDRAWN {run}: {n} finding(s) left the count "
                      f"without being examined — the run is no longer swept "
                      f"with a reports/ tree")
            for run, n in sorted(split["unknown"].items()):
                print(f"   UNKNOWN   {run}: {n} finding(s); this baseline "
                      f"predates examined_runs, so the fall cannot be "
                      f"attributed")
            if split["withdrawn_total"] and not split["repaired_total"]:
                head = (f"NONE of it is repair: {split['withdrawn_total']} "
                        f"finding(s) left because their run stopped being "
                        f"swept with a reports/ tree, not because anyone "
                        f"examined them")
            elif split["withdrawn_total"]:
                head = (f"{split['repaired_total']} repaired and "
                        f"{split['withdrawn_total']} withdrawn without being "
                        f"examined; only the first is debt paid")
            else:
                head = f"{base - now} of them are PAID and still on the register"
            print(f"[FAIL] the recorded baseline claims {base} unacknowledged "
                  f"step-internal FAIL(s) and the sweep measures {now}: "
                  f"{head}. A register that keeps a settled entry is "
                  f"permission for the number to grow back to it unnoticed. "
                  f"Re-record it with --write-baseline, which carries any "
                  f"withdrawal into `withdrawn_unexamined` so the drop is not "
                  f"later read as work somebody did; the ratchet may only "
                  f"shrink, and it must.")
            return 1
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
