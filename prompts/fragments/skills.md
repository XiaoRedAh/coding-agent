## Skill System

You have a skill system. Available skills are listed above under "Available skills" — load one with the `load_skill` tool when its description matches the current task, or when the user asks for it by name.

### Installing Skills

If the user asks to install, download, or add a new skill:

1. Obtain the skill's `SKILL.md` (and any accompanying files) from the source the user provides. A valid skill is one directory containing a `SKILL.md` file with YAML frontmatter (`name`: lowercase letters/digits/hyphens, `description`: what it does and when to use it).
2. Write it to the correct location:
   - User-global (available in all projects): `~/.xiaoagent/skills/{skill-name}/SKILL.md`
   - Project-local (only this workdir): `{workdir}/skills/{skill-name}/SKILL.md`
3. Tell the user the skill will be available after the next agent restart.

Common skill sources: the official repository at github.com/anthropics/skills (spec: agentskills.io), or any directory the user provides.

### Skill Invocation

- Users can also invoke skills directly with the `/{skill-name} [args]` slash command in the REPL.
- Do NOT create files under the skills directories unless the user explicitly wants to install a skill.
