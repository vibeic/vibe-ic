"""v0.3.6 — #504: blindness_audit path extraction truncated at SPACE for
QUOTED paths. A legitimate allowed-glob prompt read under a
space-bearing dataset directory —

    cat ".../Miscellaneous/Signal generation/.../design_description.txt"

— was extracted as the truncated prefix `.../Miscellaneous/Signal`,
mis-matched the allowed glob, and the whole run was refused at the
scoring front door. #480 fixed quote-TERMINATION (don't bleed past a
closing quote); this is the dual: quote-PROTECTION (a quoted token IS
one path, spaces included).

Root causes pinned here:
  * the disk-truth ladder's probe kept the glued shell trailer (`";`)
    so the real file never EXISTed as written and the ladder shrank
    PAST the in-name space;
  * no quote-context rule existed at all (host-independent case).

Fixtures embed the REAL flagged command line VERBATIM (from the real
run's transcript) per the #501 verbatim doctrine — with the dataset
root swapped to a tmp tree, since committed tests must stay
dataset-AGNOSTIC. Both directions are pinned: (a) quoted allowed-glob
read under a space dir → NOT flagged; (b) quoted DIRECTORY access under
the same space dir → STILL flagged (real violations must not leak).
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import blindness_audit as BA  # noqa: E402

ALLOWED = ["design_description.txt"]


def _mk_dataset(tmp_path: Path) -> Path:
    # space-bearing directory layout mirroring the real upstream dataset
    # shape ("<category>/<problem name with space>/<problem>/<prompt>")
    ds = tmp_path / "dataset"
    d = ds / "Miscellaneous" / "Signal generation" / "signal_generator"
    d.mkdir(parents=True)
    (d / "design_description.txt").write_text("spec\n")
    (d / "verified_signal_generator.v").write_text("module m; endmodule\n")
    return ds


def _audit(line: str, ds: Path) -> list:
    return BA.audit_text(line, ds, ALLOWED, "t.jsonl")


# ── (a) the REAL false-positive shape: quoted allowed read, space dir ─

def test_quoted_allowed_read_under_space_dir_not_flagged(tmp_path):
    ds = _mk_dataset(tmp_path)
    # REAL command shape, verbatim modulo dataset root (transcript
    # agent_batch04 line 30 of the real run):
    line = (f'cat "{ds}/Miscellaneous/Signal generation/'
            f'signal_generator/design_description.txt"; echo exit=$?')
    assert _audit(line, ds) == []


def test_quoted_allowed_read_nonexistent_host_path_not_flagged(tmp_path):
    # quote-context rule is host-INDEPENDENT: even when the file does
    # not exist on the auditing host, the quoted span is one token.
    ds = _mk_dataset(tmp_path)
    line = (f'cat "{ds}/Other category/Frequency divider/'
            f'freq_div/design_description.txt"')
    assert _audit(line, ds) == []


def test_single_quoted_allowed_read_not_flagged(tmp_path):
    ds = _mk_dataset(tmp_path)
    line = (f"cat '{ds}/Miscellaneous/Signal generation/"
            f"signal_generator/design_description.txt'")
    assert _audit(line, ds) == []


def test_tool_use_json_command_field_not_flagged(tmp_path):
    # the real transcript shape: the command lives in a tool_use JSON
    # envelope's input.command field.
    ds = _mk_dataset(tmp_path)
    rec = {"message": {"content": [{"type": "tool_use", "name": "Bash",
           "input": {"command":
                     f'cat "{ds}/Miscellaneous/Signal generation/'
                     f'signal_generator/design_description.txt"; '
                     f'echo exit=$?'}}]}}
    assert _audit(json.dumps(rec), ds) == []


# ── (b) real violations under the SAME space dir must still flag ─────

def test_quoted_directory_listing_still_flagged(tmp_path):
    ds = _mk_dataset(tmp_path)
    line = f'ls "{ds}/Miscellaneous/Signal generation/"'
    found = _audit(line, ds)
    assert found and found[0]["kind"] == "dataset-file-access"


def test_quoted_oracle_read_under_space_dir_still_flagged(tmp_path):
    # reading the reference solution next to the allowed prompt is the
    # canonical violation — the space dir must not become a blind spot.
    ds = _mk_dataset(tmp_path)
    line = (f'cat "{ds}/Miscellaneous/Signal generation/'
            f'signal_generator/verified_signal_generator.v"')
    found = _audit(line, ds)
    assert found and found[0]["kind"] == "dataset-file-access"


def test_unquoted_existing_path_with_trailer_resolves(tmp_path):
    # disk-truth ladder hardening: an UNQUOTED existing path whose tail
    # glues a shell trailer (`";` / `;`) now strips the trailer before
    # the existence probe instead of shrinking past the in-name space.
    ds = _mk_dataset(tmp_path)
    p = (f"{ds}/Miscellaneous/Signal generation/"
         f"signal_generator/design_description.txt")
    rel = BA._extract_rel(f"cat {p};", len(str(ds)) + 4, str(ds))
    assert rel.endswith("design_description.txt")
