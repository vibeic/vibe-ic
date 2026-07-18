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


# ---------------------------------------------------------------------------
# Commercial-PDK SKU: the deny-list was BLIND to it (chip_deny_list.txt didn't
# list commercial_pdk/commercial_pdk), which is why ~90 SKU leaks sat undetected. These verify
# the token is now in the DEFAULT panel AND that the line-EXACT allowlist
# (chip_deny_allow.txt) suppresses ONLY the sanctioned discovery literals while
# staying fail-safe against a fresh prose leak in the very same file.
# ---------------------------------------------------------------------------
def test_commercial_sku_now_in_default_panel(tmp_path: Path) -> None:
    """A fresh prose leak of the commercial SKU is caught WITHOUT extra_tokens
    (previously the guard's default panel was blind to it)."""
    root = _mk_plugin(tmp_path, {
        "programs/widget.py": "# tuned for commercial_pdk metal stack\nx = 1\n",
    })
    v, findings = audit(root)
    assert v == "FAIL"
    assert any(f.token.lower() == "commercial_pdk" for f in findings)


def test_line_allow_suppresses_sanctioned_discovery_literal(tmp_path: Path) -> None:
    """The exact load-bearing PDK-discovery line registered in
    chip_deny_allow.txt is suppressed (the plugin must name the real PDK)."""
    root = _mk_plugin(tmp_path, {
        "programs/fault_atpg_run.py": '"commercial_pdk": {\n',
    })
    v, findings = audit(root)
    assert v == "PASS", findings


def test_line_allow_is_fail_safe_new_prose_leak_still_caught(tmp_path: Path) -> None:
    """A NEW prose leak in the SAME allow-listed file is a DIFFERENT line, so it
    is still caught — the allowlist is line-EXACT, never file-level."""
    root = _mk_plugin(tmp_path, {
        "programs/fault_atpg_run.py":
            '"commercial_pdk": {\n'                       # sanctioned -> allowed
            '# new leak: retuned for commercial_pdk corner\n',  # prose -> caught
    })
    v, findings = audit(root)
    assert v == "FAIL"
    assert any(f.line == 2 for f in findings)


def test_line_allow_near_miss_not_blanket_allowed(tmp_path: Path) -> None:
    """A line that only RESEMBLES a sanctioned line (trailing text appended) is
    NOT suppressed — proves exact-match keying, not substring/prefix."""
    root = _mk_plugin(tmp_path, {
        "programs/fault_atpg_run.py": '"commercial_pdk": {  # sneaky\n',
    })
    v, findings = audit(root)
    assert v == "FAIL"
