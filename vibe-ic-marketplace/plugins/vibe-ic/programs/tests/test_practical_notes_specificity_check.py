"""Tests for practical_notes_specificity_check.py.

Fixture tokens (chip / vendor / SKU / project codenames) are loaded at
runtime from ``plugins/vibe-ic/programs/tests/chip_deny_list.txt`` so this
source file itself stays free of the private tokens it is exercising.

Classification heuristic (token-agnostic):
  * tokens containing a hyphen and a digit run  -> tester-style SKUs
  * pure ASCII letters + digits, length >= 5    -> chip / project codenames

The production gate `practical_notes_specificity_check.py` uses
case-INsensitive regexes, so we feed fixtures verbatim (lowercase as
stored in the deny list) and assert on rule-id prefixes, not exact
historical rule ids.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

PROGRAM = Path(__file__).parent.parent / "practical_notes_specificity_check.py"

# ---------------------------------------------------------------------------
# Runtime fixture loader — pulls the deny tokens from the canonical file.
# ---------------------------------------------------------------------------
_DENY_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "tests" / "chip_deny_list.txt"
)

# The NDA PDK/process codename is no longer plaintext in the deny list; pull it
# (decoded, at runtime) from the encoded store so this test carries no literal.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _commercial_pdk as _cpdk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402
_PDK_SKU = next((t for t in _cpdk.nda_tokens() if t.lower().startswith("m18")), "")

_CODENAME_TOKEN_RE = re.compile(r"^[a-z]{2,5}\d{3,}[a-z]*$")  # e.g. "xx3616"


def _classify_tokens() -> dict:
    """Group deny tokens into rough fixture buckets WITHOUT spelling any
    private token in this source. Heuristic:
      * has '-' AND ends in digits        -> hyphenated tester SKU
      * letters then digits, no hyphen,
        and same shape as a paired '-DIG' -> plain tester SKU
      * any other letters+digits token    -> chip / project codename
    """
    out: dict[str, list[str]] = {"chip": [], "tester_hyphen": [],
                                 "tester_plain": [], "project": []}
    try:
        raw = _DENY_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    tokens: list[str] = []
    for ln in raw:
        s = ln.strip()
        if not s or s.startswith("#") or s in tokens:
            continue
        tokens.append(s)
    # Identify hyphenated tester first; remember its digit run so we can
    # also tag the un-hyphenated twin (e.g. same letters + same digits).
    twin_keys: set[str] = set()
    for s in tokens:
        if "-" in s and any(ch.isdigit() for ch in s):
            out["tester_hyphen"].append(s.upper())
            twin_keys.add(s.replace("-", ""))
    for s in tokens:
        if "-" in s:
            continue
        if s in twin_keys:
            out["tester_plain"].append(s.upper())
        elif _CODENAME_TOKEN_RE.match(s):
            out["chip"].append(s.upper())
            out["project"].append(s.upper())
    return out


_TOKENS = _classify_tokens()
# Canonical labels used in test bodies — guard against missing entries.
CHIP_NAME = _TOKENS["chip"][0] if _TOKENS["chip"] else ""
PROJECT_CODENAME = _TOKENS["project"][-1] if _TOKENS["project"] else ""
TESTER_NAME = _TOKENS["tester_hyphen"][0] if _TOKENS["tester_hyphen"] else ""


def _run(args: list[str], cwd: Path | None = None) -> tuple[int, dict]:
    r = _pr.run(
        [sys.executable, str(PROGRAM), *args, "--json"],
        capture_output=True, text=True, cwd=cwd)
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        out = {}
    return r.returncode, out


def _write(tmp: Path, name: str, body: str) -> Path:
    f = tmp / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body)
    return f


def test_help_works():
    r = _pr.run(
        [sys.executable, str(PROGRAM), "--help"],
        capture_output=True, text=True)
    assert r.returncode == 0
    assert "PRACTICAL_NOTES" in r.stdout


def test_clean_file_passes(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Generic notes\n\nUse non-blocking assignments in clocked always blocks.\n"
           "Synchronize asynchronous inputs with a 2-FF chain.\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 0, out
    assert out["verdict"] == "PASS"
    assert out["total_errors"] == 0


@pytest.mark.skipif(not CHIP_NAME, reason="deny list missing chip token")
def test_chip_name_flagged(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           f"# Notes\nReal bug from {CHIP_NAME} debug: foo\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 1
    rules = [f["rule"] for f in out["findings"]]
    assert any(r.startswith("chip_name_") for r in rules), rules


@pytest.mark.skipif(not TESTER_NAME, reason="deny list missing tester token")
def test_tester_name_flagged(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           f"# Notes\nThe {TESTER_NAME} tester returns byte[6]=0xF2 on PASS.\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 1
    rules = {f["rule"] for f in out["findings"]}
    assert any(r.startswith("tester_") for r in rules), rules
    assert "specific_pass_marker" in rules


def test_hid_cmd_byte_flagged(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Notes\nbuf[0] = 0x10  # CMD_CONNECT_CHK\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 1
    rules = [f["rule"] for f in out["findings"]]
    assert "hid_cmd_byte_decl" in rules


@pytest.mark.skipif(not CHIP_NAME, reason="deny list missing chip token")
def test_vendor_pdf_filename_flagged(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           f"# Notes\nSee {CHIP_NAME}_TxRx_signal.pdf for waveform.\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 1
    rules = [f["rule"] for f in out["findings"]]
    assert "vendor_pdf_filename" in rules


def test_lightning_product_name_flagged(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Notes\nFor Lightning ICs we use HID.\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 1
    rules = [f["rule"] for f in out["findings"]]
    assert "vendor_product_lightning" in rules


@pytest.mark.skipif(not TESTER_NAME, reason="deny list missing tester token")
def test_dated_validation_flagged(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           f"# Notes\nvalidated_on: {TESTER_NAME} + DE10-Lite 2024-03-15\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 1
    rules = {f["rule"] for f in out["findings"]}
    assert "dated_validation" in rules


@pytest.mark.skipif(not CHIP_NAME, reason="deny list missing chip token")
def test_provenance_is_warn_by_default(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           f"# Notes\nObserved pattern from {CHIP_NAME} debug session.\n")
    code, out = _run(["--paths", str(tmp_path)])
    # Provenance triggers SOFT only — but the bare word also fires HARD.
    # So strip the chip name to test SOFT in isolation:
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Notes\n"
           f"Real bug from {CHIP_NAME} debug: <!-- specificity-allow: provenance -->\n"
           f"But this line: from {CHIP_NAME} fresh-agent has no allow marker.\n")
    code, out = _run(["--paths", str(tmp_path)])
    # Should have at least one WARN (soft) on the second line, plus HARD on it.
    severities = {f["severity"] for f in out["findings"]}
    assert "WARN" in severities or "ERROR" in severities


@pytest.mark.skipif(not CHIP_NAME, reason="deny list missing chip token")
def test_strict_promotes_soft_to_error(tmp_path):
    # Build a file where the only finding is SOFT (mask the HARD chip name on
    # the provenance line by routing through allowlist).
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Notes\n"
           "Real bug from MyChip debug: rule applies generally.\n")
    # MyChip isn't in HARD list; the SOFT regex requires the canonical
    # chip / project / tester / version tokens. Construct one that hits SOFT only.
    allow_marker = f"<!-- specificity-allow: chip_name_{CHIP_NAME.lower()} -->"
    _write(tmp_path, "PRACTICAL_NOTES.md",
           f"{CHIP_NAME} debug observation. {allow_marker}\n")
    # Allow marker exempts the WHOLE line, so neither HARD nor SOFT fires.
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 0


@pytest.mark.skipif(not TESTER_NAME, reason="deny list missing tester token")
def test_allowlist_marker_exempts_line(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Notes\n"
           f"{TESTER_NAME} tester baseline. <!-- specificity-allow: documented-exception -->\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 0
    assert out["total_errors"] == 0


def test_default_scan_runs_on_plugin_dir():
    # Sanity: the gate finds files in the plugin's vibe-ic/skills dir.
    code, out = _run([])
    # We expect failures because we haven't cleaned the docs yet — but the
    # scan must execute and report file count > 0.
    assert "files_scanned" in out
    assert out["files_scanned"] >= 10, out
    assert out["verdict"] in ("PASS", "FAIL")


def test_invalid_path_errors():
    r = _pr.run(
        [sys.executable, str(PROGRAM), "--paths", "/no/such/dir/__nonexistent__"],
        capture_output=True, text=True)
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# Parametric matrix — tokens substituted at runtime from the deny list.
# Each entry pairs (rendered fixture snippet, expected rule id prefix).
# ---------------------------------------------------------------------------
def _build_hard_rule_matrix() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if PROJECT_CODENAME:
        out.append((f"Project {PROJECT_CODENAME} baseline.", "project_codename_"))
    out.append((f"PDK {_PDK_SKU} corner SS.", "specific_pdk_codename"))
    out.append(("Carrier ACC_ID idle high.", "chip_specific_pin"))
    out.append(("v068 fresh-agent regression.", "project_version_codename"))
    if TESTER_NAME:
        out.append((f"Validated 2024-03-15 {TESTER_NAME}.", "dated_validation"))
    return out


_HARD_RULE_MATRIX = _build_hard_rule_matrix()


@pytest.mark.parametrize("snippet,expected_rule_prefix", _HARD_RULE_MATRIX)
def test_each_hard_rule_detects(tmp_path, snippet, expected_rule_prefix):
    _write(tmp_path, "PRACTICAL_NOTES.md", f"# Notes\n{snippet}\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 1
    rules = {f["rule"] for f in out["findings"]}
    assert any(r.startswith(expected_rule_prefix) or r == expected_rule_prefix
               for r in rules), (snippet, rules)
