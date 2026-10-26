# Python → Rust tool survey

Survey of this checkout, 2026-10-26. Python capabilities are assembled by
`coworker/catalog.py` and `coworker/agent.py`; not every persona receives every
tool. This compares shipped integrations, not what a caller could implement
through a generic shell or MCP server. No Python code is changed by this work.

| Capability | Python | Rust SDK after this change |
|---|---|---|
| Read/list files | Windowed reads, directory/glob listing, multiple granted roots | `coding.read_file/list_files`: bounded workspace-only UTF-8 reads/listing. Glob/directory entries/multi-root parity remains. |
| Edit files | aisuite write/replace, Codex-style patch, unified diff | Atomic `coding.write_file/edit_file`, hash preconditions, exact single-match replacement. Patch/diff formats remain missing. |
| Code search | `grep`: regex, glob, ripgrep/.gitignore awareness | `coding.search_files`: bounded literal search. Regex/glob/gitignore parity remains. |
| Commands/background jobs | Persistent shell cwd/env, `run_shell`, `shell_task_output/kill` | Fresh-shell commands plus tracked process start/status/logs/stop and configurable deadlines. No persistent shell state; managed processes currently Linux only. |
| Git inspection | `git_status`, `git_diff`, `git_log` | No dedicated Git tools. Shell can invoke Git, but is a broader execution capability. |
| Questions | `ask_user` and UI policies | Structured `ask_user`; SDK now exposes durable auto-skip independently of approval mode. Schemas differ. |
| Planning | `propose_plan`, `todo_write` | Durable `update_plan`; not a wire-compatible replacement for Python's plan approval UI. |
| Skills/history | Skill loading/resources and session history | Bundled skills, `load_skill`, `read_skill_resource`, `read_history` exist. Workspace skill-directory discovery is a separate integration task. |
| Delegation/teams | `explore`, lead/worker creation, boards/messages | Declarative subagents and durable team boards on SQLite/PostgreSQL exist. No identical synchronous `explore` API or proposal-card workflow. |
| Web | `web_search`, `web_fetch` (`coworker/web.py`) | No bundled generic web-search/fetch tools. Can add an explicit MCP/native provider; that is not bundled parity. |
| Long-term memory | `remember`, `memory_read/update/forget/search` | No equivalent semantic-memory CRUD tools. Durable sessions/compaction/history are not long-term memory. |
| Clock/scheduling | Current time, scheduled-task CRUD, `sleep_for/until`, completion/event wakes | No equivalent scheduling/clock tool set. SDK timers remain unsupported; team notification delivery is a separate capability. |
| Runtime access requests | `request_directory`, `request_network_access`, `request_tool`, connector grants | Host-controlled resource policy and tool registration exist; equivalent model-facing request/consent tools are missing. |
| Connectors | Email, Slack/Telegram, GitHub/GitLab, Jira/Linear, Confluence, Zendesk and more | Generic MCP/native/app callback integration exists. Bundled authenticated service adapters are not ported. |
| Browser/computer/media | Optional browser connector and image-related integration paths | Optional Windows computer tool crate and ephemeral image tool results exist. Not broad browser automation or document/media tool parity. |

The Python file/Git catalog also incorporates aisuite tools; its exact dependency
version determines that expanded inventory. This survey identifies the explicit
capability families and editing formats referenced in the checked-in catalog,
rather than importing Python dependencies or claiming an exhaustive remote catalog.

## Suggested sequence after the learner-container integration

1. Regex/glob/gitignore-aware search, dedicated read-only Git tools, and patch/diff
   editing. These are the largest remaining coding-agent convenience gaps.
2. A reusable web-fetch/search provider with explicit network and credential policy.
3. Decide the long-term-memory contract and storage ownership before adding memory
   tools. Keep it distinct from durable session history.
4. Timer/scheduler and access-request tools when a product actually needs those
   workflows; build on durable state rather than process-local timers.
5. Port selected connectors or consume explicit MCP integrations, based on partner
   demand. Avoid making the core harness carry every service's authentication UI.

See [coding tools and unattended sessions](CODING-TOOLS.md) for the newly added
API, execution placement, process lifetime and current platform limits.
