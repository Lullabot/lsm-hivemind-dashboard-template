"""kenkeep knowledge-base graph for the /memory-map page.

kenkeep (https://github.com/e0ipso/kenkeep) keeps a git-tracked knowledge base
of typed markdown nodes under ``.ai/kenkeep/nodes/``. This module reads one or
more of those stores and turns them into a node/link graph the memory map can
draw. It never writes to a store.

Layers:

    L1  <repo>/.ai/kenkeep/nodes/                         shared knowledge
    L2  agents/<agent_dir>/.ai/kenkeep/nodes/             one project workspace
    L3  agents/<agent_dir>/.ai/kenkeep/nodes/codebase/    that project's codebase

L2 and L3 live in the same store and are told apart by the ``codebase/``
branch, so every L2 source excludes its own ``codebase/`` subtree. A missing
store contributes nothing, so the map works with only the root installed.

When no store exists at all, the page falls back to the small example store in
``examples/kenkeep/nodes/`` so it renders something on first boot.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path

import config

REPO_ROOT = config.REPO_ROOT
EXAMPLE_NODES = REPO_ROOT / "examples" / "kenkeep" / "nodes"
CURATION_HISTORY_JSONL = REPO_ROOT / "dashboard" / "data" / "kenkeep-curation-history.jsonl"
KENKEEP_CODE_BRANCH = "codebase"


def _agents_dir() -> Path:
    return config.load()["paths"]["agents"]


def _project_tag(p: dict) -> str:
    return (p.get("kenkeep_tag") or p["name"]).lower()


def _active_projects() -> list[dict]:
    return [p for p in config.load()["projects"] if p.get("status", "active") != "archived"]


def _archived_tags() -> set[str]:
    return {_project_tag(p) for p in config.load()["projects"]
            if p.get("status", "active") == "archived"}


def _tag_to_project() -> dict[str, str]:
    return {_project_tag(p): p["name"] for p in _active_projects()}


def kenkeep_sources(root: Path | None = None, agents_dir: Path | None = None) -> list[dict]:
    """Return every store the memory map should read.

    Honors ``MEMORY_MAP_SCOPE=l1`` to restrict the map to the root store, which
    is the safe setting whenever the dashboard is reachable by someone who
    should not see per-project knowledge.
    """
    root = root or REPO_ROOT
    agents_dir = agents_dir or _agents_dir()
    sources = [{"layer": "L1", "source_key": "root", "project": None,
                "path": root / ".ai" / "kenkeep" / "nodes"}]
    if os.environ.get("MEMORY_MAP_SCOPE", "all").strip().lower() != "l1":
        slug_to_dir = config.load()["slug_to_agent_dir"]
        for p in _active_projects():
            nodes = agents_dir / slug_to_dir.get(p["name"], p["name"]) / ".ai" / "kenkeep" / "nodes"
            key = _project_tag(p)
            sources.append({"layer": "L2", "source_key": f"{key}-workspace", "project": p["name"],
                            "path": nodes, "exclude": [nodes / KENKEEP_CODE_BRANCH]})
            sources.append({"layer": "L3", "source_key": f"{key}-code", "project": p["name"],
                            "path": nodes / KENKEEP_CODE_BRANCH})
    if not any(s["path"].exists() for s in sources) and EXAMPLE_NODES.exists():
        return [{"layer": "L1", "source_key": "example", "project": None,
                 "path": EXAMPLE_NODES, "example": True}]
    return sources


# kenkeep frontmatter key spellings, newest first. Schema 3 renamed the fields
# this parser depends on (id -> kk_id, kind -> type, summary -> description,
# relates_to -> kk_relates_to). Reading both keeps mixed-schema stores working
# while they migrate one at a time.
KENKEEP_SCALAR_ALIASES = {"id": ("kk_id", "id"), "kind": ("type", "kind"),
                          "title": ("title",)}
KENKEEP_FOLDED_ALIASES = {"summary": ("description", "summary")}
KENKEEP_LIST_ALIASES = {"tags": ("tags",),
                        "relates_to": ("kk_relates_to", "relates_to")}

_FOLD_MARKERS = (">-", ">", "|", "|-")


def _parse_kenkeep_frontmatter(fm: str) -> dict:
    """Parse a node's simple YAML frontmatter into schema-1 field names.

    Handles scalars, ``- item`` / ``[]`` lists, and folded ``>-`` blocks that
    continue on indented lines (kenkeep folds long ids and descriptions).
    """
    list_keys = {a: f for f, aliases in KENKEEP_LIST_ALIASES.items() for a in aliases}
    folded_keys = {a: f for f, aliases in KENKEEP_FOLDED_ALIASES.items() for a in aliases}
    scalar_keys = {a: f for f, aliases in KENKEEP_SCALAR_ALIASES.items() for a in aliases}

    raw: dict = {}
    lines = fm.splitlines()
    i = 0
    while i < len(lines):
        key, sep, rest = lines[i].strip().partition(":")
        if not sep:
            i += 1
            continue
        rest = rest.strip()

        if key in list_keys:
            vals, j = [], i + 1
            while j < len(lines) and lines[j].lstrip().startswith("- "):
                vals.append(lines[j].lstrip()[2:].strip().strip("'\""))
                j += 1
            raw[key] = vals
            i = j
            continue

        if key in folded_keys or key in scalar_keys:
            if rest in _FOLD_MARKERS:
                parts, j = [], i + 1
                while j < len(lines) and lines[j].startswith("  ") and lines[j].strip():
                    parts.append(lines[j].strip())
                    j += 1
                # A wrapped id rejoins without spaces; wrapped prose keeps them.
                joiner = " " if key in folded_keys or any(" " in p for p in parts) else ""
                raw[key] = joiner.join(parts)
                i = j
                continue
            raw[key] = rest.strip("'\"")
        i += 1

    meta = {}
    for field, aliases in list(KENKEEP_SCALAR_ALIASES.items()) + list(KENKEEP_FOLDED_ALIASES.items()):
        meta[field] = next((raw[a] for a in aliases if raw.get(a)), "")
    for field, aliases in KENKEEP_LIST_ALIASES.items():
        meta[field] = next((raw[a] for a in aliases if raw.get(a)), [])
    return meta


def _kenkeep_md_to_html(text: str, *, headings: bool = False) -> str:
    """Minimal markdown -> HTML for node bodies. Escapes HTML first."""
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def inline(s):
        s = esc(s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        return s

    # kenkeep appends generated Related/Citations blocks; the panel shows
    # relations itself, so drop them.
    text = re.sub(r"<!-- kk:(\w+):start -->.*?<!-- kk:\1:end -->", "", text, flags=re.DOTALL)
    if headings:
        text = re.sub(r"(?m)^(#{1,6})[ \t]+([^\n]+)$", r"\n\n\1 \2\n\n", text)
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        heading = re.fullmatch(r"#{1,6}[ \t]+(.+)", lines[0]) if headings and len(lines) == 1 else None
        if heading:
            out.append("<h3>" + inline(heading[1]) + "</h3>")
        elif all(ln.lstrip().startswith("- ") for ln in lines):
            out.append("<ul>" + "".join("<li>" + inline(ln.lstrip()[2:]) + "</li>" for ln in lines) + "</ul>")
        else:
            out.append("<p>" + inline(" ".join(lines)) + "</p>")
    return "".join(out)


def _iter_node_files(entry: dict):
    src = entry["path"]
    if not src.exists():
        return
    excluded = list(entry.get("exclude", []))
    for path in sorted(src.rglob("*.md")):
        # index.md files are kenkeep's generated branch catalogs, not nodes.
        if path.name == "index.md" or any(path.is_relative_to(ex) for ex in excluded):
            continue
        yield path


def _parse_one_kenkeep_source(entry: dict):
    """Parse one store into ``(nodes, relates_edges, skipped)``.

    Graph ids are namespaced ``<layer>:<source_key>:<orig_id>`` so the same id
    in two stores stays two nodes. ``relates_to`` resolves only within the
    store. ``skipped`` counts files with no readable id, which usually means a
    frontmatter schema this parser does not know.
    """
    layer, skey = entry["layer"], entry["source_key"]
    nodes, relates, skipped = [], [], 0

    def gid(orig):
        return f"{layer}:{skey}:{orig}"

    raw = []
    for path in _iter_node_files(entry):
        text = path.read_text()
        m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, flags=re.DOTALL)
        fm, body = (m.group(1), m.group(2)) if m else ("", text)
        meta = _parse_kenkeep_frontmatter(fm)
        if not meta["id"]:
            skipped += 1
            continue
        meta["body_html"] = _kenkeep_md_to_html(body)
        raw.append(meta)

    tag_to_project = _tag_to_project()
    archived = _archived_tags()
    colors = config.load()["project_colors"]
    local_ids = {n["id"] for n in raw}
    for n in raw:
        orig = n["id"]
        # A node's primary project is its first tag that names a project. Hide
        # nodes whose primary project is archived.
        primary = next((t for t in n["tags"] if t in tag_to_project or t in archived), None)
        if primary in archived:
            continue
        rel_local = [r for r in n["relates_to"] if r in local_ids and r != orig]
        project = entry.get("project") or tag_to_project.get(primary)
        nodes.append({
            "id": gid(orig),
            "orig_id": orig,
            "layer": layer,
            "source": skey,
            "title": n["title"],
            "kind": n["kind"],
            "tags": n["tags"],
            "summary": n["summary"],
            "body_html": n["body_html"],
            "relates_to": [gid(r) for r in rel_local],
            "project": project,
            "color": colors.get(project) if project else None,
            # Lineage tags: from:<source-key>:<orig-id> points at the node in a
            # child layer that a rollup was lifted from.
            "_from": [t[len("from:"):] for t in n["tags"] if t.startswith("from:")],
        })
        for r in rel_local:
            relates.append({"source": gid(orig), "target": gid(r)})
    return nodes, relates, skipped


def parse_kenkeep_nodes(sources: list[dict] | None = None) -> dict:
    """Aggregate stores into ``{nodes, links, projects, stats}`` for the map.

    Links carry a ``class``: ``relates`` (within a store) or ``lineage``
    (a ``from:`` tag pointing at a node in another layer).
    """
    if sources is None:
        sources = kenkeep_sources()
    example = any(s.get("example") for s in sources)
    installed = any(s["path"].exists() for s in sources)

    all_nodes, relates, skipped = [], [], 0
    for entry in sources:
        ns, rs, sk = _parse_one_kenkeep_source(entry)
        all_nodes.extend(ns)
        relates.extend(rs)
        skipped += sk

    empty_stats = {"total": 0, "map": 0, "practice": 0, "agents": 0, "edges": 0,
                   "lineage": 0, "sources": 0, "layers": {"L1": 0, "L2": 0, "L3": 0},
                   "skipped": skipped, "installed": installed, "example": example}
    if not all_nodes:
        return {"nodes": [], "links": [], "projects": [], "stats": empty_stats}

    node_ids = {n["id"] for n in all_nodes}
    seen, links = set(), []
    for e in relates:
        if e["source"] not in node_ids or e["target"] not in node_ids:
            continue
        key = tuple(sorted((e["source"], e["target"])))
        if key not in seen:
            seen.add(key)
            links.append({"source": key[0], "target": key[1], "class": "relates"})

    src_layer = {e["source_key"]: e["layer"] for e in sources}
    lseen, lineage = set(), []
    for n in all_nodes:
        for ref in n.get("_from", []):
            skey, _, orig = ref.rpartition(":")
            if skey not in src_layer or not orig:
                continue
            child = f"{src_layer[skey]}:{skey}:{orig}"
            if child not in node_ids or child == n["id"]:
                continue
            key = tuple(sorted((n["id"], child)))
            if key not in lseen:
                lseen.add(key)
                lineage.append({"source": n["id"], "target": child, "class": "lineage"})

    deg = defaultdict(int)
    for link in links:
        deg[link["source"]] += 1
        deg[link["target"]] += 1
    for n in all_nodes:
        n["deg"] = deg.get(n["id"], 0)
        n.pop("_from", None)

    colors = config.load()["project_colors"]
    present = {n["project"] for n in all_nodes if n["project"]}
    projects = [{"name": p, "color": c} for p, c in colors.items() if p in present]

    layers = {"L1": 0, "L2": 0, "L3": 0}
    for n in all_nodes:
        layers[n["layer"]] += 1

    return {
        "nodes": all_nodes,
        "links": links + lineage,
        "projects": projects,
        "stats": {
            **empty_stats,
            "total": len(all_nodes),
            "map": sum(1 for n in all_nodes if n["kind"] == "map"),
            "practice": sum(1 for n in all_nodes if n["kind"] == "practice"),
            "agents": len(projects),
            "edges": len(links),
            "lineage": len(lineage),
            "sources": len({n["source"] for n in all_nodes}),
            "layers": layers,
        },
    }


def _slug_to_id(sources: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for entry in sources:
        for path in _iter_node_files(entry):
            out.setdefault(path.stem, f"{entry['layer']}:{entry['source_key']}:{path.stem}")
    return out


def _resolve_curation_items(slugs, lookup, known_ids=None):
    seen, items = set(), []
    for s in slugs:
        if not s or s == "index" or s in seen:
            continue
        seen.add(s)
        nid = lookup.get(s)
        present = bool(nid) and (nid in known_ids if known_ids is not None else True)
        items.append({"slug": s, "id": nid, "present": present})
    return items


def _git_added_nodes_by_date(days: int) -> dict[str, list[str]]:
    """Commit date -> node slugs first added in that commit. Best-effort."""
    added: dict[str, list[str]] = defaultdict(list)
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "log", f"--since={days} days ago",
             "--diff-filter=A", "--name-only", "--no-renames",
             "--pretty=format:COMMIT %cd", "--date=short", "--", "*.ai/kenkeep/nodes/*.md"],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return added
    cur = None
    for line in out.splitlines():
        if line.startswith("COMMIT "):
            cur = line[7:].strip()
        elif cur and line.strip().endswith(".md"):
            added[cur].append(line.strip().rsplit("/", 1)[-1][:-3])
    return added


def parse_kenkeep_curation_history(sources: list[dict] | None = None, days: int = 45,
                                   limit: int = 40, known_ids=None,
                                   history_path: Path | None = None) -> list[dict]:
    """Per-day curation activity for the strip under the map, newest first.

    Reads ``dashboard/data/kenkeep-curation-history.jsonl`` (one JSON object
    per night, written by the retrospector's kenkeep phase) and backfills
    older days from git add-dates of node files. The JSONL wins on any date it
    covers. ``status`` is ``added`` or ``ran-empty``: a night that curated
    nothing leaves no node to draw, so the strip is the only place it shows.
    """
    sources = sources if sources is not None else kenkeep_sources()
    history_path = history_path or CURATION_HISTORY_JSONL
    lookup = _slug_to_id(sources)
    by_date = {}
    for d, slugs in _git_added_nodes_by_date(days).items():
        items = _resolve_curation_items(slugs, lookup, known_ids)
        by_date[d] = {"date": d, "nodes_added": len(items), "added_nodes": items,
                      "conflicts": None, "pending": None, "source": "git"}
    if history_path.exists():
        for line in history_path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            d = rec.get("date")
            if not d:
                continue
            slugs = rec.get("added_nodes") or []
            n_added = int(rec.get("nodes_added", len(slugs)) or 0)
            if slugs:
                items = _resolve_curation_items(slugs, lookup, known_ids)
                n_added = len(items)
            elif n_added > 0:
                items = by_date.get(d, {}).get("added_nodes", [])
            else:
                items = []
            by_date[d] = {"date": d, "nodes_added": n_added, "added_nodes": items,
                          "conflicts": rec.get("conflicts"),
                          "pending": rec.get("pending_signal", rec.get("pending")),
                          "source": "capture"}
    records = sorted(by_date.values(), key=lambda r: r["date"], reverse=True)
    for r in records:
        r["status"] = "added" if r["nodes_added"] > 0 else "ran-empty"
    return records[:limit]


def parse_kenkeep_review(sources: list[dict], nodes: list[dict]) -> dict:
    """List pending conflict files, read-only.

    kenkeep writes a file to ``<store>/conflicts/`` when curation finds a
    proposal that contradicts an existing node, and waits for a human. The
    page lists them so they are not forgotten; resolve them with
    ``/kk-curate`` in a Claude Code session.
    """
    conflicts, unavailable, seen = [], [], set()
    for source in sources:
        if source["layer"] == "L3":
            continue
        store = Path(source["path"]).parent
        if store in seen:
            continue
        seen.add(store)
        try:
            for path in sorted((store / "conflicts").glob("*.md")):
                if path.is_symlink():
                    continue
                parts = path.read_text().split("---", 2)
                if len(parts) != 3 or parts[0].strip():
                    unavailable.append(path.name)
                    continue

                def field(name, fm=parts[1]):
                    m = re.search(r"^" + name + r":(.*(?:\n[ \t]+[^\n]*)*)", fm, re.M)
                    return _parse_kenkeep_frontmatter("title:" + m[1])["title"] if m else ""

                if field("status") != "pending":
                    continue
                target = field("target_node_id")
                matches = [n for n in nodes if n.get("orig_id") == target
                           and (n.get("source") == source["source_key"]
                                or (source.get("project") and n.get("project") == source["project"]))]
                conflicts.append({
                    "title": field("proposed_title") or path.stem,
                    "detected_at": field("detected_at"),
                    "project": source.get("project"),
                    "source": str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else path.name,
                    "body": parts[2].strip(),
                    "body_html": _kenkeep_md_to_html(parts[2], headings=True),
                    "target": target,
                    "target_id": matches[0]["id"] if len(matches) == 1 else None,
                })
        except (OSError, UnicodeError):
            unavailable.append(source["source_key"])
    return {"conflicts": sorted(conflicts, key=lambda c: c["detected_at"], reverse=True),
            "unavailable": unavailable}


def get_memory_map() -> dict:
    """Everything /api/memory-map returns."""
    sources = kenkeep_sources()
    payload = parse_kenkeep_nodes(sources)
    payload["review"] = parse_kenkeep_review(sources, payload["nodes"])
    payload["curation"] = parse_kenkeep_curation_history(
        sources, known_ids={n["id"] for n in payload["nodes"]})
    return payload
