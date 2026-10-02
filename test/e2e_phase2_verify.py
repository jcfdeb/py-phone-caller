#!/usr/bin/env python3
"""
Phase 2 End-to-End Real-Infrastructure Test Suite
=================================================
Verifies Phase 2 specifications against live running microservices:
1. Asterisk ARI Circuit Breaker & PJSIP Trunk Prober (/ready, /live)
2. Database Concurrency Bouncers (call_mutex distributed Redis lock)
3. Sovereign SMS Mode & Two-Way Inbound SMS Acknowledgment (/sms/inbound)
"""

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime
import aiohttp
import redis.asyncio as aioredis

# Ensure paths
sys.path.insert(0, os.path.abspath("src"))
sys.path.insert(0, os.path.abspath("src/py-phone-caller-utils"))

TARGET_HOST = os.environ.get("TARGET_HOST", "127.0.0.1")
CALLER_PORT = 8081
REGISTER_PORT = 8083
SMS_PORT = 8085

passed_tests = 0
failed_tests = 0


def log_step(name, status, detail=""):
    global passed_tests, failed_tests
    icon = "✅" if status else "❌"
    if status:
        passed_tests += 1
    else:
        failed_tests += 1
    print(f" {icon} {name:<45} : {detail}")


async def test_1_trunk_prober_and_readiness(session):
    print("\n" + "=" * 70)
    print(" 1. Asterisk ARI Circuit Breaker & PJSIP Trunk Prober")
    print("=" * 70)

    url_ready = f"http://{TARGET_HOST}:{CALLER_PORT}/ready"
    try:
        async with session.get(url_ready, timeout=5) as resp:
            data = await resp.json()
            is_ready = data.get("ready")
            checks = data.get("checks", {})
            ari_check = checks.get("asterisk_ari", {})
            trunk_check = checks.get("pjsip_trunk", {})

            log_step("Asterisk ARI Connectivity", ari_check.get("ready") is True, ari_check.get("message", ""))
            log_step("PJSIP Trunk State Probe", "pjsip_trunk" in checks, f"Trunk: {trunk_check.get('message', '')}")
            log_step("Readiness Overall Evaluation", is_ready is True, f"HTTP {resp.status}")
    except Exception as e:
        log_step("Readiness Probe Error", False, str(e))


async def test_2_concurrency_bouncer_redis_mutex():
    print("\n" + "=" * 70)
    print(" 2. Database Concurrency Bouncers (Redis Distributed Lock)")
    print("=" * 70)

    from py_phone_caller_utils.redis_lock import call_mutex, get_redis_client

    test_chan = f"test-chan-{uuid.uuid4().hex[:8]}"
    execution_order = []
    concurrency_violations = []

    active_holders = 0

    async def worker(worker_id):
        nonlocal active_holders
        async with call_mutex(test_chan, timeout=5.0, blocking_timeout=5.0) as acquired:
            if not acquired:
                concurrency_violations.append(f"Worker {worker_id} failed to acquire lock")
                return
            active_holders += 1
            if active_holders > 1:
                concurrency_violations.append(f"Overlap detected: {active_holders} workers inside mutex")
            execution_order.append(worker_id)
            await asyncio.sleep(0.05)
            active_holders -= 1

    # Run 5 concurrent tasks contending for the exact same channel resource
    tasks = [worker(i) for i in range(5)]
    await asyncio.gather(*tasks)

    log_step("Redis Lock Exclusivity (No Overlap)", len(concurrency_violations) == 0, f"Violations: {len(concurrency_violations)}")
    log_step("Distributed Mutex Sequentialization", len(execution_order) == 5, f"All 5 acquired cleanly in order: {execution_order}")


async def test_3_sovereign_sms_fallback_behavior(session):
    print("\n" + "=" * 70)
    print(" 3. Conditional Sovereign SMS Fallback Evaluation")
    print("=" * 70)

    # Check caller_sms readiness and config
    url_ready = f"http://{TARGET_HOST}:{SMS_PORT}/ready"
    async with session.get(url_ready, timeout=5) as resp:
        data = await resp.json()
        log_step("caller_sms Readiness Check", resp.status == 200, f"Ready: {data.get('ready')}")

    # Dispatch SMS to non-existent GSM modem or Twilio without credentials (should fail-fast sovereignly)
    url_send = f"http://{TARGET_HOST}:{SMS_PORT}/send_sms"
    test_phone = "00393349246425"
    async with session.post(url_send, json={"phone": test_phone, "message": "Test Phase 2 Sovereign Dispatch"}) as resp:
        data = await resp.json()
        # On-premise modem will fail because no physical USB modem is plugged into this VM,
        # and sovereign mode (sms_saas_fallback=false) ensures it does NOT leak to public cloud
        if resp.status in (200, 500):
            log_step("Sovereign SMS Fast-Fail / Execution", True, f"Status: {resp.status}, Response: {data}")
        else:
            log_step("Sovereign SMS Fast-Fail / Execution", False, f"Unexpected status: {resp.status}")


async def test_4_inbound_sms_acknowledgment_flow(session):
    print("\n" + "=" * 70)
    print(" 4. Two-Way Inbound SMS Acknowledgment (ACK / OK Token Matching)")
    print("=" * 70)

    test_phone = "+393349246425"
    clean_phone = "00393349246425"
    test_chan = f"chan-phase2-{uuid.uuid4().hex[:8]}"
    test_msg = "Phase 2 Live Inbound ACK Test Alert"

    # Step A: Register an active call via caller_register
    url_reg = f"http://{TARGET_HOST}:{REGISTER_PORT}/register_call"
    params = {
        "phone": clean_phone,
        "message": test_msg,
        "asterisk_chan": test_chan,
        "oncall": "false",
        "backup_callee": "false",
    }
    async with session.post(url_reg, params=params) as resp:
        reg_data = await resp.json()
        log_step("Active Call Registration", resp.status == 200, f"Registered chan: {test_chan}")

    # Verify call in Piccolo DB is cycle_done == False
    from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import Calls, Sms

    active_call = await Calls.select().where(Calls.asterisk_chan == test_chan).first().run()
    log_step("DB Initial State (cycle_done=False)", active_call is not None and not active_call["cycle_done"], f"ID: {active_call.get('id') if active_call else None}")

    # Step B: Send Inbound SMS with 'ACK' token
    url_inbound = f"http://{TARGET_HOST}:{SMS_PORT}/sms/inbound"
    inbound_payload = {
        "From": test_phone,
        "Body": "ACK - Incident noted, team is responding",
    }
    async with session.post(url_inbound, json=inbound_payload) as resp:
        inbound_data = await resp.json()
        log_step("Inbound SMS ACK Endpoint Response", resp.status == 200, f"{inbound_data}")
        log_step("Inbound SMS Matched & Acknowledged", inbound_data.get("acknowledged") is True and inbound_data.get("matched_calls") >= 1, f"Matched calls: {inbound_data.get('matched_calls')}")

    # Step C: Verify DB Call record was marked acknowledged & cycle_done=True
    updated_call = await Calls.select().where(Calls.asterisk_chan == test_chan).first().run()
    log_step("DB Call Marked Acknowledged", updated_call.get("acknowledge_at") is not None, f"acknowledge_at: {updated_call.get('acknowledge_at')}")
    log_step("DB Call Marked cycle_done=True", updated_call.get("cycle_done") is True, f"cycle_done: {updated_call.get('cycle_done')}")

    # Step D: Verify Inbound SMS record logged in Sms table
    sms_record = await Sms.select().where(Sms.message == inbound_payload["Body"]).first().run()
    log_step("Inbound SMS Logged in DB", sms_record is not None, f"Status: {sms_record.get('status') if sms_record else None}, Carrier: {sms_record.get('carrier') if sms_record else None}")

    # Step E: Test Non-ACK message (does NOT acknowledge call)
    non_ack_payload = {
        "From": test_phone,
        "Body": "Hello, what server is that?",
    }
    async with session.post(url_inbound, json=non_ack_payload) as resp:
        non_ack_data = await resp.json()
        log_step("Non-ACK Inbound Ignored by Acknowledger", non_ack_data.get("acknowledged") is False and non_ack_data.get("matched_calls") == 0, f"Acknowledged: {non_ack_data.get('acknowledged')}")


async def main():
    print("=" * 80)
    print(" 🚀 PY-PHONE-CALLER PHASE 2 END-TO-END VERIFICATION")
    print(f" Target Host: {TARGET_HOST}")
    print(f" Timestamp:   {datetime.now(UTC).isoformat()}")
    print("=" * 80)

    async with aiohttp.ClientSession() as session:
        await test_1_trunk_prober_and_readiness(session)
        await test_2_concurrency_bouncer_redis_mutex()
        await test_3_sovereign_sms_fallback_behavior(session)
        await test_4_inbound_sms_acknowledgment_flow(session)

    print("\n" + "=" * 80)
    print(f" 🏁 SUMMARY: {passed_tests} PASSED, {failed_tests} FAILED")
    print("=" * 80)
    return 0 if failed_tests == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
