"""Smoke tests for search_company_disclosures (mocked)."""
from unittest.mock import patch, MagicMock

import numpy as np

from fabops.tools.base import ToolResult
from fabops.tools import search_disclosures


def test_empty_edgar_index_returns_no_hits():
    search_disclosures.reset_cache()
    with patch.object(search_disclosures, "_load_all_chunks", return_value=[]):
        result = search_disclosures.run(query="Taiwan lead times", top_k=3)
    assert isinstance(result, ToolResult)
    assert result.ok
    assert result.data["hits"] == []
    assert "empty" in result.data["note"].lower()


def test_cosine_ranking_picks_closest_chunk():
    search_disclosures.reset_cache()
    fake_chunks = [
        {
            "doc_id": "acc1", "chunk_id": "c1", "form": "10-K",
            "filing_date": "2025-12-31",
            "sec_url": "https://sec.gov/x",
            "text": "Supply chain disruption in Taiwan extended lead times.",
            "embedding": [1.0, 0.0, 0.0],
        },
        {
            "doc_id": "acc2", "chunk_id": "c2", "form": "10-Q",
            "filing_date": "2025-09-30",
            "sec_url": "https://sec.gov/y",
            "text": "Unrelated content about dividends.",
            "embedding": [0.0, 1.0, 0.0],
        },
    ]
    with patch.object(search_disclosures, "_load_all_chunks", return_value=fake_chunks):
        with patch.object(search_disclosures, "_embed_query", return_value=np.array([1.0, 0.0, 0.0])):
            result = search_disclosures.run(query="Taiwan lead times", top_k=2)
    assert result.ok
    assert len(result.data["hits"]) == 2
    # The Taiwan chunk should be first with relevance ~ 1.0
    assert "Taiwan" in result.data["hits"][0]["excerpt"]
    assert result.data["hits"][0]["relevance"] > 0.99
