# Run native Level 3 PPA tools

Run `programs/ppa_level3.py` inside the EDA environment with LibreLane, the
selected PDK and, for ORFS, the isolated `autotuner-python` launcher. Set `HOME`
to the execution user's home when the container supplies a temporary home.
Every output directory must be under `~/vibe-ic-temp/runs`. Each child gets a
private temporary folder under `FLEET_SCRATCH`, otherwise `TMPDIR`, otherwise
`~/vibe-ic-temp/tmp`. The folder is removed when the child exits. Native runs,
adopted views and reports remain available for review.

```python
from pathlib import Path
from ppa_level3 import Budget, NativeBest, Orfs, run

results = run(
    Path("project"),
    output=Path.home() / "vibe-ic-temp/runs/native-ppa",
    route="ic",
    pdk_root=Path("installed-pdks"),
    orfs=Orfs(Path("installed-orfs"), "explicit-platform", Path("native-space.json")),
    budget=Budget(samples=200, jobs=8, threads=2),
)
for arm, result in results.items():
    if isinstance(result, NativeBest):
        print(arm, result.index, result.run)
    else:
        print(arm, result.status, result.reason, result.reports)
```

The equivalent CLI requires `--project`, `--output`, `--route` and `--pdk-root`.
ORFS additionally requires `--orfs-root`, `--platform` and `--native-space`
together. Omitting ORFS returns `NOT_MEASURED` for its arm and still runs both
LibreLane arms. The platform is explicit. The adapter exports the resolved
native standard-cell, technology, timing and mapping views to that platform.
Unsupported inputs remain native errors or `NOT_MEASURED`.

Each invocation creates a new folder and gives each arm a private project.
The snapshot contains original inputs, L documents, producer RTL and declared
SDC. It excludes earlier results and generated native overrides. Only the top
declaration survives from implementation metadata. The caller project stays
unchanged.

LibreLane `SynthesisExploration` and `Optimizing` run unchanged. Synthesis
exploration has no single native winner. This adapter completes successful
strategies in minimum synthesis area order until one passes native Chip or
Classic closure. That ordering does not optimize final routed PPA. Optimizing
retains its native strategy and utilization choice before full native closure.
Document-fixed synthesis strategy prevents both native searches. Document-fixed
core utilization prevents Optimizing, which forcibly varies it.

ORFS runs a stock reference, then unchanged AutoTuner with Hyperopt, PPAImprov,
seed 42 and physical finish. Document-fixed dimensions are removed from its
native JSON search space. The original SDC stays unchanged. Without a supplied
SDC, the existing chip-input constraint translator uses native elaborated ports
and document settings. SDC search mutations are unsupported. Exact trial IDs
identify results. Native score orders candidates. Native KLayout DRC and LVS
results, final timing and electrical reports, and original declared limits
determine whether a physical result can be exported. The dashboard QoR checker
is not used.

Chip PDN uses the explicit ORFS platform's own script, native voltage defaults
and prepared supply names. Native LibreLane PDN settings without an ORFS
translation produce `NOT_MEASURED`. Each native worker uses at most eight
threads.

A completed handoff contains `job.json` with `keep_run: true` and publishes
`index.json` last. Its schema is
`{documents:[path],settings:[path],odb:path,def:path,netlist:path,sdc:[path],liberty:[path],spef:[path],reports:[path],metrics:[path]}`.
All paths are relative to the handoff folder. Files retain their contents and
native corner directories. Missing essential views produce `NOT_MEASURED`
without an index. Native failures remain available in the retained run folder.

The result covers the selected native flows and their enabled checks. It does
not claim whole-design verification or tape-out acceptance. Level 4 consumes the
plain-path index separately.
