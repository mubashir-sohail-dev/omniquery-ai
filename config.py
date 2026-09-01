"""Centralized configuration for OmniQuery AI — Natural Language to SQL Assistant."""

import os
import logging
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

# --- LOGGING CONFIGURATION ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("omniquery")

# --- SQL SERVER CONFIGURATION ---
DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
DB_SERVER = os.getenv("DB_SERVER", r"localhost\SQLEXPRESS")
DB_NAME = os.getenv("DB_NAME", "AdventureWorks2025")
DB_TRUSTED_CONNECTION = os.getenv("DB_TRUSTED_CONNECTION", "yes")
DB_ENCRYPT = os.getenv("DB_ENCRYPT", "yes")
DB_TRUST_SERVER_CERTIFICATE = os.getenv("DB_TRUST_SERVER_CERTIFICATE", "yes")
DB_USER = os.getenv("DB_USER", None)
DB_PASSWORD = os.getenv("DB_PASSWORD", None)

if DB_USER and DB_PASSWORD:
    DB_CONN_STR = (
        f"Driver={{{DB_DRIVER}}};"
        f"Server={DB_SERVER};"
        f"Database={DB_NAME};"
        f"Uid={DB_USER};"
        f"Pwd={DB_PASSWORD};"
        f"Encrypt={DB_ENCRYPT};"
        f"TrustServerCertificate={DB_TRUST_SERVER_CERTIFICATE};"
    )
else:
    DB_CONN_STR = (
        f"Driver={{{DB_DRIVER}}};"
        f"Server={DB_SERVER};"
        f"Database={DB_NAME};"
        f"Trusted_Connection={DB_TRUSTED_CONNECTION};"
        f"Encrypt={DB_ENCRYPT};"
        f"TrustServerCertificate={DB_TRUST_SERVER_CERTIFICATE};"
    )

# --- OFFLINE / MOCK MODE ---
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() in ("true", "1", "yes")

# --- AI & LLM CONFIGURATION ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

def get_groq_client() -> Groq:
    """Returns an authenticated Groq client instance."""
    if not GROQ_API_KEY:
        logger.warning(
            "GROQ_API_KEY is not set in environment or .env file. "
            "LLM API calls will fail unless provided."
        )
    return Groq(api_key=GROQ_API_KEY)

GROQ_CLIENT = get_groq_client()

FAST_MODEL = os.getenv("FAST_MODEL", "llama-3.1-8b-instant")      # Routing & Descriptions
SMART_MODEL = os.getenv("SMART_MODEL", "llama-3.3-70b-versatile")  # SQL Generation & Self-Healing

# --- VECTOR DB CONFIGURATION ---
QDRANT_PATH = os.getenv("QDRANT_PATH", "./qdrant_db")
CACHE_FILE = os.getenv("CACHE_FILE", "table_descriptions.json")
COLLECTION_NAME = "adventureworks_schema"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
SPARSE_MODEL = "Qdrant/bm25"