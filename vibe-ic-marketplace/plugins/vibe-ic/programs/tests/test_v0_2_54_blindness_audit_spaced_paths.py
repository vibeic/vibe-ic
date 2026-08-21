"""v0.2.54 blindness-audit spaced-path regressions.

Pins the #425 fix (ORGANIC-20260606-blindness-audit-space-path-truncation):
the V1 path extraction used a space-free charclass tail after the dataset
root, so a dataset whose directory names contain spaces
("…/Misc category/Frequency divider/…") truncated at the first space — the
ALLOWED per-design spec read then mis-matched the allowed glob and the
audit hard-blocked scoring of a fully blind run. New resolution ladder in
`_extract_rel`: disk-truth longest-prefix (shrink right-to-left at
whitespace until the path exists), then the `READ <path>`-to-EOL transcript
convention, then the legacy space-free tail. V1 findings now also carry the
resolved `allowed_globs` so a failure names the bench's actual allow-list.

chip-AGNOSTIC: fixtures build synthetic dataset trees under tmp_path.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import blindness_audit as ba  # noqa: E402

ALLOWED = ["design_description.txt"]


def _mk(tmp_path: Path, rel: str) -> Path:
    p = tmp_path / "ds" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")
    return p


# ── the filed failure: spaced dirs + ALLOWED spec read must PASS ──────────

def test_spaced_path_allowed_spec_read_passes(tmp_path):
    spec = _mk(tmp_path, "Misc category/Frequency divider/uut/design_description.txt")
    text = f"READ {spec}\n"
    fs = ba.audit_text(text, tmp_path / "ds", ALLOWED, "t1.md")
    assert fs == [], fs


def test_spaced_path_with_trailing_annotation_passes(tmp_path):
    # disk-truth shrinking strips "(123 bytes)"-style trailers
    spec = _mk(tmp_path, "Misc category/Counter bank/uut/design_description.txt")
    text = f"READ {spec} (1234 bytes)\n"
    assert ba.audit_text(text, tmp_path / "ds", ALLOWED, "t2.md") == []


def test_spaced_path_inside_cmd_with_flags_passes(tmp_path):
    # a CMD line carries flags after the path — shrinking must stop at the
    # real on-disk path, not swallow the flags
    spec = _mk(tmp_path, "Misc category/Adder tree/uut/design_description.txt")
    text = f"CMD cat {spec} -n\n"
    assert ba.audit_text(text, tmp_path / "ds", ALLOWED, "t3.md") == []


# ── true violation under a spaced path: FAIL with the FULL path ───────────

def test_spaced_path_true_violation_reports_full_path(tmp_path):
    tb = _mk(tmp_path, "Misc category/Frequency divider/uut/testbench.v")
    text = f"READ {tb}\n"
    fs = ba.audit_text(text, tmp_path / "ds", ALLOWED, "t4.md")
    assert len(fs) == 1
    assert fs[0]["kind"] == "dataset-file-access"
    assert fs[0]["path"] == str(tb)              # FULL untruncated path
    assert "test/ref/golden" in fs[0]["class"]
    assert fs[0]["allowed_globs"] == ALLOWED     # resolved allow-list surfaced


# ── ladder fallbacks ───────────────────────────────────────────────────────

def test_read_line_convention_when_path_not_on_disk(tmp_path):
    # transcript from another host: file absent locally → READ-to-EOL rule
    ds = tmp_path / "ds"; ds.mkdir()
    text = f"READ {ds}/Misc category/Divider farm/uut/design_description.txt\n"
    assert ba.audit_text(text, ds, ALLOWED, "t5.md") == []


def test_legacy_spacefree_prose_mention_still_flags(tmp_path):
    # prose mention (no READ marker, not on disk): legacy tail still catches
    # a space-free oracle path exactly as before
    ds = tmp_path / "ds"; ds.mkdir()
    text = f"the file {ds}/uut/golden_ref.v holds the answer\n"
    fs = ba.audit_text(text, ds, ALLOWED, "t6.md")
    assert len(fs) == 1
    assert fs[0]["path"].endswith("uut/golden_ref.v")


def test_spacefree_allowed_read_unchanged(tmp_path):
    spec = _mk(tmp_path, "prob_001/design_description.txt")
    text = f"READ {spec}\n"
    assert ba.audit_text(text, tmp_path / "ds", ALLOWED, "t7.md") == []
