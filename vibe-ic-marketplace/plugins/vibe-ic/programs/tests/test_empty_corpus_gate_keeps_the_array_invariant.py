"""An empty loop corpus must not KILL the sweep before it records anything.

THE DEFECT, MEASURED ON `75776dbbb`
===================================
`gate_dispatch_over` over a corpus that expands to zero items appends a
synthetic NOT_CHECKED gate (vibe-ic#1075), so that a corpus which silently
emptied leaves a verdict instead of no gate at all. That site is the ONLY gate
in the file that does not go through `_dispatch`, and `_dispatch` is where the
eight per-gate arrays are pushed in lockstep.

#1075 pushed the six arrays that existed when it was written. #584 landed
separately and made the invariant EIGHT, adding `GATE_EX_UNTIL` /
`GATE_EX_WHY`. From that point `gate_dispatch_finish` read `GATE_EX_UNTIL[$i]`
for every `i < declared` — and for the synthetic gate there was no entry::

    $ bash gates.sh --summary-json rec.json
       ^^ EMPTY CORPUS "an empty corpus": 0 item(s), so the gates it would
          have dispatched did not run. Recorded NOT_CHECKED …
    _gate_dispatch.sh: line 741: GATE_EX_UNTIL[$i]: unbound variable
    $ echo $?
    1
    summary written? NO

Under `set -u` that is fatal, and it is fatal BEFORE `_gate_dispatch_emit`
runs. So the record a consumer reads is not merely wrong about the empty
corpus — it does not exist, and `gatekeeper_review` gets nothing at all to
reason from. An empty corpus is exactly the state #1075 exists to report, and
it was the one state that destroyed the report.

WHY THIS IS A CLASS AND NOT A TYPO. The file's own header promises that "every
`run*` wrapper funnels through ONE `_dispatch`, and a third wrapper added later
cannot accidentally skip the recording". The synthetic gate is a recording site
that does not funnel through it, so it has to restate the invariant by hand,
and a hand-maintained parallel list is the drift shape #527/#530/#534/#538 each
spent a version removing. The first test below therefore pins the INVARIANT
over every gate the dispatcher can produce, not just the empty-corpus one, so
a ninth array or a second synthetic gate is covered the day it appears.
"""
from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_LIB = _REPO / "tools" / "ci" / "_gate_dispatch.sh"

#: Inner bound. The harness runs `--timeout=180 --timeout-method=thread`, and a
#: thread-based timeout cannot interrupt a subprocess wait, so a bound at or
#: above it would take the SESSION down rather than fail one test. Every
#: fixture here is `true` and a `printf`; measured well under 2s.
_BOUND_S = 60


def _run(root: Path, body: str, *args: str):
    (root / "tools" / "ci").mkdir(parents=True, exist_ok=True)
    script = root / "tools" / "ci" / "gates.sh"
    script.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT="{root}"
        . "{_LIB}"
        gate_dispatch_init "$@"
        """) + body + "\ngate_dispatch_finish\n")
    rec = root / "record.json"
    proc = subprocess.run(["bash", str(script), "--summary-json", str(rec), *args],
                          cwd=str(root), capture_output=True, text=True,
                          timeout=_BOUND_S)
    doc = json.loads(rec.read_text()) if rec.is_file() and rec.stat().st_size else None
    return proc, doc


_EMPTY_LOOP = (
    'run "a flat gate" "$ROOT" true\n'
    '_body() { run "per item ($1)" "$ROOT" true; }\n'
    'gate_dispatch_over "an empty corpus" _body printf ""\n')


def test_an_empty_corpus_does_not_kill_the_sweep(tmp_path):
    """ARM A. The measured defect: `set -u` fatal, and no record written."""
    proc, doc = _run(tmp_path, _EMPTY_LOOP)
    text = proc.stdout + proc.stderr

    assert "unbound variable" not in text, (
        f"the sweep DIED on its own array invariant over an empty corpus — "
        f"the one state the synthetic gate exists to report:\n{text}")
    assert proc.returncode == 2, (
        "the sweep must survive long enough to write its record, then refuse "
        f"the unmeasured denominator with rc 2:\n{text}")
    assert doc is not None, (
        "no summary record was written at all. A consumer cannot tell this "
        "from a run that never happened, which is strictly worse than a "
        f"record that is wrong:\n{text}")


def test_the_empty_corpus_gate_is_IN_the_record_it_did_not_destroy(tmp_path):
    """Surviving is not enough — the synthetic gate must still be recorded.

    Without this, the defect above is 'fixed' by dropping the synthetic gate,
    which is the silent PASS #1075 added it to refuse.
    """
    _, doc = _run(tmp_path, _EMPTY_LOOP)

    assert doc["declared"] == 2, doc
    assert doc["not_checked"] == 1, doc
    labels = [g["label"] for g in doc["gates"] if g["state"] == "NOT_CHECKED"]
    assert any("EMPTY" in l for l in labels), labels
    # #957's corpus row still reports the zero denominator beside it.
    assert any(c["items"] == 0 for c in doc["corpora"]), doc["corpora"]


def test_the_empty_corpus_gate_is_recorded_as_UNEXEMPTED(tmp_path):
    """It bought no tolerance, and the record must say so.

    Handing it a placeholder date would grant every future empty corpus a
    silent exemption — a tolerance nobody declared at a wiring site, which is
    precisely what #584 made impossible for every other gate.
    """
    _, doc = _run(tmp_path, _EMPTY_LOOP)

    empty = [g for g in doc["gates"] if g["state"] == "NOT_CHECKED"][0]
    assert empty["exempt_until"] is None, empty
    assert doc["not_checked_unexempted"] == [empty["label"]], doc


def test_the_rollup_does_not_claim_an_exemption_that_does_not_exist(tmp_path):
    """`(exempt until )` asserted a tolerance with a blank date.

    That sentence is the one #539 added so a reader could tell a bought
    refusal from an unbought one, so it is the last place that may imply one.
    """
    proc, _ = _run(tmp_path, _EMPTY_LOOP)
    text = proc.stdout + proc.stderr
    rollup = [ln for ln in text.splitlines()
              if ln.startswith("repo_hygiene_gates:") and "NOT a pass" in ln]

    assert len(rollup) == 1, text
    assert "exempt until )" not in rollup[0], (
        f"the roll-up claims an exemption with a blank date:\n{rollup[0]}")
    assert "NO EXEMPTION DECLARED" in rollup[0], rollup[0]


def test_a_genuinely_exempted_refusal_still_names_its_date(tmp_path):
    """ARM B — the control for the sentence above.

    Without it, the assertion is satisfied by a roll-up that stopped printing
    exemption dates at all, which would lose exactly the disclosure #584 added.
    """
    proc, _ = _run(tmp_path,
                   'run "a green gate" "$ROOT" true\n'
                   'uncheckable_until 2999-01-01 "a missing prerequisite"\n'
                   'run_tolerating_uncheckable "a refusing gate" "$ROOT" '
                   'bash -c "exit 2"\n')
    rollup = [ln for ln in proc.stdout.splitlines()
              if ln.startswith("repo_hygiene_gates:") and "NOT a pass" in ln]

    assert len(rollup) == 1, proc.stdout
    assert "exempt until 2999-01-01" in rollup[0], rollup[0]
    assert "NO EXEMPTION DECLARED" not in rollup[0], rollup[0]


# ==========================================================================
# THE INVARIANT ITSELF — not just today's instance of breaking it
# ==========================================================================
def test_every_per_gate_array_is_pushed_the_same_number_of_times(tmp_path):
    """The eight arrays are indexed by ONE gate index; a site that pushes
    seven of them is a latent `set -u` death at whichever index it skipped.

    Driven through the REAL dispatcher over a run containing every gate shape
    the file can produce — a plain gate, a tolerated refusal, a failure, and
    the synthetic empty-corpus gate — and the lengths are read out of the live
    shell rather than reasoned about from the source.
    """
    root = tmp_path
    (root / "tools" / "ci").mkdir(parents=True, exist_ok=True)
    script = root / "tools" / "ci" / "gates.sh"
    script.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT="{root}"
        . "{_LIB}"
        gate_dispatch_init "$@"
        run "a passing gate" "$ROOT" true
        uncheckable_until 2999-01-01 "a missing prerequisite"
        run_tolerating_uncheckable "a refusing gate" "$ROOT" bash -c "exit 2"
        _body() {{ run "per item ($1)" "$ROOT" true; }}
        gate_dispatch_over "an empty corpus" _body printf ""
        for _a in GATE_LABELS GATE_STATES GATE_SECONDS GATE_ITEM_CORPUS \\
                  GATE_ITEM_IDX GATE_ITEM_TOTAL GATE_EX_UNTIL GATE_EX_WHY; do
          eval "printf 'LEN %s %s\\n' \\"$_a\\" \\"\\${{#$_a[@]}}\\""
        done
        """))
    proc = subprocess.run(["bash", str(script)], cwd=str(root),
                          capture_output=True, text=True, timeout=_BOUND_S)

    lens = dict((m.group(1), int(m.group(2))) for m in
                re.finditer(r"^LEN (\S+) (\d+)$", proc.stdout, re.M))
    assert len(lens) == 8, f"could not read all eight lengths:\n{proc.stdout}\n{proc.stderr}"
    assert len(set(lens.values())) == 1, (
        f"the per-gate arrays are NOT parallel, so some gate index is a "
        f"`set -u` death waiting to be read: {lens}")
    # 3 = the passing gate, the refusing gate, and the synthetic empty-corpus
    # gate. Stated so this cannot pass by every array being empty.
    assert set(lens.values()) == {3}, lens
