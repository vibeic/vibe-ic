---
name: sample-command
description: Replace this — what does /sample-command do?
argument-hint: <project-dir> [--option]
---

# /sample-command

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/sample_runner.py "$1" ${@:2}
```

Tell Claude (AI) what to do after the runner completes.
