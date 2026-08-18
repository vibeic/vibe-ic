"""v1.3.43 candidate #6 (HIGH PRIORITY) — slang frontend: probe built-in
`read_slang`, skip `plugin -i slang` when compiled-in.

The fork's yosys (0.66+232) ships slang COMPILED-IN (built-in `read_slang`, NO
slang.so). The runner hardcoded `yosys -p 'plugin -i slang; read_slang …'` at 3
call-sites, so `plugin -i slang` ERRORs "Can't load module ./slang" and ABORTS
the whole -p script -> synth silently fell back to read_verilog (can't prune a
masked generate branch: "aes_sbox_dom not part of the design"). The fix probes
whether read_slang is built-in and skips the plugin load when it is; keeps the
load for images that ship slang as a separate .so. Single source of truth in
synth_frontend for all 3 sites.

Verified this session on the fork container (vibeic-eda:0.2.5):
  OLD `plugin -i slang; read_slang <AES>` -> RC=1 "Can't load module ./slang"
  NEW `read_slang <AES>`                  -> RC=0
  and on a self-contained SV pkg+generate design: read_verilog -sv RC=1
  (TOK_IMPORT syntax error) vs built-in read_slang RC=0 (masked branch pruned).
"""
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import synth_frontend as sf  # noqa: E402

# real fork probe output (`yosys -p 'read_slang'` with no file, built-in):
_BUILTIN_OUT = (
    "-- Running command `read_slang' --\n"
    "1. Executing SLANG frontend.\n"
    "error: no input files\n"
    "ERROR: Bad command\n"
)
# absent (image where slang is an unloaded .so, or genuinely missing):
_ABSENT_OUT = (
    "-- Running command `read_slang' --\n"
    "ERROR: No such command: read_slang (type 'help' for a command overview)\n"
)


def test_builtin_probe_skips_plugin_load():
    assert sf.read_slang_is_builtin(_BUILTIN_OUT) is True
    assert sf.slang_load_prefix(_BUILTIN_OUT) == ""


def test_absent_probe_keeps_plugin_load():
    assert sf.read_slang_is_builtin(_ABSENT_OUT) is False
    assert sf.slang_load_prefix(_ABSENT_OUT) == "plugin -i slang; "


def test_inconclusive_or_empty_probe_is_fork_safe_skip():
    """An empty/garbled probe must DEFAULT to skip (fork-safe) — never emit a
    load that would abort the fork's -p script."""
    assert sf.slang_load_prefix("") == ""
    assert sf.slang_load_prefix("some unrelated banner noise") == ""


def test_resolve_memoises_and_uses_exec_fn():
    calls = {"n": 0}

    def fake_exec(container, cmd):
        calls["n"] += 1
        assert "read_slang" in cmd  # probes read_slang, no file
        return (0, _BUILTIN_OUT, "")

    p1 = sf.resolve_slang_load_prefix("cont-unit-test-6a", fake_exec)
    p2 = sf.resolve_slang_load_prefix("cont-unit-test-6a", fake_exec)
    assert p1 == "" and p2 == ""
    assert calls["n"] == 1  # memoised: probe ran ONCE


def test_resolve_defaults_skip_on_exec_exception():
    def boom(container, cmd):
        raise RuntimeError("docker unreachable")

    assert sf.resolve_slang_load_prefix("cont-unit-test-6b", boom) == ""


def test_probe_cmd_is_pathset_read_slang_no_file():
    # the probe sets the yosys PATH and runs read_slang with NO file
    assert "read_slang" in sf.SLANG_PROBE_CMD
    assert "plugin -i slang" not in sf.SLANG_PROBE_CMD  # must NOT load to probe
    assert "/foss/tools/yosys/bin" in sf.SLANG_PROBE_CMD


def test_all_three_call_sites_use_the_shared_helper():
    """No SV synth recipe may still HARDCODE `plugin -i slang; ` — every site
    must route through resolve_slang_load_prefix (single source of truth)."""
    d1 = (_PROGRAMS / "design_one_shot_runner.py").read_text()
    p3 = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    # the shared probe is called in both runners
    assert "resolve_slang_load_prefix" in d1
    assert p3.count("resolve_slang_load_prefix") >= 2
    # and no literal `plugin -i slang; ` remains hardcoded inside a read_slang
    # recipe (the helper emits it only when NOT built-in)
    for src in (d1, p3):
        assert "'plugin -i slang; " not in src
        assert '"plugin -i slang; ' not in src
