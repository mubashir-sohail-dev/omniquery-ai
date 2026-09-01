"""Unit tests for SQL generation and prompt handling."""

from unittest.mock import MagicMock, patch
from ai_engine.llm import generate_sql_query


@patch("ai_engine.llm.GROQ_CLIENT.chat.completions.create")
def test_generate_sql_markdown_stripping(mock_create):
    """Ensure markdown backticks (```sql ... ```) are stripped cleanly."""
    mock_resp = MagicMock()
    mock_resp.choices = [
        MagicMock(message=MagicMock(content="```sql\nSELECT TOP 5 * FROM Production.Product\n```"))
    ]
    mock_create.return_value = mock_resp

    sql = generate_sql_query(
        user_query="Show top 5 products",
        schema_context="Table: Production.Product",
    )
    assert sql == "SELECT TOP 5 * FROM Production.Product"


@patch("ai_engine.llm.GROQ_CLIENT.chat.completions.create")
def test_self_healing_prompt_injection(mock_create):
    """Ensure previous errors trigger the self-healing correction prompt."""
    mock_resp = MagicMock()
    mock_resp.choices = [
        MagicMock(message=MagicMock(content="SELECT ProductID FROM Production.Product"))
    ]
    mock_create.return_value = mock_resp

    generate_sql_query(
        user_query="Show products",
        schema_context="Table: Production.Product",
        previous_sql="SELECT ProdID FROM Production.Product",
        previous_error="Invalid column name 'ProdID'",
    )

    # Verify that the system prompt sent to Groq contains the correction block
    call_args = mock_create.call_args[1]
    messages = call_args["messages"]
    system_msg = messages[0]["content"]

    assert "URGENT CORRECTION REQUIRED" in system_msg
    assert "Invalid column name 'ProdID'" in system_msg
