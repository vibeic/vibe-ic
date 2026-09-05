#!/usr/bin/env python3
"""GAP 1 — a constraint stated in the design's PROSE must reach L19.

Measured on a real run (spm, plugin v1.14.75, current `origin/main`): 10 of
10 constraint tokens present in the input documents, 0 of 10 present in the
emitted `L19_CONSTRAINTS_PDK.json` — which additionally carried
`constraints_present: false` and a note saying the spec does not state PDK
or timing constraints. A missing fact is a hole; a stated falsehood is what
stops the reader looking.

NEGATIVE CONTROLS — each of these is RED against the pre-fix tree, and each
is red for a DIFFERENT reason, which is the point of having three:

  1. `import l19_constraint_token_emit` at MODULE level. Pre-fix the module
     does not exist and this file fails at COLLECTION. It is deliberately
     not `pytest.importorskip`: that reports the true pre-fix state as
     "1 skipped" and the suite passes green, which is a test that cannot
     fail against the code it is meant to indict.
  2. the WIRING tests read the runner's AST. A module that exists and is
     never called is an orphan, and every one of the behaviour tests below
     would still pass while the flow emitted the same empty layer.
  3. `test_column_oriented_table_keeps_the_designs_own_scope` and
     `test_a_key_with_no_value_is_a_mention_not_a_setting` fail if the
     reader is reduced to the row-oriented form, or if the value binding
     is dropped — the two ways this extractor silently becomes partial.

Every fixture is synthesized neutral text. The configuration KEYS used here
are invented (`CORE_UTIL_TARGET`, `PDN_SKIP_TRIM`, …) precisely to prove the
extractor keys on the SHAPE of a configuration key and not on a whitelist of
any tool's variable names. chip-AGNOSTIC.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_RUNNER_SRC = _PROGRAMS / "phase1_doc_one_shot_runner.py"

import constraint_prose_tokens as CPT           # noqa: E402
import _atomic_artefact as A                     # noqa: E402
import l19_constraint_token_emit as EMIT        # noqa: E402
import phase1_doc_one_shot_runner as R          # noqa: E402

HELPER = "_post_emit_l19_constraint_tokens"

# A specification that states its constraints in prose and ships no deck.
_DOC = """---
layer: L9
status: draft
---

# L9 — Constraints

## Clocking

```sdc
set_units -time ns
create_clock [get_ports clk] -name core_clock -period 10
```

- `set_input_delay` / `set_output_delay`: 20% of the clock period.

## Fanout

| library | `FANOUT_LIMIT_MAX` |
|---|---|
| `family_a_*` | 5 |
| `family_b_*` | 4 |

## Floorplan

| technology family | `CORE_UTIL_TARGET` | `PLACE_DENSITY_TARGET` |
|---|---|---|
| FAMILY_A | 45% | tool default |
| FAMILY_B | 40% | 0.5 |

## Power network

| setting | value |
|---|---|
| `PDN_SKIP_TRIM` | true |
| `PDN_V_OFFSET` | 7 |

## Mentioned but never set

The `UNBOUND_SETTING_KEY` is discussed in the integration guide.
"""

_DOC_NO_CONSTRAINTS = """# L9 — Constraints

Constraints are deferred to the integration owner; this block states none.
"""

_DOC_DENIED_CONSTRAINTS = """# L9 — Constraints

## Floorplan

No `CORE_UTIL_TARGET = 45%` is specified.

## Timing

Do not use `create_clock` for this interface.
"""

_DOC_IMPLEMENTATION_CONTEXT = """# Integration brief

4. **Implementation route (intended path)**: **REUSED-IP / catalog-glue**.
   `input/vendor_rtl/{core,prim_portable,bus}/` is the staged dependency
   closure; select **prim_portable** and author only the wrapper and tie-offs.

5. **Sign-off target**
   The translate-hdl + synth-engine flow reference is staged at
   `input/reference_flow/prebuild/` for implementation context.

6. **Functional verification oracle**
   - SPEC-123 / PROFILE-42 standard vectors, driven through the bus interface.
   - The named oracle is a verification contract; Phase 1 must not open it.
"""

_DOC_UNRELATED_CONTEXT_WORDS = """# Design notes

The implementation discusses a route selector and a catalog index.
Verification uses an oracle selector signal. A flow reference counter is
also present in the datapath. None of these sentences declares an
implementation route, reference-flow artifact, or verification oracle.
"""

_L19_SKELETON = {
    "doc_id": "L19",
    "doc_name": "L19_CONSTRAINTS_PDK",
    "applicability": "APPLICABLE",
    "extraction_status": "NOT_YET_EXTRACTED",
    "fields": {
        "pdk_target": None,
        "die_area_budget_um": None,
        "sdc_constraints_path": None,
        "floorplan_hints": [],
    },
    "evidence": [],
    "source_documents": [],
}


def _mk(project: Path, doc_text: str, *, with_l19: bool = True) -> None:
    if with_l19:
        gd = project / "phase1" / "generated_docs"
        gd.mkdir(parents=True, exist_ok=True)
        (gd / "L19_CONSTRAINTS_PDK.json").write_text(
            json.dumps(_L19_SKELETON, ensure_ascii=False), encoding="utf-8")
    d = project / "input" / "docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "L9_constraints.md").write_text(doc_text, encoding="utf-8")


def _l19(project: Path) -> dict:
    return json.loads(
        (project / "phase1" / "generated_docs"
         / "L19_CONSTRAINTS_PDK.json").read_text(encoding="utf-8"))


def _tokens(doc: dict) -> set:
    return {r["token"] for r in doc["fields"].get("constraint_declarations", [])}


# ───────────────────────────────────────────── 1. the gap itself, closed ──
def test_prose_stated_constraints_reach_l19(tmp_path):
    _mk(tmp_path, _DOC)
    before = _l19(tmp_path)
    assert not before["fields"].get("constraint_declarations"), before
    assert before["fields"].get("constraints_present") in (None, False)

    n = getattr(R, HELPER)(tmp_path)
    assert n > 0, "the runner wiring lifted nothing"

    doc = _l19(tmp_path)
    got = _tokens(doc)
    for want in ("CORE_UTIL_TARGET", "PLACE_DENSITY_TARGET",
                 "PDN_SKIP_TRIM", "PDN_V_OFFSET", "FANOUT_LIMIT_MAX",
                 "create_clock", "set_input_delay", "set_output_delay"):
        assert want in got, f"{want} is stated in the input and absent from L19"
    assert doc["fields"]["constraints_present"] is True
    assert doc["extraction_status"] == "PARTIALLY_EXTRACTED"
    assert doc["source_documents"], "the layer records no source document"


def test_every_declaration_carries_auditable_provenance(tmp_path):
    _mk(tmp_path, _DOC)
    getattr(R, HELPER)(tmp_path)
    for rec in _l19(tmp_path)["fields"]["constraint_declarations"]:
        assert rec["source"] and not rec["source"].startswith("/"), (
            f"provenance is absolute and will not survive leaving this "
            f"machine: {rec['source']}")
        assert isinstance(rec["line"], int) and rec["line"] > 0
        assert rec["evidence"], "a declaration with no evidence row"


# ─────────────────────────── 2. the two orientations, and the value bind ──
def test_column_oriented_table_keeps_the_designs_own_scope(tmp_path):
    """A per-family setting has TWO values, and each belongs to its row.

    RED if the reader is reduced to the row-oriented form (the column
    table contributes nothing), and RED if ornament stripping eats the
    trailing `_*` of a glob scope — that turns a setting scoped to a whole
    family into one scoped to a family that does not exist.
    """
    _mk(tmp_path, _DOC)
    getattr(R, HELPER)(tmp_path)
    util = [r for r in _l19(tmp_path)["fields"]["constraint_declarations"]
            if r["token"] == "CORE_UTIL_TARGET"]
    assert {(r["scope"], r["value"]) for r in util} == {
        ("FAMILY_A", "45%"), ("FAMILY_B", "40%")}, util

    fan = [r for r in _l19(tmp_path)["fields"]["constraint_declarations"]
           if r["token"] == "FANOUT_LIMIT_MAX"]
    assert {r["scope"] for r in fan} == {"family_a_*", "family_b_*"}, (
        f"a glob scope lost its wildcard to ornament stripping: {fan}")


def test_a_key_with_no_value_is_a_mention_not_a_setting(tmp_path):
    _mk(tmp_path, _DOC)
    getattr(R, HELPER)(tmp_path)
    assert "UNBOUND_SETTING_KEY" not in _tokens(_l19(tmp_path)), (
        "a key the document only DISCUSSES was published as a setting")


def test_inline_value_stops_at_the_punctuation_that_wraps_it():
    """`met(KEY = 5)` binds 5, not `5)`."""
    got = CPT.inline_bindings("timing met(FANOUT_LIMIT_MAX = 5) at TT")
    assert [(g["token"], g["value"]) for g in got] == [
        ("FANOUT_LIMIT_MAX", "5")], got


def test_emphasis_is_stripped_only_when_symmetric():
    assert CPT.strip_ornament("**20**") == "20"
    assert CPT.strip_ornament("`KEY_NAME`") == "KEY_NAME"
    assert CPT.strip_ornament("`family_a_*`") == "family_a_*"


# ─────────────────── 2b. THE DOMAIN ANCHOR — the sweep's own correction ──
# The two fixtures below are the corpus sweep in miniature. Swept dry-run
# across 105 published run dirs, the SHAPE rule alone put a CPU's RTL
# parameters (`IC_SIZE_BYTES`, `BUS_W`), a crypto block's registers
# (`KEY_SHARE0_0`) and a power IC's command codes (`VOUT_COMMAND`) into the
# CONSTRAINTS layer — 224 records on one design, every one shaped like a
# setting and none of them a flow constraint. Anchoring on the SUBJECT the
# design filed the binding under took the corpus from 24 moving roots to 11
# with zero false positives left.

_OTHER_DOMAIN_DOC = """# Instruction cache

## Cache geometry

| parameter | value |
|---|---|
| `IC_LINE_BYTES` | 32 |
| `IC_NUM_WAYS` | 2 |

## Register map

| register | offset |
|---|---|
| `KEY_SHARE0_0` | 0x04 |
"""


def test_a_named_constant_of_another_layers_domain_is_not_a_constraint(
        tmp_path):
    _mk(tmp_path, _OTHER_DOMAIN_DOC)
    assert getattr(R, HELPER)(tmp_path) == 0, (
        f"L19 absorbed another layer's constants: {_tokens(_l19(tmp_path))}")


def test_every_flow_setting_records_the_subject_that_anchored_it(tmp_path):
    """The anchor is recorded, so the call is auditable from the layer
    rather than only reproducible by re-running the extractor."""
    _mk(tmp_path, _DOC)
    getattr(R, HELPER)(tmp_path)
    for rec in _l19(tmp_path)["fields"]["constraint_declarations"]:
        if rec["kind"] != "flow_setting":
            continue          # an SDC directive is self-identifying
        assert rec.get("domain_anchor"), (
            f"{rec['token']} was published with no subject filing it under "
            f"the constraints domain")


def test_a_bare_generic_noun_does_not_anchor():
    """`core`, `area`, `pin`, `clock` alone are section titles in documents
    about something else — a CPU has a "Core" section. Admitting the bare
    nouns would undo the sweep."""
    for generic in ("Core", "Pin description", "Clock", "Area", "IO"):
        assert EMIT._domain_anchored(generic, "") is None, generic
    for real in ("9.2 Floorplan", "Core utilization", "Power network (PDN)",
                 "Synthesis constraints", "9.4 簽核目標"):
        assert EMIT._domain_anchored(real, "") is not None, real


def test_a_code_block_is_code_not_a_setting(tmp_path):
    """A shell environment block has the shape of a settings list.

    MEASURED: `export RISCV_TOOLCHAIN=/path/to/riscv` and its neighbours
    contributed 181 of one design's 224 records.
    """
    doc = ("# L9 — Constraints\n\n## Floorplan\n\n"
           "Set up the environment first:\n\n"
           "    export TOOLCHAIN_ROOT=/path/to/tools\n"
           "    export LIB_SEARCH_PATH=$LIB_SEARCH_PATH:/opt/libs\n\n"
           "```sh\nexport FENCED_SETTING_KEY=1\n```\n\n"
           "| setting | value |\n|---|---|\n| `CORE_UTIL_TARGET` | 45% |\n")
    _mk(tmp_path, doc)
    getattr(R, HELPER)(tmp_path)
    got = _tokens(_l19(tmp_path))
    assert "CORE_UTIL_TARGET" in got, got
    for shell in ("TOOLCHAIN_ROOT", "LIB_SEARCH_PATH", "FENCED_SETTING_KEY"):
        assert shell not in got, f"{shell} came out of a code block: {got}"


# ───────────── 2c. explicit implementation context belongs in L19 ──
def test_declared_implementation_context_reaches_l19_without_opening_it(
        tmp_path, monkeypatch):
    """Prompt-declared context is metadata; named artifacts stay unread.

    RED on the pre-fix program: all three fields are absent and the helper
    reports zero.  The read guard independently proves that recovery did not
    come from opening the staged reference or oracle content.
    """
    _mk(tmp_path, _DOC_IMPLEMENTATION_CONTEXT)
    (tmp_path / "input" / "reference_flow" / "prebuild").mkdir(
        parents=True)
    (tmp_path / "input" / "reference_flow" / "prebuild" /
     "recipe.tcl").write_text("SHOULD_NOT_BE_READ", encoding="utf-8")
    (tmp_path / "input" / "golden").mkdir(parents=True)
    (tmp_path / "input" / "golden" / "answer.json").write_text(
        "SHOULD_NOT_BE_READ", encoding="utf-8")

    real_read_text = Path.read_text

    def guarded_read_text(path, *args, **kwargs):
        lowered = {part.lower() for part in Path(path).parts}
        assert not lowered.intersection({"reference_flow", "golden",
                                         "oracle", "harness"}), path
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    assert getattr(R, HELPER)(tmp_path) == 3

    fields = _l19(tmp_path)["fields"]
    reference = json.dumps(fields.get("reference_flow"), ensure_ascii=False)
    route = json.dumps(fields.get("implementation_route"), ensure_ascii=False)
    oracle = json.dumps(fields.get("verification_oracle"), ensure_ascii=False)
    for token in ("translate-hdl", "synth-engine", "reference_flow"):
        assert token in reference, (token, reference)
    for token in ("REUSED-IP", "catalog-glue", "vendor_rtl",
                  "prim_portable"):
        assert token in route, (token, route)
    for token in ("SPEC-123", "PROFILE-42"):
        assert token in oracle, (token, oracle)


def test_context_vocabulary_without_a_declaration_emits_nothing(tmp_path):
    """A word hit is not a contract; explicit declaration framing is required."""
    _mk(tmp_path, _DOC_UNRELATED_CONTEXT_WORDS)
    assert getattr(R, HELPER)(tmp_path) == 0
    fields = _l19(tmp_path)["fields"]
    for key in ("reference_flow", "implementation_route",
                "verification_oracle"):
        assert key not in fields, (key, fields.get(key))


# ────────────────────────────────────── 3. refuses rather than fabricates ──
def test_a_design_that_states_no_constraint_gets_nothing(tmp_path):
    _mk(tmp_path, _DOC_NO_CONSTRAINTS)
    assert getattr(R, HELPER)(tmp_path) == 0
    doc = _l19(tmp_path)
    assert not doc["fields"].get("constraint_declarations")
    assert doc["fields"].get("constraints_present") in (None, False), (
        "the presence flag was set True with no evidence behind it")


def test_denied_setting_and_directive_do_not_become_declarations(tmp_path):
    """Both scanner record classes carry prose whose polarity is load-bearing."""
    _mk(tmp_path, _DOC_DENIED_CONSTRAINTS)
    assert getattr(R, HELPER)(tmp_path) == 0
    doc = _l19(tmp_path)
    assert not doc["fields"].get("constraint_declarations"), doc
    assert doc["fields"].get("constraints_present") in (None, False)


def test_missing_l19_degrades_with_a_named_skip(tmp_path, capsys):
    _mk(tmp_path, _DOC, with_l19=False)
    assert getattr(R, HELPER)(tmp_path) == 0
    assert "L19 prose constraints: SKIPPED" in capsys.readouterr().out


def test_unreadable_l19_degrades_loudly_not_as_zero(tmp_path):
    _mk(tmp_path, _DOC)
    (tmp_path / "phase1" / "generated_docs" /
     "L19_CONSTRAINTS_PDK.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unreadable"):
        getattr(R, HELPER)(tmp_path)
    assert EMIT.main([str(tmp_path)]) == 1


def test_cli_report_appears_only_after_an_atomic_write(tmp_path, monkeypatch):
    """The report writer still runs, and an interrupted first write is absent."""
    _mk(tmp_path, _DOC_NO_CONSTRAINTS)
    complete = tmp_path / "reports" / "complete.json"
    assert EMIT.main([str(tmp_path), "--json", str(complete)]) == 0
    assert json.loads(complete.read_text(encoding="utf-8"))["tool"] == EMIT.TOOL

    def die(*_args, **_kwargs):
        raise OSError("simulated interruption before atomic rename")

    doomed = tmp_path / "reports" / "doomed.json"
    monkeypatch.setattr(A.os, "fsync", die)
    try:
        rc = EMIT.main([str(tmp_path), "--json", str(doomed)])
    except OSError as exc:
        outcome = ("raised", str(exc))
    else:
        outcome = ("returned", rc)
    assert outcome[0] == "raised", outcome
    assert not doomed.exists()
    assert not A.temp_name_for(doomed).exists()


def test_rerun_is_idempotent(tmp_path):
    _mk(tmp_path, _DOC)
    first = getattr(R, HELPER)(tmp_path)
    assert first > 0
    assert getattr(R, HELPER)(tmp_path) == 0, "re-run duplicated declarations"
    assert len(_l19(tmp_path)["fields"]["constraint_declarations"]) == first


def test_the_same_document_shipped_twice_is_one_declaration(tmp_path):
    """Path A ships each input as both `input/docs/*.md` and
    `phase1/input_doc/*.txt`. An evidence count that doubles with the
    corpus layout is a copy count wearing an evidence count's name."""
    _mk(tmp_path, _DOC)
    dup = tmp_path / "phase1" / "input_doc"
    dup.mkdir(parents=True, exist_ok=True)
    (dup / "L9_constraints.txt").write_text(_DOC, encoding="utf-8")
    getattr(R, HELPER)(tmp_path)
    recs = _l19(tmp_path)["fields"]["constraint_declarations"]
    ids = [(r["kind"], r["token"], r["scope"], r["value"]) for r in recs]
    assert len(ids) == len(set(ids)), f"the corpus layout was counted: {ids}"


# ────────────── 4. the false NOTE the overlay used to write is not written ──
def test_the_neutral_overlay_no_longer_contradicts_a_populated_layer(tmp_path):
    """The integration guarantee, exercised through the REAL overlay.

    `spi_protocol_synth._apply_universal` fills an unset L19 with
    `constraints_present: false` plus "Spec does not state PDK / timing
    constraints". Its `setdefault` + `contradicted` machinery is already
    built to yield to a real extraction — it simply had nothing to yield
    to. RED if this emitter stops setting the presence flag, or is
    re-ordered to run AFTER the overlay.
    """
    import spi_protocol_synth as SPI
    _mk(tmp_path, _DOC)
    getattr(R, HELPER)(tmp_path)
    SPI._apply_universal(tmp_path / "phase1" / "generated_docs",
                         is_spi=False)
    fields = _l19(tmp_path)["fields"]
    assert fields["constraints_present"] is True, (
        "the overlay overwrote a value read from the design's own prose")
    assert "notes" not in fields, (
        f"the layer states its constraints AND a note denying it has any: "
        f"{fields.get('notes')!r}")


# ─────────────────────────────────────────────────── 5. it is really WIRED ──
def _main_body() -> ast.FunctionDef:
    tree = ast.parse(_RUNNER_SRC.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("phase1_doc_one_shot_runner.main() not found")


def _call_lines(fn: ast.AST, name: str):
    return [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == name]


def test_runner_exposes_the_wiring_helper():
    assert callable(getattr(R, HELPER, None)), (
        f"phase1_doc_one_shot_runner.{HELPER} is missing — the emitter "
        f"would be an orphan program nothing runs")


def test_main_calls_the_helper_after_the_skeleton_that_creates_l19():
    body = _main_body()
    ours = _call_lines(body, HELPER)
    skeleton = _call_lines(body, "_emit_l19_to_l23_skeletons")
    assert ours, f"{HELPER} is defined but never called from main()"
    assert skeleton, "_emit_l19_to_l23_skeletons is no longer called"
    assert min(ours) > max(skeleton), (
        f"{HELPER} runs at line {min(ours)}, before L19 exists on disk "
        f"(line {max(skeleton)}) — it would SKIP on every run")


def test_the_helper_runs_before_the_protocol_overlay_that_would_deny_it():
    """Ordering is the fix, not a detail of it.

    Run AFTER `apply_spi_synth`, the emitter would be writing beside a
    note already asserting the design states no constraints, and would
    have to rewrite another module's prose to repair it.
    """
    body = _main_body()
    ours = _call_lines(body, HELPER)
    overlay = [n.lineno for n in ast.walk(body)
               if isinstance(n, ast.Call)
               and getattr(n.func, "attr", getattr(n.func, "id", None))
               in ("apply_spi_synth",)]
    assert ours, f"{HELPER} is never called"
    if overlay:
        assert min(ours) < min(overlay), (
            f"{HELPER} at line {min(ours)} runs AFTER the protocol overlay "
            f"at line {min(overlay)} — the overlay's neutral placeholder "
            f"would win and its contradicting note would be written")
