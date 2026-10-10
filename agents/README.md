# Agent setup

For Claude Code, copy `agents/claude/shotseek/` to
`~/.claude/skills/shotseek/`. Alternatively, create that folder with `mkdir -p`
and write `shotseek agent-prompt --target claude-skill` into its `SKILL.md`.

For Codex, paste `agents/codex/AGENTS.md` into the project's `AGENTS.md` or
`~/.codex/AGENTS.md`. For another agent, paste `agents/generic/PROMPT.md` into
its instructions. These three files are generated from
`src/shotseek/agent/guide.md` and must stay synchronized with `agent-prompt`.

No server or remote authentication is needed. The user's own agent calls the local command.
