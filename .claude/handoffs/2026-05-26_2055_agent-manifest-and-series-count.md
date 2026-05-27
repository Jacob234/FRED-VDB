---
handoff_id: 2026-05-26_2055
title: "Agent-Facing API Customization & Series-Count Correction for the FRED-VDB Space"
date: 2026-05-26T20:55:02-04:00
parent_handoffs:
  - .claude/handoffs/2026-05-25_2342_hf-spaces-deployment.md
status: active
---

# Handoff: Agent-Facing API Customization & Series-Count Correction

## Session Overview

**Date**: 2026-05-26
**Primary Goal**: Test the deployed Space's `agents.md`, decide how to "customize the manifest," and prepare the agent-facing API surface. Mid-session, caught and corrected a long-standing wrong series count (~840K → 33K).

**Outcome**: Space copy + API surface improved and **committed (`4739b92`)** — but **NOT yet deployed** to the live Space (the deploy push was blocked by Claude Code's permission classifier; user has not re-authorized it).

## What Was Accomplished

- **Tested the live Space** — `agents.md` returns **HTTP 200** (627 B, `text/plain`), *not* the 404 the parent handoff predicted. HF **auto-generates** an agent manifest for every Gradio Space (4 lines: schema URL / call template / poll template / auth). A bogus `.md` path 404s, confirming `agents.md` is a real, selective endpoint. `/gradio_api/info` resolves with a typed `/search` endpoint. Documented at https://huggingface.co/docs/hub/spaces-agents.
- **Determined `agents.md` is not directly authorable** — there's no documented repo-file override. The two things an agent actually consumes *are* controllable: (1) the manifest's description line (via the Space card `short_description`), and (2) the `/gradio_api/info` schema (via `api_name` / `api_visibility` / `api_description` in `app.py`).
- **Cleaned the agent-facing API surface** in `space/app.py`:
  - Collapsed the duplicate endpoint — there were `/search` *and* `/search_1` because the handler is bound to both `search_btn.click` and `query_box.submit`. Marked the submit handler `api_visibility="private"` (Gradio 6 replacement for the removed `show_api` / `api_name=False`) so Enter-to-search still works in-UI but no longer mints a 2nd API endpoint.
  - Named the canonical endpoint `api_name="search"`.
  - Added a rich `api_description` (the LLM-facing tool doc) including an explicit caveat that the ranking is a similarity heuristic, not an authoritative answer — the agent should read across the top 10 and use judgment (or re-query).
  - Added `short_description` to `space/README.md` front matter (drives the manifest's description line; was unset, so HF auto-summarized it).
- **Validated against the real pin** (`gradio==6.14.0`, throwaway venv, no index): both `api_visibility` and `api_description`/`api_name` are accepted, and `demo.get_api_info()` confirms a **single** `/search` endpoint carrying the description. (Caught here: pre-6 idiom `api_name=False` would have errored — exactly the kind of pin gotcha the parent handoff warned about.)
- **Corrected the series count everywhere it was overstated.** The searchable index holds **33,230** curated series (`t.count_rows()` on the LanceDB table) — a filtered subset of FRED's ~840K *raw* catalog (840,376 fetched into `fred_ingest_state.db`, filtered down at index time). The "~840K searchable" claim was misleading. Fixed in `space/app.py`, `space/README.md`, top-level `README.md:3`, and `.claude/commands/fred-lookup.md:7`. Left the *accurate* ~840K mentions alone (raw catalog, state DB, FRED-as-context).

## Key Decisions & Context

### Decision 1: "Customize the manifest" = shape the generator inputs, not author a file
**Context**: User chose "customize the manifest," conditioned on verifying overridability.
**Decision**: Since HF auto-generates `agents.md` with no override, customize the two consumable surfaces: `short_description` (manifest line) + the `/gradio_api/info` schema (`api_name`/`api_visibility`/`api_description`).
**Rationale**: Those are the only levers, and they're the right ones — they're what an agent reads at step 1 (manifest) and step 2 (schema) of the documented flow.

### Decision 2: Use `api_visibility="private"`, not `api_name=False`
**Context**: Gradio 6.x removed `show_api` and dropped `api_name=False`.
**Decision**: `api_visibility` (public / undocumented / private) is the 6.x replacement; "private" hides the submit handler from the API schema while leaving the in-UI behavior intact.
**Rationale**: Verified accepted + effective against the pinned `gradio==6.14.0`.

### Decision 3: Encode the ranker's limits into the tool contract
**Context**: User asked to tell agents the ranker isn't perfect and to use judgment across the top 10.
**Decision**: Appended that guidance to `api_description`.
**Rationale**: Honest tool-contract design — the calling agent treats output as ranked candidates needing judgment, with re-query as a recovery move.

## Current State

### Files Modified (committed `4739b92`)
- [space/app.py](../../space/app.py) — `api_name`/`api_visibility` dedup, rich `api_description`, 33K copy
- [space/README.md](../../space/README.md) — `short_description` added; body → 33K curated
- [README.md](../../README.md) — line 3 → 33K curated (filtered from ~840K)
- [.claude/commands/fred-lookup.md](../../.claude/commands/fred-lookup.md) — line 7 → 33K curated

### System State
- Live Space `Jacob235/fred-vdb`: still serving the **pre-edit** version (deploy not done). `agents.md` + `/search` work; manifest line is HF's auto-summary; schema still shows `/search` + `/search_1`.
- Session edits **committed locally** (`4739b92`) but **not pushed to GitHub** and **not deployed to the Space**.
- `HF_TOKEN` is set in the shell (fine-grained, `Jacob235`, write scope — verified via `whoami`). `huggingface_hub` 1.6.0 lives in `.venv`.
- `space/_build/` still holds the **stale** pre-edit copies — must be re-synced from source before any `upload_folder`. (For this redeploy, only `app.py` + `README.md` changed, so a 2-file `create_commit` avoids `_build` entirely.)

### Next Steps
1. **Deploy the two changed files** to the Space (was blocked). Single commit via `huggingface_hub`:
   ```python
   from huggingface_hub import HfApi, CommitOperationAdd
   import os
   HfApi(token=os.environ["HF_TOKEN"]).create_commit(
       repo_id="Jacob235/fred-vdb", repo_type="space",
       operations=[CommitOperationAdd("app.py","space/app.py"),
                   CommitOperationAdd("README.md","space/README.md")],
       commit_message="agent API: clean /search endpoint, rich api_description, 33K count, short_description")
   ```
   This is a **production deploy** — needs explicit user authorization (the classifier gates it separately from content edits).
2. **After deploy, re-verify**: `curl .../agents.md` (new 33K description line), `curl .../gradio_api/info` (single `/search`, with `api_description`). Watch the three pinned gotchas before touching any pins (see parent handoff).
3. `git push origin main` to publish `4739b92` (user pushed `a170b51` this session; `4739b92` is local-only).
4. **Open product question (user-raised)**: "should we get a more official bit of the dataset onto HF?" — i.e., expand the searchable index beyond the 33K curated subset. See Open Questions.

## Context from Parent Handoffs

### From [HF Spaces Deployment](.claude/handoffs/2026-05-25_2342_hf-spaces-deployment.md)
- FRED-VDB is live on HF Spaces (`Jacob235/fred-vdb`, Gradio 6.14.0, py3.12), index hosted as public dataset `Jacob235/fred-vector-index`.
- Deploy source in `space/`; redeploys go through local `HF_TOKEN` via `huggingface_hub` (the HF MCP is read-only). Three pin gotchas: lance/symlinks (use `local_dir`), py3.13/audioop (pin 3.12), gradio/HfFolder (pin gradio 6.14.0).
- That handoff's prediction that `agents.md` would 404 was **wrong** — corrected this session.

## Suggested Child Handoffs

### Child Handoff 1: Deploy + verify the agent-API changes
**Focus**: Push `app.py`+`README.md` to the Space, confirm the new manifest line and single `/search` endpoint, optionally smoke-test an end-to-end agent call.
**Prerequisites**: User authorizes the production deploy; `HF_TOKEN` in env.
**Expected Outcome**: Live Space reflects 33K copy + clean agent API.

### Child Handoff 2: Expand / "officialize" the HF dataset
**Focus**: Decide whether to index more of FRED's ~840K catalog (loosen the popularity/quality filter — see parent's `--liberal` idea), re-embed, and re-upload the dataset; add a dataset card documenting coverage, filter criteria, embedding model, and snapshot date.
**Prerequisites**: Decide target coverage and refresh cadence; FRED API key for re-ingest.
**Expected Outcome**: A larger and/or better-documented index dataset whose coverage matches the copy.

### Child Handoff 3: Index refresh automation (carried from parent)
**Focus**: Script/GitHub Action to re-ingest + re-upload the index so the demo stays current.

## Open Questions & Issues

1. **User's question — "a more official bit of the dataset onto HF?"** Two readings: (a) *expand coverage* — index more than the 33K curated subset (the filter drops 840K → 33K, which the Mar-14 handoff already flagged as aggressive); (b) *make the dataset more official* — add a proper HF **dataset card** (coverage %, filter criteria, embedding model `all-MiniLM-L6-v2`, snapshot date, license). Both are reasonable; (b) is cheap and high-value regardless, (a) is a bigger ingest/embed/upload job. Needs a decision before work.
2. **Deploy is pending** — content edits are committed but the live Space is unchanged until the gated push runs.
3. `4739b92` is local-only — needs `git push`.

## References
- Live Space: https://huggingface.co/spaces/Jacob235/fred-vdb
- Index dataset: https://huggingface.co/datasets/Jacob235/fred-vector-index
- HF docs — Spaces as Agent Tools: https://huggingface.co/docs/hub/spaces-agents
- Gradio 6 migration (api_visibility): https://github.com/gradio-app/gradio/blob/main/guides/11_other-tutorials/gradio-6-migration-guide.md
- [space/DEPLOY.md](../../space/DEPLOY.md) — deploy runbook
- Memory: `hf-spaces-deployment.md`
- Session commit: `4739b92`

## Technical Notes

### The two numbers (do not conflate again)
- **840,376** = raw series fetched from the FRED API into `data/fred_ingest_state.db`. FRED's near-full catalog.
- **33,230** = series that survived filtering and got embedded into the searchable LanceDB index (`data/fred_vector_index`, table `fred_series`). This is what the demo can return.

### Agent-API mechanics (Gradio 6.14)
- `agents.md` is HF-auto-generated (4 lines); not authorable via a repo file. Description line comes from the Space card `short_description` (else HF auto-summarizes).
- Event-listener API control: `api_name="..."` (endpoint name), `api_visibility` in {public, undocumented, private} (replaces removed `show_api`/`api_name=False`), `api_description` in {None=docstring, False=hide, str=custom}.
- `api_description` lives in `/gradio_api/info` (agent step 2), NOT in the `agents.md` manifest (step 1).

### Deploy mechanics
- Production deploy = `huggingface_hub` `create_commit`/`upload_file` with `HF_TOKEN`; the classifier gates this as outward-facing and needs explicit per-action authorization.
- Don't `git add`/`commit` without a pathspec (concurrent agents write `.git/index`). Hit a transient `index.lock` this session — it cleared on its own (a `git shortlog` from the unrelated `JBK-Research` repo was the only running git proc).

## Next Session Prompt

```
Continue from .claude/handoffs/2026-05-26_2055_agent-manifest-and-series-count.md.

The FRED-VDB Space's agent-facing API was customized and committed (4739b92) but
NOT yet deployed: clean single /search endpoint (api_visibility="private" on the
submit handler — Gradio 6, not api_name=False), a rich api_description telling
agents the ranker is a heuristic to judge, a short_description for the manifest,
and the series count corrected to 33K (searchable index) vs ~840K (FRED's raw
catalog — don't conflate them).

Next: (1) get explicit OK to deploy app.py+README.md to Jacob235/fred-vdb via
huggingface_hub + HF_TOKEN (single create_commit), then re-curl agents.md and
/gradio_api/info to confirm. (2) git push 4739b92. (3) Decide the open dataset
question: expand coverage beyond the 33K subset and/or add a proper HF dataset
card. Watch the three pin gotchas (lance/symlinks, py3.13/audioop, gradio 6.14.0).
```
