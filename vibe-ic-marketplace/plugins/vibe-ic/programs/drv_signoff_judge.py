#!/usr/bin/env python3
"""BLOCKING post-route DRV(tran/cap/fanout) sign-off judge.

The receipt is a frozen, content-addressed measurement bundle.  Missing
instrument evidence is NOT_MEASURED; a measured rule breach is FAIL.  This
program never creates a waiver.  WAIVED is a disclosed deviation, never PASS.
Noise/SI, EM and max_length remain separately NOT_MEASURED.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from librelane_contract import Refusal as LocalProviderRefusal  # noqa: E402
from _atomic_artefact import write_text  # noqa: E402
from drv_signoff_anchor import image_pdk_anchor  # noqa: E402

KINDS = ("max_slew", "max_capacitance", "max_fanout")
_TITLES = {"max slew": KINDS[0], "max capacitance": KINDS[1],
           "max fanout": KINDS[2]}
_VALUES = {"max_slew": ("max slew", "slew"),
           "max_capacitance": ("max capacitance", "capacitance"),
           "max_fanout": ("max fanout", "fanout")}
_NUM = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"
_PIN = re.compile(r"^Pin\s+(\S+)(?:\s+([\^v]))?\s*$")
_METRIC = re.compile(rf"^(.+?)\s+({_NUM})(?:\s+\((?:VIOLATED|MET)\))?\s*$")
_COMMAND = "report_check_types -max_slew -max_capacitance -max_fanout -violators -verbose"
_REQUIRED_STAGES = ("synth", "placement_repair", "cts", "post_grt_repair", "signoff_sta")
_FORBIDDEN_SDC = re.compile(r"\b(set_case_analysis|set_disable_timing|set_ideal_network|set_ideal_net)\b")
_SCENE_PROFILES = Path(__file__).resolve().parent / "data/drv_signoff_scene_profiles.json"
_OWNER_SIGNERS = Path(__file__).resolve().parent / "data/drv_owner_allowed_signers"
_THRESHOLD_FREEZES = Path(__file__).resolve().parent / "data/drv_threshold_freezes.json"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def _evidence(item: dict, errors: list[str], label: str) -> str:
    path = Path(str(item.get("path") or ""))
    expected = str(item.get("sha256") or "")
    if not path.is_file() or not re.fullmatch(r"[0-9a-f]{64}", expected):
        errors.append(f"{label}: file or sha256 absent")
        return ""
    actual = _sha(path)
    if actual != expected:
        errors.append(f"{label}: sha256 changed ({expected} -> {actual})")
        return ""
    return path.read_text(errors="replace")


def _sdc_values(body: str, command: str, *, include_ports: bool = True,
                only_port: str | None = None) -> list[float]:
    # Tcl is not a line-oriented format.  A conflicting later assignment must
    # never be hidden by reading only the first matching line.
    # IO port constraints have their own domain. They are not the core
    # defaults the stage receipt and the core declaration must agree on.
    values = []
    for match in re.finditer(
            rf"(?m)^\s*{re.escape(command)}\s+({_NUM})(?=\s|$)([^\n;]*)", body):
        target = match.group(2).strip()
        if only_port is not None:
            listed = re.fullmatch(r"\[get_ports\s+\[list\s+((?:\{[^{}]+\}\s*)+)\]\]", target)
            literal = re.fullmatch(r"\[get_ports\s+\{([^{}]+)\}\]", target)
            names = (re.findall(r"\{([^{}]+)\}", listed[1]) if listed else
                     [literal[1]] if literal else
                     ["*"] if target == "[get_ports *]" else [])
            if only_port not in names and "*" not in names:
                continue
        elif not include_ports and re.search(
                r"\[(?:get_ports|all_inputs|all_outputs)\b", target):
            continue
        values.append(float(match.group(1)))
    return values


def parse_check_types(body: str, *, scene: str, mode: str,
                      violators_only: bool) -> dict[str, list[dict]]:
    """Parse OpenSTA 3.1 verbose Pin blocks; preserve rise/fall and tool slack."""
    out: dict[str, list[dict]] = {kind: [] for kind in KINDS}
    kind = None
    row: dict[str, Any] | None = None
    for raw in body.splitlines():
        line = raw.strip()
        if line in _TITLES:
            kind = _TITLES[line]
            row = None
            continue
        pin = _PIN.fullmatch(line)
        if pin and kind:
            row = {"pin": pin.group(1), "direction":
                   {"^": "rise", "v": "fall"}.get(pin.group(2), "none"),
                   "scene": scene, "mode": mode}
            out[kind].append(row)
            continue
        if row is None or kind is None:
            continue
        status = re.fullmatch(r"Slack\s+\((VIOLATED|MET)\)", line)
        if status:
            # Native fanout reports can omit the numeric slack while retaining
            # an explicit verdict. Preserve that verdict without inventing slack.
            row["violated"] = status.group(1) == "VIOLATED"
            continue
        metric = _METRIC.fullmatch(line)
        if not metric:
            continue
        name = metric.group(1).strip().lower()
        limit_name, measured_name = _VALUES[kind]
        if name == limit_name:
            row["limit"] = float(metric.group(2))
        elif name == measured_name:
            row["measured"] = float(metric.group(2))
        elif name == "slack":
            row["slack"] = float(metric.group(2))
            row["violated"] = "(VIOLATED)" in line or row["slack"] < 0
    if violators_only:
        for rows in out.values():
            rows[:] = [r for r in rows if r.get("violated")]
    return out


def _attribute(block: str, key: str) -> float | None:
    hit = re.search(rf"\b{re.escape(key)}\s*:\s*({_NUM})\s*;", block)
    return float(hit.group(1)) if hit else None


def _balanced_block(text: str, start: int) -> str:
    opening = text.find("{", start)
    if opening < 0:
        return ""
    depth = 1
    # Liberty strings/comments may contain braces without opening a group.
    for token in re.finditer(r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\n]*|[{}]',
                             text[opening + 1:], flags=re.S):
        if token[0] == "{":
            depth += 1
        elif token[0] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1:opening + 1 + token.start()]
    return ""


def _liberty_limits(body: str) -> dict:
    """Read direct pin attributes in any order, excluding nested groups."""
    # PDK Liberty writers commonly split a unit declaration with a Tcl-style
    # backslash/newline (the linked gf180 IO library does exactly this).
    body = re.sub(r"\\\s*\n\s*", " ", body)
    time_match = re.search(r'time_unit\s*:\s*"?(' + _NUM +
                           r')\s*(fs|ps|ns|us|ms|s)"?', body, re.I)
    cap_match = re.search(r'capacitive_load_unit\s*\(\s*(' + _NUM +
                          r')\s*,\s*"?(ff|pf|nf|uf)"?\s*\)', body, re.I)
    if not time_match or not cap_match:
        raise ValueError("Liberty time/capacitance units absent")
    time_scale = float(time_match.group(1)) * {
        "fs": 1e-6, "ps": 1e-3, "ns": 1, "us": 1e3,
        "ms": 1e6, "s": 1e9}[time_match.group(2).lower()]
    cap_scale = float(cap_match.group(1)) * {
        "ff": 1e-3, "pf": 1, "nf": 1e3, "uf": 1e6}[cap_match.group(2).lower()]
    scales = {"max_slew": time_scale, "max_capacitance": cap_scale,
              "max_fanout": 1}
    def scaled(block: str, kind: str, prefix: str = "") -> float | None:
        value = _attribute(block, prefix + kind.replace("max_slew", "max_transition"))
        return value * scales[kind] if value is not None else None
    first_cell = re.search(r"\bcell\s*\(", body)
    header = body[:first_cell.start()] if first_cell else body
    defaults = {kind: scaled(header, kind, "default_")
                for kind in KINDS}
    default_fanout_load = _attribute(header, "default_fanout_load")
    cells: dict[str, dict] = {}
    ff_states: dict[str, set[str]] = {}
    pad_cells: set[str] = set()
    for cell in re.finditer(r'\bcell\s*\(\s*"?([^"\)]+)"?\s*\)\s*\{', body):
        cell_body = _balanced_block(body, cell.start())
        if re.search(r"\bpad_cell\s*:\s*true\s*;", cell_body, re.I):
            pad_cells.add(cell.group(1).strip())
        pins = {}
        for pin in re.finditer(r'\bpin\s*\(\s*"?([^"\)]+)"?\s*\)\s*\{', cell_body):
            pin_body = _balanced_block(cell_body, pin.start())
            # Liberty permits pin attributes after timing/power tables. Keep
            # every direct attribute while discarding child-group bodies.
            direct_chars = []
            depth = 0
            for char in pin_body:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                elif depth == 0:
                    direct_chars.append(char)
            direct = "".join(direct_chars)
            pins[pin.group(1).strip()] = {
                kind: scaled(direct, kind)
                for kind in KINDS}
            pins[pin.group(1).strip()]["fanout_load"] = _attribute(direct, "fanout_load")
            pin_name = pin.group(1).strip()
            related = re.findall(r'\brelated_pin\s*:\s*"?([^";]+)"?\s*;', cell_body)
            pins[pin_name]["has_timing_arc"] = (
                bool(re.search(r"\btiming\s*\(", pin_body)) or
                any(pin_name in value.split() for value in related))
        cells[cell.group(1).strip()] = pins
        states = set()
        # Only direct cell groups declare FF state; quoted descriptions,
        # comments and child-group bodies cannot supply model authority.
        depth = 0
        tokens = re.finditer(
            r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\n]*'
            r'|(?P<ff>\bff\s*\((?P<names>[^()]+)\)\s*\{)'
            r'|[A-Za-z_][\w.-]*|(?P<brace>[{}])', cell_body, flags=re.S)
        for token in tokens:
            if token["ff"] is not None:
                names = [re.fullmatch(r'\s*(?:"([A-Za-z_]\w*)"|([A-Za-z_]\w*))\s*', part)
                         for part in token["names"].split(",")]
                if depth == 0 and len(names) in (1, 2) and all(names):
                    states.update(name[1] or name[2] for name in names)
                depth += 1
            elif token["brace"] == "{":
                depth += 1
            elif token["brace"] == "}":
                depth -= 1
        ff_states[cell.group(1).strip()] = states
    return {"defaults": defaults, "cells": cells, "pad_cells": pad_cells,
            "default_fanout_load": default_fanout_load, "ff_states": ff_states}


def _liberty_header(body: str) -> dict[str, float | None]:
    first_cell = re.search(r"\bcell\s*\(", body)
    head = body[:first_cell.start()] if first_cell else body
    return {key: _attribute(head, key) for key in
            ("nom_process", "nom_voltage", "nom_temperature")}


def _key(kind: str, row: dict) -> tuple:
    if kind == "max_slew":
        return row["pin"], row["scene"], row["direction"]
    if kind == "max_capacitance":
        return row["pin"], row["scene"]
    return row["pin"], row["mode"]


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _integrator_value(body: str, *keys: str) -> float | None:
    for key in keys:
        matches = re.findall(rf"(?m)^\s*set\s+::env\({re.escape(key)}\)\s+({_NUM})(?=\s|$)", body)
        if matches:
            return float(matches[-1])
    return None


def _installed_image_digest(image: str) -> str | None:
    """Read the actual local image identity; a bundle cannot assert its own pin."""
    try:
        import _container_exec as _ce
        if _ce.no_container_route():
            import librelane_contract as _ll
            try:
                return _ll.local_image_attestation(image)["image_id"]
            except _ll.Refusal:
                return None
        process = subprocess.run(
            ["docker", "image", "inspect", image, "--format", "{{json .}}"],
            capture_output=True, text=True, check=False, timeout=15)
        if process.returncode:
            return None
        value = json.loads(process.stdout).get("Id")
        return value if re.fullmatch(r"sha256:[0-9a-f]{64}", str(value)) else None
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return None


def _script_reads(body: str) -> list[tuple[str, str]]:
    return re.findall(
        r"(?m)^\s*(read_liberty|read_verilog|read_sdc|read_spef)\s+\{([^{}]+)\}\s*$",
        body)


def _owner_records(project: Path | None, identity: dict, current: dict,
                   frozen: dict) -> tuple[list[dict], str]:
    """Read only independently signed owner records, never the capture plan."""
    try:
        signers = _OWNER_SIGNERS.read_text()
    except OSError:
        return [], "OWNER_SIGNATURE_UNREADABLE"
    entries = [line.strip() for line in signers.splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    if not entries:
        return [], "OWNER_SIGNATURE_UNAVAILABLE"
    if not any(line.strip().startswith("owner ") for line in signers.splitlines()):
        return [], "OWNER_SIGNATURE_INVALID"
    if project is None:
        return [], "OWNER_PROJECT_UNBOUND"
    expected = {
        "run_id": identity.get("run_id"),
        "tree_sha": identity.get("tree_sha"),
        "netlist_sha256": identity.get("sta_netlist"),
        "sdc_sha256": (current.get("sources") or {}).get("signoff_sdc", {}).get("sha256"),
        "l7_sha256": (frozen.get("sources") or {}).get("l7"),
        "l9_sha256": (frozen.get("sources") or {}).get("l9"),
        "pdk_config_sha256": (frozen.get("sources") or {}).get("pdk_config"),
        "spec_version": identity.get("spec_version"),
    }
    approved: list[dict] = []
    folder = project / "owner_approvals" / "drv"
    for path in sorted(folder.glob("*.json")):
        signature = path.with_suffix(path.suffix + ".sig")
        if not signature.is_file():
            continue
        try:
            payload = path.read_bytes()
            process = subprocess.run(
                ["ssh-keygen", "-Y", "verify", "-f", str(_OWNER_SIGNERS),
                 "-I", "owner", "-n", "vibeic-drv-owner", "-s", str(signature)],
                input=payload, capture_output=True, check=False)
            if process.returncode:
                continue
            record = json.loads(payload)
            if not isinstance(record, dict):
                continue
            kind = record.get("type")
            # A threshold freeze precedes the complete implementation run.
            # Its routed netlist does not exist yet; the other owner decisions
            # concern measured nets and keep the exact netlist binding.
            binding = ({key: value for key, value in expected.items()
                        if key != "netlist_sha256"}
                       if kind == "threshold_freeze" else expected)
            if (record.get("identity") == binding and kind in
                    ("waiver", "design_override", "clock_limits",
                     "threshold_freeze")):
                approved.append(record)
        except (OSError, ValueError, TypeError):
            continue
    return approved, "OWNER_APPROVAL_ABSENT"


def _approved_before_run(record: dict, identity: dict) -> bool:
    try:
        approved = datetime.fromisoformat(record["owner_timestamp"])
        started = datetime.fromisoformat(identity["run_started_at"])
        return bool(record.get("owner_quote")) and approved.tzinfo is not None and (
            started.tzinfo is not None and approved < started)
    except (KeyError, TypeError, ValueError):
        return False


def _scene_profile_conditions(profile: object) -> dict | None:
    """The selected PDK's existing typed PVT/RC conditions, per scene."""
    if not isinstance(profile, dict):
        return None
    points, corners = profile.get("pvt"), profile.get("rc_corners")
    if (not isinstance(points, dict) or not points or
            not isinstance(corners, list) or not corners or
            not all(isinstance(rc, str) and rc for rc in corners)):
        return None
    for name, point in points.items():
        if (not isinstance(name, str) or not name or not isinstance(point, dict) or
                not all(isinstance(point.get(axis), (int, float)) and
                        not isinstance(point.get(axis), bool)
                        for axis in ("nom_voltage", "nom_temperature"))):
            return None
    return {f"{name}_{rc}": point for name, point in points.items() for rc in corners}


def _check_threshold_freeze(identity: dict, frozen: dict,
                            owner_records: list[dict],
                            fails: list[str], missing: list[str], *,
                            owner_status: str = "OWNER_APPROVAL_ABSENT",
                            scene_profile: dict | None = None) -> dict:
    """Reconcile the plan with committed values and any required owner signature.

    The data file is independent of the capture plan.  Its PDK defaults and
    design declarations are pinned by source hashes; the signed receipt binds
    the remaining run-specific SDC and complete Liberty selection before the
    run begins.  A plan cannot authorize its own change to either source.
    """
    try:
        payload = _THRESHOLD_FREEZES.read_bytes()
        standard_sha = hashlib.sha256(payload).hexdigest()
        doc = json.loads(payload)
        if doc.get("schema_version") != 1:
            raise ValueError("unsupported schema")
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        missing.append(f"threshold freeze record absent or invalid: {exc}")
        return {}
    pdk, library = identity.get("pdk"), identity.get("library")
    sources = frozen.get("sources") or {}
    pdk_defaults = [row for row in doc.get("defaults", [])
                    if row.get("pdk") == pdk and row.get("library") == library]
    defaults = [row for row in pdk_defaults
                if row.get("pdk_config_sha256") == sources.get("pdk_config")]
    if len(defaults) != 1:
        (fails if pdk_defaults else missing).append(
            "threshold source changed: PDK config" if pdk_defaults else
            "threshold freeze record absent for PDK/library")
        return {}
    source_pair = {key: sources.get(key) for key in ("l7", "l9")}
    pdk_designs = [row for row in doc.get("designs", [])
                   if row.get("pdk") == pdk and row.get("library") == library]
    designs = [row for row in pdk_designs
               if source_pair in (row.get("sources") if isinstance(
                   row.get("sources"), list) else [row.get("sources")])]
    if len(designs) != 1:
        design_name = identity.get("design") or identity.get("ic_name")
        project_parts = Path(str(identity.get("project") or "")).parts
        same_design = [row for row in pdk_designs
                       if row.get("design") == design_name or
                       row.get("design") in project_parts]
        (fails if same_design else missing).append(
            "threshold source changed: L7/L9" if same_design else
            "threshold freeze record absent for design/L7/L9")
        return {}
    standard = designs[0]
    if not standard.get("owner_approval_citation"):
        missing.append("threshold freeze owner approval citation absent")
    try:
        issued = datetime.fromisoformat(standard["issued_at"])
        started = datetime.fromisoformat(identity["run_started_at"])
        if issued.tzinfo is None or started.tzinfo is None or issued >= started:
            missing.append("threshold freeze record was not issued before run")
    except (KeyError, TypeError, ValueError):
        missing.append("threshold freeze issuance or run start is unverified")
    default_values = defaults[0].get("values") or {}
    values = frozen.get("values") or {}
    for field, expected in default_values.items():
        if field == "fanout":
            if values.get("default_fanout_ceiling") != expected:
                fails.append("threshold source changed: PDK fanout ceiling")
        elif values.get(field) != expected:
            fails.append(f"threshold source changed: PDK {field}")
    if values != standard.get("values"):
        fails.append("threshold source changed: declared values")
    for field in ("scope", "scenes", "rc_corners"):
        if frozen.get(field) != standard.get(field):
            fails.append(f"threshold source changed: {field}")
    conditions = _scene_profile_conditions(scene_profile)
    expected_pvt = standard.get("pvt") or {}
    if conditions is None:
        fails.append("threshold source changed: active PDK scene profile incomplete")
    elif (set(conditions) != set(standard.get("scenes") or []) or
          set(scene_profile["rc_corners"]) != set(standard.get("rc_corners") or []) or
          any(not isinstance(expected_pvt.get(name), dict) or
              any(expected_pvt[name].get(axis) != value for axis, value in point.items())
              for name, point in conditions.items())):
        fails.append("threshold source changed: active PDK scene profile")
    for scene, expected in (standard.get("pvt") or {}).items():
        actual = (frozen.get("pvt") or {}).get(scene) or {}
        if any(actual.get(key) != value for key, value in expected.items()):
            fails.append(f"threshold source changed: {scene} PVT")
    if set(frozen.get("pvt") or {}) != set(standard.get("pvt") or {}):
        fails.append("threshold source changed: PVT scene set")
    actual_libs = frozen.get("liberties") or {}
    standard_libs = standard.get("liberties") or {}
    if sorted(actual_libs.values()) != sorted(standard_libs.values()):
        fails.append("threshold source changed: Liberty identities")
    actual_links = frozen.get("scene_liberties") or {}
    standard_links = standard.get("scene_liberties") or {}
    if set(actual_links) != set(standard_links):
        fails.append("threshold source changed: scene Liberty set")
    else:
        for scene, names in standard_links.items():
            expected = [standard_libs.get(name) for name in names]
            actual = [actual_libs.get(name) for name in actual_links[scene]]
            if None in expected or None in actual or sorted(expected) != sorted(actual):
                fails.append(f"threshold source changed: {scene} Liberty selection")
    supplied = [record for record in owner_records
                if record.get("type") == "threshold_freeze"]
    signed = [record for record in supplied
              if record.get("type") == "threshold_freeze"
              and record.get("standard_sha256") == standard_sha
              and record.get("thresholds") == frozen
              and _approved_before_run(record, identity)]
    # R-0929-DRV-FREEZE: the committed standard is the approval until the
    # owner registers a key. Unreadable/malformed registries never imply that
    # state, and an unsigned standard is never labelled signature-verified.
    if not signed and owner_status != "OWNER_SIGNATURE_UNAVAILABLE":
        (fails if supplied else missing).append(
            "threshold source changed: signed threshold_freeze" if supplied else
            "validated threshold_freeze owner record absent before run")
    return {"standard_sha256": standard_sha,
            "design": standard.get("design"),
            "issued_at": standard.get("issued_at"),
            "owner_approval_citation": standard.get("owner_approval_citation"),
            "signed_owner_record_verified": bool(signed)}


def _annotate_limits(row: dict, kind: str, scene: dict, libs: dict,
                     pins: dict, declared: dict, missing: list[str]) -> bool:
    """Resolve a pin against the Liberty files linked by this STA scene."""
    meta = pins.get(row["pin"])
    if not isinstance(meta, dict):
        missing.append(f"{scene['name']}: pin metadata absent for {row['pin']}")
        return False
    row.update({key: value for key, value in meta.items() if key != "liberty"})
    if row.get("net_class") not in ("clock", "data", "IO", "constant"):
        missing.append(f"{scene['name']}: pin/net class absent for {row['pin']}")
        return False
    cell, cell_pin = row.get("cell"), row.get("cell_pin")
    is_port = row.get("cell_class") == "port" and not cell and not cell_pin
    is_internal = row.get("cell_class") == "internal" and not row.get("net")
    matched = []
    for linked in scene.get("linked_liberties") or []:
        lib = libs.get(linked.get("name")) if isinstance(linked, dict) else None
        if lib and cell in lib["limits"]["cells"]:
            if is_internal:
                # FF state variables have no physical pin table. Their cell
                # still binds the existing core-scoped sign-off declaration.
                pin_table = ({} if kind == "max_slew" and
                    cell_pin in lib["limits"]["ff_states"].get(cell, set()) and
                    cell_pin not in lib["limits"]["cells"][cell] else None)
            else:
                pin_table = lib["limits"]["cells"][cell].get(cell_pin)
            if pin_table is not None:
                matched.append((linked["name"], lib, pin_table))
    if len(matched) != 1 and not is_port:
        missing.append(f"{scene['name']}: cell/pin Liberty identity unresolved for "
                       f"{row['pin']} ({len(matched)} matches)")
        return False
    lib_name, lib, pin_table = matched[0] if matched else (None, None, {})
    actual_io = bool(lib and cell in lib["limits"]["pad_cells"])
    if row.get("cell_class") == "IO" and not actual_io:
        missing.append(f"{scene['name']}: IO class lacks Liberty pad_cell proof for {row['pin']}")
        return False
    row["cell_class"] = ("port" if is_port else "internal" if is_internal else
                         "IO" if actual_io else "std")
    if row["net_class"] == "clock" and row["pin"] not in (
            scene.get("clock_network_pins") or []):
        missing.append(f"{scene['name']}: clock net classification lacks tool proof for {row['pin']}")
        return False
    pin_limit = pin_table.get(kind)
    if pin_limit is None and lib is not None and not is_internal:
        pin_limit = lib["limits"]["defaults"].get(kind)
    explicit = declared.get({"max_slew": "slew_ns",
                             "max_capacitance": "cap_pf",
                             "max_fanout": "fanout"}[kind])
    if (kind == "max_slew" and declared.get("core_scoped_slew") and
            lib_name != scene.get("liberty")):
        # This SDC binds the declared slew to core masters, not to every
        # linked library. Keep actual port constraints on their named net;
        # other IO/macro pins retain their own linked Liberty limit.
        port = row["pin"] if is_port else row.get("net")
        explicit = (declared.get("port_slew_limits") or {}).get(port)
    if kind == "max_capacitance" and row.get("cell_class") == "IO":
        explicit = declared.get("io_cap_pf")
    if kind == "max_fanout" and row["net_class"] == "clock":
        explicit = declared.get("clock_fanout", explicit)
    limits = [v for v in (pin_limit, explicit) if _positive_number(v)]
    if not limits:
        missing.append(f"{scene['name']}: no Liberty or declared limit for "
                       f"{kind} {row['pin']}")
        return False
    row["kind"] = kind
    row["liberty_limit"] = pin_limit
    row["explicit_limit"] = explicit
    row["effective_limit"] = min(limits)
    row["liberty_source"] = ({"name": lib_name,
                               "path": lib["identity"].get("path"),
                               "sha256": lib["identity"].get("sha256"),
                               "pin": cell_pin} if lib is not None else None)
    row["limit_source"] = (
        "Liberty" if _positive_number(pin_limit) and
        pin_limit <= (explicit if _positive_number(explicit) else pin_limit)
        else "design/PDK sign-off declaration")
    row["load_pin"] = (kind == "max_slew" and
                       row.get("driver_pin", row["pin"]) != row["pin"])
    row["liberty_usage"] = (row["measured"] / pin_limit
                            if _positive_number(pin_limit) else None)
    return True


def _waiver_support(waiver: dict, row: dict, bundle: dict,
                    source_errors: list[str], owner_records: list[dict]) -> bool:
    """Section 6: accept numerical, content-addressed timing/EM evidence."""
    local_errors: list[str] = []
    identity = bundle["identity"]
    declared = bundle["frozen"]["values"]
    scenes = set(bundle["frozen"]["scenes"])
    timing = waiver.get("timing") or []
    if {r.get("scene") for r in timing} != scenes or len(timing) != len(scenes):
        return False
    for receipt in timing:
        if (receipt.get("netlist_sha256") != identity.get("sta_netlist") or
                receipt.get("sdc_sha256") != bundle["current"]["sources"]["signoff_sdc"]["sha256"] or
                receipt.get("period_ns") != declared.get("period_ns") or
                receipt.get("io_delay_ns") != declared.get("io_delay_ns") or
                not isinstance(receipt.get("setup_slack_ns"), (int, float)) or
                not isinstance(receipt.get("hold_slack_ns"), (int, float)) or
                receipt["setup_slack_ns"] < 0 or receipt["hold_slack_ns"] < 0):
            return False
        timing_text = _evidence(receipt.get("report") or {}, local_errors,
                                "waiver timing " + str(receipt.get("scene")))
        from sta_corner_record_completeness_check import extract_slacks
        slacks = extract_slacks(timing_text)
        if (slacks["setup_wns_ns"] is None or slacks["hold_wns_ns"] is None or
                slacks["setup_wns_ns"] < 0 or slacks["hold_wns_ns"] < 0 or
                abs(slacks["setup_wns_ns"] - receipt["setup_slack_ns"]) > 1e-6 or
                abs(slacks["hold_wns_ns"] - receipt["hold_slack_ns"]) > 1e-6):
            return False
    em = waiver.get("signal_em") or {}
    if (em.get("netlist_sha256") != identity.get("sta_netlist") or
            em.get("scene") not in scenes or not em.get("worst_scene") or
            not em.get("drm_source")):
        return False
    em_text = _evidence(em.get("report") or {}, local_errors,
                        "waiver signal EM")
    _evidence(em.get("drm_source") or {}, local_errors, "waiver DRM")
    try:
        measured_em = json.loads(em_text)
        if (measured_em.get("currents") != em.get("currents") or
                measured_em.get("limits") != em.get("limits")):
            return False
    except (ValueError, TypeError, AttributeError):
        return False
    for axis in ("average", "rms", "peak"):
        measured = (em.get("currents") or {}).get(axis)
        limit = (em.get("limits") or {}).get(axis)
        if not isinstance(measured, (int, float)) or not _positive_number(limit) or measured > limit:
            return False
    if row["net_class"] == "clock":
        clocks = waiver.get("clock_metrics") or {}
        prior = next((record for record in owner_records
                      if record.get("type") == "clock_limits" and
                      _approved_before_run(record, identity) and
                      _positive_number(record.get("skew_limit")) and
                      _positive_number(record.get("latency_limit"))), None)
        clock_text = _evidence(clocks.get("report") or {}, local_errors,
                               "waiver clock metrics")
        try:
            measured_clocks = json.loads(clock_text)
        except (ValueError, TypeError):
            measured_clocks = {}
        if (prior is None or
                clocks.get("skew") != measured_clocks.get("skew") or
                clocks.get("latency") != measured_clocks.get("latency") or
                not isinstance(clocks.get("skew"), (int, float)) or
                not isinstance(clocks.get("latency"), (int, float)) or
                clocks["skew"] > prior["skew_limit"] or
                clocks["latency"] > prior["latency_limit"] or
                waiver.get("clock_reason") not in
                ("intentional_cts_tradeoff", "unfixed_tool_defect")):
            return False
        if waiver["clock_reason"] == "unfixed_tool_defect" and not (
                waiver.get("upstream_issue") and waiver.get("pinned_tool_reproducer")
                and waiver.get("upstream_unfixed") is True):
            return False
    source_errors.extend(local_errors)
    return not local_errors


def _record(ref: dict, missing: list[str], label: str) -> dict | None:
    """A flow record the bundle binds by sha256, RE-READ from its file: the
    judgement is about what the record says, never the bundle's copy of it."""
    text = _evidence(ref or {}, missing, label)
    if not text:
        return None
    try:
        doc = json.loads(text)
    except ValueError:
        doc = None
    if not isinstance(doc, dict):
        missing.append(f"{label}: not a JSON object")
        return None
    return doc


def _filled_lvs_association(identity: dict, inputs: dict) -> bool:
    """Re-read the existing native fill bridge between STA and filled LVS."""
    try:
        import _physical_current as physical
        import librelane_fill_dfm as fill
        project = Path(identity["project"]).resolve()
        selected = physical.default_signoff_inputs(project)
        if (selected is None or physical.digest(selected["gds"]) !=
                identity["derivation"]["gds"]["sha256"]):
            return False
        fill.validate_fill_consumption(project)
        tool = json.loads((project / fill.RECORD_REL).read_text())["odb"]["tool"]
        before = json.loads(Path(tool["binding"]["input_state"]).read_text())
        after = json.loads(Path(tool["state"]).read_text())
        if tool.get("refusals") != []:
            return False
        config = json.loads(Path(tool["binding"]["config"]).read_text())
        census = fill.fill_census(Path(before["def"]).read_text(),
                                  Path(after["def"]).read_text(),
                                  fill.cell_patterns(config))
        if (census != tool.get("census") or census["removed"]
                or census["per_class"]["other"]):
            return False
        artifacts = identity["artifacts"]
        before_def, before_nl = Path(before["def"]), Path(before["nl"])
        if (physical.digest(before_def) != artifacts["def"]["sha256"]
                or physical.digest(before_nl) != identity["sta_netlist"]):
            return False
        for name, role, state_role in (("layout_def", "def", "def"),
                                       ("schematic_netlist", "netlist", "nl")):
            row = inputs[name]
            if (Path(row["path"]).resolve() != selected[role].resolve()
                    or physical.digest(selected[role]) != row["sha256"]
                    or physical.digest(Path(after[state_role])) != row["sha256"]):
                return False
        return (identity["lvs_netlist"] == physical.digest(selected["netlist"])
                and identity["gds_netlist"] in
                    (identity["sta_netlist"], identity["lvs_netlist"]))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
        return False


def _check_post_stream_derivation(identity: dict, fails: list[str],
                                  missing: list[str]) -> bool:
    """R-0929-DRV-IDENTITY: the final capture proves the streamed GDS and the
    LVS netlist derive from the judged DEF / netlist.  Every file is
    re-hashed and every record re-read here (review wave 58: the bundle's
    copy of a record's fields was trusted); a record the flow did not write is
    NOT_MEASURED, a link that names a different DEF or netlist is FAIL (the
    verdict would be about another layout)."""
    derivation = identity.get("derivation")
    artifacts = identity.get("artifacts") or {}
    judged_def = (artifacts.get("def") or {}).get("sha256")
    if not isinstance(derivation, dict):
        missing.append("post-stream derivation record absent")
        return False
    gds = derivation.get("gds")
    if not isinstance(gds, dict):
        missing.append("post-stream GDS admission record absent")
    else:
        _evidence(gds, missing, "streamed GDS")
        admission = _record(gds.get("record") or {}, missing, "GDS admission record")
        if admission is not None:
            streamed_from = (admission.get("basis_inputs") or {}).get(
                "phase3/stage3/pnr/routed.def")
            if admission.get("gds_sha256") != gds.get("sha256"):
                missing.append("GDS admission record admits another stream than the bound GDS")
            if not streamed_from:
                missing.append("streamed GDS names no source DEF")
            elif streamed_from != judged_def:
                fails.append("streamed GDS derives from a DEF other than the judged DEF")
    lvs = derivation.get("lvs")
    if not isinstance(lvs, dict):
        missing.append("post-stream LVS record absent")
        return False
    inputs_ref = lvs.get("inputs_record") or {}
    inputs = _record(inputs_ref, missing, "LVS inputs record")
    verdict = _record(lvs.get("verdict_record") or {}, missing, "LVS verdict record")
    if inputs is None or verdict is None:
        return False
    # The verdict is the verdict OF these inputs only when step 31 wrote it
    # while this very record stood (a stale PASS of another layout is not).
    if (verdict.get("lvs_inputs") or {}).get("sha256") != inputs_ref.get("sha256"):
        missing.append("LVS verdict is not bound to the recorded LVS inputs")
    layout = (inputs.get("layout_def") or {}).get("sha256")
    schematic = inputs.get("schematic_netlist") or {}
    # The netlist LVS compared is the one it recorded, by those bytes.
    _evidence(schematic, missing, "LVS schematic netlist")
    if (lvs.get("schematic_netlist") or {}).get("sha256") != schematic.get("sha256"):
        missing.append("bundle LVS netlist differs from the LVS inputs record")
    filled = _filled_lvs_association(identity, inputs)
    if not layout:
        missing.append("LVS names no layout DEF")
    elif layout != judged_def and not filled:
        fails.append("LVS compared a layout DEF other than the judged DEF")
    if schematic.get("sha256") != identity.get("sta_netlist") and not filled:
        fails.append("LVS compared a netlist other than the judged STA netlist")
    if verdict.get("status") != "PASS" or verdict.get("compare_performed") is False:
        missing.append(f"LVS did not prove the layout matches the netlist "
                       f"(verdict {verdict.get('status')})")
    return filled


#: The DRV standard's listed (never gated, never dropped) row classes
#: (R-0928-DRV-IC, section 4, R-0929-CAP-MARGIN-SCOPE).  Every reader -- this
#: judge, the capture census, Step 32's PRR census, sta_record R5 -- applies
#: the SAME two rules below; none carries its own copy.
OFFCHIP_PORT_TO_PAD_NET = "OFFCHIP_PORT_TO_PAD_NET"
IO_STD_CELL_MARGIN_DISCLOSURE = "IO_STD_CELL_MARGIN_DISCLOSURE"


def port_to_pad(port: str, net_pins, is_pad_pin) -> bool:
    """A top-level port whose net reaches nothing but IO-cell (pad_cell) pins:
    the off-chip port-to-PAD net.  `net_pins` is every pin on the port's net
    (drivers and loads, the port itself included or not); `is_pad_pin(pin)`
    answers from the reader's own source (OpenSTA net census or netlist)."""
    others = [pin for pin in net_pins if pin != port]
    return bool(others) and all(is_pad_pin(pin) for pin in others)


def io_margin_scope(kind: str, cell_class: str | None, explicit_limit,
                    tool_limit, cap_margin) -> bool:
    """An IO-cell pin whose tool limit IS the design-scope std-cell cap margin
    (R-0929-CAP-MARGIN-SCOPE): the known inheritance, not an instrument
    disagreement."""
    return (kind == "max_capacitance" and cell_class == "IO" and
            explicit_limit is None and tool_limit is not None and
            _positive_number(cap_margin) and tool_limit == cap_margin)


def io_margin_disclosure(kind: str, cell_class: str | None, explicit_limit,
                         tool_limit, measured, io_limit, cap_margin) -> bool:
    """Section 4: an IO-cell row the tool FLAGGED against the std-cell margin
    while within its own IO Liberty limit is listed apart, not gated."""
    return (io_margin_scope(kind, cell_class, explicit_limit, tool_limit, cap_margin)
            and measured is not None and _positive_number(io_limit) and
            tool_limit < measured <= io_limit)


def def_identity(bundle: dict, layout_def: Path | None) -> str | None:
    """THE comparison of a layout DEF with the bundle's judged DEF identity,
    shared by every caller (the CLI's current routed DEF and step-23 tool-arm
    DEF, step 32's final DEF): "absent", "differs", or None when it is the
    judged layout."""
    recorded = ((bundle.get("identity") or {}).get("artifacts") or {}).get(
        "def", {}).get("sha256")
    if layout_def is None or not Path(layout_def).is_file():
        return "absent"
    return None if recorded and _sha(Path(layout_def)) == recorded else "differs"


def judge(bundle: dict, *, project: Path | None = None) -> dict:
    """Judge measured rows independently of tool rc/checker summaries."""
    import instrument_calibration
    instrument_calibration.assert_calibrated("drv_signoff_judge::parse_check_types")
    fails: list[str] = []
    missing: list[str] = []
    findings: list[dict] = []
    io_margin_disclosures: list[dict] = []
    offchip_port_rows: list[dict] = []
    waived: list[dict] = []
    identity = bundle.get("identity") or {}
    frozen = bundle.get("frozen") or {}
    current = bundle.get("current") or {}
    owner_records, owner_status = _owner_records(project, identity, current, frozen)
    declared = frozen.get("values") or {}
    run_id, tree_sha = identity.get("run_id"), identity.get("tree_sha")
    profiles = json.loads(_SCENE_PROFILES.read_text())
    profile = next((value for key, value in profiles.items()
                    if str(identity.get("pdk", "")).lower().startswith(key.lower())), None)
    freeze_evidence = {}
    if project is not None:
        freeze_evidence = _check_threshold_freeze(
            identity, frozen, owner_records, fails, missing, owner_status=owner_status,
            scene_profile=profile)
        if Path(str(identity.get("project") or "")).resolve() != project.resolve():
            missing.append("project identity differs from judged project directory")
    if not run_id or not tree_sha or not identity.get("spec_version"):
        missing.append("run ID, tree SHA or specification version absent")
    # R-0929-DRV-IDENTITY: an in-flow capture (step 23, step 32, pre-stream)
    # cannot bind GDS / LVS-netlist identity, which exists only after
    # stream-out; it names them as bound at the final post-stream capture.
    # Any other capture (the default) must bind them.  The in-flow verdict is
    # never the final one: the post-stream verdict counts toward IC PASS.
    capture_point = "in_flow" if identity.get("capture_point") == "in_flow" else "post_stream"
    bound_at = identity.get("bound_at") if capture_point == "in_flow" else {}
    deferred = {name: str((bound_at or {}).get(name)) for name in ("lvs_netlist", "gds_netlist")
                if isinstance(bound_at, dict) and (bound_at or {}).get(name)}
    for name in ("sta_netlist", "lvs_netlist", "gds_netlist"):
        if name in deferred:
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", str(identity.get(name) or "")):
            missing.append(f"{name} sha256 absent")
    for name in ("sta_netlist", "lvs_netlist", "gds_netlist", "odb", "def"):
        if name in deferred:
            continue
        item = (identity.get("artifacts") or {}).get(name) or {}
        _evidence(item, missing, name)
        if name.endswith("netlist") and item.get("sha256") != identity.get(name):
            fails.append(f"{name}: recorded netlist sha256 disagrees with file")
    filled_association = False
    if capture_point == "post_stream":
        filled_association = _check_post_stream_derivation(identity, fails, missing)
    identified_netlists = [identity.get(name) for name in
                           ("sta_netlist", "lvs_netlist", "gds_netlist")
                           if identity.get(name)]
    if len(set(identified_netlists)) > 1 and not filled_association:
        fails.append("STA/LVS/GDS netlist identity mismatch")
    for name in ("openroad_commit", "opensta_commit", "pdk_commit"):
        if not identity.get(name):
            missing.append(f"{name} absent")
    image = identity.get("tool_image")
    digest = identity.get("tool_image_digest")
    if (not isinstance(image, str) or
            not re.fullmatch(r"sha256:[0-9a-f]{64}", str(digest)) or
            _installed_image_digest(image) != digest):
        missing.append("OpenSTA image digest not bound to installed image")
    if project is not None:
        try:
            anchor_image = image
            provenance_path = project / "phase3/librelane_pdk_root.provenance.json"
            root_doc = json.loads(provenance_path.read_text()) if provenance_path.is_file() else {}
            if root_doc.get("source") == "local_provider" or identity.get("source_tool_provider"):
                from drv_signoff_anchor import pdk_source_identity
                from librelane_signoff_evidence import _retained_local_provider
                source = pdk_source_identity(root_doc, project=project)
                try:
                    captured = _retained_local_provider(
                        project, identity.get("source_tool_provider"),
                        identity.get("source_tool_image"))
                except (ValueError, LocalProviderRefusal):
                    raise ValueError("LOCAL source provider differs from capture") from None
                if (source.get("provider") != captured.as_record() or
                        source["pdk"] != identity.get("pdk") or
                        identity.get("source_tool_image") != identity.get("source_tool_image_id")):
                    raise ValueError("LOCAL source provider differs from capture")
                anchor_image = source["image"]
            anchor = image_pdk_anchor(
                anchor_image, str(identity.get("pdk") or ""),
                str(identity.get("library") or ""))
            if bundle.get("threshold_anchor") != anchor:
                missing.append("frozen threshold anchor differs from installed image")
            if ((frozen.get("sources") or {}).get("pdk_config") != anchor["sha256"] or
                    (current.get("sources") or {}).get("pdk_config", {}).get("sha256")
                    != anchor["sha256"]):
                fails.append("PDK threshold source differs from pinned image")
            if identity.get("pdk_commit") != anchor.get("pdk_commit"):
                missing.append("PDK commit differs from pinned image version")
        except (OSError, ValueError, TypeError, KeyError, AttributeError, LocalProviderRefusal,
                subprocess.TimeoutExpired) as exc:
            missing.append(f"installed PDK threshold anchor unavailable: {exc}")
    source_texts = {}
    for name in ("l7", "l9", "pdk_config", "signoff_sdc"):
        item = (current.get("sources") or {}).get(name) or {}
        source_texts[name] = _evidence(item, fails, name)
        if item.get("sha256") != (frozen.get("sources") or {}).get(name):
            fails.append(f"{name}: 門檻來源已變更")
    if project is not None:
        for layer in ("l7", "l9"):
            source_path = Path(str((current.get("sources") or {}).get(
                layer, {}).get("path") or "")).resolve()
            allowed = (project / "input/docs", project / "phase1/generated_docs")
            if not any(source_path.is_relative_to(root.resolve()) and
                       source_path.name.upper().startswith(layer.upper())
                       for root in allowed):
                missing.append(f"{layer}: declaration file outside judged project")
        provenance = project / "phase3/librelane_pdk_root.provenance.json"
        try:
            root_doc = json.loads(provenance.read_text())
            pdk_root = (Path(root_doc["path"]) / str(identity.get("pdk") or "")).resolve()
            pdk_source = Path(str((current.get("sources") or {}).get(
                "pdk_config", {}).get("path") or "")).resolve()
            if not pdk_root.is_dir() or not pdk_source.is_relative_to(pdk_root):
                missing.append("PDK config is not inside installed PDK root")
            if root_doc.get("source") == "local_provider":
                from drv_signoff_anchor import pdk_source_identity
                from librelane_signoff_evidence import _retained_local_provider
                source_id = pdk_source_identity(root_doc, project=project)["image_id"]
                captured = _retained_local_provider(
                    project, identity.get("source_tool_provider"),
                    identity.get("source_tool_image"))
                if identity.get("source_tool_image") != identity.get("source_tool_image_id"):
                    raise ValueError("LOCAL capture image identity is not self-bound")
                expected_source_id = str(captured)
            elif root_doc.get("source") == "declared":
                from drv_signoff_anchor import pdk_source_identity
                source_id = pdk_source_identity(root_doc, project=project)["image_id"]
                expected_source_id = (identity.get("source_tool_image_id") or
                                      identity.get("tool_image_digest"))
            else:
                source_id = (root_doc.get("derivation") or {}).get("image_id")
                expected_source_id = (identity.get("source_tool_image_id") or
                                      identity.get("tool_image_digest"))
            if source_id != expected_source_id:
                missing.append("installed PDK root image identity differs from producer image")
        except (OSError, ValueError, TypeError, KeyError, AttributeError, LocalProviderRefusal):
            missing.append("installed PDK root provenance unavailable")
    sdc = (current.get("sources") or {}).get("signoff_sdc") or {}
    sdc_text = _evidence(sdc, fails, "signoff_sdc")
    from sdc_environment import PAD_OPERATING_SCENE_TCL
    # Exports embed the same producer literal in the saved variable and body.
    # Only its exact copies are known; changed or additional commands remain.
    sdc_exclusions = sdc_text.replace(PAD_OPERATING_SCENE_TCL, "")
    if _FORBIDDEN_SDC.search(sdc_exclusions) and not bundle.get("owner_exclusion_declaration"):
        missing.append("DRV exclusions in sign-off SDC lack prior owner declaration")
    for field, command in (("fanout", "set_max_fanout"),
                           ("slew_ns", "set_max_transition"),
                           ("cap_pf", "set_max_capacitance")):
        values = _sdc_values(sdc_text, command, include_ports=False)
        if not values:
            fails.append(f"sign-off SDC {command} absent")
        elif any(v != declared.get(field) for v in values):
            fails.append(f"sign-off SDC {command} != declared value")
    if (frozen.get("values") != current.get("values") or
            frozen.get("scenes") != current.get("scenes") or
            frozen.get("scope") != current.get("scope") or
            frozen.get("scene_liberties") != current.get("scene_liberties")):
        fails.append("門檻來源已變更: value/scope/scene")
    if frozen.get("scope") != "whole final netlist":
        fails.append("sign-off scope is not the whole final netlist")
    pdk_text = source_texts.get("pdk_config", "")
    integrator = {
        "fanout": _integrator_value(pdk_text, "MAX_FANOUT_CONSTRAINT", "SYNTH_MAX_FANOUT"),
        "slew_ns": _integrator_value(pdk_text, "MAX_TRANSITION_CONSTRAINT", "MAX_SLEW_CONSTRAINT"),
        "cap_pf": _integrator_value(pdk_text, "MAX_CAPACITANCE_CONSTRAINT", "MAX_CAP_CONSTRAINT"),
    }
    for field, value in integrator.items():
        if value is None:
            missing.append(f"PDK integrator {field} not extracted")
        elif field == "fanout" and declared.get("default_fanout_ceiling") != value:
            fails.append("default fanout ceiling != installed PDK config")
        elif field != "fanout" and declared.get(field) != value:
            signed_override = any(
                record.get("type") == "design_override" and
                record.get("field") == field and
                record.get("value") == declared.get(field) and
                record.get("reason") and
                _approved_before_run(record, identity)
                for record in owner_records)
            if not signed_override:
                fails.append(f"{field}: design override lacks signed prior owner "
                             f"rationale ({owner_status})")
    try:
        from declared_knob_applied_parity import collect_declared, _source_files
        declaration_project = project or Path(str(identity.get("project") or ""))
        if project is not None:
            l9_path = Path(str((current.get("sources") or {}).get("l9", {}).get("path") or ""))
            if l9_path.resolve() not in {p.resolve() for p in _source_files(project)}:
                missing.append("project L9 source is not a declaration file in judged project")
        if not identity.get("pdk") or not identity.get("library"):
            missing.append("L9 fanout scope identity lacks PDK or library")
        declared_l9 = collect_declared(declaration_project, pdk=str(identity.get("pdk") or ""),
                                       library=str(identity.get("library") or ""))
        l9_fanout = declared_l9.get("SYNTH_MAX_FANOUT")
        scoped_fanout = bool(re.search(
            r"(?im)^\s*\|\s*(?:pdk|library|lib|standard_cell_library)\s*\|[^\n]*"
            r"\bMAX_FANOUT_CONSTRAINT\b", source_texts.get("l9", "")))
        if l9_fanout and l9_fanout[0] != declared.get("fanout"):
            fails.append("L9 declared fanout != frozen sign-off value")
        elif not l9_fanout and scoped_fanout:
            missing.append("L9 fanout scope did not match judged PDK/library")
        elif not l9_fanout and declared.get("fanout") != integrator["fanout"]:
            fails.append("fanout has no L9 declaration or PDK-default basis")
    except (OSError, ValueError) as exc:
        missing.append(f"L9 design declaration unreadable: {exc}")
    required_scenes = frozen.get("scenes") or []
    if not required_scenes:
        missing.append("frozen corner/RC scene set absent")
    if profile is None:
        missing.append("installed PDK sign-off scene profile unresolved")
    elif _scene_profile_conditions(profile) is None:
        missing.append("installed PDK sign-off scene profile incomplete")
    else:
        expected_scenes = {f"{pvt}_{rc}" for pvt in profile["pvt"]
                           for rc in profile["rc_corners"]}
        if set(required_scenes) != expected_scenes or len(required_scenes) != len(expected_scenes):
            missing.append("installed PDK sign-off requires the fixed 3 PVT x 3 RC scenes")
        # The complete file digest remains provenance; only this PDK's
        # typed conditions define the run's frozen measurement conditions.
        if not re.fullmatch(r"[0-9a-f]{64}", str(frozen.get("scene_profile_sha256") or "")):
            missing.append("frozen PDK scene profile sha256 absent or invalid")
        for scene_name in required_scenes:
            pvt_key = next((key for key in profile["pvt"]
                            if scene_name.startswith(key + "_")), None)
            if pvt_key and any((frozen.get("pvt") or {}).get(scene_name, {}).get(axis)
                               != value for axis, value in profile["pvt"][pvt_key].items()):
                missing.append(f"{scene_name}: frozen PVT differs from installed PDK profile")
    libs = {}
    for item in current.get("liberties") or []:
        body = _evidence(item, fails, "linked Liberty")
        if body:
            libs[item.get("name")] = {"identity": item,
                                      "limits": _liberty_limits(body),
                                      "header": _liberty_header(body)}
        if item.get("sha256") != (frozen.get("liberties") or {}).get(item.get("name")):
            fails.append("linked Liberty changed or removed")
    if set(libs) != set(frozen.get("liberties") or {}):
        fails.append("linked Liberty set changed")
    if {key for group in (frozen.get("scene_liberties") or {}).values()
        for key in group} != set(frozen.get("liberties") or {}):
        missing.append("frozen scene Liberty inventory does not cover every linked file")
    for field in ("fanout", "slew_ns", "cap_pf"):
        if not _positive_number(declared.get(field)):
            missing.append(f"declared {field} absent")
    for field in ("period_ns", "io_delay_ns"):
        if not _positive_number(declared.get(field)):
            missing.append(f"declared {field} absent for waiver qualification")

    stage_rows = {s.get("name"): s for s in bundle.get("stages") or []}
    postroute_repair_ran = bool(bundle.get("postroute_repair_ran"))
    adoption_basis = identity.get('repair_adoption')
    if project is not None and adoption_basis is not None:
        try:
            from librelane_contract import postroute_repair_adoption
            layout = ((identity.get('artifacts') or {}).get('def') or {})
            current_adoption = postroute_repair_adoption(project, Path(layout['path']))
            if adoption_basis != current_adoption:
                missing.append('repair adoption basis differs from current layout-bound sources')
            postroute_repair_ran = current_adoption['adopted']
            if postroute_repair_ran != bool(bundle.get('postroute_repair_ran')):
                missing.append('step 32 repair adoption differs from DRV bundle')
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            missing.append(f'repair adoption basis unreadable: {exc}')
    elif project is not None:
        repair_report = project / "reports/phase3/librelane_postroute_repair.json"
        if repair_report.is_file():
            try:
                recorded_repair = json.loads(repair_report.read_text())
                postroute_repair_ran = bool(recorded_repair.get("adopted"))
                if recorded_repair.get("site") == "after_route":
                    route_handoff = project / "reports/phase3/librelane_route_handoff.json"
                    handoff = json.loads(route_handoff.read_text())
                    if ((handoff.get("postroute_repair") or {}).get(
                            "report_sha256") != _sha(repair_report)):
                        missing.append("step 32 in-chain repair receipt not bound to route handoff")
            except (OSError, ValueError, TypeError, AttributeError):
                missing.append("step 32 repair adoption receipt unreadable")
            if postroute_repair_ran != bool(bundle.get("postroute_repair_ran")):
                missing.append("step 32 repair adoption differs from DRV bundle")
    for name in _REQUIRED_STAGES:
        if name not in stage_rows:
            fails.append(f"{name}: required stage absent")
    if postroute_repair_ran and "postroute_repair" not in stage_rows:
        fails.append("postroute_repair: required applied constraints absent")
    broad_stage = False
    for name, stage in stage_rows.items():
        if name not in (*_REQUIRED_STAGES, "postroute_repair"):
            continue
        if not stage.get("ran") or not stage.get("behavior_report"):
            fails.append(f"{name}: did not run or lacks DRV behavior report")
        else:
            behavior = _evidence(stage["behavior_report"], fails, name + " behavior")
            if _COMMAND not in behavior or not all(
                    re.search(rf"\b{kind}\s+violators=\d+\b", behavior)
                    for kind in KINDS):
                fails.append(f"{name}: declared-value DRV behavior census absent")
        applied = stage.get("applied") or {}
        if name == "synth":
            from drv_stage_receipts import abc_script_graph
            script = _evidence(stage.get("abc_script") or {}, fails, "ABC script")
            scripts = abc_script_graph(
                script, stage.get("abc_sources", []),
                lambda ref: _evidence(ref or {}, fails, "ABC source"))
            buffers = re.findall(
                rf"(?:^|[;\n])\s*buffer\s+-N\s+({_NUM})"
                rf"(?:\s+-S\s+{_NUM})?\s*(?=;|\n|$)", "\n".join(scripts))
            if not stage.get("synth_abc_buffering") or not buffers:
                fails.append("synth: fanout buffering absent")
            elif any(float(value) != applied.get("fanout") for value in buffers):
                fails.append("synth: applied fanout differs from ABC buffer -N")
        else:
            snapshot = _evidence(stage.get("sdc_snapshot") or {}, fails,
                                 name + " pre-command SDC")
            for field, command in (("fanout", "set_max_fanout"),
                                   ("slew_ns", "set_max_transition"),
                                   ("cap_pf", "set_max_capacitance")):
                values = _sdc_values(snapshot, command, include_ports=False)
                if not values or any(value != applied.get(field) for value in values):
                    fails.append(f"{name}: {command} snapshot != applied value")
            if not _positive_number(stage.get("fanout_check_limit")):
                fails.append(f"{name}: sta::max_fanout_check_limit absent")
            elif stage["fanout_check_limit"] != applied.get("fanout"):
                fails.append(f"{name}: top-cell fanout check limit != applied value")
            if name == "cts" and not stage.get("cts_parameters"):
                fails.append("cts: clock_tree_synthesis parameters absent")
            if name == "cts" and not isinstance(stage.get("clock_driver_fanout"), list):
                fails.append("cts: propagated clock-driver fanout list absent")
        if name == "synth" and stage.get("ideal_clock_excluded") is not True:
            fails.append("synth: post-synth DRV report did not exclude ideal clock")
        for field in ("fanout", "slew_ns", "cap_pf"):
            if name == "synth" and field != "fanout":
                continue  # ABC has no slew/cap parameter.
            value = applied.get(field)
            if not _positive_number(value):
                fails.append(f"{name}: applied {field} absent")
            elif name == "signoff_sta" and value != declared.get(field):
                fails.append(f"sign-off SDC {field} != declared value")
            elif name != "signoff_sta" and value > declared.get(field, 0):
                broad_stage = True
    pins = bundle.get("pins") or {}
    seen: dict[str, set[tuple]] = {k: set() for k in KINDS}
    rows_by_kind: dict[str, list[dict]] = {k: [] for k in KINDS}
    scene_names = set()
    spef_by_pvt: dict[str, dict[str, str]] = {}
    for scene in bundle.get("scenes") or []:
        name, mode = scene.get("name"), scene.get("mode")
        scene_pins = scene.get("pins") or pins
        if not name or name in scene_names or name not in required_scenes:
            missing.append(f"scene identity missing, repeated or unexpected: {name}")
            continue
        scene_names.add(name)
        from drv_signoff_census import _core_only_kinds
        core_cells = set((libs.get(scene.get("liberty")) or {}).get(
            "limits", {}).get("cells", {}))
        scoped_declared = dict(declared)
        scoped_declared["core_scoped_slew"] = "max_slew" in _core_only_kinds(
            sdc_text, core_cells, ignore_port_limits=True)
        scoped_declared["port_slew_limits"] = {}
        if scoped_declared["core_scoped_slew"]:
            for pin, meta in scene_pins.items():
                if not isinstance(meta, dict) or meta.get("cell_class") != "port":
                    continue
                port_limits = _sdc_values(sdc_text, "set_max_transition", only_port=pin)
                if port_limits:
                    scoped_declared["port_slew_limits"][pin] = min(port_limits)
        if not scene.get("fresh_process") or not scene.get("postroute"):
            missing.append(f"{name}: fresh post-route STA process not proven")
        if scene.get("unannotated_nets") != 0:
            missing.append(f"{name}: parasitic annotation incomplete")
        ann = _evidence(scene.get("parasitic_annotation_report") or {}, missing,
                        name + " parasitic annotation")
        counts_ann = re.findall(
            r"Found\s+(\d+)\s+(?:partially\s+)?unannotated\s+(?:drivers|nets)", ann)
        if not counts_ann:
            missing.append(f"{name}: unannotated parasitic census absent")
        if any(int(count) for count in counts_ann) and not scene.get("annotation_census"):
            missing.append(f"{name}: unannotated parasitic census lacks pin proof")
        if scene.get("propagated_clocks") is not True or not scene.get("clock_properties"):
            missing.append(f"{name}: propagated clock evidence absent")
        if not scene.get("excluded_pins_recorded"):
            missing.append(f"{name}: excluded pin population absent")
        excluded = scene.get("excluded_pins")
        if not isinstance(excluded, list) or any(
                not isinstance(p, dict) or not p.get("pin") or
                p.get("reason") not in ("constant", "disabled", "ideal",
                                        "lef_pg_no_liberty_arc", "lef_physical_no_liberty_arc",
                                        "no_applicable_limit",
                                        "unconnected_no_net",
                                        "unproven") or
                ("excluded_kinds" in p and
                 (not isinstance(p["excluded_kinds"], list) or
                  any(kind not in KINDS for kind in p["excluded_kinds"]))) or
                any(not isinstance(p.get(axis), (int, float)) for axis in
                    ("fanout", "cap_pf", "slew_rise_ns", "slew_fall_ns"))
                for p in (excluded or [])):
            missing.append(f"{name}: excluded pin values incomplete")
        excluded_text = _evidence(scene.get("excluded_pins_report") or {},
                                  missing, name + " excluded pin report")
        try:
            if json.loads(excluded_text) != excluded:
                missing.append(f"{name}: excluded pins differ from raw tool report")
        except (ValueError, TypeError):
            missing.append(f"{name}: excluded pin report unreadable")
        for item in excluded or []:
            if not isinstance(item, dict) or not item.get("pin"):
                continue
            if item.get("reason") in ("lef_pg_no_liberty_arc", "lef_physical_no_liberty_arc",
                                      "no_applicable_limit", "unconnected_no_net"):
                continue
            if item.get("reason") == "unproven":
                missing.append(f"{name}: omitted pin {item['pin']} has no exclusion proof")
                continue
            for kind, axis, direction in (
                    ("max_fanout", "fanout", "none"),
                    ("max_capacitance", "cap_pf", "none"),
                    ("max_slew", "slew_rise_ns", "rise"),
                    ("max_slew", "slew_fall_ns", "fall")):
                if kind not in item.get("excluded_kinds", KINDS):
                    continue
                measured = item.get(axis)
                if not isinstance(measured, (int, float)):
                    continue
                row = {"pin": item["pin"], "scene": name, "mode": mode,
                       "direction": direction, "measured": measured,
                       "excluded_reason": item.get("reason")}
                if not _annotate_limits(row, kind, scene, libs, scene_pins,
                                        scoped_declared, missing):
                    continue
                row["limit"] = row["effective_limit"]
                row["slack"] = row["effective_limit"] - measured
                row["violated"] = measured > row["effective_limit"]
                if row["violated"]:
                    rows_by_kind[kind].append(row)
                    if item.get("reason") != "constant":
                        fails.append(f"{name}: excluded {item.get('reason')} pin "
                                     f"{item['pin']} violates {kind}")
        for field in ("spef", "clock_properties", "all_limits_report", "positive_control_report"):
            if isinstance(scene.get(field), dict):
                _evidence(scene[field], missing, name + " " + field)
            else:
                missing.append(f"{name}: {field} absent")
        if scene.get("rc_corner") not in (frozen.get("rc_corners") or []):
            missing.append(f"{name}: RC corner not frozen")
        pvt_name, _, name_rc = name.rpartition("_")
        if not pvt_name or name_rc != scene.get("rc_corner"):
            missing.append(f"{name}: scene RC corner differs from declared RC corner")
        spef_by_pvt.setdefault(pvt_name, {})[str(scene.get("rc_corner"))] = (
            (scene.get("spef") or {}).get("sha256", ""))
        if scene.get("spef_layout_sha256") != (identity.get("artifacts") or {}).get("def", {}).get("sha256"):
            missing.append(f"{name}: SPEF not bound to routed DEF identity")
        extraction_text = _evidence(scene.get("spef_extraction_receipt") or {},
                                    missing, name + " SPEF extraction receipt")
        try:
            extraction = json.loads(extraction_text)
            extraction_command = extraction.get("extraction_command") or {}
            _evidence(extraction_command, missing,
                      f"{name} SPEF extraction command")
            if (extraction.get("routed_def_sha256") !=
                    (identity.get("artifacts") or {}).get("def", {}).get("sha256")
                    or extraction.get("spef_sha256") !=
                    (scene.get("spef") or {}).get("sha256") or
                    extraction.get("rc_corner") != scene.get("rc_corner") or
                    extraction.get("extraction_command_sha256") !=
                    extraction_command.get("sha256")):
                missing.append(f"{name}: SPEF extraction input/output hashes differ")
        except (TypeError, ValueError):
            missing.append(f"{name}: SPEF extraction provenance unreadable")
        if scene.get("liberty") not in libs:
            missing.append(f"{name}: linked Liberty identity absent")
        linked = {item.get("name"): item.get("sha256")
                  for item in scene.get("linked_liberties") or []
                  if isinstance(item, dict)}
        expected_links = (frozen.get("scene_liberties") or {}).get(name)
        if (not isinstance(expected_links, list) or not expected_links or
                linked != {key: libs[key]["identity"]["sha256"]
                           for key in expected_links if key in libs} or
                set(linked) != set(expected_links)):
            missing.append(f"{name}: process did not link its frozen full Liberty set")
        expected_reads = ([
            ("read_liberty", str(Path(item["path"]).resolve()))
            for item in scene.get("linked_liberties") or []
            if isinstance(item, dict) and item.get("path")]
            + [("read_verilog", str(Path((identity.get("artifacts") or {}).get(
                "sta_netlist", {}).get("path") or "").resolve())),
               ("read_sdc", str(Path(sdc.get("path") or "").resolve())),
               ("read_spef", str(Path((scene.get("spef") or {}).get("path") or "").resolve()))])
        scripts = scene.get("tool_scripts") or []
        if not isinstance(scripts, list) or len(scripts) != 2:
            missing.append(f"{name}: fresh STA tool scripts absent")
        else:
            for index, script in enumerate(scripts):
                body = _evidence(script, missing, f"{name} STA tool script {index}")
                if (_script_reads(body) != expected_reads or
                        _COMMAND not in body or
                        re.search(r"(?m)^\s*(?:source|eval|exec)\b", body)):
                    missing.append(f"{name}: STA tool script reads differ from frozen inputs")
                if index == 1 and not re.search(
                        r"(?m)^set_max_fanout\s+1\s+\[current_design\]\s*$", body):
                    missing.append(f"{name}: positive control fanout injection absent")
        expected_pvt = (frozen.get("pvt") or {}).get(name)
        actual_pvt = (libs.get(scene.get("liberty")) or {}).get("header")
        if (not isinstance(expected_pvt, dict) or
                any((actual_pvt or {}).get(k) is None or
                    (actual_pvt or {}).get(k) != expected_pvt.get(k)
                    for k in ("nom_process", "nom_voltage", "nom_temperature"))):
            missing.append(f"{name}: Liberty PVT header mismatch")
        for linked_item in scene.get("linked_liberties") or []:
            if not isinstance(linked_item, dict):
                missing.append(f"{name}: linked Liberty record malformed")
                continue
        # The core library defines this scene's PVT. IO and supply libraries
        # have their own nominal headers; some passive supply models use the
        # same header in every corner. Their identities are checked against
        # the frozen full per-scene library set above and the frozen input
        # hashes, rather than against another library's nominal header.
        if scene.get("command") != _COMMAND:
            missing.append(f"{name}: required OpenSTA report_check_types command absent")
        report = _evidence(scene.get("report") or {}, missing, name + " violator report")
        parsed = parse_check_types(report, scene=name, mode=mode, violators_only=True)
        counter_text = _evidence(scene.get("counter_report") or {}, missing,
                                 name + " violation counters")
        tool_counters = dict((m.group(1), int(m.group(2))) for m in re.finditer(
            r"(?m)^DRV_COUNTER\s+(max_slew|max_capacitance|max_fanout)\s+(\d+)\s*$",
            counter_text))
        all_text = _evidence(scene.get("all_limits_report") or {}, missing,
                             name + " all limits")
        all_rows = parse_check_types(all_text, scene=name, mode=mode,
                                     violators_only=False)
        annotation_census = scene.get("annotation_census")
        if annotation_census is not None:
            raw_census = _evidence(scene.get("annotation_census_report") or {},
                                   missing, name + " annotation census")
            try:
                if json.loads(raw_census) != annotation_census:
                    missing.append(f"{name}: annotation census differs from recorded file")
                from drv_signoff_annotation import derive as derive_annotation
                scene_folder = Path(scene["parasitic_annotation_report"]["path"]).parent
                lefs = scene.get("linked_lefs") or []
                for item in lefs:
                    _evidence(item, missing, name + " linked LEF")
                derived = derive_annotation(
                    scene_folder, scene_pins,
                    scene.get("linked_liberties") or [], lefs,
                    Path(identity["artifacts"]["def"]["path"]),
                    Path(scene["spef"]["path"]))
                if derived != annotation_census or len(derived["unresolved"]) != scene.get("unannotated_nets"):
                    missing.append(f"{name}: independent annotation census differs")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                missing.append(f"{name}: annotation proof incomplete: {exc}")
        if project is not None:
            census_refs = ("pin_census_report", "net_census_report",
                           "disabled_edges_report")
            census_paths = []
            for field in census_refs:
                item = scene.get(field) or {}
                _evidence(item, missing, name + " " + field)
                census_paths.append(Path(str(item.get("path") or "")))
            if (all(path.is_file() for path in census_paths) and
                    len({path.parent for path in census_paths}) == 1):
                try:
                    from drv_signoff_census import derive as derive_census
                    census = derive_census(census_paths[0].parent,
                                           scene.get("linked_liberties") or [], all_rows,
                                           scene.get("linked_lefs"), allow_unproven=True,
                                           signoff_sdc=Path(sdc["path"]),
                                           core_liberty=scene.get("liberty"))
                    if (scene_pins != census["pins"] or
                            scene.get("excluded_pins") != census["excluded"] or
                            scene.get("clock_network_pins") != census["clock_network_pins"] or
                            scene.get("driver_pin_census") != census["driver_pins"] or
                            (scene.get("unproven_omitted_pins") or []) != census["unproven"] or
                            scene.get("population") != census["population"]):
                        missing.append(f"{name}: independent OpenSTA pin census differs from bundle")
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    missing.append(f"{name}: independent OpenSTA pin census incomplete: {exc}")
            else:
                missing.append(f"{name}: independent OpenSTA pin census absent")
        control_text = _evidence(scene.get("positive_control_report") or {},
                                 missing, name + " positive control")
        control_rows = parse_check_types(control_text, scene=name, mode=mode,
                                         violators_only=True)
        control_all_text = _evidence(scene.get("positive_control_all_limits_report") or {},
                                    missing, name + " positive control all limits")
        control_all_rows = parse_check_types(control_all_text, scene=name, mode=mode,
                                             violators_only=False)
        if not scene.get("positive_control_fresh_process"):
            missing.append(f"{name}: positive control did not use fresh process")
        controls = scene.get("positive_control_limits") or {}
        if controls.get("max_fanout") != 1 or any(
                not _positive_number(controls.get(kind)) or
                controls[kind] >= declared.get(field, 0)
                for kind, field in (("max_slew", "slew_ns"),
                                    ("max_capacitance", "cap_pf"))):
            missing.append(f"{name}: positive control thresholds not tightened")
        for kind in KINDS:
            counter = (scene.get("counters") or {}).get(kind)
            if not isinstance(counter, int) or isinstance(counter, bool) or counter < 0:
                missing.append(f"{name}: {kind} counter absent")
                continue
            if tool_counters.get(kind) != counter:
                missing.append(f"{name}: {kind} counter differs from raw tool output")
            keys = {_key(kind, row) for row in parsed[kind]}
            if len(keys) != counter or len(keys) != len(parsed[kind]):
                missing.append(f"{name}: {kind} report names != counter")
            all_bad = {_key(kind, row) for row in all_rows[kind]
                       if row.get("violated")}
            if all_bad != keys:
                missing.append(f"{name}: {kind} all-limits vs violator names differ")
            population = (scene.get("population") or {}).get(kind)
            if (not isinstance(population, int) or population < 1 or
                    len(all_rows[kind]) < population or
                    (scene.get("all_limits_max_count") or 0) < population):
                missing.append(f"{name}: {kind} all-limits population incomplete")
            if any("limit" not in row for row in all_rows[kind]):
                missing.append(f"{name}: {kind} row without limit")
            control_limit = controls.get(kind)
            # Global control limits also constrain IO pins which had no limit
            # in the measurement. Use the control process's own full population.
            expected_control_keys = {
                _key(kind, row) for row in control_all_rows[kind]
                if _positive_number(control_limit) and
                isinstance(row.get("measured"), (int, float)) and
                row["measured"] > control_limit}
            control_keys = {_key(kind, row) for row in control_rows[kind]}
            actual_control = (scene.get("positive_control_counters") or {}).get(kind)
            control_all_keys = {_key(kind, row) for row in control_all_rows[kind]}
            if (not expected_control_keys or
                    control_keys != expected_control_keys or
                    len(control_rows[kind]) != len(control_keys) or
                    len(control_all_rows[kind]) != len(control_all_keys) or
                    actual_control != len(expected_control_keys)):
                missing.append(f"{name}: {kind} positive control did not detect "
                               "the measured eligible population")
            # Tightening limits cannot remove an eligible measurement pin or
            # change its physical fanout/capacitance. Keep that cross-check.
            original_eligible = {_key(kind, row) for row in all_rows[kind]
                                 if _positive_number(control_limit) and
                                 isinstance(row.get("measured"), (int, float)) and
                                 row["measured"] > control_limit}
            if not original_eligible <= expected_control_keys:
                missing.append(f"{name}: {kind} positive control lost measurement pins")
            if kind != "max_slew":
                original_values = {_key(kind, row): row.get("measured")
                                   for row in all_rows[kind]}
                if any(key in original_values and
                       (not isinstance(original_values[key], (int, float)) or
                        not isinstance(row.get("measured"), (int, float)) or
                        abs(row["measured"] - original_values[key]) > 1e-6)
                       for row in control_all_rows[kind]
                       for key in [_key(kind, row)]):
                    missing.append(f"{name}: {kind} positive control changed measurement")
            independent_bad = set()
            for row in all_rows[kind]:
                key = _key(kind, row)
                if key in seen[kind] and kind != "max_fanout":
                    missing.append(f"duplicate {kind} key {key}")
                seen[kind].add(key)
                if any(field not in row for field in ("limit", "measured", "slack")):
                    missing.append(f"{name}: incomplete {kind} row {row['pin']}")
                    continue
                if kind == "max_slew" and row["direction"] not in ("rise", "fall"):
                    missing.append(f"{name}: slew rise/fall absent for {row['pin']}")
                if not _annotate_limits(row, kind, scene, libs, scene_pins,
                                        scoped_declared, missing):
                    continue
                effective = row["effective_limit"]
                tolerance = max(1e-6, abs(effective) * 1e-6)
                # R-0929-CAP-MARGIN-SCOPE: the std-cell margin is design-wide,
                # so every IO-cell pin carries it as its tool limit.  That is
                # the known inheritance, not an instrument disagreement; only a
                # row the tool FLAGGED within its IO Liberty limit is a
                # disclosure (merge note 4: tagging every IO pin broke the
                # per-scene set check once one IO pin exceeded and one did not).
                in_margin_scope = io_margin_scope(
                    kind, row.get("cell_class"), row.get("explicit_limit"),
                    row["limit"], declared.get("cap_pf"))
                io_disclosure = io_margin_disclosure(
                    kind, row.get("cell_class"), row.get("explicit_limit"),
                    row["limit"], row["measured"], effective, declared.get("cap_pf"))
                if io_disclosure:
                    row["failed_tier"] = IO_STD_CELL_MARGIN_DISCLOSURE
                    io_margin_disclosures.append(row)
                elif row["limit"] > effective + tolerance:
                    fails.append(f"{name}: {kind} {row['pin']} tool limit "
                                 f"{row['limit']} exceeds frozen effective limit {effective}")
                elif row["limit"] < effective - tolerance and not in_margin_scope:
                    missing.append(f"{name}: {kind} {row['pin']} tool limit "
                                   "differs from frozen effective limit")
                independently_violated = row["measured"] > effective + tolerance
                if not io_disclosure and independently_violated != bool(row.get("violated")):
                    missing.append(f"{name}: {kind} {row['pin']} tool/slack vs "
                                   "frozen limit disagree")
                if independently_violated:
                    independent_bad.add(key)
                    rows_by_kind[kind].append(row)
            if independent_bad != keys and not (
                    kind == "max_capacitance" and
                    keys - independent_bad == {
                        _key(kind, row) for row in io_margin_disclosures
                        if row["scene"] == name}):
                missing.append(f"{name}: {kind} independent violators differ "
                               "from tool report")
    if scene_names != set(required_scenes):
        missing.append("required PVT/RC scenes absent")
    for pvt_name, rc_sha in spef_by_pvt.items():
        if len(rc_sha) > 1 and len(set(rc_sha.values())) != len(rc_sha):
            missing.append(f"{pvt_name}: RC corner SPEFs have identical hashes")
    # Fanout is invariant to RC; repeated corner rows describe one driver/mode.
    dedup = {}
    for row in rows_by_kind["max_fanout"]:
        key = _key("max_fanout", row)
        if key in dedup and row["measured"] != dedup[key]["measured"]:
            missing.append(f"fanout differs across scenes for {key}")
        if key not in dedup or row.get("limit", float("inf")) < dedup[key].get("limit", float("inf")):
            dedup[key] = row
    rows_by_kind["max_fanout"] = list(dedup.values())
    for kind, rows in rows_by_kind.items():
        for row in rows:
            if (kind in ("max_slew", "max_capacitance") and
                    row.get("cell_class") == "port" and row.get("port_to_pad") is True):
                # R-0928-DRV-IC: the port-to-PAD net is off-chip. Its slew is
                # the pad pin's own row (judged by IO Liberty T1) and its load
                # is the pad's PAD-pin capacitance plus the set_load; the
                # std-cell margin never applies. Listed, never a finding.
                row["failed_tier"] = OFFCHIP_PORT_TO_PAD_NET
                offchip_port_rows.append(row)
                continue
            pin_limit = row["liberty_limit"]
            explicit = row["explicit_limit"]
            effective = row["effective_limit"]
            if (kind == "max_capacitance" and row.get("cell_class") == "IO" and
                    explicit is None and _positive_number(pin_limit) and
                    row["measured"] <= pin_limit):
                row["failed_tier"] = "IO_STD_CELL_MARGIN_DISCLOSURE"
                io_margin_disclosures.append(row)
                continue
            # OpenSTA's displayed precision can differ by one last digit;
            # the tool's negative slack and independent source tier must agree.
            if pin_limit is not None and row["measured"] > pin_limit:
                tier, waivable = ("T1_LIBERTY_FANOUT" if kind == "max_fanout"
                                  else "T1_LIBERTY"), False
            elif kind == "max_slew" and row["net_class"] == "clock":
                tier, waivable = "T2_CLOCK_SLEW", False
            elif kind == "max_fanout":
                loads = row.get("loads") or {}
                cls = row["net_class"]
                eligible = (cls == "clock" or cls == "constant" or
                            (loads.get("logical", 0) <= effective and
                             loads.get("antenna_diode", 0) > 0 and
                             loads.get("logical", 0) + loads.get("antenna_diode", 0) >= row["measured"]))
                cap = declared.get("default_fanout_ceiling")
                tier, waivable = "DECLARED_FANOUT", eligible and (
                    _positive_number(cap) and row["measured"] <= cap or
                    _positive_number(declared.get("owner_class_fanout_ceiling")) and
                    row["measured"] <= declared["owner_class_fanout_ceiling"])
                if cls == "data" and not eligible:
                    tier = "DATA_NET_RESIDUE"
            elif kind == "max_capacitance" and row.get("cell_class") == "IO" and explicit is None:
                tier, waivable = "IO_MARGIN_DISCLOSURE", False
            else:
                tier, waivable = "T3_MARGIN", True
            row["failed_tier"] = tier
            row["waivable"] = bool(waivable)
            findings.append(row)
    flow_defects = []
    if broad_stage and findings:
        fails.append("post-route violation with broader implementation constraint")
    elif broad_stage:
        flow_defects.append("implementation constraint broader than declared; open flow-defect issue")
    ledger = [r.get("waiver") for r in owner_records
              if r.get("type") == "waiver" and isinstance(r.get("waiver"), dict)]
    for row in findings:
        if not row["waivable"] or (broad_stage and findings):
            fails.append(f"{row['failed_tier']}: {row['pin']} {row['scene']}")
            continue
        key = {"netlist_sha256": identity.get("sta_netlist"),
               "tree_sha": tree_sha, "run_id": run_id,
               "driver_pin": row.get("driver_pin", row["pin"]),
               "driver_cell": row.get("driver_cell", row.get("cell")),
               "measured": row["measured"], "limit": row["effective_limit"],
               "scene_or_mode": row["mode"] if row["kind"] == "max_fanout" else row["scene"],
               "sdc_sha256": sdc.get("sha256")}
        matches = [w for w in ledger if all(w.get(k) == v for k, v in key.items())]
        valid = [w for w in matches if w.get("owner_quote") and
                 w.get("owner_timestamp") and
                 _positive_number(w.get("approved_value")) and
                 w["approved_value"] >= row["measured"] and
                 _waiver_support(w, row, bundle, missing, owner_records)]
        if valid:
            waived.append({"key": key, "owner_quote": valid[0]["owner_quote"],
                           "owner_timestamp": valid[0]["owner_timestamp"],
                           "below_baseline_quality": True})
        else:
            fails.append(f"{row['failed_tier']}: no valid signed owner waiver "
                         f"for {row['pin']} ({owner_status})")
    verdict = ("FAIL" if fails else "NOT_MEASURED" if missing else
               "WAIVED" if waived else "PASS")
    return {"schema_version": 1, "name": "DRV(tran/cap/fanout)",
            "verdict": verdict, "run_id": run_id, "tree_sha": tree_sha,
            "spec_version": identity.get("spec_version"),
            "counts": {k: len(v) for k, v in rows_by_kind.items()},
            "findings": findings, "waived": waived,
            "load_pin_slew_findings": [r for r in findings
                                       if r.get("load_pin")],
            "findings_by_net_class": {name: [r for r in findings
                                              if r.get("net_class") == name]
                                      for name in ("clock", "data", "IO", "constant")},
            "thresholds": {"values": declared,
                           "sources": frozen.get("sources"),
                           "liberties": frozen.get("liberties"),
                           "scope": frozen.get("scope"),
                           "scenes": required_scenes},
            "threshold_freeze": freeze_evidence,
            "stage_constraints": bundle.get("stages") or [],
            "capture_point": capture_point,
            "final_signoff_capture": capture_point == "post_stream",
            "identity_bound_later": deferred,
            "io_margin_disclosures": io_margin_disclosures,
            "offchip_port_rows": offchip_port_rows,
            "flow_defects": flow_defects,
            "failures": fails, "not_measured": missing,
            "out_of_scope": {k: "NOT_MEASURED" for k in
                             ("noise/SI", "signal EM", "cell EM", "max_length")}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path,
                        help="evidence JSON or project root containing reports/phase3/sta/drv_signoff_bundle.json")
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--capture-point", choices=("in_flow", "post_stream"),
                        help="the capture this gate judges; a bundle of another "
                             "kind is NOT_MEASURED (R-0929-DRV-IDENTITY)")
    args = parser.parse_args(argv)
    source = (args.bundle / "reports/phase3/sta/drv_signoff_bundle.json"
              if args.bundle.is_dir() else args.bundle)
    tool_arm = None
    if args.bundle.is_dir():
        # F15 -- STEP 23 ON THE TOOL. When step 23 runs `librelane` or `dual`
        # the route that was signed off is the one STAPostPNR timed. Bind that
        # arm first, exactly as the other step-23 gates do: a tool arm that
        # cannot be read REFUSES (rc 1) before anything is judged.
        import librelane_signoff as _ls
        from librelane_contract import Refusal
        try:
            arm = _ls.step23_tool_arm(args.bundle)
        except Refusal as exc:
            result = {"name": "DRV(tran/cap/fanout)", "verdict": "REFUSED",
                      "refusal": exc.code,
                      "reason": (f"step 23 runs on the tool and its sign-off "
                                 f"cannot be read: {exc}")}
            write_text(args.json, json.dumps(result, indent=2) + "\n")
            print(result["verdict"], result["name"])
            return 1
        if arm is not None:
            tool_arm = {"basis": _ls.tool_arm_basis(arm)}
            try:
                state = json.loads((Path(arm["folder"]) / "state_out.json").read_text())
                tool_arm["def"] = str(state["def"])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                tool_arm["def_error"] = str(exc)
    try:
        bundle = json.loads(source.read_text())
        result = judge(bundle, project=args.bundle if args.bundle.is_dir() else None)
        if args.capture_point and result.get("capture_point") != args.capture_point:
            result.setdefault("not_measured", []).append(
                f"gate judges the {args.capture_point} capture but the bundle is "
                f"{result.get('capture_point')}")
            result["verdict"] = ("FAIL" if result.get("failures") else "NOT_MEASURED")
        if not args.bundle.is_dir():
            result.setdefault("not_measured", []).append(
                "project context absent; threshold sources cannot be authenticated")
            result["verdict"] = ("FAIL" if result.get("failures") else
                                 "NOT_MEASURED")
        else:
            if not (args.bundle / "reports/phase3/sta/drv_capture_plan.json").is_file():
                result.setdefault("not_measured", []).append(
                    "fresh DRV capture plan absent")
            routed = def_identity(bundle, args.bundle / "phase3/stage3/pnr/routed.def")
            if routed == "absent":
                result.setdefault("not_measured", []).append(
                    "current routed DEF absent")
            elif routed == "differs":
                result.setdefault("not_measured", []).append(
                    "current routed DEF differs from judged layout identity")
            # Merge note (F15 x DRV stack): "the DEF STAPostPNR timed" binds
            # the step-23 (in-flow) capture only.  The FINAL capture binds the
            # shipped DEF/GDS through its post-stream derivation; step 32
            # repair or step 34 fill may change the DEF after step 23 timed it.
            if (tool_arm is not None and args.capture_point != "post_stream" and
                    def_identity(bundle, Path(tool_arm["def"]) if tool_arm.get("def")
                                 else None) is not None):
                # The DRV census is a fresh OpenSTA capture of a routed DEF; on
                # the tool arm it certifies step 23 only if that DEF is the one
                # STAPostPNR timed. STAPostPNR's own reports carry violator
                # COUNTS, not the per-(pin, scene) census the standard judges,
                # so they cannot stand in for the capture.
                result.setdefault("not_measured", []).append(
                    "step 23 runs on the tool: the DRV bundle's routed DEF is "
                    "not the DEF STAPostPNR timed "
                    f"({tool_arm.get('def') or tool_arm.get('def_error')})")
            result["verdict"] = ("FAIL" if result.get("failures") else
                                 "NOT_MEASURED" if result.get("not_measured") else
                                 result["verdict"])
    except Exception as exc:  # noqa: BLE001 - a crashed instrument has no verdict
        result = {"name": "DRV(tran/cap/fanout)", "verdict": "NOT_MEASURED",
                  "not_measured": [f"bundle unreadable: {exc}"]}
        if tool_arm is not None:
            result["not_measured"].append(
                "step 23 runs on the tool, and STAPostPNR's reports carry DRV "
                "violator counts, not the per-(pin, scene) census the DRV "
                "standard judges: a fresh capture of the DEF it timed is required")
    if tool_arm is not None:
        result["tool_arm"] = tool_arm
    if result["verdict"] == "NOT_MEASURED":
        result["reason_class"] = ("input_absent" if not source.is_file()
                                  else "partial_population")
    write_text(args.json, json.dumps(result, indent=2) + "\n")
    print(result["verdict"], result["name"])
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
