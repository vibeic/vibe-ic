#!/usr/bin/env python3
"""Run the official wafer.space flow with LibreLane's typed initial state.

The pinned operator CLI passes its --with-initial-state filename directly to
Flow.start. LibreLane requires a State object. This adapter only loads that
object and calls the operator's unchanged main; all operator steps run.
An engineering slot is a technical target, not a purchased reservation or ID.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json  # noqa: E402


def _file(path):
    path = Path(path).resolve()
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return {"path": str(path), "sha256": h.hexdigest(), "bytes": path.stat().st_size}


def read_signoff_evidence(project, release_record):
    """Read actual selected-engine counts, bound to the delivered GDS.

    The official WriteLayout can change timestamps without changing geometry.
    Compare each selected measurement's actual input with the delivered file.
    A strict KLayout LayoutDiff handles serialization order without ignoring
    text or properties.
    This is a read-only consumer, not a new PV run or an LVS substitute.
    """
    from die_finishing_gen import read_admitted_release
    from gds_canonical_digest import semantic_layout_equivalence

    release = read_admitted_release(Path(project), Path(release_record))
    record = json.loads(release["report"].read_text())
    official_ref = record["basis"]["files"]["official_precheck"]
    official = json.loads(Path(official_ref["path"]).read_text())
    final = _file(release["gds"])
    finite = {}
    def keep(path, role):
        ref = _file(path)
        key = ref["path"]
        if key not in finite:
            finite[key] = dict(ref, roles=[])
        if role not in finite[key]["roles"]:
            finite[key]["roles"].append(role)
        return ref
    keep(release["report"], "assembly_record")
    keep(Path(official_ref["path"]), "official_precheck_record")
    finite[final["path"]] = dict(final, roles=["delivered_gds"])
    views = {}
    def equivalent(path):
        path = str(Path(path).resolve())
        if path not in views:
            source = keep(path, "official_input_gds")
            try:
                compared = semantic_layout_equivalence(Path(path), release["gds"])
                views[path] = {"input": source, "output": final,
                               **{key: compared[key] for key in
                                  ("method", "flags", "tolerance", "tool_version", "equivalent")}}
            except (ImportError, RuntimeError) as exc:
                raise ValueError(f"strict layout comparison unavailable: {exc}") from exc
        return views[path]
    steps = {}
    for step_id, item in zip(official["expected_steps"], official["steps"]):
        folder = Path(item["folder"])
        inp_path, out_path = folder / "state_in.json", folder / "state_out.json"
        keep(inp_path, "official_state_in")
        keep(out_path, "official_state_out")
        inp, state = json.loads(inp_path.read_text()), json.loads(out_path.read_text())
        steps[step_id] = (folder, inp, state)
    rows = {}
    for kind, step_id, metric in [
            ("density", "KLayout.Density", "klayout__density_error__count"),
            ("antenna", "KLayout.Antenna", "klayout__antenna_error__count"),
            ("drc", "KLayout.DRC", "klayout__drc_error__count")]:
        row = {"verdict": "NOT_MEASURED", "value": "NOT_MEASURED",
               "selected_engine": "KLayout", "gds_sha256": final["sha256"]}
        try:
            folder, inp, state = steps[step_id]
            cfg_path = folder / "config.json"
            config = json.loads(cfg_path.read_text())
            if config.get("meta", {}).get("step") != step_id:
                raise ValueError("native step configuration belongs to another engine")
            report = folder / "reports" / (kind + ".klayout.json")
            measured = json.loads(report.read_text())
            count = state.get("metrics", {}).get(metric)
            if (isinstance(count, bool) or not isinstance(count, int) or count < 0
                    or isinstance(measured.get("total"), bool)
                    or not isinstance(measured.get("total"), int)
                    or measured.get("total") != count):
                raise ValueError("native count is missing or differs from its raw report")
            evidence = keep(report, kind + "_raw_report")
            state_ref = keep(folder / "state_out.json", kind + "_state")
            keep(cfg_path, kind + "_config")
            keep(folder / "COMMANDS", kind + "_native_command")
            bridge = equivalent(inp["gds"])
            row.update(value=count, source=evidence["path"], source_sha256=evidence["sha256"],
                       record=state_ref["path"], record_sha256=state_ref["sha256"],
                       operator_report=official_ref["path"], equivalence=bridge,
                       source_verdict="PASS" if count == 0 else "FAIL")
            if not bridge["equivalent"]:
                raise ValueError("the selected native measurement input differs from the delivered GDS")
            row["verdict"] = "PASS" if count == 0 else "FAIL"
        except (KeyError, OSError, ValueError, TypeError) as exc:
            row["reason"] = str(exc)
        rows[kind] = row
    disclosures = []
    if "Magic.DRC" in steps:
        folder, inp, state = steps["Magic.DRC"]
        config = json.loads((folder / "config.json").read_text())
        disclosures.append({"engine": "Magic", "value": state.get("metrics", {}).get("magic__drc_error__count", "NOT_MEASURED"),
                            "error_on_magic_drc": config.get("ERROR_ON_MAGIC_DRC"),
                            "state": keep(folder / "state_out.json", "magic_disclosure"),
                            "equivalence": equivalent(inp["gds"]),
                            "scope": "operator Magic policy disclosure; selected Default DRC is KLayout; not LVS"})
        keep(folder / "config.json", "magic_disclosure_config")
    verdicts = [row["verdict"] for row in rows.values()]
    verdict = "FAIL" if "FAIL" in verdicts else "PASS" if all(v == "PASS" for v in verdicts) else "NOT_MEASURED"
    return {"verdict": verdict, "gds_sha256": final["sha256"], "rows": rows,
            "input_view_equivalence": list(views.values()), "disclosures": disclosures,
            "finite_files": list(finite.values()), "scope": "selected KLayout DRC/antenna/density; LVS is independent"}


def run(args):
    from librelane.state import State

    official = Path(args.official_source).resolve() / "precheck.py"
    spec = importlib.util.spec_from_file_location("wafer_space_official_precheck", official)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    initial = State.load(json.loads(Path(args.with_initial_state).read_text()))
    input_record = _file(args.input)
    initial_record = _file(args.with_initial_state)
    official_record = _file(official)
    rc = 0
    try:
        module.main(args.input, args.output, args.top, args.dir,
                    args.id if args.id is not None else "FFFFFFFF", args.cob,
                    args.slot, str(args.threads), args.workers, args.run_tag,
                    False, None, None, None, initial)
    except SystemExit as exc:
        rc = int(exc.code or 0)
    except Exception:
        traceback.print_exc()
        rc = 1
    run_dir = Path(args.dir).resolve() / "runs" / args.run_tag
    steps = []
    for folder in sorted(run_dir.iterdir()) if run_dir.is_dir() else []:
        if folder.is_dir() and folder.name[:2].isdigit():
            state = folder / "state_out.json"
            steps.append({"folder": str(folder),
                          "state_out": _file(state) if state.is_file() else None})
    output = _file(args.output) if Path(args.output).is_file() else None
    expected = [step.id for step in module.PrecheckFlow.Steps]
    complete = (rc == 0 and len(steps) == len(expected)
                and all(step["state_out"] for step in steps) and output is not None)
    record = {
        "producer": "wafer_space_precheck",
        "scope": "official provider precheck; not LVS, purchase or platform acceptance",
        "returncode": rc,
        "verdict": "PASS" if complete else "FAIL",
        "input": input_record,
        "initial_state": initial_record,
        "official_entry": official_record,
        "slot": args.slot, "packaging": "cob" if args.cob else "bare_die",
        "assigned_id": args.id,
        "uses_official_unassigned_test_default": args.id is None,
        "all_steps_requested": True,
        "expected_steps": expected, "steps": steps,
        "output": output,
    }
    write_json(Path(args.record), record)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("official-source", "input", "output", "top", "slot", "dir",
                 "run-tag", "with-initial-state", "record"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--id")
    parser.add_argument("--cob", action="store_true")
    result = run(parser.parse_args(argv))
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "PASS" else (result["returncode"] or 1)


if __name__ == "__main__":
    sys.exit(main())
