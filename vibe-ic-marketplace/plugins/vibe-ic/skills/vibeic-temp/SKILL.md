---
name: vibeic-temp
description: Inspect and clean Vibe-IC leftovers from crashed executions, showing size, date and name. Use for leftover temp cleanup, including an explicit request to remove all leftovers older than a day.
---

Executions clean up their own scratch and run folders automatically. This skill
handles leftovers after crashes. Use the plugin's `programs/vibeic_temp.py`;
`VIBEIC_TMP` defaults to `~/vibe-ic-temp`.

List leftovers with their exact names, dates, sizes and activity:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/programs/vibeic_temp.py" list --json
```

A listing request does not authorize deletion. Remove the leftover names selected
in the request. If none were named, ask which leftovers to remove. Skip active
executions, Git worktrees, input documents, cited or adopted reference evidence,
unrelayed result tars and anything belonging to another lane or queue.

```bash
python3 "$CLAUDE_PLUGIN_ROOT/programs/vibeic_temp.py" delete 'runs/<selected-name>' 'tmp/<selected-name>'
```

When the user asks to remove every leftover older than a day:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/programs/vibeic_temp.py" delete --older-than-day
```

The helper skips active executions and Git worktrees. Never delete the root,
projects or unselected folders. Report removed names and preserved exceptions.
An explicit keep request preserves a run folder; routine cleanup belongs to the
execution that created it, not to the user.
