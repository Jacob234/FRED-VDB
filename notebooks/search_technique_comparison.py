import marimo

__generated_with = "0.20.4"
app = marimo.App(width="full")


@app.cell
def __():
    import marimo as mo

    mo.md(
        """
        # FRED-VDB Search Technique Comparison

        Compare different retrieval techniques against the 10 spec test queries.
        Each technique modifies a different part of the search pipeline — document-side
        (what gets embedded), query-side (how queries are processed), or retrieval
        architecture (how results are combined).
        """
    )
    return (mo,)


@app.cell
def __(mo):
    mo.md(
        """
        ## Setup

        Loading embedding model and LanceDB index. This takes a few seconds on first run
        (model download) but is cached for subsequent cells.
        """
    )
    return


@app.cell
def __():
    import math
    import sys
    from pathlib import Path

    import numpy as np
    import pandas as pd

    # Add project root to path so we can import fred_search
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    import lancedb
    from sentence_transformers import SentenceTransformer

    from fred_search._abbreviations import expand_query

    # Load model and index
    _model = SentenceTransformer("all-MiniLM-L6-v2")
    _db = lancedb.connect(str(project_root / "data" / "fred_vector_index"))
    _table = _db.open_table("fred_series")

    # Create FTS index for hybrid search (idempotent)
    _table.create_fts_index("embedding_text", replace=True)

    model_info = f"Model: all-MiniLM-L6-v2 (384-dim) | Index: {_table.count_rows():,} series"
    return (
        SentenceTransformer,
        Path,
        _db,
        _model,
        _table,
        expand_query,
        lancedb,
        math,
        np,
        pd,
        project_root,
        model_info,
        sys,
    )


@app.cell
def __(mo, model_info):
    mo.md(f"**{model_info}**")
    return


# ── Query Selection ──────────────────────────────────────────────────────────


@app.cell
def __(mo):
    # Spec queries with expected series
    SPEC_QUERIES = {
        "10-year treasury yield": {"targets": ["DGS10"]},
        "commercial real estate loan delinquency": {"targets": ["DRCRELEXFACBS"]},
        "inflation expectations": {"targets": ["T5YIE", "T10YIE", "MICH"]},
        "housing starts": {"targets": ["HOUST"]},
        "financial stress indicator": {"targets": ["STLFSI4", "NFCI"]},
        "unemployment rate": {"targets": ["UNRATE"]},
        "REIT performance": {"targets": ["WILLREITIND"]},
        "high yield credit spread": {"targets": ["BAMLH0A0HYM2"]},
        "multifamily lending": {"targets": ["SUBLPDRCSM", "SUBLPDRCDM"]},
        "construction costs": {"targets": ["WPUSI012011", "TLRESCONS"]},
    }

    query_dropdown = mo.ui.dropdown(
        options=list(SPEC_QUERIES.keys()),
        value="high yield credit spread",
        label="Spec Query",
    )

    custom_query_input = mo.ui.text(
        value="",
        label="Or type a custom query",
        full_width=True,
    )

    top_k_slider = mo.ui.slider(
        start=5,
        stop=50,
        value=15,
        step=5,
        label="Top K results per technique",
    )

    mo.md(
        f"""
        ## Query Selection

        {mo.hstack([query_dropdown, top_k_slider], justify="start", gap=2)}

        {custom_query_input}
        """
    )
    return SPEC_QUERIES, custom_query_input, query_dropdown, top_k_slider


@app.cell
def __(SPEC_QUERIES, custom_query_input, query_dropdown):
    # Resolve the active query
    active_query = custom_query_input.value.strip() if custom_query_input.value.strip() else query_dropdown.value
    target_ids = SPEC_QUERIES.get(active_query, {}).get("targets", [])
    return active_query, target_ids


@app.cell
def __(active_query, expand_query, mo, target_ids):
    expanded = expand_query(active_query)
    expansion_note = f"  →  **Expanded**: `{expanded}`" if expanded != active_query else "  _(no abbreviations found)_"

    mo.md(
        f"""
        **Active query**: `{active_query}`{expansion_note}

        **Target series**: {', '.join(f'`{t}`' for t in target_ids) if target_ids else '_(custom query — no targets)_'}
        """
    )
    return expanded, expansion_note


# ── Technique Implementations ────────────────────────────────────────────────


@app.cell
def __(_model, _table, expand_query, math, np, pd):
    def _embed(text):
        """Embed a single text string."""
        return _model.encode([text], normalize_embeddings=True)[0].tolist()

    def _l2_to_cosine(l2_dist):
        """Convert L2 distance to cosine similarity for normalized vectors."""
        return max(0.0, 1.0 - (l2_dist**2) / 2.0)

    def _pop_boost(cos_sim, popularity):
        """Apply popularity boost: cos_sim * (1 + log(pop + 1) / 10)."""
        return cos_sim * (1.0 + math.log(popularity + 1) / 10.0)

    def _results_to_df(rows, query_vec=None, boost=True):
        """Convert LanceDB result rows to a clean DataFrame."""
        def build_records(result_rows):
            records = []
            for _idx, row in result_rows.iterrows():
                l2 = float(row.get("_distance", 0.0))
                cos_sim = _l2_to_cosine(l2)
                pop = int(row.get("popularity", 0))
                score = _pop_boost(cos_sim, pop) if boost else cos_sim
                records.append({
                    "series_id": row["series_id"],
                    "title": row["title"][:70],
                    "popularity": pop,
                    "cosine_sim": round(cos_sim, 4),
                    "score": round(score, 4),
                })
            return records

        records = build_records(rows)
        df = pd.DataFrame(records)
        if len(df) > 0:
            df = df.sort_values("score", ascending=False).reset_index(drop=True)
            df.index = df.index + 1
            df.index.name = "rank"
        return df

    # ── Technique 1: Baseline (current search) ──

    def search_baseline(query, top_k=15):
        """Current search: abbreviation expansion + vector + popularity boost."""
        expanded = expand_query(query)
        vec = _embed(expanded)
        fetch_limit = top_k * 3
        df = _table.search(vec).limit(fetch_limit).to_pandas()
        return _results_to_df(df, boost=True).head(top_k)

    # ── Technique 2: Pure cosine (no popularity boost) ──

    def search_no_boost(query, top_k=15):
        """Vector search with abbreviation expansion but no popularity boost."""
        expanded = expand_query(query)
        vec = _embed(expanded)
        df = _table.search(vec).limit(top_k).to_pandas()
        return _results_to_df(df, boost=False).head(top_k)

    # ── Technique 3: Raw query (no abbreviation expansion) ──

    def search_no_expansion(query, top_k=15):
        """Vector search with popularity boost but no abbreviation expansion."""
        vec = _embed(query)  # Raw query, no expansion
        fetch_limit = top_k * 3
        df = _table.search(vec).limit(fetch_limit).to_pandas()
        return _results_to_df(df, boost=True).head(top_k)

    # ── Technique 4: Full-text search (BM25 keyword matching) ──

    def search_fts_only(query, top_k=15):
        """Pure full-text search (BM25) on embedding_text field."""
        try:
            df = _table.search(query, query_type="fts").limit(top_k).to_pandas()
            def build_fts_records(result_rows):
                records = []
                for _i, row in result_rows.iterrows():
                    pop = int(row.get("popularity", 0))
                    fts_score = float(row.get("_score", row.get("_relevance_score", 0.0)))
                    records.append({
                        "series_id": row["series_id"],
                        "title": row["title"][:70],
                        "popularity": pop,
                        "cosine_sim": 0.0,
                        "score": round(fts_score, 4),
                    })
                return records
            records = build_fts_records(df)
            result = pd.DataFrame(records)
            if len(result) > 0:
                result = result.sort_values("score", ascending=False).reset_index(drop=True)
                result.index = result.index + 1
                result.index.name = "rank"
            return result
        except Exception as exc:
            return pd.DataFrame({"error": [str(exc)]})

    # ── Technique 5: Hybrid (vector + FTS with RRF) ──

    def search_hybrid(query, top_k=15, k_rrf=60):
        """Hybrid: merge vector and FTS results via Reciprocal Rank Fusion."""
        expanded = expand_query(query)
        vec = _embed(expanded)

        fetch_n = top_k * 3

        # Vector results
        vec_df = _table.search(vec).limit(fetch_n).to_pandas()
        vec_ranks = {row["series_id"]: rank + 1 for rank, (_, row) in enumerate(vec_df.iterrows())}

        # FTS results
        try:
            fts_df = _table.search(query, query_type="fts").limit(fetch_n).to_pandas()
            fts_ranks = {row["series_id"]: rank + 1 for rank, (_, row) in enumerate(fts_df.iterrows())}
        except Exception:
            fts_ranks = {}

        # RRF merge
        all_ids = set(vec_ranks.keys()) | set(fts_ranks.keys())

        def compute_rrf_scores(series_ids, v_ranks, f_ranks, k):
            scores = {}
            for sid in series_ids:
                rrf = 0.0
                if sid in v_ranks:
                    rrf += 1.0 / (k + v_ranks[sid])
                if sid in f_ranks:
                    rrf += 1.0 / (k + f_ranks[sid])
                scores[sid] = rrf
            return scores

        rrf_scores = compute_rrf_scores(all_ids, vec_ranks, fts_ranks, k_rrf)

        # Build result df with metadata from whichever source has the series
        def build_hybrid_records(scores, v_df, f_df):
            combined = pd.concat([v_df, f_df]).drop_duplicates(subset="series_id")
            records = []
            for sid, rrf in sorted(scores.items(), key=lambda x: -x[1]):
                matching = combined[combined["series_id"] == sid]
                if len(matching) > 0:
                    row = matching.iloc[0]
                    vec_r = vec_ranks.get(sid, "—")
                    fts_r = fts_ranks.get(sid, "—")
                    records.append({
                        "series_id": sid,
                        "title": row["title"][:70],
                        "popularity": int(row.get("popularity", 0)),
                        "cosine_sim": 0.0,
                        "score": round(rrf, 6),
                        "vec_rank": vec_r,
                        "fts_rank": fts_r,
                    })
            return records

        try:
            fts_df_for_merge = fts_df
        except NameError:
            fts_df_for_merge = pd.DataFrame()

        records = build_hybrid_records(rrf_scores, vec_df, fts_df_for_merge)
        result = pd.DataFrame(records).head(top_k)
        if len(result) > 0:
            result.index = range(1, len(result) + 1)
            result.index.name = "rank"
        return result

    # ── Technique 6: Title-boosted re-embedding ──

    def search_title_boosted(query, top_k=15):
        """
        Re-embed candidates with title repeated 3x, then re-rank.

        This simulates what would happen if we rebuilt the index with
        title-weighted embedding text. We fetch broad candidates first,
        then re-embed their text with title repeated.
        """
        expanded = expand_query(query)
        query_vec = np.array(_embed(expanded))

        # Fetch broad candidate pool
        candidate_df = _table.search(query_vec.tolist()).limit(top_k * 5).to_pandas()

        # Re-embed with title repeated
        def build_boosted_texts(cand_df):
            texts = []
            for _i, row in cand_df.iterrows():
                title = row["title"]
                orig_text = row["embedding_text"]
                # Repeat title 3x at the start
                boosted = f"{title} | {title} | {title} | {orig_text}"
                texts.append(boosted)
            return texts

        boosted_texts = build_boosted_texts(candidate_df)
        boosted_vecs = _model.encode(boosted_texts, normalize_embeddings=True)

        # Re-score against query
        sims = boosted_vecs @ query_vec  # cosine similarity (both normalized)

        def build_boosted_records(cand_df, similarities):
            records = []
            for idx_val in range(len(cand_df)):
                row = cand_df.iloc[idx_val]
                cos_sim = float(similarities[idx_val])
                pop = int(row.get("popularity", 0))
                score = _pop_boost(cos_sim, pop)
                records.append({
                    "series_id": row["series_id"],
                    "title": row["title"][:70],
                    "popularity": pop,
                    "cosine_sim": round(cos_sim, 4),
                    "score": round(score, 4),
                })
            return records

        records = build_boosted_records(candidate_df, sims)
        result = pd.DataFrame(records)
        result = result.sort_values("score", ascending=False).reset_index(drop=True).head(top_k)
        result.index = range(1, len(result) + 1)
        result.index.name = "rank"
        return result

    # ── Technique 7: Multi-query RRF ──

    def search_multi_query(query, top_k=15, k_rrf=60):
        """
        Generate query variants (original, expanded, rephrased), search each,
        merge with Reciprocal Rank Fusion.
        """
        expanded = expand_query(query)
        variants = [query]
        if expanded != query:
            variants.append(expanded)

        # Simple heuristic variants
        variants.append(f"{query} economic data indicator")
        variants.append(f"{query} FRED series index")

        # Search each variant
        all_rankings = []
        for variant in variants:
            vec = _embed(variant)
            df = _table.search(vec).limit(top_k * 3).to_pandas()
            ranks = {row["series_id"]: rank + 1 for rank, (_, row) in enumerate(df.iterrows())}
            all_rankings.append(ranks)

        # RRF merge across all variants
        all_ids = set()
        for ranking in all_rankings:
            all_ids |= set(ranking.keys())

        def compute_multi_rrf(series_ids, rankings, k):
            scores = {}
            for sid in series_ids:
                rrf = 0.0
                for ranking in rankings:
                    if sid in ranking:
                        rrf += 1.0 / (k + ranking[sid])
                scores[sid] = rrf
            return scores

        rrf_scores = compute_multi_rrf(all_ids, all_rankings, k_rrf)

        # Get metadata from first search
        first_vec = _embed(variants[0])
        meta_df = _table.search(first_vec).limit(top_k * 5).to_pandas()

        def build_multi_records(scores, m_df):
            records = []
            for sid, rrf in sorted(scores.items(), key=lambda x: -x[1]):
                matching = m_df[m_df["series_id"] == sid]
                if len(matching) > 0:
                    row = matching.iloc[0]
                    records.append({
                        "series_id": sid,
                        "title": row["title"][:70],
                        "popularity": int(row.get("popularity", 0)),
                        "cosine_sim": 0.0,
                        "score": round(rrf, 6),
                    })
            return records

        records = build_multi_records(rrf_scores, meta_df)
        result = pd.DataFrame(records).head(top_k)
        if len(result) > 0:
            result.index = range(1, len(result) + 1)
            result.index.name = "rank"
        return result

    technique_names = [
        "baseline",
        "no_boost",
        "no_expansion",
        "fts_only",
        "hybrid_rrf",
        "title_boosted",
        "multi_query",
    ]
    return (
        _embed,
        _l2_to_cosine,
        _pop_boost,
        _results_to_df,
        search_baseline,
        search_fts_only,
        search_hybrid,
        search_multi_query,
        search_no_boost,
        search_no_expansion,
        search_title_boosted,
        technique_names,
    )


# ── Run All Techniques ───────────────────────────────────────────────────────


@app.cell
def __(
    active_query,
    mo,
    search_baseline,
    search_fts_only,
    search_hybrid,
    search_multi_query,
    search_no_boost,
    search_no_expansion,
    search_title_boosted,
    target_ids,
    top_k_slider,
):
    _k = top_k_slider.value

    technique_results = {
        "Baseline (vector + pop boost)": search_baseline(active_query, _k),
        "No popularity boost": search_no_boost(active_query, _k),
        "No abbreviation expansion": search_no_expansion(active_query, _k),
        "Full-text search only (BM25)": search_fts_only(active_query, _k),
        "Hybrid (vector + FTS via RRF)": search_hybrid(active_query, _k),
        "Title-boosted re-embedding": search_title_boosted(active_query, _k),
        "Multi-query RRF": search_multi_query(active_query, _k),
    }

    # Build summary: which techniques found each target?
    def build_summary(results_dict, targets):
        summary_rows = []
        for name, df in results_dict.items():
            if "error" in df.columns:
                summary_rows.append({
                    "technique": name,
                    "found_targets": "ERROR",
                    "best_target_rank": "—",
                    "top_1": df.iloc[0].get("error", "?") if len(df) > 0 else "—",
                })
                continue
            found = [t for t in targets if t in df["series_id"].values]
            best_rank = "—"
            if found:
                def get_best_rank(dataframe, found_list):
                    ranks = []
                    for tid in found_list:
                        matching = dataframe[dataframe["series_id"] == tid]
                        if len(matching) > 0:
                            ranks.append(matching.index[0])
                    return min(ranks) if ranks else None
                br = get_best_rank(df, found)
                best_rank = br if br is not None else "—"
            summary_rows.append({
                "technique": name,
                "found_targets": ", ".join(found) if found else "NONE",
                "best_target_rank": best_rank,
                "top_1": df.iloc[0]["series_id"] if len(df) > 0 else "—",
            })
        return summary_rows

    summary_data = build_summary(technique_results, target_ids)

    mo.md(
        f"""
        ## Results Summary

        Query: **{active_query}** | Target(s): **{', '.join(target_ids) if target_ids else 'N/A'}** | Top K: **{_k}**
        """
    )
    return summary_data, technique_results


@app.cell
def __(mo, pd, summary_data):
    summary_df = pd.DataFrame(summary_data)
    mo.ui.table(summary_df, selection=None)
    return (summary_df,)


# ── Detailed Results per Technique ───────────────────────────────────────────


@app.cell
def __(mo, target_ids, technique_results):
    def _highlight_targets(df, targets):
        """Mark rows where series_id matches a target."""
        if "series_id" not in df.columns or not targets:
            return df
        df = df.copy()
        df["target?"] = df["series_id"].apply(lambda sid: ">>>" if sid in targets else "")
        # Move target column to front
        cols = ["target?"] + [c for c in df.columns if c != "target?"]
        return df[cols]

    tabs_content = {}
    for _name, _df in technique_results.items():
        highlighted = _highlight_targets(_df, target_ids)
        tabs_content[_name] = mo.ui.table(highlighted, selection=None)

    mo.md("## Detailed Results by Technique")
    return tabs_content,


@app.cell
def __(mo, tabs_content):
    mo.ui.tabs(tabs_content)
    return


# ── Technique Explanations ───────────────────────────────────────────────────


@app.cell
def __(mo):
    mo.md(
        """
        ## Technique Reference

        | # | Technique | Pipeline Stage | What It Changes | Cost |
        |---|-----------|---------------|-----------------|------|
        | 1 | **Baseline** | — | Current search: abbreviation expansion → embed → vector search → popularity boost | — |
        | 2 | **No popularity boost** | Scoring | Pure cosine similarity, no `log(pop)` multiplier | Free |
        | 3 | **No abbreviation expansion** | Query-side | Raw query text, no finance term expansion | Free |
        | 4 | **Full-text search (BM25)** | Retrieval | Keyword matching on embedding_text via LanceDB FTS index | Free |
        | 5 | **Hybrid (vector + FTS via RRF)** | Retrieval | Merge vector and BM25 results with Reciprocal Rank Fusion `1/(k+rank)` | 2× search |
        | 6 | **Title-boosted re-embedding** | Document-side | Re-embed candidates with title repeated 3×, simulating a title-weighted index | Slow (re-embeds top candidates) |
        | 7 | **Multi-query RRF** | Query-side | Generate query variants (original, expanded, + heuristic rephrasings), merge with RRF | N× search |

        ---

        **Reading the results**: The `target?` column marks series that the spec says should appear.
        A `>>>` means the series was found. Compare `best_target_rank` across techniques —
        lower is better. If a technique finds the target but baseline doesn't, that technique
        addresses the specific embedding gap.
        """
    )
    return


# ── Batch Comparison: All 10 Spec Queries ────────────────────────────────────


@app.cell
def __(mo):
    run_batch_button = mo.ui.run_button(label="Run all 10 spec queries across all techniques (slow)")
    mo.md(
        f"""
        ## Batch Comparison

        Run all 10 spec queries through every technique and see which technique
        works best overall.

        {run_batch_button}
        """
    )
    return (run_batch_button,)


@app.cell
def __(
    SPEC_QUERIES,
    mo,
    pd,
    run_batch_button,
    search_baseline,
    search_fts_only,
    search_hybrid,
    search_multi_query,
    search_no_boost,
    search_no_expansion,
    search_title_boosted,
):
    mo.stop(not run_batch_button.value, mo.md("_Press the button above to run batch comparison._"))

    _technique_fns = {
        "Baseline": search_baseline,
        "No boost": search_no_boost,
        "No expansion": search_no_expansion,
        "FTS only": search_fts_only,
        "Hybrid RRF": search_hybrid,
        "Title-boosted": search_title_boosted,
        "Multi-query": search_multi_query,
    }

    _TOP = 25

    def run_batch(queries, technique_functions, top_k_val):
        batch_rows = []
        for query_text, spec in queries.items():
            targets = spec["targets"]
            for tech_name, tech_fn in technique_functions.items():
                try:
                    df = tech_fn(query_text, top_k_val)
                    if "error" in df.columns:
                        batch_rows.append({
                            "query": query_text[:40],
                            "technique": tech_name,
                            "found": "ERROR",
                            "best_rank": "—",
                        })
                        continue
                    found_list = [t for t in targets if t in df["series_id"].values]
                    best_r = "—"
                    if found_list:
                        def get_rank(dataframe, found_items):
                            ranks = []
                            for tid in found_items:
                                matching = dataframe[dataframe["series_id"] == tid]
                                if len(matching) > 0:
                                    ranks.append(matching.index[0])
                            return min(ranks) if ranks else None
                        br = get_rank(df, found_list)
                        best_r = br if br is not None else "—"
                    batch_rows.append({
                        "query": query_text[:40],
                        "technique": tech_name,
                        "found": ", ".join(found_list) if found_list else "MISS",
                        "best_rank": best_r,
                    })
                except Exception as exc:
                    batch_rows.append({
                        "query": query_text[:40],
                        "technique": tech_name,
                        "found": f"ERR: {exc}",
                        "best_rank": "—",
                    })
        return batch_rows

    batch_results = run_batch(SPEC_QUERIES, _technique_fns, _TOP)
    batch_df = pd.DataFrame(batch_results)

    # Pivot: queries as rows, techniques as columns, values = best_rank
    batch_pivot = batch_df.pivot(index="query", columns="technique", values="best_rank")
    batch_found = batch_df.pivot(index="query", columns="technique", values="found")

    mo.md("### Best Target Rank by Technique (lower = better, — = miss)")
    return batch_df, batch_found, batch_pivot, batch_results


@app.cell
def __(batch_pivot, mo):
    mo.ui.table(batch_pivot.reset_index(), selection=None)
    return


@app.cell
def __(batch_df, mo, pd):
    # Score summary: count hits and misses per technique
    def summarize_techniques(df):
        summary_rows = []
        for tech in df["technique"].unique():
            tech_data = df[df["technique"] == tech]
            hits = tech_data[tech_data["found"] != "MISS"]
            misses = tech_data[tech_data["found"] == "MISS"]
            numeric_ranks = []
            for rank_val in hits["best_rank"]:
                if isinstance(rank_val, (int, float)):
                    numeric_ranks.append(rank_val)
            avg_rank = round(sum(numeric_ranks) / len(numeric_ranks), 1) if numeric_ranks else "—"
            summary_rows.append({
                "technique": tech,
                "hits": len(hits),
                "misses": len(misses),
                "avg_best_rank": avg_rank,
            })
        return summary_rows

    tech_summary = summarize_techniques(batch_df)
    tech_summary_df = pd.DataFrame(tech_summary).sort_values("hits", ascending=False)

    mo.md("### Technique Scorecard")
    return tech_summary, tech_summary_df


@app.cell
def __(mo, tech_summary_df):
    mo.ui.table(tech_summary_df, selection=None)
    return


if __name__ == "__main__":
    app.run()
