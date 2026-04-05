---
name: commit
description: Create a well-formatted git commit following conventional commits
---

# Git Commit Skill

## When to use
When the user asks to commit changes, create a PR, or save progress.

## Steps
1. Run `git status` to see what changed
2. Run `git diff --staged` to review staged changes (if nothing staged, run `git add -A` first)
3. Analyze the changes and determine the commit type:
   - `feat`: new feature
   - `fix`: bug fix
   - `refactor`: code restructuring
   - `docs`: documentation only
   - `test`: adding or updating tests
   - `chore`: maintenance tasks
4. Write a commit message: `type(scope): short description`
5. Run `git commit -m "type(scope): description"`

## Rules
- Keep the first line under 72 characters
- Use imperative mood ("add" not "added")
- Reference issue numbers when applicable (#123)
- If $ARGUMENTS is provided, use it as the commit message hint
