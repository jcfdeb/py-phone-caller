"""
Celery tasks and unified queue definitions for py-phone-caller.
Provides priority queue routing (telephony.p0 emergency leapfrogging, telephony.p2 batch)
and resilient dispatching to Asterisk Caller and Caller SMS.
"""

import logging
import requests
from celery import Celery
from kombu import Queue, Exchange

from py_phone_caller_utils.telemetry import inject_trace_context
from py_phone_caller_utils.tasks.constants import (
    BROKER_URL,
    URL,
    LOG_FORMATTER,
    LOG_LEVEL,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)

app = Celery("py_phone_caller_tasks", broker=BROKER_URL)

app.conf.enable_utc = True
app.conf.timezone = "UTC"

# Priority Queuing & Unified Routing definitions
# 10 priority levels: 0 (lowest) to 9 (highest). P0 emergency runs at priority 9. Standard runs at priority 5.
app.conf.broker_transport_options = {
    "priority_steps": list(range(10)),
    "sep": ":",
    "queue_order_strategy": "priority",
}

telephony_exchange = Exchange("telephony", type="direct")

app.conf.task_queues = [
    Queue("telephony.p0", exchange=telephony_exchange, routing_key="telephony.p0", queue_arguments={"x-max-priority": 9}),
    Queue("telephony.p2", exchange=telephony_exchange, routing_key="telephony.p2", queue_arguments={"x-max-priority": 9}),
    Queue("telephony.dlq", exchange=telephony_exchange, routing_key="telephony.dlq"),
    Queue("celery", exchange=telephony_exchange, routing_key="celery", queue_arguments={"x-max-priority": 9}),
]

app.conf.task_default_queue = "telephony.p2"
app.conf.task_default_exchange = "telephony"
app.conf.task_default_routing_key = "telephony.p2"

app.conf.task_routes = {
    "py_phone_caller_utils.tasks.celery_task.do_this_call": {"queue": "telephony.p2"},
    "py_phone_caller_utils.tasks.celery_task.dispatch_emergency_call": {"queue": "telephony.p0"},
}


@app.task(bind=True, max_retries=3, default_retry_delay=5)
def do_this_call(self, phone, message, priority=5):
    """
    Executes a standard scheduled call task by sending a POST request to Asterisk Caller.
    """
    data = {"phone": phone, "message": message}
    try:
        response = requests.post(URL, params=data, headers=inject_trace_context(), timeout=30)
        return response.status_code
    except requests.exceptions.RequestException as err:
        logging.exception(f"Error dispatching scheduled call to Asterisk: {err}")
        raise self.retry(exc=err)


@app.task(bind=True, max_retries=3, default_retry_delay=2)
def dispatch_emergency_call(self, phone, message):
    """
    P0 Emergency call dispatch that leapfrogs standard calls in Celery.
    """
    data = {"phone": phone, "message": message}
    try:
        response = requests.post(URL, params=data, headers=inject_trace_context(), timeout=15)
        return response.status_code
    except requests.exceptions.RequestException as err:
        logging.exception(f"Error dispatching emergency P0 call to Asterisk: {err}")
        raise self.retry(exc=err)

# Celery Beat Periodic Tasks Configuration
app.conf.beat_schedule = {
    "periodic-telephony-recall": {
        "task": "py_phone_caller_utils.tasks.celery_task.periodic_recall_task",
        "schedule": 15.0,  # runs every 15 seconds
        "options": {"queue": "telephony.p2"},
    },
}

import traceback
import json

@app.task(name="py_phone_caller_utils.tasks.celery_task.record_dead_letter")
def record_dead_letter(task_id, task_name, queue, payload, exc_str, tb_str):
    """
    Persists a failed task or poison pill to the Piccolo DB DeadLetterQueue table.
    """
    try:
        import asyncio
        from py_phone_caller_utils.py_phone_caller_db.piccolo_conf import DB
        from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import DeadLetterQueue

        async def _save():
            if DB.pool is None:
                await DB.start_connection_pool()
            await DeadLetterQueue.insert(
                DeadLetterQueue(
                    task_id=str(task_id),
                    task_name=str(task_name),
                    queue=str(queue),
                    payload=json.loads(json.dumps(payload)) if payload else {},
                    exception=str(exc_str)[:2040],
                    traceback=str(tb_str)[:4090],
                )
            )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_save())
        loop.close()
        logging.info(f"Recorded dead-letter task {task_id} to Piccolo DB")
    except Exception as err:
        logging.error(f"Failed to record dead letter to database: {err}")


@app.task(name="py_phone_caller_utils.tasks.celery_task.periodic_recall_task")
def periodic_recall_task():
    """
    Distributed periodic recall task with Redis lock.
    Replaces uncoordinated while-loops in asterisk_recaller.
    """
    import asyncio
    import redis
    from py_phone_caller_utils.config import settings

    queue_url = settings.get("QUEUE", {}).get("QUEUE_URL", "redis://redis.lan:6379/7")
    try:
        r = redis.from_url(queue_url, socket_connect_timeout=2)
        # Distributed lock: only one worker instance executes recall scan every cycle
        lock_acquired = r.set("lock:recaller_cycle", "1", nx=True, ex=12)
        if not lock_acquired:
            logging.debug("Another worker is currently executing the recall cycle. Skipping.")
            return "skipped_locked"
    except Exception as redis_err:
        logging.debug(f"Redis distributed lock check skipped: {redis_err}")

    # Invoke recall scan
    try:
        from asterisk_recaller.asterisk_recaller import run_single_recall_cycle
        loop = asyncio.new_event_loop()
        count = loop.run_until_complete(run_single_recall_cycle())
        loop.close()
        return f"processed_{count}"
    except ImportError:
        return "recaller_module_not_found"
    except Exception as err:
        logging.exception(f"Error in periodic recall task: {err}")
        return f"error_{err}"
