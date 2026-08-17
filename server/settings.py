"""Environment-derived settings shared by more than one server module.

Anything read from the environment in two or more places belongs here. Keeping
a second `os.environ.get(..., <default>)` for the same variable elsewhere is how
the modules drift apart: `main` and `feature_services` each carried their own
fallback for MEM0_DEFAULT_LLM_MODEL and disagreed about what it was, so with the
variable unset the API extracted memories with one model and classified them
with another.
"""

import os

# --- Build identity ---------------------------------------------------------

# Baked in at image build time via Docker build args, never read from a file at
# runtime: a running container must report the commit it was built from, not
# whatever happens to be checked out in a mounted working tree.
APP_VERSION = os.environ.get("APP_VERSION", "dev")
GIT_SHA = os.environ.get("GIT_SHA", "unknown")
BUILT_AT = os.environ.get("BUILT_AT", "unknown")

# --- Models -----------------------------------------------------------------

DEFAULT_LLM_MODEL = os.environ.get("MEM0_DEFAULT_LLM_MODEL", "gpt-5.4-nano")
DEFAULT_EMBEDDER_MODEL = os.environ.get("MEM0_DEFAULT_EMBEDDER_MODEL", "text-embedding-3-small")

# Category classification is a harder judgement than extraction, so it may run on
# a stronger model. It falls back to the extraction model rather than to a
# literal, so overriding MEM0_DEFAULT_LLM_MODEL alone never leaves the two split.
CATEGORY_MODEL = os.environ.get("MEM0_CATEGORY_LLM_MODEL") or DEFAULT_LLM_MODEL
CATEGORY_CONFIDENCE_FLOOR = float(os.environ.get("MEM0_CATEGORY_CONFIDENCE_FLOOR", "0.45"))

# --- Database ---------------------------------------------------------------

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "postgres")
APP_DB_NAME = os.environ.get("APP_DB_NAME", "mem0_app")

# Bound how long a single connect attempt may block. Without this psycopg waits
# indefinitely, so an unreachable Postgres turns any caller into a hang instead
# of a prompt error.
POSTGRES_CONNECT_TIMEOUT = int(os.environ.get("POSTGRES_CONNECT_TIMEOUT", "10"))

# --- Webhooks ---------------------------------------------------------------

MAX_WEBHOOK_ATTEMPTS = int(os.environ.get("MEM0_WEBHOOK_MAX_ATTEMPTS", "5"))
WEBHOOK_TIMEOUT_SECONDS = int(os.environ.get("MEM0_WEBHOOK_TIMEOUT_SECONDS", "8"))

# --- Retention --------------------------------------------------------------


def _optional_int(name: str) -> int | None:
    """Read an int that is allowed to be unset or blank, rather than defaulting.

    Retention is destructive, so an unset value must mean "keep everything", not
    "apply some default cutoff".
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


REQUEST_LOG_RETENTION_DAYS = _optional_int("REQUEST_LOG_RETENTION_DAYS")
