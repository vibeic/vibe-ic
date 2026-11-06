#!/usr/bin/env python3
"""The flow must run OUR klayout, and both halves of that are load bearing.

vibeic-eda#17. The fork patches the LEF/DEF importer to honour tech-LEF
MANUFACTURINGGRID. Measured on the fork's own fixture — same DEF, same tech
LEF, 5 nm grid:

    base pymod                          OFFGRID_VERTICES_TOTAL = 8
    fork pymod                          OFFGRID_VERTICES_TOTAL = 0
    fork pymod + base LD_LIBRARY_PATH   OFFGRID_VERTICES_TOTAL = 8   <-- the trap

The last line is why these tests exist. The pymod extension modules link
libklayout_db.so by SONAME, so pointing sys.path at our build while the base
directory is on the library search path reproduces the base's behaviour exactly.
A fix that moved only sys.path would look right and change nothing.

These drive the real fragments — the shell one through a real shell, the Python
one through a real interpreter — rather than asserting that the source contains
a string.
"""
from __future__ import annotations

import ast
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as P                            # noqa: E402












def _docstring_ids(tree):
    """The `ast.Constant` nodes that are PROSE, not call-site values.

    A DOCSTRING IS NOT A CALL SITE, and reading one as a hard-code is how this
    guard accused an honest landing. MEASURED (czmainred9, v1.19.60): `8000bb196`
    documented WHY `_local_exec_mode` exists by quoting the measurement that
    produced it —

        `yosys`, `openroad` and `klayout` were all on PATH in that same process
        (/foss/tools/bin/yosys, /foss/tools/bin/openroad,
        /foss/tools/klayout/klayout)

    — inside the function's docstring. That is a report of where the tools were
    found on one host, it invokes nothing, and this scan named it as a site that
    hard-codes the base tree. The string it flagged does not even reach a
    process; a fix "for" it could only have been to delete the evidence.

    A string in EXPRESSION POSITION executed for no effect is the same class
    `gate_is_wired_check.executable_text` drops for the same reason, and that
    docstring rule is the one respelled here: this scan needs the NODE (to keep
    `node.lineno` for the message) where `executable_text` returns text, so it
    cannot call it — but it must not disagree with it either. Comments never
    reach `ast` at all, so only docstrings need saying.

    THIS IS NOT A CARVE-OUT FOR THE OFFENDING LINE. Any string that a call site
    passes still counts, including one built or bound in the same function;
    `test_a_hard_code_in_a_call_site_is_still_caught` plants one and proves it.
    """
    out = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not isinstance(
                node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                       ast.ClassDef)):
            continue
        first = body[0] if body else None
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            out.add(id(first.value))
    return out


def test_no_call_site_hard_codes_the_base_klayout():
    """WIRING, which is where a fix like this leaks.

    Stated limit: this reads the call sites rather than executing them — the
    real ones need a container and a GDS. It can only catch a site that names
    the base tree directly, which is exactly how both of the sites this issue
    found were written.

    A string that names the base tree AND the fork tree is a resolver, and the
    base path in it is the fallback that keeps a stock image working. A string
    that names only the base is a hard-code. That distinction is the property,
    not a carve-out for the two constants — a resolver written tomorrow passes,
    and a hard-code hidden inside one does not.
    """
    src = pathlib.Path(P.__file__).read_text()
    tree = ast.parse(src)
    docstrings = _docstring_ids(tree)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue                 # PROSE. See `_docstring_ids`.
            v = node.value
            names_base = ("/foss/tools/klayout/" in v
                          or v.endswith("/foss/tools/klayout"))
            if names_base and "klayout-vibeic" not in v:
                offenders.append((node.lineno, v[:70]))
    assert not offenders, (
        "these name the BASE klayout tree directly, so the fork never runs "
        "there: " + "; ".join(f"line {l}: {v}" for l, v in offenders))


def test_a_hard_code_in_a_call_site_is_still_caught():
    """MUTATION. The docstring exemption must not be an exemption for anything
    that runs.

    Both directions on one synthetic module: the SAME path string is invisible
    in a docstring and an offender everywhere a call site can put it — bound to
    a name, passed as an argument, built into an f-string, or sitting in a list.
    Drop `_docstring_ids` and the first assertion fails; widen it to any string
    constant and every one of the four below goes quiet.
    """
    mod = ast.parse(
        '"""prose: measured at /foss/tools/klayout/klayout on one host."""\n'
        'BOUND = "/foss/tools/klayout/klayout"\n'
        'def go(run):\n'
        '    """also prose about /foss/tools/klayout/klayout."""\n'
        '    run("/foss/tools/klayout/strmcmp")\n'
        '    run(f"{PRE}/foss/tools/klayout/x")\n'
        '    return ["/foss/tools/klayout"]\n')
    docstrings = _docstring_ids(mod)
    hits = [n.value for n in ast.walk(mod)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings
            and ("/foss/tools/klayout/" in n.value
                 or n.value.endswith("/foss/tools/klayout"))]
    assert sorted(hits) == [
        "/foss/tools/klayout",
        "/foss/tools/klayout/klayout",
        "/foss/tools/klayout/strmcmp",
        "/foss/tools/klayout/x",
    ], hits
