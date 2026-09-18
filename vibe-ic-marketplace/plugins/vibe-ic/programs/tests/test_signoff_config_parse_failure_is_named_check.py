"""A config read may not answer "I could not parse it" with "nothing declared".

The defect this guards: a declaration file was read inside a broad handler that
re-assigned the same empty default the ABSENT case uses, so one misplaced comma
reverted every declared decision to a default nobody chose — silently. A dozen
lines away the same function warned on stderr about other declarations, so the
code base already held the position that one site broke.

Both directions are asserted here, because an assertion that holds for the
defect AND for its fix measures nothing:

  POSITIVE — the defect shape FAILS (rc 1) and the message NAMES the file, the
             line, the reverted name and the keys that go quiet.
  NEGATIVE — the same function with the failure NAMED (raise, or a stderr line
             before the default) PASSES (rc 0).

Then one control per narrowing: each legitimate shape the rule deliberately
does NOT fire on gets its own PASS, so a future widening of the predicate turns
this file red instead of turning the tree red. `except ...: pass` WAS such a
control until the round that measured it: the absent default is already
standing when the `try` runs, so rebinding nothing leaves the very state
`cfg = {}` leaves, and the rule now asks what the name HOLDS rather than what
the handler WRITES. Its replacement control is the one that distinguishes
them — a REAL value standing at the `try`, which a `pass` handler does not
turn into "absent".

And one arm per deleted EXEMPTION. The rule was cut down to a core that cannot
be talked out of a verdict: no skip list, no overlay exemption, no distance
window, no "any call excuses the handler", no `try`-body size bound, no tuning
flags. Each of those used to be a one-edit way to keep a live silent default
and still print PASS, so each has a test that goes red if it comes back.

And one arm per deleted FALSE POSITIVE. Requirement 4 used to credit a key it
could not name (`memo.get(rel)` was recorded as `<line 18>`) and a key that
was being WRITTEN, not read (`doc["program"] = ...`). Those two reported a
memo cache that recomputes on corruption, and a read-modify-write ledger, as
declared decisions reverting. Both now have a control here, so widening the
predicate back turns this file red rather than the tree.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import signoff_config_parse_failure_is_named_check as C  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures — written as SOURCE TEXT at runtime, never as live code in this
# file, so this test module can never trip the checker it exercises. (It is
# also why no directory is skipped: fixtures for this shape belong in strings.)
# ---------------------------------------------------------------------------
_HEAD = """import json
import sys


def resolve(staged_dir, deck):
"""

#: THE DEFECT, structurally verbatim: an absent-case default, an existence
#: guard, a broad handler that re-assigns that same default, and decisions
#: mined out of the result key by key.
DEFECT = _HEAD + """    cfg = {}
    cfg_f = staged_dir / "config.json"
    if not deck:
        print("[WARN] no deck declared", file=sys.stderr)
    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception:
            cfg = {}
    return cfg.get("compare_engine", "builtin"), cfg.get("fill_target")
"""
#: 1-indexed line of the offending handler body in DEFECT.
DEFECT_HANDLER_LINE = 13

#: The fix: the parse failure is REFUSED, and it names the file and the error.
FIXED_RAISES = _HEAD + """    cfg = {}
    cfg_f = staged_dir / "config.json"
    if not deck:
        print("[WARN] no deck declared", file=sys.stderr)
    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except (OSError, ValueError) as exc:
            raise RuntimeError("cannot read %s: %s" % (cfg_f, exc)) from exc
    return cfg.get("compare_engine", "builtin"), cfg.get("fill_target")
"""

#: The other acceptable fix: still defaults, but SAYS SO on stderr first.
FIXED_WARNS = _HEAD + """    cfg = {}
    cfg_f = staged_dir / "config.json"
    if not deck:
        print("[WARN] no deck declared", file=sys.stderr)
    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception as exc:
            print("[WARN] unreadable %s: %s" % (cfg_f, exc), file=sys.stderr)
            cfg = {}
    return cfg.get("compare_engine", "builtin"), cfg.get("fill_target")
"""

#: Bookkeeping beside the default does not buy an exemption: `ok = False` says
#: nothing to anybody, and the declared keys still go quiet.
DEFECT_WITH_BOOKKEEPING = _HEAD + """    cfg = {}
    ok = True
    cfg_f = staged_dir / "config.json"
    if not deck:
        print("[WARN] no deck declared", file=sys.stderr)
    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception:
            cfg = {}
            ok = False
    return cfg.get("compare_engine", "builtin"), cfg.get("fill_target"), ok
"""

#: A CALL in the handler used to excuse it, on the theory that a call might be
#: a log line. `seen.append(cfg_f)` tells nobody anything, and one inserted
#: line of it bought green with the defect untouched. Only a `raise` or a real
#: emit excuses a handler now.
DEFECT_WITH_HARMLESS_CALL = _HEAD + """    cfg = {}
    seen = []
    cfg_f = staged_dir / "config.json"
    if not deck:
        print("[WARN] no deck declared", file=sys.stderr)
    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception:
            cfg = {}
            seen.append(cfg_f)
    return cfg.get("compare_engine", "builtin"), cfg.get("fill_target"), seen
"""

#: Filling in place is filling: `cfg.update(json.loads(...))` reads into `cfg`
#: exactly as an assignment would.
DEFECT_INPLACE_FILL = _HEAD + """    cfg = {}
    cfg_f = staged_dir / "config.json"
    if not deck:
        print("[WARN] no deck declared", file=sys.stderr)
    if cfg_f.is_file():
        try:
            cfg.update(json.loads(cfg_f.read_text()))
        except Exception:
            cfg = {}
    return cfg.get("compare_engine", "builtin"), cfg.get("fill_target")
"""

#: `dict()` is how this code base spells `{}` in places. A handler that CALLS
#: the empty container into existence is still a handler that says nothing.
DEFECT_DICT_SPELLING = _HEAD + """    cfg = dict()
    cfg_f = staged_dir / "config.json"
    if not deck:
        print("[WARN] no deck declared", file=sys.stderr)
    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception:
            cfg = dict()
    return cfg.get("compare_engine", "builtin"), cfg.get("fill_target")
"""

#: READ-MODIFY-WRITE. An earlier version EXEMPTED this shape — file read and
#: written back in one function — on the theory that an unreadable prior copy
#: legitimately starts empty. The exemption was a door: one added `write_text`
#: call walked any site out of the rule. And the shape is not innocent: the
#: unparseable prior copy is OVERWRITTEN two lines later, so the silence
#: destroys the only copy on disk. It is a finding.
DEFECT_OVERLAY_THAT_SPEAKS = """import json
import sys


def merge(ledger_f, entry):
    doc = {}
    if ledger_f.is_file():
        try:
            doc = json.loads(ledger_f.read_text())
        except Exception:
            doc = {}
    if not entry:
        print("[WARN] empty entry", file=sys.stderr)
    doc.setdefault("entries", []).append(entry)
    ledger_f.write_text(json.dumps(doc))
    return doc.get("entries"), doc.get("updated_at")
"""

#: A BIG `try` body. This used to be a control, exempted by a four-statement
#: size bound on the read. The bound was a line anyone could step over: four
#: dead assignments above the parse took the real pre-fix defect from rc 1 to
#: rc 0, and deleting the bound left the guarded tree at rc 0, so it was
#: holding back nothing. The handler here still answers a parse failure with
#: an unannounced `cfg = {}` that the absent case already means, and still
#: reverts two declared keys — which is the whole defect, at any body length.
DEFECT_LARGE_TRY_BODY = _HEAD + """    cfg = {}
    cfg_f = staged_dir / "config.json"
    if not deck:
        print("[WARN] no deck declared", file=sys.stderr)
    if cfg_f.is_file():
        try:
            a = 1
            b = a + 1
            c = b + 1
            d = c + 1
            e = d + 1
            cfg = json.loads(cfg_f.read_text())
            cfg["seen"] = e
        except Exception:
            cfg = {}
    return cfg.get("compare_engine", "builtin"), cfg.get("fill_target")
"""

#: A real logging channel IS a contrast, so requirement 5's emit arm was not
#: simply deleted along with the false ones below.
DEFECT_VIA_LOGGER = """import json
import logging

LOG = logging.getLogger(__name__)


def resolve(cfg_f, deck):
    cfg = {}
    if not deck:
        LOG.warning("no deck declared")
    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception:
            cfg = {}
    return cfg.get("compare_engine"), cfg.get("fill_target")
"""


#: THREE SPELLINGS OF ONE STATE. The absent default is already standing when
#: the `try` runs, so a handler that rebinds nothing leaves `cfg` at `{}` just
#: as `cfg = {}` does. `pass` was a CONTROL here until the round that measured
#: it: replacing the real pre-fix defect's one handler line with `pass` — or
#: with `_cfg_err = {}`, which rebinds a different name — took rc 1 to rc 0
#: with the defect bit-identical. The requirement was restated from "the
#: handler ASSIGNS an empty container" to "the handler LEAVES the name at its
#: empty default", and all three now fall out of the same condition.
DEFECT_PASS_HANDLER = _HEAD + """    cfg = {}
    cfg_f = staged_dir / "config.json"
    if not deck:
        print("[WARN] no deck declared", file=sys.stderr)
    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception:
            pass
    return cfg.get("compare_engine", "builtin"), cfg.get("fill_target")
"""

DEFECT_REBINDS_ANOTHER_NAME = _HEAD + """    cfg = {}
    cfg_f = staged_dir / "config.json"
    if not deck:
        print("[WARN] no deck declared", file=sys.stderr)
    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception:
            cfg_err = {}
    return cfg.get("compare_engine", "builtin"), cfg.get("fill_target")
"""


# --- controls: legitimate shapes the narrowings keep out --------------------

#: A REAL VALUE STANDING AT THE `try`. The last assignment before the read is
#: `cfg = _builtin_defaults()`, not `cfg = {}`, so a failed parse does not land
#: on "absent": the handler wipes a real value, which is a different program
#: and a different claim. (Requirement 2.)
CONTROL_NON_EMPTY_STANDING_VALUE = _HEAD + """    cfg = {}
    cfg = _builtin_defaults()
    cfg_f = staged_dir / "config.json"
    if not deck:
        print("[WARN] no deck declared", file=sys.stderr)
    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception:
            pass
    return cfg.get("compare_engine", "builtin"), cfg.get("fill_target")
"""

#: No earlier assignment of the same empty value: the function never had an
#: "absent" answer to collapse onto, so unreadable is not being recorded as
#: absent. (Requirement 3.)
CONTROL_NO_ABSENT_DEFAULT = _HEAD + """    cfg_f = staged_dir / "config.json"
    if not deck:
        print("[WARN] no deck declared", file=sys.stderr)
    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception:
            cfg = {}
        return cfg.get("compare_engine", "builtin"), cfg.get("fill_target")
    return None, None
"""

#: An earlier `return {}` is not an earlier `cfg = {}`. A bare `return` carries
#: no name, and crediting it as this name's absent answer is name-blind: it
#: says "somewhere this function returns {}" and concludes something about
#: `cfg`. (Requirement 3, the clause deleted this round.)
CONTROL_EARLY_RETURN_IS_NOT_A_DEFAULT = _HEAD + """    if not deck:
        print("[WARN] no deck declared", file=sys.stderr)
        return {}
    cfg_f = staged_dir / "config.json"
    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception:
            cfg = {}
    return cfg.get("compare_engine", "builtin"), cfg.get("fill_target")
"""

#: Read once, passed along, never mined: an empty value here is a legitimate
#: "nothing to merge", not a set of decisions reverting. (Requirement 4.)
CONTROL_NOT_A_DECLARATION = _HEAD + """    cfg = {}
    cfg_f = staged_dir / "config.json"
    if not deck:
        print("[WARN] no deck declared", file=sys.stderr)
    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception:
            cfg = {}
    return merge(cfg), cfg.get("only_one_key")
"""

#: Nothing anywhere in this function raises or writes to stderr: it has no
#: house position on speaking up, so its silence is style, not a broken rule.
#: (Requirement 5.)
CONTROL_NO_CONTRAST = _HEAD + """    cfg = {}
    cfg_f = staged_dir / "config.json"
    if not deck:
        print("[info] no deck declared")
    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception:
            cfg = {}
    return cfg.get("compare_engine", "builtin"), cfg.get("fill_target")
"""

#: `None` is not an empty declaration set. Code receiving it must test it
#: before reading a key, whereas `{}` answers every `.get` with a default
#: nobody chose. Out of scope by DEFINITION — which is what let the distance
#: bound go, because the one legitimate site this rule ever reached on the
#: guarded tree was exactly this shape. (Requirement 2.)
CONTROL_NONE_IS_NOT_AN_EMPTY_CONTAINER = """import json
import sys


def record(ev_f, payload):
    prior = None
    if ev_f.is_file():
        try:
            prior = json.loads(ev_f.read_text())
        except (OSError, ValueError):
            prior = None
    if not payload:
        print("[WARN] nothing to record", file=sys.stderr)
    return prior.get("verdict") if prior else None, prior.get("report")
"""

#: A REPORT handle is not a warning channel. `print(row, file=out_fh)` writes
#: the product, not a complaint, and crediting it as "this function speaks up"
#: printed a reason sentence pointing at code that takes no position at all.
#: (Requirement 5's emit predicate.)
CONTROL_REPORT_HANDLE = """import json


def render(cache_f, out_fh, rows):
    cache = {}
    if cache_f.is_file():
        try:
            cache = json.loads(cache_f.read_text())
        except Exception:
            cache = {}
    for row in rows:
        print(row, file=out_fh)
    return cache.get("rows"), cache.get("stamp")
"""

#: `result.error(...)` is a domain method on a result object, not logging. The
#: spelling of the attribute is not the channel. (Requirement 5's emit
#: predicate.)
CONTROL_DOMAIN_METHOD = """import json


def render(cache_f, result, rows):
    cache = {}
    if cache_f.is_file():
        try:
            cache = json.loads(cache_f.read_text())
        except Exception:
            cache = {}
    if not rows:
        result.error("no rows to render")
    return cache.get("rows"), cache.get("stamp")
"""

#: A MEMO CACHE that recomputes on corruption. Recomputing is exactly what a
#: cache is for, and this one raises about a genuinely missing file a few lines
#: down, so requirement 5 is satisfied. It fired anyway, because `memo.get(rel)`
#: and `memo.get(rel + ".mtime")` were recorded as the "keys" `<line 18>` and
#: `<line 19>`. A finding whose evidence reads "2 declared key(s): <line 18>,
#: <line 19>" is a count dressed as a name. A key that is not a literal is not
#: a declared key. (Requirement 4.)
CONTROL_MEMO_CACHE_RECOMPUTES = """import json


def sha_memo(run, files):
    memo = {}
    memo_f = run / ".sha_memo.json"
    if memo_f.is_file():
        try:
            memo = json.loads(memo_f.read_text())
        except Exception:
            memo = {}
    out = {}
    for rel in files:
        hit = memo.get(rel)
        stamp = memo.get(rel + ".mtime")
        if hit and stamp:
            out[rel] = hit
            continue
        p = run / rel
        if not p.is_file():
            raise FileNotFoundError("%s is declared but absent" % rel)
        out[rel] = _sha(p)
    return out
"""

#: A READ-MODIFY-WRITE LEDGER. `doc` is consulted for nothing; `doc["program"]`
#: and `doc["updated_at"]` are WRITES, and the whole document is rewritten. It
#: fired with "2 declared key(s) then take their defaults unannounced" naming
#: those two writes. A store takes no default and reverts no decision. This is
#: the shape of `step_preflight.record()`, whose own docstring says "NEVER
#: raises. Best-effort in the WRITE direction only". (Requirement 4.)
CONTROL_LEDGER_WRITES_ARE_NOT_READS = """import json
import time


def append(project, row):
    p = project / "ledger.json"
    doc = {}
    if p.is_file():
        try:
            doc = json.loads(p.read_text())
        except (OSError, ValueError):
            doc = {}
    if not isinstance(doc, dict):
        raise TypeError("ledger must be a JSON object")
    doc["program"] = "step_preflight"
    doc["updated_at"] = time.strftime("%Y-%m-%d")
    doc.setdefault("rows", []).append(row)
    p.write_text(json.dumps(doc))
"""

#: ANOTHER NAME'S KEYS ARE NOT THIS NAME'S. `cfg` is read for exactly one key
#: here; the two mined keys belong to `defaults`, which nothing defaulted and
#: nothing reverted. Requirement 4 is a claim about ONE name — the same name
#: requirements 2 and 3 are about — and a predicate that counts every `.get`
#: in the function says "somebody mines two keys somewhere" and concludes
#: something about `cfg`. (Requirement 4's venue.)
CONTROL_ANOTHER_NAMES_KEYS = """import json
import sys


def resolve(cfg_f, defaults):
    cfg = {}
    if not cfg_f.is_file():
        print("[WARN] no config declared", file=sys.stderr)
    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception:
            cfg = {}
    engine = defaults.get("compare_engine")
    fill = defaults["fill_target"]
    return cfg.get("only_one_key"), engine, fill
"""

#: A nested `def`'s refusal is the INNER function's position. Crediting it made
#: an unrelated helper look like this function's house rule — and requirements
#: 3 and 4 already excluded nested definitions, so "the same function" meant
#: two different things in one rule. (Requirement 5's venue.)
CONTROL_NESTED_RAISE = """import json


def outer(cfg_f):
    def helper(x):
        raise RuntimeError("unrelated helper refusal")

    cfg = {}
    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception:
            cfg = {}
    return helper, cfg.get("a"), cfg.get("b")
"""


def _write(tmp_path: Path, name: str, source: str) -> Path:
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return target


def _run(capsys, *argv) -> tuple:
    rc = C.main([str(a) for a in argv])
    captured = capsys.readouterr()
    return rc, captured.out + captured.err


def _except_line(source: str, needle: str) -> int:
    """1-indexed line of the `except ...` clause whose STRIPPED text matches.

    A finding is anchored at the HANDLER, which is the `except` line, not the
    line of the default it substitutes.
    """
    for number, line in enumerate(source.splitlines(), start=1):
        if line.strip() == needle:
            return number
    raise AssertionError(f"fixture no longer contains {needle!r}")


# ---------------------------------------------------------------------------
# POSITIVE arm — the defect FAILS, and the message names where it is
# ---------------------------------------------------------------------------
def test_silent_default_config_read_fails_and_names_the_site(tmp_path, capsys):
    target = _write(tmp_path, "runner.py", DEFECT)

    rc, out = _run(capsys, target)

    assert rc == 1, out
    assert "[FAIL]" in out
    assert str(target) in out, "the verdict must name the offending file"
    assert f"{target}:{DEFECT_HANDLER_LINE}:" in out, (
        "the verdict must name the offending LINE")
    assert "resolve()" in out, "the verdict must name the function"
    assert "leaves cfg at {}" in out, (
        "the verdict must name the reverted default")
    assert "'compare_engine'" in out and "'fill_target'" in out, (
        "the verdict must name the declared keys that go quiet")


def test_the_finding_is_reachable_through_the_api(tmp_path):
    findings = C.scan_source(DEFECT, "runner.py")
    assert len(findings) == 1
    finding = findings[0]
    assert finding.line == DEFECT_HANDLER_LINE
    assert finding.function == "resolve"
    assert finding.name == "cfg"
    assert finding.default == "{}"
    assert finding.absent_default_line < finding.line
    assert finding.key_reads == ["'compare_engine'", "'fill_target'"]


@pytest.mark.parametrize("name,source", [
    ("bookkeeping", DEFECT_WITH_BOOKKEEPING),
    ("harmless_call", DEFECT_WITH_HARMLESS_CALL),
    ("inplace_fill", DEFECT_INPLACE_FILL),
    ("logger_contrast", DEFECT_VIA_LOGGER),
    ("dict_spelling", DEFECT_DICT_SPELLING),
    ("large_try_body", DEFECT_LARGE_TRY_BODY),
    ("pass_handler", DEFECT_PASS_HANDLER),
    ("rebinds_another_name", DEFECT_REBINDS_ANOTHER_NAME),
])
def test_further_spellings_of_the_same_silence_fail(tmp_path, capsys, name,
                                                    source):
    """One harmless extra statement, or `update()`, must not buy an exemption."""
    target = _write(tmp_path, f"{name}.py", source)

    rc, out = _run(capsys, target)

    assert rc == 1, out
    assert f"{target}:{_except_line(source, 'except Exception:')}:" in out, out


# ---------------------------------------------------------------------------
# NEGATIVE arm — the corrected shapes PASS
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,source", [
    ("raises", FIXED_RAISES),
    ("warns_then_defaults", FIXED_WARNS),
])
def test_a_named_parse_failure_passes(tmp_path, capsys, name, source):
    target = _write(tmp_path, f"fixed_{name}.py", source)

    rc, out = _run(capsys, target)

    assert rc == 0, out
    assert "[PASS]" in out
    assert "1 file(s) scanned" in out


# ---------------------------------------------------------------------------
# One control per narrowing. Each of these is a shape that EXISTS in the tree
# this rule guards; if a future widening makes any of them fire, this file goes
# red before the tree does.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,source", [
    ("non_empty_standing_value", CONTROL_NON_EMPTY_STANDING_VALUE),
    ("no_absent_default", CONTROL_NO_ABSENT_DEFAULT),
    ("early_return_is_not_a_default", CONTROL_EARLY_RETURN_IS_NOT_A_DEFAULT),
    ("not_a_declaration", CONTROL_NOT_A_DECLARATION),
    ("no_contrast", CONTROL_NO_CONTRAST),
    ("none_is_not_a_container", CONTROL_NONE_IS_NOT_AN_EMPTY_CONTAINER),
    ("report_handle", CONTROL_REPORT_HANDLE),
    ("domain_method", CONTROL_DOMAIN_METHOD),
    ("nested_raise", CONTROL_NESTED_RAISE),
    ("memo_cache_recomputes", CONTROL_MEMO_CACHE_RECOMPUTES),
    ("ledger_writes", CONTROL_LEDGER_WRITES_ARE_NOT_READS),
    ("another_names_keys", CONTROL_ANOTHER_NAMES_KEYS),
])
def test_legitimate_shapes_do_not_fire(tmp_path, capsys, name, source):
    target = _write(tmp_path, f"control_{name}.py", source)

    rc, out = _run(capsys, target)

    assert rc == 0, f"{name} must not be a finding\n{out}"


def test_every_control_differs_from_the_defect_in_exactly_one_way():
    """The controls are only evidence if the DEFECT itself still fires."""
    assert C.scan_source(DEFECT, "d.py"), "the positive fixture stopped firing"
    for source in (CONTROL_NON_EMPTY_STANDING_VALUE, CONTROL_NO_ABSENT_DEFAULT,
                   CONTROL_EARLY_RETURN_IS_NOT_A_DEFAULT,
                   CONTROL_NOT_A_DECLARATION, CONTROL_NO_CONTRAST,
                   CONTROL_NONE_IS_NOT_AN_EMPTY_CONTAINER,
                   CONTROL_REPORT_HANDLE, CONTROL_DOMAIN_METHOD,
                   CONTROL_NESTED_RAISE, CONTROL_MEMO_CACHE_RECOMPUTES,
                   CONTROL_LEDGER_WRITES_ARE_NOT_READS,
                   CONTROL_ANOTHER_NAMES_KEYS,
                   FIXED_RAISES, FIXED_WARNS):
        assert source != DEFECT
        assert not C.scan_source(source, "c.py")


def test_the_emit_predicate_is_pinned_in_BOTH_directions():
    """A report handle is not a channel; a logger is.

    Widening `file=<name>` back to "any name" or narrowing logging away both
    turn this red. Before, either edit left every assertion green.
    """
    assert not C.scan_source(CONTROL_REPORT_HANDLE, "c.py"), (
        "print(row, file=out_fh) is the product, not a complaint")
    assert not C.scan_source(CONTROL_DOMAIN_METHOD, "c.py"), (
        "result.error(...) is a domain method, not a logging channel")
    assert C.scan_source(DEFECT_VIA_LOGGER, "d.py"), (
        "LOG.warning(...) on a bound logger IS this function speaking up")
    assert C._is_stderr_print(_first_call("print('x', file=sys.stderr)"))
    assert not C._is_stderr_print(_first_call("print('x', file=out_fh)")), (
        "file=<any name> is not stderr; this is the clause that has to stay "
        "narrow in BOTH directions")


def _handler(source: str) -> ast.ExceptHandler:
    """The first `except` clause of the first `try` in a fixture."""
    return next(h for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.Try) for h in n.handlers)


def _first_call(expr: str):
    return next(n for n in ast.walk(ast.parse(expr)) if isinstance(n, ast.Call))


# ---------------------------------------------------------------------------
# The deleted EXEMPTIONS. Each of these was a one-edit way to keep a live
# silent default and still print PASS. If one comes back, this section is red.
# ---------------------------------------------------------------------------
def test_nothing_in_the_handler_but_a_raise_or_an_emit_excuses_it():
    """`seen.append(p)` tells nobody anything and must not buy an exemption."""
    assert C.scan_source(DEFECT_WITH_HARMLESS_CALL, "d.py"), (
        "any-call-excuses-the-handler was a door; it must stay shut")
    assert not C.scan_source(FIXED_RAISES, "f.py")
    assert not C.scan_source(FIXED_WARNS, "f.py")


def test_leaving_the_default_is_the_requirement_not_assigning_it():
    """The hole that "the handler ASSIGNS an empty container" left open.

    Requirement 2 guarantees the name is already at `{}` when the `try` runs,
    so a handler that rebinds nothing leaves exactly the state `cfg = {}`
    leaves. Keying requirement 3 on the ASSIGNMENT meant one edit — `pass`, or
    a rebind of some other name — bought green with the defect bit for bit
    alive. All three spellings are one condition now, and the control below is
    the other direction: when a REAL value is what stands at the `try`, a
    `pass` handler is not this defect and must not fire.
    """
    for source in (DEFECT, DEFECT_PASS_HANDLER, DEFECT_REBINDS_ANOTHER_NAME):
        findings = C.scan_source(source, "d.py")
        assert findings, "all three leave cfg at the absent default"
        assert findings[0].name == "cfg" and findings[0].default == "{}"
    assert not C.scan_source(CONTROL_NON_EMPTY_STANDING_VALUE, "c.py"), (
        "a handler that leaves a REAL value standing is a different program")

    passing, assigning = (_handler(DEFECT_PASS_HANDLER), _handler(DEFECT))
    assert C._leaves_name_empty(passing, "cfg", "{}"), (
        "`pass` changes nothing, so it leaves the name at its empty default")
    assert C._leaves_name_empty(assigning, "cfg", "{}")
    assert not C._leaves_name_empty(assigning, "cfg", "[]"), (
        "a rebind must be to the SAME empty value requirement 2 measured")
    assert not C._leaves_name_empty(_handler(
        DEFECT.replace("            cfg = {}\n",
                       "            cfg.update(_fallback())\n")), "cfg", "{}"), (
        "a handler that fills the name in place is a different program")


def test_the_overlay_exemption_is_gone():
    """Read-and-write-back no longer exempts a silent parse failure.

    The exemption could be entered by ADDING one `write_text` call, and the
    sites it covered are exactly the ones where the unparseable file is then
    overwritten — where the silence destroys the only copy.
    """
    findings = C.scan_source(DEFECT_OVERLAY_THAT_SPEAKS, "o.py")
    assert findings, "an overlay that speaks elsewhere is still a finding"
    assert findings[0].name == "doc"


def test_distance_does_not_decide_requirement_5(tmp_path, capsys):
    """A line-distance window could be closed by inserting a COMMENT.

    So requirement 5 asks whether this function speaks up AT ALL. Four hundred
    padding lines between the stderr line and the read do not change the
    verdict, and neither does a comment.
    """
    pad = "".join(f"    pad{i} = {i}\n" for i in range(400))
    far = _HEAD + """    cfg = {}
    cfg_f = staged_dir / "config.json"
    if not deck:
        print("[WARN] no deck declared", file=sys.stderr)
""" + pad + """    if cfg_f.is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception:
            cfg = {}
    return cfg.get("compare_engine", "builtin"), cfg.get("fill_target")
"""
    assert C.scan_source(far, "far.py"), (
        "400 lines is still this function's own position on speaking up")

    commented = DEFECT.replace("    if cfg_f.is_file():",
                               "    # best effort\n    if cfg_f.is_file():")
    assert C.scan_source(commented, "c.py"), (
        "an inserted comment must not erase a finding")

    assert not hasattr(C, "WINDOW"), (
        "a distance bound is a knob prose can turn; it must not come back")


def test_the_try_body_size_bound_is_gone(tmp_path, capsys):
    """A threshold one line can cross is not a requirement.

    `MAX_READ_STMTS` was 4, so four dead assignments above the parse walked a
    live silent default out of the rule — measured on the real pre-fix source,
    rc 1 -> rc 0 with the defect untouched. It was also not load-bearing:
    deleting it left the guarded tree at rc 0. Both halves are asserted here,
    because reinstating the bound would leave every other assertion green.
    """
    assert not hasattr(C, "MAX_READ_STMTS"), (
        "a size threshold is not part of this invariant; it must not come back")

    padded = DEFECT.replace(
        "            cfg = json.loads(cfg_f.read_text())",
        "            _a = 1\n            _b = 2\n            _c = 3\n"
        "            _d = 4\n            cfg = json.loads(cfg_f.read_text())")
    assert C.scan_source(padded, "padded.py"), (
        "four dead statements must not buy green")

    grown = DEFECT.replace(
        "            cfg = json.loads(cfg_f.read_text())",
        "".join(f"            _p{i} = {i}\n" for i in range(40))
        + "            cfg = json.loads(cfg_f.read_text())")
    assert C.scan_source(grown, "grown.py"), (
        "forty statements do not change what the handler does either")

    target = _write(tmp_path, "runner.py", DEFECT)
    with pytest.raises(SystemExit):
        C.main([str(target), "--max-read-stmts", "1"])
    capsys.readouterr()


def test_a_key_read_must_name_its_key_and_must_be_a_read():
    """Requirement 4's two false-positive cures, pinned in BOTH directions.

    Crediting a non-literal key invented the evidence line `<line 18>` and
    reported a memo cache — whose contract is "absent or corrupt, we
    recompute" — as decisions going quiet. Crediting a STORE reported a
    read-modify-write ledger the same way. Widening either one back turns this
    red; narrowing literal READS away turns the positive arm red.
    """
    assert not C.scan_source(CONTROL_MEMO_CACHE_RECOMPUTES, "c.py"), (
        "memo.get(rel) names no declared key")
    assert not C.scan_source(CONTROL_LEDGER_WRITES_ARE_NOT_READS, "c.py"), (
        'doc["program"] = ... is a write, not a consultation')
    assert not C.scan_source(CONTROL_ANOTHER_NAMES_KEYS, "c.py"), (
        "another name's keys say nothing about the name that defaulted")

    keys = C.scan_source(DEFECT, "d.py")[0].key_reads
    assert keys == ["'compare_engine'", "'fill_target'"], keys
    assert not any(k.startswith("<line ") for k in keys), (
        "no finding may name a key it could not read off the source")

    subscripted = DEFECT.replace(
        '    return cfg.get("compare_engine", "builtin"), cfg.get("fill_target")',
        '    return cfg["compare_engine"], cfg["fill_target"]')
    assert C.scan_source(subscripted, "s.py"), (
        "a LOAD subscript is a key read and must still count")


def test_the_documented_false_negatives_are_real(tmp_path):
    """KNOWN CONSERVATISM is a list of misses, so it must actually miss them.

    Two rounds were lost to docstrings that promised what the code did not do.
    If a later change starts catching one of these, delete its bullet from the
    module docstring in the same commit — that is what this test is for.
    """
    tuple_target = DEFECT.replace("            cfg = {}\n",
                                  "            cfg, err = {}, None\n")
    assert tuple_target != DEFECT
    assert not C.scan_source(tuple_target, "t.py"), (
        "tuple targets are a DOCUMENTED miss")

    dead_raise = DEFECT.replace(
        "            cfg = {}\n",
        "            cfg = {}\n            if False: raise RuntimeError('x')\n")
    assert not C.scan_source(dead_raise, "t.py"), (
        "a deliberate fake fix is a DOCUMENTED miss, not a structural question")

    respelled = DEFECT.replace("            cfg = {}\n",
                               "            cfg = {}.copy()\n")
    assert not C.scan_source(respelled, "t.py"), (
        "`{}.copy()` is a DOCUMENTED miss of the empty-value vocabulary")

    self_assign = DEFECT.replace("            cfg = {}\n",
                                 "            cfg = cfg\n")
    assert not C.scan_source(self_assign, "t.py"), (
        "`cfg = cfg` is a DOCUMENTED miss of the empty-value vocabulary")

    returning = DEFECT.replace("            cfg = {}\n",
                               "            return {}\n")
    assert not C.scan_source(returning, "t.py"), (
        "a handler that RETURNS is a DOCUMENTED miss: control leaves")

    doc = C.__doc__
    for phrase in ("KNOWN CONSERVATISM", "TUPLE", "FAKE FIX", "RETURN FORM",
                   "EMPTY-VALUE VOCABULARY"):
        assert phrase in doc, f"{phrase} is not disclosed in the docstring"


def test_there_are_no_tuning_flags(tmp_path, capsys):
    """A gate the wiring can narrow at the call site is one it can disarm."""
    target = _write(tmp_path, "runner.py", DEFECT)
    with pytest.raises(SystemExit):
        C.main([str(target), "--window", "1"])
    capsys.readouterr()
    with pytest.raises(SystemExit):
        C.main([str(target), "--min-key-reads", "99"])
    capsys.readouterr()


def test_no_subtree_is_exempt_from_the_census(tmp_path, capsys):
    """Adding one directory name to a skip list dropped 94% of the tree.

    There is no skip list. A defect is a defect wherever it is written, and
    "scanned" is the complete census of what was looked at.
    """
    for where in ("fixtures", "testdata", "a/b/gate_fixtures", "node_modules",
                  ".venv"):
        _write(tmp_path, f"{where}/runner.py", DEFECT)

    rc, out = _run(capsys, tmp_path)

    assert rc == 1, out
    assert "5 file(s) scanned" in out, out
    for where in ("fixtures", "testdata", "gate_fixtures", "node_modules",
                  ".venv"):
        assert where in out, f"{where} was silently dropped from the scan"


# ---------------------------------------------------------------------------
# The scan itself: what it walks, and what it refuses to claim
# ---------------------------------------------------------------------------
def test_the_scan_descends_into_subdirectories(tmp_path, capsys):
    """`rglob` -> `glob` silently shrank a 5595-file scan to 63 and said PASS."""
    target = _write(tmp_path, "sub/pkg/deep/runner.py", DEFECT)
    _write(tmp_path, "top.py", "X = 1\n")

    rc, out = _run(capsys, tmp_path)

    assert rc == 1, out
    assert str(target) in out, "a defect below the root must be reached"


def test_missing_root_refuses(tmp_path, capsys):
    rc, out = _run(capsys, tmp_path / "nowhere")
    assert rc == 2
    assert "[REFUSE]" in out and "no such path" in out


def test_empty_root_refuses(tmp_path, capsys):
    (tmp_path / "empty").mkdir()
    rc, out = _run(capsys, tmp_path / "empty")
    assert rc == 2, out
    assert "[REFUSE]" in out and "0 Python file(s)" in out


def test_an_empty_root_beside_a_populated_one_still_refuses(tmp_path, capsys):
    """One root with files must not vouch for a sibling root with none."""
    _write(tmp_path, "full/ok.py", FIXED_RAISES)
    (tmp_path / "empty").mkdir()

    rc, out = _run(capsys, tmp_path / "full", tmp_path / "empty")

    assert rc == 2, out
    assert str(tmp_path / "empty") in out, out


def test_unparseable_file_refuses(tmp_path, capsys):
    _write(tmp_path, "broken.py", "def f(:\n")
    rc, out = _run(capsys, tmp_path)
    assert rc == 2, out
    assert "[REFUSE]" in out and "SyntaxError" in out


def test_a_finding_outranks_an_unreadable_sibling(tmp_path, capsys):
    """A real finding is never downgraded to "I could not look"."""
    _write(tmp_path, "broken.py", "def f(:\n")
    _write(tmp_path, "runner.py", DEFECT)
    rc, out = _run(capsys, tmp_path)
    assert rc == 1, out


# ---------------------------------------------------------------------------
# The machine answer and the human answer may never disagree
# ---------------------------------------------------------------------------
def test_json_report_records_the_verdict(tmp_path, capsys):
    import json as _json
    target = _write(tmp_path, "runner.py", DEFECT)
    report = tmp_path / "out.json"
    rc, _ = _run(capsys, target, "--json", report)
    assert rc == 1
    data = _json.loads(report.read_text())
    assert data["verdict"] == "FAIL"
    assert data["count"] == 1
    assert data["findings"][0]["line"] == DEFECT_HANDLER_LINE


@pytest.mark.parametrize("name,build", [
    ("unparseable", lambda p: _write(p, "broken.py", "def f(:\n")),
    ("empty_scan", lambda p: (p / "x").mkdir()),
    ("missing_root", lambda p: None),
])
def test_cannot_check_is_never_PASS_in_json_either(tmp_path, capsys, name,
                                                   build):
    """`rc=2` beside `"verdict": "PASS"` is the very defect this batch is about.

    Consumers in this tree branch on the JSON `verdict`, so a CANNOT-CHECK that
    reports itself as PASS is read as a clean tree by every one of them.
    """
    import json as _json
    root = tmp_path / "scan"
    root.mkdir()
    build(root)
    report = tmp_path / "out.json"
    where = root if name != "missing_root" else root / "nowhere"

    rc, out = _run(capsys, where, "--json", report)

    assert rc == 2, out
    data = _json.loads(report.read_text())
    assert data["verdict"] == "CANNOT_CHECK", (
        f'--json said {data["verdict"]!r} while the program exited 2')
    assert data["count"] == 0


# ---------------------------------------------------------------------------
# Comments and string literals cannot move the verdict
# ---------------------------------------------------------------------------
def test_prose_cannot_erase_a_finding(tmp_path, capsys):
    """Appending a comment that CLAIMS the failure is named changes nothing."""
    source = DEFECT + (
        '\n\n# The handler above raises and prints the parse error to stderr.\n'
        'REASSURANCE = "raise RuntimeError; print(..., file=sys.stderr)"\n')
    target = _write(tmp_path, "prose.py", source)

    rc, out = _run(capsys, target)

    assert rc == 1, out
    assert f"{target}:{DEFECT_HANDLER_LINE}:" in out, (
        "the finding must keep its line; prose must not shift the verdict")


def test_prose_cannot_create_a_finding(tmp_path, capsys):
    """A comment SHAPED like the defect, inside correct code, stays green."""
    source = FIXED_RAISES + (
        '\n\n# A cautionary example, in prose only:\n'
        '#     try:\n'
        '#         cfg = json.loads(cfg_f.read_text())\n'
        '#     except Exception:\n'
        '#         cfg = {}\n'
        'BAD_SHAPE = "except Exception:\\n    cfg = {}"\n')
    target = _write(tmp_path, "prose_control.py", source)

    rc, out = _run(capsys, target)

    assert rc == 0, out
