"""
Hugging Face Space entrypoint for FRED-VDB semantic search.

This is a thin Gradio wrapper around fred_search.FREDSearcher. All the real
work lives in the package; this file only:
  1. Downloads the prebuilt 118 MB LanceDB vector index from a HF Dataset.
  2. Instantiates ONE FREDSearcher at module load (model + index loaded once).
  3. Exposes a search box + frequency dropdown + popularity-boost toggle.

Search is fully offline at request time — no FRED API key is needed or used.
"""

from __future__ import annotations

import os
from pathlib import Path

import gradio as gr
from huggingface_hub import snapshot_download

from fred_search import FREDSearcher
from fred_search.models import FREDSearchResult

# ---------------------------------------------------------------------------
# 1. Fetch the prebuilt index from a HF Dataset.
#
# Upload data/fred_vector_index/ to a HF Dataset whose repo root contains a
# `fred_vector_index/` folder, then set this to "<username>/<dataset-name>".
# snapshot_download caches it, so this is a no-op after the first cold boot.
# ---------------------------------------------------------------------------
INDEX_DATASET = os.environ.get("INDEX_DATASET", "Jacob235/fred-vector-index")

# NOTE: must use local_dir to get REAL files, not the default cache symlinks.
# LanceDB does its own directory traversal + mmap over its multi-file table and
# cannot open it through HF's symlink-into-blobs snapshot layout (it fails with
# "lance error: file size is too small"). local_dir writes real copies.
_index_root = Path(
    snapshot_download(
        repo_id=INDEX_DATASET,
        repo_type="dataset",
        local_dir=os.environ.get("INDEX_LOCAL_DIR", "/tmp/fred_index"),
    )
)

# ---------------------------------------------------------------------------
# 2. Load model + index ONCE. Doing this at module scope (not inside the
#    handler) means the ~few-second startup cost is paid at boot, and every
#    query afterward is the ~50ms vector scan.
# ---------------------------------------------------------------------------
_searcher = FREDSearcher(data_dir=_index_root)

FREQUENCIES = ["Any", "Daily", "Weekly", "Monthly", "Quarterly", "Annual"]


def _render(results: list[FREDSearchResult]) -> str:
    """Format search results as Markdown for the Gradio output panel."""
    if not results:
        return "_No matching series found. Try rephrasing your query._"

    blocks: list[str] = []
    for i, r in enumerate(results, start=1):
        url = f"https://fred.stlouisfed.org/series/{r.series_id}"
        header = f"### {i}. [`{r.series_id}`]({url}) — {r.title}"
        meta = (
            f"**Similarity:** {r.similarity_score:.3f}  ·  "
            f"**Frequency:** {r.frequency}  ·  "
            f"**Units:** {r.units}  ·  "
            f"**Popularity:** {r.popularity}"
        )
        notes = (r.notes or "").strip()
        if len(notes) > 300:
            notes = notes[:300].rstrip() + "…"
        blocks.append("\n\n".join(p for p in (header, meta, notes) if p))
    return "\n\n---\n\n".join(blocks)


def search(query: str, frequency: str, popularity_boost: bool) -> str:
    """Gradio handler: run a semantic search and return formatted Markdown."""
    query = (query or "").strip()
    if not query:
        return "_Enter a natural-language description of the data you want._"

    results = _searcher.search(
        query,
        top_k=10,
        frequency=None if frequency == "Any" else frequency,
        popularity_boost=popularity_boost,
    )
    return _render(results)


EXAMPLES = [
    ["indicators of commercial real estate credit stress", "Any", True],
    ["inflation expectations vs realized inflation", "Monthly", True],
    ["risk-free rate benchmarks at various maturities", "Daily", True],
    ["housing supply pipeline for multifamily", "Any", True],
]

with gr.Blocks(title="FRED-VDB — Semantic Search over FRED") as demo:
    gr.Markdown(
        "# FRED-VDB\n"
        "Semantic search over ~840K FRED economic series. Describe the data "
        "you want in plain language — matching is by *meaning*, not keywords."
    )
    with gr.Row():
        query_box = gr.Textbox(
            label="What are you looking for?",
            placeholder="e.g. indicators of labor market slack",
            scale=4,
        )
        freq_dropdown = gr.Dropdown(
            FREQUENCIES, value="Any", label="Frequency", scale=1
        )
    boost_toggle = gr.Checkbox(
        value=True,
        label="Boost well-known series (popularity re-ranking)",
        info="On: surfaces headline series like UNRATE/DGS10. Off: pure similarity.",
    )
    search_btn = gr.Button("Search", variant="primary")
    output = gr.Markdown()

    gr.Examples(EXAMPLES, inputs=[query_box, freq_dropdown, boost_toggle])

    search_btn.click(
        search, inputs=[query_box, freq_dropdown, boost_toggle], outputs=output
    )
    query_box.submit(
        search, inputs=[query_box, freq_dropdown, boost_toggle], outputs=output
    )

if __name__ == "__main__":
    demo.launch()
