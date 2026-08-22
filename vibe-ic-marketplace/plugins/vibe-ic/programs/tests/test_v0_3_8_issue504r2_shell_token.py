"""v0.3.8 — #504 ROUND-2: two further blindness_audit false-positive
shapes survived the round-1 fix on the REAL 9-transcript artifact (11
flags, all false):

  (1) dead-branch OR-fallback (10×): ``cat "<ds>/.../prompt.txt"
      2>/dev/null || cat "<ds>/.../prompt.md"`` — the agent reads the
      allowed ``.txt``; the ``.md`` twin (the blind-instructions
      documented fallback NAME) does not even exist in the dataset, yet
      its literal token was flagged;
  (2) variable assignment (1×): ``B=<ds>/<category-dir>`` inside a
      ``declare -A`` staging block — pure RHS storage; every consumption
      is ``"$B/.../design_description.txt"`` (allowed).

Fix: shell-token semantics — `_is_assignment_rhs` (storage, not access;
round-1 doctrine's `SRC=` shape generalised to all assignment forms) and
`_is_or_fallback_family_twin` (right branch of `A || B` whose LEFT
branch references an allowed file and whose basename shares the
name-STEM of an allowed glob).

Per the #501 verbatim doctrine the fixtures below embed the REAL
transcript command lines BYTE-FOR-BYTE (provenance: the real run's
agent_batch01.jsonl line 20 and agent_batch03.jsonl line 41), with only
the dataset/work roots mapped onto the tmp fixture tree at audit time.
Negative directions are pinned too: a non-family right branch (oracle
read) still flags, a twin with a non-allowed left branch still flags,
and a direct oracle read still flags.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import blindness_audit as BA  # noqa: E402

ALLOWED = ["design_description.txt"]

# Roots as they appear in the REAL transcript lines (mapped to tmp at
# audit time so the committed test is host/dataset-independent).
_REAL_DS = "/home/testuser/AI_IC_design/_extbench/RTLLM"
_REAL_WORK = "/home/testuser/AI_IC_design/rtllm_cleanroom_v034/work"

# ── agent_batch01.jsonl:20 — VERBATIM (dead-branch OR-fallback) ──────
_REAL_LINE_B01_20 = (
    'cat "/home/testuser/AI_IC_design/_extbench/RTLLM/Arithmetic/'
    'Multiplier/multi_16bit/design_description.txt" 2>/dev/null || '
    'cat "/home/testuser/AI_IC_design/_extbench/RTLLM/Arithmetic/'
    'Multiplier/multi_16bit/design_description.md"; echo exit=$?'
)

# ── agent_batch03.jsonl:41 — VERBATIM (declare -A staging block) ─────
_REAL_LINE_B03_41 = """set -e
declare -A M=(
 [freq_div]="Frequency divider/freq_div"
 [freq_divbyeven]="Frequency divider/freq_divbyeven"
 [freq_divbyfrac]="Frequency divider/freq_divbyfrac"
 [freq_divbyodd]="Frequency divider/freq_divbyodd"
 [calendar]="Others/calendar"
 [edge_detect]="Others/edge_detect"
 [parallel2serial]="Others/parallel2serial"
 [pulse_detect]="Others/pulse_detect"
 [serial2parallel]="Others/serial2parallel"
 [synchronizer]="Others/synchronizer"
)
B=/home/testuser/AI_IC_design/_extbench/RTLLM/Miscellaneous
W=/home/testuser/AI_IC_design/rtllm_cleanroom_v034/work
for leaf in "${!M[@]}"; do
  src="$B/${M[$leaf]}/design_description.txt"
  cat "$src" > "$W/$leaf/input/phase1_prompt.md"
  cat "$src" > "$W/$leaf/input/docs/design_description.md"
done
echo "---written---"
for leaf in freq_div freq_divbyeven freq_divbyfrac freq_divbyodd calendar edge_detect parallel2serial pulse_detect serial2parallel synchronizer; do
  printf "%-16s prompt=%s docs=%s\\n" "$leaf" $(wc -c < "$W/$leaf/input/phase1_prompt.md") $(wc -c < "$W/$leaf/input/docs/design_description.md")
done
echo exit=$?"""


def _mk_dataset(tmp_path: Path) -> Path:
    ds = tmp_path / "dataset"
    d = ds / "Arithmetic" / "Multiplier" / "multi_16bit"
    d.mkdir(parents=True)
    (d / "design_description.txt").write_text("spec\n")
    (d / "verified_multi_16bit.v").write_text("module m; endmodule\n")
    (ds / "Miscellaneous" / "Frequency divider" / "freq_div").mkdir(
        parents=True)
    return ds


def _audit(line: str, ds: Path) -> list:
    return BA.audit_text(line, ds, ALLOWED, "t.jsonl")


# ── (1) the REAL dead-branch OR-fallback shape ───────────────────────

def test_real_or_fallback_md_twin_not_flagged(tmp_path):
    ds = _mk_dataset(tmp_path)
    line = _REAL_LINE_B01_20.replace(_REAL_DS, str(ds))
    assert _audit(line, ds) == []


def test_or_fallback_nonfamily_right_branch_still_flagged(tmp_path):
    # negative: same `A || B` shape, but the right branch reads the
    # ORACLE — not a name-family twin → must still flag.
    ds = _mk_dataset(tmp_path)
    line = (f'cat "{ds}/Arithmetic/Multiplier/multi_16bit/'
            f'design_description.txt" 2>/dev/null || '
            f'cat "{ds}/Arithmetic/Multiplier/multi_16bit/'
            f'verified_multi_16bit.v"')
    found = _audit(line, ds)
    assert found and found[0]["kind"] == "dataset-file-access"


def test_or_fallback_without_allowed_left_still_flagged(tmp_path):
    # negative: the twin name on the right does NOT get a pass when the
    # LEFT branch is not an allowed read.
    ds = _mk_dataset(tmp_path)
    line = (f'cat "{ds}/Arithmetic/Multiplier/multi_16bit/'
            f'verified_multi_16bit.v" 2>/dev/null || '
            f'cat "{ds}/Arithmetic/Multiplier/multi_16bit/'
            f'design_description.md"')
    found = _audit(line, ds)
    # the oracle read on the left is one violation; the .md twin without
    # an allowed left is a second.
    assert len(found) == 2


def test_statement_separator_breaks_the_pair(tmp_path):
    # `A || true; cat B.md` — the `;` ends the fallback pair, so the
    # later .md access is NOT the fallback's right branch → flags.
    ds = _mk_dataset(tmp_path)
    line = (f'cat "{ds}/Arithmetic/Multiplier/multi_16bit/'
            f'design_description.txt" || true; '
            f'cat "{ds}/Arithmetic/Multiplier/multi_16bit/'
            f'design_description.md"')
    found = _audit(line, ds)
    assert len(found) == 1


# ── (2) the REAL declare -A / assignment shape ───────────────────────

def test_real_declare_block_assignment_not_flagged(tmp_path):
    ds = _mk_dataset(tmp_path)
    line = (_REAL_LINE_B03_41
            .replace(_REAL_DS, str(ds))
            .replace(_REAL_WORK, str(tmp_path / "work")))
    assert _audit(line, ds) == []


def test_simple_assignment_not_flagged(tmp_path):
    ds = _mk_dataset(tmp_path)
    for stem in (f"SRC={ds}/Miscellaneous",
                 f'export ROOT="{ds}/Arithmetic"',
                 f"local d={ds}/Miscellaneous"):
        assert _audit(stem, ds) == [], stem


def test_direct_oracle_read_still_flagged(tmp_path):
    # the assignment exemption must not soften direct accesses.
    ds = _mk_dataset(tmp_path)
    line = (f'cat "{ds}/Arithmetic/Multiplier/multi_16bit/'
            f'verified_multi_16bit.v"')
    found = _audit(line, ds)
    assert found and found[0]["kind"] == "dataset-file-access"


def test_directory_listing_still_flagged(tmp_path):
    # round-1 negative stays pinned: a directory access (not an
    # assignment) under a space-bearing dir still flags.
    ds = _mk_dataset(tmp_path)
    line = f'ls "{ds}/Miscellaneous/Frequency divider/"'
    found = _audit(line, ds)
    assert found and found[0]["kind"] == "dataset-file-access"
