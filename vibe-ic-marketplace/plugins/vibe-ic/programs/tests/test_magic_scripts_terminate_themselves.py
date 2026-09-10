"""A magic script must end itself, because the caller's stdin is not ours.

MEASURED 2026-09-09/10 in ghcr.io/vibeic/vibeic-eda:0.3.54. magic run with
`-noconsole` finishes its script and then falls into its own text console,
which re-prints its whole menu for every byte of stdin it cannot parse:

    script WITHOUT a terminal quit, stdin attached   4.0 MB / 6 s
    script WITH `quit -noprompt`, stdin attached     945 B
    script WITHOUT quit, stdin at EOF                992 B

At ~2 MB/s that is ~170 GB/day. A netgen run left on this host in the same
shape wrote a single 102 GB log -- 1,619,420,055 lines whose last 2000 held
NINE distinct ones.

Today the only thing protecting the shipped magic calls is the third row:
`_container_exec.docker_exec_argv` builds `docker exec` WITHOUT `-i`, so the
tool sees EOF. That is a property of the CALLER's argv, in another file, and
anyone adding `-i` for an unrelated reason re-arms every call site at once. A
`quit` travels with the script, which is why it belongs in the builders.

Verified not to truncate: a real magic run writes a byte-identical GDS (182 B)
with and without the terminator.
"""
import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import digital_hardmacro_gen as D  # noqa: E402
import magic_port_extract_emit as M  # noqa: E402

#: magic exits on `quit`; `-noprompt` skips the "really?" it would otherwise
#: ask about unsaved cells, which is itself a console read.
_TERMINATOR = re.compile(r"^\s*quit\b", re.M)


def _last_command(tcl: str) -> str:
    lines = [ln.strip() for ln in tcl.splitlines() if ln.strip()
             and not ln.strip().startswith("#")]
    return lines[-1] if lines else ""


@pytest.mark.parametrize("build,kwargs", [
    (M.build_extraction_tcl, {"top_cell": "blk", "gds_path": "blk.gds",
                              "out_spice": "blk.spice"}),
    (M.build_gds_write_tcl, {"top_cell": "blk", "layout_mag": "blk",
                             "out_gds": "blk.gds"}),
    (M.build_lef_write_tcl, {"top_cell": "blk", "layout_mag": "blk",
                             "out_lef": "blk.lef"}),
])
def test_every_magic_script_builder_terminates(build, kwargs):
    """THE REGRESSION. Each of these ended on its last real command, so magic
    fell straight into the console."""
    tcl = build(**kwargs)
    assert _TERMINATOR.search(tcl), tcl[-200:]
    assert _last_command(tcl).startswith("quit"), (
        "the terminator must be the LAST command; anything after it does not "
        f"run: {_last_command(tcl)!r}")


def test_the_lef_writer_terminates_after_its_done_marker():
    """`digital_hardmacro_gen.build_lef_tcl` ended on a `puts` marker its
    caller greps for. The marker must still be emitted, and the quit must come
    after it."""
    tcl = D.build_lef_tcl("blk", "blk.gds", "blk.def", "blk.lef",
                          full_lef=False, pinonly=False)
    assert "DIGITAL_LEF_WRITE_DONE" in tcl
    assert _TERMINATOR.search(tcl)
    assert _last_command(tcl).startswith("quit")
    assert tcl.index("DIGITAL_LEF_WRITE_DONE") < tcl.rindex("quit")


def test_the_lef_write_is_still_in_the_script():
    """THE CONTROL. A terminator that displaced the work would pass the test
    above and produce nothing."""
    tcl = D.build_lef_tcl("blk", "blk.gds", "blk.def", "blk.lef",
                          full_lef=False, pinonly=False)
    assert "lef write" in tcl and "gds read" in tcl


def test_the_gds_writer_still_writes_before_it_quits():
    tcl = M.build_gds_write_tcl(top_cell="blk", layout_mag="blk",
                                out_gds="blk.gds")
    assert "gds write" in tcl
    assert tcl.index("gds write") < tcl.rindex("quit")
