# Deploying FRED-VDB to Hugging Face Spaces

The search demo is fully offline — **no FRED API key is needed or used.** The
only artifact to ship is the 118 MB vector index (NOT the 1.5 GB ingest state DB).

## One-time setup

### 1. Push the source to GitHub (public)

The Space installs `fred_search` from your repo. Make sure `data/` stays
gitignored, then update the repo URL in `requirements.txt`.

### 2. Upload the index as a HF Dataset

The index is a directory (`data/fred_vector_index/`). Upload it so the Dataset
repo root contains a `fred_vector_index/` folder:

```bash
pip install huggingface_hub
huggingface-cli login
huggingface-cli upload --repo-type dataset \
  YOUR_HF_USERNAME/fred-vector-index \
  data/fred_vector_index fred_vector_index
```

> Do **not** upload `data/fred_ingest_state.db` — it's ingestion bookkeeping
> the demo doesn't use, and it's ~1.5 GB.

### 3. Create the Space

- New Space → SDK: **Gradio** → CPU basic (free).
- Push the **contents of this `space/` directory** to the Space repo
  (`app.py`, `requirements.txt`, `README.md`).
- In the Space **Settings → Variables**, set:
  - `INDEX_DATASET = YOUR_HF_USERNAME/fred-vector-index`
- No secrets needed.

## How it boots

1. `requirements.txt` installs `fred_search` from GitHub + runtime deps.
2. `app.py` calls `snapshot_download(...)` to fetch + cache the index.
3. `FREDSearcher` loads the index + `all-MiniLM-L6-v2` model **once** (~few sec).
4. Each query is then the ~50 ms vector scan.

## Local test before pushing

```bash
INDEX_DATASET=... python space/app.py   # or just run against ./data locally
```
