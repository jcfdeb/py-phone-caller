"""
Home blueprint for the Py Phone Caller UI.

Provides the landing page with NOC Telemetry dashboard, wallboard mode,
real-time Server-Sent Events (SSE) telemetry stream, and diagnostic test dispatches.
"""

import asyncio
import json
import logging
from typing import Any, Dict

import aiohttp
from flask import Blueprint, Response, jsonify, redirect, render_template, request, url_for
from flask_login import login_required, logout_user

from py_phone_caller_utils.config import settings
from py_phone_caller_utils.event_bus import subscribe_events
from .telemetry import get_noc_dashboard_metrics

logger = logging.getLogger(__name__)

home_blueprint = Blueprint(
    "home_blueprint",
    __name__,
    template_folder="templates/home",
)


@home_blueprint.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login_blueprint.login"))


@home_blueprint.route("/api/dashboard_metrics")
@login_required
async def api_dashboard_metrics():
    """
    Returns real-time telemetry metrics in JSON format for the NOC Dashboard auto-refresh.
    """
    metrics = await get_noc_dashboard_metrics()
    return jsonify(metrics)


@home_blueprint.route("/api/telemetry_stream")
@login_required
async def telemetry_stream():
    """
    Server-Sent Events (SSE) stream endpoint.
    Streams live telemetry metrics and telephony state transitions in real time.
    """
    async def event_generator():
        # Yield initial state immediately
        initial_metrics = await get_noc_dashboard_metrics()
        yield f"event: metrics\ndata: {json.dumps(initial_metrics)}\n\n"

        async for event in subscribe_events():
            # Broadcast telephony/SMS event
            yield f"event: telephony_event\ndata: {json.dumps(event)}\n\n"
            # Follow with updated metrics
            fresh_metrics = await get_noc_dashboard_metrics()
            yield f"event: metrics\ndata: {json.dumps(fresh_metrics)}\n\n"

    return Response(
        event_generator(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@home_blueprint.route("/api/diagnostics/test_sms", methods=["POST"])
@login_required
async def test_sms_dispatch():
    """
    Triggers an immediate test SMS via caller_sms microservice.
    """
    data = request.get_json(silent=True) or request.form
    phone = (data.get("phone") or "").strip()
    message = (data.get("message") or "py-phone-caller diagnostic test SMS").strip()

    if not phone:
        return jsonify({"success": False, "error": "Phone number is required."}), 400

    sms_port = getattr(settings.caller_sms, "caller_sms_port", 8085)
    sms_route = str(getattr(settings.caller_sms, "caller_sms_app_route", "send_sms")).lstrip("/")
    url = f"http://127.0.0.1:{sms_port}/{sms_route}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"phone": phone, "message": message}, timeout=10.0) as resp:
                resp_json = await resp.json()
                if resp.status == 200:
                    return jsonify({"success": True, "details": resp_json, "service": "caller_sms", "target": phone})
                return jsonify({
                    "success": False,
                    "error": resp_json.get("error", resp_json.get("message", f"HTTP {resp.status} - SMS rejected")),
                    "details": resp_json
                }), resp.status
    except Exception as exc:
        logger.exception("Failed to dispatch diagnostic test SMS: %s", exc)
        return jsonify({"success": False, "error": f"caller_sms connection error: {exc}"}), 500


@home_blueprint.route("/api/diagnostics/test_call", methods=["POST"])
@login_required
async def test_call_dispatch():
    """
    Triggers an immediate test phone call via asterisk_caller.
    """
    data = request.get_json(silent=True) or request.form
    phone = (data.get("phone") or "").strip()
    message = (data.get("message") or "This is a diagnostic test call from py-phone-caller.").strip()

    if not phone:
        return jsonify({"success": False, "error": "Phone number is required."}), 400

    call_port = getattr(settings.asterisk_call, "asterisk_call_port", 8081)
    call_route = str(getattr(settings.asterisk_call, "asterisk_call_app_route_place_call", "place_call")).lstrip("/")
    url = f"http://127.0.0.1:{call_port}/{call_route}"

    payload = {
        "phone": phone,
        "message": message,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10.0) as resp:
                resp_json = await resp.json()
                if resp.status == 200:
                    return jsonify({"success": True, "details": resp_json, "service": "asterisk_caller", "target": phone})
                return jsonify({
                    "success": False,
                    "error": resp_json.get("error", resp_json.get("message", f"HTTP {resp.status} - Call rejected")),
                    "details": resp_json
                }), resp.status
    except Exception as exc:
        logger.exception("Failed to dispatch diagnostic test call: %s", exc)
        return jsonify({"success": False, "error": f"asterisk_caller connection error: {exc}"}), 500


@home_blueprint.route("/wallboard")
@login_required
async def wallboard():
    """
    Renders high-contrast 24/7 NOC Wallboard mode optimized for TV / wall monitors.
    """
    metrics = await get_noc_dashboard_metrics()
    return render_template("wallboard.html", metrics=metrics)


@home_blueprint.route("/")
@login_required
async def home():
    """
    Renders the NOC Dashboard home page for authenticated users,
    providing telemetry KPIs, lifecycle breakdowns, gateway health, and navigation links.

    Returns:
        flask.Response: The rendered HTML home page.
    """
    metrics = await get_noc_dashboard_metrics()

    return render_template(
        "home.html",
        metrics=metrics,
        home_url=url_for("home_blueprint.home"),
        calls_url=url_for("calls_blueprint.calls"),
        ws_events_url=url_for("ws_events_blueprint.ws_events"),
        schedule_call_url=url_for("schedule_call_blueprint.schedule_call"),
        users_url=url_for("users_blueprint.users"),
        address_book_url=url_for("address_book_blueprint.address_book"),
        logout_url=url_for("home_blueprint.logout"),
    )
