import logging
from datetime import UTC, datetime

import py_phone_caller_utils.caller_configuration as conf
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import \
    Calls

logging.basicConfig(format=conf.get_log_formatter())


async def insert_into_db(
    phone,
    message,
    asterisk_chan,
    msg_chk_sum,
    call_chk_sum,
    unique_chk_sum,
    first_dial,
    seconds_to_forget,
    times_to_dial,
):
    """
    Inserts a new call record into the database with the provided call details.

    This asynchronous function creates the Calls table if it does not exist, inserts a new call record, and logs the operation.

    Args:
        phone (str): The recipient's phone number.
        message (str): The message content for the call.
        asterisk_chan (str): The identifier of the Asterisk channel.
        msg_chk_sum (str): The checksum of the message.
        call_chk_sum (str): The checksum of the call.
        unique_chk_sum (str): The unique checksum for this call attempt.
        first_dial (datetime): The timestamp of the first dial attempt.
        seconds_to_forget (int): The time window for forgetting the call.
        times_to_dial (int): The maximum number of dial attempts.

    Returns:
        None
    """
    await Calls.create_table(if_not_exists=True)
    await Calls.insert(
        Calls(
            phone=phone,
            message=message,
            asterisk_chan=asterisk_chan,
            msg_chk_sum=msg_chk_sum,
            call_chk_sum=call_chk_sum,
            unique_chk_sum=unique_chk_sum,
            first_dial=first_dial,
            seconds_to_forget=seconds_to_forget,
            times_to_dial=times_to_dial,
            dialed_times=1,
            last_dial=datetime.min,
            heard_at=datetime.min,
            acknowledge_at=datetime.min,
        )
    )
    logging.info(
        f"New cycle for the number '{phone}' with the message '{message}' starting at '{first_dial}'."
    )


async def update_the_call_db_record(
    call_chk_sum, current_call_id, current_dialed_times, asterisk_chan, phone, message
):
    """
    Updates an existing call record in the database with new dial information.

    This asynchronous function updates the last dial time, increments the dialed times, and sets the current Asterisk channel for the specified call.

    Args:
        call_chk_sum (str): The checksum of the call.
        current_call_id (str): The unique identifier of the current call record.
        current_dialed_times (int): The current number of times the call has been dialed.
        asterisk_chan (str): The identifier of the Asterisk channel.
        phone (str): The recipient's phone number.
        message (str): The message associated with the call.

    Returns:
        None
    """
    await Calls.create_table(if_not_exists=True)
    await Calls.update(
        {
            Calls.last_dial: datetime.now(UTC).replace(tzinfo=None),
            Calls.dialed_times: current_dialed_times + 1,
            Calls.asterisk_chan: asterisk_chan,
        }
    ).where(Calls.call_chk_sum == call_chk_sum and Calls.id == current_call_id)
    logging.info(
        f"Updating the call status for the number '{phone}' with the message '{message}'. UUID: '{current_call_id}'"
    )


async def get_first_dial_age(call_chk_sum, current_call_id):
    """
    Retrieves the time elapsed since the first dial attempt for a given call.

    This asynchronous function queries the database for the age of the first dial based on the call checksum and ID.

    Args:
        call_chk_sum (str): The checksum of the call.
        current_call_id (str): The unique identifier of the current call record.

    Returns:
        timedelta or None: The time elapsed since the first dial, or None if not found.
    """
    await Calls.create_table(if_not_exists=True)
    first_dial_age = await Calls.raw(
        "SELECT AGE((SELECT timezone('utc', now())),first_dial) FROM"
        + f" calls WHERE call_chk_sum='{call_chk_sum}' AND id='{current_call_id}'"
    )

    try:
        return first_dial_age[0].get("age")
    except IndexError:
        return None


async def get_current_call_id(seconds_to_forget, call_chk_sum):
    """
    Retrieves the current call record ID for a call within the active retry period.

    This asynchronous function queries the database for the call ID based on the call checksum and the allowed time window.

    Args:
        seconds_to_forget (int): The time window in seconds for considering a call as active.
        call_chk_sum (str): The checksum of the call.

    Returns:
        str or None: The unique identifier of the current call record, or None if not found.
    """
    await Calls.create_table(if_not_exists=True)
    current_call_id = await Calls.raw(
        "SELECT id from calls where ((AGE((SELECT timezone('utc', now())),first_dial))"
        + f" < (SELECT {seconds_to_forget} * '1 seconds'::interval)) AND call_chk_sum='{str(call_chk_sum)}';",
    )
    try:
        return current_call_id[0].get("id")
    except IndexError:
        return None


async def get_dialed_times(seconds_to_forget, call_chk_sum):
    """
    Retrieves the number of times a call has been dialed within the active retry period.

    This asynchronous function queries the database for the dialed_times value based on the call checksum and the allowed time window.

    Args:
        seconds_to_forget (int): The time window in seconds for considering a call as active.
        call_chk_sum (str): The checksum of the call.

    Returns:
        int or None: The number of times the call has been dialed, or None if not found.
    """
    await Calls.create_table(if_not_exists=True)
    dialed_times = await Calls.raw(
        "SELECT dialed_times from calls where ((AGE((SELECT timezone('utc', now())),first_dial)) "
        + f"< (SELECT {seconds_to_forget} * '1 seconds'::interval)) AND call_chk_sum='{call_chk_sum}';"
    )
    try:
        return dialed_times[0].get("dialed_times")
    except IndexError:
        return None


async def check_call_yet_present(call_chk_sum, phone, message):
    """
    Checks if a call with the given checksum already exists in the database.

    This asynchronous function queries the Calls table for an existing call with the specified checksum and logs the result.

    Args:
        call_chk_sum (str): The checksum of the call.
        phone (str): The recipient's phone number.
        message (str): The message content for the call.

    Returns:
        str or None: The call checksum if present, or None if no matching call is found.
    """
    try:
        await Calls.create_table(if_not_exists=True)
        call_yet_present = await Calls.select(Calls.call_chk_sum).where(
            Calls.call_chk_sum == call_chk_sum
        )
        logging.info(
            f"Call received for the number '{phone}' with the message '{message}'."
        )
        return call_yet_present[0].get("call_chk_sum", None)
    except IndexError:
        logging.info(
            f"No previous call in the DB, for the number '{phone}' with the message '{message}'."
        )


async def update_acknowledgement(asterisk_chan):
    """
    Updates the acknowledgement timestamp and marks the call cycle as done for the specified Asterisk channel.

    This asynchronous function sets the acknowledge_at field to the current time and updates the cycle_done flag in the database.

    Args:
        asterisk_chan (str): The identifier of the Asterisk channel.

    Returns:
        None
    """
    await Calls.create_table(if_not_exists=True)
    await Calls.update(
        {
            Calls.acknowledge_at: datetime.now(UTC).replace(tzinfo=None),
            Calls.cycle_done: True,
        }
    ).where(Calls.asterisk_chan == asterisk_chan)


async def update_heard_at(asterisk_chan):
    """
    Updates the 'heard_at' timestamp for the specified Asterisk channel in the database.

    This asynchronous function sets the heard_at field to the current time for the matching call record.

    Args:
        asterisk_chan (str): The identifier of the Asterisk channel.

    Returns:
        None
    """
    await Calls.create_table(if_not_exists=True)
    await Calls.update({Calls.heard_at: datetime.now(UTC).replace(tzinfo=None)}).where(
        Calls.asterisk_chan == asterisk_chan
    )


async def get_msg_chk_sum(asterisk_chan):
    """
    Retrieves the message and its checksum for the specified Asterisk channel from the database.

    This asynchronous function queries the Calls table for the message and msg_chk_sum fields for the given channel.

    Args:
        asterisk_chan (str): The identifier of the Asterisk channel.

    Returns:
        tuple: A tuple containing the message and its checksum, or (None, None) if not found.
    """
    await Calls.create_table(if_not_exists=True)
    message_and_msg_chk_sum = await Calls.select(
        Calls.msg_chk_sum, Calls.message
    ).where(Calls.asterisk_chan == asterisk_chan)
    return (
        message_and_msg_chk_sum[0].get("message", None),
        message_and_msg_chk_sum[0].get("msg_chk_sum", None),
    )


async def select_calls():
    """
    Retrieves all call records from the Calls table in the database.

    This asynchronous function ensures the Calls table exists and returns all stored call records.

    Returns:
        list: A list of all call records in the database.
    """
    await Calls.create_table(if_not_exists=True)
    return await Calls.select()
