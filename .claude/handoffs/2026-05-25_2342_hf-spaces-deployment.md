---
handoff_id: 2026-05-25_2342
title: "Hugging Face Spaces Deployment of FRED-VDB Search"
date: 2026-05-25T23:42:00-04:00
parent_handoffs:
  - .claude/handoffs/2026-03-15_2200_fetch-cli-and-agent-skill.md
status: completed
---

# Handoff: Hugging Face Spaces Deployment of FRED-VDB Search

## Session Overview

**Date**: 2026-05-25
**Primary Goal**: Make FRED-VDB shareable — stand up a public, no-install demo of the semantic search so anyone can try it.

Outcome: a live public Gradio app on Hugging Face Spaces, backed by the vector index hosted as a separate HF Dataset. Deploy source committed to the repo and pushed to GitHub.

## What Was Accomplished

- **Live demo deployed**: https://huggingface.co/spaces/Jacob235/fred-vdb (Gradio SDK, free CPU, public, `RUNNING`).
- **Index hosted as a dataset**: `Jacob235/fred-vector-index` (public) — the 118 MB LanceDB index, uploaded with `huggingface_hub`.
- **Created `space/` deploy source** (committed `a9519f5`, pushed to GitHub):
  - `space/app.py` — Gradio 6 wrapper: search box + frequency dropdown + popularity-boost toggle. Loads `FREDSearcher` once at module scope. Each result links its series ID to `https://fred.stlouisfed.org/series/{id}`.
  - `space/requirements.txt` — runtime deps (vendored package, no GitHub git-install).
  - `space/README.md` — HF Space config (sdk gradio 6.14.0, python 3.12).
  - `space/DEPLOY.md` — step-by-step deploy runbook.
- **Vendored the `fred_search` package** into the Space (328 KB) instead of git-installing from GitHub — fully self-contained.
- **Added top-level README live-demo link** and gitignored `space/_build/` (generated staging dir).
- **Verified end-to-end against the live Space** via `gradio_client` — search returns correct results with working FRED links.
- **Saved a project memory** (`hf-spaces-deployment.md`) capturing the deployment + the three gotchas.

## Key Decisions & Context

### Decision 1: HF Spaces + HF Dataset split (not Streamlit Cloud, not a VPS)
**Context**: Need a public, no-install demo. The 118 MB index exceeds GitHub's 100 MB file limit, and search is offline/key-free.
**Decision**: Gradio app on HF Spaces; index as a separate HF Dataset fetched at boot.
**Rationale**: Free, public URL, no FRED API key needed for search (zero credential surface). HF Dataset sidesteps the 100 MB git limit cleanly.
**Alternatives**: Streamlit Community Cloud (deploys from GitHub → fights the 100 MB limit, needs LFS); Fly.io/Render (paid, needless infra).

### Decision 2: Vendor the package, don't git-install it
**Context**: `requirements.txt` could install `fred_search` from GitHub, but that requires the repo public + current.
**Decision**: Copy the 328 KB `fred_search/` into the Space via a `space/_build/` staging dir.
**Rationale**: Self-contained, no external git dependency, deploys regardless of GitHub state.

### Decision 3: Dataset stays public
**Context**: User asked to keep the index dataset public.
**Decision**: `Jacob235/fred-vector-index` is public. (FRED metadata is public-domain; no secrets.)

## Current State

### Files Modified / Created (committed `a9519f5`, pushed)
- [space/app.py](../../space/app.py) — Gradio 6 search app with FRED series links
- [space/requirements.txt](../../space/requirements.txt) — pinned `gradio==6.14.0`, `huggingface_hub>=0.33.5`
- [space/README.md](../../space/README.md) — Space config: `sdk_version: 6.14.0`, `python_version: "3.12"`
- [space/DEPLOY.md](../../space/DEPLOY.md) — deploy runbook
- [README.md](../../README.md) — added 🤗 live-demo link
- [.gitignore](../../.gitignore) — ignores `space/_build/`

### System State
- Space `Jacob235/fred-vdb`: **RUNNING**, search verified working, series links verified.
- Dataset `Jacob235/fred-vector-index`: **public**, 124 MB uploaded.
- `main` pushed to `github.com/Jacob234/FRED-VDB` (`1476fb5..a9519f5`).
- `space/_build/` exists locally (gitignored) — regenerate with the `rsync` step in `space/DEPLOY.md` / session history if needed.

### Next Steps
1. **Test the live Space** as the user requested: `curl https://huggingface.co/spaces/Jacob235/fred-vdb/agents.md` (verify what the Space serves at that path; note that HF Spaces may not serve an `agents.md` by default — confirm intent and whether an agent manifest should be added).
2. Optional: re-deploy flow is documented — change `space/app.py`, `cp` into `space/_build/`, `upload_file`/`upload_folder` via `huggingface_hub` with `HF_TOKEN`.

## Context from Parent Handoffs

### From [Fetch CLI & Agent Skill](.claude/handoffs/2026-03-15_2200_fetch-cli-and-agent-skill.md)
- FRED-VDB is a semantic-search CLI over ~840K FRED series; `FREDSearcher` (in `fred_search/search.py`) is the core API, opening a LanceDB index at `data_dir/fred_vector_index` and embedding queries with `all-MiniLM-L6-v2`.
- Search is offline/local; only ingest/fetch need the FRED API key.
- Between that handoff and this session, a security campaign redacted a leaked FRED key and added gitleaks + a hookify rule (commits `dcb0531`..`c4076a7`).

## Suggested Child Handoffs

### Child Handoff 1: Space verification & agent-manifest
**Focus**: Run the `curl .../agents.md` test; decide whether to add an agent-readable manifest or API docs to the Space; harden first-boot UX (cold-start spinner, error messaging if dataset fetch fails).
**Prerequisites**: Space is RUNNING (it is).
**Expected Outcome**: Confirmed external reachability + a decision on agent-facing endpoints.

### Child Handoff 2: Index refresh automation
**Focus**: A GitHub Action (or script) that re-runs ingest and re-uploads the index to the HF Dataset, so the demo stays current as FRED data updates.
**Prerequisites**: Decide refresh cadence; FRED API key available as a secret.
**Expected Outcome**: One-command (or scheduled) index refresh → dataset upload.

## Open Questions & Issues

1. What should `https://huggingface.co/spaces/Jacob235/fred-vdb/agents.md` return? HF Spaces don't serve a custom `agents.md` by default — is the goal to expose an agent manifest, or just to confirm the Space responds?
2. Index staleness: the deployed index is a point-in-time snapshot; no refresh mechanism yet.

## Technical Notes

### The three deployment gotchas (each caused a RUNTIME_ERROR, fixed in order)
1. **LanceDB cannot open its table through HF's snapshot symlink layout** (`lance error: file size is too small`). HF `snapshot_download` defaults to symlinks-into-`blobs/`; lance does its own dir-walk + mmap and breaks. **Fix**: `snapshot_download(..., local_dir=...)` to materialize real files.
2. **`audioop` removed in Python 3.13** → breaks gradio→pydub import. **Fix**: pin `python_version: "3.12"` in the Space README YAML (matches the project's `.python-version`).
3. **gradio 4.x imports the removed `huggingface_hub.HfFolder`**, colliding with the hf_hub 1.x that `sentence-transformers` pulls. **Fix**: `gradio==6.14.0` (requires hf_hub `>=0.33.5,<2.0`). Validated UI + import in a throwaway venv before deploying.

### Deploy mechanics
- Redeploys go through the local `hf` CLI auth (`HF_TOKEN` env var — fine-grained, `repo.write` scoped to Jacob235).
- The HF **MCP** tools are read/discover/invoke-only — they CANNOT create Spaces or upload files. Deployment used `huggingface_hub` (`HfApi.create_repo`, `upload_folder`, `upload_file`) locally.
- **Read Space crash logs**: `GET https://huggingface.co/api/spaces/{repo}/logs/run` as SSE, with `follow_redirects=True` and the user bearer token. (The `api.hf.space` JWT route returns 401.)
- `fred_search/__init__.py` eagerly imports `fetch`/`ingest`, so importing `FREDSearcher` pulls in `httpx` + `numpy` at import time — both must be in the Space requirements even though search never calls them.

### Dependencies (Space)
- gradio==6.14.0, huggingface_hub>=0.33.5, lancedb>=0.13, sentence-transformers>=3.0, pyarrow>=16.0, pandas>=2.0, httpx>=0.27, numpy>=1.26
- Python 3.12

## References
- Live Space: https://huggingface.co/spaces/Jacob235/fred-vdb
- Index dataset: https://huggingface.co/datasets/Jacob235/fred-vector-index
- [space/DEPLOY.md](../../space/DEPLOY.md) — deploy runbook
- Memory: `hf-spaces-deployment.md`
- Session commit: `a9519f5`

## Next Session Prompt

```
Continue from .claude/handoffs/2026-05-25_2342_hf-spaces-deployment.md.

FRED-VDB is now deployed to HF Spaces (Jacob235/fred-vdb, RUNNING) with the
index hosted as the public dataset Jacob235/fred-vector-index. Deploy source
is in space/ (committed a9519f5, pushed). Redeploys go through the local
HF_TOKEN via huggingface_hub; the HF MCP is read-only.

Next: run `curl https://huggingface.co/spaces/Jacob235/fred-vdb/agents.md`
to test the Space, and clarify what that path should return (HF Spaces don't
serve agents.md by default — decide whether to add an agent manifest). Watch
the three deployment gotchas documented in the handoff (lance/symlinks,
py3.13/audioop, gradio/HfFolder) before changing any pins.
```
