"""`module named \\`foo\\`` was read as the declaration "module name" plus `d`.

`_REQ_MODULE_NAME_RE` matched `name` without a word boundary, so the word
`named` satisfied it and the extractor took the leftover `d` as the required
module name. The stem this function returns is what the gate checks a
completion's module name AGAINST, so a junk stem is not inert.

Measured over the 302 public CVDP prompts, before → after:

    a plausible module name    24 → 59
    an English fragment        39 → 0     (`d`, `The`, `and`)
    nothing at all            239 → 243

and no design lost a real stem — every dropped value was a stopword.
"""
import importlib.util
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
BENCH = PLUGIN / "benchmark"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))


def _gate():
    spec = importlib.util.spec_from_file_location(
        "gate_modname_under_test", BENCH / "cvdp_gate.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_named_is_not_read_as_name_plus_d():
    """THE REGRESSION, verbatim from cvdp_copilot_prbs_gen_0003."""
    got = _gate().required_module_names_from_prompt(
        "Create a SystemVerilog module named `cvdp_prbs_gen` that ...")
    assert "d" not in got, got
    assert "cvdp_prbs_gen" in got, got


def test_the_declaration_form_still_works():
    """The other tail: `Module Name:` is the form 293 of 302 prompts use."""
    got = _gate().required_module_names_from_prompt(
        "### Module Name:\n`qam16_mapper_interpolated`\n\nThe module ...")
    assert "qam16_mapper_interpolated" in got, got


def test_the_called_variant_is_read_too():
    got = _gate().required_module_names_from_prompt(
        "Design a module called `barrel_shifter_8bit` which ...")
    assert "barrel_shifter_8bit" in got, got


def test_an_english_fragment_is_never_returned():
    """A stem that is a stopword is evidence the regex caught prose. Returning
    it is worse than returning nothing, because the gate would check a real
    completion against it."""
    g = _gate()
    for text in ("the module name is the one you must use",
                 "a module named the thing",
                 "this module and its ports"):
        for stem in g.required_module_names_from_prompt(text):
            assert stem.lower() not in g._MODULE_NAME_STOPWORDS, (text, stem)


def test_a_prompt_that_names_nothing_returns_nothing():
    """It must not invent a name — `required_module_names_from_prompt` returning
    empty is how the gate knows to fall through to its id-derived candidates."""
    assert _gate().required_module_names_from_prompt(
        "Design a synchronous counter that increments on each clock edge.") == set()
