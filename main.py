"""Main CLI entrypoint for OmniQuery AI — Natural Language to SQL Assistant."""

import argparse
import os
import sys
import time
import pandas as pd

from config import FAST_MODEL, MOCK_MODE, QDRANT_PATH, SMART_MODEL
from vector_store.qdrant_db import build_vector_db, retrieve_relevant_schemas
from ai_engine.llm import is_sql_request, generate_sql_query, fix_sql_query
from database.sql_server import execute_and_display_sql


def process_query(user_question: str, top_k: int = 12, max_retries: int = 3) -> None:
    """Runs the 4-stage pipeline for a single natural language question."""
    print(f"\n[?] Question: {user_question}")
    start_time = time.time()

    # 1. Intent Routing
    if not is_sql_request(user_question):
        print("\n[!] Out of Scope: I can only answer questions regarding business database schemas.")
        return

    # 2. Retrieve Relevant Schemas (Hybrid Search: Dense + BM25)
    print("\n🔍 Retrieving relevant schemas via Hybrid Vector Search (Qdrant)...")
    schema_context, matched_tables = retrieve_relevant_schemas(user_question, top_k=top_k)

    if not schema_context:
        print("[!] Could not retrieve relevant tables from vector database.")
        return

    print(f"✅ Retrieved {len(matched_tables)} relevant tables: {', '.join(matched_tables[:6])}{'...' if len(matched_tables) > 6 else ''}")

    # 3. Generate SQL
    print(f"🤖 Generating T-SQL with Groq ({SMART_MODEL})...")
    sql_query = generate_sql_query(user_question, schema_context)

    # 4. Execute & Self-Healing Loop
    attempt = 1
    while attempt <= max_retries:
        print("\n" + "=" * 60)
        print(f"📝 Generated T-SQL (Attempt {attempt}/{max_retries}):")
        print("=" * 60)
        print(sql_query)
        print("=" * 60)

        df, error_msg = execute_and_display_sql(sql_query)

        if df is not None:
            elapsed = time.time() - start_time
            if df.empty:
                print(f"\n⚡ Query executed successfully in {elapsed:.2f}s (Returned 0 rows).")
            else:
                print(f"\n📊 Query Results ({len(df)} rows found in {elapsed:.2f}s):")
                print("-" * 60)
                try:
                    print(df.head(20).to_markdown(index=False))
                except Exception:
                    print(df.head(20).to_string(index=False))
                if len(df) > 20:
                    print(f"... and {len(df) - 20} more rows.")
            break

        else:
            if error_msg in ["INSUFFICIENT_SCHEMA", "OUT_OF_SCOPE", "EMPTY_QUERY"] or str(error_msg).startswith("UNSAFE_QUERY"):
                print(f"\n[!] Guardrail Intervention: {error_msg}")
                break

            print(f"\n[!] Database Error on Attempt {attempt}: {error_msg}")
            if attempt < max_retries:
                print(f"🔄 Engaging Self-Healing Loop (Attempting automatic repair via {SMART_MODEL})...")
                sql_query = fix_sql_query(user_question, sql_query, error_msg, schema_context)
            else:
                print(f"\n❌ Max retries ({max_retries}) reached. Query could not be repaired.")

        attempt += 1


def main() -> None:
    """CLI argument parser and main execution loop."""
    parser = argparse.ArgumentParser(
        description="OmniQuery AI — Enterprise Hybrid RAG Text-to-SQL Engine with Self-Healing"
    )
    parser.add_argument(
        "-q", "--query",
        type=str,
        help="Run a single question non-interactively and exit.",
    )
    parser.add_argument(
        "-r", "--rebuild",
        action="store_true",
        help="Force rebuild the vector database index from database metadata.",
    )
    parser.add_argument(
        "-m", "--mock",
        action="store_true",
        help="Run in offline mock mode (simulated execution without live SQL Server).",
    )
    parser.add_argument(
        "-k", "--top-k",
        type=int,
        default=12,
        help="Number of table schemas to retrieve for context (default: 12).",
    )

    args = parser.parse_args()

    if args.mock:
        os.environ["MOCK_MODE"] = "true"

    # Handle explicit vector DB rebuild
    if args.rebuild:
        print("[*] Rebuilding Vector Database...")
        build_vector_db()
        if not args.query:
            return

    # Check if vector DB needs initialization
    if not os.path.exists(QDRANT_PATH):
        print("[*] Initializing Vector Database for first-time use...")
        build_vector_db()

    # Non-interactive single query mode
    if args.query:
        process_query(args.query, top_k=args.top_k)
        return

    # Interactive REPL Loop
    print("\n" + "=" * 60)
    print("  🚀 OmniQuery AI — Enterprise Text-to-SQL Assistant")
    print(f"  🧠 Router: {FAST_MODEL} | Generator: {SMART_MODEL}")
    print(f"  💾 Mode: {'OFFLINE MOCK DEMO' if os.getenv('MOCK_MODE') == 'true' else 'LIVE SQL SERVER'}")
    print("=" * 60)
    print("Commands: 'exit' to quit | 'rebuild' to re-index | 'help' for info\n")

    while True:
        try:
            user_question = input("\n💬 Ask a data question: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting. Goodbye!")
            break

        if not user_question:
            continue

        if user_question.lower() in ("exit", "quit", "q"):
            print("Goodbye!")
            break

        if user_question.lower() == "rebuild":
            print("[*] Rebuilding Vector Database...")
            build_vector_db()
            continue

        if user_question.lower() == "help":
            print("""
Sample Questions:
  - "Which top 10 products have generated the highest total revenue?"
  - "List all sales representatives and their current bonus amounts."
  - "Show me the top 5 customers with the most orders in 2024."
  - "What are the names and categories of products with zero inventory?"
            """)
            continue

        process_query(user_question, top_k=args.top_k)


if __name__ == "__main__":
    main()