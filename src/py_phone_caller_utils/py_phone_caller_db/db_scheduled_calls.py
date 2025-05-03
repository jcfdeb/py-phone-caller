from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import \
    ScheduledCalls


async def insert_scheduled_call(
    phone, message, call_chk_sum, inserted_at, scheduled_at
):
    """
    Inserts a new scheduled call record into the ScheduledCalls table.

    This asynchronous function ensures the table exists and inserts a new scheduled call with the provided details.

    Args:
        phone (str): The recipient's phone number.
        message (str): The message content for the scheduled call.
        call_chk_sum (str): The checksum of the call.
        inserted_at (datetime): The timestamp when the record was inserted.
        scheduled_at (datetime): The scheduled time for the call.

    Returns:
        None
    """
    await ScheduledCalls.create_table(if_not_exists=True)
    await ScheduledCalls.insert(
        ScheduledCalls(
            phone=phone,
            message=message,
            call_chk_sum=call_chk_sum,
            inserted_at=inserted_at,
            scheduled_at=scheduled_at,
        )
    )


async def select_scheduled_calls():
    """
    Retrieves all scheduled call records from the ScheduledCalls table.

    This asynchronous function ensures the table exists and returns all stored scheduled call records.

    Returns:
        list: A list of all scheduled call records in the database.
    """
    await ScheduledCalls.create_table(if_not_exists=True)
    return await ScheduledCalls.select()
