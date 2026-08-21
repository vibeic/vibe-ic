"""`phase1_layer_demand_probe` landed in v1.9.1 with no tests at all.

The D1 program-test-coverage audit named it, and D1 only runs in the FULL tier
of the landing gate — so the program shipped, three releases went out, and the
first thing to notice was an unrelated batch being blocked by it.

Every case here drives the REAL extraction path (`l21_doc_supply_rail_synth`
reading a document table) rather than substituting the probe callable. The
program's whole claim is "a deterministic probe can show, from the design's own
documents, that a layer was demanded" — a test that stubs the probe asserts the
plumbing and leaves the claim unmeasured.

The two exit paths that do NOT signal are asserted too, because they are the
ones that can hide: `LAYER_ABSENT` and `PROBE_UNAVAILABLE` both leave
`silent_empty` empty and exit 0, which is the same code a satisfied layer
returns. They are recorded here as the program's CURRENT behaviour, with the
distinction stated, so a later change to it is a deliberate one.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
PROG = _PROGRAMS / "phase1_layer_demand_probe.py"

import phase1_layer_demand_probe as P  # noqa: E402

#: A document stating its rails in a table — the shape that reaches L21 through
#: the shipped synthesiser. Copied in form (not by import) from
#: `test_l21_doc_supply_rail_synth`, so a change there cannot silently retune
#: this file's fixtures.
_L9_WITH_RAILS = """\
# L9 Constraints

Some prose about the block.

## Supplies / levels

| Rail | Voltage | Note |
|---|---|---|
| VDDA | 1.8 V | analog supply |
| VDDD | 1.2 V | digital core |
| VSS  | 0 V   | common ground |
"""

#: The same document with no supply table at all.
_L9_NO_RAILS = """\
# L9 Constraints

## Timing

| Parameter | Value |
|---|---|
| Temp | 27 C |
"""


def _project(tmp_path, doc_text=_L9_WITH_RAILS, l21=None, write_l21=True):
    d = tmp_path / "input" / "docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "L9_CONSTRAINTS.md").write_text(doc_text, encoding="utf-8")
    if write_l21:
        g = tmp_path / "phase1" / "generated_docs"
        g.mkdir(parents=True, exist_ok=True)
        (g / "L21_POWER_INTENT.json").write_text(
            json.dumps(l21 if l21 is not None
                       else {"doc_id": "L21", "fields": {"power_domains": []}}),
            encoding="utf-8")
    return tmp_path


def _l21(status):
    return status["layers"][0]


def _run(project, *extra):
    return subprocess.run([sys.executable, str(PROG), str(project), *extra],
                          capture_output=True, text=True, timeout=45)


# ── the defect the program exists for ────────────────────────────────────────
def test_a_demanded_layer_left_empty_is_reported(tmp_path):
    """The measured case: the input states three rails, L21 holds none.

    This is the whole point — the coverage percentage reported 100 % over this
    exact miss, because the literals appeared in three PROSE layers.
    """
    res = P.evaluate(_project(tmp_path))
    layer = _l21(res)
    assert layer["status"] == "SILENT_EMPTY", res
    assert layer["input_states"] == 3, layer
    assert layer["layer_holds"] == 0, layer
    assert res["silent_empty"] == ["L21_POWER_INTENT"], res


def test_the_stated_items_carry_their_evidence(tmp_path):
    """A finding that cannot be checked against the document is not actionable.

    Without this, `input_states=3` could be any three things.
    """
    layer = _l21(P.evaluate(_project(tmp_path)))
    names = {i["name"] for i in layer["stated_items"]}
    assert {"VDDA", "VDDD"} <= names, layer["stated_items"]
    for item in layer["stated_items"]:
        assert item["evidence"]["file"], item
        assert item["evidence"]["line"], item


# ── the accept cases: the program must be able to stay quiet ─────────────────
def test_a_satisfied_layer_is_not_reported(tmp_path):
    """The layer holds what the input demanded — nothing to say.

    Load-bearing: a probe that reported every project would be switched off,
    and `silent_empty` would stop meaning anything.
    """
    proj = _project(tmp_path, l21={
        "doc_id": "L21",
        "fields": {"power_domains": [{"name": "VDDA"}, {"name": "VDDD"}]}})
    res = P.evaluate(proj)
    assert _l21(res)["status"] == "SATISFIED", res
    assert res["silent_empty"] == [], res


def test_a_document_stating_no_rails_is_not_demanded(tmp_path):
    """No demand, so an empty L21 is correct and must not be flagged."""
    res = P.evaluate(_project(tmp_path, doc_text=_L9_NO_RAILS))
    assert _l21(res)["status"] == "NOT_DEMANDED", res
    assert res["silent_empty"] == [], res


def test_power_rails_counts_as_well_as_power_domains(tmp_path):
    """`_l21_layer_holds` reads both keys; a fixture using only one would let
    the other be dropped with the suite green."""
    proj = _project(tmp_path, l21={
        "doc_id": "L21", "fields": {"power_rails": [{"name": "VDDA"}]}})
    assert _l21(P.evaluate(proj))["status"] == "SATISFIED"


# ── the two paths that do not signal ─────────────────────────────────────────
def test_an_absent_layer_is_distinguished_from_a_satisfied_one(tmp_path):
    """L21 was never written. The status says so; `silent_empty` stays empty.

    Recorded rather than endorsed: the exit code for this is 0, the same one a
    satisfied layer returns, so a caller reading only the code cannot tell "the
    layer holds what was demanded" from "there is no layer". The STATUS is the
    only place the two differ, which is why it is pinned here.
    """
    res = P.evaluate(_project(tmp_path, write_l21=False))
    assert _l21(res)["status"] == "LAYER_ABSENT", res
    assert res["silent_empty"] == [], res


def test_an_unparsable_layer_reads_as_absent(tmp_path):
    """`_read_layer` swallows a JSON error and returns None."""
    proj = _project(tmp_path)
    (proj / "phase1" / "generated_docs" / "L21_POWER_INTENT.json").write_text(
        "{not json", encoding="utf-8")
    assert _l21(P.evaluate(proj))["status"] == "LAYER_ABSENT"


def test_a_probe_that_cannot_run_says_so(tmp_path, monkeypatch):
    """`PROBE_UNAVAILABLE` — the synthesiser raised.

    Monkeypatched HERE and only here: this branch is unreachable through the
    document path, and leaving it unexercised would mean the one status that
    admits the probe did not work is the one nothing checks.
    """
    import l21_doc_supply_rail_synth as S
    monkeypatch.setattr(S, "derive", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("synth is broken")))
    res = P.evaluate(_project(tmp_path))
    assert _l21(res)["status"] == "PROBE_UNAVAILABLE", res
    assert res["silent_empty"] == [], res


# ── the CLI, which is what the runner actually invokes ───────────────────────
def test_exit_code_is_one_only_when_a_layer_is_silently_empty(tmp_path):
    demanded = _project(tmp_path / "a")
    satisfied = _project(tmp_path / "b", l21={
        "doc_id": "L21", "fields": {"power_domains": [{"name": "VDDA"}]}})
    assert _run(demanded).returncode == 1
    assert _run(satisfied).returncode == 0


def test_the_stdout_names_the_layer_and_its_consumer(tmp_path):
    """A report that says a count and not what breaks is not actionable."""
    out = _run(_project(tmp_path)).stdout
    assert "L21_POWER_INTENT" in out
    assert "SILENT_EMPTY" in out
    assert "consumer:" in out
    assert "VDDA" in out, out


def test_the_json_written_matches_the_returned_result(tmp_path):
    """`--json` is what downstream reads; a divergence between it and the
    verdict would let the two disagree unnoticed."""
    proj = _project(tmp_path)
    out = tmp_path / "demand.json"
    proc = _run(proj, "--json", str(out))
    assert proc.returncode == 1
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written == P.evaluate(proj), written


# ── the summary line the runner prints beside the percentage ─────────────────
def test_the_summary_line_states_the_miss_loudly(tmp_path):
    line = P.summary_line(P.evaluate(_project(tmp_path)))
    assert "L21_POWER_INTENT" in line
    assert "1" in line, line


def test_the_summary_line_is_quiet_when_there_is_nothing_to_say(tmp_path):
    proj = _project(tmp_path, l21={
        "doc_id": "L21", "fields": {"power_domains": [{"name": "VDDA"}]}})
    line = P.summary_line(P.evaluate(proj))
    assert "0 silently empty" in line, line
    assert "**" not in line, line


def test_the_summary_line_interpolates_rather_than_printing_its_template(tmp_path):
    """The miss branch builds its text with `.format` inside a string that also
    carries `{n}` and `{names}`. If the two halves are ever concatenated the
    other way round, the placeholders reach the runner SUMMARY verbatim and the
    line reads as a template — visibly wrong, and nothing else would catch it.
    """
    line = P.summary_line(P.evaluate(_project(tmp_path)))
    assert "{n}" not in line and "{names}" not in line, line
