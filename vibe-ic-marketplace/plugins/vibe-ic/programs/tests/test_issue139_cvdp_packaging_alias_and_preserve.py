"""#139 — the two scorer-side (packaging-layer) sub-items + the §4.05 guard.

(a) record-id alias stop-word guard + the packaging code reads NO harness oracle.
(b) file-clobber preservation: re-include a provided-context module the delivered
    set still instantiates (provided context = legal INPUT); no-leak on the
    intended-replacement / author-redefine / nothing-outside-context cases.

These live at the IO-SHELL packaging layer (cvdp_gate.py). The AUTHORING side
stays honest — the module is named from the spec; this only adapts the emit
FORMAT to the official harness using the record id (dataset addressing metadata =
legal input) and the provided context.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "benchmark"))
sys.path.insert(0, str(PLUGIN / "programs"))
import cvdp_gate as G  # noqa: E402


# ── (a) record-id alias stop-word guard ───────────────────────────────────
def test_stopword_bare_stem_dropped_prefixed_kept():
    # a generic stop-word stem never becomes a BARE alias (would collide with a
    # real submodule); the specific `cvdp_copilot_<stem>` form is always kept.
    assert G.candidate_tops_from_id("cvdp_copilot_top_0001") == ["cvdp_copilot_top"]
    assert G.candidate_tops_from_id("cvdp_copilot_core_0001") == ["cvdp_copilot_core"]
    assert G.candidate_tops_from_id("cvdp_copilot_dut_0001") == ["cvdp_copilot_dut"]


def test_specific_stem_unaffected():
    # a real design name is untouched (no over-guarding)
    assert G.candidate_tops_from_id("cvdp_copilot_bus_arbiter_0001") == [
        "cvdp_copilot_bus_arbiter", "bus_arbiter", "arbiter_bus"]


def test_invalid_identifier_stem_still_dropped():
    # digit-leading stem is not a legal module name → no bare/ reversed alias
    assert G.candidate_tops_from_id("cvdp_copilot_16qam_mapper_0001") == [
        "cvdp_copilot_16qam_mapper", "mapper_16qam"]


def test_non_cvdp_id_yields_nothing():
    assert G.candidate_tops_from_id("some_other_module") == []
    assert G.candidate_tops_from_id("") == []


# ── §4.05: the alias derivation takes ONLY the record id (no harness path) ──
def test_alias_derivation_takes_only_the_record_id():
    # the record-id alias derivation accepts ONLY the id string — it structurally
    # CANNOT read a harness `.env`/TOPLEVEL/golden path (no dataset/file/path
    # parameter). Purity: same id → same output, with no file argument.
    assert list(inspect.signature(G.candidate_tops_from_id).parameters) == ["rid"]
    assert list(inspect.signature(G.required_top_from_id).parameters) == ["rid"]
    rid = "cvdp_copilot_bus_arbiter_0001"
    assert G.candidate_tops_from_id(rid) == G.candidate_tops_from_id(rid)


# ── (b) file-clobber preservation ─────────────────────────────────────────
_EMITTED = "module top(input a, output b);\n child u(.a(a), .b(b));\nendmodule\n"
_CTX = ["module child(input a, output b); assign b = a; endmodule\n",
        "module unused(input x); endmodule\n"]


def test_reincludes_instantiated_dropped_context_module():
    repaired, names = G.preserve_dropped_context_modules(_EMITTED, _CTX)
    assert names == ["child"]
    assert "module child" in repaired
    # never injects a provided module that nothing instantiates
    assert "module unused" not in repaired


def test_no_repair_when_module_not_instantiated():
    emitted = "module top(input a, output b); assign b = a; endmodule\n"
    _, names = G.preserve_dropped_context_modules(emitted, _CTX)
    assert names == []                       # intended replacement — never repaired


def test_no_repair_when_author_redefines():
    emitted = _EMITTED + "module child(input a, output b); assign b = ~a; endmodule\n"
    _, names = G.preserve_dropped_context_modules(emitted, _CTX)
    assert names == []                       # author kept/redefined it


def test_never_injects_outside_context():
    # a module the emit instantiates but that is NOT in ctx is never fabricated:
    # no `module missing_mod` DEFINITION is ever added (the instantiation stays).
    emitted = "module top; missing_mod u(); endmodule\n"
    repaired, names = G.preserve_dropped_context_modules(emitted, _CTX)
    assert names == [] and "module missing_mod" not in repaired


def test_json_envelope_left_untouched():
    js = '{"code": [{"rtl/top.sv": "module top; child u(); endmodule"}]}'
    repaired, names = G.preserve_dropped_context_modules(js, _CTX)
    assert repaired == js and names == []


def test_empty_inputs_are_noops():
    assert G.preserve_dropped_context_modules("", _CTX) == ("", [])
    assert G.preserve_dropped_context_modules(_EMITTED, None) == (_EMITTED, [])


def test_preserve_takes_only_completion_and_context():
    # the preservation repair accepts ONLY the delivered completion + the
    # provided input.context — both LEGAL inputs; it has no harness/dataset/path
    # parameter, so it structurally cannot read the oracle.
    assert list(inspect.signature(G.preserve_dropped_context_modules).parameters) \
        == ["emitted", "ctx_texts"]
