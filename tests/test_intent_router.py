"""Unit tests for the intent router classification module."""

from unittest.mock import MagicMock, patch
from ai_engine.llm import is_sql_request


@patch("ai_engine.llm.GROQ_CLIENT.chat.completions.create")
def test_is_sql_request_positive(mock_create):
    """Test that business queries return True."""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="YES"))]
    mock_create.return_value = mock_resp

    result = is_sql_request("What are the top 10 selling products?")
    assert result is True
    assert mock_create.called


@patch("ai_engine.llm.GROQ_CLIENT.chat.completions.create")
def test_is_sql_request_negative(mock_create):
    """Test that general chat prompts return False."""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="NO"))]
    mock_create.return_value = mock_resp

    result = is_sql_request("Hi, how is the weather today?")
    assert result is False


@patch("ai_engine.llm.GROQ_CLIENT.chat.completions.create")
def test_is_sql_request_api_error_fallback(mock_create):
    """Test that API failures gracefully fall back to True."""
    mock_create.side_effect = Exception("API rate limit or connection error")

    result = is_sql_request("Show me all orders")
    assert result is True
