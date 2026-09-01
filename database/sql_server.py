"""Database connection, metadata extraction, and SQL execution module."""

import logging
import re
from typing import Any
import pandas as pd

from config import DB_CONN_STR, MOCK_MODE

logger = logging.getLogger(__name__)

# Fallback offline schema summary for mock / offline mode
OFFLINE_SCHEMA_SAMPLE: dict[str, dict[str, list[str]]] = {
    "Sales.SalesOrderHeader": {
        "columns": [
            "SalesOrderID (int)",
            "OrderDate (datetime)",
            "DueDate (datetime)",
            "ShipDate (datetime)",
            "Status (tinyint)",
            "CustomerID (int)",
            "SalesPersonID (int)",
            "TerritoryID (int)",
            "SubTotal (money)",
            "TaxAmt (money)",
            "Freight (money)",
            "TotalDue (money)",
        ],
        "primary_keys": ["SalesOrderID"],
        "foreign_keys": [
            "FK: CustomerID -> Sales.Customer(CustomerID)",
            "FK: SalesPersonID -> Sales.SalesPerson(BusinessEntityID)",
            "FK: TerritoryID -> Sales.SalesTerritory(TerritoryID)",
        ],
    },
    "Sales.SalesOrderDetail": {
        "columns": [
            "SalesOrderID (int)",
            "SalesOrderDetailID (int)",
            "OrderQty (smallint)",
            "ProductID (int)",
            "SpecialOfferID (int)",
            "UnitPrice (money)",
            "UnitPriceDiscount (money)",
            "LineTotal (numeric)",
        ],
        "primary_keys": ["SalesOrderID", "SalesOrderDetailID"],
        "foreign_keys": [
            "FK: SalesOrderID -> Sales.SalesOrderHeader(SalesOrderID)",
            "FK: ProductID -> Production.Product(ProductID)",
        ],
    },
    "Production.Product": {
        "columns": [
            "ProductID (int)",
            "Name (nvarchar)",
            "ProductNumber (nvarchar)",
            "Color (nvarchar)",
            "StandardCost (money)",
            "ListPrice (money)",
            "Size (nvarchar)",
            "Weight (decimal)",
            "ProductSubcategoryID (int)",
            "ProductModelID (int)",
        ],
        "primary_keys": ["ProductID"],
        "foreign_keys": [
            "FK: ProductSubcategoryID -> Production.ProductSubcategory(ProductSubcategoryID)",
            "FK: ProductModelID -> Production.ProductModel(ProductModelID)",
        ],
    },
    "Sales.Customer": {
        "columns": [
            "CustomerID (int)",
            "PersonID (int)",
            "StoreID (int)",
            "TerritoryID (int)",
            "AccountNumber (varchar)",
        ],
        "primary_keys": ["CustomerID"],
        "foreign_keys": [
            "FK: PersonID -> Person.Person(BusinessEntityID)",
            "FK: StoreID -> Sales.Store(BusinessEntityID)",
            "FK: TerritoryID -> Sales.SalesTerritory(TerritoryID)",
        ],
    },
    "Person.Person": {
        "columns": [
            "BusinessEntityID (int)",
            "PersonType (nchar)",
            "NameStyle (bit)",
            "Title (nvarchar)",
            "FirstName (nvarchar)",
            "MiddleName (nvarchar)",
            "LastName (nvarchar)",
            "Suffix (nvarchar)",
            "EmailPromotion (int)",
        ],
        "primary_keys": ["BusinessEntityID"],
        "foreign_keys": [],
    },
}


def is_safe_sql(sql_query: str) -> tuple[bool, str]:
    """Validates that a SQL query is read-only and safe to execute.

    Args:
        sql_query: The SQL query string to inspect.

    Returns:
        Tuple of (is_safe: bool, reason: str).
    """
    if not sql_query or not sql_query.strip():
        return False, "EMPTY_QUERY"

    # Remove comments (-- single line and /* multiline */)
    clean_sql = re.sub(r"--.*?\n", " ", sql_query)
    clean_sql = re.sub(r"/\*.*?\*/", " ", clean_sql, flags=re.DOTALL)
    clean_sql = clean_sql.strip()

    if not clean_sql:
        return False, "EMPTY_QUERY"

    # Disallow destructive DDL/DML keywords
    destructive_keywords = [
        r"\bINSERT\b",
        r"\bUPDATE\b",
        r"\bDELETE\b",
        r"\bDROP\b",
        r"\bALTER\b",
        r"\bTRUNCATE\b",
        r"\bCREATE\b",
        r"\bMERGE\b",
        r"\bEXEC\b",
        r"\bEXECUTE\b",
        r"\bGRANT\b",
        r"\bREVOKE\b",
        r"\bBACKUP\b",
        r"\bRESTORE\b",
        r"\bSHUTDOWN\b",
    ]

    for pattern in destructive_keywords:
        if re.search(pattern, clean_sql, re.IGNORECASE):
            matched = re.search(pattern, clean_sql, re.IGNORECASE).group(0)
            return False, f"UNSAFE_QUERY: Blocked keyword '{matched}'"

    # Ensure query starts with SELECT or WITH (common table expression)
    first_word_match = re.match(r"^\s*([A-Za-z]+)", clean_sql)
    if not first_word_match:
        return False, "INVALID_QUERY"

    first_word = first_word_match.group(1).upper()
    if first_word not in ("SELECT", "WITH"):
        return False, f"UNSAFE_QUERY: Queries must begin with SELECT or WITH, got '{first_word}'"

    return True, "SAFE"


def extract_full_database_metadata() -> dict[str, dict[str, list[str]]]:
    """Extracts columns, data types, Primary Keys, and Foreign Keys from SQL Server.

    Falls back to embedded offline metadata if SQL Server is not reachable or MOCK_MODE is enabled.
    """
    if MOCK_MODE:
        logger.info("MOCK_MODE enabled. Using offline schema metadata.")
        return OFFLINE_SCHEMA_SAMPLE

    logger.info("Extracting raw schemas and metadata from SQL Server...")
    db_metadata: dict[str, dict[str, list[str]]] = {}

    try:
        import pyodbc
        with pyodbc.connect(DB_CONN_STR, timeout=5) as conn:
            with conn.cursor() as cursor:
                # 1. Fetch Columns and Data Types
                cursor.execute("""
                    SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA NOT IN ('sys', 'INFORMATION_SCHEMA')
                    ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION;
                """)

                for schema_name, table_name, col_name, data_type in cursor.fetchall():
                    full_table_name = f"{schema_name}.{table_name}"
                    if full_table_name not in db_metadata:
                        db_metadata[full_table_name] = {
                            "columns": [],
                            "primary_keys": [],
                            "foreign_keys": [],
                        }
                    db_metadata[full_table_name]["columns"].append(f"{col_name} ({data_type})")

                # 2. Fetch Primary Keys
                cursor.execute("""
                    SELECT kcu.TABLE_SCHEMA, kcu.TABLE_NAME, kcu.COLUMN_NAME
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu 
                        ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME 
                        AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                    WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY' 
                      AND tc.TABLE_SCHEMA NOT IN ('sys', 'INFORMATION_SCHEMA');
                """)

                for schema_name, table_name, col_name in cursor.fetchall():
                    full_table_name = f"{schema_name}.{table_name}"
                    if full_table_name in db_metadata:
                        db_metadata[full_table_name]["primary_keys"].append(col_name)

                # 3. Fetch Foreign Key Relationships
                cursor.execute("""
                    SELECT 
                        OBJECT_SCHEMA_NAME(fkc.parent_object_id) + '.' + OBJECT_NAME(fkc.parent_object_id) AS parent_table,
                        COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS parent_column,
                        OBJECT_SCHEMA_NAME(fkc.referenced_object_id) + '.' + OBJECT_NAME(fkc.referenced_object_id) AS referenced_table,
                        COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS referenced_column
                    FROM sys.foreign_key_columns fkc 
                    WHERE OBJECT_SCHEMA_NAME(fkc.parent_object_id) NOT IN ('sys', 'INFORMATION_SCHEMA');
                """)

                for parent_tbl, parent_col, ref_tbl, ref_col in cursor.fetchall():
                    if parent_tbl in db_metadata:
                        fk_str = f"FK: {parent_col} -> {ref_tbl}({ref_col})"
                        db_metadata[parent_tbl]["foreign_keys"].append(fk_str)

        logger.info("Successfully extracted metadata for %d tables.", len(db_metadata))
        return db_metadata

    except Exception as e:
        logger.warning(
            "Could not connect to SQL Server (%s). Falling back to offline schema sample.", e
        )
        return OFFLINE_SCHEMA_SAMPLE


def execute_and_display_sql(sql_query: str) -> tuple[pd.DataFrame | None, str | None]:
    """Executes a generated T-SQL query against SQL Server or mock engine.

    Returns:
        Tuple of (Pandas DataFrame | None, Error Message | None).
    """
    # 1. Handle special AI sentinel return values
    if sql_query == "INSUFFICIENT_SCHEMA":
        return None, "INSUFFICIENT_SCHEMA"

    if sql_query == "OUT_OF_SCOPE":
        return None, "OUT_OF_SCOPE"

    # 2. Safety Validation
    is_safe, safety_reason = is_safe_sql(sql_query)
    if not is_safe:
        logger.warning("Query rejected by safety validator: %s", safety_reason)
        return None, safety_reason

    # 3. Offline / Mock Execution Support
    if MOCK_MODE:
        logger.info("Executing in MOCK_MODE — returning simulated demo DataFrame.")
        mock_data = {
            "Simulation_Status": ["SUCCESS (Mock Execution)"],
            "Query_Preview": [sql_query.strip().replace("\n", " ")[:60] + "..."],
            "Rows_Found": [42],
            "Note": ["Connected via offline mock demo engine."],
        }
        return pd.DataFrame(mock_data), None

    # 4. Live SQL Server Execution
    try:
        import pyodbc
        logger.info("Executing query against SQL Server...")
        with pyodbc.connect(DB_CONN_STR, timeout=10) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql_query)
                if cursor.description is None:
                    return pd.DataFrame(), None

                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()
                rows_as_tuples = [tuple(row) for row in rows]
                df = pd.DataFrame(rows_as_tuples, columns=columns)
                return df, None

    except Exception as e:
        error_msg = str(e)
        logger.error("SQL Execution Error: %s", error_msg)
        return None, error_msg
