## What this PR does

<!-- One-paragraph summary. Link the issue: "Closes #NNN" -->

## Type of change

- [ ] Bug fix
- [ ] New skill / new MCP tool wrapper / new device driver
- [ ] New deterministic check / gate
- [ ] New benchmark fixture
- [ ] Documentation / typo
- [ ] Refactor (no behaviour change)
- [ ] Test only

## How was this tested?

<!--
  Paste the commands you ran. At minimum:
    pytest -q vibe-ic-marketplace/plugins/vibe-ic/tests
    pytest -q mcp-eda/test
    python3 vibe-ic-marketplace/plugins/vibe-ic/programs/source_chip_agnostic_check.py \
            vibe-ic-marketplace/plugins/vibe-ic
-->

## Checklist

- [ ] I read [CONTRIBUTING.md](../CONTRIBUTING.md)
- [ ] `pytest -q` passes for both `vibe-ic-marketplace/plugins/vibe-ic/tests/` and `mcp-eda/test/`
- [ ] `source_chip_agnostic_check.py` PASSes (no private chip / vendor / protocol names)
- [ ] If I added a walker / regex / merge patch, I shipped a real-shape fixture under `tests/fixtures/real_benchmark/`
- [ ] If I changed behaviour, I updated the relevant `docs/` page
- [ ] If I bumped a version, I updated `plugin.json`, `marketplace.json`, and `package.json` together
- [ ] If I added a new MCP tool wrapper, I also opened a PR against [awesome-open-ic](https://github.com/vibeic/awesome-open-ic) to mark the upstream project as MCP-wrapped
- [ ] No `git push --force` on `main`, no `--no-verify`, no skipped pre-commit hooks
- [ ] No bundled secrets / API keys / proprietary PDK files
