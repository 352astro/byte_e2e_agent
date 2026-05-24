# Simple Git Committer

Use this skill when the user asks the agent to make a small, focused git commit.

## Instructions

1. Run `git status --short` to see changed files.
2. Inspect the relevant diff before staging anything.
3. Stage only the file or files needed for this commit.
4. Commit with a concise semantic message.

## Command Shape

Use normal git commands:

```bash
git add <target_file>
git commit -m "<type>: <short_description>"
```
