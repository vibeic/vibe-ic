"""Run a native PDK or declared geometry antenna deck and read its actual counts."""
from __future__ import annotations

import argparse
import importlib.util
import json
import posixpath
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from . import _klayout_launch as _kl                     # type: ignore
except ImportError:                                          # standalone gate
    import _klayout_launch as _kl                            # type: ignore
from _atomic_artefact import write_bytes as _atomic_write_bytes  # vibe-ic#1082

PASS, FAIL, SKIP = 0, 1, 2
_NATIVE_STALL_GRACE_S = 1800  # idle time, never a total-runtime deadline
_NATIVE_MEMORY_LIMIT_MB = 32768

# Where a streamed GDS lands, most-final first. Globs only — no design literal.
_GDS_GLOBS = (
    "phase3/stage4/gds/*.gds",
    "phase3/stage3/pnr/*.gds",
    "**/*.gds",
)
# Where the per-PDK antenna deck config may be declared.
_BRIDGE_CFG = "input/pdk/bridge/signoff_config.json"
_BRIDGE_KEY = "antenna_deck"
# The CONFIG filename is subject to the same collision as the report filenames
# (see the naming note in run()): `antenna_report_check` rglobs `*antenna*.json`
# across the WHOLE project and would ingest this deck config as if it were a
# router antenna report — it carries no violation count, so a project that
# adopted the deck would see spurious ANTENNA_VIOLATION_COUNT errors and, with
# no genuine antenna.rpt present, a hard FAIL of the sibling gate. Hence
# "gate_oxide", not "antenna".
_GEOMETRY_CFG_GLOBS = (
    "signoff/gate_oxide_deck.json",
    "input/pdk/bridge/gate_oxide_deck.json",
)
_ROUTER_RECORD = "reports/phase3/antenna.json"
_ROUTER_STATE_RECORD = "reports/phase3/antenna_librelane.json"
# See the naming note in run(): these must NOT match `*antenna*.json`.
#: Where an engine the runner cannot reach is STAGED to, relative to the
#: GDS directory. Must not contain the substring "antenna" for the same
#: reason the report names do not -- see the naming note in run().
_STAGE_REL = "gate_oxide_deck"
_RAW_REPORT_NAME = "gate_oxide_geom_deck_raw.json"
_MATERIALISED_CFG_NAME = "gate_oxide_geom_deck_config.json"


def _first(project: Path, globs) -> Optional[Path]:
    for g in globs:
        hits = sorted(p for p in project.glob(g) if p.is_file())
        if hits:
            return hits[0]
    return None


def _router_report(project: Path, explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        path = Path(explicit)
        path = path if path.is_absolute() else project / path
        if not path.is_file() or path.suffix.lower() == ".log":
            raise ValueError("router antenna report is absent or is an aggregate log")
        return path
    path = project / "reports/phase3/antenna.rpt"
    return path if path.is_file() else None


def _resolve_config(project: Path, explicit: Optional[str]) -> tuple:
    """Return (config_path, deck_dict, source) — deck_dict None when absent.

    A bridge `signoff_config.json` may declare `antenna_deck` either INLINE (a
    dict) or as a path relative to the PDK dir.
    """
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = project / p
        if not p.is_file():
            return None, None, f"config not found: {explicit}"
        return p, json.loads(p.read_text()), f"--config {explicit}"
    bridge = project / _BRIDGE_CFG
    if bridge.is_file():
        try:
            declared = json.loads(bridge.read_text()).get(_BRIDGE_KEY)
        except (ValueError, OSError, AttributeError) as exc:
            return None, None, f"{_BRIDGE_CFG} is unreadable: {exc}"
        if isinstance(declared, dict):
            return None, declared, f"{_BRIDGE_CFG}:{_BRIDGE_KEY} (inline)"
        if isinstance(declared, str):
            p = (bridge.parent / declared).resolve()
            if p.is_file():
                return p, json.loads(p.read_text()), \
                    f"{_BRIDGE_CFG}:{_BRIDGE_KEY} -> {declared}"
            return None, None, (f"{_BRIDGE_CFG}:{_BRIDGE_KEY} points at a "
                                f"missing deck: {declared}")
    found = _first(project, _GEOMETRY_CFG_GLOBS)
    if found:
        return found, json.loads(found.read_text()), \
            str(found.relative_to(project))
    return None, None, "no antenna deck config declared for this PDK"




#: Where a PDK tree keeps its KLayout DRC decks, relative to the PDK directory.
_DECK_DIR = ("libs.tech", "klayout", "tech", "drc")








def _discover_deck(tree: str, read, list_files, list_tree):
    """Discover a PDK's own antenna rule and its runnable parent deck.

    `read`/`list_files` answer from the environment KLayout will run in, so
    the selected files are available to that runner. The rule
    file is not an executable KLayout script on its own: the parent loads
    layers, options and the rule registry. Only a parent that declares the
    native ``decks`` selection grammar may be run with ``decks=antenna``.
    No PDK name, layer number or antenna ratio is supplied by this program.
    """
    drc = posixpath.join(tree, *_DECK_DIR)
    rule = posixpath.join(drc, "rule_decks", "antenna.rb")
    rule_bytes = read(rule)
    standalone = False
    if rule_bytes is None:
        # Some installed PDKs ship the antenna table as a complete executable
        # .drc, not as the selectable parent's antenna.rb fragment.
        rule = posixpath.join(drc, "rule_decks", "antenna.drc")
        rule_bytes = read(rule)
        if rule_bytes is None:
            return None, f"selected PDK has no native antenna rule deck: {rule}"
        source = rule_bytes.decode("utf-8", "replace")
        if not all(token in source for token in ("antenna_check(", "source($input", "report(")):
            return None, "standalone antenna runset does not declare its native input/report/check interface"
        standalone = True
    candidates = list_files(drc, ".drc")
    if candidates is None:
        return None, f"native antenna rule exists, but {drc} could not be listed"
    parents = []
    for candidate in candidates:
        data = read(candidate)
        if data is None:
            return None, f"native deck candidate is unreadable: {candidate}"
        source = data.decode("utf-8", "replace")
        if "decks: $decks" in source and "rule_decks" in source:
            parents.append((candidate, data))
    if standalone:
        parents = [(rule, rule_bytes)]
    if len(parents) != 1:
        return None, (f"native antenna rule exists, but exactly one runnable "
                      f"parent with deck selection was required; found {len(parents)}")
    deck = {"tree": tree, "rule": rule, "parent": parents[0][0], "deck_dir": drc}
    if standalone:
        deck["format"] = "standalone"
    return deck, ""






_NATIVE_RDB = "gate_oxide_native.lyrdb"
_NATIVE_LOG = "gate_oxide_native.log"
#: The native deck's own record of WHICH rule file it executed ...
_DECK_FROM_RE = re.compile(r"Executing deck\s+\S+\s+from\s+(\S+)\s*$", re.M)
#: ... and of its completion tally, printed after every selected deck ran.
_TALLY_RE = re.compile(
    r"DRC RESULT:\s*(SUCCESS|FAILURE)\s*\((\d+)\s+violations?(?:\(s\))?\)")
#: The RDB's own record of the script that generated it.
_GENERATOR_RE = re.compile(r"<generator>\s*drc:\s*script='([^']*)'\s*</generator>")




def _executed_native_decks(log: str) -> set[str]:
    """Read each deck event, including Rich's single-token path continuations.

    Keep event boundaries: a blank, timestamp/level prefix or other message
    cannot be removed to manufacture a path. The reconstructed token still
    has to equal the complete hashed rule in the caller.
    """
    executed = set()
    for match in _DECK_FROM_RE.finditer(log):
        path = match.group(1)
        for line in log[match.end(1):].splitlines()[1:]:
            fragment = line.strip()
            if not re.fullmatch(r"[A-Za-z0-9_./+@%=~-]+", fragment):
                break
            path += fragment
        executed.add(path)
    return executed


def _native_result_count(rdb: Path, transcript: Path, deck: Optional[dict]):
    """Read the native deck completion tally and its RDB error count."""
    log = transcript.read_text(errors="replace")
    if deck is not None and deck.get("format") == "standalone":
        # The native standalone table emits per-rule events and RDB categories,
        # but no parent-framework completion tally. Keep that distinction.
        import _a6_drc_authority as rules
        import eda_report_audit as audit
        text = rdb.read_text(errors="replace")
        generator = _GENERATOR_RE.search(text)
        if generator is None or generator.group(1) != deck["parent"]:
            return None, "standalone RDB does not name the bound native runset", {}
        graded = rules.lyrdb_text_rules(text)["graded"]
        executed = set(re.findall(r"Executing (?:rule )?(Ant\.[A-Za-z0-9_]+)(?=\s|$)", log, re.I))
        if (not graded or any(not re.fullmatch(r"Ant\.[A-Za-z0-9_]+", x, re.I) for x in graded)
                or {x.casefold() for x in graded} != {x.casefold() for x in executed}):
            return None, "standalone executed antenna rules and RDB graded rules are absent/incomplete", {}
        count = audit._antenna_klayout_count(text)
        if count is None:
            return None, "standalone RDB has no usable antenna measurement", {}
        return count, "", {"graded_rules": graded, "checked_gate_nets": None,
                            "coverage_status": "NOT_MEASURED"}
    if not re.search(r"Executing rule\s+ANT\.", log):
        return None, "native transcript names no executed ANT rule", {}
    if deck is None:
        return None, "no native deck identity to bind the transcript to", {}
    executed = _executed_native_decks(log)
    if executed != {deck["rule"]}:
        return None, (f"native transcript executed decks from "
                      f"{sorted(executed) or 'no named rule file'}, not the "
                      f"hashed rule {deck['rule']}"), {}
    tallies = _TALLY_RE.findall(log)
    if len(tallies) != 1:
        return None, (f"native transcript carries {len(tallies)} completion "
                      f"tallies; exactly one is required"), {}
    text = rdb.read_text(errors="replace")
    generator = _GENERATOR_RE.search(text)
    if generator is None or generator.group(1) != deck["parent"]:
        return None, (f"native RDB was generated by "
                      f"{generator.group(1) if generator else 'an unnamed script'}"
                      f", not the hashed parent {deck['parent']}"), {}
    import eda_report_audit as _audit  # existing calibrated KLayout RDB reader
    count = _audit._antenna_klayout_count(text)
    if count is None:
        return None, "native RDB has no usable ANT measurement", {}
    status, tallied = tallies[0][0], int(tallies[0][1])
    if tallied != count or (status == "SUCCESS") != (count == 0):
        return None, (f"native RDB holds {count} violation(s) but the deck's "
                      f"own tally says {status} ({tallied})"), {}
    return count, "", {"transcript_tally": tallied}




def _rdb_red_count(rdb: Path) -> Optional[int]:
    """ANT items in this run's RDB when there are any, else None.

    Read with the same calibrated reader the bound count uses. Used only to
    keep measured violations red when the binding fails; it never makes a
    result green."""
    try:
        text = rdb.read_text(errors="replace")
    except OSError:
        return None
    import eda_report_audit as _audit
    count = _audit._antenna_klayout_count(text)
    return count if count else None




def _native_router_cross_check(project: Path, router: Optional[str], raw: Path,
                                res: dict, count: int) -> dict:
    # Native router reports may be KLayout RDBs.  The plugin's calibrated
    # cross-check reader understands that dialect; an image copy can lag it.
    xtool = Path(__file__).resolve().parent / "gds_antenna" / "xcheck_router.py"
    try:
        rpt = _router_report(project, router)
    except ValueError as exc:
        res["cross_check"] = {"verdict": "NOT_RUN", "selection": "REFUSED", "reason": str(exc)}
        return res
    if xtool is not None and rpt is not None and rpt.is_file():
        try:
            x = _load_module(xtool, "_vibeic_xcheck_router").cross_check(raw, rpt)
            if not isinstance(x, dict) or x.get("verdict") not in (
                    "AGREE", "DISAGREE", "ERROR"):
                raise ValueError("cross-check returned no recognized verdict")
        except Exception as exc:  # noqa: BLE001
            x = {"verdict": "ERROR", "detail": f"cross-check failed: {exc}"}
        res["cross_check"] = {**x, "router_report": str(rpt)}
        if x.get("verdict") == "DISAGREE":
            res.update(verdict="FAIL", reason=f"router-vs-geometry antenna DISAGREEMENT: {x.get('detail')}")
        elif x.get("verdict") == "ERROR":
            reason = x.get("detail") or x.get("error") or "no usable cross-check result"
            res.update(verdict="FAIL" if count else "NOT_MEASURED",
                       measurement="NOT_MEASURED" if count == 0 else "FAIL",
                       failure_class="ROUTER_CROSS_CHECK",
                       reason=f"router-vs-geometry antenna cross-check ERROR: {reason}")
    else:
        res["cross_check"] = {"verdict": "NOT_RUN", "reason": "no router report or cross-check engine"}
    return res


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                             # type: ignore
    return mod


def stage_engine(runner, path: Path, into: Path):
    """`path` as the RUNNER can open it — a copy under `into` when it cannot.

    THE DEFECT THIS EXISTS FOR (vibe-ic#2119). `path` is a HOST path under this
    plugin's own installation, and the runner may be a CONTAINER. The plugin
    tree is not one of the mounts the repo's own container helper creates —
    `tools/vibeic-eda/restart-eda.sh` binds the designs directory and nothing
    else — so on a container built exactly the way this repo says to build one
    the host file exists, the container has no such path, and this gate
    DISCLOSED_SKIPped on every PDK and every design: the one INDEPENDENT
    antenna opinion in the flow never ran, and said so in a line nobody had to
    act on. After vibe-ic#2107 this was the ONLY one of the four KLayout-engine
    callers that did not stage.

    Copying is sound because the engine is self-contained: `antenna_check.py`
    imports only `json`, `os`, `sys` and `pya` and pulls in no sibling of its
    own, so a copy of it is the same program. Same remedy, and for the same
    measured reason, as `die_density_fill_gen.stage_engine`.

    Returns (path_for_the_runner, error_or_None). The error is NEVER folded
    into a skip or a pass: an engine the runner cannot open is this program
    failing, not the design failing and not the deck being undeclared.
    """
    if runner.covers(path):
        return path, None
    dest = into / path.name
    try:
        into.mkdir(parents=True, exist_ok=True)
        # ATOMIC, and not `dest.write_bytes` (vibe-ic#1082): a copy interrupted
        # halfway leaves a TRUNCATED engine at a path that exists, and KLayout
        # would then fail on a syntax error inside this program's own engine —
        # a failure indistinguishable from a defect in the engine itself.
        _atomic_write_bytes(dest, path.read_bytes())
    except OSError as exc:                                   # noqa: BLE001
        return path, (f"{path} is not reachable from the {runner.kind} KLayout "
                      f"environment ({runner.detail}) and could not be staged "
                      f"into {into}: {exc}")
    if not runner.covers(dest):
        return dest, (f"neither {path} nor a copy of it at {dest} is reachable "
                      f"from the {runner.kind} KLayout environment "
                      f"({runner.detail})")
    return dest, None


def run(project: Path, gds: Optional[str], config: Optional[str],
        router: Optional[str], cell: Optional[str]) -> Dict[str, Any]:
    """Return a verdict dict. Verdicts: PASS / FAIL / DISCLOSED_SKIP."""
    def skip(reason: str, **extra) -> Dict[str, Any]:
        return {"verdict": "DISCLOSED_SKIP", "reason": reason,
                "check": "gds_geometry_antenna_deck", **extra}

    cfg_path, deck, cfg_src = _resolve_config(project, config)
    if deck is None:
        if config or cfg_src != "no antenna deck config declared for this PDK":
            return skip(cfg_src, config_source=cfg_src)
        try:
            tree = _native_tree(project)
        except (OSError, ValueError, KeyError) as exc:
            return skip(str(exc), config_source=cfg_src)
        return _run_native(project, gds, router, cell, tree)

    engine = _kl.find_engine("gds_antenna", "antenna_check.py")
    if engine is None:
        return skip("GDS-geometry antenna engine not found "
                    "(gds_antenna/antenna_check.py missing; set "
                    "$VIBEIC_KLAYOUT_TOOLS to a KLayout-fork checkout)")

    gds_path = (Path(gds) if gds else _first(project, _GDS_GLOBS))
    if gds_path is not None and not gds_path.is_absolute():
        gds_path = project / gds_path
    if gds_path is None or not gds_path.is_file():
        return skip("no streamed GDS to check "
                    f"(looked for {', '.join(_GDS_GLOBS)})",
                    config_source=cfg_src)

    runner = _kl.find_runner(project=project)
    if runner is None:
        return skip("no KLayout runner available (no strmrun/klayout on PATH "
                    "and no KLayout in $VIBEIC_EDA_CONTAINER) — the antenna "
                    "geometry deck did NOT run",
                    config_source=cfg_src, gds=str(gds_path))

    work = project / "reports" / "phase3"
    work.mkdir(parents=True, exist_ok=True)
    # NAMING IS LOAD-BEARING: `antenna_report_check` (eda_report_audit --mode
    # antenna) rglobs `*antenna*.json` / `*antenna*.rpt` and treats every hit as
    # a ROUTER antenna report — it would swallow this gate's geometry JSON, find
    # no OpenROAD violation count in it and fail its own authenticity check. So
    # nothing this gate writes may contain the substring "antenna".
    out_json = work / _RAW_REPORT_NAME
    # An inline deck (or a config outside the runner's reach) is materialised
    # beside the output so the runner can always see it.
    if cfg_path is None or not runner.covers(cfg_path):
        cfg_path = work / _MATERIALISED_CFG_NAME
        cfg_path.write_text(json.dumps(deck, indent=2))
    for label, p in (("GDS", gds_path), ("report dir", work)):
        if not runner.covers(p):
            return skip(f"{label} path is not reachable by the KLayout runner "
                        f"({runner.kind}: {runner.detail}): {p}",
                        config_source=cfg_src)
    # NOW the engine can be checked on the side that will OPEN it, and staged
    # into the GDS directory — which the loop above has just proven the runner
    # reaches — when it is not reachable where it is. vibe-ic#2119.
    engine_staged = None
    _orig_engine = engine
    engine, _why = stage_engine(runner, engine, gds_path.parent / _STAGE_REL)
    if _why:
        return {"verdict": "FAIL", "check": "gds_geometry_antenna_deck",
                "config_source": cfg_src, "gds": str(gds_path),
                "runner": f"{runner.kind}:{runner.detail}",
                "reason": (f"this program's antenna geometry engine "
                           f"({_orig_engine.name}) is present on this host but "
                           f"cannot be opened where KLayout runs: {_why}")}
    if engine != _orig_engine:
        engine_staged = str(engine)

    env = {"ANT_GDS": str(gds_path), "ANT_CONFIG": str(cfg_path),
           "ANT_OUT": str(out_json)}
    if cell:
        env["ANT_CELL"] = cell
    if out_json.is_file():
        out_json.unlink()
    rc, out, err = runner.run(engine, env,
                              path_keys=("ANT_GDS", "ANT_CONFIG", "ANT_OUT"),
                              timeout=1800)
    if not out_json.is_file():
        return {"verdict": "FAIL", "check": "gds_geometry_antenna_deck",
                "reason": "antenna geometry deck produced no report",
                "config_source": cfg_src, "gds": str(gds_path),
                "engine_staged": engine_staged,
                "runner": f"{runner.kind}:{runner.detail}", "rc": rc,
                "stderr": (err or "")[-600:], "stdout": (out or "")[-600:]}
    deck_res = json.loads(out_json.read_text())

    res: Dict[str, Any] = {
        "check": "gds_geometry_antenna_deck",
        "runner": f"{runner.kind}:{runner.detail}",
        "config_source": cfg_src, "gds": str(gds_path),
        "engine_staged": engine_staged,
        "worst_ratio": deck_res.get("worst_ratio"),
        "violations": deck_res.get("violations"),
        "deck": deck_res,
    }
    dv = deck_res.get("verdict")
    if dv == "PASS":
        res["verdict"] = "PASS"
    elif dv == "FAIL":
        res["verdict"] = "FAIL"
        res["reason"] = (f"{deck_res.get('violations')} antenna violation(s) in "
                         f"the GDS geometry; worst ratio "
                         f"{deck_res.get('worst_ratio')}")
    else:
        # HONEST_SKIP / ERROR from the engine: the deck was DECLARED but did not
        # produce a usable measurement. Never a pass — see module docstring.
        res["verdict"] = "FAIL"
        res["reason"] = ("antenna deck ran but produced no usable measurement "
                         f"({dv}): {deck_res.get('note') or deck_res.get('error')}"
                         " — a declared deck that cannot measure is not clean")

    # Independent cross-check against the router's own count.
    xtool = _kl.find_engine("gds_antenna", "xcheck_router.py")
    try:
        rpt = _router_report(project, router)
    except ValueError as exc:
        res["cross_check"] = {"verdict": "NOT_RUN", "selection": "REFUSED", "reason": str(exc)}
        return res
    if xtool is not None and rpt is not None and rpt.is_file():
        try:
            xr = _load_module(xtool, "_vibeic_xcheck_router")
            x = xr.cross_check(out_json, rpt)                # type: ignore
        except Exception as exc:                             # noqa: BLE001
            x = {"verdict": "ERROR", "detail": f"cross-check failed: {exc}"}
        x["router_report"] = str(rpt)
        res["cross_check"] = x
        if x.get("verdict") == "DISAGREE":
            res["verdict"] = "FAIL"
            res["reason"] = (
                "router-vs-geometry antenna DISAGREEMENT — one of the two is "
                f"wrong: {x.get('detail')}")
    else:
        res["cross_check"] = {
            "verdict": "NOT_RUN",
            "reason": ("no router antenna report to cross-check against"
                       if rpt is None or not rpt.is_file()
                       else "xcheck_router.py engine not found")}
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Independent GDS-geometry process-antenna sign-off gate.")
    ap.add_argument("project_dir", nargs="?", default=".")
    ap.add_argument("--gds", default=None)
    ap.add_argument("--config", default=None,
                    help="antenna deck config (per-PDK layer stack + ratios)")
    ap.add_argument("--router", default=None,
                    help="router antenna report to cross-check against")
    ap.add_argument("--cell", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="treat a disclosed skip as a FAIL (tapeout sign-off)")
    ns = ap.parse_args(argv)

    project = Path(ns.project_dir).resolve()
    try:
        res = run(project, ns.gds, ns.config, ns.router, ns.cell)
    except Exception as exc:                                 # noqa: BLE001
        res = {"verdict": "FAIL", "check": "gds_geometry_antenna_deck",
               "reason": f"gate error: {exc}"}

    if ns.json_out:
        out = Path(ns.json_out)
        if not out.is_absolute():
            out = project / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=2))

    verdict = res.get("verdict")
    if verdict == "DISCLOSED_SKIP" and ns.strict:
        verdict = "FAIL"
        res["reason"] = f"--strict: {res.get('reason')}"
    if verdict == "DISCLOSED_SKIP":
        # Plugin disclosed-skip tier: rc 2 + sentinel -> VACUOUS-PASS, so the
        # flow report SHOWS the checker did not run instead of reading clean.
        print(f"VACUOUS_PASS: gds_antenna_deck_check did NOT run — "
              f"{res.get('reason')}")
        print(json.dumps(res, indent=2))
        return SKIP
    print(json.dumps(res, indent=2))
    if verdict == "PASS":
        if res.get("method") == "pdk_native_klayout":
            print("gds_antenna_deck_check: PASS "
                  "(0 PDK-native antenna violations on the bound GDS)")
        else:
            print("gds_antenna_deck_check: PASS "
                  f"(0 geometry antenna violations, worst ratio "
                  f"{res.get('worst_ratio')})")
        return PASS
    print(f"gds_antenna_deck_check: {verdict} — {res.get('reason')}")
    return FAIL



















def _native_tree(project, context=None):
    context = context or {}
    config = context.get("config") or {}
    if context.get("pdk_root"):
        return str(context["pdk_root"])
    if config.get("PDK_ROOT") and config.get("PDK"):
        return str(Path(config["PDK_ROOT"]) / config["PDK"])
    from declared_pdk_is_the_pdk_used_check import declared_target
    import analog_pdk_availability as resolver
    target, _ = declared_target(project)
    facts = resolver.resolve_pdk(target)
    if not facts.get("available") or not facts.get("pdk_root"):
        raise ValueError("selected PDK native antenna deck is unavailable")
    return str(facts["pdk_root"])


def _run_native(project, gds, router, cell, tree, *, work=None):
    def skip(reason):
        return {"verdict": "DISCLOSED_SKIP", "measurement": "NOT_MEASURED", "reason": reason}
    runner = _kl.find_runner(project=project)
    if runner is None:
        return skip("no KLayout runner is available")
    native, why = _discover_deck(tree, runner.read_bytes, runner.list_files, runner.list_tree)
    if native is None:
        return skip(why)
    gds_path = Path(gds) if gds else _first(project, _GDS_GLOBS)
    if gds_path is not None and not gds_path.is_absolute():
        gds_path = project / gds_path
    if gds_path is None or not gds_path.is_file() or not runner.covers(gds_path):
        return skip("no streamed GDS reachable by the native KLayout runner")
    work = Path(work) if work else project / "reports/phase3"
    work.mkdir(parents=True, exist_ok=True)
    rdb, transcript = work / _NATIVE_RDB, work / _NATIVE_LOG
    for path in (rdb, transcript):
        path.unlink(missing_ok=True)
    argv = [runner.klayout_bin(), "-b", "-r", native["parent"],
            "-rd", f"input={runner.cpath(gds_path)}",
            "-rd", f"report={runner.cpath(rdb)}"]
    if native.get("format") == "standalone":
        argv.extend(["-rd", "threads=1", "-rd", "run_mode=deep",
                     "-rd", f"log={runner.cpath(work / 'native_runset.log')}"])
    else:
        argv.extend(["-rd", "decks=antenna"])
    if cell:
        argv.extend(["-rd", f"topcell={cell}"])
    execution = runner.run_argv_supervised(
        argv, {}, stall_grace_s=_NATIVE_STALL_GRACE_S,
        memory_limit_mb=_NATIVE_MEMORY_LIMIT_MB, progress_paths=(rdb,))
    transcript.write_text((execution.out or "") + (execution.err or ""))
    result = {"check": "gds_geometry_antenna_deck", "method": "pdk_native_klayout",
              "gds": str(gds_path), "rdb": str(rdb), "transcript": str(transcript),
              "rc": execution.rc, "argv": argv, "outcome": execution.outcome}
    red = _rdb_red_count(rdb) if rdb.is_file() else None
    if red:
        return {**result, "verdict": "FAIL", "measurement": "FAIL", "violations": red}
    if execution.rc or not rdb.is_file():
        return {**result, "verdict": "DISCLOSED_SKIP", "measurement": "NOT_MEASURED",
                "reason": "native deck did not complete"}
    count, why, details = _native_result_count(rdb, transcript, native)
    if count is None:
        return {**result, "verdict": "DISCLOSED_SKIP", "measurement": "NOT_MEASURED", "reason": why}
    result.update(details, violations=count,
                  verdict="FAIL" if count else "PASS", measurement="MEASURED")
    if count == 0 and details.get("coverage_status") == "NOT_MEASURED":
        result.update(verdict="DISCLOSED_SKIP", measurement="NOT_MEASURED",
                      reason="checked gate/net population is not reported")
    raw = work / _RAW_REPORT_NAME
    raw.write_text(json.dumps({'verdict': result['verdict'], 'violations': count}))
    return _native_router_cross_check(project, router, raw, result, count)


def execute(project, context):
    project = Path(project).resolve()
    state = context.get("state") or {}
    gds = context.get("gds") or state.get("gds")
    try:
        tree = _native_tree(project, context)
        result = _run_native(project, gds, context.get("router"), context.get("top"), tree)
    except (OSError, ValueError, KeyError) as exc:
        result = {"verdict": "DISCLOSED_SKIP", "measurement": "NOT_MEASURED", "reason": str(exc)}
    result["component_status"] = result["verdict"] if result["verdict"] in {"PASS", "FAIL"} else "NOT_MEASURED"
    return result


if __name__ == "__main__":
    sys.exit(main())
