"""
Finance and economics abbreviation expansion for FRED search queries.

The embedding model (all-MiniLM-L6-v2) cannot map most finance abbreviations
to their full forms — e.g. "CRE" ↔ "commercial real estate" has only 0.217
cosine similarity. This module expands abbreviations inline before embedding
so that the query vector captures the intended semantics.

Expansion strategy: append the full form in parentheses after the abbreviation,
e.g. "CRE credit stress" → "CRE (commercial real estate) credit stress".
This preserves the original token (in case the model partially recognises it)
while adding the semantically rich expansion.

To add new abbreviations, add entries to EXPANSIONS or CONDITIONAL_EXPANSIONS.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Unconditional expansions — always applied when the abbreviation appears
# as a standalone word in the query.
# ---------------------------------------------------------------------------
EXPANSIONS: dict[str, str] = {
    # Interest Rates & Monetary Policy
    "FFR": "federal funds rate",
    "EFFR": "effective federal funds rate",
    "SOFR": "secured overnight financing rate",
    "LIBOR": "London Interbank Offered Rate",
    "IOER": "interest on excess reserves",
    "OBFR": "overnight bank funding rate",
    "TIPS": "Treasury Inflation-Protected Securities",
    "UST": "US Treasury",
    "YC": "yield curve",
    "QE": "quantitative easing",
    "QT": "quantitative tightening",
    "FOMC": "Federal Open Market Committee",
    # Fixed Income & Credit
    "HY": "high yield",
    "IG": "investment grade",
    "OAS": "option-adjusted spread",
    "MBS": "mortgage-backed securities",
    "CMBS": "commercial mortgage-backed securities",
    "RMBS": "residential mortgage-backed securities",
    "ABS": "asset-backed securities",
    "CLO": "collateralized loan obligation",
    "CDO": "collateralized debt obligation",
    "CDS": "credit default swap",
    "GSE": "government-sponsored enterprise",
    "TED": "TED spread Treasury-Eurodollar",
    # Real Estate
    "CRE": "commercial real estate",
    "REIT": "real estate investment trust",
    "ARM": "adjustable-rate mortgage",
    "FRM": "fixed-rate mortgage",
    "LTV": "loan-to-value",
    "HPI": "house price index",
    # Banking
    "SLOOS": "Senior Loan Officer Opinion Survey",
    "NPL": "nonperforming loans",
    "NIM": "net interest margin",
    "FDIC": "Federal Deposit Insurance Corporation",
    "FHLB": "Federal Home Loan Bank",
    # Economic Indicators
    "GDP": "gross domestic product",
    "GNP": "gross national product",
    "GDI": "gross domestic income",
    "CPI": "consumer price index",
    "PPI": "producer price index",
    "PCE": "personal consumption expenditures",
    "PCEPI": "PCE price index",
    "PMI": "purchasing managers index",
    "ISM": "Institute for Supply Management",
    "NFP": "nonfarm payrolls",
    "JOLTS": "Job Openings and Labor Turnover Survey",
    "LEI": "leading economic indicators",
    "ECI": "Employment Cost Index",
    "M1": "M1 money supply",
    "M2": "M2 money supply",
    # Labor Market
    "LFPR": "labor force participation rate",
    "EPOP": "employment-population ratio",
    "AHE": "average hourly earnings",
    "QCEW": "Quarterly Census of Employment and Wages",
    # Financial Conditions & Stress
    "NFCI": "National Financial Conditions Index",
    "STLFSI": "St. Louis Financial Stress Index",
    "KCFSI": "Kansas City Financial Stress Index",
    "CFNAI": "Chicago Fed National Activity Index",
    "VIX": "CBOE Volatility Index",
    # Housing Agencies
    "FHFA": "Federal Housing Finance Agency",
    "FHA": "Federal Housing Administration",
    "NAHB": "National Association of Home Builders",
    # Markets & Trade
    "FX": "foreign exchange",
    "FDI": "foreign direct investment",
    "BOP": "balance of payments",
    "DXY": "US Dollar Index",
    "REER": "real effective exchange rate",
    "ETF": "exchange traded fund",
    "S&P": "Standard and Poor's",
    # Government / Fiscal
    "DSPIC": "disposable personal income",
    "SNAP": "Supplemental Nutrition Assistance Program",
    "TANF": "Temporary Assistance for Needy Families",
}

# ---------------------------------------------------------------------------
# Conditional expansions — only applied when the query also contains one of
# the context words.  This prevents false expansions for ambiguous abbreviations.
#
# Example: "MF lending standards" → "MF (multifamily) lending standards"
#          "MF fund performance"  → unchanged (no housing context)
# ---------------------------------------------------------------------------
CONDITIONAL_EXPANSIONS: dict[str, dict] = {
    "MF": {
        "expansion": "multifamily",
        "context": {
            "housing", "lending", "loan", "property", "rental",
            "construction", "residential", "mortgage", "apartment",
            "unit", "starts", "permit", "rent", "building",
        },
    },
    "IP": {
        "expansion": "industrial production",
        "context": {
            "output", "manufacturing", "factory", "capacity",
            "index", "production", "sector", "industrial",
        },
    },
    "CU": {
        "expansion": "capacity utilization",
        "context": {
            "manufacturing", "factory", "output", "utilization",
            "production", "rate", "industrial", "capacity",
        },
    },
    "SFR": {
        "expansion": "single-family rental",
        "context": {
            "housing", "rental", "property", "residential", "rent",
            "home", "lease", "vacancy", "single-family", "tenant",
        },
    },
    "EM": {
        "expansion": "emerging markets",
        "context": {
            "market", "debt", "bond", "sovereign", "currency",
            "index", "economy", "spread", "risk", "developing",
        },
    },
}


def expand_query(query: str) -> str:
    """Expand finance abbreviations in a search query before embedding.

    Abbreviations are matched as whole words (case-insensitive) and replaced
    with ``ABBREV (full form)`` so both the original token and the expansion
    contribute to the embedding vector.

    Parameters
    ----------
    query:
        Raw user query, e.g. ``"CRE credit stress"``.

    Returns
    -------
    str
        Expanded query, e.g. ``"CRE (commercial real estate) credit stress"``.
        Returns the original query unchanged if no abbreviations are found.
    """
    query_lower = query.lower()
    query_words_lower = set(query_lower.split())

    result = query

    # --- Unconditional expansions ---
    for abbrev, expansion in EXPANSIONS.items():
        # Match abbreviation as a whole word, case-insensitive.
        # Use a function replacement to preserve the original case of the match.
        pattern = re.compile(r"\b" + re.escape(abbrev) + r"\b", re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(rf"\g<0> ({expansion})", result)

    # --- Conditional expansions ---
    for abbrev, conf in CONDITIONAL_EXPANSIONS.items():
        pattern = re.compile(r"\b" + re.escape(abbrev) + r"\b", re.IGNORECASE)
        if not pattern.search(result):
            continue
        # Check if any context word appears in the query
        if query_words_lower & conf["context"]:
            result = pattern.sub(rf"\g<0> ({conf['expansion']})", result)

    return result
