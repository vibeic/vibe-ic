"""Tests for source_chip_agnostic_check — the strengthened chip-AGNOSTIC gate.

NDA: this test file must NOT contain a literal foundry SKU (the guard would
catch its OWN test). Real NDA tokens are reconstructed at runtime from the
encoded store in `_commercial_pdk` so detection can still be exercised.
"""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

import _commercial_pdk as _cpdk
from programs.source_chip_agnostic_check import audit

# Real NDA tokens, decoded at runtime — never written as literals here.
_NDA = _cpdk.nda_tokens()
_SKU = next(t for t in _NDA if t.lower().startswith("m18"))     # process SKU
_FOUNDRY = next(t for t in _NDA if t.lower().startswith("hp"))  # foundry product
_PLUGIN_ROOT = Path(__file__).resolve().parents[2]  # plugins/vibe-ic


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


def test_pytest_runtime_cache_is_not_source_or_part_of_the_denominator(tmp_path: Path) -> None:
    """Running pytest first must not change the commit-derived NDA census."""
    root = _mk_plugin(tmp_path, {
        "programs/widget.py": "x = 1\n",
        ".pytest_cache/README.md": f"runtime cache {_FOUNDRY}\n",
    })
    v, findings = audit(root)
    assert v == "PASS", findings
    from programs import source_chip_agnostic_check as check
    assert check.SCAN_CENSUS["nda_files_found"] == 1, check.SCAN_CENSUS


def test_chip_sku_in_program_caught(tmp_path: Path) -> None:
    # EXAMPLE_CHIP is a stand-in SKU token supplied via extra_tokens so the
    # gate exercises its forbidden-token matching on a program-file comment.
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


def test_substring_in_word_not_match(tmp_path: Path) -> None:
    """`EXAMPLE_CHIPsomething` should NOT match — word boundary required for the
    generic forbidden-token panel."""
    root = _mk_plugin(tmp_path, {
        "programs/widget.py": "x = EXAMPLE_CHIPsomething",
    })
    v, findings = audit(root)
    assert v == "PASS", findings


def test_vacuous_on_missing_root(tmp_path: Path) -> None:
    v, findings = audit(tmp_path / "nonexistent")
    assert v == "VACUOUS_PASS"


# ---------------------------------------------------------------------------
# STRICT NDA contract (v1.4.62): the commercial foundry SKU is in the DEFAULT
# panel (no extra_tokens needed) AND has NO allowlist — a literal token
# anywhere, INCLUDING under programs/tests/ and inside functional code lines,
# FAILS. Only the encoded home `_commercial_pdk.py` is exempt.
# ---------------------------------------------------------------------------
def test_nda_sku_in_default_panel(tmp_path: Path) -> None:
    """A fresh prose leak of the commercial SKU is caught WITHOUT extra_tokens."""
    root = _mk_plugin(tmp_path, {
        "programs/widget.py": f"# tuned for {_FOUNDRY} metal stack\nx = 1\n",
    })
    v, findings = audit(root)
    assert v == "FAIL"
    assert any(f.rule == "FORBIDDEN_NDA_SKU" for f in findings)


def test_nda_sku_substring_caught(tmp_path: Path) -> None:
    """Substring occurrences (e.g. `<SKU>_typ.lib`) are caught — the guard is as
    strict as `git grep`, not merely word-bounded."""
    root = _mk_plugin(tmp_path, {
        "programs/foo.py": f'lib = "{_SKU}_typ.lib"\n',
    })
    v, findings = audit(root)
    assert v == "FAIL"
    assert any(f.rule == "FORBIDDEN_NDA_SKU" for f in findings)


def test_nda_sku_in_tests_dir_not_allowlisted(tmp_path: Path) -> None:
    """The old allowlist exempted programs/tests/. The strict NDA panel does
    NOT — a literal SKU in a test file FAILS."""
    root = _mk_plugin(tmp_path, {
        "programs/tests/test_x.py": f'# fixture: {_FOUNDRY}\n',
    })
    v, findings = audit(root)
    assert v == "FAIL"
    assert any(f.rule == "FORBIDDEN_NDA_SKU" for f in findings)


def test_nda_sku_in_functional_code_line_not_allowlisted(tmp_path: Path) -> None:
    """The old chip_deny_allow.txt line-allowlist sanctioned specific
    PDK-discovery source lines. It is GONE — such a line now FAILS, forcing the
    config-driven path."""
    root = _mk_plugin(tmp_path, {
        "programs/fault_atpg_run.py": f'"{_SKU}": {{\n',
    })
    v, findings = audit(root)
    assert v == "FAIL"


def test_encoded_home_is_exempt(tmp_path: Path) -> None:
    """The one sanctioned home carries only base64 forms; even if a token
    literal appeared there it is exempt (its real content never has one)."""
    root = _mk_plugin(tmp_path, {
        "programs/_commercial_pdk.py": f"# encoded home stand-in {_FOUNDRY}\n",
    })
    v, findings = audit(root)
    # No NDA finding from the exempt home.
    assert not any(f.rule == "FORBIDDEN_NDA_SKU" for f in findings)


def test_real_plugin_tree_has_zero_nda_literals() -> None:
    """The guard's headline contract: the REAL plugin tree contains no literal
    NDA foundry SKU (except the encoded home) — audit's NDA pass is clean."""
    from programs.source_chip_agnostic_check import _scan_nda
    findings = _scan_nda(_PLUGIN_ROOT)
    assert findings == [], [(f.file, f.line, f.token) for f in findings[:20]]


def test_git_grep_sku_is_zero() -> None:
    """Hard gate mirror: `git grep <SKU family>` over plugins/vibe-ic returns 0.
    The pattern is reconstructed from the encoded tokens (no literal here)."""
    # Build an ERE alternation from the decoded tokens (substring, case-insens).
    alt = "|".join(sorted({t for t in _NDA}, key=len, reverse=True))
    repo_root = Path(__file__).resolve().parents[4]  # .../vibe-ic-marketplace
    try:
        proc = subprocess.run(
            ["git", "grep", "-icE", alt, "--", "plugins/vibe-ic"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("git not available")
    # `git grep -c` prints one `path:count` line per matching file; exit 1 == no
    # matches. Any output means a literal SKU leaked back in.
    assert proc.stdout.strip() == "", (
        "literal SKU leaked into plugin source:\n" + proc.stdout)
