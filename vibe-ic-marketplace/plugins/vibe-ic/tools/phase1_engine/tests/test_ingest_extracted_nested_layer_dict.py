"""tests/test_ingest_extracted_nested_layer_dict.py — v1.6.301

Closes ORGANIC #202: the Phase 1 ingester silently folded nested-
layer-dict shape (`{"L1": {...}, "L2": {...}}`) into `L1.L2.*` paths
under canonical fact-building, producing a 41pp captured_pct silent
loss on the same fact content. The EXTRACT_SYSTEM_PROMPT documents
the flat dotted shape (`{"L1.field": ...}`); but LLM agents routinely
emit the more intuitive nested-dict shape instead.

Fix (v1.6.301): `_is_nested_layer_dict_shape` + `_flatten_nested_layer_dict`
helpers in `tools/phase1_engine/nl_ingest.py`, wired into
`from_extracted_facts` BEFORE alias rewrites. Logs a clear recovery
line so the operator sees auto-flatten happened.

Regression guard: flat dotted input still produces identical facts;
mixed-shape input falls through to flat-input handling (auto-flatten
only fires when ALL top-level keys are layer codes AND all values
are dicts).

Chip-AGNOSTIC.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.phase1_engine.nl_ingest import (  # noqa: E402
    _flatten_nested_layer_dict,
    _is_nested_layer_dict_shape,
    from_extracted_facts,
)


# ------------------------------------------------------------------
# v1.6.301 — _is_nested_layer_dict_shape detector
# ------------------------------------------------------------------

def test_v1_6_301_detect_nested_shape_canonical() -> None:
    """`{"L1": {...}, "L2": {...}}` → True."""
    extracted = {
        "L1": {"product_family": {"name": "FooCore"}},
        "L2": {"cpu": {"core_count_options": [1, 2, 4]}},
    }
    assert _is_nested_layer_dict_shape(extracted) is True


def test_v1_6_301_detect_nested_shape_includes_l8r() -> None:
    """`L8R` (with `R` suffix) is also a valid layer code."""
    extracted = {
        "L1": {"x": "y"},
        "L8R": {"synthesis_results": []},
    }
    assert _is_nested_layer_dict_shape(extracted) is True


def test_v1_6_301_detect_flat_shape_returns_false() -> None:
    """Flat dotted form should NOT trigger auto-flatten."""
    extracted = {
        "L1.product_family.name": "FooCore",
        "L2.cpu.core_count_options": [1, 2, 4],
    }
    assert _is_nested_layer_dict_shape(extracted) is False


def test_v1_6_301_detect_mixed_shape_returns_false() -> None:
    """Mixed (some flat + some nested) → False (only fires when
    ALL top-level keys are layer codes AND all values are dicts)."""
    extracted = {
        "L1.product_family.name": "FooCore",
        "L2": {"cpu": {"x": 1}},
    }
    assert _is_nested_layer_dict_shape(extracted) is False


def test_v1_6_301_detect_empty_returns_false() -> None:
    assert _is_nested_layer_dict_shape({}) is False


def test_v1_6_301_detect_non_dict_returns_false() -> None:
    assert _is_nested_layer_dict_shape([]) is False  # type: ignore
    assert _is_nested_layer_dict_shape("nope") is False  # type: ignore


def test_v1_6_301_detect_nested_layer_with_scalar_value_returns_false() -> None:
    """If a top-level value is a scalar (not a dict), shape is NOT
    purely nested-dict — fall through to flat-input handling."""
    extracted = {
        "L1": "scalar_value",
        "L2": {"cpu": {"x": 1}},
    }
    assert _is_nested_layer_dict_shape(extracted) is False


# ------------------------------------------------------------------
# v1.6.301 — _flatten_nested_layer_dict transformer
# ------------------------------------------------------------------

def test_v1_6_301_flatten_simple_two_level_nesting() -> None:
    extracted = {
        "L1": {"product_family": {"name": "FooCore"}},
    }
    flat = _flatten_nested_layer_dict(extracted)
    assert flat == {"L1.product_family.name": "FooCore"}


def test_v1_6_301_flatten_multi_layer_nested() -> None:
    extracted = {
        "L1": {"product_family": {"name": "X"}},
        "L2": {"cpu": {"core_count_options": [1, 2, 4]}},
        "L8R": {"synthesis_results": []},
        "L9": {"clock_frequency_hz": 50_000_000},
    }
    flat = _flatten_nested_layer_dict(extracted)
    assert flat == {
        "L1.product_family.name": "X",
        "L2.cpu.core_count_options": [1, 2, 4],
        "L8R.synthesis_results": [],
        "L9.clock_frequency_hz": 50_000_000,
    }


def test_v1_6_301_flatten_deep_nesting() -> None:
    """Three-level deep dict nesting all flattens."""
    extracted = {
        "L1": {
            "tapeout_metadata": {
                "process_node": {"pdk_id": "GF180MCU"},
            },
        },
    }
    flat = _flatten_nested_layer_dict(extracted)
    assert flat == {
        "L1.tapeout_metadata.process_node.pdk_id": "GF180MCU",
    }


def test_v1_6_301_flatten_preserves_list_leaves() -> None:
    """List values are leaves — not recursed into."""
    extracted = {
        "L1": {"axes": ["x", "y", "z"]},
        "L2": {"timing_parameters": [{"name": "t1", "value_ns": 5}]},
    }
    flat = _flatten_nested_layer_dict(extracted)
    assert flat == {
        "L1.axes": ["x", "y", "z"],
        "L2.timing_parameters": [{"name": "t1", "value_ns": 5}],
    }


def test_v1_6_301_flatten_empty_dict_value_preserved() -> None:
    """An explicit empty-dict leaf is preserved as `{}` (not lost)."""
    extracted = {
        "L1": {"empty_section": {}},
    }
    flat = _flatten_nested_layer_dict(extracted)
    assert flat == {"L1.empty_section": {}}


# ------------------------------------------------------------------
# v1.6.301 — end-to-end auto-flatten in from_extracted_facts
# ------------------------------------------------------------------

def test_v1_6_301_e2e_nested_input_produces_same_factgraph_as_flat() -> None:
    """Nested-dict input and equivalent flat-dotted input must produce
    fact-graphs whose flat-path key sets are identical."""
    nested = {
        "L1": {"product_family": {"name": "FooCore"}},
        "L2": {"cpu": {"core_count_options": [1, 2, 4]}},
        "L9": {"clock_frequency_hz": 50_000_000},
    }
    flat = {
        "L1.product_family.name": "FooCore",
        "L2.cpu.core_count_options": [1, 2, 4],
        "L9.clock_frequency_hz": 50_000_000,
    }

    fg_nested = from_extracted_facts(nested, class_path="processor")
    fg_flat = from_extracted_facts(flat, class_path="processor")

    nested_paths = {f.path for f in fg_nested.facts}
    flat_paths = {f.path for f in fg_flat.facts}

    assert nested_paths == flat_paths, (
        f"Nested-shape ingest produced different fact-graph paths "
        f"than flat-shape ingest:\n"
        f"  nested-only: {nested_paths - flat_paths}\n"
        f"  flat-only:   {flat_paths - nested_paths}"
    )


def test_v1_6_301_e2e_empty_nested_input_still_works() -> None:
    """Empty top-level dict — no error, empty fact-graph."""
    fg = from_extracted_facts({}, class_path="processor")
    assert fg.ic_name == "__unknown__"
    assert list(fg.facts) == []


def test_v1_6_301_e2e_flat_input_no_regression() -> None:
    """Flat dotted input — must not trigger auto-flatten path; all
    paths preserved verbatim."""
    flat = {
        "L1.product_family.name": "FooCore",
        "L9.clock_frequency_hz": 100_000_000,
    }
    fg = from_extracted_facts(flat, class_path="processor")
    paths = {f.path for f in fg.facts}
    assert "L1.product_family.name" in paths
    assert "L9.clock_frequency_hz" in paths


def test_v1_6_301_e2e_logs_recovery_to_stderr(capsys) -> None:
    """When auto-flatten fires, a clear log line goes to stderr."""
    nested = {
        "L1": {"product_family": {"name": "X"}},
    }
    from_extracted_facts(nested, class_path="processor")
    captured = capsys.readouterr()
    assert "nested-layer-dict shape detected" in captured.err
    assert "auto-flattening" in captured.err
