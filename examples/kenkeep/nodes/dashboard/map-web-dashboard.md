---
type: map
title: Web dashboard (dashboard/)
description: >-
  Starlette app that renders memory-bank files and cached JSON as pages; it never calls external APIs at request time.
tags:
  - dashboard
kk_schema_version: 3
kk_id: map-web-dashboard
kk_relates_to:
  - map-memory-bank-dashboard-md
  - map-memory-map-page
kk_confidence: medium
---
Fetch scripts write files; the dashboard only reads them. That keeps credentials out of the web tier and keeps pages fast.
