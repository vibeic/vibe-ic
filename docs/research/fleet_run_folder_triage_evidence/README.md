# fleet_run_folder_triage_evidence

Content lifted out of run folders before they were removed by the 2026-08-21
fleet run-folder triage (`../fleet_run_folder_triage.md`).

Every file here satisfied all four of these at the moment of the triage:

1. it is not a blob of any ref of `vibe-ic` or `benchmark-data`;
2. it does not live in any other run folder anywhere on the six-host fleet;
3. it sits **outside every run root** of its folder, so the folder's SUPERSEDED
   verdict — "a later, strictly better run of the same IC on the same PDK
   replaces this one" — says nothing about it;
4. it is not in a machine-regenerable class (`__pycache__`, PDK copy,
   `pytest-of-*`, `node_modules`, caches).

In other words: the run around it was superseded, this was not, and it existed
in exactly one place. It is committed here so the folder could be removed
without destroying it. Layout files (GDSII) were too large to commit and were
preserved on their own hosts instead, under `~/_kept_layouts/`.

Layout: `<host-octet>/<original folder>/<original path>`, byte-for-byte. Each
file was verified after the copy by recomputing `sha1("blob <size>\0" + content)`
— git's own object identity — against the census record: 88 of 88 matched.

Typical content: an agent's `RESULT.md` for that round, `agent.log` / `iter*.log`
narratives, an authored `.patch`, the positive and negative control arms of an
experiment, `flow_compliance_*.json` snapshots, and launch scripts.

These are historical records, not code. Nothing imports them and nothing tests
them.
