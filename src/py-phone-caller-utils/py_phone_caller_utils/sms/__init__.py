"""
On‑premise SMS backend integration.

Exposes a lightweight Python facade over the Rust `rust_engine` module used by
`caller_sms` when the `on_premise` carrier is selected. It ensures the engine is
started once and provides an async `send` API that enqueues SMS messages in a
SQLite queue processed by the Rust background worker.
"""

import asyncio
import json
import logging
from py_phone_caller_utils.config import settings

try:
    from .rust_engine import enqueue_sms, start_engine
except ImportError:
    logging.warning(
        "Rust SMS engine not found. 'on_premise' backend will not work correctly."
    )
    enqueue_sms = None
    start_engine = None


class RustBackend:
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RustBackend, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        db_path = getattr(settings.caller_sms, "on_premise_sms_db", None)
        if not db_path:
            db_path = getattr(settings.commons, "sms_db_path", "sqlite:///data/sms.db")

        if db_path and not db_path.startswith("sqlite:"):
            if db_path.startswith("/"):
                db_path = f"sqlite://{db_path}"
            else:
                db_path = f"sqlite:{db_path}"

        self.db_path = db_path
        self.modems = getattr(settings.caller_sms, "modems", [])
        self.sms_strategy = getattr(settings.caller_sms, "sms_strategy", "failover")
        self.retry_records = int(
            getattr(settings.caller_sms, "on_premise_sms_db_retry_records", 30)
        )
        self._worker_started = False
        self._initialized = True

    async def send(self, to: str, body: str):
        """Standard interface for the rest of the app"""
        if enqueue_sms is None:
            logging.error("Rust engine not available.")
            return False

        if not self._worker_started:
            async with self._lock:
                if not self._worker_started:
                    await self.run_worker()

        try:
            logging.debug(f"Enqueuing SMS to {to} using DB: {self.db_path}")
            result = await enqueue_sms(self.db_path, to, body)
            return result in ["QUEUED", "DUPLICATE_IGNORED"]
        except Exception as e:
            logging.exception(f"Rust Error: {e}")
            return False

    async def run_worker(self):
        """Called at startup or on first send. Already protected by lock in send()."""
        if self._worker_started:
            return

        if start_engine is None:
            logging.error("Rust engine not available.")
            return

        try:
            modems_json = json.dumps([dict(m) for m in self.modems])

            logging.info(
                f"Starting Rust engine with DB: {self.db_path}, Strategy: {self.sms_strategy}, Modems: {len(self.modems)}"
            )
            await start_engine(
                self.db_path,
                modems_json,
                self.sms_strategy,
                self.retry_records,
            )
            self._worker_started = True
            logging.info("Rust SMS engine started successfully.")
        except Exception as e:
            logging.exception(f"Failed to start Rust SMS engine: {e}")
