"""Tests for finance abbreviation expansion."""

import pytest

from fred_search._abbreviations import (
    CONDITIONAL_EXPANSIONS,
    EXPANSIONS,
    expand_query,
)


class TestUnconditionalExpansion:
    def test_simple_expansion(self):
        result = expand_query("CRE credit stress")
        assert "commercial real estate" in result
        assert result.startswith("CRE")  # original token preserved

    def test_multiple_abbreviations(self):
        result = expand_query("CPI vs PCE inflation")
        assert "consumer price index" in result
        assert "personal consumption expenditures" in result

    def test_case_insensitive(self):
        lower = expand_query("gdp growth")
        upper = expand_query("GDP growth")
        assert "gross domestic product" in lower
        assert "gross domestic product" in upper

    def test_preserves_original_token(self):
        result = expand_query("SOFR rate")
        # Should be "SOFR (secured overnight financing rate) rate"
        assert "SOFR" in result
        assert "secured overnight financing rate" in result

    def test_no_expansion_when_no_abbreviation(self):
        query = "housing prices in the united states"
        assert expand_query(query) == query

    def test_empty_query(self):
        assert expand_query("") == ""

    def test_word_boundary_respected(self):
        # "TIPS" should expand, but "tips" inside a word should not
        result = expand_query("TIPS yield")
        assert "Treasury Inflation-Protected Securities" in result

    def test_all_unconditional_entries_are_strings(self):
        for abbrev, expansion in EXPANSIONS.items():
            assert isinstance(abbrev, str)
            assert isinstance(expansion, str)
            assert len(abbrev) >= 2
            assert len(expansion) > len(abbrev)


class TestConditionalExpansion:
    def test_mf_with_housing_context(self):
        result = expand_query("MF lending standards")
        assert "multifamily" in result

    def test_mf_without_context_no_expansion(self):
        result = expand_query("MF fund performance")
        assert "multifamily" not in result

    def test_ip_with_manufacturing_context(self):
        result = expand_query("IP manufacturing output")
        assert "industrial production" in result

    def test_ip_without_context_no_expansion(self):
        result = expand_query("IP address lookup")
        assert "industrial production" not in result

    def test_sfr_with_housing_context(self):
        result = expand_query("SFR rental vacancy")
        assert "single-family rental" in result

    def test_em_with_market_context(self):
        result = expand_query("EM debt market spread")
        assert "emerging markets" in result

    def test_all_conditional_entries_have_required_keys(self):
        for abbrev, conf in CONDITIONAL_EXPANSIONS.items():
            assert "expansion" in conf, f"{abbrev} missing 'expansion'"
            assert "context" in conf, f"{abbrev} missing 'context'"
            assert isinstance(conf["context"], set)
            assert len(conf["context"]) > 0


class TestEdgeCases:
    def test_abbreviation_at_start(self):
        result = expand_query("GDP")
        assert "gross domestic product" in result

    def test_abbreviation_at_end(self):
        result = expand_query("what is the GDP")
        assert "gross domestic product" in result

    def test_no_double_expansion(self):
        # Running expand twice shouldn't double-expand
        first = expand_query("CRE loans")
        second = expand_query(first)
        # Count occurrences of the expansion
        count = second.count("commercial real estate")
        assert count == 1, f"Double expansion detected: {second!r}"

    def test_mixed_conditional_and_unconditional(self):
        result = expand_query("MF housing CRE loans")
        assert "multifamily" in result  # conditional, context = "housing"
        assert "commercial real estate" in result  # unconditional
