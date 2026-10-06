"""
Home blueprint for the Py Phone Caller UI.

Provides the landing page with NOC Telemetry dashboard, wallboard mode,
real-time Server-Sent Events (SSE) telemetry stream, and diagnostic test dispatches.
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict

import aiohttp
from flask import Blueprint, Response, jsonify, redirect, render_template, request, url_for
from flask_login import login_required, logout_user

from py_phone_caller_utils.config import settings
from py_phone_caller_utils.checksums import gen_msg_chk_sum
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
    lang = (data.get("language") or data.get("lang") or "").strip()

    if not phone:
        return jsonify({"success": False, "error": "Phone number is required."}), 400

    # Pre-generate TTS audio so it is cached immediately
    try:
        if message:
            chksum = await gen_msg_chk_sum(message)
            audio_host = settings.get("generate_audio.generate_audio_host") or "127.0.0.1"
            audio_port = settings.get("generate_audio.generate_audio_port") or 8082
            if audio_host in ("192.168.101.17", "192.168.101.111"):
                audio_host = "127.0.0.1"
            gen_params = {"message": message, "msg_chk_sum": chksum}
            if lang:
                gen_params["lang"] = lang
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                await session.post(f"http://{audio_host}:{audio_port}/make_audio", params=gen_params)
    except Exception as tts_err:
        logger.warning("Pre-generation of test call audio failed: %s", tts_err)

    call_port = getattr(settings.asterisk_call, "asterisk_call_port", 8081)
    call_route = str(getattr(settings.asterisk_call, "asterisk_call_app_route_place_call", "place_call")).lstrip("/")
    url = f"http://127.0.0.1:{call_port}/{call_route}"

    payload = {
        "phone": phone,
        "message": message,
    }
    if lang:
        payload["lang"] = lang
        payload["language"] = lang

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


@home_blueprint.route("/api/audio_proxy/<filename>")
@login_required
async def api_audio_proxy(filename: str):
    """
    Proxies TTS audio preview requests from the browser to the generate_audio service.
    Avoids CORS issues and ensures LAN services remain protected.
    """
    if not re.match(r"^[a-zA-Z0-9_\-.]+\.wav$", filename):
        return jsonify({"error": "Invalid audio filename"}), 400

    audio_host = settings.get("generate_audio.generate_audio_host") or "127.0.0.1"
    audio_port = settings.get("generate_audio.generate_audio_port") or 8082
    if audio_host in ("192.168.101.17", "192.168.101.111"):
        audio_host = "127.0.0.1"

    target_url = f"http://{audio_host}:{audio_port}/audio/{filename}"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4)) as session:
            async with session.get(target_url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return Response(data, mimetype="audio/wav")
                return jsonify({"error": "Audio file not found or still generating", "status": resp.status}), resp.status
    except Exception as exc:
        logger.warning(f"Audio proxy connection failed for {target_url}: {exc}")
        return jsonify({"error": f"Audio service unreachable: {exc}"}), 502


@home_blueprint.route("/api/languages")
async def api_languages():
    """
    Proxies language discovery requests from the browser to generate_audio (/languages).
    Returns available languages for the active TTS engine with safe fallback.
    """
    audio_host = settings.get("generate_audio.generate_audio_host") or "127.0.0.1"
    audio_port = settings.get("generate_audio.generate_audio_port") or 8082
    if audio_host in ("192.168.101.17", "192.168.101.111"):
        audio_host = "127.0.0.1"

    target_url = f"http://{audio_host}:{audio_port}/languages"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as session:
            async with session.get(target_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return jsonify(data)
                return jsonify({"error": "Failed to fetch languages", "status": resp.status}), resp.status
    except Exception as exc:
        logger.warning(f"Languages proxy connection failed for {target_url}: {exc}")
        default_lang = settings.get("generate_audio.facebook_mms_language_code") or "spa"
        return jsonify({
            "active_engine": settings.get("generate_audio.tts_engine", "facebook_mms"),
            "default_language": default_lang,
            "languages": [
                {"code": default_lang, "name": default_lang.upper(), "is_default": True, "ready": True}
            ],
            "installed_models": {},
        })


@home_blueprint.route("/api/global_search")
@login_required
async def api_global_search():
    """
    Universal search API for Command Palette (Ctrl+K).
    Returns matches across Contacts, Calls, and Navigation targets.
    """
    query = request.args.get("q", "").strip().lower()
    results = []

    # 1. Navigation Targets
    nav_links = [
        {"title": "NOC Dashboard", "category": "Navigation", "icon": "bi-speedometer2", "url": url_for("home_blueprint.home")},
        {"title": "24/7 Wallboard", "category": "Navigation", "icon": "bi-display", "url": url_for("home_blueprint.wallboard")},
        {"title": "Managed Calls", "category": "Navigation", "icon": "bi-telephone-inbound", "url": url_for("calls_blueprint.calls")},
        {"title": "Incident Audit Report", "category": "Navigation", "icon": "bi-shield-check", "url": url_for("calls_blueprint.audit_report")},
        {"title": "Schedule Call", "category": "Navigation", "icon": "bi-calendar-plus", "url": url_for("schedule_call_blueprint.schedule_call")},
        {"title": "Address Book & Duty Roster", "category": "Navigation", "icon": "bi-journal-bookmark", "url": url_for("address_book_blueprint.address_book")},
        {"title": "SMS Gateway & Logs", "category": "Navigation", "icon": "bi-chat-dots", "url": url_for("sms_blueprint.sms")},
        {"title": "Asterisk WS Events", "category": "Navigation", "icon": "bi-broadcast-pin", "url": url_for("ws_events_blueprint.ws_events")},
        {"title": "User Management", "category": "Navigation", "icon": "bi-people", "url": url_for("users_blueprint.users")},
    ]

    for item in nav_links:
        if not query or query in item["title"].lower():
            results.append(item)

    # 2. Search Address Book Contacts
    try:
        from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import AddressBook
        contacts = await AddressBook.select()
        for c in contacts:
            name = f"{c.get('name', '')} {c.get('surname', '')}".strip()
            phone = c.get('phone_number', '') or ''
            city = c.get('city', '') or ''
            searchable = f"{name} {phone} {city}".lower()
            if query and query in searchable:
                results.append({
                    "title": name or phone,
                    "subtitle": f"{phone} ({city})" if city else phone,
                    "category": "Address Book",
                    "icon": "bi-person-badge",
                    "url": f"{url_for('address_book_blueprint.address_book')}?search={phone}",
                })
    except Exception as exc:
        logger.debug(f"Search contacts failed: {exc}")

    # 3. Search Calls
    try:
        from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import Calls
        calls = await Calls.select().order_by(Calls.first_dial, ascending=False).limit(20)
        for c in calls:
            phone = c.get('phone', '') or ''
            msg = c.get('message', '') or ''
            chan = c.get('asterisk_chan', '') or ''
            searchable = f"{phone} {msg} {chan}".lower()
            if query and query in searchable:
                results.append({
                    "title": f"Call to {phone}",
                    "subtitle": (msg[:60] + "...") if len(msg) > 60 else msg,
                    "category": "Calls",
                    "icon": "bi-telephone-outbound",
                    "url": f"{url_for('calls_blueprint.calls')}?search={phone}",
                })
    except Exception as exc:
        logger.debug(f"Search calls failed: {exc}")

    return jsonify({"results": results[:15]})


@home_blueprint.route("/api/quick_oncall_status")
@login_required
async def api_quick_oncall_status():
    """
    Returns current active on-call responders and enables rapid toggle.
    """
    from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import AddressBook
    from datetime import UTC, datetime
    now_utc = datetime.now(UTC)

    active_contacts = []
    all_contacts = []
    try:
        contacts = await AddressBook.select()
        for c in contacts:
            cid = str(c.get("id"))
            name = f"{c.get('name', '')} {c.get('surname', '')}".strip() or "Unnamed"
            phone = c.get("phone_number", "")
            enabled = bool(c.get("enabled", False))
            all_contacts.append({
                "id": cid,
                "name": name,
                "phone": phone,
                "enabled": enabled,
            })
            if enabled:
                active_contacts.append({
                    "id": cid,
                    "name": name,
                    "phone": phone,
                })
    except Exception as exc:
        logger.debug(f"Failed to fetch oncall status: {exc}")

    return jsonify({
        "active_count": len(active_contacts),
        "active_contacts": active_contacts,
        "contacts": all_contacts,
    })


@home_blueprint.route("/api/quick_oncall_toggle", methods=["POST"])
@login_required
async def api_quick_oncall_toggle():
    """
    Toggles a contact's enabled status directly from the header dropdown.
    """
    from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import AddressBook
    from py_phone_caller_utils.py_phone_caller_db.db_address_book import modify_contact

    data = request.get_json(silent=True) or {}
    contact_id = data.get("contact_id")
    enabled = data.get("enabled")

    if not contact_id or enabled is None:
        return jsonify({"success": False, "error": "Missing contact_id or enabled flag"}), 400

    try:
        await modify_contact(contact_id, {"enabled": bool(enabled)})
        return jsonify({"success": True, "contact_id": contact_id, "enabled": bool(enabled)})
    except Exception as exc:
        logger.exception("Failed to toggle contact enabled: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500
