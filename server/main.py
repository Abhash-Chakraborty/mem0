import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import telemetry
from auth import ADMIN_API_KEY, AUTH_DISABLED, JWT_SECRET, require_admin, verify_auth
from db import SessionLocal
from dotenv import load_dotenv
from errors import (
    UpstreamError,
    install_request_id_logging,
    new_request_id,
    request_id_var,
    upstream_error,
    upstream_error_handler,
)
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from rate_limit import limiter
from routers import api_keys as api_keys_router
from routers import auth as auth_router
from routers import analytics as analytics_router
from routers import backups as backups_router
from routers import system as system_router
from routers import categories as categories_router
from routers import entities as entities_router
from routers import export as export_router
from routers import dream as dream_router
from routers import graph as graph_router
from routers import lifecycle as lifecycle_router
from routers import organizations as organizations_router
from routers import requests as requests_router
from routers import webhooks as webhooks_router
import backup_services
import log_stream
import settings
from schemas import MessageResponse
from server_state import (
    get_current_config,
    get_memory_instance,
    initialize_state,
    set_session_factory,
    update_config,
)
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from feature_services import (
    apply_auto_add_categories,
    classify_memory,
    enqueue_webhook_event,
    process_due_webhooks,
)
import dream_scheduler
import dream_services
import identity
import lifecycle_services
import project_settings
import request_trace
import retention_services
import trace_retention
from db import get_db
from models import MemoryCategory, Project, RequestLog, User
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from tenancy import (
    Scope,
    entity_filters,
    overfetch,
    require_role,
    require_scope,
    scope_results,
    scoped_metadata,
    visible_to,
)

from mem0.exceptions import ValidationError as Mem0ValidationError

load_dotenv()

install_request_id_logging()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - [%(request_id)s] %(message)s")

MIN_KEY_LENGTH = 16
SENSITIVE_CONFIG_KEYS = {
    "admin_api_key",
    "api_key",
    "authorization",
    "jwt_secret",
    "password",
    "password_hash",
    "secret",
    "token",
}
SKIPPED_REQUEST_LOG_PATHS = {"/api/health", "/docs", "/redoc", "/openapi.json"}
SKIPPED_REQUEST_LOG_PREFIXES = ("/requests",)
# Beyond this a response is logged as a trace with no result digest. The cap is
# on what is read into memory, not on what is stored - redaction.capture applies
# its own, smaller limit afterwards.
MAX_LOGGED_RESPONSE_BYTES = 1024 * 1024

BUNDLED_LLM_PROVIDERS = ("openai", "anthropic", "gemini")
BUNDLED_EMBEDDER_PROVIDERS = ("openai", "gemini")


def _warn_if_unconfigured() -> None:
    """Pre-auth deployments upgrading into this build will 401 everywhere until
    an admin key or admin user exists. Surface the fix before the support tickets."""
    try:
        with SessionLocal() as session:
            if session.scalar(select(func.count(User.id))) > 0:
                return
    except Exception:
        return

    logging.warning(
        "\n%s\n"
        "  Auth is enabled by default and this server has no admin configured.\n"
        "  Protected endpoints will return 401 until you either:\n"
        "    1. Set ADMIN_API_KEY=<long-random-value>  (fastest, no client changes)\n"
        "    2. Register an admin at http://<host>:3000/setup\n"
        "    3. Set AUTH_DISABLED=true                 (local development only)\n"
        "  Docs: https://docs.mem0.ai/open-source/features/rest-api#authentication\n"
        "%s",
        "=" * 72,
        "=" * 72,
    )


if not AUTH_DISABLED and not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET is required. Set it in .env (generate with `openssl rand -base64 48`) "
        "or set AUTH_DISABLED=true for local development only."
    )

if AUTH_DISABLED:
    logging.warning("AUTH_DISABLED is enabled. Protected endpoints are open for local development only.")
elif ADMIN_API_KEY and len(ADMIN_API_KEY) < MIN_KEY_LENGTH:
    logging.warning(
        "ADMIN_API_KEY is shorter than %d characters - consider using a longer key for production.",
        MIN_KEY_LENGTH,
    )
elif not ADMIN_API_KEY:
    _warn_if_unconfigured()

telemetry.log_status()

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "postgres")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "postgres")
POSTGRES_COLLECTION_NAME = os.environ.get("POSTGRES_COLLECTION_NAME", "memories")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
HISTORY_DB_PATH = os.environ.get("HISTORY_DB_PATH", "/app/history/history.db")
DEFAULT_LLM_MODEL = settings.DEFAULT_LLM_MODEL
DEFAULT_EMBEDDER_MODEL = settings.DEFAULT_EMBEDDER_MODEL

DEFAULT_CONFIG = {
    "version": "v1.1",
    "vector_store": {
        "provider": "pgvector",
        "config": {
            "host": POSTGRES_HOST,
            "port": int(POSTGRES_PORT),
            "dbname": POSTGRES_DB,
            "user": POSTGRES_USER,
            "password": POSTGRES_PASSWORD,
            "collection_name": POSTGRES_COLLECTION_NAME,
        },
    },
    "llm": {
        "provider": "openai",
        "config": {"api_key": OPENAI_API_KEY, "temperature": 0.2, "model": DEFAULT_LLM_MODEL},
    },
    "embedder": {"provider": "openai", "config": {"api_key": OPENAI_API_KEY, "model": DEFAULT_EMBEDDER_MODEL}},
    "history_db_path": HISTORY_DB_PATH,
}


set_session_factory(SessionLocal)
initialize_state(DEFAULT_CONFIG)


app = FastAPI(
    title="Mem0 REST APIs",
    description=(
        "A REST API for managing and searching memories for your AI Agents and Apps.\n\n"
        "## Authentication\n"
        "Supports Bearer JWT tokens, per-user API keys via `X-API-Key` header, "
        "or the legacy `ADMIN_API_KEY` environment variable. Set `AUTH_DISABLED=true` for local development only."
    ),
    version="1.0.0",
    redirect_slashes=False,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(UpstreamError, upstream_error_handler)
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[DASHBOARD_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(organizations_router.router)
app.include_router(api_keys_router.router)
app.include_router(entities_router.router)
app.include_router(dream_router.router)
app.include_router(graph_router.router)
# Before the memory routes in main: /memories/{id}/lifecycle must not be
# swallowed by /memories/{memory_id}.
app.include_router(lifecycle_router.router)
app.include_router(requests_router.router)
app.include_router(categories_router.router)
app.include_router(webhooks_router.router)
app.include_router(analytics_router.router)
app.include_router(export_router.router)
app.include_router(backups_router.router)
app.include_router(system_router.router)


async def _webhook_retry_loop() -> None:
    while True:
        await asyncio.sleep(15)
        try:
            await asyncio.get_running_loop().run_in_executor(None, process_due_webhooks, SessionLocal)
        except Exception:
            logging.exception("Failed to process due webhooks")


@app.on_event("startup")
async def start_webhook_retry_loop() -> None:
    asyncio.create_task(_webhook_retry_loop())


async def _backup_schedule_loop() -> None:
    """Take a backup when one is due.

    Checked every 15 minutes rather than slept for the full interval, so an
    instance that is restarted more often than its backup interval still gets
    backed up instead of never reaching the end of a sleep.
    """
    while True:
        await asyncio.sleep(900)
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, backup_services.run_scheduled_backup, SessionLocal
            )
        except Exception:
            logging.exception("Scheduled backup check failed")
        # Sweeping traces on the same tick as the backup check keeps the number
        # of background loops down; both are cheap no-ops when nothing is due.
        try:
            await asyncio.get_running_loop().run_in_executor(None, trace_retention.run_sweep, SessionLocal)
        except Exception:
            logging.exception("Trace retention sweep failed")
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, retention_services.run_expiry_sweep, SessionLocal, get_memory_instance
            )
        except Exception:
            logging.exception("Expiry sweep failed")


async def _dream_schedule_loop() -> None:
    """Run due synthesis passes.

    Woken every 15 minutes rather than sleeping a full cadence window, so an
    instance restarted more often than its cadence still synthesises instead of
    never reaching the end of a sleep - the same reasoning as the backup loop.
    """
    while True:
        await asyncio.sleep(900)
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, dream_scheduler.run_due_synthesis, SessionLocal, get_memory_instance
            )
        except Exception:
            logging.exception("Dream synthesis sweep failed")


@app.on_event("startup")
async def start_dream_schedule_loop() -> None:
    asyncio.create_task(_dream_schedule_loop())


@app.on_event("startup")
async def start_backup_schedule_loop() -> None:
    if backup_services.SCHEDULE_INTERVAL_HOURS > 0:
        logging.info(
            "Automatic backups enabled: every %d hour(s), keeping %d.",
            backup_services.SCHEDULE_INTERVAL_HOURS,
            backup_services.RETENTION_COUNT,
        )
        asyncio.create_task(_backup_schedule_loop())


@app.on_event("startup")
async def start_log_stream() -> None:
    """Capture logs for the dashboard's log view.

    The handler is installed here rather than at import time so it binds to the
    loop that will actually serve the SSE subscribers.
    """
    log_stream.bind_loop(asyncio.get_running_loop())
    log_stream.install()


class Message(BaseModel):
    role: str = Field(..., description="Role of the message (user or assistant).")
    content: str = Field(..., description="Message content.")


class MemoryCreate(BaseModel):
    messages: List[Message] = Field(..., description="List of messages to store.")
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    expiration_date: Optional[str] = Field(None, description="Expiration date in YYYY-MM-DD format.")
    infer: Optional[bool] = Field(None, description="Whether to extract facts from messages. Defaults to True.")
    memory_type: Optional[str] = Field(None, description="Type of memory to store (e.g. 'core').")
    prompt: Optional[str] = Field(None, description="Custom prompt to use for fact extraction.")


class MemoryUpdate(BaseModel):
    text: Optional[str] = Field(None, description="New content to update the memory with.")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Metadata to update.")
    expiration_date: Optional[str] = Field(None, description="Expiration date in YYYY-MM-DD format, or null to clear.")


class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query.")
    latest_only: Optional[bool] = Field(
        None, description="Exclude memories that have been superseded or merged away."
    )
    include_merged: Optional[bool] = Field(
        None, description="Include memories that were merged into another."
    )
    user_id: Optional[str] = Field(None, description="Deprecated: pass inside `filters` instead.", deprecated=True)
    run_id: Optional[str] = Field(None, description="Deprecated: pass inside `filters` instead.", deprecated=True)
    agent_id: Optional[str] = Field(None, description="Deprecated: pass inside `filters` instead.", deprecated=True)
    filters: Optional[Dict[str, Any]] = None
    top_k: Optional[int] = Field(None, description="Maximum number of results to return.")
    threshold: Optional[float] = Field(None, description="Minimum similarity score for results.")
    explain: Optional[bool] = Field(None, description="Include score details for each search result.")
    show_expired: Optional[bool] = Field(None, description="Include expired memories.")


class GenerateInstructionsRequest(BaseModel):
    use_case: str = Field(..., description="Description of what the user will use Mem0 for.")


def _client_error(exc: Exception) -> HTTPException:
    """Map core validation / not-found errors to 4xx so clients can tell a bad
    request from an upstream outage. 'not found' is a 404, everything else a 400."""
    detail = str(exc)
    status_code = 404 if isinstance(exc, ValueError) and "not found" in detail.lower() else 400
    return HTTPException(status_code=status_code, detail=detail)


def _redact_config(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {item_key: _redact_config(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact_config(item_value, key) for item_value in value]
    if key is not None and key.lower() in SENSITIVE_CONFIG_KEYS:
        return "[redacted]" if value else value
    return value


def _validate_bundled_providers(config: Dict[str, Any]) -> None:
    llm = config.get("llm")
    if isinstance(llm, dict) and (provider := llm.get("provider")) and provider not in BUNDLED_LLM_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"LLM provider '{provider}' is not bundled in this image. "
                f"Bundled providers: {', '.join(BUNDLED_LLM_PROVIDERS)}. "
                "To use another provider, install its Python package, rebuild the container, "
                "and extend BUNDLED_LLM_PROVIDERS in server/main.py."
            ),
        )

    embedder = config.get("embedder")
    if (
        isinstance(embedder, dict)
        and (provider := embedder.get("provider"))
        and provider not in BUNDLED_EMBEDDER_PROVIDERS
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Embedder provider '{provider}' is not bundled in this image. "
                f"Bundled providers: {', '.join(BUNDLED_EMBEDDER_PROVIDERS)}. "
                "To use another provider, install its Python package, rebuild the container, "
                "and extend BUNDLED_EMBEDDER_PROVIDERS in server/main.py."
            ),
        )


def _should_log_request(request: Request) -> bool:
    if request.method == "OPTIONS":
        return False
    path = request.url.path
    if path in SKIPPED_REQUEST_LOG_PATHS:
        return False
    return not path.startswith(SKIPPED_REQUEST_LOG_PREFIXES)


def _persist_request_log(row: Dict[str, Any]) -> None:
    """Write one trace. Runs on a worker thread, after the response has gone out.

    Swallows everything: a log that can fail a request is worse than no log.
    """
    session = SessionLocal()
    try:
        session.add(RequestLog(**row))
        session.commit()
    except Exception:
        session.rollback()
        logging.exception("Failed to persist request log")
    finally:
        session.close()


def _build_and_persist(row: Dict[str, Any], trace_input: Optional[Dict[str, Any]]) -> None:
    """Assemble the trace and write it, both off the request path."""
    if trace_input is not None:
        row.update(request_trace.build_trace(**trace_input))
    _persist_request_log(row)


async def _read_response_body(response) -> tuple[bytes, Any]:
    """Drain a streamed response so it can be logged, and hand back a replayable body.

    BaseHTTPMiddleware always hands back a streaming response, so there is no
    way to read the body without consuming the iterator. Callers must use the
    returned bytes to build a fresh response - the original is spent.
    """
    chunks = []
    total = 0
    async for chunk in response.body_iterator:
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_LOGGED_RESPONSE_BYTES:
            break
    body = b"".join(chunks)
    return body, response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request.state.auth_type = getattr(request.state, "auth_type", "none")
    rid = new_request_id()
    token = request_id_var.set(rid)
    start = time.perf_counter()
    status_code = 500
    response = None

    # Streaming endpoints are never buffered: a stream held in memory so it can
    # be logged is a stream that no longer streams.
    trace_wanted = _should_log_request(request) and not request_trace.is_streaming(request.url.path)

    request_body = b""
    if trace_wanted and request.method in ("POST", "PUT", "PATCH"):
        # Starlette caches this on the request, so downstream handlers still
        # read the body normally.
        try:
            request_body = await request.body()
        except Exception:
            request_body = b""

    response_body = b""
    try:
        response = await call_next(request)
        status_code = response.status_code
        if trace_wanted:
            response_body, response = await _read_response_body(response)
            response = Response(
                content=response_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        response.headers["X-Request-ID"] = rid
        return response
    except Exception:
        status_code = 500
        raise
    finally:
        request_id_var.reset(token)
        if _should_log_request(request):
            row: Dict[str, Any] = {
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "latency_ms": round((time.perf_counter() - start) * 1000, 2),
                "auth_type": getattr(request.state, "auth_type", "none"),
                "request_id": rid,
                "project_id": getattr(request.state, "scope_project_id", None),
            }
            trace_input = (
                {
                    "method": request.method,
                    "path": request.url.path,
                    "query_params": dict(request.query_params),
                    "headers": request.headers,
                    "request_body": request_body,
                    "response_body": response_body,
                    "status_code": status_code,
                }
                if trace_wanted
                else None
            )
            asyncio.get_running_loop().run_in_executor(None, _build_and_persist, row, trace_input)


@app.get("/configure", summary="Get current Mem0 configuration")
def get_config(_auth=Depends(verify_auth)):
    return _redact_config(get_current_config())


@app.get("/configure/providers", summary="List bundled LLM and embedder providers")
def list_bundled_providers(_auth=Depends(verify_auth)):
    return {"llm": list(BUNDLED_LLM_PROVIDERS), "embedder": list(BUNDLED_EMBEDDER_PROVIDERS)}


@app.post("/configure", summary="Configure Mem0")
def set_config(config: Dict[str, Any], _auth=Depends(require_admin)):
    """Set memory configuration. Requires admin role."""
    _validate_bundled_providers(config)
    update_config(config)
    return {"message": "Configuration set successfully"}


@app.post("/generate-instructions", summary="Generate custom instructions from a use case")
def generate_instructions(req: GenerateInstructionsRequest, _auth=Depends(verify_auth)):
    """Generate custom instructions and a contextual test message tailored to a use case."""
    try:
        llm = get_memory_instance().llm
        prompt = (
            "You are configuring a memory system. Given the use case below, produce two things:\n"
            "1. INSTRUCTIONS: A short paragraph of custom instructions telling the memory extraction system "
            "what kinds of facts, preferences, and context to prioritize. Be specific to the use case.\n"
            "2. TEST_MESSAGE: A single realistic sentence a user in this use case would say, suitable for "
            "testing that the memory system works.\n\n"
            "Respond in exactly this format (no markdown, no extra text):\n"
            "INSTRUCTIONS: <your instructions>\n"
            f"TEST_MESSAGE: <your test message>\n\nUse case: {req.use_case}"
        )
        response = llm.generate_response([{"role": "user", "content": prompt}])
        instructions = response
        test_message = "I like to hike on weekends."
        if "INSTRUCTIONS:" in response and "TEST_MESSAGE:" in response:
            parts = response.split("TEST_MESSAGE:")
            instructions = parts[0].replace("INSTRUCTIONS:", "").strip()
            test_message = parts[1].strip()
        return {"custom_instructions": instructions, "test_message": test_message}
    except Exception:
        raise upstream_error()


@app.post("/memories", summary="Create memories")
def add_memory(
    memory_create: MemoryCreate,
    scope: Scope = Depends(require_role("member")),
    db: Session = Depends(get_db),
):
    """Store new memories in the caller's project, under its extraction settings."""
    if not any([memory_create.user_id, memory_create.agent_id, memory_create.run_id]):
        raise HTTPException(status_code=400, detail="At least one identifier (user_id, agent_id, run_id) is required.")

    params = {k: v for k, v in memory_create.model_dump().items() if v is not None and k != "messages"}
    metadata = scoped_metadata(scope, memory_create.metadata)
    # Linked identifiers are collapsed on write, so new memories stop
    # fragmenting across a person's channels. The identifier the caller sent is
    # kept under metadata.source_entity_id - nothing is lost, but the stored
    # payload is not what was sent, which the link dialog says explicitly.
    params["metadata"] = identity.apply_to_write(db, scope.project_id, params, metadata)
    apply_project_settings(db, scope, memory_create, params)
    try:
        response = get_memory_instance().add(messages=[m.model_dump() for m in memory_create.messages], **params)
        if response.get("results"):
            telemetry.log_dashboard_nudge_once(DASHBOARD_URL)
            with SessionLocal() as session:
                for memory in response.get("results", []):
                    try:
                        classify_memory(session, memory, scope.project_id)
                    except Exception:
                        logging.warning("Failed to classify memory %s", memory.get("id"), exc_info=True)
                    try:
                        apply_auto_add_categories(session, memory, scope.project_id)
                    except Exception:
                        logging.warning("Failed to auto-add categories for memory %s", memory.get("id"), exc_info=True)
                    try:
                        enqueue_webhook_event(session, "memory.created", {"memory": memory})
                    except Exception:
                        logging.warning("Failed to enqueue memory.created webhook", exc_info=True)
            _dispatch_curation(response.get("results", []), scope, params.get("filters") or _entity_scope(params))
        return JSONResponse(content=response)
    except (ValueError, Mem0ValidationError) as e:
        raise _client_error(e)
    except Exception:
        raise upstream_error()


def apply_project_settings(
    db: Session,
    scope: Scope,
    request_body: "MemoryCreate",
    params: Dict[str, Any],
) -> None:
    """Fold the project's extraction and retention settings into an add.

    Both are defaults, not overrides: an explicit `prompt` or `expiration_date`
    on the request always wins. A project setting that silently overrode what
    the caller asked for would make the API unpredictable from the client side.

    Mutates `params` rather than returning, because the caller has already
    assembled it from the request body and a second merge step would be one
    more place for the two to disagree.
    """
    project = db.get(Project, scope.project_id)
    if project is None:
        return
    settings_blob = project.settings or {}

    if "prompt" not in params:
        prompt = project_settings.extraction_prompt(
            settings_blob,
            has_user=bool(request_body.user_id),
            has_agent=bool(request_body.agent_id),
        )
        if prompt:
            params["prompt"] = prompt

    extraction = project_settings.section(settings_blob, "extraction")
    if "infer" not in params and extraction.get("infer") is False:
        params["infer"] = False

    if "expiration_date" not in params:
        days = project_settings.section(settings_blob, "retention").get("default_expiration_days")
        if isinstance(days, int) and days > 0:
            expires = datetime.now(timezone.utc).date() + timedelta(days=days)
            params["expiration_date"] = expires.isoformat()



def _apply_decay(db: Session, scope: Scope, response: Any, top_k: Optional[int]) -> Any:
    """Re-rank by recency of use, when the project has decay switched on.

    Runs last, after scope and lifecycle filtering, so it only reorders results
    the caller was going to see anyway. With decay off it is a straight
    truncation, which keeps the two paths identical apart from the ordering.
    """
    project = db.get(Project, scope.project_id) if scope.project_id else None
    if project is None or not retention_services.enabled(project.settings):
        if top_k is not None and isinstance(response, dict) and isinstance(response.get("results"), list):
            return {**response, "results": response["results"][:top_k]}
        return response
    return retention_services.rerank(db, response, top_k)


def _entity_scope(params: Dict[str, Any]) -> Dict[str, Any]:
    """The entity filter to look for neighbours within.

    Curation compares a new memory only against memories about the same entity.
    Without this bound it would compare across everyone in the project, which is
    both expensive and wrong - two people can hold contradictory facts without
    either being out of date.
    """
    return {
        key: params[key]
        for key in ("user_id", "agent_id", "run_id")
        if params.get(key)
    }


def _dispatch_curation(results: List[Dict[str, Any]], scope: Scope, filters: Dict[str, Any]) -> None:
    """Hand new memories to Dream, off the request path.

    Fire-and-forget on the shared executor, the same place the webhook and
    classification hooks already run. An add must not wait for curation, and
    curation failing must not fail the add.
    """
    if not filters:
        return
    for memory in results:
        if not isinstance(memory, dict) or not memory.get("id"):
            continue
        try:
            asyncio.get_running_loop().run_in_executor(
                None,
                dream_services.curate_new_memory,
                SessionLocal,
                memory,
                scope.project_id,
                filters,
                get_memory_instance().search,
            )
        except Exception:
            logging.warning("Failed to dispatch Dream curation", exc_info=True)


def _expanded_filters(db: Session, scope: Scope, filters: Dict[str, Any]) -> Optional[Dict[str, list]]:
    """Alias expansions for an entity filter, or None when nothing is linked.

    Returns None rather than a single-element mapping in the common case so the
    caller can take the plain, one-query path. Only a filter that actually spans
    several identifiers is worth fanning out for.
    """
    field_to_type = {"user_id": "user", "agent_id": "agent", "run_id": "run"}
    expansions: Dict[str, list] = {}
    fanned = False
    for field, entity_type in field_to_type.items():
        value = filters.get(field)
        if not isinstance(value, str) or not value:
            continue
        ids = identity.expand(db, scope.project_id, entity_type, value)
        expansions[field] = ids or [value]
        if len(expansions[field]) > 1:
            fanned = True
    return expansions if fanned else None


def _merge_results(batches: list[Any]) -> Dict[str, Any]:
    """Combine several SDK responses, keeping the first copy of each memory.

    A memory can match more than one alias query only if the same id came back
    twice; dedupe on id rather than trusting the store not to repeat itself.
    """
    seen: set = set()
    merged: list = []
    envelope: Dict[str, Any] = {}
    for batch in batches:
        rows = batch.get("results", []) if isinstance(batch, dict) else (batch or [])
        if isinstance(batch, dict):
            for key, value in batch.items():
                if key != "results" and key not in envelope:
                    envelope[key] = value
        for row in rows:
            key = row.get("id") if isinstance(row, dict) else None
            if key is not None and key in seen:
                continue
            if key is not None:
                seen.add(key)
            merged.append(row)
    return {**envelope, "results": merged}


def _alias_filter_variants(filters: Dict[str, Any], expansions: Dict[str, list]) -> list[Dict[str, Any]]:
    """One filter dict per identifier, since the SDK cannot express an OR."""
    variants = [dict(filters)]
    for field, ids in expansions.items():
        rebuilt = []
        for base in variants:
            for candidate in ids:
                rebuilt.append({**base, field: candidate})
        variants = rebuilt
    return variants


def _union_across_aliases(
    db: Session,
    scope: Scope,
    expansions: Dict[str, list],
    params: Dict[str, Any],
    mode: Any,
    top_k: Optional[int],
) -> Dict[str, Any]:
    instance = get_memory_instance()
    batches = []
    for variant in _alias_filter_variants(params.get("filters", {}), expansions):
        call = {**params, "filters": variant}
        batches.append(instance.get_all(**call))
    merged = _merge_results(batches)
    scoped = scope_results(merged, scope, None)
    return lifecycle_services.apply_read_mode(db, scoped, mode, top_k)


def _search_across_aliases(
    db: Session,
    scope: Scope,
    search_req: "SearchRequest",
    filters: Dict[str, Any],
    expansions: Dict[str, list],
    params: Dict[str, Any],
    mode: Any,
) -> Dict[str, Any]:
    instance = get_memory_instance()
    batches = []
    for variant in _alias_filter_variants(filters, expansions):
        batches.append(instance.search(query=search_req.query, filters=variant, **params))
    merged = _merge_results(batches)
    # Re-sorted after the union: each alias query ranked independently, so
    # concatenating them would interleave a weak match from one identifier
    # above a strong one from another.
    results = merged.get("results", [])
    if results and all(isinstance(r, dict) and isinstance(r.get("score"), (int, float)) for r in results):
        merged["results"] = sorted(results, key=lambda r: r["score"], reverse=True)
    scoped = scope_results(merged, scope, None)
    response = lifecycle_services.apply_read_mode(db, scoped, mode, None)
    response = _apply_decay(db, scope, response, search_req.top_k)
    try:
        lifecycle_services.record_access(
            db,
            [r.get("id") for r in response.get("results", []) if isinstance(r, dict)],
            scope.project_id,
        )
    except Exception:
        logging.warning("Failed to record memory access for aliased search", exc_info=True)
    return response


ALL_MEMORIES_LIMIT = 1000
_RESERVED_PAYLOAD_KEYS = {"data", "user_id", "agent_id", "run_id", "hash", "created_at", "updated_at", "expiration_date"}


def _serialize_memory(row: Any) -> Dict[str, Any]:
    payload = getattr(row, "payload", None) or {}
    return {
        "id": getattr(row, "id", None),
        "memory": payload.get("data"),
        "user_id": payload.get("user_id"),
        "agent_id": payload.get("agent_id"),
        "run_id": payload.get("run_id"),
        "hash": payload.get("hash"),
        "expiration_date": payload.get("expiration_date"),
        "metadata": {k: v for k, v in payload.items() if k not in _RESERVED_PAYLOAD_KEYS},
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
    }


def _list_all_memories(scope: Scope, limit: int = ALL_MEMORIES_LIMIT) -> Dict[str, Any]:
    """Every memory in the caller's project.

    Over-fetches because the project filter is applied after the read - see the
    module docstring in tenancy.py for why it cannot be pushed into the query.
    """
    results = get_memory_instance().vector_store.list(top_k=overfetch(limit) or limit)
    rows = results[0] if results and isinstance(results, list) and isinstance(results[0], list) else results or []
    return {"results": [_serialize_memory(row) for row in rows if visible_to(row, scope)][:limit]}


@app.get("/memories", summary="Get memories")
def get_all_memories(
    request: Request,
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    top_k: Optional[int] = Query(None, ge=0, le=ALL_MEMORIES_LIMIT),
    show_expired: bool = Query(False),
    latest_only: bool = Query(False, description="Exclude superseded and merged memories."),
    include_merged: bool = Query(False, description="Include memories merged into another."),
    _auth=Depends(verify_auth),
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
):
    """Retrieve stored memories in the caller's project.

    Lists every memory in the project when no identifier is given (admin only).
    Every memory carries its lifecycle state; `latest_only` drops the ones that
    have been superseded or merged away.
    """
    mode = lifecycle_services.read_mode(latest_only=latest_only, include_merged=include_merged)
    try:
        if not any([user_id, run_id, agent_id]):
            auth_type = getattr(request.state, "auth_type", "none")
            if _auth is not None and _auth.role != "admin" and auth_type not in {"admin_api_key", "disabled"}:
                raise HTTPException(status_code=403, detail="Admin role required to list all memories.")
            # This path reads the vector store directly rather than going
            # through get_all, so it applies neither expiry visibility nor the
            # SDK's serialization - only the project scope.
            listed = _list_all_memories(scope, limit=top_k if top_k is not None else ALL_MEMORIES_LIMIT)
            return lifecycle_services.apply_read_mode(db, listed, mode, top_k)
        filters = entity_filters({"user_id": user_id, "run_id": run_id, "agent_id": agent_id})
        params = {"filters": filters}
        if top_k is not None:
            params["top_k"] = overfetch(top_k)
        params["show_expired"] = show_expired
        # Reads expand rather than resolve: a memory written before the link
        # still carries the old identifier, and filtering on the canonical
        # alone would make it disappear the moment someone linked accounts.
        alias_sets = _expanded_filters(db, scope, filters)
        if alias_sets is not None:
            return _union_across_aliases(db, scope, alias_sets, params, mode, top_k)
        # Scoped first, then lifecycle-filtered: both trim, and doing project
        # scoping last would mean paying to look up lifecycle for memories the
        # caller may not see.
        scoped = scope_results(get_memory_instance().get_all(**params), scope, None)
        return lifecycle_services.apply_read_mode(db, scoped, mode, top_k)
    except HTTPException:
        raise
    except Exception:
        raise upstream_error()


def _require_in_scope(memory_id: str, scope: Scope) -> Dict[str, Any]:
    """Fetch a memory and confirm it belongs to the caller's project.

    404 rather than 403 on a cross-project id: a project should not be able to
    probe whether an id exists somewhere else on the instance.
    """
    try:
        memory = get_memory_instance().get(memory_id)
    except Exception:
        raise upstream_error()
    if memory is None or not visible_to(memory, scope):
        raise HTTPException(status_code=404, detail="Memory not found.")
    return memory


@app.get("/memories/{memory_id}", summary="Get a memory")
def get_memory(
    memory_id: str,
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
):
    """Retrieve a specific memory by ID, with its lifecycle state and access counts."""
    memory = _require_in_scope(memory_id, scope)
    annotated = lifecycle_services.annotate([memory], lifecycle_services.states_for(db, [memory_id]))[0]

    access = lifecycle_services.access_for(db, [memory_id]).get(memory_id)
    annotated["access"] = {
        "count": access.access_count if access else 0,
        "last_access_at": access.last_access_at.isoformat() if access and access.last_access_at else None,
        "first_access_at": access.first_access_at.isoformat() if access and access.first_access_at else None,
    }
    # A direct fetch is a read. Counted after the response is assembled so a
    # bookkeeping failure cannot cost the caller their memory.
    try:
        lifecycle_services.record_access(db, [memory_id], scope.project_id)
    except Exception:
        logging.warning("Failed to record access for memory %s", memory_id, exc_info=True)
    return annotated


@app.post("/search", summary="Search memories")
def search_memories(
    search_req: SearchRequest,
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
):
    """Search for memories based on a query, within the caller's project."""
    try:
        filters = entity_filters(search_req.filters)
        deprecated_keys = []
        for entity_key in ("user_id", "agent_id", "run_id"):
            entity_val = getattr(search_req, entity_key, None)
            if entity_val:
                filters[entity_key] = entity_val
                deprecated_keys.append(entity_key)
        if deprecated_keys:
            logging.warning(
                "Top-level %s in /search is deprecated. Use filters={%s} instead.",
                ", ".join(deprecated_keys),
                ", ".join(f'"{k}": "..."' for k in deprecated_keys),
            )
        project = db.get(Project, scope.project_id) if scope.project_id else None
        reranking = project is not None and retention_services.enabled(project.settings)
        params = {}
        if search_req.top_k is not None:
            params["top_k"] = overfetch(search_req.top_k, reranking=reranking)
        if search_req.threshold is not None:
            params["threshold"] = search_req.threshold
        if search_req.explain is not None:
            params["explain"] = search_req.explain
        if search_req.show_expired is not None:
            params["show_expired"] = search_req.show_expired
        mode = lifecycle_services.read_mode(
            latest_only=bool(search_req.latest_only),
            include_merged=bool(search_req.include_merged),
        )
        alias_sets = _expanded_filters(db, scope, filters)
        if alias_sets is not None:
            return _search_across_aliases(db, scope, search_req, filters, alias_sets, params, mode)
        scoped = scope_results(
            get_memory_instance().search(query=search_req.query, filters=filters, **params),
            scope,
            None,
        )
        response = lifecycle_services.apply_read_mode(db, scoped, mode, None)
        response = _apply_decay(db, scope, response, search_req.top_k)
        try:
            # Recall is the signal decay reads, so a search counts against
            # everything it actually returned.
            lifecycle_services.record_access(
                db,
                [r.get("id") for r in response.get("results", []) if isinstance(r, dict)],
                scope.project_id,
            )
        except Exception:
            logging.warning("Failed to record memory access for search", exc_info=True)
        try:
            with SessionLocal() as session:
                enqueue_webhook_event(
                    session,
                    "search.performed",
                    {"query": search_req.query, "filters": filters, "result_count": len(response.get("results", []))},
                )
        except Exception:
            logging.warning("Failed to enqueue search.performed webhook", exc_info=True)
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        raise upstream_error()


@app.put("/memories/{memory_id}", summary="Update a memory")
def update_memory(
    memory_id: str,
    updated_memory: MemoryUpdate,
    scope: Scope = Depends(require_role("member")),
):
    """Update an existing memory."""
    _require_in_scope(memory_id, scope)
    try:
        # Not getattr(..., getattr(...)): Python evaluates the default eagerly,
        # so the Pydantic v1 fallback fired a deprecation warning on every
        # update even though model_fields_set was present.
        fields_set = updated_memory.model_fields_set
        params = {"memory_id": memory_id}
        if "text" in fields_set:
            params["data"] = updated_memory.text
        if "metadata" in fields_set:
            # Re-stamped, because an update replaces metadata wholesale and a
            # caller omitting project_id would otherwise strip the memory's
            # scope and hand it to the default project.
            params["metadata"] = scoped_metadata(scope, updated_memory.metadata)
        if "expiration_date" in fields_set:
            params["expiration_date"] = updated_memory.expiration_date
        response = get_memory_instance().update(**params)
        try:
            memory = _serialize_memory(get_memory_instance().vector_store.get(vector_id=memory_id))
            with SessionLocal() as session:
                classify_memory(session, memory, scope.project_id)
                enqueue_webhook_event(session, "memory.updated", {"memory": memory})
        except Exception:
            logging.warning("Failed to run memory.updated side effects", exc_info=True)
        return response
    except (ValueError, Mem0ValidationError) as e:
        raise _client_error(e)
    except Exception:
        raise upstream_error()


@app.get("/memories/{memory_id}/history", summary="Get memory history")
def memory_history(memory_id: str, scope: Scope = Depends(require_scope)):
    """Retrieve memory history."""
    _require_in_scope(memory_id, scope)
    try:
        return get_memory_instance().history(memory_id=memory_id)
    except Exception:
        raise upstream_error()


@app.delete("/memories/{memory_id}", summary="Delete a memory", response_model=MessageResponse)
def delete_memory(memory_id: str, scope: Scope = Depends(require_role("member"))):
    """Delete a specific memory by ID."""
    _require_in_scope(memory_id, scope)
    try:
        memory = _serialize_memory(get_memory_instance().vector_store.get(vector_id=memory_id))
        get_memory_instance().delete(memory_id=memory_id)
        try:
            with SessionLocal() as session:
                session.execute(delete(MemoryCategory).where(MemoryCategory.memory_id == memory_id))
                # No foreign key to cascade from - the memory is not in this
                # database - so the cascade is explicit.
                lifecycle_services.forget(session, [memory_id], commit=False)
                enqueue_webhook_event(session, "memory.deleted", {"memory": memory})
                session.commit()
        except Exception:
            logging.warning("Failed to run memory.deleted side effects", exc_info=True)
        return MessageResponse(message="Memory deleted successfully")
    except (ValueError, Mem0ValidationError) as e:
        raise _client_error(e)
    except Exception:
        raise upstream_error()


@app.delete("/memories", summary="Delete all memories", response_model=MessageResponse)
def delete_all_memories(
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    scope: Scope = Depends(require_role("admin")),
):
    """Delete every memory for an identifier within the caller's project. Requires admin role."""
    if not any([user_id, run_id, agent_id]):
        raise HTTPException(status_code=400, detail="At least one identifier is required.")
    try:
        filters = entity_filters({"user_id": user_id, "run_id": run_id, "agent_id": agent_id})
        # Enumerate and delete one at a time rather than calling delete_all:
        # the SDK's delete_all matches on entity alone, so on an instance with a
        # second project it would take that project's memories with it.
        matches = scope_results(
            get_memory_instance().get_all(filters=filters, top_k=ALL_MEMORIES_LIMIT), scope
        )
        rows = matches.get("results", []) if isinstance(matches, dict) else matches
        memory_ids = [m.get("id") for m in rows if isinstance(m, dict) and m.get("id")]
        for memory_id in memory_ids:
            get_memory_instance().delete(memory_id=memory_id)
        if memory_ids:
            try:
                with SessionLocal() as session:
                    session.execute(delete(MemoryCategory).where(MemoryCategory.memory_id.in_(memory_ids)))
                    lifecycle_services.forget(session, memory_ids, commit=False)
                    session.commit()
            except Exception:
                logging.warning("Failed to clear categories for bulk-deleted memories", exc_info=True)
        return MessageResponse(message=f"Deleted {len(memory_ids)} memories")
    except HTTPException:
        raise
    except Exception:
        raise upstream_error()


@app.post("/reset", summary="Reset all memories")
def reset_memory(_scope: Scope = Depends(require_role("owner"))):
    """Erase the entire memory store across every project. Requires the owner role.

    This is the one memory route that is deliberately not project-scoped: it
    drops the underlying store, so scoping it would be a lie. Owner-only for
    that reason.
    """
    try:
        get_memory_instance().reset()
        return {"message": "All memories reset"}
    except Exception:
        raise upstream_error()


@app.get("/", summary="Redirect to the OpenAPI documentation", include_in_schema=False)
def home():
    """Redirect to the OpenAPI documentation."""
    return RedirectResponse(url="/docs")
