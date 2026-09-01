"""AI Inference Engine for Intent Routing, Schema Summarization, and T-SQL Generation with Self-Healing."""

import logging
import re
from typing import Optional

from config import FAST_MODEL, GROQ_CLIENT, SMART_MODEL

logger = logging.getLogger(__name__)


def is_sql_request(user_query: str) -> bool:
    """Intent Router: Classifies whether the user prompt requests database business data.

    Args:
        user_query: The natural language prompt from the user.

    Returns:
        True if the query is a business/data query, False for greetings/chitchat.
    """
    system_prompt = """
You are a classification router for an enterprise SQL database assistant (AdventureWorks).
Return YES if the prompt asks about: Products, prices, costs, margins, sales, customers, orders, metrics, top items, inventory, employees, departments, vendors, territories.
Return NO if the prompt asks about: Greetings, personal questions, general trivia, casual chat, programming questions, translation, coding advice.

EXAMPLES:
User: "Hi, how are you?" -> NO
User: "What is your name?" -> NO
User: "Which top 10 products have the highest profit margin?" -> YES
User: "How many active customers do we have in Europe?" -> YES

Output ONLY the word YES or NO.
"""
    try:
        response = GROQ_CLIENT.chat.completions.create(
            model=FAST_MODEL,
            messages=[
                {"role": "system", "content": system_prompt.strip()},
                {"role": "user", "content": user_query.strip()},
            ],
            temperature=0.0,
            max_tokens=5,
        )
        content = response.choices[0].message.content.strip().upper()
        return "YES" in content
    except Exception as e:
        logger.warning("Intent routing API call failed (%s), defaulting to True.", e)
        return True


def generate_table_description(table_name: str, columns: list[str]) -> str:
    """Generates a concise, single-sentence business purpose description for a database table.

    Args:
        table_name: Fully qualified table name (e.g. Sales.SalesOrderHeader).
        columns: List of column definitions.

    Returns:
        One-line business description string.
    """
    prompt = f"""
Table Name: {table_name}
Columns: {', '.join(columns[:15])}

Write a SINGLE, concise sentence (maximum 15 words) describing the core business purpose of this database table.
Do NOT use markdown formatting, bullet points, or intro text like "This table...". Just state the purpose directly.
"""
    try:
        response = GROQ_CLIENT.chat.completions.create(
            model=FAST_MODEL,
            messages=[{"role": "user", "content": prompt.strip()}],
            temperature=0.0,
            max_tokens=40,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("Error generating description for %s: %s", table_name, e)
        return f"Stores business data, metrics, and relationships for {table_name}."


def generate_sql_query(
    user_query: str,
    schema_context: str,
    previous_sql: Optional[str] = None,
    previous_error: Optional[str] = None,
) -> str:
    """Sends user question and retrieved schema context to Groq to generate executable T-SQL.

    Supports zero-shot generation and iterative self-healing correction.

    Args:
        user_query: Natural language question.
        schema_context: Formatted string containing retrieved table definitions, PKs, and FKs.
        previous_sql: The failed SQL query if this is a retry attempt.
        previous_error: The database error message if this is a retry attempt.

    Returns:
        Clean, executable T-SQL query or sentinel strings (INSUFFICIENT_SCHEMA, OUT_OF_SCOPE).
    """
    system_prompt = """
You are an expert Microsoft SQL Server (T-SQL) Data Analyst.

Your task is to generate ONE valid, executable, and efficient Microsoft SQL Server (T-SQL) query that answers the user's question using ONLY the provided SCHEMA CONTEXT.

RULES:

1. Use ONLY the tables, columns, primary/foreign key relationships, and semantic information present in the SCHEMA CONTEXT.

2. NEVER invent, assume, rename, or infer:
   - tables
   - columns
   - relationships
   - business rules
   - calculated fields
   - identifiers
   - filter values
   - user-specific information

3. If a requested attribute (e.g. age, birth date, salary, email, address, manager, customer status) does NOT exist in the schema context, DO NOT substitute another column. Return exactly:
INSUFFICIENT_SCHEMA

4. If the user's question cannot be answered completely and correctly using only the provided schema and database contents, return exactly:
INSUFFICIENT_SCHEMA

5. Never fabricate WHERE clauses, IDs, GUIDs, names, dates, or constants.

6. Use the provided Foreign Keys to generate correct JOIN conditions.

7. Follow standard MS SQL semantics for dates, monetary values, and aggregations.

8. Generate Microsoft SQL Server (T-SQL) syntax ONLY. Never use MySQL, PostgreSQL, Oracle, or SQLite syntax.

9. Always use fully qualified schema.table names (e.g., Sales.SalesOrderHeader) and meaningful table aliases.

10. Always qualify column names with table aliases when multiple tables are joined.

11. Return only the columns necessary to answer the question. Never use SELECT *.

12. Use appropriate GROUP BY, HAVING, ORDER BY, TOP, DISTINCT, and aggregate functions whenever required.

13. If the user's request implies ranking, latest, earliest, highest, lowest, top, or bottom results, include the appropriate ORDER BY.

14. If the user's message is a greeting, casual conversation, personal question, opinion request, or anything unrelated to querying the database, return exactly:
OUT_OF_SCOPE

15. Return ONLY one of the following:
    - A valid executable T-SQL query
    - INSUFFICIENT_SCHEMA
    - OUT_OF_SCOPE

Do not include explanations, markdown code blocks, or preamble text.
"""

    if previous_error and previous_sql:
        system_prompt += (
            f"\n\nURGENT CORRECTION REQUIRED:\n"
            f"Your previous query:\n{previous_sql}\n"
            f"Failed with this SQL Server error:\n{previous_error}\n"
            f"Fix ONLY the syntax/join/column errors. Do NOT invent columns. "
            f"If the query cannot be repaired without inventing schema, return INSUFFICIENT_SCHEMA.\n"
        )

    user_message = f"""
SCHEMA CONTEXT:
{schema_context}

USER QUESTION:
{user_query}

Generate only the T-SQL query.
"""

    logger.info(
        "Sending prompt to LLM [%s] (Self-Healing: %s)...",
        SMART_MODEL,
        bool(previous_error),
    )

    try:
        response = GROQ_CLIENT.chat.completions.create(
            model=SMART_MODEL,
            messages=[
                {"role": "system", "content": system_prompt.strip()},
                {"role": "user", "content": user_message.strip()},
            ],
            temperature=0.0,
        )

        raw_sql = response.choices[0].message.content.strip()

        # Clean markdown code blocks if the LLM adds them
        raw_sql = re.sub(r"^```(?:sql)?\s*", "", raw_sql, flags=re.IGNORECASE)
        raw_sql = re.sub(r"\s*```$", "", raw_sql)

        return raw_sql.strip()

    except Exception as e:
        logger.error("Error during SQL generation: %s", e)
        return ""


def fix_sql_query(
    user_question: str,
    failed_query: str,
    error_message: str,
    schema_context: str,
) -> str:
    """Attempts to fix a failed SQL query using the error message from the database."""
    return generate_sql_query(
        user_query=user_question,
        schema_context=schema_context,
        previous_sql=failed_query,
        previous_error=error_message,
    )