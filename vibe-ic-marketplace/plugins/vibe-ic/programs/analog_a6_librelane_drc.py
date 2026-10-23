#!/usr/bin/env python3
"""analog_a6_librelane_drc.py — A6 per-block DRC through LibreLane (T94).

Runs LibreLane `KLayout.DRC` (the PDK's sign-off runset, as LibreLane's PDK
configuration names it) and `Magic.DRC` on the block's A5 GDS, through
`librelane_contract.run_chain` (`python3 -m librelane.steps run`, GDS-only
state), and writes `phase3/analog/<block>/a6_librelane_drc.json`:

  * per engine: the step's own metric (`klayout__drc_error__count`,
    `magic__drc_error__count`) and the violations per rule read from the
    step's own lyrdb report;
  * the GRADED-RULE UNION: every rule the KLayout runset graded (its lyrdb
    lists each graded rule as a category, fired or not), and every rule Magic
    fired that the runset does not grade;
  * the native A6 attribution beside it: a Magic rule the sign-off deck does
    not grade is only ever excused when A6's own attribution
    (`analog_a6_drc_attribute`) classes it as the PDK's own gencell
    (`DEVICE_CELL`). Anything else is `blocking`.

LibreLane itself runs the two engines separately and compares only totals
(ERROR_ON_MAGIC_DRC / ERROR_ON_KLAYOUT_DRC); the union and the attribution are
the vibe-ic layer on top of the tool's output.

THE EXTRA-RULES DECK AND THE AUTHORITY RULE (q1, T109). The PDK's KLayout
sign-off is its main runset PLUS the extra-rules runset(s) it ships beside it
(`rule_decks/*_maximal.drc`), which the PDK's own `run_drc.py` runs by
default; LibreLane runs only `KLAYOUT_DRC_RUNSET`. So `KLayout.DRC` runs
once more per extra runset (namespace `a6_klayout_drc_extra*`), and the
authoritative graded set is the union of every pass. An extra runset that is
present but grades nothing is NOT_MEASURED, never CLEAN. On top of the union
`_a6_drc_authority.authority` decides: any authoritative hit FAILs (inside a
PDK device cell too); a rule Magic fires that an authoritative deck graded
with 0 is deferred only when a CAPABILITY CONTROL shows the same deck firing
it on the PDK's unit FAIL testcase; `ENGINE_ARTEFACT` is reported when the
bare-device GDS round trip also reproduces it.

MEASURED on vibeic-eda 0.3.79 / u_hawaii_adc: Magic.DRC on the GDS reports
M2.d (60 / 816 rectangles) and MIM.e (4 / 92). MIM.e is a Magic-engine
artefact of GDS read-back — IHP's extra deck grades MIM.e and reports 0 on
both blocks and fires it on the unit `mim.gds`. M2.d is REAL (Mn.d
0.144 um2): the extra deck fires it 20 (ldo) / 14 deep, 272 flat
(delta_sigma), and it FAILs; its fix belongs to A5, not here.

Exit codes: 0 record written and nothing blocking; 1 record written with a
blocking rule; 2 honest gap (no GDS / no layout record); 69 environment
refusal. chip-AGNOSTIC.
"""
from __future__ import annotations

import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

import _a6_drc_authority as _auth
import _analog_producer_common as _pc
from _atomic_artefact import write_bytes, write_json

PRODUCER = "analog_a6_librelane_drc"
ENGINES = (("KLayout.DRC", "klayout__drc_error__count", "drc.klayout.lyrdb"),
           ("Magic.DRC", "magic__drc_error__count", "drc.magic.lyrdb"))


def _rule_name(raw: Optional[str]) -> str:
    return (raw or "").strip().strip("'\"").strip()


def lyrdb_rules(path: Path) -> Dict[str, object]:
    """`{"graded": [...], "violations": {rule: n}}` from a KLayout report
    database. Each `<category>` is a rule the engine GRADED; each `<item>`
    one violation of the rule it names. Parsed as XML, never scraped."""
    root = ET.parse(path).getroot()
    graded = sorted({_rule_name(c.findtext("name"))
                     for c in root.iter("category")} - {""})
    hits = Counter(_rule_name(i.findtext("category")) for i in root.iter("item"))
    hits.pop("", None)
    return {"graded": graded, "violations": dict(sorted(hits.items()))}


def union(klayout: dict, magic: dict, device_cell_rules: set) -> dict:
    """The graded-rule union of the two engines' outputs."""
    graded = set(klayout["graded"])
    ungraded_fired = {r: n for r, n in magic["violations"].items()
                      if r not in graded}
    excused = {r: n for r, n in ungraded_fired.items() if r in device_cell_rules}
    blocking = dict(klayout["violations"])
    blocking.update({f"magic:{r}": n for r, n in ungraded_fired.items()
                     if r not in device_cell_rules})
    return {"signoff_rules_graded": len(graded),
            "signoff_violations": klayout["violations"],
            "magic_rules_the_signoff_deck_does_not_grade": ungraded_fired,
            "magic_deferred_to_signoff_deck": {
                r: n for r, n in magic["violations"].items() if r in graded},
            "excused_as_pdk_device_cell": excused,
            "blocking": blocking}


def native_device_cell_rules(attribution: Optional[dict]) -> set:
    """Rule ids A6's own attribution classes as the PDK's gencell."""
    import analog_a6_native_pv as nat
    out = set()
    rules = (((attribution or {}).get("by_class_and_rule") or {})
             .get("DEVICE_CELL") or {})
    for message in rules:
        rid = nat.rule_id(message)
        if rid:
            out.add(rid)
    return out


def _image_run(image: str, entrypoint: str, args: List[str],
               docker: str = "docker") -> "subprocess.CompletedProcess":
    """One throw-away container of the pinned image: a PDK file lives there
    and nowhere on this host."""
    import _docker_memory as _dmem
    from librelane_contract import PROBE_DEADLINE_S, run_container
    return run_container(
        [docker, "run", "--rm", *_dmem.docker_memory_flags(),
         "--entrypoint", entrypoint, image, *args],
        probe_deadline_s=PROBE_DEADLINE_S)


def image_extra_runsets(image: str, main_runset: str) -> List[str]:
    """The extra-rules runsets beside `main_runset` INSIDE the image, by the
    authority module's glob (never by a literal file name)."""
    pattern = str(Path(main_runset).parent / _auth.EXTRA_RUNSET_GLOB)
    cp = _image_run(image, "sh", ["-c", f'for f in {pattern}; do '
                                        f'[ -f "$f" ] && echo "A6EXTRA $f"; '
                                        f'done; true'])
    if cp.returncode:
        raise RuntimeError(f"could not list {pattern} in the image "
                           f"(rc={cp.returncode})")
    return sorted(line.split(" ", 1)[1].strip()
                  for line in cp.stdout.splitlines()
                  if line.startswith("A6EXTRA "))


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower() or "x"


class _Arm:
    """The LibreLane steps this arm runs, over one resolved step config each.

    Everything goes through `librelane_contract` (`resolve_step_config`,
    `run_chain`, `judge_step`); nothing here invokes a tool directly except
    the two read-only image queries above."""

    def __init__(self, project: Path, image: str, pdk: str, pdk_root: str,
                 work: Path):
        import librelane_contract as lc
        self.lc, self.project, self.image = lc, project, image
        self.pdk, self.pdk_root, self.work = pdk, pdk_root, work
        self.configs: Dict[str, dict] = {}

    def config(self, step: str, block: str) -> dict:
        if step not in self.configs:
            slug = step.lower().replace(".", "_")
            src = self.work / f"{slug}.src.json"
            write_json(src, {"meta": {"version": 2, "step": step},
                             "DESIGN_NAME": block, "PDK": self.pdk})
            cfg = self.lc.resolve_step_config(self.project, self.image, src,
                                              self.work / f"{slug}.json",
                                              pdk_root=self.pdk_root)
            resolved = json.loads(cfg.read_text())
            resolved.setdefault("meta", {})["step"] = step
            self.configs[step] = resolved
        return dict(self.configs[step])

    def run(self, step: str, cfg: dict, state: Path, namespace: str,
            cfg_name: str, retries: int = 0) -> Path:
        path = self.work / f"{cfg_name}.json"
        write_json(path, cfg)
        for attempt in range(retries + 1):
            try:
                return self.lc.run_chain(self.project, self.image,
                                         [(step, path, state)],
                                         namespace=namespace,
                                         pdk_root=self.pdk_root)[-1]
            except self.lc.Refusal as exc:
                if exc.code != "LL_STEP_FAILED" or attempt == retries:
                    raise


def run(project: Path, block: str, image: str,
        attribution: Optional[dict] = None, container: str = "",
        roundtrip_runner=None) -> int:
    import librelane_contract as lc
    import analog_a7_post_layout_emit as a7

    bdir = project / "phase3" / "analog" / block
    out = bdir / "a6_librelane_drc.json"
    record: dict = {"producer": PRODUCER, "schema": 2, "block": block,
                    "image": image}
    gds = bdir / f"{block}.gds"
    try:
        tech = a7.layout_tech(bdir)
    except ValueError as exc:
        tech = None
        why = str(exc)
    if not gds.is_file() or tech is None:
        print(f"{_pc.HONEST_GAP_TOKEN} {PRODUCER}: "
              f"{'no ' + gds.name if not gds.is_file() else why}",
              file=sys.stderr)
        return 2
    pdk, pdk_root = tech.parents[2].name, str(tech.parents[3])
    record.update({"pdk": pdk, "pdk_root": pdk_root,
                   "gds_sha256": _sha256(gds)})
    work = bdir / "a6_librelane"
    work.mkdir(parents=True, exist_ok=True)
    state_in = work / "state_in.json"
    write_json(state_in, {"gds": str(gds.resolve()), "metrics": {}})
    arm = _Arm(project, image, pdk, pdk_root, work)

    def refused(step: str, exc: "lc.Refusal") -> int:
        # A tool the contract STOPPED (no progress, or a probe past its
        # deadline) never answered: the environment tier with that reason,
        # never the `FAIL:` a finding about the layout earns.
        stopped = lc.tool_stop_reason(exc.code)
        rc = _pc.EX_ENV_REFUSED if stopped or exc.code in (
            "LL_IMAGE_INCAPABLE", "LL_CONFIG_RESOLVE_FAILED") else 1
        record.update({"result": "NOT_MEASURED", "rule": exc.code,
                       "detail": f"{step}: {exc}"})
        if stopped:
            record["reason_class"] = stopped
        write_json(out, record)
        tok = _pc.ENV_REFUSED_TOKEN if rc == _pc.EX_ENV_REFUSED else "FAIL:"
        print(f"{tok} {PRODUCER} {step}: {exc}", file=sys.stderr)
        return rc

    def graded_nothing(detail: str, engines: dict) -> int:
        record.update({"engines": engines, "result": "NOT_MEASURED",
                       "rule": "A6_LL_SIGNOFF_GRADED_NOTHING",
                       "detail": detail})
        write_json(out, record)
        print(f"FAIL: {PRODUCER}: {detail}", file=sys.stderr)
        return 1

    def measure(step: str, metric: str, report: str, cfg: dict,
                namespace: str, cfg_name: str, state: Path = state_in,
                retries: int = 0) -> dict:
        folder = arm.run(step, cfg, state, namespace, cfg_name, retries)
        judged = lc.judge_step(folder, [metric],
                               work / f"{cfg_name}.judge.json",
                               required_reports=[f"reports/{report}"],
                               scope={"block": block, "gds": str(gds)})
        rpt = folder / "reports" / report
        rules = lyrdb_rules(rpt) if rpt.is_file() else {"graded": [],
                                                        "violations": {}}
        rec = {"step_dir": str(folder.relative_to(project)),
               "judge": judged["verdict"],
               "metric": judged["metrics"][metric], **rules}
        n = judged["metrics"][metric].get("value")
        if isinstance(n, int) and n != sum(rules["violations"].values()):
            rec["report_disagrees_with_metric"] = True
        return rec

    engines: Dict[str, dict] = {}
    for step, metric, report in ENGINES:
        slug = step.lower().replace(".", "_")
        try:
            engines[step] = measure(step, metric, report,
                                    arm.config(step, block),
                                    f"analog/{block}/a6_{slug}", slug)
        except lc.Refusal as exc:
            return refused(step, exc)
    k, m = engines["KLayout.DRC"], engines["Magic.DRC"]
    if k["judge"] != "PASS" or not k["graded"]:
        return graded_nothing("the KLayout runset graded no rule — silence "
                              "is not a clean deck", engines)

    # THE EXTRA-RULES RUNSET(S). The PDK's sign-off is its main runset plus
    # the extra runset(s) beside it; a rule only the extra deck grades was
    # graded by NO deck in this arm before, so Magic's word on it stood alone.
    kcfg = arm.config("KLayout.DRC", block)
    main_runset = str(kcfg.get("KLAYOUT_DRC_RUNSET") or "")
    extras: List[str] = []
    if main_runset:
        try:
            extras = image_extra_runsets(image, main_runset)
        except lc.Refusal as exc:
            record["engines"] = engines
            return refused("extra runset listing", exc)
        except RuntimeError as exc:
            record.update({"engines": engines, "result": "NOT_MEASURED",
                           "rule": _auth.EXTRA_RUNSET_GRADED_NOTHING,
                           "detail": str(exc)})
            write_json(out, record)
            print(f"FAIL: {PRODUCER}: {exc}", file=sys.stderr)
            return 1
    passes = {main_runset or "KLayout.DRC": k}
    opts = dict(kcfg.get("KLAYOUT_DRC_OPTIONS") or {})
    threads = str(kcfg.get("KLAYOUT_DRC_THREADS") or os.cpu_count() or 1)
    extra_cfgs: Dict[str, dict] = {}
    for runset in extras:
        stem = _slug(Path(runset).stem)
        cfg = dict(kcfg, KLAYOUT_DRC_RUNSET=runset,
                   KLAYOUT_DRC_OPTIONS={**opts, "run_mode": "deep",
                                        "threads": threads})
        extra_cfgs[runset] = cfg
        ns = (f"analog/{block}/a6_klayout_drc_extra" if len(extras) == 1
              else f"analog/{block}/a6_klayout_drc_extra_{stem}")
        try:
            # ONE RETRY, RECORDED: the image's KLayout has been measured to
            # segfault in its deep-shape-store destructor AFTER a complete
            # report (1 in 5 runs on one block). A second failure stands.
            rec = measure("KLayout.DRC", "klayout__drc_error__count",
                          "drc.klayout.lyrdb", cfg, ns,
                          f"klayout_drc_extra_{stem}", retries=1)
        except lc.Refusal as exc:
            return refused(f"KLayout.DRC extra {runset}", exc)
        rec["runset"] = runset
        if rec["judge"] != "PASS" or not rec["graded"]:
            engines[f"KLayout.DRC extra {Path(runset).name}"] = rec
            return graded_nothing(
                f"the extra runset {runset} graded no rule — present but "
                f"silent is NOT_MEASURED, never clean", engines)
        if rec["violations"]:
            # WHAT A DEEP COUNT COUNTS. Deep mode reports one marker per
            # unique cell; the flat run counts every instance. Disclosure
            # only — the verdict is the same either way.
            try:
                flat = measure("KLayout.DRC", "klayout__drc_error__count",
                               "drc.klayout.lyrdb",
                               dict(cfg, KLAYOUT_DRC_OPTIONS={
                                   **cfg["KLAYOUT_DRC_OPTIONS"],
                                   "run_mode": "flat"}),
                               ns + "_flat", f"klayout_drc_extra_{stem}_flat",
                               retries=1)
                rec["flat_counts"] = flat["violations"]
            except lc.Refusal as exc:
                rec["flat_counts"] = f"NOT_MEASURED: {exc}"
        engines[f"KLayout.DRC extra {Path(runset).name}"] = rec
        passes[runset] = rec
    klayout = _auth.merge_passes(passes)
    u = union(klayout, m, native_device_cell_rules(attribution))

    # CAPABILITY CONTROLS for every rule the engines disagree on.
    dis = _auth.disagreements(klayout, m["violations"])
    capability: Dict[str, dict] = {}
    if dis:
        try:
            capability = _capability_controls(
                arm, block, image, main_runset,
                {main_runset: kcfg, **extra_cfgs} if main_runset else {},
                sorted(dis))
        except lc.Refusal as exc:
            record.update({"engines": engines,
                           "authoritative_runsets": [r for r in
                                                     [main_runset, *extras] if r],
                           "union": u})
            return refused("capability controls", exc)
    roundtrip = None
    if dis:
        roundtrip = (roundtrip_runner or _default_roundtrip)(
            project, block, container, sorted(dis),
            [r for r in [main_runset, *extras] if r])
    auth = _auth.authority(klayout, m["violations"],
                           native_device_cell_rules(attribution),
                           capability, roundtrip)
    if roundtrip is not None:
        auth["roundtrip"] = roundtrip
    record.update({"engines": {s: {kk: vv for kk, vv in e.items()
                                   if kk != "graded"}
                               for s, e in engines.items()},
                   "authoritative_runsets": [r for r in [main_runset, *extras]
                                             if r],
                   "union": u, "authority": auth,
                   "result": "BLOCKING" if auth["blocking"] else "CLEAN"})
    write_json(out, record)
    print(f"[{PRODUCER}] block={block} KLayout.DRC graded "
          f"{len(klayout['graded'])} rule(s) over {len(passes)} runset(s), "
          f"{sum(klayout['violations'].values())} violation(s); Magic.DRC "
          f"{sum(m['violations'].values())} violation(s); engine_artefact="
          f"{sorted(auth['engine_artefact']) or 'none'}; blocking="
          f"{auth['blocking'] or 'none'}")
    return 1 if auth["blocking"] else 0


_UNIT_PAYLOAD_MARKER = "VIBEIC_UNIT_TESTCASE_B64="


def _unit_case_bytes(stdout: str) -> bytes:
    """Read one framed testcase; image startup logging is not file content."""
    import base64
    payloads = [line[len(_UNIT_PAYLOAD_MARKER):] for line in stdout.splitlines()
                if line.startswith(_UNIT_PAYLOAD_MARKER)]
    if len(payloads) != 1 or not payloads[0]:
        raise ValueError("native unit testcase payload is absent or ambiguous")
    return base64.b64decode(payloads[0], validate=True)


def _capability_controls(arm: "_Arm", block: str, image: str,
                         main_runset: str, cfgs: Dict[str, dict],
                         rules: List[str]) -> Dict[str, dict]:
    """Run every authoritative deck on the PDK's unit testcases that name a
    disagreeing rule, through the same LibreLane `KLayout.DRC` step.

    The testcases are the PDK's own (`<main deck dir>/testing/testcases/unit`
    inside the image), matched to a rule by the labels they carry; each is
    copied out of the image once, into this arm's own area, and cached by
    `run_chain`'s fingerprint across blocks."""
    lc = arm.lc
    unit_dir = str(Path(main_runset).parent / _auth.UNIT_TESTCASE_DIR) \
        if main_runset else ""
    cap_root = arm.project / "phase3" / "librelane" / "analog" / "_capability"
    cache = cap_root / "unit_labels.json"
    labels = None
    if unit_dir:
        try:
            doc = json.loads(cache.read_text())
            if doc.get("image") == image and doc.get("unit_dir") == unit_dir:
                labels = doc.get("labels")
        except (OSError, ValueError):
            labels = None
        if labels is None:
            cp = _image_run(image, "python3", ["-c", _auth.UNIT_LABEL_SCRIPT,
                                               unit_dir])
            labels = _auth.parse_unit_labels(cp.stdout) or {}
            write_json(cache, {"image": image, "unit_dir": unit_dir,
                               "labels": labels})
    out: Dict[str, dict] = {}
    results: Dict[str, Optional[dict]] = {}
    for rule in rules:
        tcs = _auth.testcases_for_rule(labels or {}, rule)
        for tc in tcs:
            if tc in results:
                continue
            top = ((labels or {}).get(tc) or {}).get("top") or []
            dst = cap_root / "unit" / tc
            if not dst.is_file():
                import _docker_memory as _dmem
                from librelane_contract import PROBE_DEADLINE_S, run_container
                cp = run_container(
                    ["docker", "run", "--rm", *_dmem.docker_memory_flags(),
                     "--entrypoint", "python3", image, "-c",
                     "import base64,pathlib,sys;print(" + repr(_UNIT_PAYLOAD_MARKER) +
                     "+base64.b64encode(pathlib.Path(sys.argv[1]).read_bytes()).decode())",
                     f"{unit_dir}/{tc}"], probe_deadline_s=PROBE_DEADLINE_S)
                if cp.returncode or not cp.stdout:
                    results[tc] = None
                    continue
                try:
                    payload = _unit_case_bytes(cp.stdout)
                except ValueError:
                    results[tc] = None
                    continue
                write_bytes(dst, payload)
            if len(top) != 1:
                results[tc] = None
                continue
            state = cap_root / "unit" / f"{tc}.state_in.json"
            write_json(state, {"gds": str(dst.resolve()), "metrics": {}})
            passes: Dict[str, dict] = {}
            ok = True
            for runset, cfg in cfgs.items():
                rs = _slug(Path(runset).stem)
                try:
                    folder = arm.run("KLayout.DRC",
                                     dict(cfg, DESIGN_NAME=top[0]), state,
                                     f"analog/_capability/{_slug(tc)}/{rs}",
                                     f"capability_{_slug(tc)}_{rs}",
                                     retries=1)
                except lc.Refusal:
                    ok = False
                    break
                rpt = folder / "reports" / "drc.klayout.lyrdb"
                passes[runset] = (lyrdb_rules(rpt) if rpt.is_file()
                                  else {"graded": [], "violations": {}})
            results[tc] = _auth.merge_passes(passes) if ok else None
        out[rule] = _auth.capability_record(rule, tcs, results)
    return out


def _default_roundtrip(project: Path, block: str, container: str,
                       rules: List[str], decks: List[str]) -> Optional[dict]:
    """The bare-device GDS round trip (ENGINE_ARTEFACT conditions ii/iii),
    measured by A6's own attribution program in the EDA container. Without a
    container it is NOT_MEASURED, and no rule is called an engine artefact."""
    if not container:
        return {"result": "NOT_MEASURED",
                "reason": "no EDA container named; the round trip runs Magic"}
    import analog_a6_drc_attribute as att
    dst = (project / "phase3" / "librelane" / "analog" / block
           / "a6_gds_roundtrip.json")
    argv = [str(project), "--block", block, "--container", container,
            "--json", str(dst), "--gds-roundtrip"]
    for r in rules:
        argv += ["--rule", r]
    for d in decks:
        argv += ["--klayout-deck", d]
    try:
        att.main(argv)
        doc = json.loads(dst.read_text())
    except (OSError, ValueError, SystemExit, RuntimeError) as exc:
        return {"result": "NOT_MEASURED", "reason": str(exc)}
    return doc.get("gds_roundtrip") or {"result": "NOT_MEASURED",
                                        "reason": doc.get("reason", "")}


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: Optional[List[str]] = None) -> int:
    ap = _pc.ProducerArgumentParser(prog=PRODUCER,
                                    description=__doc__.split("\n")[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--block", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--attribution", type=Path, default=None,
                    help="analog_a6_drc_attribute --json report for the block")
    ap.add_argument("--container", default="",
                    help="the EDA container the bare-device GDS round trip "
                         "(ENGINE_ARTEFACT) runs Magic in; absent -> that "
                         "evidence is NOT_MEASURED")
    a = ap.parse_args(argv)
    att = None
    if a.attribution and a.attribution.is_file():
        att = json.loads(a.attribution.read_text())
        if isinstance(att.get("blocks"), dict):
            att = att["blocks"].get(a.block, att)
    return run(a.project.resolve(), a.block, a.image, att, a.container)


if __name__ == "__main__":
    sys.exit(main())
