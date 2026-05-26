---
title: FRED-VDB Semantic Search
emoji: 📈
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 6.14.0
python_version: "3.12"
app_file: app.py
pinned: false
license: mit
---

# FRED-VDB — Semantic Search over FRED

Semantic search over ~840K FRED (Federal Reserve Economic Data) series.
Describe the data you want in natural language; matching is by meaning, not
keywords. Search runs fully offline — no FRED API key required.

The prebuilt vector index is loaded from a HF Dataset at startup (set the
`INDEX_DATASET` Space variable). Source: <your GitHub repo>.
