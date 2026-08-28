"""A language keyword quoted in spec prose is not a submodule.

External-interface documents routinely quote Verilog keywords in prose to tell
the implementer what NOT to write -- "all module ports are declared unsigned
(do not use the ``signed`` keyword in a port declaration)".  The heading-
anchored bullet walker harvests backticked identifiers from the bullet block
under an ``Integration`` / ``Modules`` heading, so that quoted keyword was
collected as a submodule name.

Two properties made it damaging rather than cosmetic:

  * the bullet path does NOT tag its entries ``low_confidence`` (the sibling
    heading path does, and `l9_submodule_conformance_check` correctly skips
    those), so the keyword lands as a CONFIDENT declaration;
  * `l9_submodule_conformance_check` therefore EXAMINES it and returns
    ``SUBMODULE_FILE_MISSING`` -- a FAIL, on a correct design, for a submodule
    the design never declared.

The bullet filter deliberately relaxes `_is_real_submodule_name`'s RTL-shape
gate (the heading anchor is strong evidence, so bare words like ``alu`` are
legitimate here).  That relaxation is what lets a bare keyword through, so the
deny list is where the guard belongs.

Negative control: `test_quoted_reserved_word_is_not_a_submodule` drives the
REAL emit path end-to-end, so it fails BEHAVIOURALLY against the byte-identical
pre-fix program (the keyword appears in ``L9.submodules``) rather than merely
raising on a symbol the pre-fix module does not export.  The remaining tests
are tightening guards; they reach the filter through a shim that works against
both the pre-fix (nested) and post-fix (module-level) shape for the same
reason.

chip-AGNOSTIC: IEEE 1364 / 1800 reserved words and English tokens only.  No
chip, vendor, PDK or IC-name literal participates.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import phase1_doc_one_shot_runner as R  # noqa: E402

import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_RUNNER = _PROGRAMS / "phase1_one_shot_runner.py"


# The exact prose shape that triggers it: an `Integration` heading (in the
# bullet-walker's heading vocabulary) followed by a bullet that QUOTES a
# keyword in order to forbid it.
def _iface_doc(keyword: str = "signed") -> str:
    return """
# External Interface

## Module Port List

Top module name: **`widget_core`**

| Signal | Direction | Width |
|---|---|---|
| `clk`  | input  | 1 |
| `dout` | output | 8 |

## Integration constraints

- All module ports are declared unsigned (do not use the `%s` keyword in a
  port declaration); internal signed arithmetic uses `$signed()`.
- Pin placement is chosen by the place-and-route tool.
""" % (keyword,)


def _emitted_submodule_names(tmp_path: Path, keyword: str = "signed"):
    """Run Phase 1 end-to-end and return the names in ``L9.submodules``.

    Goes through the shipped runner rather than an internal symbol so the
    result is comparable across the fix boundary -- that is what makes the
    negative control a BEHAVIOURAL one.
    """
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L3_external_interface.md").write_text(_iface_doc(keyword))
    (docs / "L1_product_metadata.md").write_text(
        "# L1 — Product Metadata\n\n"
        "| Field | Value |\n|---|---|\n"
        "| product_name | `widget_core` |\n")
    # Bounded at the harness ceiling `ci_harness_timeout_ceiling_check`
    # enforces (60s vs the 180s session bound), so THIS call's own timeout
    # fires and fails the test rather than the harness killing the session.
    # Measured: this Phase-1 invocation returns in ~1-3s, so the bound is
    # ~20x headroom, not a tight fit.
    proc = _pr.run(
        [sys.executable, str(_RUNNER), str(tmp_path), "--ic-name",
         "widget_core"],
        capture_output=True, text=True)
    l9 = tmp_path / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    assert l9.is_file(), (
        "Phase 1 emitted no L9 (rc=%s)\n%s" % (proc.returncode, proc.stdout[-3000:]))
    blob = json.loads(l9.read_text())
    return [str(s.get("name")) for s in (blob.get("submodules") or [])
            if isinstance(s, dict)]


def _accepts(nm: str) -> bool:
    """Signature-agnostic filter call.

    Post-fix the filter is module-level.  Pre-fix it was nested inside the L9
    emitter and unreachable by name, so fall back to asking the walker whether
    the name survives -- the same question, answered through the shipped path.
    """
    fn = getattr(R, "_is_bullet_submodule_name", None)
    if fn is not None:
        return bool(fn(nm))
    doc = "## Submodules\n\n- the `%s` block\n" % (nm,)
    return nm in list(R._l9_bullet_submodule_extract(doc))


def test_quoted_reserved_word_is_not_a_submodule(tmp_path):
    """NEGATIVE CONTROL — fails BEHAVIOURALLY pre-fix, passes post-fix."""
    names = _emitted_submodule_names(tmp_path)
    assert "signed" not in names, (
        "the reserved word `signed`, quoted in prose in order to FORBID it, "
        "was emitted as a confident L9 submodule: %r" % (names,))


def test_every_reserved_word_is_rejected():
    """The guard is the whole keyword set, not one special case."""
    for kw in ("input", "output", "inout", "module", "wire", "reg",
               "always", "assign", "generate", "function", "signed"):
        assert _accepts(kw) is False, (
            "reserved word %r accepted as a submodule name" % (kw,))


def test_real_submodule_names_survive():
    """TIGHTENING GUARD — the relaxed bare-word acceptance must be kept.

    These are exactly the names the bullet path exists to accept; a deny list
    that cost the design them would trade one false FAIL for another.
    """
    for nm in ("alu", "regfile", "crc8", "rx_phy", "byte_assembler",
               "spi_master", "aes_core"):
        assert _accepts(nm) is True, (
            "real submodule name %r was rejected" % (nm,))


def test_a_name_that_merely_contains_a_keyword_survives():
    """TIGHTENING GUARD — exact match only.

    `signed_mult` and `case_decoder` are ordinary module names that happen to
    embed a keyword.  A substring-based deny list would delete them, which is
    how a guard against a false FAIL becomes a false FAIL of its own.
    """
    for nm in ("signed_mult", "case_decoder", "input_buffer",
               "output_stage", "module_top", "wire_delay"):
        assert _accepts(nm) is True, (
            "legitimate name %r rejected by an over-broad keyword deny" % (nm,))
