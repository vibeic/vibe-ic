#!/usr/bin/env python3
"""d9_content_census.py — for each of the 63 steps, does the gate READ THE BYTES?

THE GAP THIS FILLS, IN ONE SENTENCE
===================================
``d9_flow_gate_reality`` decides MOVES/DARK with a two-arm mutation whose arm B
DELETES the step's declared outputs. That is a strong test and it is the wrong
question for D9, because **an existence check also changes its mind when the
file is gone**. A gate that never read a byte and only asserted the artefact was
there scores MOVES TODAY under a deletion arm, and D9 exists precisely to catch
that gate.

So this instrument adds the arm the sibling does not have:

    ARM A   the published run, untouched
    ARM C   the SAME paths, still present, still the same file type, with their
            BYTES corrupted                                   <- the D9 question
    ARM B   the paths deleted                     (the sibling's existence arm)

and reads the three together:

    CONTENT-SENSITIVE   A != C            the gate read the bytes
    EXISTENCE-ONLY      A == C and A != B the gate confirmed a file exists and
                                          never looked inside it   <- the target
    DARK                A == C == B       the gate is not measuring this step
    NO-DENOMINATOR      no published run carries the step's declared outputs
    NO-BLOCKING-RULER   the step declares no blocking gate program at all

NO ORACLE. THIS IS NOT NEGOTIABLE
=================================
D9 was first designed against known-correct answers and sent straight back:
「當然我們自己在訓練、收斂的時候可以用 oracle。可是真的在跑的時候，oracle 哪裡來？」
A real project ships no answer key, so a criterion that needs one is the wrong
criterion. Nothing here knows what any artefact SHOULD contain. The corruption
is generated FROM the artefact's own bytes, and the question asked is only
"did the verdict follow the bytes" — which is answerable on a project whose
correct output nobody knows, including a project being run for the first time.

WHAT A CORRUPTION MAY AND MAY NOT DO
====================================
It must change MEANING while preserving SHAPE, or the arms differ for the wrong
reason and an existence check is scored as a content check:

  * the path still exists, with the same name and the same extension;
  * JSON stays parseable JSON with the same keys and the same value TYPES —
    only leaf VALUES move (numbers scaled and sign-flipped, booleans inverted,
    strings replaced by a marker of equal-ish length);
  * text stays text of similar length, with its numeric literals moved;
  * bytes stay bytes of exactly the same length, with an interior run flipped.

A corruption that makes a file unparseable would be caught by any gate that
merely calls ``json.load`` in a ``try``, which is the existence check wearing a
content check's clothes. Structure-preserving corruption is what separates them.

THE ANSWER IS A LOWER BOUND, and it is stated as one. A gate scored
EXISTENCE-ONLY here read no byte THAT MATTERED to the mutation applied; a
cleverer corruption might move it. A gate scored CONTENT-SENSITIVE genuinely
read bytes — that direction is sound, because a verdict cannot follow bytes it
never read.

EXIT CODES
    0  ran, report written
    2  refused — the corpus or the flow could not be established (never a pass)
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
                      / "programs" / "tests"))

import d9_flow_gate_reality as R          # noqa: E402  the sibling instrument
from matrix_63x8 import flowref as F      # noqa: E402

CONTENT_SENSITIVE = "CONTENT-SENSITIVE"
EXISTENCE_ONLY = "EXISTENCE-ONLY"
DARK = "DARK"
NO_DENOMINATOR = "NO-DENOMINATOR"
#: Kept SEPARATE from NO-DENOMINATOR on purpose. "no published run carries the
#: outputs" and "the step declares no blocking gate program at all" are two
#: different absences, and folding them into one bucket hides which half is
#: missing — the ruler or the thing to measure.
NO_RULER = "NO-BLOCKING-RULER"
#: The run could not DECIDE. Kept apart from DARK, which is a finding about the
#: gate; this is a finding about the SAMPLE. A run whose arm A is not CLEAN
#: cannot serve as the baseline for "the verdict did not change", so scoring it
#: EXISTENCE-ONLY reports the sample's limit as the gate's defect.
INCONCLUSIVE = "INCONCLUSIVE"

#: A deterministic seed. The corruption must be REPRODUCIBLE — a finding whose
#: repro line does not reproduce is a rumour.
_SEED = 20260812

#: Strings are replaced by this rather than by noise, so a human reading a
#: corrupted tree can see instantly that it is a probe artefact and not data.
_STR_MARK = "__D9_CORRUPTED__"


# ─────────────────────────────────────────────────────────── the corruption
def _corrupt_json_value(node: Any, rng: random.Random) -> Any:
    """Move every leaf VALUE, keep every key and every TYPE."""
    if isinstance(node, dict):
        return {k: _corrupt_json_value(v, rng) for k, v in node.items()}
    if isinstance(node, list):
        return [_corrupt_json_value(v, rng) for v in node]
    if isinstance(node, bool):
        return not node
    if isinstance(node, int):
        # a different number, still an int, still plausible in magnitude
        return -(node * 3 + 7)
    if isinstance(node, float):
        return -(node * 3.0 + 7.0)
    if isinstance(node, str):
        if not node:
            return node
        flipped = _flip_polarity(node)
        # a verdict string must INVERT, not vanish: blanking it is a parse-level
        # change any `if not value` would catch without reading the meaning
        return flipped if flipped.lower() != node.lower() else _STR_MARK
    return node


#: Polarity pairs, flipped in BOTH directions. This is not an oracle and the
#: distinction is the whole point: it does not know which pole is CORRECT for
#: any file, it only inverts whichever pole the file already states. A report
#: that said "match" says "mismatch"; one that said "mismatch" says "match".
#: Chip-AGNOSTIC — no vendor, tool, PDK or design name appears here.
#:
#: WHY THIS EXISTS: the first version of this census moved only NUMBERS, and
#: scored `lvs_report_check` EXISTENCE-ONLY. Driven by hand on the same
#: published run, that gate goes rc 0 -> rc 1 the moment its report says
#: "Netlists do NOT match" — it reads content, and the census said it did not.
#: A verdict-bearing report keeps its meaning in WORDS at least as much as in
#: numbers, so a corruption that leaves every word standing is not adversarial
#: to the criterion being measured, and its EXISTENCE-ONLY verdicts are the
#: instrument's own failure reported as the gate's.
_POLARITY = [
    ("mismatch", "match"), ("mismatches", "matches"),
    ("not match", "does match"),
    ("equivalent", "inequivalent"),
    ("clean", "violating"),
    ("passed", "failed"), ("pass", "fail"),
    ("no violation", "one violation"), ("violation-free", "violation-bearing"),
    ("ok", "bad"), ("success", "failure"), ("succeeded", "failed"),
    ("congruent", "incongruent"), ("identical", "differing"),
    ("within", "outside"), ("met", "violated"),
]


def _flip_polarity(text: str) -> str:
    """Invert every polarity word, case-insensitively, longest pair first.

    Both directions, so the corruption is a genuine INVERSION rather than a
    push toward "bad" — a gate that only ever fires on the word "fail" would
    otherwise be scored content-sensitive by a corruption that always inserts
    it, which is a different and much weaker claim.
    """
    import re  # noqa: PLC0415
    pairs = sorted(_POLARITY, key=lambda ab: -len(ab[0]))
    # The placeholder must contain NO polarity word of its own. Spelling it
    # "\x00<word>\x00" looked obvious and was wrong: flipping ("mismatch",
    # "match") then rewrote the `match` INSIDE the placeholder protecting
    # `mismatch`, and the pair silently stopped inverting in one direction.
    # An index carries no vocabulary, so nothing can match inside it.
    for i, (a, b) in enumerate(pairs):
        mark = f"\x00{i}\x00"
        text = re.sub(re.escape(a), mark, text, flags=re.I)
        text = re.sub(re.escape(b), a, text, flags=re.I)
        text = text.replace(mark, b)
    return text


def _corrupt_text(text: str, rng: random.Random) -> str:
    """Move the numbers AND invert the polarity words; keep the layout.

    A report's meaning lives in its numbers and in its verdict words; its shape
    lives in its lines, and the shape must survive so the arms differ for a
    content reason and not a parse reason.
    """
    import re  # noqa: PLC0415
    def bump(m: "re.Match") -> str:
        raw = m.group(0)
        try:
            if "." in raw:
                return f"{-(float(raw) * 3.0 + 7.0):.6g}"
            return str(-(int(raw) * 3 + 7))
        except ValueError:
            return raw
    return _flip_polarity(re.sub(r"-?\d+\.?\d*", bump, text))


def corrupt_declared_outputs(root: Path, step_id: str,
                             rng: random.Random) -> List[str]:
    """ARM C: rewrite the step's OWN declared outputs IN PLACE.

    Same paths, same names, same types — only the bytes move. Returns what was
    actually corrupted, so an arm that corrupted NOTHING is visible as such
    rather than masquerading as a clean control (the sibling's rule for arm B,
    and the reason its `removed` count is in its report).
    """
    touched: List[str] = []
    for entry in F.required_outputs(step_id):
        for alt in F.split_any_of(entry):
            alt = alt.strip()
            if not alt:
                continue
            targets = sorted(root.glob(alt)) if F.is_glob(alt) else [root / alt]
            for t in targets:
                if t.is_dir():
                    targets.extend(sorted(p for p in t.rglob("*") if p.is_file()))
                    continue
                if not t.is_file():
                    continue
                try:
                    rel = str(t.relative_to(root))
                except ValueError:
                    continue
                try:
                    if t.suffix == ".json":
                        doc = json.loads(t.read_text(errors="replace"))
                        t.write_text(json.dumps(_corrupt_json_value(doc, rng),
                                                indent=1), encoding="utf-8")
                    else:
                        raw = t.read_bytes()
                        try:
                            text = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            # binary: same LENGTH, interior run flipped
                            if len(raw) < 8:
                                continue
                            lo = len(raw) // 3
                            hi = min(lo + 256, len(raw) - 1)
                            t.write_bytes(raw[:lo]
                                          + bytes(b ^ 0xFF for b in raw[lo:hi])
                                          + raw[hi:])
                        else:
                            t.write_text(_corrupt_text(text, rng), encoding="utf-8")
                    touched.append(rel)
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
    return touched


# ───────────────────────────────────────────────────────────── the three arms
def followed_the_bytes(arm_a: Dict[str, Any], arm_c: Dict[str, Any]) -> bool:
    """Did the verdict move when ONLY the bytes moved?

    Deliberately NOT `d9_flow_gate_reality.verdict_moved`, and the difference is
    the point. That function requires arm A to be content-derived (CLEAN or
    FINDING) before it will believe a move, which is right for ITS question —
    it compares against a DELETION, and a gate that reported NO-INPUT before the
    delete tells you nothing about the delete.

    Here the mutation leaves the file in place, so a gate that said NO-INPUT and
    then reported a FINDING once the bytes were corrupted has DEMONSTRABLY read
    those bytes. Measured on `spm/v1.10.18_sky130A`: `dft_signoff_check` goes
    `NO-INPUT/rc=0 -> FINDING/rc=1` under corruption alone, and the whitelist
    discarded that as DARK — the census reporting "not measuring this step"
    about a gate that had just proved it was.
    """
    return (arm_a.get("bucket") != arm_c.get("bucket")
            or arm_a.get("rc") != arm_c.get("rc"))


def can_baseline_a_non_move(arm_a: Dict[str, Any]) -> bool:
    """Only a CLEAN arm A can support "the verdict did not change".

    A gate that was ALREADY FINDING in arm A is failing for a reason the
    mutation did not cause; its arm C staying FINDING is not evidence that the
    bytes went unread, because the pre-existing finding masks any second one.
    Measured on `caravel_user_project/v1.9.43_sky130A`:
    `dft_atpg_coverage_check` reads `A=FINDING -> C=FINDING` and was scored
    EXISTENCE-ONLY — while on the two runs where its arm A is CLEAN the same
    gate is plainly CONTENT-SENSITIVE. The accusation was the sample's, not the
    gate's.
    """
    return arm_a.get("bucket") == R.CLEAN


def three_arm_cell(step_id: str, run_rel: str, programs: Sequence[str],
                   repo: Path, scratch: Path, timeout: int) -> Dict[str, Any]:
    """Drive every BLOCKING gate program of one step three times on one run.

    Isolation is unconditional — two of the three arms mutate the tree.
    Order matters: CORRUPT before DELETE, on the same copy, because deleting
    first would leave the corruption arm nothing to corrupt.
    """
    rng = random.Random(f"{_SEED}:{step_id}:{run_rel}")
    tmp = Path(tempfile.mkdtemp(dir=str(scratch)))
    try:
        dest = tmp / "run"
        shutil.copytree(repo / run_rel, dest, symlinks=True)
        progs = [p for p in programs if F.program_path(p)]

        arm_a = {p: R._drive(F.program_path(p), dest, timeout) for p in progs}
        corrupted = corrupt_declared_outputs(dest, step_id, rng)
        arm_c = {p: R._drive(F.program_path(p), dest, timeout) for p in progs}
        removed = R.remove_declared_outputs(dest, step_id)
        arm_b = {p: R._drive(F.program_path(p), dest, timeout) for p in progs}

        per_program = {}
        for p in progs:
            a, c, b = arm_a[p], arm_c.get(p, {}), arm_b.get(p, {})
            if followed_the_bytes(a, c):
                verdict = CONTENT_SENSITIVE
            elif not can_baseline_a_non_move(a):
                # the sample cannot decide; say so instead of accusing the gate
                verdict = INCONCLUSIVE
            elif followed_the_bytes(a, b):
                verdict = EXISTENCE_ONLY
            else:
                verdict = DARK
            per_program[p] = {
                "verdict": verdict,
                "arm_a": f'{a.get("bucket")}/rc={a.get("rc")}',
                "arm_c": f'{c.get("bucket")}/rc={c.get("rc")}',
                "arm_b": f'{b.get("bucket")}/rc={b.get("rc")}',
            }
        return {"run": run_rel, "corrupted": len(corrupted),
                "removed": len(removed), "programs": per_program}
    except OSError as exc:
        return {"run": run_rel, "error": f"isolation failed: {exc}",
                "corrupted": 0, "removed": 0, "programs": {}}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cell_verdict(runs: Sequence[Dict[str, Any]]) -> str:
    """One verdict per STEP from its per-run results.

    Best-case across runs, deliberately: the claim being made is "this gate CAN
    read the bytes", and one run proving it is enough. The pessimistic direction
    would let a run with a thin artefact set mask a gate that does read content.
    """
    order = {CONTENT_SENSITIVE: 3, EXISTENCE_ONLY: 2, DARK: 1, INCONCLUSIVE: 0}
    best, seen = None, False
    for r in runs:
        for info in r.get("programs", {}).values():
            seen = True
            v = info["verdict"]
            if v == CONTENT_SENSITIVE:
                return CONTENT_SENSITIVE
            if best is None or order.get(v, 0) > order.get(best, 0):
                best = v
    if not seen:
        return NO_DENOMINATOR
    return best


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--limit-per-step", type=int, default=1,
                    help="runs probed PER STEP. The report records how many "
                         "(step,run) pairs the cap dropped; never silent.")
    ap.add_argument("--only-step", action="append", default=[])
    args = ap.parse_args(argv)

    repo = REPO
    tracked = R.tracked_files(repo)
    runs = R.published_runs(tracked) if hasattr(R, "published_runs") else None
    if runs is None:
        runs = sorted({f.rsplit("/phase1/generated_docs/", 1)[0]
                       for f in tracked if "/phase1/generated_docs/" in f})
    if not runs:
        print("REFUSE — no published runs. A content census over nothing is not "
              "a census, and after a corpus withdrawal this is the expected "
              "state, not a clean one.")
        return 2
    by_run = R.index_runs(tracked, runs)

    step_ids = [str(s) for s in F.step_ids()]
    if args.only_step:
        step_ids = [s for s in step_ids if s in set(args.only_step)]

    rows, dropped = [], 0
    with tempfile.TemporaryDirectory() as scratch:
        for i, sid in enumerate(step_ids, 1):
            progs = R.blocking_programs(sid)
            n, candidates = R.denominator(by_run, sid)
            probe = candidates[: args.limit_per_step]
            dropped += max(0, len(candidates) - len(probe))
            per_run = [three_arm_cell(sid, r, progs, repo, Path(scratch),
                                      args.timeout) for r in probe] if progs else []
            if not progs:
                v = NO_RULER
            elif not probe:
                v = NO_DENOMINATOR
            else:
                v = cell_verdict(per_run)
            rows.append({"step": sid, "name": F.step_name(sid),
                         "blocking_programs": progs, "denominator": n,
                         "verdict": v, "runs": per_run})
            print(f"  [{i}/{len(step_ids)}] step {sid:>4} "
                  f"({len(progs)} blocking, denom {n:>3})  {v}",
                  file=sys.stderr, flush=True)

    tally: Dict[str, int] = {}
    for r in rows:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(
        {"generated_by": "tools/d9_content_census.py",
         "corpus_runs": len(runs), "steps": len(rows),
         "limit_per_step": args.limit_per_step,
         "step_run_pairs_dropped_by_cap": dropped,
         "tally": tally, "rows": rows}, indent=1), encoding="utf-8")

    print()
    print("=" * 74)
    print(f"D9 CONTENT CENSUS — {len(rows)} step(s), {len(runs)} published run(s)")
    print("=" * 74)
    for k in (CONTENT_SENSITIVE, EXISTENCE_ONLY, DARK, INCONCLUSIVE,
              NO_DENOMINATOR, NO_RULER):
        print(f"  {k:<20} {tally.get(k, 0):>4}")
    if dropped:
        print(f"  ({dropped} (step,run) pair(s) dropped by --limit-per-step "
              f"{args.limit_per_step} — a cap, disclosed, never a silent truncation)")
    print()
    for r in rows:
        if r["verdict"] == EXISTENCE_ONLY:
            print(f"[{EXISTENCE_ONLY}] step {r['step']} — {r['name'][:56]}")
            for p, info in (r["runs"][0]["programs"].items() if r["runs"] else []):
                if info["verdict"] == EXISTENCE_ONLY:
                    print(f"     {p}: A={info['arm_a']} C={info['arm_c']} "
                          f"B={info['arm_b']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
