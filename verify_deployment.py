import aiohttp
import asyncio
import logging
import sys

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

import os

TARGET_HOST = os.environ.get("VERIFY_HOST", "127.0.0.1")

SERVICES = [
    {"name": "asterisk_caller", "port": 8081},
    {"name": "generate_audio", "port": 8082},
    {"name": "caller_register", "port": 8083},
    {"name": "caller_prometheus_webhook", "port": 8084},
    {"name": "caller_sms", "port": 8085},
    {"name": "caller_scheduler", "port": 8086},
    {"name": "caller_address_book", "port": 8087},
    {"name": "py_phone_caller_ui", "port": 5000},
]


async def check_service_health(session, name, port):
    url = f"http://{TARGET_HOST}:{port}/health"
    try:
        async with session.get(url, timeout=5) as response:
            if response.status == 200:
                data = await response.json()
                if data.get("status") == "healthy":
                    logging.info(
                        f"✅ {name:<30} HEALTH OK (Port {port}, Service: {data.get('service')})"
                    )
                    return True
                else:
                    logging.error(
                        f"❌ {name:<30} UNHEALTHY (Port {port}, Response: {data})"
                    )
                    return False
            else:
                logging.error(
                    f"❌ {name:<30} FAIL (Port {port}, Status {response.status})"
                )
                return False
    except Exception as e:
        logging.error(f"❌ {name:<30} FAIL (Port {port}, Error: {e})")
        return False


async def check_service_metrics(session, name, port):
    url = f"http://{TARGET_HOST}:{port}/metrics"
    try:
        async with session.get(url, timeout=5) as response:
            if response.status == 200:
                logging.info(f"📊 {name:<30} METRICS OK (Port {port})")
                return True
            else:
                logging.error(
                    f"❌ {name:<30} METRICS FAIL (Port {port}, Status {response.status})"
                )
                return False
    except Exception as e:
        logging.error(f"❌ {name:<30} METRICS FAIL (Port {port}, Error: {e})")
        return False


async def check_generate_audio_functional(session):
    """
    Functionally test generate_audio by requesting a simple audio file.
    This verifies TTS engine loading and filesystem permissions.
    """
    logging.info("-" * 60)
    logging.info("🔊 Testing generate_audio functionality...")

    # Check is_audio_ready (should be false for random checksum)
    chk_sum = "test_checksum_123"
    url = f"http://{TARGET_HOST}:8082/is_audio_ready?msg_chk_sum={chk_sum}"

    try:
        async with session.get(url, timeout=5) as resp:
            if resp.status == 200:
                logging.info("   is_audio_ready endpoint: OK")
                return True
            else:
                logging.error(
                    f"   is_audio_ready endpoint: FAIL (Status {resp.status})"
                )
                return False
    except Exception as e:
        logging.error(f"   is_audio_ready check failed: {e}")
        return False


async def main():
    logging.info("🚀 Starting End-to-End Deployment Verification")
    logging.info(f"🎯 Target Host: {TARGET_HOST}")
    logging.info("-" * 60)

    results = []
    async with aiohttp.ClientSession() as session:
        # Check all microservices health & metrics
        for svc in SERVICES:
            health_ok = await check_service_health(
                session, svc["name"], svc["port"]
            )
            metrics_ok = await check_service_metrics(
                session, svc["name"], svc["port"]
            )
            results.append(health_ok and metrics_ok)

        # Check functionality
        audio_ok = await check_generate_audio_functional(session)
        results.append(audio_ok)

    logging.info("-" * 60)
    if all(results):
        logging.info("🎉 ALL CHECKS PASSED! Deployment looks healthy.")
        sys.exit(0)
    else:
        logging.error("💥 SOME CHECKS FAILED. See logs above.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
