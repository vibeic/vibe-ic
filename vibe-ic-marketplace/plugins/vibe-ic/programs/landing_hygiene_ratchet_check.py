#!/usr/bin/env python3
"""landing_hygiene_ratchet_check.py — the LANDING refuses a hygiene finding
that this landing INTRODUCES, even under a label that is already red.

THIS GATE BLOCKS (rc=1), AND REFUSES RATHER THAN GUESSES (rc=2).

THE DEFECT (vibe-ic#2176), MEASURED ON MAIN
===========================================
`tools/gatekeeper-land.sh --cheap-only` prints

    --- full tier SKIPPED (--cheap-only) — no stamp will be written ---

at line 807 and exits at line 808 — BEFORE `--- full tier ---` at line 811 and
therefore before `run_capture "full:repo-hygiene"` at line 2004, which is the
only thing in this repository that runs `tools/ci/repo_hygiene_gates.sh`.  The
direct-push landing path uses `--cheap-only`.  So the 154-gate hygiene tier,
the ONLY instrument that measures the hygiene gates, never runs at landing.

The consequence, measured over `origin/main` on 2026-09-07 across 140 landings
(v1.17.99 -> v1.19.38): of the seven hygiene gates red on main, SIX were made
red that same day by this repository's own landings.  `shipped-path
portability` — BLOCKING since 2026-07-20 — went

    577fb50d3^  0 non-portable paths
    577fb50d3   4     (#2158)
    dbba4729c   9     (#2165)

green -> red across a landing, then worse across a second, and the landing gate
said `LAND GATE OK` both times.  This lane re-measured the endpoint on 8HD-8 in
its own clone of `a1f3685837ca`: 9 findings in 5860 files.  Nothing is wrong
with the gate; the process that was supposed to run it did not.

WHY THIS IS A DELTA AND NOT THE GATE ITSELF
===========================================
The obvious repair — run `shipped_path_portability_check.py` as a cheap landing
gate — refuses EVERY landing, because main already carries 9 findings.  A bar
that is red every day is the bar people learn to bypass, which is how this
repository got `--no-verify` on the evening of 2026-08-29.

The rule that is both true and enforceable is the one the TEST tier has had
since vibe-ic#1019 and `hygiene_finding_delta.py` was written to give the
hygiene tier: main is red, so a landing is refused when its finding set is NOT
a SUBSET of the base's.  What must be empty is the DIFFERENCE, never the count.

This program is that rule at the granularity of ONE GATE, computed from two
arms of the same instrument, cheaply enough to run on the landing path.  It
does not replace the hygiene tier and it does not make the tier cheaper: the
tier still runs every one of its gates, unchanged, wherever it runs today.

WHY A COUNT APPEARS HERE AND WHY IT IS NOT A COUNT RATCHET
==========================================================
Identity is `(path, rule)` — deliberately NOT `(path, line, rule)`.  A line
number is not a property of the finding; inserting an unrelated import above an
offender moves every line below it, and a line-keyed identity would present the
whole tail of a file as introduced by a landing that touched none of it.

But `(path, rule)` alone is too coarse for the very landing this gate exists
for: `dbba4729c` added `legacy_external_reference_debt.py:52` and `:54` to a
file that ALREADY held `:14`, so all three collapse to one key and the landing
would read as introducing nothing.  So the per-key OCCURRENCE COUNT is compared
too, and a key whose count GREW is an introduction.

That is not the count ratchet this repository forbids.  A count ratchet pins a
whole-population number, so REMOVING an offender elsewhere pays for ADDING one
here and tightening a rule is punished.  This compares per-key counts in ONE
direction only: growth blocks, shrinkage is free, and a key that disappears is
never mentioned.  There is no total, so there is nothing to trade against.

BOTH ARMS ARE THE SAME POPULATION, BY CONSTRUCTION
==================================================
Both arms are materialised with `git archive <rev> | tar -x`, so both are the
tracked tree at their own revision and neither can see a worktree leftover.
This matters concretely: `shipped_path_portability_check.py` enumerates
git-tracked files when it is pointed at a git checkout and falls back to a
filesystem walk when it is not.  Measured on this lane's clone, the two modes
report the SAME population and the SAME findings over the same commit —
`9 non-portable path(s) in 5860 file(s) scanned (git-tracked)` and
`... (filesystem-walk)` — but relying on that coincidence would leave the two
arms asking subtly different questions.  Archiving both makes them one question.

THE INSTRUMENT IS THE CANDIDATE'S; THE SUBJECT IS EACH ARM'S OWN
================================================================
The checker program is taken from `--plugin-root` (the candidate) for BOTH
arms.  Taking each arm's own copy of the checker would mean a landing that
TIGHTENS a rule reports every pre-existing offender the tightened rule now sees
as introduced, and would be refused for improving the gate.  Only the subject
tree varies between arms; the question does not.

EVERY REFUSAL BLOCKS
====================
If either arm cannot be run, or its output cannot be parsed into the shape this
program declares, the verdict is rc=2 REFUSED and the landing stops.  "Could
not measure it" is never reported as "measured it and it was clean" — a landing
gate that cannot measure must never report that it measured.

WHAT THIS REGISTRY DOES NOT ASK, IT NOW SAYS (vibe-ic#2224)
===========================================================
The rule above governs the gates this registry DECLARES.  It said nothing at
all about the gates it does not, and the landing printed one unqualified line —
`PASS  this landing introduces no hygiene finding` — over a hand-listed subset.
MEASURED on `9c653d47f1`: `tools/ci/repo_hygiene_gates.sh` declares **124**
BLOCKING gates (`run`, i.e. `_dispatch 0 0`, whose non-zero rc fails the tier)
plus 30 `run_tolerating_uncheckable`; **2** of the 124 were ratcheted.  So 122
BLOCKING questions were not asked at any direct-push landing and nothing said
so.  `program_path_load_check` (#2104) was one of them, which is #2224: the
gate has exactly one caller, `repo_hygiene_gates.sh:1128`, whose only caller is
`run_capture "full:repo-hygiene"` in `tools/gatekeeper-land.sh` — after the
`--cheap-only` exit the direct-push path takes.

Two things follow, and they are one cause: the gate is added to the registry
BELOW, and the complement is disclosed on every run.

BLOCKING vs ADVISORY, DECLARED RATHER THAN INFERRED
===================================================
* The per-gate ratchet is **BLOCKING** (rc 1) and every unanswerable question
  is **BLOCKING** (rc 2).  Unchanged.
* The coverage disclosure is **ADVISORY**: it prints, it is recorded in
  `--json`, and it never changes the return code.  It is not blocking because
  the only way to satisfy a blocking version today is to ratchet 121 more
  gates in one landing; a bar that refuses every landing is the bar people
  learn to bypass, which this program's own history is about.  What it buys is
  that the PASS line can no longer be read as a statement about the tier.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# vibe-ic#2104 — the two imports below are BARE SIBLINGS. This program is loaded
# by path (`spec_from_file_location`) by the landing and by
# `program_path_load_check`, and under that loader the program's own directory
# is NOT on `sys.path`, so both raised ModuleNotFoundError. The gate's own
# remedy, verbatim: put the program's directory on `sys.path` before the bare
# import; do not silence the import.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_text  # noqa: E402
import atomic_artifact_write_check as _atomic_census  # noqa: E402

GATE = "landing_hygiene_ratchet_check"

# ── THE REGISTRY ──────────────────────────────────────────────────────────
#
# `label`   the gate's label EXACTLY as `tools/ci/repo_hygiene_gates.sh` runs
#           it.  `programs/tests/test_issue2176_landing_hygiene_ratchet.py`
#           asserts every label here is still wired there, so a rename in the
#           hygiene tier makes this registry fail loudly instead of silently
#           ratcheting a gate that no longer exists.
# `argv`    the checker, formatted with {plugin} and {root} of the arm.
# `finding` a regex over stdout+stderr whose named groups `path` and `rule`
#           are the finding's identity.  A gate whose output does not match it
#           at all, while the checker reported a failure, is a REFUSAL.
_RATCHETED_GATES: Tuple[Dict[str, object], ...] = (
    {
        "label": "shipped-path portability",
        "argv": ("python3", "{plugin}/programs/shipped_path_portability_check.py", "{plugin}"),
        "finding": re.compile(
            r"^\s+(?P<path>\S+?):\d+\s+\[(?P<rule>[A-Za-z0-9_]+)\]", re.M),
    },
    # vibe-ic#2224 — BLOCKING since #2104, wired into the hygiene tier by
    # #2175, and until this entry it was asked on NO landing: the tier is
    # reached only after the `--cheap-only` exit that the direct-push path
    # takes. MEASURED on 9c653d47f1 before adding it: `1407 program(s) loaded
    # by path, 0 offenders` rc 0 — green, which is the condition this registry
    # requires of a new entry, so it adds an asked question and not a new red.
    #
    # COST, MEASURED RATHER THAN FEARED — and it is NOT the ~23 s/gate the
    # section above records for the first two. This sweep spawns ONE CHILD PER
    # PROGRAM (1407 of them) per arm. MEASURED on 8HD-4, in the pinned image,
    # over `HEAD~1..HEAD`, on a host at load ~175-180 (73 containers, another
    # lane's fleet run):
    #
    #   this entry alone, both arms   real 4m13.9s   (user 8m40.0s)
    #   the whole 3-gate registry     real 5m50.2s   (user 10m20.9s)
    #
    # so ~2m07 per arm against the 900 s `_findings` timeout — roughly 7x
    # headroom at a load this repository's own fleet actually produces. That
    # timeout is a REFUSAL (rc 2), not a pass, so exhausting it stops the
    # landing rather than waving it through; the headroom is what says it will
    # not. On an idle 32-core host the same sweep is 12.5 s (the program's own
    # docstring), so the figures above are an upper bound, not a typical cost.
    #
    # IDENTITY. `(path, rule)` = (the program's BARE FILENAME, the sibling it
    # cannot resolve). The checker reports `p.name`, never a path under the
    # arm's temporary root, so the two arms' keys are comparable; a key built
    # from the printed header — which does carry the arm's root — would differ
    # on every run and report the whole population as introduced.
    {
        "label": "programs load when loaded by path",
        "argv": ("python3", "{plugin}/programs/program_path_load_check.py",
                 "--programs", "{plugin}/programs", "--jobs", "8"),
        "finding": re.compile(
            r"^\s+\[FAIL\]\s+(?P<path>\S+?)\s+cannot resolve sibling\s+"
            r"`(?P<rule>[^`]+)`", re.M),
    },
)


#: vibe-ic#2224 — the hygiene tier's own declaration syntax. `run` is the
#: BLOCKING wrapper (`tools/ci/_gate_dispatch.sh:1437` -> `_dispatch 0 0`); a
#: non-zero rc from it fails the tier. `run_tolerating_uncheckable` is the
#: non-blocking one and is deliberately NOT counted here: this disclosure is
#: about questions that BLOCK when they are asked and are not asked at all.
_HYGIENE_TIER_REL = "tools/ci/repo_hygiene_gates.sh"
_BLOCKING_DECLARATION = re.compile(r'^run\s+"([^"]+)"', re.M)


def unratcheted_blocking_labels(
        subject_root: Path,
        ratcheted: Sequence[str]) -> Tuple[List[str], int, Optional[str]]:
    """`(labels, declared_total, not_measured)` — what this path never asks.

    THE SUBJECT IS THE CANDIDATE'S TREE, not the runtime's, so a landing that
    ADDS a blocking hygiene gate discloses it as unratcheted in the same run
    that adds it.

    AN UNREADABLE TIER IS `NOT_MEASURED`, NEVER AN EMPTY GAP. If the script is
    absent, or its declaration syntax changed so that nothing parses, this
    returns a reason and an empty list — and the caller prints the reason. A
    coverage figure this program could not compute must never reach a reader as
    "nothing is missing"; that is the exact shape of the defect #2224 is about.
    """
    script = subject_root / _HYGIENE_TIER_REL
    try:
        text = script.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], 0, f"cannot read {_HYGIENE_TIER_REL}: {exc}"
    declared = set(_BLOCKING_DECLARATION.findall(text))
    if not declared:
        return [], 0, (
            f"{_HYGIENE_TIER_REL} parsed to zero `run` declarations — the "
            f"tier's declaration syntax changed and this coverage cannot be "
            f"computed from it")
    return sorted(declared - set(ratcheted)), len(declared), None


def summarize_coverage(gaps: List[str], declared_total: int,
                       not_measured: Optional[str], asked: int) -> str:
    """ONE line, and it is ADVISORY — see this module's docstring.

    NAMED, NOT JUST COUNTED, and printed BEFORE the per-gate verdicts.
    `tools/gatekeeper-land.sh:run_emit` renders a FAILING gate as its FAIL
    lines plus `tail -5`, so a block of names printed after the verdicts would
    displace the verdict out of that tail. Printed before them it cannot, and
    a passing landing pays nothing for it either: `run_emit` prints no stdout
    at all on PASS, and the whole capture still reaches `landing_record`, which
    is where a reader who wants the names goes. `--json .coverage` carries the
    same list in machine form.
    """
    if not_measured:
        return (f"{GATE}: NOT_MEASURED — coverage of the hygiene tier is "
                f"unknown: {not_measured}")
    if not gaps:
        return (f"{GATE}: COVERAGE — all {declared_total} BLOCKING hygiene "
                f"gate(s) are ratcheted on this path.")
    return "\n".join(
        [f"{GATE}: NOT_MEASURED — {len(gaps)} of {declared_total} BLOCKING "
         f"hygiene gate(s) are not ratcheted on this path, so this landing "
         f"was NOT asked about them; the {asked} ratcheted gate(s) below are "
         f"the whole of what it WAS asked."]
        + [f"  [NOT_MEASURED] {label}" for label in gaps])


class Refusal(Exception):
    """Raised for anything this program cannot answer.  Always rc=2."""


PROGRAMS_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs"
_FLOW_REL = str(Path(PROGRAMS_REL).parent / _atomic_census.FLOW_REL)


def _git_subject(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    if proc.returncode:
        raise Refusal(f"git {args[0]} rc={proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout


def _subject_blob(repo: Path, rev: str, path: str) -> Optional[str]:
    entry = _git_subject(repo, "ls-tree", "-z", rev, "--", path)
    if not entry:
        return None
    mode, kind, _oid = entry.split("\t", 1)[0].split()
    if kind != "blob" or mode not in ("100644", "100755"):
        raise Refusal(f"{rev}:{path} is not a regular tracked source file")
    return _git_subject(repo, "show", f"{rev}:{path}")


def _subject_declarations(text: Optional[str], scratch: Path) -> Dict[str, set]:
    if text is None:
        return {}  # A subject without a flow still has its CLI destinations.
    import yaml
    # The census's historical CLI fallback is not evidence that a malformed
    # flow has no changed declarations. Keep that uncertainty a refusal here.
    try:
        yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise Refusal(f"cannot read subject flow declarations: {exc}") from exc
    flow = scratch / _atomic_census.FLOW_REL
    flow.parent.mkdir(parents=True, exist_ok=True)
    flow.write_text(text)
    return _atomic_census.declared_outputs_by_program(scratch)


def _atomic_sites(text: str, path: Path, declared: set) -> Dict[Tuple[str, str], List[int]]:
    """Use #1082 itself; source/form identity survives harmless line movement.

    Occurrences are retained, so duplicating an existing write cannot cancel
    against the old copy merely because its source text is identical.
    """
    path.write_text(text)
    lines = text.splitlines()
    sites: Dict[Tuple[str, str], List[int]] = {}
    for hit in _atomic_census.scan_program(path, declared):
        line = int(hit["line"])
        key = (lines[line - 1].strip(), str(hit["form"]))
        sites.setdefault(key, []).append(line)
    return sites


def atomic_added_offenders(repo: Path, base: str, head: str = "HEAD") -> dict:
    """The existing cheap unit's affected #1082 delta, not a full-tree gate.

    Adapted from the unshipped issue2154 delta (6494f3f6). Unlike that version,
    the subject is each COMMIT's bytes and declaration-only changes select the
    affected programs too. The candidate census instrument stays the same.
    """
    record = {"base": base, "head": head, "programs_examined": 0,
              "affected_programs": [], "added": [], "not_measured": {}}
    try:
        base = _git_subject(repo, "rev-parse", "--verify", f"{base}^{{commit}}").strip()
        head = _git_subject(repo, "rev-parse", "--verify", f"{head}^{{commit}}").strip()
        record.update(base=base, head=head)
        changed = _git_subject(repo, "diff", "--name-only", "-z", base, head,
                               "--", PROGRAMS_REL, _FLOW_REL).split("\0")
        names = {p for p in changed if p.endswith(".py")
                 and Path(p).parent.as_posix() == PROGRAMS_REL}
        # No Python/flow change means no atomic population needs measuring.
        if not names and _FLOW_REL not in changed:
            return record
        with tempfile.TemporaryDirectory(prefix="atomic-delta.") as td:
            scratch = Path(td)
            before_decl = _subject_declarations(
                _subject_blob(repo, base, _FLOW_REL), scratch / "base")
            after_decl = _subject_declarations(
                _subject_blob(repo, head, _FLOW_REL), scratch / "candidate")
            for stem in before_decl.keys() | after_decl.keys():
                if before_decl.get(stem, set()) != after_decl.get(stem, set()):
                    # Match the census's top-level programs/*.py population.
                    if Path(stem).name == stem:
                        names.add(f"{PROGRAMS_REL}/{stem}.py")
            record["affected_programs"] = sorted(names)
            for name in sorted(names):
                after_text = _subject_blob(repo, head, name)
                if after_text is None:
                    continue  # Deleted/absent in candidate: no introduced write.
                before_text = _subject_blob(repo, base, name)
                stem = Path(name).stem
                before = _atomic_sites(before_text or "", scratch / "before.py",
                                       before_decl.get(stem, set()))
                after = _atomic_sites(after_text, scratch / "after.py",
                                      after_decl.get(stem, set()))
                record["programs_examined"] += 1
                for key, lines in sorted(after.items()):
                    for line in lines[len(before.get(key, [])):]:
                        record["added"].append({"file": name, "line": line,
                                                "source": key[0], "form": key[1]})
    except (OSError, Refusal) as exc:
        record["not_measured"]["range"] = str(exc)
    return record


def summarize_atomic(record: dict) -> str:
    if record["not_measured"]:
        return f"{GATE}: REFUSED — atomic writes: {record['not_measured']}; NOTHING WAS MEASURED"
    if record["added"]:
        return (f"{GATE}: FAIL — this landing INTRODUCES non-atomic report writes:\n"
                + "\n".join(f"  {r['file']}:{r['line']}  {r['form']}"
                            for r in record["added"]))
    if not record["programs_examined"]:
        return f"{GATE}: NOT_APPLICABLE — no affected atomic-write population"
    return (f"{GATE}: PASS — atomic writes introduce nothing "
            f"({record['programs_examined']} affected programs examined)")


def _archive(repo: Path, rev: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    try:
        tar = subprocess.run(["git", "-C", str(repo), "archive", rev],
                             capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refusal(f"could not archive {rev}: {exc}") from exc
    if tar.returncode != 0:
        raise Refusal(
            f"could not archive {rev} (git archive rc={tar.returncode}): "
            f"{tar.stderr.decode('utf-8', 'replace').strip()[:400]}")
    try:
        untar = subprocess.run(["tar", "-x", "-C", str(dest)], input=tar.stdout,
                               capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refusal(f"could not extract {rev}: {exc}") from exc
    if untar.returncode != 0:
        raise Refusal(
            f"could not extract {rev} (tar rc={untar.returncode}): "
            f"{untar.stderr.decode('utf-8', 'replace').strip()[:400]}")


def _findings(entry: Dict[str, object], instrument_plugin: Path,
              arm_root: Path, arm_name: str) -> Counter:
    """Run one checker over one arm and return Counter[(path, rule)]."""
    label = str(entry["label"])
    # The INSTRUMENT is the candidate's; only {root}/{plugin} of the SUBJECT
    # move between arms.  `{plugin}` in an argv slot that names the checker
    # itself is resolved against the instrument, never against the arm.
    argv: List[str] = []
    for i, tok in enumerate(entry["argv"]):  # type: ignore[union-attr]
        if i == 1:
            argv.append(tok.format(plugin=instrument_plugin, root=arm_root))
        else:
            argv.append(tok.format(
                plugin=arm_root / "vibe-ic-marketplace/plugins/vibe-ic",
                root=arm_root))
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              cwd=str(arm_root), timeout=900)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refusal(f"[{label}] {arm_name} arm could not be run: {exc}") from exc
    out = (proc.stdout or "") + (proc.returncode and (proc.stderr or "") or "")
    if proc.returncode not in (0, 1):
        raise Refusal(
            f"[{label}] {arm_name} arm exited {proc.returncode}, which is "
            f"neither clean (0) nor a finding report (1): "
            f"{(proc.stderr or proc.stdout or '').strip()[:400]}")
    pat = entry["finding"]
    found = Counter()
    for m in pat.finditer(out):  # type: ignore[union-attr]
        found[(m.group("path"), m.group("rule"))] += 1
    if proc.returncode == 1 and not found:
        raise Refusal(
            f"[{label}] {arm_name} arm reported a failure (rc=1) but not one "
            f"line matched the declared finding shape — this program cannot "
            f"say what it found, so it does not say it found nothing. "
            f"First 400 chars: {out.strip()[:400]}")
    return found


def compare(base: Counter, cand: Counter) -> List[Tuple[Tuple[str, str], int, int]]:
    """Keys the candidate INTRODUCES: new keys, and keys whose count grew.

    One direction only.  A key that shrank or vanished is not reported, so
    removing an offender can never pay for adding one.
    """
    introduced = []
    for key, n in sorted(cand.items()):
        was = base.get(key, 0)
        if n > was:
            introduced.append((key, was, n))
    return introduced


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="refuse a landing that introduces a hygiene finding, "
                    "even under an already-red label")
    ap.add_argument("--repo", required=True, type=Path,
                    help="the repository being landed from")
    ap.add_argument("--plugin-root", required=True, type=Path,
                    help="the CANDIDATE plugin root — supplies the instrument "
                         "for both arms")
    ap.add_argument("--base", required=True,
                    help="the revision this landing is measured against")
    ap.add_argument("--head", default="HEAD",
                    help="the revision being landed (default HEAD)")
    ap.add_argument("--only", action="append", default=None,
                    help="restrict to these labels (repeatable); "
                         "for tests and for triage, never for a landing")
    ap.add_argument("--json", type=Path, help="write the comparison as JSON")
    args = ap.parse_args(argv)

    entries = list(_RATCHETED_GATES)
    if args.only:
        entries = [e for e in entries if str(e["label"]) in set(args.only)]
        missing = set(args.only) - {str(e["label"]) for e in _RATCHETED_GATES}
        if missing:
            print(f"{GATE}: REFUSED — --only names no declared gate: "
                  f"{sorted(missing)}", file=sys.stderr)
            return 2
    if not entries:
        print(f"{GATE}: REFUSED — nothing declared to ratchet. An empty "
              f"registry is a wiring error, not a clean tree.", file=sys.stderr)
        return 2

    atomic = atomic_added_offenders(args.repo, args.base, args.head)
    print(summarize_atomic(atomic))
    if atomic["not_measured"]:
        if args.json:
            write_text(args.json, json.dumps({"atomic_writes": atomic}, indent=2))
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="hygratchet."))
    record: Dict[str, object] = {"base": args.base, "head": args.head,
                                 "gates": {}, "atomic_writes": atomic}
    try:
        try:
            base_root = tmp / "base"
            cand_root = tmp / "cand"
            _archive(args.repo, args.base, base_root)
            _archive(args.repo, args.head, cand_root)
        except Refusal as r:
            print(f"{GATE}: REFUSED — {r}", file=sys.stderr)
            return 2

        # vibe-ic#2224 — SAY WHAT WAS NOT ASKED, BEFORE ANSWERING WHAT WAS.
        # ADVISORY: it never touches the return code (see the docstring).
        gaps, declared_total, cov_not_measured = unratcheted_blocking_labels(
            cand_root, [str(e["label"]) for e in _RATCHETED_GATES])
        record["coverage"] = {
            "hygiene_tier": _HYGIENE_TIER_REL,
            "blocking_gates_declared": declared_total,
            "ratcheted": sorted(str(e["label"]) for e in _RATCHETED_GATES),
            "not_ratcheted": gaps,
            "not_measured": cov_not_measured,
            "advisory": True,
        }
        print(summarize_coverage(gaps, declared_total, cov_not_measured,
                                 len(_RATCHETED_GATES)))

        introduced_any = bool(atomic["added"])
        for entry in entries:
            label = str(entry["label"])
            try:
                b = _findings(entry, args.plugin_root, base_root, "base")
                c = _findings(entry, args.plugin_root, cand_root, "candidate")
            except Refusal as r:
                print(f"{GATE}: REFUSED — {r}", file=sys.stderr)
                return 2
            new = compare(b, c)
            record["gates"][label] = {
                "base_findings": sum(b.values()),
                "candidate_findings": sum(c.values()),
                "introduced": [{"path": k[0], "rule": k[1],
                                "base_count": was, "candidate_count": now}
                               for k, was, now in new],
            }
            if new:
                introduced_any = True
                print(f"{GATE}: FAIL — [{label}] this landing INTRODUCES "
                      f"{len(new)} finding key(s) "
                      f"(base {sum(b.values())} -> candidate {sum(c.values())}):")
                for (path, rule), was, now in new:
                    print(f"  {path}  [{rule}]  {was} -> {now}")
                print(f"  The label is already red, which excuses what was "
                      f"ALREADY there and excuses nothing added here. Remove "
                      f"the new occurrence(s); never write a baseline, widen "
                      f"the gate, or acknowledge the row.")
            else:
                print(f"{GATE}: PASS — [{label}] introduces nothing "
                      f"(base {sum(b.values())} -> candidate {sum(c.values())})")

        if args.json:
            write_text(args.json, json.dumps(record, indent=2, sort_keys=True))
        return 1 if introduced_any else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
