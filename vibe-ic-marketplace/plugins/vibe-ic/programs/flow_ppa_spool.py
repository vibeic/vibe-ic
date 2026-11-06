"""Self-contained native trials in the caller's existing job-folder spool."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tarfile
import uuid


PLUGIN = Path(__file__).resolve().parent.parent
RUN_SCRIPT = '''#!/usr/bin/env bash
set -uo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")" || exit 1
job_dir=$(pwd -P)
date -u +%FT%TZ > started.txt
container=$(python3 -c 'import json; print(json.load(open("job.json"))["container"])')
image=$(python3 -c 'import json; print(json.load(open("config.json"))["image"])')
task_scratch="${FLEET_SCRATCH:-${TMPDIR:?A job scratch directory is required}}"
docker run --rm --name "$container" --cpus CPU_COUNT --memory MEMORYg --memory-swap MEMORYg \\
    --user "$(id -u):$(id -g)" --network none \\
    -v "$job_dir:/work:rw" -v "$task_scratch:/scratch:rw" \\
    -e VIBEIC_TMP=/scratch -e TMPDIR=/scratch -e PYTHONDONTWRITEBYTECODE=1 \\
    -e VIBEIC_EDA_IMAGE="$image" -w /work --entrypoint bash "$image" -lc '
        ll_site=$(python3 -c "import pathlib,librelane; print(pathlib.Path(librelane.__file__).parent.parent)")
        export PYTHONPATH="/work/plugin/programs:$ll_site:${PYTHONPATH:-}"
        exec python3 /work/plugin/programs/flow_ppa_spool.py worker
    ' > native.log 2>&1
native_rc=$?
python3 plugin/programs/flow_ppa_spool.py collect "$native_rc"
date -u +%FT%TZ > ended.txt
printf '%s\\n' "$native_rc" > exit-code.txt
exit "$native_rc"
'''


def publish(project, outbox, variant, *, cpus, flow_args, level, image):
    """Publish only after inputs, programs and the two contract files are ready."""
    project, outbox = Path(project).resolve(), Path(outbox).resolve()
    if outbox.is_relative_to(project) or outbox.is_relative_to(PLUGIN):
        raise ValueError("The job spool must be outside the project and plugin")
    outbox.mkdir(parents=True, exist_ok=True)
    job = "vibeic-ppa-" + uuid.uuid4().hex
    staging = outbox / ("." + job)
    staging.mkdir()
    try:
        shutil.copytree(PLUGIN, staging / "plugin",
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".git"))
        shutil.copytree(project, staging / "inputs", ignore=lambda path, names: {
            item for item in names if Path(path) == project
            and item in {"steps", "reports", "work", "runs", ".git"}})
        name, overrides = variant
        (staging / "config.json").write_text(json.dumps({
            "name": name, "overrides": overrides, "public_args": list(flow_args),
            "cpus": cpus, "ppa_level": level, "image": image}, indent=2) + "\n")
        (staging / "job.json").write_text(json.dumps({
            "cpus": cpus, "label": "Native PPA trial " + name, "container": job,
            "priority": 10 if name == "reference" else 0, "keep_run": False}, indent=2) + "\n")
        script = RUN_SCRIPT.replace("CPU_COUNT", str(cpus)).replace("MEMORY", str(cpus * 4))
        (staging / "run.sh").write_text(script)
        (staging / "run.sh").chmod(0o755)
        staging.rename(outbox / job)
    except Exception:
        shutil.rmtree(staging)
        raise
    return job


def discard_job(outbox, job):
    """Delete an author's used job even if its consumer already removed it."""
    def on_error(function, path, error):
        if not isinstance(error[1], FileNotFoundError):
            raise error[1]

    shutil.rmtree(Path(outbox) / job, onerror=on_error)


def worker(root):
    from flow_explore import run_variant

    config = json.loads((root / "config.json").read_text())
    cores = sorted(os.sched_getaffinity(0))[:config["cpus"]]
    row = run_variant(root / "inputs", root, ("project", config["overrides"]),
                      cores, config["public_args"], config["ppa_level"])
    row["name"] = config["name"]
    (root / "metrics.json").write_text(json.dumps(row, indent=2) + "\n")
    return row["exit_code"] if row["exit_code"] is not None else 2


def finish(root, code):
    """Keep native evidence in returned names before exit-code.txt is written."""
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    config = json.loads((root / "config.json").read_text())
    metrics = root / "metrics.json"
    if not metrics.is_file():
        metrics.write_text(json.dumps({"name": config["name"], "exit_code": code,
            "all_pass": False, "state": "NOT_MEASURED", "rows": [], "metrics": {},
            "project": str(root / "project"), "overrides": config["overrides"],
            "resolved_settings": {}, "native_activity": {}, "violation_metrics": {},
            "ppa_level": config["ppa_level"], "wall_seconds": None,
            "detail": "Native trial launch did not produce a report"}) + "\n")
    log = root / "project.log"
    if log.is_file():
        shutil.copyfile(log, reports / "public-entry.log")
    project = root / "project"
    project.mkdir(exist_ok=True)
    try:
        with tarfile.open(reports / "project.tar.gz", "w:gz", compresslevel=1) as archive:
            archive.add(project, arcname="project")
    except OSError as exc:
        row = json.loads(metrics.read_text())
        row.update(state="NOT_MEASURED", all_pass=False, collection_error=str(exc))
        metrics.write_text(json.dumps(row, indent=2) + "\n")


def collect(job, results, destination):
    """Read completed native payloads; a partly transferred archive stays pending."""
    result = Path(results) / job
    code_file, metrics_file = result / "exit-code.txt", result / "metrics.json"
    archive = result / "reports/project.tar.gz"
    if not all(path.is_file() for path in (code_file, metrics_file)):
        return None
    import vibeic_temp

    try:
        code = int(code_file.read_text().strip())
        row = json.loads(metrics_file.read_text())
        if row.get("collection_error"):
            row.update(exit_code=code, all_pass=False, spool_job=job, spool_result=str(result))
            return row
        if not archive.is_file():
            return None
        with vibeic_temp.TemporaryDirectory(prefix="ppa-result-") as staging:
            with tarfile.open(archive) as bundle:
                bundle.extractall(staging, filter="data")
            destination = Path(destination)
            shutil.move(str(Path(staging) / "project"), destination)
    except (EOFError, tarfile.ReadError, ValueError):
        return None
    mapping = {str(row.get("project") or "/work/project"): str(destination)}
    # The returned archive preserves raw worker files; local State paths must
    # name the collected views so downstream native consumers can load them.
    for path in destination.rglob("*.json"):
        try:
            before = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        after = vibeic_temp.relocate(before, mapping)
        if after != before:
            mode = stat.S_IMODE(path.stat().st_mode)
            path.chmod(mode | stat.S_IWUSR)
            try:
                path.write_text(json.dumps(after, indent=2) + "\n")
            finally:
                path.chmod(mode)
    row = vibeic_temp.relocate(row, mapping)
    row.update(exit_code=code, all_pass=bool(row.get("all_pass")) and code == 0,
               spool_job=job, spool_result=str(result))
    return row


if __name__ == "__main__":
    if sys.argv[1:] == ["worker"]:
        sys.exit(worker(Path.cwd()))
    if len(sys.argv) == 3 and sys.argv[1] == "collect":
        finish(Path.cwd(), int(sys.argv[2]))
    else:
        sys.exit("Internal worker invocation requires its job folder")
