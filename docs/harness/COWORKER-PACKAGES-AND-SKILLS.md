# Native coworker packages and bundled skills

M2b.4 adds a supported native manifest profile and progressive skill loading.
This is not full Desktop persona/skill-manager parity. Python/Desktop is unchanged.

## Package layout

```text
partner-bundle/
  tools.json                          # existing exact MCP routing
  coworker/
    manifest.md                       # identity, description, instructions
    skills/
      report-guide/
        SKILL.md                      # skill metadata + instruction body
        references/report-template.md
        scripts/optional-helper.sh    # inert until separately executed
```

The coworker directory layout matches Python's manifest-with-sibling-skills shape;
the native package wraps it alongside `tools.json`. Use `harness/examples/skilled`
as the complete runnable example. One installed coworker per runtime process and
at least one explicitly bound MCP server remain the current profile.

```yaml
---
schema_version: 1
id: example-report
name: ExampleApp Report Coworker
version: "1.0"
description: Prepares local reports using a bundled procedure.
tagline: A repeatable report workflow
requires_folder: true
skills: [report-guide]
---
Use the report-guide skill when preparing a report. Follow the user's task and
report observed results honestly. Loading a skill does not authorize publishing.
```

Supported frontmatter: `schema_version`, `id`, `name`, `version`, `description`,
`tagline`, `icon`, `requires_folder`, `skills`, `default_model`, `planning`, `team_role`.
Optional `planning: true` enables [durable session plans](DURABLE-PLANS.md);
it grants no execution permission. Omission keeps the existing tool catalog.
Schema version is a format integer;
`version` is the author's informational string, not an update/security decision.
Older native manifests without `schema_version` normalize to 1 and pass the same
strict validation. Name defaults to ID; workspace remains required.

Unsupported fields are rejected, including `default_permission_mode`, `tools`,
`connectors`, `models`, other scheduling/team/subagent traits, or approval guidance.
This avoids accepting a setting we do not implement. Tools are defined in the
existing `tools.json`, while session permissions and host classifications remain
host-controlled. A Python coworker may need conversion to this explicit subset.

Optional `team_role: lead|worker` enables the shared team contract. Such a bundle
requires membership in a host-created team before its first turn. The
[SDK host](SDK-STORAGE.md) supports SQLite or PostgreSQL; the distributed server
uses PostgreSQL. It does not grant tools, permission modes or sandbox access. See
[providers and teams](PROVIDERS-AND-TEAMS.md) and the lead/worker example bundles.
Omitting the field preserves solo behavior.

## Skill format and selection

```yaml
---
name: report-guide
description: Create an evidence-based report using the bundled template.
allowed-tools: [write_file, run_shell]
license: MIT
metadata:
  author: ExampleApp
---
Read references/report-template.md with read_skill_resource. Use its structure
for the requested local report. Request ordinary approval before file writes.
```

Required: name, description, nonempty body. Name must match its folder. Optional:
`allowed-tools` (or `allowed_tools`), `license`, `compatibility`, string-to-string
`metadata`. Tool hints accept a YAML string/list and are returned as
`allowed_tools_hint`. They **neither grant nor restrict runtime tool access**.
Unknown fields, duplicate YAML keys, unsafe names and malformed packages fail.

Selection happens twice:

1. Manifest `skills` narrows the bundled catalog. Omitted/empty = all discovered
   bundle skills, matching the current Python convention. Every named skill must
   exist. Even unselected skill files remain validated and package-hashed.
2. Host `session/create.skills` can narrow it further. Omitted = manifest-selected
   catalog; explicit `[]` = none. Unknown/duplicate names are rejected. This
   selection is immutable for the session; no live enable/disable endpoint yet.

```json
{"jsonrpc":"2.0","id":2,"method":"session/create","params":{"name":"Report","coworker":"skilled-example","workspace":"/path/to/project","skills":["report-guide"],"permissions":{"mode":"ask"}}}
```

There is no global/project skill auto-discovery, overwrite precedence, upload,
download, archive installation, model `save_skill`, or skill editing in this slice.
Keep installed bundles outside writable projects and protect them through the
installer/OS. Editing a package requires a new session; a pending approval cannot
silently switch to new instructions/resources. Restoring the exact original
package/profile permits that original pending work to resume.

## Runtime behavior

Every model request receives the selected skill catalog, not full instruction
bodies. The model uses ordinary function tools:

- `load_skill({"name":"report-guide"})`: complete instructions, resource inventory,
  content digests, descriptive metadata and execution-backend resource path.
- `read_skill_resource({"name":"report-guide","path":"references/report-template.md"})`:
  bounded UTF-8 content from that exact skill's inventory; no traversal, absolute
  paths, symlinks or arbitrary host reads. Not an executor.

Both tools are internal Read operations, not MCP routes. Ask still asks; Auto-
approve still needs a verdict; Bypass skips approval. Loading cannot approve the
next write, add a tool, change policy, obtain a credential or open the network.
Skill bodies/reference contents are not supplied to the action reviewer as user
authority. Scripts never execute automatically; an explicit subsequent tool call
is separately authorized and runs in the selected backend.

`tool_finished` atomically records content/provenance with successful loaded-skill
names. Denial/error does not claim a skill loaded. Names and selection survive
restart and compaction; full bodies may be summarized out of model context. The
catalog/reload guidance remains, and the model can load the same pinned skill again.

Resource paths for approved shell use are `/opt/partner/coworker/skills/<name>`
under OpenShell, or the installed directory under explicit Off. Skill reads report
`enforcement: bundle-read-only`, `sandbox: not-applicable`; subsequent MCP actions
report their actual execution backend. Off is still unsandboxed host-account access.

**Selection is not file confidentiality.** The sandbox has the installed package
mounted read-only. An approved shell can read other package files, including an
unselected skill. No claim of isolation between skills or MCP servers.

## Partner-facing inspection and limits

`inspect-bundle` and `coworker/list` include normalized package metadata and skill
catalogs, never skill bodies. `skills/list` takes `session_id` and returns that
session's catalog, loaded names and package digest; incompatible runtime/package
profiles are refused. `session/attach.session` includes `package`, `skills` and
`loaded_skills`. Initialization advertises `coworker_schema_versions: [1]`,
`bundled_skills: true`, `skill_resources: true`.

Limits: 32 skill folders; 64 KB per manifest/SKILL.md; 1,024-byte descriptions;
128 resources per skill; 8 MiB per resource in the package; 64 KB UTF-8 resource
reads. Non-text/oversized reads return an explicit tool error.
Serialized skill-tool results are capped at 128 KB (including JSON escaping and
resource inventory), with an explicit error instead of partial instructions.
Total package:
128 MiB, 4,096 entries, depth 32; resource tree depth 8. Files are fingerprinted
before and after package loading. This is change detection, not a signed package
or protection from a malicious process already controlling the host account.

Use fresh **schema-6** state. Earlier development stores remain untouched and are
refused without migration. No new runtime dependencies or Python interpreter.

## Python reference and known differences

Reference: `c34615d`, `coworker/skills/base.py`, `agent.py`, `personas/manifest.py`,
persona-skill tests. Preserve catalog-first + `load_skill` and bundle narrowing.
Shared fixtures: `harness/tests/skills-contract.json`; development adapter:
`harness/tests/python-skills-contract.py`.

Current Python manually splits frontmatter lines: multiline descriptions and YAML
tool lists can be misread; duplicate names can overwrite earlier entries. Native
uses typed YAML, rejects duplicate keys and folder/name mismatches, and never
rescans writable workspaces for newly authored instructions. Four parser differences
are explicitly tested. These are follow-up findings, not Python fixes in this slice.
The archived skills spec's scope precedence differs from current Python code;
bundled-only native skills have no cross-scope precedence decision to make yet.
