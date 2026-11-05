#!/usr/bin/env python3
"""D03 native technology selection. BLOCKING on native config/pin refusal.

LibreLane resolves the design's configuration and validates its selected files;
Ciel or the existing PDK revision reader identifies the installed revision. This identifies the technology in use,
not execution/signoff of every downstream tool, corner or physical deck.
"""
from __future__ import annotations

from importlib.metadata import version
import json
import os
from pathlib import Path

from declared_pdk_is_the_pdk_used_check import declared_distribution, PDKDeclarationError



class D03Refusal(ValueError):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def _installed_pin(pdk_root: Path, pdk: str, family: str) -> dict:
    """Consume the installed layout's actual revision authority, not its name.

    A Ciel installation still owes its Ciel pin; missing/deleted registration
    cannot fall back to metadata. Other native SDK installations use the
    existing PDK revision reader, which checks declared-source conflicts.
    """
    import ciel
    tree = pdk_root / pdk
    if not tree.is_dir():
        raise D03Refusal("D03_PDK_TREE_UNRESOLVED", str(tree))
    if pdk_root.parent.name == "versions":
        installed = ciel.Version.get_all_installed(str(pdk_root.parents[3]), family)
        pins = [v for v in installed
                if Path(v.get_dir(str(pdk_root.parents[3]))).resolve() == pdk_root]
        if len(pins) != 1:
            raise D03Refusal("D03_CIEL_PIN_UNRESOLVED", str(pdk_root))
        return {"family": family, "variant": pdk, "revision": pins[0].name,
                "root": str(pdk_root), "authority": "ciel_installed_pin"}
    import pdk_revision_resolve as revision
    node_info = tree / ".config/nodeinfo.json"
    if node_info.exists():
        try:
            node = json.loads(node_info.read_text())
            if not isinstance(node, dict) or node.get("node") != pdk:
                raise ValueError("nodeinfo does not identify the selected PDK variant")
        except (OSError, ValueError) as exc:
            raise D03Refusal("D03_PDK_PIN_AUTHORITY_INVALID", str(exc)) from exc
    record = revision.resolve_tree(revision.Fs(), str(tree))
    if record.get("resolved") is not True:
        raise D03Refusal("D03_INSTALLED_PDK_PIN_UNRESOLVED",
                         str(record.get("reason") or tree))
    return {"family": family, "variant": pdk, "root": str(pdk_root),
            "revision": record["revision"], "authority": "installed_pdk_revision"}


def _resolve(config_path: Path, pdk_root: Path, *, pdk: str, project: Path):
    import ciel
    from librelane.flows import Flow

    # Constructing a native Flow resolves/validates configuration only. No
    # physical or synthesis step is launched, and no existing run is resumed.
    meta = json.loads(config_path.read_text()).get("meta", {})
    name = meta.get("flow", "Classic")
    if not isinstance(name, str) or Flow.factory.get(name) is None:
        raise D03Refusal("D03_NATIVE_FLOW_UNRESOLVED", str(name))
    target = Flow.factory.get(name)
    if meta.get("substituting_steps"):
        target = target.Substitute(meta["substituting_steps"])
    raw_pdk = json.loads(config_path.read_text()).get("PDK")
    if raw_pdk is not None and raw_pdk != pdk:
        raise D03Refusal("D03_PDK_DECLARATION_CONFLICT", "config PDK differs from case declaration")
    flow = target(str(config_path), pdk=pdk, pdk_root=str(pdk_root),
                  design_dir=str(project))
    selected = flow.config
    pdk = selected["PDK"]
    family = next((f for f in ciel.Family.by_name.values() if pdk in f.variants), None)
    if family is None:
        raise D03Refusal("D03_CIEL_FAMILY_UNRESOLVED", pdk)
    return selected, _installed_pin(pdk_root, pdk, family.name)


def execute(project: Path, directory: Path) -> dict:
    """Resolve native technology before RTL; refusal is FAIL, missing input is NOT_MEASURED."""
    project, directory = Path(project).resolve(), Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    started = False
    reports, metrics = [], {}
    import time
    before = time.perf_counter()
    try:
        declared_pdk, _ = declared_distribution(project)
        import librelane_contract as native
        config_path = project / "phase3/librelane/config.json"
        if not config_path.exists():
            docs = project / "phase1/generated_docs"
            design = (native._ldoc(docs, "L9_INTEGRATION_SPEC.json").get("top_module")
                      or native._ldoc(docs, "L1_DATASHEET.json").get("ic_name"))
            settings, _ = native._declared_flow_settings(
                native._ldoc(docs, "L19_CONSTRAINTS_PDK.json"), declared_pdk)
            config_path = directory / "technology.json"
            config_path.write_text(json.dumps({"meta": {"version": 2, "flow": "Classic"},
                "DESIGN_NAME": design, "PDK": declared_pdk,
                "VERILOG_FILES": [], **settings}, default=str) + "\n")
        root = os.environ.get("VIBEIC_LIBRELANE_PDK_ROOT") or os.environ.get("PDK_ROOT")
        if not root:
            return {"ran": False, "detail": "No installed PDK_ROOT for native technology resolution."}
        started = True
        selected, pin = _resolve(config_path, Path(root).resolve(strict=True),
                                 pdk=declared_pdk, project=project)
        if selected["PDK"] != declared_pdk:
            raise D03Refusal("D03_PDK_DECLARATION_CONFLICT", "resolved PDK differs from design declaration")
        resolved = directory / "resolved.json"
        resolved.write_text(selected.dumps())
        reports = [str(config_path), str(resolved)]
        metrics = {"pdk": selected["PDK"], "standard_cell_library": selected["STD_CELL_LIBRARY"],
                   "default_corner": selected["DEFAULT_CORNER"], "installed_pdk_revision": pin["revision"],
                   "librelane_version": version("librelane"), "ciel_version": version("ciel")}
        return {"ran": True, "exit_code": 0, "metrics": metrics, "reports": reports,
                "tool_seconds": time.perf_counter() - before,
                "detail": "Native LibreLane configuration and installed PDK revision resolved; downstream tools have not run."}
    except (D03Refusal, PDKDeclarationError) as exc:
        failed = not isinstance(exc, PDKDeclarationError) or exc.code != "PDK_UNDECLARED"
        return {"ran": failed or started, "exit_code": 1 if failed else None,
                "metrics": metrics, "reports": reports, "tool_seconds": time.perf_counter() - before,
                "detail": str(exc)}
    except (ImportError, FileNotFoundError) as exc:
        return {"ran": started, "exit_code": 1 if started else None, "detail": str(exc),
                "tool_seconds": time.perf_counter() - before}
    except Exception as exc:
        return {"ran": started, "exit_code": 1 if started else None, "detail": str(exc),
                "tool_seconds": time.perf_counter() - before}
