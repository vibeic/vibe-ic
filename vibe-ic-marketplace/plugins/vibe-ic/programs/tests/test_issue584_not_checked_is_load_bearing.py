"""vibe-ic#584 — a gate that cannot RUN must not be free.

THE DEFECT
==========
`tools/ci/repo_hygiene_gates.sh` printed, in its own words:

    74 declared, 3 NOT CHECKED — this is NOT a pass over: <names>

and exited 0. `gatekeeper_review._hygiene_verdict` read that record, copied the
three names into its summary string, and returned rc 0 — MERGE_OK. So the sweep
said "not a pass" and the merge gate passed, which is the #539 lie one level up:
#539 fixed the SENTENCE and left the EXIT CODE and the CONSUMER alone.

Mechanically, before this change:
  * NOT_CHECKED was reachable ONLY via `run_tolerating_uncheckable` + rc 2.
    A missing binary (rc 127), an uncaught exception (rc 1) and a plain `run`
    exiting 2 all became FAIL, which is loud. That part was sound.
  * But `run` -> `run_tolerating_uncheckable` is a ONE-WORD edit that converts
    a gate's every rc-2 refusal into a tolerated non-verdict, and NOTHING
    objected — no ratchet, no baseline, no declaration. The count could go
    0 -> 3 and the only trace was a line in a log nobody exits non-zero on.

THE REPAIR, AND ITS TWO ARMS
============================
Tolerance must be BOUGHT, at the wiring site, with a date and a reason:

    uncheckable_until 2027-02-28 "needs a reachable ghcr registry: ..."
    run_tolerating_uncheckable "image-version pins resolve" "$ROOT" python3 ...

Everything below is a two-arm control over that: each test that asserts the new
refusal has a sibling asserting the SAME fixture passes once the exemption is
declared. A test that cannot pass in the other arm proves only that the script
is broken, not that it discriminates.
"""

import importlib.util
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_SCRIPT = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
_LIB = _REPO / "tools" / "ci" / "_gate_dispatch.sh"

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


GR = _load("gatekeeper_review")

#: Far enough out that this file does not become a time bomb of its own, and
#: still a real ISO date the comparison treats exactly as it treats a live one.
_FUTURE = "2999-01-01"
_PAST = "2000-01-01"


# --------------------------------------------------------------------------
# fixtures — a throwaway hygiene script sourcing the REAL dispatch library, so
# these drive the code that actually runs in CI rather than a copy of it.
# --------------------------------------------------------------------------
def _fixture_script(root: Path, gate_lines: str) -> Path:
    (root / "tools" / "ci").mkdir(parents=True, exist_ok=True)
    script = root / "tools" / "ci" / "repo_hygiene_gates.sh"
    script.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT="{root}"
        PLUGIN="{_PROGRAMS.parent}"
        PG="{_PROGRAMS}"
        . "{_LIB}"
        gate_dispatch_init "$@"
        """) + gate_lines + "\ngate_dispatch_finish\n")
    return script


def _probe(root: Path, name: str, body: str) -> Path:
    p = root / f"{name}.py"
    p.write_text(textwrap.dedent(body))
    return p


def _ok_and_refusing(root: Path):
    _probe(root, "p_ok", 'print("PASS (2 item(s) examined)")\n')
    _probe(root, "p_refuse", """
        import sys
        print("cannot look: the prerequisite is missing")
        sys.exit(2)
    """)


def _run(root: Path, gate_lines: str, *args: str):
    """Run a fixture script; return (proc, record-or-None)."""
    script = _fixture_script(root, gate_lines)
    rec = root / "record.json"
    proc = subprocess.run(
        ["bash", str(script), "--summary-json", str(rec), *args],
        cwd=str(root), capture_output=True, text=True, timeout=60)
    doc = json.loads(rec.read_text()) if rec.is_file() else None
    return proc, doc


def _refusing_gate(label: str = "a refusing gate") -> str:
    return (f'run_tolerating_uncheckable "{label}" "$ROOT" '
            f'python3 "$ROOT/p_refuse.py"\n')


_GREEN_GATE = 'run "a green gate" "$ROOT" python3 "$ROOT/p_ok.py"\n'


# ==========================================================================
# 1. THE RATCHET — an undeclared NOT_CHECKED is refused, a declared one is not
# ==========================================================================
def test_a_tolerating_gate_with_no_exemption_is_a_wiring_error(tmp_path):
    """ARM A. This is the state main shipped: tolerance taken, not bought."""
    root = tmp_path / "r"; root.mkdir()
    _ok_and_refusing(root)
    proc, doc = _run(root, _GREEN_GATE + _refusing_gate())

    assert proc.returncode == 2, (
        "a gate wired to tolerate NOT_CHECKED with no declared exemption still "
        f"lets the sweep exit {proc.returncode} — the count is not load-bearing"
        f"\n{proc.stdout}\n{proc.stderr}")
    text = proc.stdout + proc.stderr
    assert "WIRING ERROR" in text, text
    assert "a refusing gate" in text, (
        f"the mis-wired gate is not NAMED; a bare count cannot act:\n{text}")
    assert doc["wiring_errors"], doc


def test_the_same_gate_with_a_dated_reasoned_exemption_is_tolerated(tmp_path):
    """ARM B — the control. Same fixture, same refusal, exemption declared.

    Without this arm the test above proves only that the fixture is broken.
    It also pins the property the repair must NOT break: an exempted refusal
    still exits 0, because a permanently red script is a skipped script.
    """
    root = tmp_path / "r"; root.mkdir()
    _ok_and_refusing(root)
    proc, doc = _run(root, _GREEN_GATE
                     + f'uncheckable_until {_FUTURE} "needs a prerequisite this '
                       f'host does not supply"\n'
                     + _refusing_gate())

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not doc["wiring_errors"] and not doc["not_checked_unexempted"]
    assert doc["not_checked"] == 1
    rollup = [ln for ln in proc.stdout.splitlines()
              if ln.startswith("repo_hygiene_gates:")]
    assert len(rollup) == 1, proc.stdout
    # Still LOUD, still named, still "not a pass" — #539's property is intact.
    assert "NOT a pass" in rollup[0] and "a refusing gate" in rollup[0], rollup[0]
    assert f"exempt until {_FUTURE}" in rollup[0], (
        "the roll-up names the refusal but not the exemption covering it, so a "
        f"reader cannot tell a bought tolerance from an unbought one:\n{rollup[0]}")


def test_the_record_carries_the_exemption_for_each_gate(tmp_path):
    """The machine record must answer the same question as the roll-up.

    `gatekeeper_review` decides from the RECORD, not from the text, so an
    exemption visible only in prose would leave the consumer blind.
    """
    root = tmp_path / "r"; root.mkdir()
    _ok_and_refusing(root)
    _, doc = _run(root, _GREEN_GATE
                  + f'uncheckable_until {_FUTURE} "the stated reason"\n'
                  + _refusing_gate())
    by = {g["label"]: g for g in doc["gates"]}
    assert by["a refusing gate"]["exempt_until"] == _FUTURE
    assert by["a refusing gate"]["exempt_reason"] == "the stated reason"
    assert by["a refusing gate"]["exemption_expired"] is False
    # An unexempted, non-tolerating gate carries nulls — never a default date.
    assert by["a green gate"]["exempt_until"] is None


# ==========================================================================
# 2. THE EXEMPTION LIST IS ITSELF CHECKED — a stale one expires LOUDLY
# ==========================================================================
def test_an_expired_exemption_fails_the_sweep_even_though_it_fired(tmp_path):
    root = tmp_path / "r"; root.mkdir()
    _ok_and_refusing(root)
    proc, doc = _run(root, _GREEN_GATE
                     + f'uncheckable_until {_PAST} "a reason that has aged out"\n'
                     + _refusing_gate())
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert doc["exemptions_expired"] == ["a refusing gate"], doc
    assert "PAST their review date" in (proc.stdout + proc.stderr)


def test_an_expired_exemption_fails_even_when_the_gate_RAN_FINE(tmp_path):
    """The half that matters most, and the one an obvious implementation misses.

    An exemption covering a gate that currently passes is dormant, not gone. If
    it only expired when it FIRED, the day the prerequisite disappears is the
    day a years-stale exemption silently starts covering it — and that is the
    run where nobody is looking. It is a promise to revisit; the date is what
    makes anybody revisit.
    """
    root = tmp_path / "r"; root.mkdir()
    _ok_and_refusing(root)
    proc, doc = _run(root, _GREEN_GATE
                     + f'uncheckable_until {_PAST} "aged out while dormant"\n'
                     + 'run_tolerating_uncheckable "a gate that passes today" '
                       '"$ROOT" python3 "$ROOT/p_ok.py"\n')
    assert doc["not_checked"] == 0, "the fixture gate was meant to PASS"
    assert proc.returncode == 1, (
        "a stale exemption over a currently-passing gate expired silently; it "
        f"will be there, unreviewed, on the day the gate stops running\n"
        f"{proc.stdout}\n{proc.stderr}")
    assert doc["exemptions_expired"] == ["a gate that passes today"]


def test_an_unexpired_exemption_over_a_passing_gate_is_quiet(tmp_path):
    """The control for the two above: a live exemption is not itself a defect."""
    root = tmp_path / "r"; root.mkdir()
    _ok_and_refusing(root)
    proc, doc = _run(root, _GREEN_GATE
                     + f'uncheckable_until {_FUTURE} "still true"\n'
                     + 'run_tolerating_uncheckable "a gate that passes today" '
                       '"$ROOT" python3 "$ROOT/p_ok.py"\n')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["exemptions_expired"] == []
    assert "all 2 gate(s) passed" in proc.stdout, proc.stdout


# ==========================================================================
# 3. THE EXEMPTION CANNOT BE VAGUE, DANGLING, OR ON THE WRONG GATE
# ==========================================================================
@pytest.mark.parametrize("lines,needle", [
    # A date that is not a date cannot be compared, so it could never expire.
    (f'uncheckable_until nextyear "a reason"\n' + _refusing_gate(),
     "ISO-8601"),
    # An exemption with no reason is a skip button with a date printed on it.
    (f'uncheckable_until {_FUTURE} ""\n' + _refusing_gate(),
     "must state WHY"),
    # Attached to a gate that can never report NOT_CHECKED: it describes a
    # tolerance the reader would believe and the gate does not have.
    (f'uncheckable_until {_FUTURE} "a reason"\n'
     + 'run "an intolerant gate" "$ROOT" python3 "$ROOT/p_ok.py"\n',
     "can never report NOT_CHECKED"),
    # Declared twice, so the first covers nothing.
    (f'uncheckable_until {_FUTURE} "first"\n'
     f'uncheckable_until {_FUTURE} "second"\n' + _refusing_gate(),
     "never attached to a gate"),
    # Declared after the last gate: the author believed they had covered one.
    (_GREEN_GATE + f'uncheckable_until {_FUTURE} "a reason"\n',
     "attaches to nothing"),
])
def test_a_malformed_exemption_is_refused(tmp_path, lines, needle):
    root = tmp_path / "r"; root.mkdir()
    _ok_and_refusing(root)
    proc, _doc = _run(root, lines)
    assert proc.returncode == 2, (
        f"expected a wiring refusal for {needle!r}\n{proc.stdout}\n{proc.stderr}")
    assert needle in (proc.stdout + proc.stderr), proc.stdout + proc.stderr


def test_a_mis_wired_gate_does_not_leak_its_exemption_onto_the_next_gate(tmp_path):
    """The slot is consumed unconditionally, including by the gate that erred.

    Left armed, an exemption written for gate N would silently excuse gate N+1
    — an exemption on a gate nobody chose to exempt, which is worse than none.
    """
    root = tmp_path / "r"; root.mkdir()
    _ok_and_refusing(root)
    proc, doc = _run(root,
                     f'uncheckable_until {_FUTURE} "written for the green gate"\n'
                     + _GREEN_GATE          # consumes it, and errors: intolerant
                     + _refusing_gate())    # must NOT inherit it
    assert proc.returncode == 2
    text = proc.stdout + proc.stderr
    assert "can never report NOT_CHECKED" in text, text
    assert "a refusing gate" in text and "tolerance has to be bought" in text, (
        f"the exemption leaked forward onto the next gate:\n{text}")


def test_an_unreadable_clock_refuses_rather_than_making_exemptions_immortal(tmp_path):
    """Fail CLOSED on the clock.

    Every expiry decision is `until < today`. With `today` empty or malformed,
    no `until` ever compares as due, so every exemption becomes immortal and
    the expiry half of this change is silently absent — a check that stops
    checking without saying so. It has to be rc 2, not a quiet pass.
    """
    root = tmp_path / "r"; root.mkdir()
    _ok_and_refusing(root)
    # Shadow `date` with one that cannot answer, ahead of the real one on PATH.
    shim = root / "bin"; shim.mkdir()
    (shim / "date").write_text("#!/bin/sh\nexit 1\n")
    (shim / "date").chmod(0o755)

    script = _fixture_script(root, _GREEN_GATE
                             + f'uncheckable_until {_PAST} "long expired"\n'
                             + _refusing_gate())
    import os
    env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")
    proc = subprocess.run(["bash", str(script)], cwd=str(root), env=env,
                          capture_output=True, text=True, timeout=60)
    text = proc.stdout + proc.stderr
    assert proc.returncode == 2, (
        "an unreadable clock let a long-expired exemption through — every "
        f"exemption is immortal in this state:\n{text}")
    assert "could not read today's date" in text, text


# ==========================================================================
# 4. `--list` — static wiring is enforced; a wall-clock verdict is not
# ==========================================================================
def test_list_mode_still_catches_a_missing_exemption(tmp_path):
    """The cheap 1-second enumeration catches the DECLARATION defect."""
    root = tmp_path / "r"; root.mkdir()
    _ok_and_refusing(root)
    proc, _ = _run(root, _GREEN_GATE + _refusing_gate(), "--list")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "WIRING ERROR" in (proc.stdout + proc.stderr)


def test_list_mode_does_not_apply_the_wall_clock(tmp_path):
    """`--list` answers "what does this script declare", and that answer must
    not change with the date — otherwise the enumeration every parser-vs-runner
    drift test depends on would start flapping on a calendar boundary."""
    root = tmp_path / "r"; root.mkdir()
    _ok_and_refusing(root)
    proc, doc = _run(root, _GREEN_GATE
                     + f'uncheckable_until {_PAST} "expired but only declared"\n'
                     + _refusing_gate(), "--list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # The staleness is still RECORDED — not enforced here, not hidden either.
    assert doc["exemptions_expired"] == ["a refusing gate"], doc


# ==========================================================================
# 5. THE CONSUMER — the merge gate must refuse what the sweep refused
# ==========================================================================
def test_the_merge_gate_refuses_an_unexempted_not_checked(tmp_path):
    """Lie-shape #1, end to end: the sweep says NOT CHECKED, MERGE_OK follows.

    Driven through the REAL `repo_hygiene_gate`, which runs the REAL dispatch
    library over a fixture gate set — not through a hand-written record.
    """
    root = tmp_path / "r"; root.mkdir()
    _ok_and_refusing(root)
    script = _fixture_script(root, _GREEN_GATE + _refusing_gate())
    res = GR.repo_hygiene_gate(root, script=script)
    assert res.rc != 0, (
        "the merge gate answered a pass over a hygiene set that named a gate "
        f"it could not run: {res.summary}")
    assert "wiring error" in res.summary.lower(), res.summary


def test_the_merge_gate_accepts_an_exempted_not_checked(tmp_path):
    """The control. A bought tolerance still lands, and still says so."""
    root = tmp_path / "r"; root.mkdir()
    _ok_and_refusing(root)
    script = _fixture_script(root, _GREEN_GATE
                             + f'uncheckable_until {_FUTURE} "a stated reason"\n'
                             + _refusing_gate())
    res = GR.repo_hygiene_gate(root, script=script)
    assert res.rc == 0, res.summary
    assert "NOT CHECKED (not a pass)" in res.summary, res.summary


def test_the_merge_gate_refuses_an_expired_exemption(tmp_path):
    root = tmp_path / "r"; root.mkdir()
    _ok_and_refusing(root)
    script = _fixture_script(root, _GREEN_GATE
                             + f'uncheckable_until {_PAST} "aged out"\n'
                             + _refusing_gate())
    res = GR.repo_hygiene_gate(root, script=script)
    assert res.rc == 1, res.summary
    assert "PAST" in res.summary and "a refusing gate" in res.summary, res.summary


def test_a_record_predating_the_exemption_mechanism_fails_SAFE():
    """An old or hand-written summary must not be the way to buy silence.

    `_hygiene_verdict` derives the unexempted list from the per-gate records
    when the top-level key is absent. The default direction is the whole point:
    a NOT_CHECKED with no `exempt_until` reads as UNEXEMPTED and refuses. The
    opposite default would make "produce a record in the old format" a skip
    button for the entire mechanism.
    """
    stale = {"declared": 2, "seconds": 1, "gates": [
        {"label": "a green gate", "state": "PASS", "seconds": 0},
        {"label": "a refusing gate", "state": "NOT_CHECKED", "seconds": 0},
    ]}
    res = GR._hygiene_verdict(stale, 0)
    assert res.rc == 1, (
        "a record with no exemption fields was read as if every NOT_CHECKED in "
        f"it were exempt: {res.summary}")
    assert "no declared exemption" in res.summary, res.summary


# ==========================================================================
# 6. THE REAL SCRIPT — wired correctly, and its dates are still in the future
# ==========================================================================
def test_the_real_hygiene_script_declares_every_tolerance_it_takes():
    """Proved by INVOKING the real script, not by re-parsing it.

    `--list` runs the real declarations through the real dispatcher in about a
    second and returns 2 if any `run_tolerating_uncheckable` lacks an exemption,
    so this cannot drift from what a full sweep would conclude.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        rec = Path(td) / "record.json"
        out = subprocess.run(
            ["bash", str(_SCRIPT), "--list", "--summary-json", str(rec)],
            cwd=str(_REPO), capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, (
            "the shipped hygiene script is mis-wired:\n"
            f"{out.stdout}\n{out.stderr}")
        doc = json.loads(rec.read_text())

    exempt = [g for g in doc["gates"] if g["exempt_until"]]
    assert exempt, (
        "no gate in the real script declares an exemption — either the "
        "mechanism is unwired, or every `run_tolerating_uncheckable` is gone "
        "and this test should be deleted along with them")
    for g in exempt:
        assert len(g["exempt_reason"] or "") >= 40, (
            f"{g['label']}: the exemption reason is too terse to tell a reader "
            f"which prerequisite was missing: {g['exempt_reason']!r}")


def test_no_exemption_reason_is_silently_eaten_by_the_shell():
    """A reason is a double-quoted BASH string, so backticks and `$` expand.

    MEASURED, not hypothesised: the first draft of the `blocker list contract`
    exemption read "... predate the `blockers` key ...", and the sweep printed
    "predate the  key" — bash ran `blockers` as a command, it failed, and the
    empty result was substituted in silence. The reason is the whole value of
    the exemption; one that quietly loses a word is a reason a reader cannot
    act on, and nothing in the run says a word went missing.

    Caught statically because it CANNOT be caught at run time: `uncheckable_
    until` receives the string already expanded, so by then the word is gone.
    """
    bad = []
    for m in re.finditer(r'^\s*uncheckable_until\s+\S+\s+"([^"]*)"',
                         _SCRIPT.read_text(), re.M):
        reason = m.group(1)
        hits = [c for c in ("`", "$") if c in reason]
        if hits:
            bad.append((hits, reason[:70]))
    assert not bad, (
        "exemption reason(s) contain shell-expanding characters, which bash "
        "substitutes away inside the double quotes before the dispatcher ever "
        "sees them: " + "; ".join(f"{h} in {r!r}" for h, r in bad))


def test_no_shipped_exemption_is_already_stale():
    """The expiry, enforced where a landing actually looks.

    The sweep enforces this too, but the sweep is minutes and pytest is what
    runs on every landing. When this goes red the fix is one line: re-review the
    named gate and restate the date with a reason that is still true, or delete
    the tolerance.
    """
    import datetime
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    stale = [(m.group(2), m.group(1)) for m in re.finditer(
        r'^uncheckable_until\s+(\d{4}-\d{2}-\d{2})\s+"([^"]*)"',
        _SCRIPT.read_text(), re.M) if m.group(1) < today]
    assert not stale, (
        "uncheckable exemption(s) are past their review date: "
        + "; ".join(f"(due {d}) {r[:80]}" for r, d in stale))
