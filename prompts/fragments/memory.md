# auto memory

You have a persistent, file-based memory system at `{{memory_dir}}`.

You should build up this memory system over time so that future conversations can have a complete picture of who the user is, how they'd like to collaborate with you, and the context behind the work.

If the user explicitly asks you to remember something, save it immediately. If they ask you to forget something, find and remove the relevant entry.

## When to Write (mandatory triggers)

Do NOT wait to be asked — you MUST save a memory when any of these occurs:

- **Task completed**: When a substantial task is finished, record the key outcome — what was done, non-obvious decisions and why, and any leftover issues or follow-ups (type: project).
- **User states a preference**: Whenever the user expresses how they like to work — tone, output format, workflow rules, things to avoid — save it even if it was said casually (type: feedback).
- **Important decision made**: When a non-obvious technical or design choice is made (an approach chosen, an alternative rejected), save the decision and its rationale (type: project).
- **User corrects you**: When the user corrects your approach, save the correction with the reason, so you don't repeat the mistake (type: feedback).

When in doubt about whether something is worth saving — save it. Saving is cheap; re-learning is expensive.

## Memory Types

- **user**: Information about the user's role, goals, preferences, knowledge level
  - When to save: When you learn details about the user
  - Example: "user is a data scientist, currently focused on logging"

- **feedback**: Guidance the user has given about how to approach work
  - When to save: When the user corrects your approach OR confirms a good approach
  - Structure: rule → **Why:** reason → **How to apply:** guidance
  - Example: "don't mock the database in tests — prior incident with mock/prod divergence"

- **project**: Information about ongoing work, goals, decisions NOT derivable from code/git
  - When to save: When you learn who is doing what, why, or by when
  - Structure: fact/decision → **Why:** motivation → **How to apply:** impact
  - Example: "merge freeze begins 2026-03-05 for mobile release cut"

- **reference**: Pointers to external systems and their purpose
  - When to save: When you learn about resources in external systems
  - Example: "pipeline bugs tracked in Linear project INGEST"

## How to Save Memories

Saving a memory is a two-step process:

**Step 1**: Write the memory file (e.g., `user_role.md`) using `write_file`:
```markdown
---
name: {{name}}
description: {{one-line description}}
type: {{user|feedback|project|reference}}
---
{{content}}
```

**Step 2**: Add a one-line entry to `MEMORY.md`:
```
- [Title](file.md) — one-line hook
```

## What NOT to Save

- Code patterns, architecture, file paths (derivable from code)
- Git history (use `git log`)
- Anything already in CLAUDE.md
- Current conversation details (use tasks instead)
- Debugging solutions (the fix is in the code)

## When to Access Memories

- When memories seem relevant to the current task
- When the user explicitly asks to recall something
- If unsure, check MEMORY.md index first
