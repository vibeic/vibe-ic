from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import vibeic_temp as tempfile

from librelane.common import Path as NativePath, get_script_dir
from librelane.state import DesignFormat, State
from librelane.steps import Step, StepError, StepException
from librelane.steps.klayout import Density
from librelane.steps.magic import MagicStep

from metal_fill_config_gen import build_metal_fill_config


METRIC = "klayout__density_error__count"
MAGIC_METRIC = "magic__density_error__count"


def magic_helpers(config, *names):
    root, pdk = config.get("PDK_ROOT"), config.get("PDK")
    helpers = Path(str(root)) / str(pdk) / "libs.tech/magic"
    if not root or not pdk or not all((helpers / name).is_file() for name in names):
        raise StepException("NOT_MEASURED: no configured native density runset or Magic helpers")
    return helpers


def check_magic_density(step, source, report, environment, **kwargs):
    helper = magic_helpers(step.config, "check_density.py") / "check_density.py"
    result = step.run_subprocess(
        ["python3", str(helper.resolve()), source.name],
        log_to=report, env=environment, **{**kwargs, "cwd": str(source.parent), "check": False})
    text = report.read_text()
    if (result["returncode"] or not text.rstrip().endswith("Done!")
            or not re.search(r"^Stepped area density results \(total tiles = [1-9]\d*\):$", text, re.M)
            or not re.search(r"^\S+ Density: [-+]?\d+(?:\.\d+)?$", text, re.M)):
        raise StepException("NOT_MEASURED: native Magic density report is incomplete or unmeasured")
    return {MAGIC_METRIC: len(re.findall(r"^\*\*\*Error:", text, re.M))}


@Step.factory.register()
class MagicDensity(Density):
    id = "VibeIC.MagicDensity"
    name = "PDK Magic density check"

    def run(self, state_in, **kwargs):
        if self.config.get("KLAYOUT_DENSITY_RUNSET"):
            return {}, {}
        magic_helpers(self.config, "check_density.py")
        work = Path(tempfile.mkdtemp(prefix="magic-", dir=tempfile.current_run() / "density"))
        source = work / f"{self.config['DESIGN_NAME']}.gds"
        source.symlink_to(Path(str(state_in[DesignFormat.GDS])).resolve())
        kwargs, environment = self.extract_env(kwargs)
        environment.update(PDK=str(self.config["PDK"]), PDK_ROOT=str(self.config["PDK_ROOT"]))
        return {}, check_magic_density(self, source, Path(self.step_dir) / "density.log", environment, **kwargs)


def fill_config(config, odb_path):
    """Keep the published recipe's PDK rules and placed pad/macro exclusions."""
    import odb

    layer_map = config.get("KLAYOUT_DEF_LAYER_MAP")
    tech = config.get("TECH_LEFS") or {}
    deck = config.get("KLAYOUT_DENSITY_RUNSET")
    if not layer_map or not tech or not deck:
        raise StepException("NOT_MEASURED: PDK density deck, layer map and technology LEF are required")
    deck = Path(str(deck))
    deck_files = list(dict.fromkeys([deck, *sorted(deck.parent.rglob("*.rb"))]))
    result = build_metal_fill_config(
        Path(str(layer_map)).read_text(),
        "\n".join(Path(str(path)).read_text() for path in tech.values()),
        "\n".join(path.read_text() for path in deck_files))
    if not result or result["_derivation"]["density_floor_pct"] is None:
        raise StepException("NOT_MEASURED: no PDK density floor could be derived")
    database = odb.dbDatabase.create()
    odb.read_db(database, str(odb_path))
    block = database.getChip().getBlock()
    dbu = block.getDbUnitsPerMicron()
    spacing = max(layer["space_to_metal"] for layer in result["layers"])
    pad_masters = set()
    for path in config.get("PAD_LEFS") or []:
        pad_masters.update(re.findall(r"^\s*MACRO\s+(\S+)", Path(str(path)).read_text(), re.M))
    boxes, pads = [], False
    for instance in block.getInsts():
        master = instance.getMaster()
        is_pad = master.isPad() or master.getName() in pad_masters
        if not (is_pad or master.isBlock()):
            continue
        if not instance.isPlaced():
            raise StepException("NOT_MEASURED: a protected pad or macro has no placement")
        pads |= is_pad
        box = instance.getBBox()
        boxes.append([box.xMin() / dbu - spacing, box.yMin() / dbu - spacing,
                      box.xMax() / dbu + spacing, box.yMax() / dbu + spacing])
    result["keepout_boxes_um"] = sorted(boxes)
    if pads:
        die, core = block.getDieArea(), block.getCoreArea()
        edge = max(core.xMin() - die.xMin(), core.yMin() - die.yMin(),
                   die.xMax() - core.xMax(), die.yMax() - core.yMax()) / dbu
        result["keepout_edge_um"] = max(result.get("keepout_edge_um", 0), edge)
    return result


@Step.factory.register()
class DensityTopUp(Density):
    id = "VibeIC.DensityTopUp"
    name = "PDK density top-up"
    inputs = [DesignFormat.GDS, DesignFormat.ODB]
    outputs = [DesignFormat.GDS]
    config_vars = [*Density.config_vars,
                   next(item for item in MagicStep.config_vars if item.name == "MAGICRC")]

    def run(self, state_in, **kwargs):
        count = state_in.metrics.get(METRIC)
        if not self.config.get("KLAYOUT_DENSITY_RUNSET"):
            count = state_in.metrics.get(MAGIC_METRIC, count)
        if count is None:
            if not self.config.get("KLAYOUT_DENSITY_RUNSET"):
                return {}, {}
            raise StepException("NOT_MEASURED: KLayout density has not produced its native count")
        if count <= 0:
            return {}, {}
        if not self.config.get("KLAYOUT_DENSITY_RUNSET"):
            try:
                views, metrics = self.run_magic(state_in, **kwargs)
            except StepException as exc:
                detail = str(exc).removeprefix("NOT_MEASURED: ")
                raise StepError(f"Native density violations remain ({count} > 0): {detail}") from exc
            if metrics["magic__density_error__count"] > 0:
                raise StepError(f"Native Magic density violations: {metrics['magic__density_error__count']} > 0")
            return views, metrics
        root = Path(self.step_dir)
        engine = Path(os.environ.get("VIBEIC_KLAYOUT_TOOLS", "")) / "metal-fill/metal_fill.py"
        if not engine.is_file():
            return {}, {}
        try:
            config = fill_config(self.config, state_in[DesignFormat.ODB])
        except (OSError, ValueError) as exc:
            raise StepException(f"NOT_MEASURED: PDK fill inputs could not be read: {exc}") from exc
        config_path, output, report = root / "fill_config.json", root / "topped.gds", root / "fill_report.json"
        config_path.write_text(json.dumps(config, indent=2) + "\n")
        output.unlink(missing_ok=True)
        report.unlink(missing_ok=True)
        kwargs, environment = self.extract_env(kwargs)
        environment.update(FILL_GDS=str(state_in[DesignFormat.GDS]), FILL_CONFIG=str(config_path),
                           FILL_OUT=str(output), FILL_REPORT=str(report), FILL_CELL=self.config["DESIGN_NAME"])
        command = ["python3", str(engine)]
        result = self.run_pya_script(command, env=environment, check=False, **kwargs)
        if result["returncode"]:
            raise subprocess.CalledProcessError(result["returncode"], command)
        if not output.is_file() or not report.is_file():
            raise StepException("NOT_MEASURED: native fill left no layout or report")
        measured = json.loads(report.read_text())
        if measured.get("verdict") not in {"PASS", "PARTIAL"}:
            raise StepException("NOT_MEASURED: native fill did not produce a measured layout")
        filled = State(state_in, overrides={DesignFormat.GDS: NativePath(str(output))}, metrics=state_in.metrics)
        density = Density(self.config, filled)
        checked = density.start(toolbox=self.toolbox, step_dir=str(root / "density"))
        if METRIC not in checked.metrics:
            raise StepException("NOT_MEASURED: density rerun left no native count")
        return {DesignFormat.GDS: NativePath(str(output))}, {METRIC: checked.metrics[METRIC]}

    def run_magic(self, state_in, **kwargs):
        helpers = magic_helpers(self.config, "generate_fill.py", "check_density.py")
        work = Path(tempfile.mkdtemp(prefix="magic-", dir=tempfile.current_run() / "density"))
        fill_dir, checked_dir = work / "fill", work / "checked"
        fill_dir.mkdir()
        checked_dir.mkdir()
        name = self.config["DESIGN_NAME"]
        input_gds = fill_dir / f"{name}.gds"
        input_gds.symlink_to(Path(str(state_in[DesignFormat.GDS])).resolve())
        kwargs, environment = self.extract_env(kwargs)
        environment.update(PDK=str(self.config["PDK"]), PDK_ROOT=str(self.config["PDK_ROOT"]))
        self.run_subprocess(
            ["python3", str((helpers / "generate_fill.py").resolve()), input_gds.name, "-dist"],
            log_to=work / "fill.log", env=environment, **{**kwargs, "cwd": str(fill_dir)})
        pattern = fill_dir / f"{name}_fill_pattern.gds.gz"
        if not pattern.is_file() or not pattern.stat().st_size:
            raise StepException("NOT_MEASURED: native Magic fill left no pattern GDS")
        output = checked_dir / input_gds.name
        self.run_subprocess(
            ["klayout", "-b", "-zz", "-r", str(Path(get_script_dir()) / "klayout/insert_cell.py"),
             "-rd", f"input={input_gds}", "-rd", f"insert={pattern}", "-rd", f"output={output}"],
            log_to=work / "merge.log", env=environment, **kwargs)
        if not output.is_file() or not output.stat().st_size:
            raise StepException("NOT_MEASURED: native fill merge left no combined GDS")
        report = work / "density.log"
        return {DesignFormat.GDS: NativePath(str(output))}, check_magic_density(
            self, output, report, environment, **kwargs)
