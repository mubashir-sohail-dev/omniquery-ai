"""Qdrant Vector Database module with Hybrid Dense + Sparse BM25 Search."""

import json
import logging
import os
import uuid
import warnings
from typing import Tuple, List

from qdrant_client import QdrantClient

from config import (
    CACHE_FILE,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    QDRANT_PATH,
    SPARSE_MODEL,
)
from database.sql_server import extract_full_database_metadata
from ai_engine.llm import generate_table_description

warnings.filterwarnings("ignore", category=UserWarning, module="qdrant_client")
logger = logging.getLogger(__name__)


def get_qdrant_client() -> QdrantClient:
    """Initializes the Qdrant embedded client with Dense and Sparse BM25 models."""
    os.makedirs(QDRANT_PATH, exist_ok=True)
    client = QdrantClient(path=QDRANT_PATH)
    client.set_model(EMBEDDING_MODEL)
    client.set_sparse_model(SPARSE_MODEL)
    return client


def build_vector_db() -> None:
    """Extracts database metadata, generates 1-line business summaries, and indexes schema into Qdrant."""
    raw_metadata = extract_full_database_metadata()
    total_tables = len(raw_metadata)

    # 1. Load or initialize description cache
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                descriptions_cache = json.load(f)
        except Exception as e:
            logger.warning("Could not read cache file %s (%s). Recreating.", CACHE_FILE, e)
            descriptions_cache = {}
    else:
        descriptions_cache = {}

    logger.info("Extracted %d tables. Indexing schema into Qdrant...", total_tables)
    client = get_qdrant_client()

    # Rebuild collection cleanly
    if client.collection_exists(collection_name=COLLECTION_NAME):
        logger.info("Dropping existing collection '%s' to rebuild...", COLLECTION_NAME)
        client.delete_collection(collection_name=COLLECTION_NAME)

    ids: list[str] = []
    documents: list[str] = []
    payloads: list[dict] = []

    for index, (table_name, data) in enumerate(raw_metadata.items(), 1):
        # 2. Fetch from cache or generate description via LLM
        if table_name in descriptions_cache:
            description = descriptions_cache[table_name]
        else:
            logger.info("[%d/%d] Generating description for: %s...", index, total_tables, table_name)
            description = generate_table_description(table_name, data["columns"])
            descriptions_cache[table_name] = description

        columns_formatted = "\n".join([f"  - {col}" for col in data["columns"]])
        pks_formatted = ", ".join(data.get("primary_keys", [])) if data.get("primary_keys") else "None"
        fks_formatted = "\n".join([f"  - {fk}" for fk in data["foreign_keys"]]) if data.get("foreign_keys") else "  - None"

        # 3. SEARCH document (Indexed by Qdrant Dense + BM25 FastEmbed)
        search_document = (
            f"Table Name: {table_name}\n"
            f"Description: {description}\n"
            f"Columns:\n{columns_formatted}\n"
            f"Foreign Keys:\n{fks_formatted}"
        )

        # 4. RAW SCHEMA payload (Sent to Groq LLM to generate T-SQL)
        raw_schema_payload = (
            f"Table: {table_name}\n"
            f"Description: {description}\n"
            f"Primary Key(s): {pks_formatted}\n"
            f"Columns:\n{columns_formatted}\n"
            f"Foreign Keys:\n{fks_formatted}"
        )

        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, table_name))
        ids.append(point_id)
        documents.append(search_document)
        payloads.append({
            "table_name": table_name,
            "raw_schema": raw_schema_payload,
        })

    # Save cached descriptions to disk
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(descriptions_cache, f, indent=4)
    except Exception as e:
        logger.warning("Could not persist cache file %s: %s", CACHE_FILE, e)

    logger.info("Embedding and upserting %d tables into Qdrant...", len(documents))
    client.add(
        collection_name=COLLECTION_NAME,
        documents=documents,
        metadata=payloads,
        ids=ids,
    )
    logger.info("Vector Database successfully indexed at %s", QDRANT_PATH)


def retrieve_relevant_schemas(user_query: str, top_k: int = 10) -> Tuple[str, List[str]]:
    """Searches Qdrant using Hybrid Search (Dense + Sparse BM25).

    Returns:
        Tuple of (combined_schema_context: str, retrieved_table_names: list[str]).
    """
    client = get_qdrant_client()

    if not client.collection_exists(collection_name=COLLECTION_NAME):
        logger.info("Collection '%s' not found. Building vector database...", COLLECTION_NAME)
        build_vector_db()

    results = client.query(
        collection_name=COLLECTION_NAME,
        query_text=user_query,
        limit=top_k,
    )

    if not results:
        logger.warning("No matching tables found in Vector DB for query: '%s'", user_query)
        return "", []

    schemas = []
    retrieved_table_names = []

    for point in results:
        schemas.append(point.metadata["raw_schema"])
        retrieved_table_names.append(point.metadata["table_name"])

    separator = "\n\n" + ("=" * 40) + "\n\n"
    combined_schema_context = separator.join(schemas)

    return combined_schema_context, retrieved_table_names
