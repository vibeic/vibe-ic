#!/usr/bin/env python3
"""A tool's own schema default must pass that tool's own input guard.

From 9d7e5e1a5 (2026-07-13) until this fix, TWO MCP tools refused every single
invocation, unconditionally, before doing any work:

    eda_sta        index.js  container:             z.string().default("vibeic-eda")
                             assertSafeIdent(container, "container")
    eda_extraction index.js  field_solve_container: z.string().default("vibeic-eda")
                             assertSafeIdent(field_solve_container, ...)

`assertSafeIdent` validates against _IDENT_RE = /^[A-Za-z_][A-Za-z0-9_]*$/, which
has no hyphen, so the shipped default "vibeic-eda" failed it:

    {"success":false,"error":"input rejected: unsafe container: \"vibeic-eda\"
     (expected a plain identifier /^[A-Za-z_][A-Za-z0-9_]*$/)"}

Both guards sit OUTSIDE the opt-in branch that is the only consumer of the param,
so ordinary single-netlist STA and ordinary Magic extraction — neither of which
touches `container` at all — were refused too. eda_sta is declared as the
mcp_tool of two flow steps in flow/phase1_phase2_phase3.yaml.

The defect is the CHARACTER CLASS, not the default: a docker container name
legitimately carries '-' and '.'. The fix is `assertSafeContainer` /
_CONTAINER_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/ — the identifier class plus '-'
and '.', and additionally requiring an alphanumeric FIRST character so a value
like "-v/:/host" cannot be read by docker as a flag. It remains strictly tighter
than assertSafeToken and admits no shell metacharacter.

This test locks in both arms:
  * every container-typed param's own default is ACCEPTED by its own guard, and
    no container-typed param is guarded by assertSafeIdent any more;
  * the widened class still rejects every shell metacharacter, exhaustively over
    U+0000..U+02FF, plus concrete injection and docker-flag payloads.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

MCP_ROOT = Path(__file__).resolve().parents[1]
INDEX_JS = MCP_ROOT / "src" / "index.js"
SAFETY_MJS = MCP_ROOT / "src" / "lib" / "shell_safety.mjs"
SRC = INDEX_JS.read_text()

_NODE = shutil.which("node")

# Every container-typed param in index.js, discovered from the source rather
# than hard-coded, so a THIRD one added later is covered without editing this
# test. (Enumerations must be derived from the tree.)
_DECL_RE = re.compile(
    r"^\s*(\w*container)\s*:\s*z\.string\(\)\.default\(\"([^\"]+)\"\)", re.M
)


def _container_params():
    found = _DECL_RE.findall(SRC)
    assert found, "no container-typed param with a default found in index.js"
    return found


def test_the_tree_still_has_container_params_with_defaults():
    names = [n for n, _ in _container_params()]
    # The two known at the time of the fix; the guard below covers any others.
    assert "container" in names
    assert "field_solve_container" in names


def test_no_container_param_is_guarded_by_assertSafeIdent():
    """The exact regression: assertSafeIdent on a container-typed param."""
    offenders = re.findall(r"assertSafeIdent\(\s*(\w*container)\b", SRC)
    assert offenders == [], (
        "container-typed param(s) guarded by assertSafeIdent, whose class has no "
        f"hyphen — their own default cannot pass their own guard: {offenders}"
    )


def test_every_container_param_is_guarded_by_assertSafeContainer():
    for name, _default in _container_params():
        assert re.search(rf"assertSafeContainer\(\s*{name}\b", SRC), (
            f"container param {name!r} has a default but no assertSafeContainer guard"
        )


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_each_default_passes_its_own_guard_and_metacharacters_stay_out():
    """Behavioural, run through the real validator."""
    defaults = [d for _n, d in _container_params()]
    # Namespace import + a fallback to the guard the pre-fix tree actually used,
    # so this arm RUNS against the pre-fix code and answers wrongly there, rather
    # than dying on a missing named export and observing nothing.
    script = r"""
import * as S from "%s";
const DEFAULTS = %s;
const guard = S.assertSafeContainer || S.assertSafeIdent;
const assertSafeIdent = S.assertSafeIdent;
const ok = (v) => { try { guard(v); return true; } catch (e) { return false; } };
let fail = 0;
if (!S.assertSafeContainer) {
  console.log("NOTE running against the pre-fix guard (assertSafeIdent) — expect ARM A to fail");
}

// ARM A — every shipped default must be ACCEPTED by its own guard.
for (const d of DEFAULTS) {
  if (!ok(d)) { console.log("FAIL default rejected by its own guard: " + JSON.stringify(d)); fail++; }
}

// ARM A control — the OLD guard rejected those same defaults. Without this the
// test could pass against the pre-fix tree and prove nothing.
for (const d of DEFAULTS) {
  let threw = false;
  try { assertSafeIdent(d); } catch (e) { threw = true; }
  if (!threw) {
    console.log("FAIL control did not reproduce: assertSafeIdent accepted " + JSON.stringify(d));
    fail++;
  }
}

// ARM B — the widened class must still admit no shell metacharacter, and no
// leading '-' (which docker would parse as a flag, not a container name).
for (const p of ["vibeic-eda; rm -rf /", "vibeic-eda && id", "$(id)", "`id`",
                 "a|b", "a\nb", "a b", "vibeic-eda'; docker rm -f x; '",
                 "-v/:/host", "--privileged", "-eda", "..", "./x", "",
                 "a>b", "a<b", "a&b", "a;b", "a$b", "a*b", "a?b", "a~b",
                 'a"b', "a'b", "a\\b", "a\rb", "a\tb", "a\0b"]) {
  if (ok(p)) { console.log("FAIL payload accepted: " + JSON.stringify(p)); fail++; }
}
for (const nv of [undefined, null, 7, {}, [], ["vibeic-eda"]]) {
  if (ok(nv)) { console.log("FAIL non-string accepted: " + JSON.stringify(nv)); fail++; }
}

// ARM B exhaustive — the accepted set is EXACTLY [A-Za-z0-9_.-] in the interior
// and EXACTLY [A-Za-z0-9] in first position, over the whole low plane.
for (let i = 0; i < 0x300; i++) {
  const ch = String.fromCharCode(i);
  const expectMid = /[A-Za-z0-9_.\-]/.test(ch) && i < 128;
  if (ok("a" + ch) !== expectMid) {
    console.log("FAIL interior codepoint " + i + " " + JSON.stringify(ch)); fail++;
  }
  const expectFirst = /[A-Za-z0-9]/.test(ch) && i < 128;
  if (ok(ch + "a") !== expectFirst) {
    console.log("FAIL first codepoint " + i + " " + JSON.stringify(ch)); fail++;
  }
}
console.log(fail === 0 ? "ALL_OK" : ("FAILURES=" + fail));
""" % (SAFETY_MJS.as_posix(), json.dumps(defaults))

    out = subprocess.run(
        [_NODE, "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=180,
    )
    assert out.returncode == 0, out.stderr
    assert "ALL_OK" in out.stdout, out.stdout + out.stderr
