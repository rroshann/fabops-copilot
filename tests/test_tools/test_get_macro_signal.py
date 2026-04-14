"""Smoke test for get_industry_macro_signal (mocked)."""
import pytest
from unittest.mock import patch, MagicMock


def test_get_macro_signal_ok_path_mocked():
    from fabops.tools.base import ToolResult
    from fabops.tools import get_macro_signal as mod

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "observations": [
            {"date": "2026-03-01", "value": "102.3"},
            {"date": "2026-02-01", "value": "101.5"},
            {"date": "2025-03-01", "value": "98.2"},
        ]
    }
    mock_response.raise_for_status = lambda: None

    with patch.object(mod, "get_item", return_value={}):
        with patch.object(mod, "get_table") as mock_table:
            mock_table.return_value.put_item = MagicMock()
            with patch.object(mod.requests, "get", return_value=mock_response):
                import os
                os.environ["FRED_API_KEY"] = "fake_key_for_test"
                result = mod.run(month="2026-03", series="production")
                assert isinstance(result, ToolResult)
                assert result.ok
                assert result.data["series_id"] == "IPG3344S"
                assert result.data["value"] is not None


def test_get_macro_signal_unsupported_series():
    from fabops.tools import get_macro_signal as mod
    from unittest.mock import patch
    with patch.object(mod, "get_item", return_value={}):
        result = mod.run(month="2026-03", series="shipments")
        assert not result.ok
        assert "not implemented" in result.error
