# PLAN

## V1 Success Requirements

- [ ] Installer: README includes one copy-paste install script that sets up prerequisites and boots `pith`.
- [ ] Setup CLI: `pith setup` runs an interactive flow for provider/model selection and API key wiring.
- [ ] Setup CLI: Telegram setup is optional and skippable.
- [ ] Setup CLI: Telegram setup can be run later from the same CLI.
- [ ] Chat CLI: user can chat with the agent from CLI without Telegram.
- [ ] Config handling: setup CLI writes/updates external `config.yaml` and `.env` references with validation and clear errors.
- [ ] Bootstrap mode: runtime uses bootstrap prompt mode until required profile fields exist in SQLite.
- [ ] Persona layer: `SOUL.md` is always injected and remains agent-editable.
- [ ] Continuity: memory and session history are both persisted in SQLite and survive restart.
- [ ] Memory tools: `memory_save` and `memory_search` operate directly on DB tables; search returns full matched entries.
- [ ] Unified tool API: runtime exposes `tool_call(name, args)` for both extension tools and MCP tools.
- [ ] Namespace safety: MCP tools are registered as `MCP__<server>__<tool>` and extension tools with `MCP__` prefix are rejected.
- [ ] Extension loop: extension files in `workspace/extensions/tools/` hot-reload without process restart.
- [ ] Self-growth demo: agent can create a new extension tool and call it successfully in a later turn.
- [ ] Docker: repository includes a working `Dockerfile` and documented run command.
- [ ] Safety boundary: no Docker socket mount; no host FS access beyond mounted paths; runtime config mount is read-only.
- [ ] Observability: append-only local `.log` file(s) capture turns/tool calls/errors and are excluded from git.
- [ ] Telegram loop: when configured, long-polling receives messages and returns responses end-to-end.
