---
type: practice
title: Group data per project when feeding it to an LLM
description: >-
  Never mix two projects' data in one prompt section; label each block with its project.
tags:
  - project-alpha
  - project-beta
  - isolation
kk_schema_version: 3
kk_id: practice-keep-projects-apart
kk_relates_to:
  - practice-read-context-before-acting
kk_confidence: medium
---
When a PM carries several projects, the expensive mistakes come from one project's context leaking into another's output. Build prompts with one clearly labelled section per project.
