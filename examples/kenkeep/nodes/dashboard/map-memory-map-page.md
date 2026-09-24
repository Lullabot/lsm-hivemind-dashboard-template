---
type: map
title: /memory-map page
description: >-
  Force-directed graph of the kenkeep knowledge base, read-only, with a nightly curation strip.
tags:
  - dashboard
  - project-alpha
  - kenkeep
kk_schema_version: 3
kk_id: map-memory-map-page
kk_relates_to:
  - map-web-dashboard
kk_confidence: medium
---
Reads `.ai/kenkeep/nodes/` at the repo root and any `agents/<Project>/.ai/kenkeep/nodes/` store. Nodes tagged with a project's `kenkeep_tag` take that project's color.
