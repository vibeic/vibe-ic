"""Tests for source_chip_agnostic_check (v1.6.38 anti-fabrication gate)."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from programs.source_chip_agnostic_check import audit


def _mk_plugin(tmp_path: Path, files: dict) -> Path:
    """files: {relative_path_str: contents}"""
    root = tmp_path / "plugin"
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
    return root


def test_clean_plugin_passes(tmp_path: Path) -> None:
    root = _mk_plugin(tmp_path, {
        "programs/widget.py": """
            def make_widget():
                return "ok"
        """,
        "skills/widget/SKILL.md": "# widget\n\nDoes widget things.",
    })
    v, findings = audit(root)
    assert v == "PASS"
    assert findings == []


def test_chip_sku_in_program_caught(tmp_path: Path) -> None:
    # EXAMPLE_CHIP is a stand-in SKU token (real private SKUs are kept
    # out of the public test tree); supply it via extra_tokens so the
    # gate exercises its default forbidden-token matching path on a
    # program-file comment.
    root = _mk_plugin(tmp_path, {
        "programs/widget.py": """
            def make_widget():
                # EXAMPLE_CHIP SDQ tester reference voltage = 1.62V
                return 1.62
        """,
    })
    v, findings = audit(root, extra_tokens=["EXAMPLE_CHIP"])
    assert v == "FAIL"
    assert any(f.token.upper() == "EXAMPLE_CHIP" for f in findings)


def test_foundry_pdk_in_skill_caught(tmp_path: Path) -> None:
    # commercial_pdk is a stand-in foundry-PDK token; supply it via
    # extra_tokens so the gate exercises forbidden-token detection on a
    # skill-doc file.
    root = _mk_plugin(tmp_path, {
        "skills/place/SKILL.md": "Use commercial_pdk metal stack only.",
    })
    v, findings = audit(root, extra_tokens=["commercial_pdk"])
    assert v == "FAIL"
    assert any("commercial_pdk" in f.token.upper() for f in findings)


def test_allowlist_skill_can_mention_tokens(tmp_path: Path) -> None:
    """skills/community-backlog-submit/ explains the rule and must be
    able to mention vendor tokens as examples."""
    root = _mk_plugin(tmp_path, {
        "skills/community-backlog-submit/SKILL.md":
            "Examples: EXAMPLE_CHIP, commercial_pdk, EXAMPLE_TESTER. These are forbidden in source.",
    })
    v, findings = audit(root)
    assert v == "PASS"


def test_extra_tokens_extend_panel(tmp_path: Path) -> None:
    root = _mk_plugin(tmp_path, {
        "programs/widget.py": """
            def make_widget():
                # ABC123 vendor reference
                return 1
        """,
    })
    v_default, _ = audit(root)
    assert v_default == "PASS"  # ABC123 not in default panel
    v_ext, findings = audit(root, extra_tokens=["ABC123"])
    assert v_ext == "FAIL"
    assert any(f.token == "ABC123" for f in findings)


def test_md_905_word_boundary(tmp_path: Path) -> None:
    """A multi-part SKU token (EXAMPLE_TESTER stand-in) must match as a
    unit on word boundaries. Supplied via extra_tokens since the real
    private SKU is kept out of the public test tree."""
    root = _mk_plugin(tmp_path, {
        "programs/widget.py": "x = 'EXAMPLE_TESTER tester'",
    })
    v, findings = audit(root, extra_tokens=["EXAMPLE_TESTER"])
    assert v == "FAIL"
    assert any(f.token == "EXAMPLE_TESTER" for f in findings)


def test_substring_in_word_not_match(tmp_path: Path) -> None:
    """`EXAMPLE_CHIPsomething` should NOT match — word boundary required."""
    root = _mk_plugin(tmp_path, {
        "programs/widget.py": "x = EXAMPLE_CHIPsomething",
    })
    v, findings = audit(root)
    # Word boundary excludes alphanumeric continuation; this should pass
    # because the token is followed by `something` (alpha continuation).
    assert v == "PASS", findings


def test_vacuous_on_missing_root(tmp_path: Path) -> None:
    v, findings = audit(tmp_path / "nonexistent")
    assert v == "VACUOUS_PASS"
