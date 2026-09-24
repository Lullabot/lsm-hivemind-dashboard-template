# kenkeep knowledge base

[kenkeep](https://github.com/e0ipso/kenkeep) builds a git-tracked knowledge base out of your AI coding sessions. Hooks record each Claude Code session, and a curation pass turns those transcripts into small typed markdown notes ("nodes") under `.ai/kenkeep/nodes/`. The curator decides on its own what to keep and only asks a human when a new proposal contradicts an existing node.

For a PM setup this replaces the pile of feedback files and CLAUDE.md appendices that grows when you tell an agent the same thing twice. Conventions, gotchas, and "why we decided this" end up in one place that every future session reads.

The dashboard's `/memory-map` page draws that knowledge base as a graph.

## Install

Pin a version and use the same one everywhere. The CLI, the hook scripts it installs, and the curation prompts move together, so mixing versions breaks capture or curation quietly.

```bash
# From the repo root. Replace 1.16.1 with the version you pin.
npx kenkeep@1.16.1 init --harnesses claude
```

Record the pinned version in one place that both humans and the nightly retrospector read, and never run `npx kenkeep@latest`. To upgrade, bump the pin and re-run `init --upgrade` in the same commit.

`init` does three things:

1. Creates `.ai/kenkeep/` with `config.yaml`, prompts, and an empty `nodes/` tree.
2. Registers hooks in `.claude/settings.json` (session capture on Stop, SessionEnd and PreCompact; proposal drain on SessionStart; a UserPromptSubmit hook that injects the nodes most relevant to each prompt).
3. Installs the `/kk-add`, `/kk-curate`, `/kk-bootstrap`, `/kk-migrate` and `/kk-session-extract` skills.

Then seed the knowledge base from your existing docs:

```text
/kk-bootstrap
```

## What to commit

| Path | Commit? | Why |
|------|---------|-----|
| `.ai/kenkeep/nodes/**` | Yes | The knowledge itself. Review new nodes like any other change. |
| `.ai/kenkeep/ENTRY.md`, `GRAPH.md`, `FOLDER_SUMMARIES.md` | Yes | Generated catalogs the hooks read. |
| `.ai/kenkeep/config.yaml`, `.config/`, `scripts/` | Yes | Settings and prompts, pinned with the version. |
| `.ai/kenkeep/_sessions/` | No | Raw session transcripts. They can contain client data and credentials pasted into a prompt. |
| `.ai/kenkeep/_logs/` | No | Curation logs. |
| `.ai/kenkeep/hooks/` | No | Vendored hook bundles; `init` reinstalls them. The registrations in `.claude/settings.json` are committed. |

kenkeep writes a `.ai/kenkeep/.gitignore` covering the three ignored paths. Check it is there before your first commit.

## Per-project stores

If each project workspace under `agents/<Project>/` runs its own Claude Code sessions, install kenkeep there too. Knowledge about the codebase goes under a `codebase/` branch of the same store:

```text
.ai/kenkeep/nodes/                              L1  shared knowledge (repo root)
agents/<Project>/.ai/kenkeep/nodes/             L2  that project's workspace
agents/<Project>/.ai/kenkeep/nodes/codebase/    L3  that project's codebase
```

Keep the store in your workspace, not inside a client's code checkout. A store inside someone else's repository puts your notes and raw transcripts one `git add` away from their history.

## How the memory map reads it

`dashboard/kenkeep_data.py` reads the root store plus `agents/<agent_dir>/.ai/kenkeep/nodes/` for every project in `config/projects.yml` whose `status` is not `archived`. It never writes to a store.

- **Colors.** A node in a project store takes that project's color. A root node takes the color of the first tag that matches a project's `kenkeep_tag` (or its lowercased name when `kenkeep_tag` is not set). Nodes whose first project tag belongs to an archived project are hidden.
- **Links.** `kk_relates_to` draws a link within a store. A `from:<source-key>:<node-id>` tag draws a lineage link to a node in another layer, for rollups lifted from a project store to the root. Source keys are `<tag>-workspace` and `<tag>-code`.
- **Schemas.** Both schema 1 (`id`, `kind`, `summary`, `relates_to`) and schema 3 (`kk_id`, `type`, `description`, `kk_relates_to`) frontmatter are read. The stats line reports files skipped for having no readable id.
- **Conflicts.** Pending files in `.ai/kenkeep/conflicts/` are listed under "Needs attention". Resolve them with `/kk-curate` in a Claude Code session.
- **Curation strip.** Reads `dashboard/data/kenkeep-curation-history.jsonl`, one JSON object per night (`date`, `nodes_added`, `added_nodes`, `conflicts`, `pending_signal`), and backfills older days from git add-dates of node files.
- **Scope.** Set `MEMORY_MAP_SCOPE=l1` to show only the root store, for example when the dashboard is reachable by someone who should not see per-project notes.

With no store installed the page shows the example knowledge base in `examples/kenkeep/nodes/`. Delete that directory once you have your own.

## Nightly curation

Curation can run in-session (`/kk-curate`) or on a schedule. The template does not ship a scheduler. If you add a nightly job, have it run curation with the pinned version, append one JSON line per run to `dashboard/data/kenkeep-curation-history.jsonl` (the memory map's curation strip reads it), soft-fail so a kenkeep problem never blocks your other nightly work, and leave new nodes uncommitted for review the next morning.
