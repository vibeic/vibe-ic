"""v1.1.38 §4.2 absorption — deterministic Karnaugh-map → RTL synth.

A don't-care-FREE K-map is a complete truth table; the answer is the exact SOP.
This was per-round single-shot variance (a blind author flips the axis mapping);
the synth absorbs it as a PROGRAM.

§4.05 no-leak: FIRES only on an exact (0/1-only) grid; SKIPs any don't-care K-map
(under-determined -> the golden picks one of many valid functions = a genuine
floor, not absorbable), mux-decomposition output, or unparseable grid.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import kmap_grid_synth as K  # noqa: E402

_KMAP_2IN = """
Implement a module named TopModule.
 - input  a
 - input  b
 - output q

The module should implement the function shown in the Karnaugh map below.

       a
  b   0   1
  0 | 0 | 1 |
  1 | 1 | 0 |
"""


def test_kmap_fires_and_is_correct():
    rtl = K.synth(_KMAP_2IN, "TopModule")
    assert rtl is not None
    assert "assign q" in rtl
    # q = a^b : 1-cells at (b=0,a=1) and (b=1,a=0)
    assert "(~b & a)" in rtl and "(b & ~a)" in rtl


_DECLARED_LOGIC_REQUESTS = [
    'Use only NAND gates.',
    'Use a minimum number of two-input NAND gates.',
    'Only NAND gates may be used.',
    'Implement using only NOR gates.',
    'The implementation must use only NAND gates and NOR gates.',
    'Minimize the Boolean expression.',
    'Use a minimized sum-of-products expression.',
    'Use only\nNAND gates; no other gates are allowed.',
    'The module must be implemented using only NAND gates.',
    'For module TopModule, use only NAND gates.',
    'Use only NAND gates. The NOR-only restriction is withdrawn.',
    'Use only NAND gates. This restriction is not withdrawn.',
]


@pytest.mark.parametrize('obligation', _DECLARED_LOGIC_REQUESTS)
@pytest.mark.parametrize('entry', ['producer', 'registry', 'record', 'chain', 'author'])
def test_declared_logic_obligation_hands_off_before_sop(tmp_path, obligation, entry):
    import deterministic_emit_chain as chain
    import design_one_shot_runner as runner
    import spec_artifact_registry as registry
    import time

    prompt = _KMAP_2IN + '\n' + obligation
    if entry == 'producer':
        rtl = K.synth(prompt, 'TopModule')
    elif entry == 'registry':
        _, rtl = registry.generate(prompt, 'TopModule')
    elif entry == 'record':
        rtl = registry.generate_from_record(
            {'prompt': prompt},
            text_fallthrough=lambda: K.synth(_KMAP_2IN, 'TopModule'))
    elif entry == 'chain':
        kind, rtl, rejected = chain.try_emit_ex(prompt, top='TopModule', check=False)
    else:
        result = runner._try_spec_artifact_registry_rtl(
            tmp_path, time.time(), phase1_plain_text=prompt)
        observed = result.status if result else 'NO_HANDOFF'
        assert observed == 'PASS_WITH_WAIVERS', result
        assert result.extras['fallback_skill'] == 'spec-to-rtl'
        assert 'DECLARED_LOGIC_OBLIGATION_UNSUPPORTED' in result.detail
        assert Path(result.extras['fallback_skill_source']).is_file()
        assert runner._rtl_gen_handoff([result]) == 'spec-to-rtl'
        assert result.output_files == []
        assert list(tmp_path.iterdir()) == []
        return
    observed = 'DECLINED' if rtl is None else 'SOP' if '&' in rtl else 'OTHER_RTL'
    assert observed == 'DECLINED', {'observed': observed, 'rtl': rtl}
    if entry == 'chain':
        assert kind is None
        assert rejected and 'DECLARED_LOGIC_OBLIGATION_UNSUPPORTED' in str(rejected)


@pytest.mark.parametrize('obligation', [
    '',
    'NAND gates are an example of universal logic.',
    'You may use NAND gates or sum-of-products.',
    'Do not use only NAND gates.',
    'Do not\nuse only NAND gates.',
    'NAND-only logic is not required.',
    'The NAND-only restriction is withdrawn.',
    'Use only NAND gates. This restriction is withdrawn.',
    'A minimum number of NAND gates is not required.',
    'For module helper, use only NAND gates.',
    'For module helper,\nuse only NAND gates.',
    'Use only NAND gates for module helper.',
    'Module name: helper\nUse only NAND gates.',
    'Module helper must use only NAND gates.',
    '// Use only NAND gates.',
    '/* Use a minimum number of NAND gates. */',
    'initial $display("Use only NAND gates.");',
    'Use only AND, OR and NOT gates; sum-of-products is allowed.',
])
def test_inactive_logic_mentions_preserve_unrestricted_bytes(tmp_path, obligation):
    import deterministic_emit_chain as chain
    import design_one_shot_runner as runner
    import spec_artifact_registry as registry
    import time

    prompt = _KMAP_2IN + '\n' + obligation
    expected = K.synth(_KMAP_2IN, 'TopModule')
    assert K.synth(prompt, 'TopModule') == expected
    assert registry.generate(prompt, 'TopModule') == ('karnaugh_map', expected)
    assert chain.try_emit_ex(prompt, top='TopModule', check=False) == (
        'karnaugh_map', expected, [])
    result = runner._try_spec_artifact_registry_rtl(
        tmp_path, time.time(), phase1_plain_text=prompt)
    assert result.status == 'PASS', result.detail
    assert Path(result.output_files[0]).read_text() == K.synth(_KMAP_2IN, 'chip_top')


@pytest.mark.parametrize('obligation', _DECLARED_LOGIC_REQUESTS[:2])
@pytest.mark.parametrize('structured', [False, True])
def test_ordinary_logic_handoff_precedes_all_producers_and_preserves_case(
        tmp_path, obligation, structured):
    import json
    import design_one_shot_runner as runner

    (tmp_path / 'input').mkdir()
    source_dir = tmp_path / 'phase1/input_prompt'
    source_dir.mkdir(parents=True)
    (source_dir / 'design.md').write_text(_KMAP_2IN + '\n' + obligation)
    rtl_dir = tmp_path / 'phase2/stage1/rtl'
    rtl_dir.mkdir(parents=True)
    (rtl_dir / 'operator.txt').write_bytes(b'operator-owned\x00bytes\n')
    if structured:
        (tmp_path / 'input/rtl_spec.json').write_text(json.dumps({
            'module': 'TopModule', 'rows': [
                {'inputs': {'a': 0, 'b': 0}, 'outputs': {'q': 0}},
                {'inputs': {'a': 0, 'b': 1}, 'outputs': {'q': 1}},
                {'inputs': {'a': 1, 'b': 0}, 'outputs': {'q': 1}},
                {'inputs': {'a': 1, 'b': 1}, 'outputs': {'q': 0}}]}))
    before = {p.relative_to(tmp_path): p.read_bytes()
              for p in tmp_path.rglob('*') if p.is_file()}
    result = runner.step_rtl_gen(tmp_path, ic_class='__neutral_logic__', force_regen=True)
    assert result.status == 'PASS_WITH_WAIVERS', result.detail
    assert 'DECLARED_LOGIC_OBLIGATION_UNSUPPORTED' in result.detail
    assert result.extras['fallback_skill'] == 'spec-to-rtl'
    assert {p.relative_to(tmp_path): p.read_bytes()
            for p in tmp_path.rglob('*') if p.is_file()} == before
    assert result.output_files == []


def test_kmap_skip_on_dont_care():
    bad = _KMAP_2IN.replace("| 0 | 1 |", "| d | 1 |")
    assert K.synth(bad, "TopModule") is None


def test_kmap_skip_on_mux_decomposition():
    p = _KMAP_2IN.replace("output  q", "output mux_in (4 bits)").replace(
        " q\n", " mux_in (4 bits)\n")
    p = p.replace("function shown", "mux_in function shown") + "\nmux_in"
    assert K.synth(p, "TopModule") is None


def test_kmap_skip_when_not_a_kmap():
    assert K.synth("Implement TopModule, a combinational adder.", "TopModule") is None


# ── Step-2.7 §4.05 remediations ───────────────────────────────────────────────

def test_kmap_skip_multibit_output():
    """A K-map is a single-bit function. A multi-bit output driven by the 1-bit
    SOP (`output [3:0] q; assign q = <sop>`) compiles clean and PASSes
    spec_conformance → it would ship a width-broken sample SILENTLY. SKIP."""
    assert K.synth(_KMAP_2IN.replace(" - output q", " - output q (4 bits)"),
                   "TopModule") is None


def test_kmap_skip_when_axis_not_declared_port():
    """Axis labels are read from grid LAYOUT; a case-mismatch (`A`/`B` vs declared
    `a`/`b`) or stray word makes the SOP reference UNDECLARED signals → a wrong
    sample. Every axis bit must be a declared input port → else SKIP."""
    up = _KMAP_2IN.replace("       a\n", "       A\n").replace("  b   0   1", "  B   0   1")
    assert K.synth(up, "TopModule") is None


def test_kmap_clean_still_fires():
    rtl = K.synth(_KMAP_2IN, "TopModule")
    assert rtl is not None and "(~b & a)" in rtl and "(b & ~a)" in rtl


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── K-map → external-mux DECOMPOSITION (Shannon expansion) ───────────────────
# The grid's columns are printed in GRAY order (00 01 11 10) while a mux data
# input is indexed by the plain BINARY value of the selector. Reading the
# columns left-to-right into mux_in[0..3] swaps the last two data inputs. This
# fixture is built so the two readings DISAGREE, so the assertions discriminate.

_KMAP_MUX_DECOMP = """
Implement a module named TopModule.
 - input  c
 - input  d
 - output mux_in (4 bits)

The module should implement the function shown in the Karnaugh map below,
supplying the data inputs of an external 4-to-1 multiplexer whose select
inputs are {a,b}; ab = 00 is connected to mux_in[0], ab = 01 to mux_in[1],
and so on.

      ab
  cd  00  01  11  10
  00 | 0 | 1 | 1 | 0 |
  01 | 0 | 1 | 0 | 1 |
  11 | 0 | 1 | 0 | 0 |
  10 | 0 | 1 | 0 | 0 |
"""


def test_kmap_mux_decomposition_fires():
    """RED before the mux-decomposition branch existed: synth returned None
    (SKIP) for this whole family, so a coin-flipping blind author decided the
    index mapping instead of the program."""
    assert K.synth(_KMAP_MUX_DECOMP, "TopModule") is not None


def test_kmap_mux_decomposition_indexes_by_binary_not_gray():
    """GREEN: each data input is the column for that SELECTOR VALUE.

    Column ab=11 (binary 3) is 1 only at cd=00, and column ab=10 (binary 2) is
    1 only at cd=01. Indexing by print position instead would swap them -- the
    exact defect this branch removes."""
    rtl = K.synth(_KMAP_MUX_DECOMP, "TopModule")
    body = {ln.split("=")[0].strip(): ln.split("=", 1)[1].strip()
            for ln in rtl.splitlines() if ln.strip().startswith("assign")}
    assert body["assign mux_in[0]"] == "1'b0;"                    # all-zero column
    assert body["assign mux_in[1]"].count("|") == 3               # all-ones column
    assert body["assign mux_in[3]"] == "(~c & ~d);"               # ab=11 -> index 3
    assert body["assign mux_in[2]"] == "(~c & d);"                # ab=10 -> index 2
    # and the two are genuinely different, so the assertion above discriminates
    assert body["assign mux_in[2]"] != body["assign mux_in[3]"]


def test_kmap_mux_decomposition_skips_when_selectors_are_ports():
    """Envelope: if EVERY axis variable is a declared port this is an ordinary
    K-map, not a mux decomposition, and the vector output must still SKIP."""
    p = _KMAP_MUX_DECOMP.replace(" - input  c", " - input  a\n - input  b\n - input  c")
    assert K.synth(p, "TopModule") is None


def test_kmap_mux_decomposition_skips_on_dont_care():
    """An under-determined grid stays a FLOOR (§4.05), decomposition or not."""
    p = _KMAP_MUX_DECOMP.replace("  01 | 0 | 1 | 0 | 1 |", "  01 | 0 | 1 | 0 | d |")
    assert K.synth(p, "TopModule") is None


def test_kmap_mux_decomposition_skips_on_width_mismatch():
    """Output width must equal 2**(number of selector bits), else the reading
    that each bit is one selector value does not hold."""
    p = _KMAP_MUX_DECOMP.replace("mux_in (4 bits)", "mux_in (8 bits)")
    assert K.synth(p, "TopModule") is None


# Public neutral header + grid: external selectors are absent from the module.
_MUX_RESTRICTION_PROMPT = """Implement the data inputs of an external 4-to-1 multiplexer from this Karnaugh map.
{restriction}
       st
 uv    00 01 11 10
 00 | 0 | 1 | 0 | 1 |
 01 | 1 | 0 | 1 | 0 |
 11 | 1 | 1 | 0 | 0 |
 10 | 0 | 0 | 1 | 1 |
module ColumnStage (
 input u,
 input v,
 output [3:0] lane_values
);
"""


@pytest.mark.parametrize('restriction', [
    'Use only multiplexers; no other logic gates are allowed.',
    'Use only multiplexers.',
    'You must use only 2-to-1 multiplexers.',
    'You may only use muxes.',
    'Implement using only multiplexers.',
    'Only multiplexers may be used.',
    'You are not allowed to use any other logic gate.',
    'You are not allowed to use any other logic gate and selectors must retain their declared order.',
    'No other logic gates are permitted.',
])
@pytest.mark.parametrize('entry', ['producer', 'registry'])
def test_explicit_mux_only_decomposition_declines_for_normal_backup(restriction, entry):
    prompt = _MUX_RESTRICTION_PROMPT.format(restriction=restriction)
    if entry == 'registry':
        import spec_artifact_registry as registry
        kind, rtl = registry.generate(prompt, 'ColumnStage')
    else:
        kind, rtl = None, K.synth(prompt, 'ColumnStage')
    observed = ('DECLINED' if rtl is None else 'FORBIDDEN_SOP'
                if all(token in rtl for token in ('~', '&', '|')) else 'OTHER_RTL')
    assert observed == 'DECLINED', {'observed': observed, 'rtl': rtl}
    assert kind is None


@pytest.mark.parametrize('restriction', [
    '',
    'Use a multiplexer decomposition.',
    'The external mux uses only the selector bits shown.',
    'Use only the data inputs of the external multiplexer.',
    'You may use multiplexers and other logic gates.',
    'Sum-of-products with AND, OR and NOT gates is explicitly allowed.',
    'You are not restricted to multiplexers; other logic gates are allowed.',
    'Do not use only multiplexers; sum-of-products is allowed.',
    'The implementation may use gates or multiplexers.',
])
def test_nonrestrictive_mux_prose_preserves_exact_sop(restriction):
    import spec_artifact_registry as registry
    plain = _MUX_RESTRICTION_PROMPT.format(restriction='')
    prompt = _MUX_RESTRICTION_PROMPT.format(restriction=restriction)
    expected = K.synth(plain, 'ColumnStage')
    rtl = K.synth(prompt, 'ColumnStage')
    observed = ('DECLINED' if rtl is None else 'SOP'
                if all(token in rtl for token in ('~', '&', '|')) else 'OTHER_RTL')
    assert observed == 'SOP', {'observed': observed, 'rtl': rtl}
    assert rtl == expected
    assert registry.generate(prompt, 'ColumnStage') == ('karnaugh_map', expected)


def test_conflicting_explicit_mux_only_prose_declines_instead_of_guessing():
    prompt = _MUX_RESTRICTION_PROMPT.format(restriction=(
        'Use only multiplexers. Other logic gates are also permitted.'))
    rtl = K.synth(prompt, 'ColumnStage')
    assert ('DECLINED' if rtl is None else 'EMITTED') == 'DECLINED'


def test_mux_constraint_does_not_expand_single_output_or_bad_axis_envelopes():
    # This repair owns external-mux decomposition only, not all K-map synthesis.
    assert K.synth(_KMAP_2IN + '\nA multiplexer is an example circuit.', 'TopModule') == K.synth(_KMAP_2IN, 'TopModule')
    prompt = _MUX_RESTRICTION_PROMPT.format(restriction='Use only multiplexers.')
    assert K.synth(prompt.replace(' uv    00', ' zz    00'), 'ColumnStage') is None
    assert K.synth(prompt.replace(' 01 | 1 | 0 | 1 | 0 |', ' 01 | 1 | d | 1 | 0 |'), 'ColumnStage') is None


@pytest.mark.parametrize('restriction', [
    'Use only multiplexers and AND, OR, or NOT gates; sum-of-products is explicitly allowed.',
    'Do not\nuse only multiplexers; sum-of-products is explicitly allowed.',
])
@pytest.mark.parametrize('entry', ['producer', 'registry'])
def test_allowed_gate_list_and_wrapped_negation_preserve_sop(restriction, entry):
    prompt = _MUX_RESTRICTION_PROMPT.format(restriction=restriction)
    expected = K.synth(_MUX_RESTRICTION_PROMPT.format(restriction=''), 'ColumnStage')
    if entry == 'registry':
        import spec_artifact_registry as registry
        kind, rtl = registry.generate(prompt, 'ColumnStage')
        assert kind in (None, 'karnaugh_map')
    else:
        rtl = K.synth(prompt, 'ColumnStage')
    observed = ('DECLINED' if rtl is None else 'SOP'
                if all(token in rtl for token in ('~', '&', '|')) else 'OTHER_RTL')
    assert observed == 'SOP', {'observed': observed, 'rtl': rtl}
    assert rtl == expected


@pytest.mark.parametrize('restriction', [
    'Only multiplexers may be used alongside AND, OR and NOT gates; sum-of-products is explicitly allowed.',
    'You are not allowed to use any other logic gate than AND, OR and NOT gates; sum-of-products is explicitly allowed.',
    'No other logic gates are allowed except AND, OR and NOT gates; sum-of-products is explicitly allowed.',
])
@pytest.mark.parametrize('wrap', [False, True])
@pytest.mark.parametrize('entry', ['producer', 'registry'])
def test_permitted_gate_exceptions_preserve_sop_across_wrapping(restriction, wrap, entry):
    if wrap:
        restriction = restriction.replace(' alongside', '\nalongside').replace(
            ' than', '\nthan').replace(' except', '\nexcept')
    prompt = _MUX_RESTRICTION_PROMPT.format(restriction=restriction)
    expected = K.synth(_MUX_RESTRICTION_PROMPT.format(restriction=''), 'ColumnStage')
    if entry == 'registry':
        import spec_artifact_registry as registry
        kind, rtl = registry.generate(prompt, 'ColumnStage')
        assert kind in (None, 'karnaugh_map')
    else:
        rtl = K.synth(prompt, 'ColumnStage')
    observed = ('DECLINED' if rtl is None else 'SOP'
                if all(token in rtl for token in ('~', '&', '|')) else 'OTHER_RTL')
    assert observed == 'SOP', {'observed': observed, 'rtl': rtl}
    assert rtl == expected
