from __future__ import annotations

import base64
import os
import subprocess
import tempfile
import threading
from datetime import time as dt_time
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.ext import AIORateLimiter, Application, ApplicationBuilder, CommandHandler, ContextTypes, TypeHandler

from app.config import Settings, get_settings
from app.handlers import admin_crud, admin_import, feedback, group, menu, ops, review_after
from app.logging_conf import configure_logging, get_logger
from app.matching.regex_matcher import RegexMatcher
from app.repo.admins import AdminRepo
from app.repo.entries import EntryCache, EntryRepo
from app.repo.firestore import FirestoreStore, Store, build_firestore_client
from app.repo.logs import LogRepo
from app.services import Services

logger = get_logger(__name__)

LIVENESS_INTERVAL_SECONDS = 30

# The bot itself only long-polls Telegram and never opens a port, but platforms
# like DigitalOcean App Platform run an HTTP readiness/liveness probe against
# $PORT (default 8080) regardless of workload type. This stub server exists
# only to satisfy that probe.
HEALTH_CHECK_PORT = int(os.environ.get("PORT", "8080"))


class _HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args: object) -> None:
        pass


def start_health_check_server(port: int) -> HTTPServer:
    server = HTTPServer(("0.0.0.0", port), _HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("health_check_server_started", port=port)
    return server


def get_git_sha() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def _write_credentials_from_base64(b64: str) -> str:
    json_bytes = base64.b64decode(b64)
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "wb") as f:
        f.write(json_bytes)
    return path


async def log_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None
    user_id = update.effective_user.id if update.effective_user else None
    logger.info("update_received", chat_id=chat_id, user_id=user_id, update_id=update.update_id)


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sha = context.bot_data["git_sha"]
    env = context.bot_data["env"]
    await update.message.reply_text(f"pong ({env}, {sha})")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # A handler exception must never kill the polling loop (plan P4): PTB
    # already isolates handler errors per-update, this just makes sure they
    # show up in structured logs instead of only PTB's own logger.
    logger.error("unhandled_error", error=str(context.error), exc_info=context.error)


async def _post_init(application: Application) -> None:
    services: Services = application.bot_data["services"]
    await services.entry_cache.start()
    logger.info("entry_cache_started")

    if application.job_queue is not None:
        application.job_queue.run_monthly(review_after.monthly_review_digest, when=dt_time(hour=9), day=1)
        application.job_queue.run_repeating(ops.touch_liveness_file, interval=LIVENESS_INTERVAL_SECONDS, first=0)


async def _post_shutdown(application: Application) -> None:
    services: Services = application.bot_data["services"]
    await services.entry_cache.stop()


def build_application(settings: Settings, store: Store | None = None) -> Application:
    application = (
        ApplicationBuilder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .rate_limiter(AIORateLimiter())
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.bot_data["git_sha"] = get_git_sha()
    application.bot_data["env"] = settings.ENV

    if store is None:
        store = FirestoreStore(build_firestore_client(settings))

    entry_repo = EntryRepo(store)
    entry_cache = EntryCache(entry_repo, store)
    services = Services(
        settings=settings,
        store=store,
        entry_repo=entry_repo,
        entry_cache=entry_cache,
        admin_repo=AdminRepo(store),
        log_repo=LogRepo(store),
        matcher=RegexMatcher(entry_cache),
    )
    application.bot_data["services"] = services

    application.add_handler(TypeHandler(Update, log_update), group=-1)
    application.add_error_handler(on_error)
    application.add_handler(CommandHandler("ping", ping))
    for handler in admin_crud.HANDLERS:
        application.add_handler(handler)
    for handler in admin_import.HANDLERS:
        application.add_handler(handler)
    for handler in review_after.HANDLERS:
        application.add_handler(handler)
    for handler in ops.HANDLERS:
        application.add_handler(handler)
    for handler in menu.HANDLERS:
        application.add_handler(handler)
    for handler in feedback.HANDLERS:
        application.add_handler(handler)
    for handler in group.HANDLERS:
        application.add_handler(handler)

    return application


def main() -> None:
    settings = get_settings()
    if settings.GOOGLE_SA_JSON_BASE64:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _write_credentials_from_base64(settings.GOOGLE_SA_JSON_BASE64)

    configure_logging(settings.LOG_LEVEL, settings.ENV)
    logger.info("starting", env=settings.ENV, git_sha=get_git_sha())

    start_health_check_server(HEALTH_CHECK_PORT)

    application = build_application(settings)
    # run_polling installs handlers for SIGINT/SIGTERM/SIGABRT by default and
    # shuts the Application down cleanly (stop polling, close the bot session).
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
