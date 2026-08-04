"""v1.6.68 — LVS was unrunnable at random because magic's DEF reader aborts
on a DEF BLOCKAGES entry that names no layer.

Field observation (real Phase-3 run, multi-supply ASIC): the routed DEF held

    BLOCKAGES 1 ;
        - PLACEMENT + SOFT + COMPONENT <inst> RECT ( x1 y1 ) ( x2 y2 ) ;
    END BLOCKAGES

A `- PLACEMENT` entry is a directive to the PLACER; it names no layer and
carries no conductor. Magic has nothing to bind the RECT to, prints

    LEF read, Line NNNN (Error): No layer defined for RECT.

and then terminates the DEF read PART OF THE TIME. Measured on the SAME
byte-identical DEF with the SAME command: 2 of 5 runs produced a netlist,
3 of 5 produced none. With the layer-less entry removed: 5 of 5 produced a
netlist, and every one of them was byte-identical (same md5) to the netlist
the intact DEF produced on the runs where it happened to survive — i.e. the
removal is loss-free for extraction, which is what makes it a fix and not a
workaround.

Two independent defects, pinned separately:

  D1  the runner fed magic the signed-off DEF as-is, so a design that uses a
      placement blockage (a routine macro-halo / keep-out) had a ~60 %
      chance of no LVS at all;
  D2  the command is `magic ... | tee log`, whose exit status is TEE's. Magic
      could die and the runner still saw rc=0, so the failure was reported as
      "produced no extracted netlist (rc=0)" — a message that quietly asserts
      the tool was fine.

chip-AGNOSTIC: DEF syntax + shell semantics only.
"""
import io
import re
import sys
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase3_one_shot_runner as P3  # noqa: E402

_P3_SRC = (Path(P3.__file__)).read_text()


def _code_only(src: str) -> str:
    """Source with COMMENT tokens blanked out.

    Injection-verified the hard way: the first cut of the pipefail and
    sentinel pins searched the RAW source, and both survived having the
    actual code deleted — because the explanatory comment right above still
    contained the literal they were looking for. A pin that a comment can
    satisfy pins nothing. These two assertions therefore run against code
    with the prose removed."""
    lines = src.splitlines(keepends=True)
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln))
    buf = list(src)
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type != tokenize.COMMENT:
            continue
        a = starts[tok.start[0] - 1] + tok.start[1]
        b = starts[tok.end[0] - 1] + tok.end[1]
        for k in range(a, b):
            buf[k] = " "
    return "".join(buf)


_P3_CODE = _code_only(_P3_SRC)

_DEF_MIXED = """\
VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
BLOCKAGES 3 ;
    - LAYER MET1 RECT ( 100 200 ) ( 300 400 ) ;
    - PLACEMENT + SOFT + COMPONENT u_otp.u_macro RECT ( 10560 305780 )
      ( 426560 458780 ) ;
    - LAYER MET2 RECT ( 5 6 ) ( 7 8 ) ;
END BLOCKAGES
SPECIALNETS 1 ;
    - VDD ( * VPWR ) + USE POWER ;
END SPECIALNETS
END DESIGN
"""

_DEF_ONLY_PLACEMENT = """\
VERSION 5.8 ;
DESIGN chip_top ;
BLOCKAGES 1 ;
    - PLACEMENT + SOFT + COMPONENT u_otp.u_macro RECT ( 1 2 ) ( 3 4 ) ;
END BLOCKAGES
SPECIALNETS 1 ;
    - VDD ( * VPWR ) + USE POWER ;
END SPECIALNETS
END DESIGN
"""

_DEF_ALL_LAYER = """\
VERSION 5.8 ;
DESIGN chip_top ;
BLOCKAGES 2 ;
    - LAYER MET1 RECT ( 100 200 ) ( 300 400 ) ;
    - LAYER MET2 RECT ( 5 6 ) ( 7 8 ) ;
END BLOCKAGES
END DESIGN
"""

_DEF_NO_BLOCKAGES = """\
VERSION 5.8 ;
DESIGN chip_top ;
SPECIALNETS 1 ;
    - VDD ( * VPWR ) + USE POWER ;
END SPECIALNETS
END DESIGN
"""


# ── D1: the layer-less entry is what gets dropped, and ONLY that ──────────
def test_layerless_placement_blockage_is_dropped():
    out, dropped = P3._strip_nonlayer_blockages(_DEF_MIXED)
    assert len(dropped) == 1
    assert "PLACEMENT" in dropped[0]
    assert "PLACEMENT" not in out


def test_layer_blockages_are_kept_and_the_count_is_corrected():
    out, dropped = P3._strip_nonlayer_blockages(_DEF_MIXED)
    assert "LAYER MET1 RECT ( 100 200 ) ( 300 400 ) ;" in out
    assert "LAYER MET2 RECT ( 5 6 ) ( 7 8 ) ;" in out
    # a stale count is itself a malformed DEF — the header must match reality
    m = re.search(r"(?m)^\s*BLOCKAGES\s+(\d+)\s*;", out)
    assert m is not None and int(m.group(1)) == 2
    assert out.count("END BLOCKAGES") == 1


def test_nothing_outside_the_blockages_section_is_touched():
    out, _ = P3._strip_nonlayer_blockages(_DEF_MIXED)
    for keep in ("VERSION 5.8 ;", "DESIGN chip_top ;",
                 "UNITS DISTANCE MICRONS 1000 ;",
                 "- VDD ( * VPWR ) + USE POWER ;",
                 "END SPECIALNETS", "END DESIGN"):
        assert keep in out, keep


def test_section_is_removed_entirely_when_every_entry_was_layerless():
    out, dropped = P3._strip_nonlayer_blockages(_DEF_ONLY_PLACEMENT)
    assert len(dropped) == 1
    assert "BLOCKAGES" not in out
    assert "- VDD ( * VPWR ) + USE POWER ;" in out
    assert out.rstrip().endswith("END DESIGN")


# ── strict fall-through: an unaffected DEF must come back UNCHANGED ───────
def test_all_layer_blockages_def_is_returned_unchanged():
    out, dropped = P3._strip_nonlayer_blockages(_DEF_ALL_LAYER)
    assert dropped == []
    assert out == _DEF_ALL_LAYER


def test_def_without_a_blockages_section_is_returned_unchanged():
    out, dropped = P3._strip_nonlayer_blockages(_DEF_NO_BLOCKAGES)
    assert dropped == []
    assert out == _DEF_NO_BLOCKAGES


# ── D1 wiring: magic must be pointed at the STAGED def, and the signed-off
#    DEF must not be rewritten in place ───────────────────────────────────
def test_extraction_uses_the_staged_def_not_the_signed_off_one():
    src = P3._run_extraction_lvs.__doc__ or ""
    assert src is not None
    i = _P3_SRC.index("def _run_extraction_lvs(")
    body = _P3_SRC[i:i + 9000]
    assert "_strip_nonlayer_blockages(" in body
    # the env handed to magic carries the STAGED def
    assert 'f"DEF={_to_container_path(str(extract_def), container)} "' in body
    # ...and the staged copy is a NEW file, never a write back over the input
    assert 'extract_def = ext_dir / f"{top}_extract.def"' in body
    assert "def_file.write_text" not in body


# ── D2: the pipeline's exit status must be magic's, not tee's ────────────
def test_magic_pipeline_does_not_let_tee_mask_the_exit_status():
    # anchor on the LVS-extraction site specifically (there is a second,
    # unrelated magic invocation for the GDS stream-out)
    i = _P3_CODE.index("_magic_tcl_c = _to_container_path(str(tcl), container)")
    window = _P3_CODE[i:i + 1200]
    assert "| " in window and "tee " in window, "still a tee pipeline"
    assert "set -o pipefail" in window


# ── D2 (the part pipefail cannot fix): MEASURED in the image, magic exits 0
#    even on a fatal `lef read`/`def read` failure, so the step must diagnose
#    from magic's OWN completion sentinel, not from rc ─────────────────────
def test_no_netlist_branch_diagnoses_from_the_sentinel_not_from_rc():
    # anchor on the magic-extraction branch specifically (LVS has more than
    # one no-netlist site; only this one is the magic recipe's)
    i = _P3_CODE.index('"LVS_EXTRACTION_NO_NETLIST", _detail')
    window = _P3_CODE[i - 2200:i + 1200]
    # the sentinel must actually be TESTED, not merely mentioned
    assert '_done = "MAGIC_EXT2SPICE_DONE" in _mlog' in window
    assert '_ports = "PORTS_PROMOTED" in _mlog' in window, \
        "must localise the abort to before/after port promotion"
    # ...and both must reach the reader
    assert '"magic_completion_sentinel": _done' in window
    assert '"magic_aborted_stage": _stage' in window
    # and the message must NOT go on implying rc means something for magic
    assert "not evidence here" in window
