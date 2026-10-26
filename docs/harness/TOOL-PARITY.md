# Python → Rust tool survey

Survey of this checkout, 2026-10-26. Python capabilities are assembled by
`coworker/catalog.py` and `coworker/agent.py`; not every persona receives every
tool. This compares shipped integrations, not what a caller could implement
through a generic shell or MCP server. No Python code is changed by this work.

| Capability | Python | Rust SDK after this change |
|---|---|---|
| Read/list files | Windowed reads, directory/glob listing, multiple granted roots | `coding.read_file/list_files`: bounded workspace-only UTF-8 reads/listing. Glob/ignore controls supported; directory entries/multiple granted roots remain different. |
| Edit files | aisuite write/replace, Codex-style patch, unified diff | Atomic `coding.write_file/edit_file`, hash preconditions, exact single-match replacement. Exact Codex-style and unified text patches now supported; fuzzy hunks, renames and binary patches excluded. |
| Code search | `grep`: regex, glob, ripgrep/.gitignore awareness | `coding.search_files`: bounded literal/regex search, glob and gitignore controls. |
| Commands/background jobs | Persistent shell cwd/env, `run_shell`, `shell_task_output/kill` | Fresh-shell commands plus tracked process start/status/logs/stop and configurable deadlines. No persistent shell state; managed processes currently Linux only. |
| Git inspection | `git_status`, `git_diff`, `git_log` | Dedicated bounded `coding.git_status/git_diff/git_log`; repository helpers disabled. |
| Questions | `ask_user` and UI policies | Structured `ask_user`; SDK now exposes durable auto-skip independently of approval mode. Schemas differ. |
| Planning | `propose_plan`, `todo_write` | Durable `update_plan`; not a wire-compatible replacement for Python's plan approval UI. |
| Skills/history | Skill loading/resources and session history | Bundled skills, `load_skill`, `read_skill_resource`, `read_history` exist. Workspace skill-directory discovery is a separate integration task. |
| Delegation/teams | `explore`, lead/worker creation, boards/messages | Declarative subagents and durable team boards on SQLite/PostgreSQL exist. No identical synchronous `explore` API or proposal-card workflow. |
| Web | `web_search`, `web_fetch` (`coworker/web.py`) | `coding.web_fetch`: public HTTPS text extraction. Web search, authenticated fetch and browser execution remain explicit integrations. |
| Long-term memory | `remember`, `memory_read/update/forget/search` | Durable scoped remember/read/search/update/forget on SQLite/PostgreSQL; literal search, no embeddings/RAG. |
| Clock/scheduling | Current time, scheduled-task CRUD, `sleep_for/until`, completion/event wakes | UTC clock and durable one-shot/bounded recurring tasks, dispatched by SDK host. No cron, sleep/event wake parity or distributed scheduler. |
| Runtime access requests | `request_directory`, `request_network_access`, `request_tool`, connector grants | Host-controlled resource policy and tool registration exist; equivalent model-facing request/consent tools are missing. |
| Connectors | Email, Slack/Telegram, GitHub/GitLab, Jira/Linear, Confluence, Zendesk and more | Generic MCP/native/app callback integration exists. Bundled authenticated service adapters are not ported. |
| Browser/computer/media | Optional browser connector and image-related integration paths | Optional Windows computer tool crate and ephemeral image tool results exist. Not broad browser automation or document/media tool parity. |

The Python file/Git catalog also incorporates aisuite tools; its exact dependency
version determines that expanded inventory. This survey identifies the explicit
capability families and editing formats referenced in the checked-in catalog,
rather than importing Python dependencies or claiming an exhaustive remote catalog.

## Remaining differences

The learner integration now has rich search, patch editing, Git inspection, web
fetch, memory and scheduling. Remaining gaps include multiple granted filesystem
roots, persistent shell cwd/environment, broader patch formats, web search,
semantic retrieval, cron/event wakes and model-facing access-request tools.
Authenticated connectors remain application integrations through MCP/native tools.

Scheduling dispatch currently belongs to the SDK host, including SDK + PostgreSQL;
the multi-node server reference does not automatically dispatch these timers.

See [coding tools](CODING-TOOLS.md) and [memory and scheduling](ASSISTANT-TOOLS.md)
for APIs, execution placement, storage semantics and limits.
