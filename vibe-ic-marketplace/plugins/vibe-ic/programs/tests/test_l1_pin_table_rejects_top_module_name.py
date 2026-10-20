"""A design's own top-module name is not one of its ports.

An external-interface document that states the top module by name puts a
backticked identifier inside a port-context heading range.  The v455 backtick
walker promoted that identifier to a PIN with ``mode='unspecified'`` — a
sentence that NAMES THE MODULE read as a sentence that declares a port.

The phantom pin lands in ``L1.pin_table`` but never in ``L9.ports`` (the
consumed layer), so ``l_doc_cross_consistency_check`` rule
``R_pin_table_subset_ports`` reports the design's own module name as a pin
"absent from L9" — a FAIL on a pin the design never had.

Negative control: the FIRST test below FAILS against the pre-fix code (the
phantom pin is present) and PASSES after.  The remaining tests are the
tightening guards — they pass BOTH before and after, and exist so the fix
cannot be widened later into something that swallows a real port.

chip-AGNOSTIC: the comparison is against the design's OWN extracted
top-module / ic_name.  No chip, vendor, PDK or IC-name literal.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import phase1_doc_one_shot_runner as R  # noqa: E402


# A minimal external-interface doc in the exact shape that triggers the bug:
# a port-context heading, a real port table, and one sentence that NAMES the
# module.  The module name is a neutral placeholder, not any real IC.
_DOC = {
    "iface.md": """
# External Interface

Top module name: **`widget_core`**

| Signal | Direction | Width | Description |
|---|---|---|---|
| `clk`   | input  | 1 | clock |
| `rst_n` | input  | 1 | async active-low reset |
| `dout`  | output | 8 | result bus |
""",
}


def _pin_names(pins):
    return [str(p.get("name")) for p in pins]


def _merge(pins, doc, self_name=None):
    """Signature-agnostic call so the negative control fails BEHAVIOURALLY
    against the pre-fix code (phantom pin present) rather than merely with a
    TypeError from the new parameter."""
    try:
        return R._v455_sanitize_and_merge_pins(pins, doc, self_name)
    except TypeError:
        return R._v455_sanitize_and_merge_pins(pins, doc)


def test_top_module_name_is_not_promoted_to_a_pin():
    """NEGATIVE CONTROL — fails pre-fix, passes post-fix."""
    pins = _merge(R._v455_interface_pins(_DOC), _DOC, "widget_core")
    names = _pin_names(pins)
    assert "widget_core" not in names, (
        "the top-module name was promoted to a pin: %r" % (names,))


def test_the_real_ports_survive():
    """The fix must not cost the design its actual ports."""
    pins = _merge(R._v455_interface_pins(_DOC), _DOC, "widget_core")
    names = _pin_names(pins)
    for want in ("clk", "rst_n", "dout"):
        assert want in names, "real port %r was dropped: %r" % (want, names)


def test_no_resolvable_self_name_is_a_no_op():
    """DEGRADE-SAFELY — an unresolvable chip name must drop NOTHING.

    With no `self_name` argument and doc text the name heuristics decline to
    read (they return ``UNKNOWN_IC`` / ``None``), the guard has nothing to
    compare against and must leave the pin set exactly as it found it.  A
    guard that fired on an empty name would delete pins from every design
    whose docs do not state a name.
    """
    doc = {
        "iface.md": "## I/O\n\nTop module name: **`widget_core`**\n"
                    "| Signal | Direction |\n|---|---|\n| `clk` | input |\n",
    }
    # Precondition of this test: neither heuristic resolves a name here.
    assert R._ic_name_from_docs(doc) == "UNKNOWN_IC"
    assert R._extract_top_module_from_docs(doc) is None

    before = _pin_names(R._v455_interface_pins(doc))
    after = _pin_names(_merge(R._v455_interface_pins(doc), doc, None))
    assert after == before, (
        "guard dropped a pin with no resolvable self-name: %r -> %r"
        % (before, after))


def test_a_directioned_port_keeps_its_name_even_if_it_matches():
    """TIGHTENING GUARD — the drop is conditioned on having NO direction.

    A pin that some walker did establish a direction for is a real port and is
    kept even when its name collides with the module name.  Without this the
    guard could mask a genuinely missing port.
    """
    doc = {"iface.md": "# I/O\n\nTop module name: **`widget_core`**\n"}
    pins = [{"name": "widget_core", "mode": "input"}]
    kept = _merge(pins, doc, "widget_core")
    assert "widget_core" in _pin_names(kept), (
        "a port carrying a direction must never be dropped by the "
        "self-name guard: %r" % (_pin_names(kept),))


def test_an_unrelated_directionless_token_is_not_dropped_by_this_guard():
    """TIGHTENING GUARD — only the design's OWN name is rejected here.

    Some other directionless entry must be left to the pre-existing guards
    (#455 ALL-CAPS prose, #475 SDC/stdcell shapes), not swallowed by this one.
    """
    doc = {"iface.md": "# I/O\n\nTop module name: **`widget_core`**\n"}
    pins = [{"name": "spi_sclk", "mode": "unspecified"}]
    kept = _merge(pins, doc, "widget_core")
    assert "spi_sclk" in _pin_names(kept), (
        "the self-name guard must not reach unrelated tokens: %r"
        % (_pin_names(kept),))


def test_reuses_the_existing_rejector():
    """The invariant already exists for the submodule back-walker (#343 P2).

    This is a wiring fix, not a new rule; assert the existing predicate is
    the one that decides, so a future change to it stays single-sourced.
    """
    assert R._v1_6_478_reject_top_module_name("widget_core", "widget_core")
    assert not R._v1_6_478_reject_top_module_name("clk", "widget_core")


def _ordinary_l1_and_pin_consumer(project, text):
    source = project / "input/docs/interface.md"
    source.parent.mkdir(parents=True)
    source.write_text(text)
    emitted = R.gen_l1_datasheet(project, {source.name: text})
    payload = json.loads(Path(emitted.path).read_text())
    consumer = subprocess.run(
        [sys.executable, str(Path(R.__file__).with_name(
            "l1_pin_table_aliases_typed_check.py")), str(project)],
        capture_output=True, text=True,
    )
    (project / "pin-consumer.json").write_text(json.dumps({
        "rc": consumer.returncode, "stdout": consumer.stdout,
        "stderr": consumer.stderr, "pins": payload["pin_table"],
    }, indent=2))
    return payload["pin_table"], consumer


def test_implementation_prose_is_not_a_physical_pin_declaration(tmp_path):
    from _hostpaths import require_repo
    fixture = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "phase1_local", "neutral_io_analysis_prose",
        "physical_io_analysis.md",
    )
    pins, consumer = _ordinary_l1_and_pin_consumer(tmp_path, fixture.read_text())
    assert (pins, consumer.returncode) == ([], 2), consumer.stdout


@pytest.mark.parametrize("prose", [
    "Source ALPHA input authority takes precedence over defaults.",
    "Verify BETA output requirements before the owner signs the input revision.",
    "Append GAMMA once after the input windows; DELTA authorizes this revision.",
])
def test_io_heading_does_not_lend_direction_to_prose_nouns(tmp_path, prose):
    pins, consumer = _ordinary_l1_and_pin_consumer(
        tmp_path, "# Physical I/O analysis\n" + prose + "\n")
    assert (pins, consumer.returncode) == ([], 2), consumer.stdout


@pytest.mark.parametrize("shape", ["table", "plain", "fenced"])
def test_same_names_remain_real_hardware_ports(tmp_path, shape):
    bodies = {
        "table": "| Signal | Direction | Width | Description |\n"
                 "|---|---|---|---|\n"
                 "| SDC | input | 4 | constraint input |\n"
                 "| ROOT | output | 2 | revision output |\n",
        "plain": "SDC input\nROOT output\n",
        "fenced": "```verilog\nmodule neutral(input [3:0] SDC, "
                  "output [1:0] ROOT); endmodule\n```\n",
    }
    pins, consumer = _ordinary_l1_and_pin_consumer(
        tmp_path, "# Hardware I/O\n" + bodies[shape])
    assert {p["name"]: p["mode"] for p in pins} == {
        "SDC": "input", "ROOT": "output"}, pins
    assert consumer.returncode == 0, consumer.stdout + consumer.stderr
    if shape != "plain":
        assert {p["name"]: p["width"] for p in pins} == {"SDC": 4, "ROOT": 2}


def test_table_description_cannot_declare_another_pin(tmp_path):
    text = "# Hardware I/O\n| Signal | Direction | Width | Description |\n" \
           "|---|---|---|---|\n" \
           "| SDC | input | 4 | ALPHA input implementation authority |\n" \
           "| ROOT | output | 2 | BETA output revision approval |\n"
    pins, consumer = _ordinary_l1_and_pin_consumer(tmp_path, text)
    assert {p["name"]: (p["mode"], p.get("width")) for p in pins} == {
        "SDC": ("input", 4), "ROOT": ("output", 2)}, pins
    assert consumer.returncode == 0, consumer.stdout + consumer.stderr


@pytest.mark.parametrize("declaration", [
    "SDC, ROOT input", "input SDC, ROOT", "SDC and ROOT input",
])
def test_grouped_bare_hardware_declarations_keep_both_ports(tmp_path, declaration):
    pins, consumer = _ordinary_l1_and_pin_consumer(
        tmp_path, "# Hardware I/O\n" + declaration + "\n")
    assert {p["name"]: p["mode"] for p in pins} == {
        "SDC": "input", "ROOT": "input"}, pins
    assert consumer.returncode == 0, consumer.stdout + consumer.stderr


@pytest.mark.parametrize("body", [
    "SDC input authority takes precedence over defaults.\n",
    "```verilog\n// SDC input authority is managed by the flow.\n"
    "module neutral(); endmodule\n```\n",
    "```verilog\n/*\nSDC input\n*/\nmodule neutral(); endmodule\n```\n",
    "```verilog\n// `SDC` input authority is managed by the flow.\n"
    "module neutral(); endmodule\n```\n",
], ids=["plain-authority", "fenced-comment", "block-comment", "quoted-comment"])
def test_implementation_noun_cannot_borrow_a_declaration_shape(tmp_path, body):
    pins, consumer = _ordinary_l1_and_pin_consumer(
        tmp_path, "# Hardware I/O\n" + body)
    assert (pins, consumer.returncode) == ([], 2), consumer.stdout


@pytest.mark.parametrize("declaration", [
    "input [3:0] SDC", "SDC (input)", "SDC [3:0] input",
    "SDC - input", "output logic [3:0] SDC",
    "SDC (4) input", "SDC — input", "1. SDC input", "SDC : input",
])
def test_existing_bare_port_forms_keep_the_declared_pin(tmp_path, declaration):
    pins, consumer = _ordinary_l1_and_pin_consumer(
        tmp_path, "# Hardware I/O\n" + declaration + "\n")
    direction = "output" if declaration.startswith("output") else "input"
    assert {p["name"]: p["mode"] for p in pins} == {"SDC": direction}, pins
    assert consumer.returncode == 0, consumer.stdout + consumer.stderr


@pytest.mark.parametrize("name", ["SDC", "`SDC`"])
def test_pipe_notes_cannot_supply_the_declared_direction_column(tmp_path, name):
    pins, consumer = _ordinary_l1_and_pin_consumer(
        tmp_path, "# Hardware I/O\n| Signal | Direction | Notes |\n"
        f"|---|---|---|\n| {name} | 4 | input |\n")
    assert (pins, consumer.returncode) == ([], 2), consumer.stdout


def test_grouped_fenced_declarations_keep_both_ports(tmp_path):
    pins, consumer = _ordinary_l1_and_pin_consumer(
        tmp_path, "# Hardware I/O\n```verilog\n"
        "module neutral(input [3:0] SDC, ROOT); endmodule\n```\n")
    assert {p["name"]: (p["mode"], p["width"]) for p in pins} == {
        "SDC": ("input", 4), "ROOT": ("input", 4)}, pins
    assert consumer.returncode == 0, consumer.stdout + consumer.stderr
