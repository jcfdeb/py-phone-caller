from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import (
    ScheduledCalls,
)


async def insert_scheduled_call(
    phone, message, call_chk_sum, inserted_at, scheduled_at, lang=""
):
    """
    Inserts a scheduled call record into the ScheduledCalls table in the database.

    This asynchronous function adds a new scheduled call entry with the specified parameters.

    Args:
        phone (str): The recipient's phone number.
        message (str): The message content for the scheduled call.
        call_chk_sum (str): The checksum of the call.
        inserted_at (datetime): The timestamp when the call was inserted.
        scheduled_at (datetime): The timestamp when the call is scheduled to be made.
        lang (str): Language code for voice audio synthesis.

    Returns:
        None
    """

    await ScheduledCalls.insert(
        ScheduledCalls(
            phone=phone,
            message=message,
            call_chk_sum=call_chk_sum,
            inserted_at=inserted_at,
            scheduled_at=scheduled_at,
            lang=lang or "",
        )
    )


async def select_scheduled_calls():
    """
    Retrieves all scheduled call records from the ScheduledCalls table in the database.

    This asynchronous function queries and returns all records from the ScheduledCalls table.

    Returns:
        list: A list of all scheduled call records.
    """

    return await ScheduledCalls.select()
