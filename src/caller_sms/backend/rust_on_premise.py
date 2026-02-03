from py_phone_caller_utils.sms import RustBackend
import asyncio

backend = RustBackend()


async def init_backend():
    """
    Initializes the Rust backend worker.
    """
    await backend.run_worker()


async def sms_sender_async(message, phone):
    """
    Bridge to the Rust On-Premise SMS engine.
    """
    # Create a future/task that wraps the backend.send call.
    # We return the future object itself, which caller_sms.py will await.

    loop = asyncio.get_running_loop()
    future = loop.create_future()

    async def _send():
        try:
            success = await backend.send(phone, message)
            if success:
                future.set_result(True)
            else:
                future.set_exception(Exception("Failed to enqueue SMS in Rust engine"))
        except Exception as e:
            future.set_exception(e)

    asyncio.create_task(_send())
    return future
