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
import sys
from pathlib import Path

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
