"""
Caller SMS service.

Provides an aiohttp endpoint to send SMS messages using a configured carrier
backend (e.g., Twilio or on-premise gateway).
"""

import asyncio
import logging
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.append(src_dir)

from aiohttp import web

from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app
from py_phone_caller_utils.web import extract_params, create_service_catalog, setup_swagger_routes
from py_phone_caller_utils.web.readiness import ReadinessRegistry, check_database_pool
from py_phone_caller_utils.py_phone_caller_db.piccolo_conf import DB
from py_phone_caller_utils.py_phone_caller_db.db_sms import insert_sms, select_sms
import caller_sms.backend.twilio as twilio_backend
import caller_sms.backend.rust_on_premise as rust_on_premise

from caller_sms.constants import (
    CALLER_SMS_PORT,
    CALLER_SMS_APP_ROUTE,
    LOG_FORMATTER,
    CALLER_SMS_ERROR,
    LOG_LEVEL,
    CALLER_SMS_CARRIER,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)

init_telemetry("caller_sms")


async def _ensure_db_pool():
    """
    Ensures the database connection pool is established for caller_sms.
    """
    if DB.pool is None:
        await DB.start_connection_pool()
        logging.info("Connected to database for caller_sms")


async def send_the_sms(request):
    """
    Handles incoming requests to send an SMS message to a specified phone number.

    This asynchronous function extracts the message and phone number from the request,
    sends the SMS asynchronously, records the transaction in the database, and returns
    a JSON response indicating the status.

    Args:
        request: The incoming HTTP request containing 'message' and 'phone' parameters.

    Returns:
        aiohttp.web.Response: A JSON response indicating the status of the SMS sending operation.

    Raises:
        web.HTTPBadRequest: If any required parameter is missing from the request.
    """

    params = await extract_params(request)
    message = params.get("message")
    phone = params.get("phone")
    if not message or not phone:
        logging.exception(
            f"No 'message' or 'phone' parameter passed on: '{request.rel_url}'"
        )
        raise web.HTTPBadRequest(
            reason=CALLER_SMS_ERROR, body=None, text=None, content_type=None
        )

    carrier = CALLER_SMS_CARRIER
    status_code = 200
    status = "sent"
    error_msg = ""

    match carrier:
        case "twilio":
            futures = await twilio_backend.sms_sender_async(message, phone)
        case "on_premise":
            futures = await rust_on_premise.sms_sender_async(message, phone)
        case _:
            error_msg = f"Carrier '{carrier}' not supported."
            logging.error(error_msg)
            try:
                await insert_sms(
                    phone=phone,
                    message=message,
                    carrier=carrier,
                    status="failed",
                    error=error_msg,
                )
            except Exception as db_err:
                logging.error(f"Error recording SMS in database: {db_err}")
            return web.json_response({"status": 500, "error": error_msg}, status=500)

    try:
        await asyncio.ensure_future(futures)
        status_code = 200
        status = "sent"
    except Exception as err:
        status_code = 500
        status = "failed"
        error_msg = str(err)
        logging.exception(f"Unable to send the SMS: '{err}'")

    try:
        await insert_sms(
            phone=phone,
            message=message,
            carrier=carrier,
            status=status,
            error=error_msg,
        )
    except Exception as db_err:
        logging.error(f"Error recording SMS in database: {db_err}")

    response_data = {"status": status_code}
    if error_msg:
        response_data["error"] = error_msg

    return web.json_response(response_data, status=status_code)


async def get_sms_records(request):
    """
    Handles incoming requests to retrieve SMS records from the database.

    Query parameters:
        limit (int, optional): Max records to return.
        phone (str, optional): Filter by phone.
        status (str, optional): Filter by status.
    """
    limit_param = request.rel_url.query.get("limit")
    limit = int(limit_param) if limit_param and limit_param.isdigit() else None
    phone = request.rel_url.query.get("phone")
    status = request.rel_url.query.get("status")

    records = await select_sms(limit=limit, phone=phone, status=status)
    formatted = []
    for r in records:
        if isinstance(r, dict):
            item = dict(r)
            if "id" in item:
                item["id"] = str(item["id"])
            if "created_at" in item and item["created_at"]:
                item["created_at"] = str(item["created_at"])
            formatted.append(item)
        else:
            formatted.append(r)
    return web.json_response({"status": 200, "records": formatted})


async def init_app():
    """
    Initializes and configures the aiohttp web application for sending SMS messages.

    This asynchronous function sets up the web application, ensures the DB connection pool,
    and registers routes for handling SMS sending requests.

    Returns:
        aiohttp.web.Application: The configured aiohttp web application instance.
    """
    try:
        await _ensure_db_pool()
    except Exception as db_err:
        logging.error(f"Database initial pool setup failed: {db_err}. Service starting degraded; /ready will indicate 503.")

    app = web.Application()

    instrument_aiohttp_app(app, "caller_sms")

    registry = ReadinessRegistry("caller_sms")
    registry.register("postgres_pool", check_database_pool)

    async def caller_sms_ready(request):
        all_ready, details = await registry.evaluate()
        status_code = 200 if all_ready else 503
        return web.json_response(details, status=status_code)

    app.router.add_route("GET", "/ready", caller_sms_ready)

    if CALLER_SMS_CARRIER == "on_premise":
        await rust_on_premise.init_backend()

    async def cleanup_db(app):
        if DB.pool is not None:
            await DB.pool.close()
            logging.info("Database connection pool closed for caller_sms")

    app.on_cleanup.append(cleanup_db)

    async def root_catalog(request):
        catalog = create_service_catalog(
            service_name="caller_sms",
            description="Caller SMS service for py-phone-caller",
            version="1.0.0",
            docs_url="/docs",
            openapi_spec="/docs/swagger.json",
            endpoints={
                f"POST /{CALLER_SMS_APP_ROUTE}": "Dispatches SMS notification (JSON body or query params: phone, message)",
                "GET /get_sms": "Retrieves recent SMS records (optional query params: limit, phone, status)",
                "GET /live": "Liveness health check",
                "GET /ready": "Readiness probe",
                "GET /metrics": "Prometheus telemetry metrics",
            },
        )
        return web.json_response(catalog)

    app.router.add_route("GET", "/", root_catalog)
    app.router.add_route("POST", f"/{CALLER_SMS_APP_ROUTE}", send_the_sms)
    app.router.add_route("GET", "/get_sms", get_sms_records)

    setup_swagger_routes(
        app=app,
        service_name="caller_sms",
        description="Caller SMS emergency alert dispatch service for py-phone-caller",
        paths={
            f"/{CALLER_SMS_APP_ROUTE}": {
                "post": {
                    "summary": "Send an SMS message",
                    "description": "Sends an SMS alert via configured carrier (Twilio or on-premise serial modem). Accepts JSON body or query parameters.",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "phone": {"type": "string", "example": "0039123456789"},
                                        "message": {"type": "string", "example": "Critical server room overheat"},
                                    },
                                    "required": ["phone", "message"],
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {"description": "SMS sent successfully"},
                        "400": {"description": "Missing required phone or message parameter"},
                        "500": {"description": "Carrier sending failure"},
                    },
                }
            },
            "/get_sms": {
                "get": {
                    "summary": "Retrieve SMS log records",
                    "description": "Fetches recent SMS delivery records from Piccolo database.",
                    "parameters": [
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50}},
                        {"name": "phone", "in": "query", "schema": {"type": "string"}},
                        {"name": "status", "in": "query", "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {"description": "List of SMS log records"},
                    },
                }
            },
        },
    )
    return app


if __name__ == "__main__":
    web.run_app(init_app(), port=int(CALLER_SMS_PORT))
