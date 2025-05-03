from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import \
    Calls


async def select_to_recall(
    times_to_dial, lesser_seconds_to_forget, greater_sleep_and_retry
):
    """
    Selects call records that are eligible for recall based on dial attempts and timing criteria.

    This asynchronous function queries the Calls table for records that have not reached the maximum dial attempts,
    are within the specified time window, and have not completed their call cycle.

    Args:
        times_to_dial (int): The maximum number of allowed dial attempts.
        lesser_seconds_to_forget (datetime): The lower bound of the time window for first dial.
        greater_sleep_and_retry (datetime): The upper bound of the time window for first dial.

    Returns:
        list: A list of call records matching the recall criteria.
    """
    await Calls.create_table(if_not_exists=True)
    result = await Calls.select(
        Calls.phone, Calls.message, Calls.seconds_to_forget
    ).where(
        (Calls.dialed_times < times_to_dial)
        & (Calls.first_dial >= lesser_seconds_to_forget)
        & (Calls.first_dial <= greater_sleep_and_retry)
        & (Calls.cycle_done == False)
    )
    return result
