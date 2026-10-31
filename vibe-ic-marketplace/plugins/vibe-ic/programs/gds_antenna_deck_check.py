#!/usr/bin/env python3
"""gds_antenna_deck_check.py — independent GDS-geometry process-antenna sign-off.

WHAT GAP THIS CLOSES
--------------------
Step 26 (antenna) previously had exactly ONE opinion: `antenna_report_check.py`,
which parses the count OpenROAD's own `check_antennas` wrote. That is a
ROUTER-REPORT consumer — it can only repeat what the router already believed. If
the router's antenna model misses a violation, the report is clean and the gate
passes, with no second opinion anywhere in the flow.

This gate adds the missing INDEPENDENT GDS opinion. When the selected PDK ships
a native KLayout antenna deck, it runs that deck on the STREAMED GDS and judges
the deck's own ANT rules. The PDK bridge receipt selects the tree. A tree the
receipt RESOLVED from the EDA image is read and executed only inside a
container running that exact image id -- never from the host cache copy; the
report binds the PDK rule and runnable parent (hashed from the bytes KLayout
reads), GDS, RDB and transcript by SHA-256, and a count is accepted only when
the transcript names the hashed rule, the RDB names the hashed parent, and the
deck's own completion tally equals the RDB's item count.

For a PDK that instead declares a JSON geometry config, it runs the KLayout
fork's GDS-geometry engine (`gds_antenna/antenna_check.py`) and computes, per
metal layer, the per-net antenna ratio
    ratio = (connected metal area) / (connected gate area)
from the as-fabricated geometry, using STAGED connectivity (at the layer-k etch
stage only layers 1..k exist, so an upper-metal jumper cannot relieve a
lower-stage antenna — a relief the router's final-netlist view credits) plus
cumulative-antenna-area (CAA) charge sharing, which no per-layer check can see.
Those staged/CAA claims apply to the JSON engine; the native path measures the
rules its PDK actually executes and does not infer an extra rule class.

It does NOT replace `antenna_report_check` — both run at Step 26. Where a router
report exists, the two independent counts are CROSS-CHECKED
(`gds_antenna/xcheck_router.py`): a clean/dirty DISAGREEMENT is a hard FAIL, so a
router-vs-geometry inconsistency is SURFACED rather than averaged away.

HONEST DEGRADATION (§4.05)
--------------------------
A step that passes because the checker never ran is a false PASS. Every
non-execution here is a NAMED, DISCLOSED skip written into the report JSON and
printed with the plugin's `VACUOUS_PASS:` sentinel at rc 2, which
`flow_compliance_check` renders as VACUOUS-PASS — never a bare PASS. Note the
exit-code remap versus the fork's reference wrapper: the fork used rc 3 for
honest-skip, but rc 3 is this plugin's PASS_WITH_WAIVERS code and a rc 3 without
the waiver sentinel reads as FAIL, so the disclosed skip is rc 2 here.

A deck config that IS present but matches no gate geometry is a FAIL, not a skip:
the PDK declared an antenna deck and it did not work, which is exactly the
"checker didn't run" case that must never read as clean. `--strict` additionally
turns every disclosed skip into a FAIL (tapeout use).

chip/PDK-AGNOSTIC: the layer stack and the per-metal ratio bounds come entirely
from the caller's deck config; no vendor, foundry or design literal appears here.

    gds_antenna_deck_check <project_dir> [--gds G] [--config C] [--router R]
                           [--cell TOP] [--json OUT] [--strict]
    main(argv) -> int : 0 PASS / 1 FAIL / 2 DISCLOSED SKIP
"""
from __future__ import annotations

import argparse
import hashlib
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
# The PDK-root receipt is emitted by the PDK bridge used by the real backend.
# It names both the selected PDK and the image-bound tree, so discovery cannot
# accidentally borrow an antenna deck from another installed PDK.
_PDK_ROOT_RECEIPT = "phase3/librelane_pdk_root.provenance.json"
_CFG_GLOBS = _GEOMETRY_CFG_GLOBS + (_PDK_ROOT_RECEIPT,)
_ROUTER_GLOBS = (
    "reports/phase3/antenna.rpt",
    "**/antenna*.rpt",
)
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


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


_IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")
#: Where a PDK tree keeps its KLayout DRC decks, relative to the PDK directory.
_DECK_DIR = ("libs.tech", "klayout", "tech", "drc")


def _pdk_receipt(project: Path):
    """The PDK tree the run's backend read, as its PDK-root receipt names it.

    A receipt RESOLVED from the EDA image carries the image id and the tree's
    path inside that image (`guest_path`). That pair, not the host cache copy
    beside it, is the identity of the tree: the copy is a convenience
    extraction whose bytes nothing re-verifies against the image.
    """
    receipt = project / _PDK_ROOT_RECEIPT
    if not receipt.is_file():
        return None, "no PDK-root bridge receipt to discover an antenna deck"
    try:
        doc = json.loads(receipt.read_text())
        root = Path(doc["path"])
        # librelane_contract.pdk_root_resolution writes two shapes: RESOLVED
        # ({path, source, derivation: {pdk, image_id, guest_path, ...}}) and
        # DECLARED ({path, source, declared_by, pdk}), whose root is a host
        # tree the declaration names and which carries no derivation.
        derivation = doc.get("derivation")
        if doc.get("source") == "local_provider":
            from librelane_contract import Refusal
            from librelane_signoff_evidence import _retained_local_provider
            from tapeout_precheck import resolve_pdk
            try:
                provider = _retained_local_provider(
                    project, doc.get("provider"), doc.get("identity"))
            except Refusal as exc:
                raise ValueError(str(exc)) from exc
            selected, _ = resolve_pdk(project)
            if (root.resolve() != Path(provider.pdk_root).resolve()
                    or (provider.pdk and provider.pdk != doc.get("pdk"))
                    or (selected and selected != doc.get("pdk"))):
                raise ValueError("LOCAL PDK root or selected PDK differs from its producer")
            derivation = {"pdk": doc.get("pdk")}
        if doc.get("source") == "declared" and derivation is None:
            if "pdk" not in doc:
                raise ValueError(
                    f"declared PDK root ({doc.get('declared_by') or 'undeclared'})"
                    " names no PDK")
            derivation = {"pdk": doc["pdk"]}
        if not isinstance(derivation, dict):
            raise ValueError("receipt names neither a resolved derivation nor "
                             "a declared PDK root")
        pdk = derivation.get("pdk")
        if not isinstance(pdk, str) or not pdk or "/" in pdk or pdk in (".", ".."):
            raise ValueError("invalid PDK identity")
        image_id = derivation.get("image_id")
        guest = derivation.get("guest_path")
        if image_id is not None or guest is not None:
            if not (isinstance(image_id, str) and _IMAGE_ID_RE.fullmatch(image_id)):
                raise ValueError(f"image id {image_id!r} names no image bytes")
            if not (isinstance(guest, str) and guest.startswith("/")
                    and posixpath.basename(posixpath.normpath(guest)) == pdk):
                raise ValueError(f"image PDK path {guest!r} is not the "
                                 f"absolute tree of PDK {pdk!r}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, f"PDK-root bridge receipt is unusable: {exc}"
    return {"receipt": receipt, "pdk": pdk, "host_tree": str(root / pdk),
            "image_id": image_id,
            "guest_tree": posixpath.normpath(guest) if guest else None}, ""


def _deck_manifest(drc: str, read, list_tree):
    """`({path: sha256}, why)` of EVERY file under the deck directory.

    The runnable parent does not execute one rule file: it requires its
    framework/options/helpers beside it and loads every rule deck under
    ``rule_decks/`` by glob, so any of those files can change what the run
    prints and writes. The deck directory is hashed whole -- a superset of
    what executes -- and re-listed after the run, so an added file counts.
    """
    files = list_tree(drc)
    if not files:
        return None, f"native deck directory {drc} could not be listed"
    manifest = {}
    for path in files:
        data = read(path)
        if data is None:
            return None, f"native deck file is unreadable: {path}"
        manifest[path] = hashlib.sha256(data).hexdigest()
    return manifest, ""


def _manifest_sha(manifest: Dict[str, str]) -> str:
    return hashlib.sha256("".join(
        f"{manifest[k]}  {k}\n" for k in sorted(manifest)).encode()).hexdigest()


def _discover_deck(tree: str, read, list_files, list_tree):
    """Discover a PDK's own antenna rule and its runnable parent deck.

    `read`/`list_files` answer from the environment KLayout will run in, so
    the recorded digests are of the very bytes the tool executes. The rule
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
    manifest, why = _deck_manifest(drc, read, list_tree)
    if manifest is None:
        return None, why
    deck = {"tree": tree, "rule": rule,
            "rule_sha256": hashlib.sha256(rule_bytes).hexdigest(),
            "parent": parents[0][0],
            "parent_sha256": hashlib.sha256(parents[0][1]).hexdigest(),
            "deck_dir": drc, "files": manifest,
            "read": read, "list_tree": list_tree}
    if standalone:
        deck["format"] = "standalone"
    for key in ("rule", "parent"):
        if manifest.get(deck[key]) != deck[f"{key}_sha256"]:
            return None, (f"native deck {key} {deck[key]} is not the file the "
                          f"deck directory listing hashed")
    return deck, ""


def _deck_changed(deck: dict) -> str:
    """Why the deck directory is no longer the one hashed before the run."""
    after, why = _deck_manifest(deck["deck_dir"], deck["read"], deck["list_tree"])
    if after is None:
        return f"native deck vanished during execution: {why}"
    if after != deck["files"]:
        moved = sorted(k for k in set(after) | set(deck["files"])
                       if after.get(k) != deck["files"].get(k))
        return ("native deck bytes changed or vanished during execution: "
                + ", ".join(moved[:8]) + (" ..." if len(moved) > 8 else ""))
    return ""


def _image_bound_deck(runner, receipt: dict):
    """The deck inside the image the run's PDK root was resolved from."""
    want, tree = receipt["image_id"], receipt["guest_tree"]
    live, why = runner.image_id()
    if live != want:
        return None, (f"the run's PDK root is bound to image {want} at {tree}, "
                      f"but KLayout container {runner.detail} runs "
                      f"{live or 'an unidentified image'}"
                      + (f" ({why})" if why else ""))
    proven, why, record = runner.image_tree_proof(tree)
    if not proven:
        return None, why
    deck, why = _discover_deck(tree, runner.read_bytes, runner.list_files,
                               runner.list_tree)
    if deck is not None:
        deck["side"] = f"container:{runner.detail}"
        deck["image_id"] = want
        deck["image_bytes"] = record
        deck["reprove"] = lambda: runner.image_tree_proof(tree)
    return deck, why


_BIND_PREFIX = "VIBEIC_GDS_SHA256="
_NATIVE_RDB = "gate_oxide_native.lyrdb"
_NATIVE_LOG = "gate_oxide_native.log"
#: The native deck's own record of WHICH rule file it executed ...
_DECK_FROM_RE = re.compile(r"Executing deck\s+\S+\s+from\s+(\S+)\s*$", re.M)
#: ... and of its completion tally, printed after every selected deck ran.
_TALLY_RE = re.compile(
    r"DRC RESULT:\s*(SUCCESS|FAILURE)\s*\((\d+)\s+violations?(?:\(s\))?\)")
#: The RDB's own record of the script that generated it.
_GENERATOR_RE = re.compile(r"<generator>\s*drc:\s*script='([^']*)'\s*</generator>")


def _bound_native_count(gds: Path, rdb: Path, transcript: Path, gds_sha: str,
                        *, deck: Optional[dict] = None):
    """Read a fresh native result only while every artefact shares one basis.

    The transcript is written by this invocation after its KLayout process
    exits. Its first line binds the process output to the pre-execution GDS
    hash; the caller also checks that the GDS did not change during execution.
    The transcript must name the exact rule file whose bytes were hashed, the
    RDB must name the exact parent script, and the deck's own completion tally
    must equal the RDB's item count -- a run that stopped early, executed
    another deck, or wrote an RDB that disagrees with its own tally is not a
    measurement. The returned hashes bind both outputs into the gate report.
    """
    if not rdb.is_file() or not transcript.is_file() or _sha(gds) != gds_sha:
        return None, "GDS or native output missing/changed", {}
    log = transcript.read_text(errors="replace")
    if not log.startswith(_BIND_PREFIX + gds_sha + "\n"):
        return None, "native transcript is bound to another GDS SHA-256", {}
    return _native_result_count(rdb, transcript, deck)


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
    """The same raw deck obligations for fresh and receipt-bound native runs."""
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
        return count, "", {"rdb_sha256": _sha(rdb), "transcript_sha256": _sha(transcript),
                            "graded_rules": graded, "checked_gate_nets": None,
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
    return count, "", {"rdb_sha256": _sha(rdb),
                       "transcript_sha256": _sha(transcript),
                       "transcript_tally": tallied}


def _retained_native_result(project: Path, gds: Path, router: Optional[str],
                            cell: Optional[str], receipt: dict) -> Optional[dict]:
    """Read the selected native producer, never substitute its summary label."""
    import librelane_signoff_evidence as native
    record_path = project / 'reports/phase3/antenna_librelane.json'
    if not record_path.is_file() or not native.tool_selected(project, '26'):
        return None
    result = {'check': 'gds_geometry_antenna_deck', 'method': 'pdk_native_klayout',
              'evidence_basis': 'retained_KLayout.Antenna',
              'gds': str(gds), 'gds_sha256': _sha(gds),
              'pdk_receipt': str(receipt['receipt']), 'record': str(record_path)}
    rdb = None
    try:
        model = native._member(native._read(record_path), 'gds')
        state = native._path(project, model.get('state'))
        folder = state.parent
        if native._read(folder / 'pdk_root.json').get('execution_route') != 'LOCAL':
            return None
        row = native.count_row(project, folder, 'KLayout.Antenna',
            'klayout__antenna_error__count', gds, project / 'phase3/librelane/26-config')
        result['native_evidence'] = row
        if type(row['value']) is not int:
            raise ValueError(row.get('reason') or 'native antenna has no current reading')
        result['violations'] = row['value']
        config = native._read(folder / 'config.json')
        if (model.get('step') != 'KLayout.Antenna'
                or model.get('state_sha256') != row['sha256']
                or model.get('subject_sha256') != result['gds_sha256']
                or type(native._member(model, 'counts').get('klayout__antenna_error__count')) is not int
                or native._member(model, 'counts').get('klayout__antenna_error__count') != row['value']
                or config.get('PDK') != receipt['pdk']):
            raise ValueError('retained antenna model differs from its native producer')
        deck, why = _discover_deck(receipt['host_tree'], _kl.host_read_bytes,
                                   _kl.host_list_files, _kl.host_list_tree)
        if deck is None:
            raise ValueError(why)
        switch_path = project / 'phase3/librelane_switch.json'
        switch = native._read(switch_path) if switch_path.is_file() else {}
        mounts = native._pdk_mounts(project, switch, folder, row['image'])
        from _container_exec import localise_mounted_paths
        def local(path):
            return Path(localise_mounted_paths(str(path), [(guest, str(host)) for host, guest in mounts])).resolve()
        if local(config.get('KLAYOUT_ANTENNA_RUNSET')) != Path(deck['parent']).resolve():
            raise ValueError('retained native antenna runset differs from the selected PDK deck')
        commands = [shlex.split(line) for line in (folder / 'COMMANDS').read_text().splitlines() if line.strip()]
        selected = [argv for argv in commands if '-r' in argv
                    and local(argv[argv.index('-r') + 1]) == Path(deck['parent']).resolve()]
        if len(selected) != 1:
            raise ValueError('retained antenna commands name no unique native runset')
        argv = selected[0]
        options = dict(argv[i + 1].split('=', 1) for i, arg in enumerate(argv) if arg == '-rd')
        design = config.get('DESIGN_NAME')
        configured_options = config.get('KLAYOUT_ANTENNA_OPTIONS')
        if configured_options is None:
            configured_options = {}
        if not isinstance(configured_options, dict):
            raise ValueError('retained native antenna options are not a mapping')
        if (not design or options.get('decks') != 'antenna'
                or any(options.get(key) != str(value) for key, value in
                       configured_options.items())
                or options.get('topcell') != design or (cell is not None and cell != design)
                or _sha(local(options['input'])) != result['gds_sha256']):
            raise ValueError('retained antenna commands do not consume the selected GDS/top/deck')
        rdb = local(options['report'])
        if not rdb.is_relative_to(folder.resolve()):
            raise ValueError('retained native antenna report is outside its producer')
        transcript = folder / 'invocation.log'
        count, why, hashes = _native_result_count(rdb, transcript, deck)
        if why:
            raise ValueError(why)
        report = folder / 'reports/antenna.klayout.json'
        raw = native._read(report)
        bound = native._read(folder / 'vibeic_receipt.json')['sha256']
        if (bound.get(str(report.relative_to(folder))) != _sha(report)
                or type(raw.get('total')) is not int or raw['total'] != count
                or count != row['value']
                or not re.search(r'<top-cell>\s*' + re.escape(design) + r'\s*</top-cell>', rdb.read_text())):
            raise ValueError('native antenna RDB, raw report, top and producer count disagree')
        result.update(hashes, rdb=str(rdb), transcript=str(transcript),
                      pdk_rule=deck['rule'], pdk_rule_sha256=deck['rule_sha256'],
                      pdk_parent=deck['parent'], pdk_parent_sha256=deck['parent_sha256'],
                      verdict='FAIL' if count else 'PASS', measurement='MEASURED',
                      reason=f'{count} PDK-native antenna violation(s)' if count else '')
        if count == 0 and hashes.get('coverage_status') == 'NOT_MEASURED':
            result.update(verdict='DISCLOSED_SKIP', measurement='NOT_MEASURED',
                          reason='retained standalone rules ran, but checked gate/net population is not reported; zero violations is not proven coverage')
            return result
        raw_out = project / 'reports/phase3' / _RAW_REPORT_NAME
        _atomic_write_bytes(raw_out, json.dumps({'verdict': result['verdict'], 'violations': count}).encode())
        return _native_router_cross_check(project, router, raw_out, result, count)
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        red = result.get('violations') or (_rdb_red_count(rdb) if rdb is not None else None)
        result.update(verdict='FAIL' if red else 'DISCLOSED_SKIP',
                      measurement='FAIL' if red else 'NOT_MEASURED',
                      failure_class='BINDING', reason=str(exc))
        return result


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


def _run_native(project: Path, gds: Optional[str], router: Optional[str],
                cell: Optional[str], receipt: dict, *, local_launch=None,
                work: Optional[Path] = None) -> Dict[str, Any]:
    def skip(reason: str, **extra) -> Dict[str, Any]:
        return {"verdict": "DISCLOSED_SKIP", "check": "gds_geometry_antenna_deck",
                "measurement": "NOT_MEASURED", "method": "pdk_native_klayout",
                "pdk_receipt": str(receipt["receipt"]), "reason": reason, **extra}

    if local_launch is not None:
        from librelane_contract import local_image_attestation
        if (local_image_attestation() != local_launch
                or receipt.get("image_id") != local_launch.get("image_id")):
            return skip("local native launch does not bind the selected PDK image")
    image_bound = receipt["image_id"] is not None
    native = None
    if not image_bound:
        # A declared host tree is read on the host, where it lives.
        native, why = _discover_deck(receipt["host_tree"], _kl.host_read_bytes,
                                     _kl.host_list_files, _kl.host_list_tree)
        if native is None:
            return skip(why)
        native["side"] = "host"
    if gds:
        gds_path = Path(gds)
    else:
        # A directory with multiple streams does not identify the delivered
        # one. Sorting filenames is not a sign-off selection rule.
        staged = sorted((project / "phase3/stage4/gds").glob("*.gds"))
        if len(staged) > 1:
            return skip("multiple streamed GDS files; select the delivered GDS with --gds")
        gds_path = staged[0] if staged else _first(project, _GDS_GLOBS)
    if gds_path is not None and not gds_path.is_absolute():
        gds_path = project / gds_path
    if gds_path is None or not gds_path.is_file():
        return skip("no streamed GDS for the selected native PDK deck")
    retained = (_retained_native_result(project, gds_path, router, cell, receipt)
                if local_launch is None else None)
    if retained is not None:
        return retained
    # An image-bound tree exists only inside that image: a host KLayout could
    # read nothing but the unverified host copy, so it is never asked.
    runner = (_kl.find_runner(project=project) if local_launch is not None else
              _kl.find_container_runner(project=project) if image_bound else
              _kl.find_runner(project=project))
    if runner is None or not runner.covers(gds_path):
        return skip("no KLayout runner reaches the streamed GDS"
                    + (" inside the image the PDK root is bound to"
                       if image_bound else ""))
    work = Path(work) if work is not None else project / "reports" / "phase3"
    work.mkdir(parents=True, exist_ok=True)
    rdb, transcript = work / _NATIVE_RDB, work / _NATIVE_LOG
    if not runner.covers(work):
        return skip("KLayout runner cannot write native antenna evidence")
    if local_launch is not None:
        if runner.kind != "host":
            return skip("attested local native entry requires the direct image runner")
        native, why = _discover_deck(receipt["guest_tree"], _kl.host_read_bytes,
                                     _kl.host_list_files, _kl.host_list_tree)
        if native is None:
            return skip(why)
        native.update(side="attested_local_image", image_id=local_launch['image_id'],
                      image_bytes=local_launch)
    elif image_bound:
        native, why = _image_bound_deck(runner, receipt)
        if native is None:
            return skip(why)
    elif runner.kind == "container":
        return skip("the PDK-root receipt binds no image, so a container "
                    "KLayout has no path to its native deck")
    for old in (rdb, transcript):
        old.unlink(missing_ok=True)
    before = _sha(gds_path)
    identity = {"pdk_tree": native["tree"], "pdk_tree_side": native["side"],
                "pdk_image_id": native.get("image_id"),
                "pdk_image_bytes": native.get("image_bytes"),
                "pdk_rule": native["rule"], "pdk_rule_sha256": native["rule_sha256"],
                "pdk_parent": native["parent"],
                "pdk_parent_sha256": native["parent_sha256"],
                "pdk_deck_dir": native["deck_dir"],
                "pdk_deck_files": dict(native["files"]),
                "pdk_deck_manifest_sha256": _manifest_sha(native["files"])}

    def unbound(record: Dict[str, Any], why: str) -> Dict[str, Any]:
        """A result the binding could not accept. Measured violations are
        never relabelled: an RDB of THIS run holding ANT items keeps the step
        red (FAIL, failure_class BINDING) whatever else failed; only a run
        with no measured violation becomes NOT_MEASURED."""
        red = _rdb_red_count(rdb)
        if red:
            return {**record, "verdict": "FAIL", "measurement": "FAIL",
                    "failure_class": "BINDING", "violations": red,
                    "reason": (f"native RDB holds {red} antenna violation(s); "
                               f"the measurement is not bound ({why}), and "
                               f"measured violations are never relabelled "
                               f"NOT_MEASURED")}
        return {**record, "verdict": "DISCLOSED_SKIP",
                "measurement": "NOT_MEASURED", "reason": why}
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
    rc, out, err = execution.rc, execution.out or "", execution.err or ""
    _atomic_write_bytes(transcript, (_BIND_PREFIX + before + "\n" + out + err).encode())
    run_record = {"argv": list(argv), "rc": rc, "outcome": execution.outcome,
                  "elapsed_s": execution.elapsed_s,
                  "stall_grace_s": _NATIVE_STALL_GRACE_S,
                  "memory_limit_mb": _NATIVE_MEMORY_LIMIT_MB,
                  "stdout_bytes": len(out.encode()), "stderr_bytes": len(err.encode()),
                  "supervision": execution.supervision}
    if rc != 0:
        incomplete = execution.outcome != "natural" or rc in (124, 125, 137, -9)
        red = _rdb_red_count(rdb)
        if red:
            # The deck stopped, but what it already wrote is measured.
            return {"check": "gds_geometry_antenna_deck", "verdict": "FAIL",
                    "measurement": "FAIL", "failure_class": "DECK_EXECUTION",
                    "method": "pdk_native_klayout", "rc": rc,
                    "execution": run_record, "violations": red,
                    "gds": str(gds_path), "gds_sha256": before, **identity,
                    "rdb": str(rdb), "rdb_sha256": _sha(rdb),
                    "transcript": str(transcript),
                    "transcript_sha256": _sha(transcript),
                    "reason": (f"native deck ended {execution.outcome} rc={rc} "
                               f"after its RDB recorded {red} antenna "
                               f"violation(s)")}
        return {"check": "gds_geometry_antenna_deck",
                "verdict": "NOT_MEASURED" if incomplete else "FAIL",
                "measurement": "NOT_MEASURED", "failure_class": "DECK_EXECUTION",
                "method": "pdk_native_klayout", "rc": rc, "execution": run_record,
                "gds": str(gds_path), "gds_sha256": before, **identity,
                "transcript": str(transcript),
                "transcript_sha256": _sha(transcript),
                "reason": (f"native antenna measurement incomplete after "
                           f"{execution.outcome} rc={rc}"
                           if incomplete else
                           f"declared native KLayout deck failed rc={rc}; "
                           "no antenna measurement")}
    base = {"check": "gds_geometry_antenna_deck", "method": "pdk_native_klayout",
            "gds": str(gds_path), "gds_sha256": before, **identity,
            "rdb": str(rdb), "transcript": str(transcript), "rc": rc,
            "execution": run_record}
    changed = _deck_changed(native)
    if local_launch is not None:
        from librelane_contract import local_image_attestation
        if local_image_attestation() != local_launch:
            return unbound(base, "local native execution launch changed")
    if changed:
        return unbound(base, changed)
    if native.get("reprove") is not None:
        proven, why, record = native["reprove"]()
        base["pdk_image_bytes_after"] = record
        if not proven:
            return unbound(base, f"after the run: {why}")
    count, why, hashes = _bound_native_count(gds_path, rdb, transcript, before,
                                             deck=native)
    base.update(hashes)
    if why:
        return unbound(base, why)
    if native.get("format") == "standalone" and count == 0:
        return {**base, "verdict": "DISCLOSED_SKIP", "measurement": "NOT_MEASURED",
                "violations": 0, "reason": "native standalone rules ran, but checked gate/net population is not reported; zero violations is not proven coverage"}
    raw = work / _RAW_REPORT_NAME
    _atomic_write_bytes(raw, json.dumps({"verdict": "PASS" if count == 0 else "FAIL",
                                         "violations": count}).encode())
    res = {**base, "verdict": "PASS" if count == 0 else "FAIL",
           "violations": count, "worst_ratio": None,
           "reason": f"{count} PDK-native antenna violation(s)" if count else ""}
    return _native_router_cross_check(project, router, raw, res, count)


def _native_router_cross_check(project: Path, router: Optional[str], raw: Path,
                                res: dict, count: int) -> dict:
    # Native router reports may be KLayout RDBs.  The plugin's calibrated
    # cross-check reader understands that dialect; an image copy can lag it.
    xtool = Path(__file__).resolve().parent / "gds_antenna" / "xcheck_router.py"
    rpt = Path(router) if router else _first(project, _ROUTER_GLOBS)
    if rpt is not None and not rpt.is_absolute():
        rpt = project / rpt
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
        receipt, why = _pdk_receipt(project)
        if receipt is None:
            return skip(f"{cfg_src}; {why}", config_source=cfg_src)
        return _run_native(project, gds, router, cell, receipt)

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
    rpt = Path(router) if router else _first(project, _ROUTER_GLOBS)
    if rpt is not None and not rpt.is_absolute():
        rpt = project / rpt
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



def _d43_inputs(project):
    from flow109_analog_floorplan import bound_file
    from declared_pdk_is_the_pdk_used_check import declared_target
    import analog_pdk_availability as resolver
    config = project / 'input/flow109/D43.json'
    if any(p.is_symlink() for p in (config, *config.parents)):
        raise ValueError('D43_INPUT_SYMLINK')
    data = json.loads(config.read_text())
    gds = bound_file(project, data.get('layout'))
    top = data.get('top')
    if not isinstance(top, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', top):
        raise ValueError('D43_TOP_INVALID')
    target, target_source = declared_target(project)
    if not isinstance(target, str) or not target.strip():
        raise ValueError('D43_DECLARED_PDK_ABSENT')
    facts = resolver.resolve_pdk(target, project=project)
    if facts.get('source') != 'container_installed' or not facts.get('available'):
        raise ValueError('D43_INSTALLED_DECLARED_PDK_UNAVAILABLE')
    deck, why = _discover_deck(facts['pdk_root'], _kl.host_read_bytes,
                                _kl.host_list_files, _kl.host_list_tree)
    if deck is None:
        raise ValueError('D43_NATIVE_DECK_UNAVAILABLE: ' + why)
    ref = data.get('antenna_deck')
    if not isinstance(ref, dict) or ref != {'path': deck['rule'], 'sha256': deck['rule_sha256']}:
        raise ValueError('D43_DECLARED_PDK_DECK_UNBOUND_OR_STALE')
    if not isinstance(target_source, str):
        raise ValueError('D43_PDK_DECLARATION_SOURCE_ABSENT')
    relative = Path(target_source.rsplit(':', 1)[0])
    declarations = [base / relative for base in (project, project / 'run')
                    if (base / relative).is_file()]
    if not declarations or any(any(p.is_symlink() for p in (path, *path.parents)) for path in declarations):
        raise ValueError('D43_PDK_DECLARATION_SOURCE_UNBOUND')
    return dict(top=top, gds=str(gds), target=target, tree=facts['pdk_root'],
                deck_files=deck['files'],
                inputs={str(p): _sha(p) for p in (config, gds, *declarations)})


def execute(project, context):
    """Ordinary D43 candidate component; original native reports remain raw."""
    import uuid
    import librelane_contract as launch
    from flow109_admission import require_launch_admission, AdmissionRefusal
    project = Path(project).resolve(strict=True)
    work = project / 'reports/flow109/D43' / uuid.uuid4().hex
    work.mkdir(parents=True)
    result = dict(step_id='D43', context_sha256=context.get('context_sha256'),
                  component_status='NOT_MEASURED', default_row_status='NOT_MEASURED',
                  completed=False, native_started=False, outputs=[], qualification='NOT_CLAIMED',
                  flow109_acceptance='NOT_MEASURED', whole_flow_acceptance='NOT_MEASURED', delivery_accepted=False)
    try:
        if (context.get('requested_step') != 'D43' or context.get('native_step_id') != 'flow109.D43'
                or context.get('resolved_row', {}).get('profile', {}).get('id') != 'analog_die'):
            raise ValueError('D43_CONTEXT_INVALID')
        result['launch_admission'] = require_launch_admission(project, 'flow109.D43', {'flow109_context': context})
        result['native_launch'] = launch.local_image_attestation()
        data = _d43_inputs(project)
        result['inputs'] = data['inputs']
        result['metric_sources'] = _d43_metric_sources()
        runner = _kl.find_runner(project=project)
        if runner is None or runner.kind != 'host':
            raise ValueError('D43_DIRECT_NATIVE_RUNNER_UNAVAILABLE')
        executable = Path(runner.klayout_bin()).resolve(strict=True)
        result['metric_tool'] = {'path': str(executable), 'sha256': _sha(executable)}
        readback = work / 'subject.json'; script = work / 'read_subject.py'
        script.write_text('import pya,json\nl=pya.Layout();l.read(' + repr(data['gds']) +
                          ')\njson.dump(dict(tops=[c.name for c in l.top_cells()],nonempty=not l.top_cells()[0].bbox().empty() if len(l.top_cells())==1 else False),open(' + repr(str(readback)) + ',"w"))\n')
        result['native_started'] = True
        rc, out, err = runner.run_argv([runner.klayout_bin(), '-b', '-r', str(script)], {})
        (work/'subject.log').write_text(out+err)
        subject = json.loads(readback.read_text()) if readback.is_file() else {}
        if rc or subject != {'tops': [data['top']], 'nonempty': True}:
            raise ValueError('D43_SUBJECT_TOP_ABSENT_AMBIGUOUS_OR_EMPTY')
        receipt = dict(receipt=project/'input/flow109/D43.json', image_id=result['native_launch']['image_id'], guest_tree=data['tree'])
        native = _run_native(project, data['gds'], None, data['top'], receipt,
                             local_launch=result['native_launch'], work=work/'native')
        result['native'] = native
        (work/'native_result.json').write_text(json.dumps(native,indent=2)+'\n')
        if _d43_inputs(project) != data or launch.local_image_attestation() != result['native_launch']:
            raise ValueError('D43_INPUT_OR_LAUNCH_CHANGED')
        if native.get('verdict') == 'FAIL':
            result['component_status'] = 'FAIL'
        # The legacy native format does not enumerate checked gates/nets
        # either. Its gate verdict is retained, never promoted to D43 coverage.
        result['reason'] = native.get('reason') or 'D43_REQUIRED_GATE_NET_AND_RULE_COVERAGE_NOT_MEASURED'
    except (ValueError, OSError, KeyError, TypeError, AdmissionRefusal, launch.Refusal) as exc:
        if result.get('native', {}).get('verdict') == 'FAIL':
            result['component_status'] = 'FAIL'
        result['reason'] = str(exc)
    result['outputs'] = [{'path': str(p.relative_to(project)), 'sha256': _sha(p)}
                         for p in sorted(work.rglob('*')) if p.is_file()]
    (work/'component.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def _d43_metric_sources():
    """D43's producer and actual native-count/rule readers, never a version label."""
    here = Path(__file__).resolve().parent
    return {name: _sha(here / name) for name in ('gds_antenna_deck_check.py',
        'eda_report_audit.py', '_a6_drc_authority.py', 'declared_pdk_is_the_pdk_used_check.py',
        'analog_pdk_availability.py')}


def _d43_metric_readback(gds, rdb, transcript, gds_sha, deck):
    """Regrade the existing native outputs, with their original source/GDS binding.

    Graded rules are observations. They are never their own required population.
    In particular, zero items cannot manufacture checked gate/net coverage.
    """
    count, reason, hashes = _bound_native_count(gds, rdb, transcript, gds_sha, deck=deck)
    if reason or type(count) is not int or count < 0:
        raise ValueError('D43_NATIVE_METRIC_UNBOUND: ' + str(reason))
    from _a6_drc_authority import lyrdb_text_rules
    rules = lyrdb_text_rules(rdb.read_text())
    return {'violations': count, 'unit': 'count', 'observed_rules': rules['graded'],
            'required_rules': None, 'checked_gate_nets': None,
            'population_status': 'NOT_MEASURED', 'native_hashes': hashes,
            'measurement_status': 'FAIL' if count else 'PASS',
            'scope': 'native executed-deck item count; complete rule/gate population not established'}


def _d43_metric_observation(project, context, component):
    """Consume a normal D43 attempt without launching another native deck."""
    import flow109
    from flow109_analog_floorplan import bound_file
    current = flow109.validate_execution_context(context)
    if (current['requested_step'] != 'D43' or current['resolved_row']['profile']['id'] != 'analog_die'
            or component.get('step_id') != 'D43'
            or component.get('context_sha256') != current['context_sha256']):
        raise ValueError('D43_METRIC_CONTEXT_MISMATCH')
    if component.get('metric_sources') != _d43_metric_sources():
        raise ValueError('D43_METRIC_SOURCE_CHANGED_OR_UNRECORDED')
    data = _d43_inputs(project)
    if component.get('inputs') != data['inputs']:
        raise ValueError('D43_METRIC_INPUT_CHANGED_OR_UNRECORDED')
    outputs = component.get('outputs')
    if not isinstance(outputs, list) or not outputs:
        raise ValueError('D43_METRIC_NATIVE_OUTPUTS_ABSENT')
    paths = [bound_file(project, ref) for ref in outputs]
    if len(set(paths)) != len(paths):
        raise ValueError('D43_METRIC_OUTPUT_POPULATION_AMBIGUOUS')
    base = project / 'reports/flow109/D43'
    if any(not p.is_relative_to(base) or len(p.relative_to(base).parts) < 2 for p in paths):
        raise ValueError('D43_METRIC_OUTPUT_FOREIGN')
    attempts = {base / p.relative_to(base).parts[0] for p in paths}
    if len(attempts) != 1:
        raise ValueError('D43_METRIC_ATTEMPT_AMBIGUOUS')
    work = attempts.pop()
    raw = work / 'component.json'
    if any(p.is_symlink() for p in (raw, *raw.parents)) or json.loads(raw.read_text()) != component:
        raise ValueError('D43_METRIC_ORIGINAL_COMPONENT_MISMATCH')
    native = component['native']
    if (work / 'native_result.json' not in paths or
            json.loads((work / 'native_result.json').read_text()) != native):
        raise ValueError('D43_METRIC_NATIVE_RESULT_MISMATCH')
    deck, reason = _discover_deck(data['tree'], _kl.host_read_bytes,
                                 _kl.host_list_files, _kl.host_list_tree)
    if deck is None or deck['files'] != data['deck_files']:
        raise ValueError('D43_METRIC_DECK_UNAVAILABLE: ' + str(reason))
    expected = {'pdk_rule': deck['rule'], 'pdk_rule_sha256': deck['rule_sha256'],
                'pdk_parent': deck['parent'], 'pdk_parent_sha256': deck['parent_sha256'],
                'pdk_deck_files': deck['files'], 'pdk_deck_manifest_sha256': _manifest_sha(deck['files']),
                'gds': data['gds'], 'gds_sha256': _sha(Path(data['gds']))}
    if any(native.get(key) != value for key, value in expected.items()):
        raise ValueError('D43_METRIC_NATIVE_BASIS_CHANGED')
    tool = component['metric_tool']
    if _sha(Path(tool['path']).resolve(strict=True)) != tool.get('sha256'):
        raise ValueError('D43_METRIC_TOOL_CHANGED')
    if component.get('native_started') is not True or type(native.get('rc')) is not int or native['rc'] != 0:
        raise ValueError('D43_METRIC_NATIVE_EXECUTION_INCOMPLETE')
    rdb, transcript = Path(native['rdb']), Path(native['transcript'])
    if rdb not in paths or transcript not in paths:
        raise ValueError('D43_METRIC_NATIVE_OUTPUT_UNRECORDED')
    observation = _d43_metric_readback(Path(data['gds']), rdb, transcript, native['gds_sha256'], deck)
    if native.get('violations') != observation['violations']:
        raise ValueError('D43_METRIC_PRINTED_COUNT_DISAGREES')
    if (_d43_inputs(project) != data or _deck_changed(deck) or
            component['metric_sources'] != _d43_metric_sources()):
        raise ValueError('D43_METRIC_CONSUMED_BASIS_CHANGED_DURING_READ')
    for ref in outputs:
        bound_file(project, ref)
    observation['readset'] = {'inputs': data['inputs'], 'deck_files': deck['files'],
        'outputs': outputs, 'sources': component['metric_sources'], 'tool': tool,
        'original_execution': native['execution'], 'original_native_launch': component.get('native_launch'),
        'component': {'path': str(raw.relative_to(project)), 'sha256': _sha(raw)},
        'context_sha256': current['context_sha256']}
    return observation


def accept_d43(project, context, component):
    """BLOCKING D43 metrics: preserve measured violations and unknown coverage."""
    import flow109
    import flow109_metric_acceptance as metrics
    result = {'schema': metrics.SCHEMA, 'row_id': 'D43', 'status': 'NOT_MEASURED',
              'metric_status': 'NOT_MEASURED', 'qualification': 'NOT_MEASURED',
              'delivery_blocked': True, 'obligations': []}
    ids = ['base_35.antenna_net_pin_violations', 'base_35.antenna_rule_coverage']
    try:
        current = flow109.validate_execution_context(context)
        if current['requested_step'] != 'D43' or [r['id'] for r in current['resolved_row']['obligations']] != ids:
            raise ValueError('D43_METRIC_OBLIGATIONS_UNREGISTERED')
        observed = _d43_metric_observation(Path(project).resolve(strict=True), current, component)
        result['observation'] = observed
        failed = observed['violations'] > 0
        result['obligations'] = [{'id': ids[0], 'status': 'FAIL' if failed else 'NOT_MEASURED',
            'measurement_status': 'FAIL' if failed else 'PASS', 'observed_value': observed['violations'],
            'unit': 'count', 'reason': 'D43_NATIVE_ANTENNA_VIOLATIONS' if failed else
            'D43_CHECKED_GATE_NET_AND_LOGICAL_MISSION_POPULATION_UNPROVEN'},
            {'id': ids[1], 'status': 'NOT_MEASURED', 'observed_rules': observed['observed_rules'],
             'reason': 'D43_SOURCE_OWNED_COMPLETE_RULE_POPULATION_NOT_ADOPTED'}]
        result.update(metric_status='FAIL' if failed else 'NOT_MEASURED',
                      reason='D43_NATIVE_COUNT_REOPENED_REQUIRED_POPULATIONS_PENDING')
    except (ValueError, OSError, KeyError, TypeError, AttributeError, flow109.Flow109Error) as exc:
        result.update(reason='D43_METRIC_EVIDENCE_UNAVAILABLE', detail=str(exc))
        result['obligations'] = [{'id': oid, 'status': 'NOT_MEASURED', 'reason': str(exc)} for oid in ids]
    if component.get('component_status') == 'FAIL' or result['metric_status'] == 'FAIL':
        result.update(status='FAIL', reason='D43_MEASURED_FAILURE_PRESERVED')
    return result


def consume_default_row_completion(project, context, component):
    """Use the existing completion seam; unknown population cannot finish D43."""
    accepted = accept_d43(project, context, component)
    previous = component.get('metric_acceptance')
    previous = previous if isinstance(previous, dict) else {}
    metric_failed = (component.get('metric_acceptance_status') == 'FAIL' or
                     previous.get('status') == 'FAIL' or previous.get('metric_status') == 'FAIL')
    if metric_failed or component.get('default_row_status') == 'FAIL':
        accepted = {**accepted, 'status': 'FAIL', 'delivery_blocked': True,
            'metric_status': 'FAIL' if metric_failed else accepted['metric_status'],
            'reason': 'D43_PRIOR_MEASURED_FAILURE_PRESERVED'}
        prior = previous.get('obligations', [])
        prior = prior if isinstance(prior, list) else []
        failed_ids = {item.get('id') for item in prior if isinstance(item, dict) and item.get('status') == 'FAIL'}
        accepted['prior_failed_obligation_ids'] = sorted(oid for oid in failed_ids if isinstance(oid, str))
        accepted['obligations'] = [
            {**item, 'status': 'FAIL', 'reason': 'D43_PRIOR_MEASURED_FAILURE_PRESERVED'}
            if item.get('id') in failed_ids and item.get('status') == 'NOT_MEASURED' else item
            for item in accepted['obligations']]
    return {**component, 'step_id': 'D43', 'context_sha256': context['context_sha256'],
        'metric_acceptance': accepted, 'metric_acceptance_status': accepted['metric_status'],
        'default_row_status': accepted['status'], 'flow109_acceptance': accepted['status'],
        'completed': False, 'qualification': 'NOT_MEASURED',
        'whole_flow_acceptance': 'NOT_MEASURED', 'delivery_accepted': False}


if __name__ == "__main__":
    sys.exit(main())
