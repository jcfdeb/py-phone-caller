from calls_table import Calls


async def select_to_recall(
    times_to_dial, lesser_seconds_to_forget, greater_sleep_and_retry
):
    result = await Calls.select(
        Calls.phone, Calls.message, Calls.seconds_to_forget
    ).where(
        (Calls.dialed_times < times_to_dial)
        & (Calls.first_dial >= lesser_seconds_to_forget)
        & (Calls.first_dial <= greater_sleep_and_retry)
        & (Calls.cycle_done == False)
    )
    return result
