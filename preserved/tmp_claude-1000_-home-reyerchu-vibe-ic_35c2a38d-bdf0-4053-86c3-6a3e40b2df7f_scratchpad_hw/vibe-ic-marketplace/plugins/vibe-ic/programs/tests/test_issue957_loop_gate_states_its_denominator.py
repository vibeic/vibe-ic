"""vibe-ic#957 — a loop-driven gate must say how many items it expanded over.

THE MEASUREMENT
===============
`tools/ci/repo_hygiene_gates.sh` wires three gates PER PUBLISHED CELL, over the
corpus its own loop selects:

    $ git ls-files -- 'benchmark-data/ic/*/*/phase3/stage3/pnr/routed.def'
    <one path>

ONE cell. Three gates, one denominator, on every merge. None of the three gates
is wrong, and the `git ls-files` loop is itself the repair for a much worse
problem — a working-directory glob once took the declared gate count from 68 to
169 on a checkout carrying run leftovers. What was wrong is one level up: the
LABELS read like corpus coverage, the roll-up counted three green rows among
~74, and a reader took from it that post-route geometry is checked across the
published corpus. The number was true and the impression was false.

`gate_discloses_denominator_check` already demands of every gate INDIVIDUALLY
that a PASS say how much it looked at. The ROLL-UP is where that requirement
was missing, and this file is where it is now pinned.

WHAT THESE TESTS PIN, AND WHAT THEY DELIBERATELY DO NOT
=======================================================
NOTHING HERE TYPES THE CORPUS SIZE. The glob is read out of the gate script and
run, so the expected denominator is whatever the commit publishes: these tests
say the disclosure must be TRUE, not that it must be 1. If a tenth cell is
published tomorrow they follow it without an edit — a test carrying `1` would
be the next hand-maintained fact to drift, which is the defect this whole file
is about.

THEY DO NOT ASK FOR MORE CELLS. Whether more published cells should carry a
routed DEF is a publishing decision with a real repository-size cost and it is
not a side effect of making a roll-up honest. These tests would pass unchanged
over a corpus of one and over a corpus of nine.

PAIRED GUARDS. Three of the tests below must pass BEFORE and AFTER the change:
a gate wired outside a loop prints exactly what it printed before, its record
entry is unchanged, and the per-cell coverage neither grew nor shrank. Without
them the disclosure could be bought by moving output that was already right, or
by quietly dropping a gate.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_REPO = _PROGRAMS.parents[3]
_SCRIPT = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
_LIB = _REPO / "tools" / "ci" / "_gate_dispatch.sh"
#: The producer library the script sources (vibe-ic#1075).
_CORPUS_LIB = _REPO / "tools" / "ci" / "_published_cell_corpus.sh"

#: Every fixture gate returns instantly, and the real script's `--list` is
#: measured at 0.03 s. This only stops a hung one from taking the pytest
#: session down, and stays under the 60 s ceiling
#: `ci_harness_timeout_ceiling_check` enforces.
_T = 55

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


def _load(base: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, base / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


#: The ONE parser of the hygiene script. Imported, never re-written: this repo
#: has already paid for a second copy of that regex living in a second file.
GD = _load(_PROGRAMS, "gate_discloses_denominator_check")
#: And the ONE reconciler of records against declarations, for the paired guard
#: that the denominator did not get glued into a gate's identity.
_538 = _load(_TESTS, "test_issue538_merge_gate_covers_ci_hygiene")


# ── what the script's corpus IS, discovered rather than declared ────────────
def _published_corpora() -> dict:
    """{corpus_name: [items]} — every loop corpus the script declares.

    Was `_published_corpus()` returning ONE list, because the script drove one
    loop over one corpus. vibe-ic#1075 gives two of the three per-cell gates the
    population they actually READ (a DRC report; a `reports/` tree), so there
    are now three. Every assertion in this file is applied per corpus; none was
    dropped to accommodate the count.

    INDEPENDENCE IS PRESERVED, which is the point of the original. #957 scraped
    the glob out of the script and ran `git ls-files` itself so it could not
    agree with the record by construction. Reading `doc["corpora"]` for the
    counts would be circular — a record that over-counted would validate
    itself. So this parses the `gate_dispatch_over` lines for (name, producer),
    SOURCES the shipped producer library, and RUNS each producer for real. The
    counts compared against the record are the producers' own output.
    """
    text = _SCRIPT.read_text(errors="replace")
    joined = re.sub(r"\\\s*\n\s*", " ", text)
    decls = [(m.group(1), m.group(3)) for m in
             re.finditer(r'gate_dispatch_over\s+"([^"]+)"\s+(\S+)\s+(\S+)', joined)]
    assert decls, (
        "the hygiene script declares no loop corpus at all, so this test "
        "cannot know what any loop expands over")
    assert _CORPUS_LIB.is_file(), (
        f"the script sources {_CORPUS_LIB.name} but it is absent, so the "
        "shipped producers cannot be driven")
    out = {}
    for name, fn in decls:
        sh = f'set -euo pipefail\nROOT="{_REPO}"\n. "{_CORPUS_LIB}"\n{fn}\n'
        res = subprocess.run(["bash", "-c", sh], capture_output=True,
                             text=True, timeout=_T)
        assert res.returncode == 0, f"producer {fn} failed: {res.stderr}"
        out[name] = [ln for ln in res.stdout.splitlines() if ln.strip()]
    return out
def _templated_decls():
    """The `run` lines a LOOP drives: the parser says so, this file does not."""
    return [d for d in GD.parse_declarations(_SCRIPT) if d.runtime_expansion]


def _literal_decls():
    return [d for d in GD.parse_declarations(_SCRIPT) if not d.runtime_expansion]


def _literal_prefix(label: str) -> str:
    """A templated label up to its first expansion — `macro OBS … (`."""
    return label.split("$")[0]


def _list_run(script: Path, cwd: Path):
    """(stdout, stderr, record) for `--list`, which drives the REAL dispatch."""
    with tempfile.TemporaryDirectory() as td:
        rec = Path(td) / "record.json"
        out = subprocess.run(
            ["bash", str(script), "--list", "--summary-json", str(rec)],
            cwd=str(cwd), capture_output=True, text=True, timeout=_T)
        assert out.returncode == 0, out.stdout + out.stderr
        return out.stdout, out.stderr, json.loads(rec.read_text())


#: A row that states a denominator: "… of N …". Deliberately looser than the
#: exact sentence the dispatcher prints — the requirement is that the number is
#: THERE and correct, not that it is phrased one way.
_DENOM_RE = re.compile(r"\bof\s+(\d+)\b")


# ==========================================================================
# THE DISCLOSURE
# ==========================================================================
def test_every_loop_driven_row_states_how_many_items_the_loop_expanded_over():
    """Per corpus. The assertion is unchanged; it is applied to each of them."""
    templated = _templated_decls()
    assert templated, "the script no longer drives any gate from a loop"
    stdout, _, _doc = _list_run(_SCRIPT, _REPO)
    rows = [ln for ln in stdout.splitlines() if ln.strip()]
    for name, items in _published_corpora().items():
        assert items, (
            f"loop corpus {name!r} expanded over NOTHING. A disclosure achieved "
            "by narrowing a corpus to zero is a coverage cut wearing a fix's "
            "clothes, which is what this guard exists to refuse")
        mine = [ln for ln in rows if "[item " in ln and name in ln]
        assert mine, f"no loop-driven row names corpus {name!r}"
        for ln in mine:
            m = re.search(r"of (\d+) over ", ln)
            assert m, f"a loop row states no denominator: {ln}"
            assert int(m.group(1)) == len(items), (
                f"row says {m.group(1)} item(s); the shipped producer for "
                f"{name!r} selects {len(items)}: {ln}")
def test_the_rollup_names_the_corpus_and_the_size_it_expanded_over():
    """The roll-up is what a reader believes, and it is where this was missing.

    Per corpus now: EVERY declared corpus must be named in the roll-up with the
    size it expanded over. `len(corpora) == 1` is gone — that was an assumption
    about the script's SHAPE, not a guard — and every guard it stood beside is
    applied to all of them instead of one.
    """
    stdout, stderr, doc = _list_run(_SCRIPT, _REPO)
    record = doc.get("corpora")
    assert record, (
        "the machine record carries no corpus entry, so a consumer of the "
        "record — which is what the merge gate reads — still cannot tell how "
        "many items the loop-driven gates covered")
    corpora = _published_corpora()
    assert len(record) == len(corpora), (
        f"the record declares {len(record)} corpus/corpora; the script drives "
        f"{len(corpora)}")
    by_name = {c["name"]: c for c in record}
    for name, items in corpora.items():
        assert name in by_name, f"the record carries no entry for {name!r}"
        c = by_name[name]
        assert c["items"] == len(items), (
            f"{name!r}: record says {c['items']} item(s); the shipped producer "
            f"selects {len(items)}")
        said = [ln for ln in (stdout + stderr).splitlines()
                if name in ln and re.search(rf"\b{len(items)}\b", ln)]
        assert said, (
            f"no line of the roll-up names {name!r} and how many items it "
            f"expanded over ({len(items)}):\n{stderr}")
def test_the_declared_count_is_still_a_count_of_GATES_not_of_items():
    """PAIRED with the two above: the disclosure must not be bought by
    inflating `declared`, which is the number the merge gate reports coverage
    against."""
    _, _, doc = _list_run(_SCRIPT, _REPO)
    assert doc["declared"] == len(doc["gates"])
    assert doc["declared"] == sum(1 for ln in _list_run(_SCRIPT, _REPO)[0]
                                  .splitlines() if ln.strip())


# ==========================================================================
# ZERO — the case that leaves no gate behind to speak for itself
# ==========================================================================
def _fixture(root: Path, body: str) -> Path:
    (root / "tools" / "ci").mkdir(parents=True, exist_ok=True)
    s = root / "tools" / "ci" / "gates.sh"
    s.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT="{root}"
        . "{_LIB}"
        gate_dispatch_init "$@"
        """) + body + "\ngate_dispatch_finish\n")
    return s


def _run_fixture(root: Path, body: str):
    rec = root / "rec.json"
    out = subprocess.run(
        ["bash", str(_fixture(root, body)), "--summary-json", str(rec)],
        cwd=str(root), capture_output=True, text=True, timeout=_T)
    doc = json.loads(rec.read_text()) if rec.is_file() else {}
    return out, doc


_OK = 'python3 -c "print(\'PASS (1 item(s) examined)\')"'


def test_a_loop_that_expands_over_NOTHING_is_still_reported(tmp_path):
    """A corpus of zero declares no gate, so it cannot be counted, cannot be
    NOT_CHECKED, and cannot fail. The gate set silently shrinks and every
    remaining sentence stays true — which is the vacuous pass this repo removes
    from gates one at a time, arriving through the denominator instead of
    through a state."""
    out, doc = _run_fixture(tmp_path, (
        f'run "a flat gate" "$ROOT" {_OK}\n'
        f'_body() {{ run "per item ($1)" "$ROOT" {_OK}; }}\n'
        'gate_dispatch_over "an empty corpus" _body printf ""\n'))
    text = out.stdout + out.stderr
    assert out.returncode == 0, text
    assert doc["declared"] == 1, doc
    assert [c for c in doc.get("corpora", []) if c["items"] == 0], (
        "a loop that expanded over nothing left no trace in the record:\n"
        + json.dumps(doc, indent=1))
    assert "an empty corpus" in text and "0 item" in text, (
        "the run never said that a loop covered nothing:\n" + text)
    closing = [ln for ln in out.stdout.splitlines()
               if ln.startswith("repo_hygiene_gates: all ")]
    assert closing, text
    assert "NOTHING was checked" in closing[-1] and "an empty corpus" in \
        closing[-1], (
        "the closing sentence stands unqualified over a corpus that expanded "
        f"to nothing:\n  {closing[-1]}")


def test_a_producer_that_FAILED_is_not_reported_as_an_empty_corpus(tmp_path):
    """`git ls-files` in a non-repository prints nothing and exits non-zero.
    "I could not look" must not reach a reader as "there was nothing there" —
    the same distinction NOT_CHECKED draws one level down."""
    out, doc = _run_fixture(tmp_path, (
        f'run "a flat gate" "$ROOT" {_OK}\n'
        f'_body() {{ run "per item ($1)" "$ROOT" {_OK}; }}\n'
        'gate_dispatch_over "an unreadable corpus" _body '
        'git -C /nonexistent-corpus-root ls-files\n'))
    text = out.stdout + out.stderr
    assert out.returncode == 0, text
    assert [c for c in doc.get("corpora", [])
            if c.get("expansion") == "PRODUCER_FAILED"], json.dumps(doc)
    assert "PRODUCER FAILED" in text, text


def test_a_loop_written_AROUND_the_dispatcher_is_caught_and_named(tmp_path):
    """The disclosure comes from the dispatcher so that a future loop cannot be
    added without it. A hand-written `for` is the one way round that, so it is
    detected — one `run` line, many gates, no expansion open — and NAMED with
    its file and line rather than assumed absent."""
    out, doc = _run_fixture(tmp_path, (
        'for _i in one two three; do\n'
        f'  run "raw loop ($_i)" "$ROOT" {_OK}\n'
        'done\n'))
    text = out.stdout + out.stderr
    assert out.returncode == 0, text
    assert doc["declared"] == 3, doc
    assert doc.get("undisclosed_loops"), (
        "a loop wired around the dispatcher left the roll-up unable to state "
        "its denominator and said nothing about it:\n" + json.dumps(doc))
    assert "LOOP WITHOUT A DECLARED DENOMINATOR" in text, text
    assert "gates.sh:" in text, (
        "the undisclosed loop is not located — a reader cannot find the line "
        f"to fix:\n{text}")


# ==========================================================================
# PAIRED GUARDS — these must pass BEFORE the change as well as after
# ==========================================================================
def test_a_gate_wired_OUTSIDE_a_loop_prints_exactly_its_label():
    """THE INVISIBILITY REQUIREMENT. ~70 of the gates are not loop-driven and
    this change must not touch a byte of what they print."""
    literal = _literal_decls()
    assert len(literal) > 40, (
        "the population this guard protects has collapsed; it would now pass "
        f"over almost nothing ({len(literal)} literal declaration(s))")
    stdout, _, _ = _list_run(_SCRIPT, _REPO)
    rows = [ln for ln in stdout.splitlines() if ln.strip()]
    missing = [d.label for d in literal if d.label not in rows]
    assert not missing, (
        "a gate wired outside any loop no longer prints its label verbatim: "
        f"{missing[:5]}")


def test_the_record_still_carries_the_gate_LABEL_as_its_identity():
    """A denominator glued into the label would make every loop-driven record
    unattributable to the `run` line that produced it — two other programs
    parse this script and reconcile exactly that."""
    decls = GD.parse_declarations(_SCRIPT)
    _, _, doc = _list_run(_SCRIPT, _REPO)
    recorded = [g["label"] for g in doc["gates"]]
    unattributed, silent = _538.reconcile(decls, recorded)
    assert not unattributed, (
        "the dispatcher recorded gate(s) no `run` line explains — the label is "
        f"no longer the gate's identity: {sorted(set(unattributed))[:5]}")
    assert not silent, silent


def test_every_published_cell_is_still_covered_by_every_per_cell_gate():
    """The other half: a disclosure that was achieved by dropping a gate, or by
    narrowing the corpus, would be a coverage cut wearing a fix's clothes.

    Per corpus. A gate must fire over every item of ITS OWN corpus, which is a
    STRICTER statement than the original once the corpora differ: a gate can no
    longer be credited by a corpus it does not read.
    """
    stdout, _, _doc = _list_run(_SCRIPT, _REPO)
    rows = [ln for ln in stdout.splitlines() if ln.strip()]
    for name, items in _published_corpora().items():
        mine = [ln for ln in rows if "[item " in ln and name in ln]
        assert mine, f"no gate fired over corpus {name!r}"
        # Group by the LITERAL PREFIX, not the whole label: a per-cell label
        # embeds the item (`DRC PASS is not vacuous (spm/v1.5.58…)`), so the
        # full string is unique per row and would count 1 every time. This is
        # the same `_literal_prefix` the original used, applied per corpus.
        prefixes = {_literal_prefix(d.label) for d in _templated_decls()}
        fired = {p: [ln for ln in mine if ln.startswith(p)] for p in prefixes}
        for pref, got in fired.items():
            if not got:
                continue          # that gate belongs to a different corpus
            assert len(got) == len(items), (
                f"`{pref}…` fired {len(got)} time(s) over {len(items)} item(s) "
                f"of corpus {name!r}")
        assert any(fired.values()), (
            f"no templated gate fired over corpus {name!r}")
