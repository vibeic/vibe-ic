"""A merge that keeps both sides, and the verdict it deletes on the way (#1228).

`EDA_FORK_SYNC_LOG.md` records one gatekeeper round per `## <date> — <image>`
section. Consecutive rounds report the SAME tools, so consecutive sections
share long, byte-identical bullet lines — and a 3-way text merge reads a shared
line as common CONTEXT belonging to both sections at once.

Measured on `origin/main` @ `75776dbbb` merging PR #1238:

    main    ## 2026-08-12 — 0.2.91   Trilinos · cocotb · ngspice · open_pdks
    PR1238  ## 2026-08-13 — 0.2.92   Trilinos · cocotb ·           open_pdks

The `open_pdks` line lands OUTSIDE the conflict hunk. Resolve the hunk the
obvious way — keep both sides, because these ARE two independent daily reports
— and the shared line is claimed by the later section. The earlier round, which
already landed, silently loses a verdict it recorded.

The result parses, renders, and reads as a `+6/-0` append. Nothing in the tree
could tell it from a round that genuinely had three verdicts, because until
this gate nothing in the tree read the ledger at all.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

from _hostpaths import repo_path

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "eda_fork_sync_log_append_only_check.py"

#: The real checked-in ledger. Class (a) in-repo artefact — resolved, never
#: hardcoded. Tests that need it skip with a named reason when absent (the
#: flattened plugin cache does not carry repo-root `tools/`).
REAL_LOG = repo_path("tools", "vibeic-eda", "EDA_FORK_SYNC_LOG.md")


def _run(base_file, head_file, *extra):
    return subprocess.run(
        [sys.executable, str(PROG),
         "--base-file", str(base_file), "--head-file", str(head_file), *extra],
        capture_output=True, text=True, timeout=60)


def _round(title, bullets):
    return f"## {title}\n\n" + "".join(f"- **DEFERRED** {b}\n" for b in bullets) + "\n"


# ── synthesized fixtures: neutral tool names, no design/PDK/vendor literal ───
_R1 = _round("2026-01-01 — img:1.0.0", ["alpha → ? — no forward range", "beta → ? — deferred", "gamma → 2.0 — artefact decision"])
_R2 = _round("2026-01-02 — img:1.0.1", ["alpha → ? — no forward range", "beta → ? — deferred", "gamma → 2.0 — artefact decision"])

BASE = "# ledger\n\n" + _R1
APPENDED = BASE + _R2


@pytest.fixture()
def files(tmp_path):
    def write(base_text, head_text):
        b = tmp_path / "base.md"
        h = tmp_path / "head.md"
        b.write_text(base_text, encoding="utf-8")
        h.write_text(head_text, encoding="utf-8")
        return b, h
    return write


# ── the defect ───────────────────────────────────────────────────────────────
def test_take_both_sides_that_steals_a_bullet_FAILS(files):
    """THE #1228 SHAPE. Both rounds are present, both headings survive, the
    diff is a net +N — and the earlier round lost the bullet the later one now
    claims. This is the assertion the gate exists for."""
    collapsed = ("# ledger\n\n"
                 + _round("2026-01-01 — img:1.0.0",
                          ["alpha → ? — no forward range", "beta → ? — deferred"])
                 + _R2)
    b, h = files(BASE, collapsed)
    r = _run(b, h)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "round_edited" in r.stderr
    assert "gamma" in r.stderr, "the gate must NAME the verdict that vanished"


def test_the_correct_resolution_PASSES(files):
    """The same two rounds, appended instead of collapsed. Paired with the test
    above — alone it would pass vacuously against a gate that never fires."""
    b, h = files(BASE, APPENDED)
    r = _run(b, h)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 appended" in r.stdout


def test_a_landed_round_deleted_outright_FAILS(files):
    b, h = files(APPENDED, "# ledger\n\n" + _R2)
    r = _run(b, h)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "round_dropped" in r.stderr


def test_a_landed_round_reordered_FAILS(files):
    """Rules 1+2 alone are satisfiable by a reshuffle: every base round present,
    every body byte-identical, chronology destroyed."""
    b, h = files(APPENDED, "# ledger\n\n" + _R2 + _R1)
    r = _run(b, h)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "round_reordered" in r.stderr


def test_an_unresolved_conflict_marker_FAILS(files):
    b, h = files(BASE, BASE + "<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> other\n")
    r = _run(b, h)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "conflict_marker" in r.stderr


def test_two_rounds_with_the_same_heading_FAILS(files):
    b, h = files(BASE, BASE + _R1)
    r = _run(b, h)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "duplicate_round" in r.stderr


def test_a_setext_underline_is_not_read_as_a_conflict_marker(files):
    """`=======` under a line is markdown H1, not half a conflict. A gate that
    fires on legitimate content is a bug in the gate (flow-change-acceptance §2)."""
    b, h = files(BASE, BASE + _R2.rstrip("\n") + "\n\nHeading\n=======\n\n")
    r = _run(b, h)
    assert r.returncode == 0, r.stdout + r.stderr


def test_whitespace_between_rounds_is_not_an_edit(files):
    b, h = files(BASE, BASE.rstrip("\n") + "\n\n\n" + _R2)
    r = _run(b, h)
    assert r.returncode == 0, r.stdout + r.stderr


# ── an unanswered question is not a pass ─────────────────────────────────────
def test_an_unreadable_base_is_CANNOT_MEASURE_not_PASS(tmp_path):
    h = tmp_path / "head.md"
    h.write_text(BASE, encoding="utf-8")
    r = _run(tmp_path / "nope.md", h)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "CANNOT-MEASURE" in r.stderr


def test_a_missing_revision_is_CANNOT_MEASURE_not_PASS(tmp_path):
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], timeout=60)
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--base", "no/such/rev"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, r.stdout + r.stderr


def test_json_records_blocking_and_the_violation_list(files, tmp_path):
    """§5 — the verdict states that it BLOCKS, in the gate's own output."""
    out = tmp_path / "v.json"
    b, h = files(APPENDED, "# ledger\n\n" + _R2)
    r = _run(b, h, "--json", str(out))
    assert r.returncode == 1
    d = json.loads(out.read_text())
    assert d["verdict"] == "FAIL" and d["blocking"] is True
    assert d["violations"] and d["violations"][0]["kind"] == "round_dropped"


# ── driven by the real checked-in ledger, not by a fixture ───────────────────
@pytest.mark.skipif(not REAL_LOG.is_file(),
                    reason=f"in-repo ledger not present at {REAL_LOG} "
                           f"(flattened plugin cache carries no repo-root tools/)")
def test_the_real_ledger_appended_to_PASSES(files):
    """A gate whose every test is a fixture authored beside it cannot tell
    itself from its own absence (#400). This one reads the shipped ledger."""
    real = REAL_LOG.read_text(encoding="utf-8")
    b, h = files(real, real.rstrip("\n") + "\n\n" + _R2)
    r = _run(b, h)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(not REAL_LOG.is_file(),
                    reason=f"in-repo ledger not present at {REAL_LOG}")
def test_the_real_ledger_losing_one_real_bullet_FAILS(files):
    """The #1228 collapse, reconstructed on REAL content: take the last bullet
    of the last-but-one round — the shared line git hands to whichever section
    comes second — and delete it. Everything else is byte-identical."""
    real = REAL_LOG.read_text(encoding="utf-8")
    lines = real.splitlines(keepends=True)
    heads = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    assert len(heads) >= 2, "the real ledger should carry at least two rounds"
    # the last bullet belonging to the second-to-last round
    victim = max(i for i in range(heads[-2], heads[-1]) if lines[i].startswith("- "))
    mutated = "".join(lines[:victim] + lines[victim + 1:])
    assert mutated != real
    b, h = files(real, mutated)
    r = _run(b, h)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "round_edited" in r.stderr


# ── §3 prove-by-run: the gate is WIRED, and a wired gate that cannot stop the
#    flow differs from no gate only in being auditable after the fact ─────────
_PROGRAMS_STR = str(_PROGRAMS)
if _PROGRAMS_STR not in sys.path:
    sys.path.insert(0, _PROGRAMS_STR)
import gatekeeper_review as GR  # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=60)


def _ledger_repo(tmp_path, head_text):
    """A repo whose base carries BASE and whose head carries `head_text`."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    p = tmp_path / "tools" / "vibeic-eda"
    p.mkdir(parents=True)
    log = p / "EDA_FORK_SYNC_LOG.md"
    log.write_text(BASE, encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    log.write_text(head_text, encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "head")
    return base, _git(tmp_path, "rev-parse", "HEAD").stdout.strip()


def test_gatekeeper_review_BLOCKS_the_stolen_bullet(tmp_path):
    """The verdict must be non-green, so the landing stops. Reading the wiring
    is not evidence that it blocks — this runs it."""
    collapsed = ("# ledger\n\n"
                 + _round("2026-01-01 — img:1.0.0",
                          ["alpha → ? — no forward range", "beta → ? — deferred"])
                 + _R2)
    base, head = _ledger_repo(tmp_path, collapsed)
    res = GR.fork_sync_log_gate(tmp_path, base, head)
    assert res.rc == 1, res
    assert res.green is False, "a FAIL that does not block is not a gate"


def test_gatekeeper_review_PASSES_the_correct_append(tmp_path):
    base, head = _ledger_repo(tmp_path, APPENDED)
    res = GR.fork_sync_log_gate(tmp_path, base, head)
    assert res.rc == 0 and res.green, res


def test_gatekeeper_review_reports_an_unresolvable_base_as_NOT_CHECKED(tmp_path):
    """Non-blocking, because it is not a finding — but NAMED, because a silent
    decline reads downstream as 'nothing needed doing' (§6)."""
    base, head = _ledger_repo(tmp_path, APPENDED)
    res = GR.fork_sync_log_gate(tmp_path, "no/such/rev", head)
    assert res.rc == -1 and res.green, res
    assert "NOT CHECKED" in res.summary


def test_the_gate_is_in_the_assembled_gate_list(tmp_path):
    """A gate function nobody calls is ORPHANED. Pins the call site so a future
    refactor cannot quietly drop it back out of the landing set."""
    src = (_PROGRAMS / "gatekeeper_review.py").read_text(encoding="utf-8")
    assert "gates.append(fork_sync_log_gate(repo, base, head))" in src
