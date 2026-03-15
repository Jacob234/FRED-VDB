---
handoff_id: 2026-03-11_1400
title: "Query Expansion for Finance Abbreviations"
date: 2026-03-11T14:00:00-06:00
parent_handoffs:
  - .claude/handoffs/2026-03-10_1500_enrichment-run-and-abbreviation-gap.md
status: active
---

# Handoff: Query Expansion for Finance Abbreviations

## Session Overview

**Date**: 2026-03-11
**Primary Goal**: Fix the abbreviation gap discovered in the previous session — finance abbreviations like CRE, MBS, HY don't match their full forms in the embedding model.

## What Was Accomplished

- **Compiled ~75 finance abbreviation candidates** across 10 domains (rates, credit, real estate, banking, econ indicators, labor, financial conditions, housing agencies, trade, fiscal).
- **Audited all 75 against the live index** — ran each abbreviation as a bare query and recorded top-3 results to identify false expansion risks.
- **Discovered real conflicts**: `CU` clashes with copper commodity series (PCOPPUSDM etc.), `IP` clashes with intellectual property investment series (Y057RC1Q027SBEA etc.), `MF` clashes with mutual fund series, `SFR` matches San Francisco geographic series.
- **Designed context-gated expansion** — ambiguous abbreviations only expand when the query contains domain-specific context words (e.g. `MF` → `multifamily` only when query also has "housing", "lending", "mortgage" etc.).
- **Built `fred_search/_abbreviations.py`** — contains the full dictionary, conditional expansion config, and `expand_query()` function.
- **Wired into `FREDSearcher.search()`** — two lines: import + call `expand_query()` before encoding.
- **Validated against key test cases** — all abbreviation queries dramatically improved, conditional gating works correctly (MF/IP expand only with context), spec queries show no regressions.

## Key Decisions & Context

### Decision 1: Append vs Replace
**Context**: Should expansion replace the abbreviation or append the full form?
**Decision**: Append in parentheses: `"CRE" → "CRE (commercial real estate)"`.
**Rationale**: Preserves the original token in case the model partially recognizes it (GDP=0.64, CPI=0.55). The expanded text adds semantic signal without removing any. Zero-downside approach for additive embedding models.

### Decision 2: Context-Gated Conditional Expansions
**Context**: Some abbreviations are ambiguous — MF (multifamily vs mutual fund), IP (industrial production vs intellectual property), CU (capacity utilization vs copper), SFR (single-family rental vs San Francisco), EM (emerging markets vs geographic names).
**Decision**: Conditional expansion — only expand when the query contains a context word from a curated set.
**Rationale**: Eliminates false expansions while still handling the abbreviation when domain context is clear. E.g. "MF lending standards" expands, "MF fund performance" does not.

### Decision 3: Module Placement
**Context**: Where to put the abbreviation dictionary for discoverability and extensibility.
**Decision**: `fred_search/_abbreviations.py` — private module alongside search.py.
**Rationale**: Obvious name, private underscore convention, Python (not JSON/YAML) because conditional expansions use sets. Easy to extend without touching search logic.

## Current State

### Files Modified (This Session)
- [`fred_search/_abbreviations.py`](../../fred_search/_abbreviations.py) — NEW. 70 unconditional + 5 conditional abbreviation expansions with `expand_query()` function.
- [`fred_search/search.py`](../../fred_search/search.py) — Added import of `expand_query` and 4-line expansion block before encoding.

### Git State
**Not yet committed.** Two files ready to stage:
```
modified:   fred_search/search.py        (+7 lines)
new file:   fred_search/_abbreviations.py
```

### Search Quality After Expansion

| Query | Before | After | Status |
|-------|--------|-------|--------|
| CRE credit stress | ISE Cyber Security (0.13) | COMREPUSQ159N #2 (0.52) | **Fixed** |
| MBS delinquency | Computers (0.21) | RE delinquency (0.79) | **Fixed** |
| CMBS spread | Liquidity surveys (0.30) | Mortgage balances (0.83) | **Fixed** |
| HY credit spread | Coin assets (0.00) | Credit spreads (0.64) | **Fixed** |
| IG corporate bonds | NASDAQ Korea (0.05) | IG bonds (0.82) | **Fixed** |
| FFR target rate | FHLB Advances (0.02) | EFFR #1 (1.09) | **Fixed** |
| MF lending (conditional) | random | SUBLPDRCSM #1 (0.87) | **Fixed** |
| MF fund (no context) | — | Not expanded | **Correct** |
| IP output (conditional) | Internet users India | INDPRO #1 (1.06) | **Fixed** |
| IP investment (no context) | — | Not expanded | **Correct** |

### Spec Queries — No Regressions
- financial stress indicator: STLFSI4 #1, NFCI #3 — PASS
- housing starts: HOUST #1 — PASS
- inflation expectations: EXPINF1YR #1 — PASS
- REIT performance: REIT indices — PASS (expansion adds insurance)

### Incomplete Validation
The full 10-query spec validation was interrupted. The following queries were NOT re-checked in this session after expansion was wired in:
- "10-year treasury yield" → DGS10 expected (known issue: DGS10 ~#10, THREEFY10 #1)
- "unemployment rate" → UNRATE expected (was #5 after enrichment)
- "high yield credit spread" → BAMLH0A0HYM2 expected (no HY abbreviation in query — shouldn't change)
- "multifamily lending" → SUBLPDRCSM expected
- "construction costs" → WPUSI012011, TLRESCONS expected

## Abbreviation Dictionary Summary

### Unconditional (70 entries)
Organized by domain:
- **Interest Rates**: FFR, EFFR, SOFR, LIBOR, IOER, OBFR, TIPS, UST, YC, QE, QT, FOMC
- **Fixed Income**: HY, IG, OAS, MBS, CMBS, RMBS, ABS, CLO, CDO, CDS, GSE, TED
- **Real Estate**: CRE, REIT, ARM, FRM, LTV, HPI
- **Banking**: SLOOS, NPL, NIM, FDIC, FHLB
- **Econ Indicators**: GDP, GNP, GDI, CPI, PPI, PCE, PCEPI, PMI, ISM, NFP, JOLTS, LEI, ECI, M1, M2
- **Labor**: LFPR, EPOP, AHE, QCEW
- **Financial Conditions**: NFCI, STLFSI, KCFSI, CFNAI, VIX
- **Housing Agencies**: FHFA, FHA, NAHB
- **Markets/Trade**: FX, FDI, BOP, DXY, REER, ETF, S&P
- **Fiscal**: DSPIC, SNAP, TANF

### Conditional (5 entries)
| Abbrev | Expansion | Context words | Conflict avoided |
|--------|-----------|---------------|-----------------|
| MF | multifamily | housing, lending, loan, property, rental, construction, residential, mortgage, apartment, unit, starts, permit, rent, building | Mutual fund |
| IP | industrial production | output, manufacturing, factory, capacity, index, production, sector, industrial | Intellectual property |
| CU | capacity utilization | manufacturing, factory, output, utilization, production, rate, industrial, capacity | Copper (Cu) |
| SFR | single-family rental | housing, rental, property, residential, rent, home, lease, vacancy, single-family, tenant | San Francisco |
| EM | emerging markets | market, debt, bond, sovereign, currency, index, economy, spread, risk, developing | Geographic names |

## Context from Parent Handoffs

### From [Tag Enrichment & Abbreviation Gap](./2026-03-10_1500_enrichment-run-and-abbreviation-gap.md)
- Enriched index: 33,230 series with per-series tags, popularity-boosted scoring
- Abbreviation gap discovered: all-MiniLM-L6-v2 can't map CRE↔commercial real estate (0.217 sim)
- Suggested query expansion as simplest fix — this session implemented it

### From [Ingest Run & Search Validation](./2026-03-09_1530_ingest-run-and-search-validation.md)
- Initial 11,827 series index validated against 10 test queries
- Known weak spots: generic queries, DGS10 ranking

## Suggested Child Handoffs

### Child 1: Commit, Full Validation & Remaining Quality Gaps
**Focus**: Commit the abbreviation expansion work, run the full 10-query validation, and investigate remaining quality gaps (DGS10 not #1 for "10-year treasury yield", UNRATE ranking, BAMLH0A0HYM2 for "high yield credit spread").
**Prerequisites**: Current uncommitted changes
**Expected Outcome**: Clean commit on main, documented quality status for all 10 spec queries, decision on whether further tuning is needed.

### Child 2: Distribution & Packaging
**Focus**: Make fred-vdb installable via PyPI.
**Work Items**: `uv build && uv publish`, GitHub Release with pre-built index (~90MB), `fred-vdb-download-index` CLI command, README with demo.
**Prerequisites**: Search quality acceptable (abbreviation gap fixed)
**Expected Outcome**: `pip install fred-vdb && fred-search "inflation expectations"` works

### Child 3: Test Suite
**Focus**: pytest tests for the full pipeline.
**Work Items**: Filter correctness, abbreviation expansion unit tests (unconditional + conditional + no-expand cases), search quality regression tests using the 10 curated queries, popularity boost math.
**Prerequisites**: Abbreviation expansion committed
**Expected Outcome**: `pytest tests/` with >90% coverage of search path

### Child 4: Incremental Updates
**Focus**: `fred-ingest --incremental` using FRED's `series/updates` endpoint.
**Prerequisites**: Full ingest working (done)
**Expected Outcome**: Updates LanceDB in-place; IngestState already tracks timestamps.

## Open Questions & Issues

1. **DGS10 still not #1**: For "10-year treasury yield", DGS10 lands ~#10. Series title is "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Daily" — no word "yield" causes yield spread series to rank higher. May need a canonical-series boost or title augmentation.
2. **BAMLH0A0HYM2 ranking**: "high yield credit spread" returns CROASMIDTIER (mortgage credit) instead of the BofA HY index. The CROAS series have richer metadata text. May need to check if BAMLH0A0HYM2 is even in the index.
3. **Abbreviation dictionary extensibility**: Currently hardcoded Python. Could add a user-extensible config file (YAML) for domain-specific additions. Not needed yet.
4. **Uncommitted work**: The expansion code works but hasn't been committed yet.

## References

- [Implementation Spec](../../fred-vector-search.md) — Test query list and design rationale
- [Abbreviation Module](../../fred_search/_abbreviations.py) — Dictionary and expansion logic
- [Search Module](../../fred_search/search.py) — Where expansion is called
- [Parent Handoff](./2026-03-10_1500_enrichment-run-and-abbreviation-gap.md) — Abbreviation gap discovery

## Technical Notes

### Expansion Strategy
`expand_query()` uses regex word-boundary matching (`\b`) to find abbreviations as standalone words, case-insensitive. Replaces with `ABBREV (full form)` to preserve both tokens in the embedding. Unconditional expansions run first, then conditional ones check for context word overlap.

### Performance Impact
Zero. Expansion is pure string manipulation (~microseconds). No additional embedding calls or vector searches.

### Edge Cases Handled
- Case-insensitive matching: "cre" and "CRE" both expand
- Multiple abbreviations in one query: all expand independently
- Conditional context check uses set intersection on lowercased words
- Abbreviations inside other words don't match (word boundary regex)

## Next Session Prompt

```
Continue work on FRED-VDB from handoff: .claude/handoffs/2026-03-11_1400_query-expansion-abbreviations.md

Query expansion for finance abbreviations is implemented but NOT YET COMMITTED.
Files: fred_search/_abbreviations.py (new), fred_search/search.py (modified).
70 unconditional + 5 context-gated conditional expansions.

Priority: commit the expansion work, then run the full 10-query spec validation
(from fred-vector-search.md) to document final quality status. Investigate
remaining gaps: DGS10 not #1 for "10-year treasury yield", BAMLH0A0HYM2 not
appearing for "high yield credit spread". After that, consider test suite or
PyPI packaging.
```
