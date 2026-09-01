"""Unit tests for SQL query safety and injection prevention."""

import pytest
from database.sql_server import is_safe_sql


def test_safe_select_query():
    """Valid SELECT queries should pass validation."""
    query = "SELECT TOP 10 Name, ListPrice FROM Production.Product ORDER BY ListPrice DESC"
    is_safe, reason = is_safe_sql(query)
    assert is_safe is True
    assert reason == "SAFE"


def test_safe_cte_query():
    """Valid Common Table Expression (WITH ...) queries should pass validation."""
    query = """
    WITH TopSales AS (
        SELECT SalesPersonID, SUM(TotalDue) AS TotalSales
        FROM Sales.SalesOrderHeader
        GROUP BY SalesPersonID
    )
    SELECT * FROM TopSales WHERE TotalSales > 100000;
    """
    is_safe, reason = is_safe_sql(query)
    assert is_safe is True
    assert reason == "SAFE"


@pytest.mark.parametrize("destructive_query", [
    "DROP TABLE Sales.Customer;",
    "DELETE FROM Production.Product WHERE ProductID = 1;",
    "UPDATE Sales.SalesOrderHeader SET TotalDue = 0;",
    "TRUNCATE TABLE Person.Person;",
    "ALTER TABLE Production.Product ADD TempCol INT;",
    "INSERT INTO Sales.Store (Name) VALUES ('Malicious Store');",
    "EXEC sp_executesql N'SELECT 1';",
    "GRANT ALL PRIVILEGES TO public;",
])
def test_block_destructive_keywords(destructive_query):
    """Destructive DDL/DML statements must be blocked."""
    is_safe, reason = is_safe_sql(destructive_query)
    assert is_safe is False
    assert "UNSAFE_QUERY" in reason


def test_block_comment_injection():
    """Queries that hide destructive actions behind SQL comments must be rejected."""
    query = "-- comment\nDROP TABLE Sales.Customer;"
    is_safe, reason = is_safe_sql(query)
    assert is_safe is False


def test_reject_empty_query():
    """Empty or whitespace queries must be rejected."""
    is_safe, reason = is_safe_sql("   \n\t  ")
    assert is_safe is False
    assert reason == "EMPTY_QUERY"
