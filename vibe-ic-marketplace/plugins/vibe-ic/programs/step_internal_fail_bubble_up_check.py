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
    records no `previous_*` count at all             -> UNDETERMINED (rc 2)
    `findings_total` != sum(`per_run`)               -> FAIL (rc 1)
    a recorded count FELL with no `shrink_reason`    -> FAIL (rc 1)
    a `shrink_reason` on a register that fell nowhere -> FAIL (rc 1)
    consistent                                       -> rc 0, printing what it
                                                        holds and stating that
                                                        nothing was re-measured

AND THE CEILING MAY NOT FALL WHILE NOBODY IS ON RECORD (vibe-ic#1704)
---------------------------------------------------------------------
The ratchet's rule is MAY ONLY SHRINK, and until #1704 the shrink direction was
the unguarded one. Every guard over the register compares it against a fresh
sweep, and the prescribed repair — `--write-baseline` — re-derives the register
FROM that same sweep, so the two agree by construction the moment anyone runs
it. MEASURED against the published corpus at v1.10.69: one argument-free command
moved `findings_total` 22 -> 1 and the denominator 16/16 -> 4/4, and every test
over this file went green.

So the writer now records `previous_findings_total`, `previous_runs_swept`,
`previous_runs_with_reports` and the `shrink_reason` that authorised the fall,
and refuses to lower any of the three without one. The reader re-checks the
writer's own rule against the recorded numbers — a register is a plain JSON
file, so the writer was never the only way to change it (the #922 lesson, one
register over).

AND ONE SMALLER INTEGER HAS THREE CAUSES. Findings somebody examined and
repaired, run trees that stopped publishing reports, and run trees that are not
in the swept corpus at all are three different facts, and `_decompose_shrink`
separates the two it can observe from each other and from the one it cannot —
see there. What a sweep of ONE corpus cannot tell apart, it does not name; the
operator names it in `shrink_reason`.

Usage:
    python3 step_internal_fail_bubble_up_check.py <project_dir>
                                                   [--json <out>] [--strict]
    python3 step_internal_fail_bubble_up_check.py --corpus benchmark-data/ic
                                                   [--baseline <f>] [--write-baseline]
                                                   [--shrink-reason <why>]
                                                   [--corpus-may-be-absent]

Exit codes:
    0  PASS — reports were examined and every FAIL/MISSING one is
       acknowledged; also a report-only run, or a corpus at-or-below baseline,
       or NO_CORPUS (opted in, and it says 0 run trees were swept)
    1  FAIL — an unacknowledged FAIL in PROJECT mode (or under --strict), or
       corpus GROWTH, or a register whose own numbers contradict each other, or
       a register whose counts fell with no written reason (vibe-ic#1704)
    2  NOT EXAMINED (nothing to look at), UNDETERMINED (the corpus could not be
       resolved, or a corpus pointer that is set and wrong), or argument / I/O
       error

chip-AGNOSTIC. No vendor / IC / specific filename hardcoded.
"""
from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _corpus_location as _cloc                    # noqa: E402
import _routed_checker_progress as _routed_progress  # noqa: E402
import _semantic_child_progress as _semantic_progress  # noqa: E402

GATE = "step_internal_fail_bubble_up_check"
PROGRESS_SCOPE = "routed-def:step-internal-fail-bubble-up"
_ACTIVE_INPUT_PLAN: Optional[_routed_progress.FiniteInputPlan] = None
_ACTIVE_PROJECT_ROOT: Optional[Path] = None
_ACTIVE_REPORTS_PRESENT: Optional[bool] = None


def _read_input_text(path: Path, *, encoding: str = "utf-8",
                     errors: str = "strict") -> str:
    if _ACTIVE_INPUT_PLAN is not None:
        return _ACTIVE_INPUT_PLAN.text_for(
            path, encoding=encoding, errors=errors)
    return Path(path).read_text(encoding=encoding, errors=errors)


def _is_project_json(relative: str) -> bool:
    return (relative == "waivers.json"
            or (relative.startswith("reports/")
                and relative.endswith(".json")))


def _input_plan(
        project: Path,
) -> Tuple[_routed_progress.FiniteInputPlan, bool, Path]:
    project = Path(project)
    index = _routed_progress.IndexSnapshot(project)
    disk: List[Path] = []
    project = index.root
    waiver = project / "waivers.json"
    if waiver.exists():
        disk.append(waiver)
    reports = project / "reports"
    try:
        reports_stat = reports.lstat()
    except FileNotFoundError:
        reports_present = False
        reports_unit = "reports-state:absent"
    except OSError as exc:
        raise _semantic_progress.ProgressProtocolError(
            f"step FAIL reports directory cannot be inspected: {exc}") from exc
    else:
        if stat.S_ISLNK(reports_stat.st_mode):
            raise _semantic_progress.ProgressProtocolError(
                f"step FAIL reports directory is a symlink: {reports}")
        reports_present = stat.S_ISDIR(reports_stat.st_mode)
        reports_unit = (
            f"reports-state:{'directory' if reports_present else 'other'}:"
            f"mode:{stat.S_IFMT(reports_stat.st_mode):o}:"
            f"dev:{reports_stat.st_dev}:ino:{reports_stat.st_ino}:"
            f"mtime:{reports_stat.st_mtime_ns}:ctime:{reports_stat.st_ctime_ns}")
    if reports_present:
        disk.extend(sorted(reports.rglob("*.json")))
    inputs = index.select(
        _is_project_json, disk,
        population="step FAIL acknowledgement JSON population")
    plan = _routed_progress.FiniteInputPlan(
        [index.population_unit("step-fail-bubble-up:git-index"),
         reports_unit],
        _routed_progress.planned_reads("project-json", inputs))
    return plan, reports_present, project


def semantic_progress_units(cell: Path) -> List[str]:
    """Trusted parent's exact finite manifest for the default cell argv."""
    return _input_plan(Path(cell))[0].units

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
        return json.loads(_read_input_text(p, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _waiver_text_corpus(project: Path) -> str:
    """Concatenate searchable text from every waiver entry. Used to
    test name-candidate substring matches."""
    waivers_path = project / "waivers.json"
    if (_ACTIVE_INPUT_PLAN is not None
            and not _ACTIVE_INPUT_PLAN.contains(waivers_path)):
        return ""
    if (_ACTIVE_INPUT_PLAN is None and not waivers_path.is_file()):
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
    if _ACTIVE_INPUT_PLAN is not None:
        for path in _ACTIVE_INPUT_PLAN.paths("project-json"):
            try:
                relative = path.relative_to(project)
            except ValueError:
                continue
            if (relative == Path("reports/phase23_completion_audit.json")
                    or (len(relative.parts) >= 3
                        and relative.parts[:2]
                        in (("reports", "orchestrator"),
                            ("reports", "audit")))):
                candidates.append(path)
        candidates.sort()
    else:
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
            txt = _read_input_text(p, encoding="utf-8")
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
    if _ACTIVE_INPUT_PLAN is not None:
        out = []
        for p in _ACTIVE_INPUT_PLAN.paths("project-json"):
            try:
                rel = p.relative_to(project)
            except ValueError:
                continue
            if (not rel.parts or rel.parts[0] != "reports"
                    or len(rel.parts) < 2
                    or rel.parts[1] in ("audit", "orchestrator")):
                continue
            out.append(p)
        return sorted(out)
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
    if _ACTIVE_INPUT_PLAN is None and not project.is_dir():
        return "NOT_EXAMINED", [], 0
    reports_present = (_ACTIVE_REPORTS_PRESENT
                       if _ACTIVE_INPUT_PLAN is not None else
                       (project / "reports").is_dir())
    if not reports_present:
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


def resolve_corpus_population(named: Path, *, announce: bool = False
                              ) -> Tuple[Path, str]:
    """Resolve the cell population using this gate's actual corpus contract.

    ``VIBE_IC_BENCHMARK_DATA`` names the root of the external corpus, while
    this gate sweeps its ``ic`` population.  Keep that translation beside the
    production consumer so tests and CLI callers cannot each reconstruct it
    from a checkout directory name.
    """
    return _cloc.resolve(Path(named), subdir="ic", gate=GATE,
                         announce=announce)


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
    for key in ("per_run", "withdrawn_unexamined", "absent_from_corpus"):
        d[key] = d[key] if isinstance(d.get(key), dict) else {}
    return d


def _prev_int(prev: Optional[Dict[str, Any]], key: str) -> Optional[int]:
    """A recorded count from the register being replaced, or None.

    None means "the register did not state this", which is not the same as zero
    and must never ratchet as one: a missing `runs_swept` on an older document
    is an absence of a statement, and :func:`_shrink_provenance_defects` skips a
    None rather than reading it as a fall from nothing.
    """
    if not prev:
        return None
    v = prev.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else None


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


#: What counts as a WRITTEN reason for LOWERING this register (vibe-ic#1704).
#: The writer demands it of `--shrink-reason` and the reader re-checks the
#: recorded `shrink_reason` against the same constant, so the two sides cannot
#: drift into disagreeing about what a written reason is — the coupling
#: `published_record_staleness_check.SCOPE_REASON_MIN_CHARS` already holds for
#: that register's growth (vibe-ic#922).
#:
#: LONGER THAN THAT ONE, DELIBERATELY. A growth reason names a rule that newly
#: adjudicates. A shrink reason has to name WHICH of three facts moved the
#: number — findings that were examined and repaired, run trees that stopped
#: being published, or a population that was never in the swept corpus — and no
#: 30-character string says that.
#:
#: AND THIS MEASURES THAT A REASON WAS WRITTEN, NOT THAT IT IS TRUE. A length is
#: the only property of free prose a program can check; what it buys is that the
#: number cannot fall while nobody is on record. That is the whole claim, and it
#: is the claim the message prints.
SHRINK_REASON_MIN_CHARS = 60


def _run_tree_is_in(corpus: Path, run: str) -> bool:
    """Can THIS sweep open the run tree the register names?

    `_run_key` has already dropped a leading `ic/`, and a caller may name either
    the cell tree or its parent as `--corpus`, so both spellings are tried — the
    same both-ways match `test_issue1025_baseline_names_runs_that_exist` makes
    against the tree.

    A directory that is present but carries no `reports/` is still IN the
    corpus: the sweep opened it and can state that it publishes nothing this
    gate reads. A directory that is not there at all was not opened, and the
    difference is the whole of :func:`_decompose_shrink`'s fourth bucket.
    """
    rel = str(run).strip("/")
    if not rel:
        return False
    return (corpus / rel).is_dir() or (corpus / "ic" / rel).is_dir()


def _decompose_shrink(base: Dict[str, Any],
                      rep: Dict[str, Any],
                      corpus: Optional[Path] = None) -> Dict[str, Any]:
    """Split a fall in the count into REPAIRED, WITHDRAWN and NOT-IN-CORPUS.

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
        not in `examined_runs`,          -> WITHDRAWN. The sweep opened the run
        tree still under the corpus         tree and it no longer publishes a
                                            reports/ file this gate reads.
        not under the corpus at all      -> NOT IN CORPUS. The sweep never
                                            opened it, and it cannot say why.

    AND THE FOURTH BUCKET IS THE ONE vibe-ic#1704 IS ABOUT. Until it existed,
    every run absent from `examined_runs` was called WITHDRAWN and filed under
    `withdrawn_unexamined`, whose own `_withdrawn_comment` asserts "These
    reports still declare FAIL." That is a present-tense claim about documents
    the sweep did not open — the instrument measured "this key is not in my
    result" and the record reported "this run left the corpus carrying an
    unexamined failure".

    The two are not the same fact, and #1704 says so in the case that forced
    it: a denominator that falls from 16 to 4 because cells were never
    published into the swept corpus is a different fact from one that falls
    because cells were deleted from it, "and the record should say which". A
    sweep of ONE corpus cannot tell those apart — that needs history the gate
    does not have — so it must not pick one. What it CAN measure is whether the
    run tree is there to be opened, and that is the line drawn here. Which of
    removal and never-published actually happened is stated by the operator in
    `shrink_reason`, where a claim beyond the instrument belongs.

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
    # The root that was actually swept, preferred from the report the sweep
    # wrote so a caller cannot decompose one corpus against a probe of another.
    if corpus is None and isinstance(rep.get("corpus"), str):
        corpus = Path(rep["corpus"])

    repaired: Dict[str, Any] = {}
    withdrawn: Dict[str, int] = {}
    absent: Dict[str, int] = {}
    unknown: Dict[str, int] = {}
    for run, was in base_runs.items():
        now = now_runs.get(run, 0)
        if now >= was:
            continue
        if examined_keys is None:
            unknown[run] = was - now
        elif run in examined_keys:
            repaired[run] = (was, now)
        elif corpus is not None and not _run_tree_is_in(corpus, run):
            absent[run] = was - now
        else:
            # Either the tree IS there without a reports/ file this gate reads,
            # or no corpus root was available to ask. The second is the caller's
            # omission and keeps the pre-#1704 reading, which never over-claims
            # in the direction of "repaired".
            withdrawn[run] = was - now
    return {
        "repaired": repaired,
        "withdrawn": withdrawn,
        "absent": absent,
        "unknown": unknown,
        "repaired_total": sum(was - now for was, now in repaired.values()),
        "withdrawn_total": sum(withdrawn.values()),
        "absent_total": sum(absent.values()),
        "unknown_total": sum(unknown.values()),
    }


def _shrink_provenance_defects(doc: Dict[str, Any]) -> List[str]:
    """Could `--write-baseline` have produced these numbers? (vibe-ic#1704)

    THE RATCHET LIVED ENTIRELY INSIDE THE COMPARISON, and the comparison is the
    record against itself. `findings_total`, `runs_swept` and
    `runs_with_reports` were re-derivable at any time by one command with no
    argument, and every guard over this file then measured that the new numbers
    agree with the new sweep — which they do by construction. Nothing anywhere
    asked why the number moved, so "MAY ONLY SHRINK UNDER A FIXED POPULATION"
    was enforced only in the direction that grows.

    That is the same hole `published_record_staleness_check` closed for its own
    register in vibe-ic#922, entered from the other side: there the writer
    refused unjustified GROWTH while the reader took the file as given; here
    both directions of a SHRINK were free.

    So the writer now records the counts it moved FROM beside the counts it
    wrote, plus the reason it was allowed to lower them, and this re-checks the
    writer's own rule against those recorded numbers on the read path. A number
    lowered by hand leaves `previous_*` behind and is caught; lowering
    `previous_*` too requires forging coupled counts AND writing a reason, which
    is a deliberate false statement rather than an omission nothing measures.

    Returns the sentences of a DEFINITE defect (rc 1). "This register predates
    the fields" is a different answer and is :func:`_register_predates_shrink_ledger`.
    """
    out: List[str] = []
    reason = doc.get("shrink_reason")
    reason_ok = (isinstance(reason, str)
                 and len(reason.strip()) >= SHRINK_REASON_MIN_CHARS)
    if reason is not None and not reason_ok:
        out.append(
            f"records a `shrink_reason` that is not a written reason "
            f"(>= {SHRINK_REASON_MIN_CHARS} chars): {reason!r}. The writer "
            f"refuses one this short.")

    fell: List[str] = []
    for now_key, prev_key in (("findings_total", "previous_findings_total"),
                              ("runs_swept", "previous_runs_swept"),
                              ("runs_with_reports",
                               "previous_runs_with_reports")):
        prev = doc.get(prev_key)
        if prev is None:
            continue                      # the first write records no "from"
        if not isinstance(prev, int) or isinstance(prev, bool):
            out.append(f"has a non-integer `{prev_key}` ({prev!r}).")
            continue
        cur = doc.get(now_key)
        if not isinstance(cur, int) or isinstance(cur, bool):
            out.append(f"has a non-integer `{now_key}` ({cur!r}).")
            continue
        if cur < prev:
            fell.append(f"{now_key} {prev} -> {cur}")

    if fell and not reason_ok:
        out.append(
            f"lowered {', '.join(fell)} with no written `shrink_reason`. A "
            f"shrink-only register makes every drop irreversible here, so the "
            f"number may not fall while nobody is on record for WHY — "
            f"findings examined and repaired, run trees that stopped being "
            f"published, and a population never in the swept corpus are three "
            f"different facts behind the same smaller integer "
            f"(vibe-ic#1704). --write-baseline exits 1 on exactly this, so a "
            f"register in this state did not come from it.")
    # A REASON IS SPENT BY THE WRITE THAT USED IT (the #922 rule, same words).
    # Left standing on a write that lowered nothing it becomes a permanent
    # authorisation for whatever drop comes next, reducing the forgery to a
    # single number.
    if reason is not None and not fell:
        out.append(
            "records a `shrink_reason` on a register whose recorded numbers "
            "did not fall. The writer records the reason only for the write it "
            "authorised; one kept past that write is a standing authorisation "
            "for a drop nobody has justified yet.")
    return out


def _register_predates_shrink_ledger(doc: Dict[str, Any]) -> bool:
    """True when the register carries none of the counts it moved FROM.

    NOT waved through as "nothing to check": that is exactly the state a hand
    edit produces once someone notices the fields, so reading it as clean would
    reopen the hole one key over. It is also not a FAIL — the register may
    simply be older than #1704 — so callers answer NOT DETERMINED and name the
    repair, which is `--write-baseline` over a corpus that reaches.
    """
    return all(k not in doc for k in ("previous_findings_total",
                                      "previous_runs_swept",
                                      "previous_runs_with_reports"))


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
    # THE SHRINK LEDGER IS CHECKABLE WITH NO CORPUS TOO (vibe-ic#1704), and for
    # the same reason the sum is: the writer produces `previous_*`,
    # `shrink_reason` and the counts together, so a document it could not have
    # written is visible without opening a single cell. Lowering the ceiling by
    # hand is the widening of #1015 spelled the other way round, and NO_CORPUS
    # excuses the sweep, never the register.
    if _register_predates_shrink_ledger(doc):
        print(f"[NOT CHECKED] {GATE}: no corpus was swept, and {bl} records "
              f"none of `previous_findings_total`, `previous_runs_swept`, "
              f"`previous_runs_with_reports`, so there is no statement of what "
              f"these numbers moved FROM and no way to tell a re-derivation "
              f"from a hand-lowered ceiling. Re-record with --write-baseline "
              f"over a corpus that reaches (vibe-ic#1704).", file=sys.stderr)
        return 2
    defects = _shrink_provenance_defects(doc)
    if defects:
        for d in defects:
            print(f"[FAIL] {GATE}: the register at {bl} {d}", file=sys.stderr)
        return 1
    carried = sum(v for v in doc["withdrawn_unexamined"].values()
                  if isinstance(v, int))
    stranded = sum(v for v in doc["absent_from_corpus"].values()
                   if isinstance(v, int))
    print(f"[{GATE}] register: findings_total={total} over "
          f"'{pop}' ({len(per_run)} run(s) named, sum agrees), plus "
          f"{carried} withdrawn_unexamined still declaring FAIL and "
          f"{stranded} in absent_from_corpus that no sweep has opened.",
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
    ap.add_argument("--shrink-reason", default=None, metavar="WHY",
                    help="the written reason this write is allowed to LOWER "
                         "findings_total, runs_swept or runs_with_reports. "
                         "Required for such a write and recorded beside the "
                         "new numbers, because a shrink-only register makes "
                         "every drop irreversible and the three facts that "
                         "produce a smaller integer — findings repaired, run "
                         "trees withdrawn, a population never in the swept "
                         "corpus — are not the same fact (vibe-ic#1704).")
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

    global _ACTIVE_INPUT_PLAN, _ACTIVE_PROJECT_ROOT, _ACTIVE_REPORTS_PRESENT
    with _semantic_progress.child_progress(PROGRESS_SCOPE) as progress:
        try:
            if progress.enabled:
                if (args.project_dir is None or args.json is not None
                        or args.strict or args.corpus is not None
                        or args.baseline is not None or args.write_baseline
                        or args.corpus_may_be_absent
                        or args.shrink_reason is not None):
                    raise _semantic_progress.ProgressProtocolError(
                        "routed parent progress covers the positional project "
                        "audit only")
                project = Path(args.project_dir)
                if not project.is_dir():
                    raise _semantic_progress.ProgressProtocolError(
                        "routed parent project input is not a directory")
                (_ACTIVE_INPUT_PLAN, _ACTIVE_REPORTS_PRESENT,
                 _ACTIVE_PROJECT_ROOT) = _input_plan(project)
                _ACTIVE_INPUT_PLAN.materialize(progress)
            rc = _main_parsed(args)
            if _ACTIVE_INPUT_PLAN is not None:
                fresh_plan, _, _ = _input_plan(Path(args.project_dir))
                _ACTIVE_INPUT_PLAN.checkpoint_decision(fresh_plan=fresh_plan)
            return rc
        finally:
            _ACTIVE_INPUT_PLAN = None
            _ACTIVE_PROJECT_ROOT = None
            _ACTIVE_REPORTS_PRESENT = None


def _main_parsed(args) -> int:

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

    # A REASON WITH NO WRITE AUTHORISES NOTHING, AND SAYING SO IS THE POINT.
    # Accepted silently it reads as "the shrink was justified" to whoever typed
    # it, while the register on disk is untouched — a statement believed to be
    # in force that never was, which is the ambiguity `_corpus_location` refuses
    # in the other direction. rc 2: the request was not understood.
    if args.shrink_reason is not None and not args.write_baseline:
        print(f"[REFUSED] {GATE}: --shrink-reason is the justification carried "
              f"by a --write-baseline that LOWERS a recorded count. Given "
              f"without it, nothing is written and nothing is authorised "
              f"(vibe-ic#1704).", file=sys.stderr)
        return 2

    if args.corpus:
        named = Path(args.corpus)
        bl = Path(args.baseline) if args.baseline else _HERE / BASELINE_NAME
        corpus, origin = resolve_corpus_population(named, announce=True)
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
            # THE SECOND LEDGER, and it is second because it is a DIFFERENT
            # claim (vibe-ic#1704). `withdrawn_unexamined` says the run tree is
            # in the corpus and stopped publishing reports this gate reads —
            # something the sweep opened the directory and saw. A run tree that
            # is not under the swept corpus at all was never opened, so no
            # sentence about what its reports say today is a measurement. Both
            # are "not repaired"; only one of them is observed.
            absent = dict(prev["absent_from_corpus"]) if prev else {}
            # Decomposed ONCE. Both ledgers and the refusal message below read
            # the same split, so the tree is walked once and the sentence the
            # operator sees cannot describe a different attribution from the one
            # a successful write would record.
            split = _decompose_shrink(prev, rep, corpus) if prev else {}
            if prev:
                for run, n in split["withdrawn"].items():
                    withdrawn[run] = withdrawn.get(run, 0) + n
                for run, n in split["absent"].items():
                    absent[run] = absent.get(run, 0) + n
            live = {_run_key(k) for k in rep["per_run"]}
            withdrawn = {k: v for k, v in sorted(withdrawn.items())
                         if _run_key(k) not in live}
            # DISJOINT BY CONSTRUCTION. A run can only ever leave `per_run`
            # once per write, so the decomposition cannot file it in both — but
            # a run that left, came back and left again by the OTHER route
            # could accumulate in both across writes, and one finding counted
            # twice is exactly the double-attribution these ledgers exist to
            # prevent. `withdrawn_unexamined` wins because it is the observed
            # one; a run whose tree the sweep can still open is not absent.
            absent = {k: v for k, v in sorted(absent.items())
                      if _run_key(k) not in live
                      and k not in withdrawn}
            # THE NUMBER MAY NOT FALL WHILE NOBODY IS ON RECORD (vibe-ic#1704).
            #
            # `--write-baseline` is what the shrink branch below TELLS the
            # operator to run, and until now it silently re-derived every count
            # from the current sweep. Measured against the published corpus at
            # v1.10.69 the one command lowered findings_total 22 -> 1 and the
            # denominator 16/16 -> 4/4, and every guard over this file then
            # passed, because each one compares the new record against the same
            # new sweep. A ratchet whose ceiling can be lowered by an
            # argument-free command is a ratchet in one direction only.
            #
            # The DENOMINATOR is ratcheted beside the numerator deliberately.
            # `findings_total` alone cannot tell "the failures were fixed" from
            # "the runs carrying them are no longer swept", which is precisely
            # what #1015 pinned and what a 16 -> 4 population change does to
            # this register.
            #
            # No `--force`, for the reason the zero-reach refusal above gives:
            # an escape hatch makes the refusal advisory. The way to lower this
            # register is to say why.
            lowered = []
            for label, cur, was in (
                    ("findings_total", now, _prev_int(prev, "findings_total")),
                    ("runs_swept", rep["runs_swept"],
                     _prev_int(prev, "runs_swept")),
                    ("runs_with_reports", rep["runs_with_reports"],
                     _prev_int(prev, "runs_with_reports"))):
                if was is not None and cur < was:
                    lowered.append(f"{label} {was} -> {cur}")
            reason = args.shrink_reason
            if lowered and not (isinstance(reason, str)
                                and len(reason.strip())
                                >= SHRINK_REASON_MIN_CHARS):
                for run, n in sorted(split.get("withdrawn", {}).items()):
                    print(f"  (withdrawn, tree still in the corpus without a "
                          f"reports/ file this gate reads) {run}: {n}",
                          file=sys.stderr)
                for run, n in sorted(split.get("absent", {}).items()):
                    print(f"  (not under the swept corpus at all, never "
                          f"opened) {run}: {n}", file=sys.stderr)
                print(f"[FAIL] {GATE}: refusing to LOWER the register "
                      f"({'; '.join(lowered)}) with no --shrink-reason. This "
                      f"register MAY ONLY SHRINK, so every drop it records is "
                      f"irreversible here, and three different facts produce a "
                      f"smaller integer: findings somebody examined and "
                      f"repaired, run trees that stopped being published, and "
                      f"a population that was never in the swept corpus. The "
                      f"record must say which. Re-run with --shrink-reason "
                      f"'<why>' (>= {SHRINK_REASON_MIN_CHARS} chars), which is "
                      f"written into the register beside the new numbers "
                      f"(vibe-ic#1704).", file=sys.stderr)
                return 1
            if reason is not None and not lowered:
                print(f"[FAIL] {GATE}: --shrink-reason was given but this "
                      f"write lowers nothing (findings_total {now}, "
                      f"{rep['runs_swept']} swept, "
                      f"{rep['runs_with_reports']} with reports/). Recording "
                      f"it anyway would leave a standing authorisation for the "
                      f"next drop, which is the shape vibe-ic#922 refuses one "
                      f"register over.", file=sys.stderr)
                return 1
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
                "_absent_comment": (
                    "Findings whose run tree is NOT UNDER THE SWEPT CORPUS at "
                    "all, so this gate never opened it (vibe-ic#1704). "
                    "Separate from withdrawn_unexamined, which names run trees "
                    "the sweep DID open and found publishing no reports/ file "
                    "it reads. Whether these were removed from publication or "
                    "were never published into this corpus is not something a "
                    "sweep of one corpus can tell; `shrink_reason` is where "
                    "that is stated by whoever looked. NOT part of "
                    "findings_total and not a ceiling on anything."),
                "findings_total": now,
                # vibe-ic#1223 — WHICH population produced this count. Without
                # it the integer below is comparable to anything.
                "corpus_population": _population_key(corpus, origin),
                "runs_swept": rep["runs_swept"],
                "runs_with_reports": rep["runs_with_reports"],
                # WHAT THIS WRITE MOVED THE NUMBERS FROM (vibe-ic#1704). The
                # numerator alone was re-derivable by one argument-free command
                # and every guard then compared the new record against the new
                # sweep, which agree by construction. Recorded here so the read
                # path can ask whether the writer could have produced this
                # document — see `_shrink_provenance_defects`.
                "previous_findings_total": prev["findings_total"] if prev else None,
                "previous_runs_swept": _prev_int(prev, "runs_swept"),
                "previous_runs_with_reports": _prev_int(prev,
                                                        "runs_with_reports"),
                # Recorded ONLY for the write it authorised. Carried past that
                # write it would be a standing permission for the NEXT drop,
                # which is the defect this ratchet exists to refuse (the #922
                # rule, applied to the direction #1704 found open).
                "shrink_reason": args.shrink_reason if lowered else None,
                "per_run": rep["per_run"],
                "withdrawn_unexamined": withdrawn,
                "absent_from_corpus": absent,
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
        # THE REGISTER'S OWN PROVENANCE, BEFORE ANY COMPARISON AGAINST IT
        # (vibe-ic#1704). A ceiling that was lowered with nobody on record is
        # not a line to hold, whichever side of it today's sweep lands on — so
        # this is asked before the count is, exactly as the population check
        # above is.
        if _register_predates_shrink_ledger(base_doc):
            print(f"[NOT CHECKED] the baseline at {bl} records none of "
                  f"`previous_findings_total`, `previous_runs_swept`, "
                  f"`previous_runs_with_reports`, so there is no statement of "
                  f"what its numbers moved FROM and no way to tell a "
                  f"re-derivation from a hand-lowered ceiling. Re-record with "
                  f"--corpus <root> --write-baseline (vibe-ic#1704).")
            return 2
        prov = _shrink_provenance_defects(base_doc)
        if prov:
            for d in prov:
                print(f"[FAIL] the baseline at {bl} {d}")
            return 1
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
        stranded = base_doc["absent_from_corpus"]
        if stranded:
            print(f"   (plus {sum(stranded.values())} finding(s) in "
                  f"absent_from_corpus across {len(stranded)} run(s) whose "
                  f"run tree is not under this corpus at all; never opened by "
                  f"any sweep, so nothing here claims what they say today)")
            for run, n in sorted(stranded.items()):
                print(f"      not in corpus {run}: {n}")
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
            split = _decompose_shrink(base_doc, rep, corpus)
            for run, (was, is_now) in sorted(split["repaired"].items()):
                print(f"   REPAIRED  {run}: {was} -> {is_now}")
            for run, n in sorted(split["withdrawn"].items()):
                print(f"   WITHDRAWN {run}: {n} finding(s) left the count "
                      f"without being examined — the run tree is still under "
                      f"the corpus and no longer publishes a reports/ file "
                      f"this gate reads")
            for run, n in sorted(split["absent"].items()):
                print(f"   NOT IN CORPUS {run}: {n} finding(s) left the count "
                      f"without being examined — the run tree is not under the "
                      f"swept corpus at all, so this sweep cannot tell a run "
                      f"removed from publication from one never published into "
                      f"it, and neither of those is repair")
            for run, n in sorted(split["unknown"].items()):
                print(f"   UNKNOWN   {run}: {n} finding(s); this baseline "
                      f"predates examined_runs, so the fall cannot be "
                      f"attributed")
            # THE HEADLINE NAMES ONLY THE BUCKETS THAT ARE NON-EMPTY, because a
            # "0 finding(s) left because ..." clause reads as a measured
            # population that happened to be empty rather than as a bucket
            # nothing landed in. Where only the observed bucket is populated the
            # sentence is the #1202 one, verbatim, because that case has not
            # changed; the #1704 bucket is named BESIDE it, never folded into it.
            unread = split["withdrawn_total"] + split["absent_total"]
            why = []
            if split["withdrawn_total"]:
                why.append(f"{split['withdrawn_total']} finding(s) left "
                           f"because their run stopped being swept with a "
                           f"reports/ tree")
            if split["absent_total"]:
                why.append(f"{split['absent_total']} finding(s) left because "
                           f"their run tree is not in the swept corpus at all")
            short = []
            if split["withdrawn_total"]:
                short.append(f"{split['withdrawn_total']} withdrawn without "
                             f"being examined")
            if split["absent_total"]:
                short.append(f"{split['absent_total']} whose run tree is not "
                             f"in the swept corpus at all")
            if unread and not split["repaired_total"]:
                head = ("NONE of it is repair: " + " and ".join(why) +
                        ", not because anyone examined them")
            elif unread:
                head = (f"{split['repaired_total']} repaired and "
                        + " and ".join(short) + "; only the first is debt paid")
            else:
                head = f"{base - now} of them are PAID and still on the register"
            # THE REMEDY IS NOT ALWAYS THE ONE THIS ARM WAS WRITTEN FOR.
            # `--write-baseline` is right when the corpus genuinely stopped
            # publishing a run. It is DESTRUCTIVE when the sweep merely stood
            # on a checkout that predates the entry: the population key names
            # the corpus REPOSITORY, not the commit, so an out-of-date clone
            # reaches this branch looking exactly like a withdrawal — and a
            # write there ratchets the register down to what that checkout
            # happens to carry and seals the result. MEASURED at e9ec0ce1c1
            # on two clones of the published corpus: the current one examines
            # the one recorded run and exits 0, a checkout 5 commits behind
            # reports it absent and lands here. Both readings are named, so
            # the operator picks one instead of running the advised command
            # over whichever tree they had.
            if split["absent_total"]:
                fetch = (f" FIRST CHECK THE CHECKOUT: {split['absent_total']} "
                         f"of these left because their run tree is not under "
                         f"{corpus} at all, and a clone that is simply behind "
                         f"the published corpus is indistinguishable here from "
                         f"one the runs were removed from. Fetch/checkout the "
                         f"corpus and re-run before recording anything — a "
                         f"--write-baseline over a stale tree records what that "
                         f"tree carries, and seals it.")
            else:
                fetch = ""
            print(f"[FAIL] the recorded baseline claims {base} unacknowledged "
                  f"step-internal FAIL(s) and the sweep measures {now}: "
                  f"{head}. A register that keeps a settled entry is "
                  f"permission for the number to grow back to it unnoticed. "
                  f"Re-record it with --write-baseline, which carries any "
                  f"withdrawal into `withdrawn_unexamined` so the drop is not "
                  f"later read as work somebody did; the ratchet may only "
                  f"shrink, and it must.{fetch}")
            return 1
        print(f"[PASS] no NEW unacknowledged step-internal FAIL ({now} recorded)")
        return 0

    if args.project_dir is None:
        ap.error("give a project_dir or --corpus")
        return 2
    proj = (_ACTIVE_PROJECT_ROOT if _ACTIVE_PROJECT_ROOT is not None
            else Path(args.project_dir).resolve())
    if _ACTIVE_INPUT_PLAN is None and not proj.is_dir():
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
        reports_present = (_ACTIVE_REPORTS_PRESENT
                           if _ACTIVE_INPUT_PLAN is not None else
                           (proj / "reports").is_dir())
        why = ("no reports/ tree (pre-output project)"
               if not reports_present
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
