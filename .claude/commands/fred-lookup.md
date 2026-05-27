---
description: Look up U.S. economic and financial data from FRED (Federal Reserve Economic Data). Use when the task requires specific economic indicators, interest rates, employment figures, inflation data, GDP, housing stats, monetary aggregates, or any quantitative U.S. macroeconomic data. Activates for questions like "what is the current unemployment rate", "how has inflation changed", "show me 10-year treasury yields", "get GDP growth data", or any analysis needing real economic time series.
---

# FRED Data Lookup

You have access to a semantic search index of 33K+ curated FRED time series (filtered from FRED's full ~840K-series catalog) and a fetch tool to pull observation data. Use this two-step workflow to answer questions requiring U.S. economic/financial data.

## Step 1: Search for relevant series

Run a natural language search to find candidate series:

```bash
fred-search "<describe what you need>" --json --top-k 15
```

Tips for good queries:
- Be descriptive: "consumer price index for urban consumers" not "CPI"
- Include qualifiers: "seasonally adjusted monthly unemployment rate"
- For spreads/comparisons, search each component separately
- Use `--frequency Monthly` (or Daily, Quarterly, Annual) to narrow results

The results include `series_id`, `title`, `units`, `frequency`, `seasonal_adjustment`, `tags`, `popularity`, and `similarity_score`.

## Step 2: Rerank and select

You are the reranker. From the search results, select the 1-3 series that best answer the user's question. Consider:

- **Title and notes**: Does it match what was actually asked?
- **Seasonal adjustment**: Prefer "Seasonally Adjusted" for trend analysis, "Not Seasonally Adjusted" for raw/actual values
- **Units**: Match what the user expects (percent, index, thousands, etc.)
- **Frequency**: Match the granularity needed
- **Popularity**: Higher-popularity series are typically the headline/canonical versions (e.g., UNRATE vs regional variants)
- **observation_end**: Prefer series with recent data

## Step 3: Fetch the data

Pull observation data for your selected series:

```bash
fred-fetch SERIES_ID [SERIES_ID ...] --last N --json
```

Options:
- `--last N` — last N observations (good for keeping output concise)
- `--start YYYY-MM-DD` — observations from this date forward
- `--end YYYY-MM-DD` — observations up to this date
- Default (no flags): last 5 years of data

Choose `--last` or `--start/--end` based on the question:
- "What is the current X?" → `--last 1`
- "How has X changed recently?" → `--last 12` (monthly) or `--last 4` (quarterly)
- "Compare X before and after COVID" → `--start 2019-01-01`
- General trend analysis → `--start` with an appropriate lookback

## Step 4: Present the data

When presenting results to the user:
- State the series name and ID so they can verify/explore further
- Note the units and seasonal adjustment
- Provide context (direction, magnitude, historical comparison) rather than just raw numbers
- If the data has `null` values, note that these are missing observations

## Common series (for reference, not exhaustive)

| Topic | Likely series |
|-------|--------------|
| Unemployment | UNRATE, U6RATE, PAYEMS |
| Inflation | CPIAUCSL, CPILFESL, PCEPI, T10YIE |
| GDP | GDP, GDPC1, A191RL1Q225SBEA |
| Interest rates | DFF, DGS2, DGS10, DGS30 |
| Housing | HOUST, MSPUS, MORTGAGE30US |
| Money supply | M2SL, BOGMBASE |
| Stock market | SP500, VIXCLS |

Do not rely on this table — always search first. FRED has 840K+ series and the right one may not be listed here.

## Requirements

- `FRED_API_KEY` environment variable must be set
- The `fred-search` command requires the LanceDB index to be built (`fred-ingest`)
- The `fred-fetch` command requires network access to the FRED API
