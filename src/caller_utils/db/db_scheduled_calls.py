from scheduled_calls_table import ScheduledCalls


async def insert_scheduled_call(
    phone, message, call_chk_sum, inserted_at, scheduled_at
):
    """Insert a row when a call is scheduled"""
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
    """Selects the rows of the 'scheduled_calls' table"""
    return await ScheduledCalls.select()
