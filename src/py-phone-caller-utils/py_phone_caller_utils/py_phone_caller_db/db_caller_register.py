import logging
from datetime import UTC, datetime, timedelta

from py_phone_caller_utils.config import settings
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import (
    Calls,
)

logging.basicConfig(
    format=settings.logs.log_formatter, level=settings.logs.log_level, force=True
)

RUNTIME_LOOP_IN_ERROR = "got Future attached to a different loop"
RUNTIME_LOOP_ERROR_MESSAGE = "This may indicate that database operations are being performed in different event loops."


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
    oncall=False,
    backup_callee=False,
):
    """
    Inserts a new call record into the database with the provided call details.

    This asynchronous function inserts a new call record and logs the operation.

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
        oncall (bool): Whether this is an oncall call.
        backup_callee (bool): Whether this is a backup call.

    Returns:
        None
    """

    try:
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
                oncall=oncall,
                backup_callee=backup_callee,
            )
        )
        logging.info(
            f"New cycle for the number '{phone}' with the message '{message}' starting at '{first_dial}'."
        )
    except RuntimeError as e:
        if "RUNTIME_LOOP_IN_ERROR" in str(e):
            logging.error(f"Event loop error in insert_into_db: {e}")
            logging.error("RUNTIME_LOOP_ERROR_MESSAGE")
        raise
    except Exception as e:
        logging.error(f"Error in insert_into_db: {e}")
        raise


async def update_the_call_db_record(
    call_chk_sum, current_call_id, current_dialed_times, asterisk_chan, phone, message
):
    """
    Updates an existing call record in the database with new dial information.

    This asynchronous function updates the last dial time, increments the dialed times (if not exceeding times_to_dial),
    and sets the current Asterisk channel for the specified call.

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

    try:
        call_details = await Calls.select(Calls.times_to_dial).where(
            (Calls.call_chk_sum == call_chk_sum) & (Calls.id == current_call_id)
        )

        if not call_details:
            logging.warning(
                f"No call found with call_chk_sum: {call_chk_sum} and id: {current_call_id}"
            )
            return

        times_to_dial = call_details[0].get("times_to_dial")

        new_dialed_times = current_dialed_times + 1
        if new_dialed_times > times_to_dial:
            logging.info(
                f"Not incrementing dialed_times for call {current_call_id} as it would exceed times_to_dial ({times_to_dial})"
            )
            new_dialed_times = times_to_dial

        await Calls.update(
            {
                Calls.last_dial: datetime.now(UTC).replace(tzinfo=None),
                Calls.dialed_times: new_dialed_times,
                Calls.asterisk_chan: asterisk_chan,
            }
        ).where((Calls.call_chk_sum == call_chk_sum) & (Calls.id == current_call_id))
        logging.info(
            f"Updating the call status for the number '{phone}' with the message '{message}'. UUID: '{current_call_id}'"
        )
    except RuntimeError as e:
        if "RUNTIME_LOOP_IN_ERROR" in str(e):
            logging.error(f"Event loop error in update_the_call_db_record: {e}")
            logging.error("RUNTIME_LOOP_ERROR_MESSAGE")
        raise
    except Exception as e:
        logging.error(f"Error in update_the_call_db_record: {e}")
        raise


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

    try:
        first_dial_age = await Calls.raw(
            "SELECT AGE((SELECT timezone('utc', now())),first_dial) FROM"
            + f" calls WHERE call_chk_sum='{call_chk_sum}' AND id='{current_call_id}'"
        )

        try:
            return first_dial_age[0].get("age")
        except IndexError:
            return None
    except RuntimeError as e:
        if "RUNTIME_LOOP_IN_ERROR" in str(e):
            logging.error(f"Event loop error in get_first_dial_age: {e}")
            logging.error("RUNTIME_LOOP_ERROR_MESSAGE")
        raise
    except Exception as e:
        logging.error(f"Error in get_first_dial_age: {e}")
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

    try:
        current_call_id = await Calls.raw(
            "SELECT id from calls where ((AGE((SELECT timezone('utc', now())),first_dial))"
            + f" < (SELECT {seconds_to_forget} * '1 seconds'::interval)) AND call_chk_sum='{str(call_chk_sum)}';",
        )
        try:
            return current_call_id[0].get("id")
        except IndexError:
            return None
    except RuntimeError as e:
        if "RUNTIME_LOOP_IN_ERROR" in str(e):
            logging.error(f"Event loop error in get_current_call_id: {e}")
            logging.error("RUNTIME_LOOP_ERROR_MESSAGE")
        raise
    except Exception as e:
        logging.error(f"Error in get_current_call_id: {e}")
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

    try:
        dialed_times = await Calls.raw(
            "SELECT dialed_times from calls where ((AGE((SELECT timezone('utc', now())),first_dial)) "
            + f"< (SELECT {seconds_to_forget} * '1 seconds'::interval)) AND call_chk_sum='{call_chk_sum}';"
        )
        try:
            return dialed_times[0].get("dialed_times")
        except IndexError:
            return None
    except RuntimeError as e:
        if "RUNTIME_LOOP_IN_ERROR" in str(e):
            logging.error(f"Event loop error in get_dialed_times: {e}")
            logging.error("RUNTIME_LOOP_ERROR_MESSAGE")
        raise
    except Exception as e:
        logging.error(f"Error in get_dialed_times: {e}")
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
        return None
    except RuntimeError as e:
        if "RUNTIME_LOOP_IN_ERROR" in str(e):
            logging.error(f"Event loop error in check_call_yet_present: {e}")
            logging.error("RUNTIME_LOOP_ERROR_MESSAGE")
        raise
    except Exception as e:
        logging.error(f"Error in check_call_yet_present: {e}")
        return None


async def update_acknowledgement(asterisk_chan):
    """
    Updates the acknowledgement timestamp and marks the call cycle as done for the specified Asterisk channel,
    but only if the call is within the firing period.

    This asynchronous function sets the acknowledge_at field to the current time and updates the cycle_done flag
    in the database, but only if the call is within the firing period (first_dial + seconds_to_forget > current time).

    Additionally, when a call is acknowledged (including backup calls), this function also marks any related
    oncall records with the same msg_chk_sum as cycle_done=True, to prevent further backup calls.

    Args:
        asterisk_chan (str): The identifier of the Asterisk channel.

    Returns:
        bool: True if the call was acknowledged within the firing period, False otherwise.
    """

    try:
        call_details = await Calls.select(
            Calls.first_dial, Calls.seconds_to_forget, Calls.msg_chk_sum
        ).where(Calls.asterisk_chan == asterisk_chan)

        if not call_details:
            logging.warning(f"No call found with asterisk_chan: {asterisk_chan}")
            return False

        first_dial = call_details[0].get("first_dial")
        seconds_to_forget = call_details[0].get("seconds_to_forget")
        msg_chk_sum = call_details[0].get("msg_chk_sum")
        current_time = datetime.now(UTC).replace(tzinfo=None)

        if first_dial and seconds_to_forget:
            firing_end_time = first_dial + timedelta(seconds=seconds_to_forget)

            if current_time <= firing_end_time:
                await Calls.update(
                    {
                        Calls.acknowledge_at: current_time,
                        Calls.cycle_done: True,
                    }
                ).where(Calls.asterisk_chan == asterisk_chan)
                logging.info(
                    f"Call with asterisk_chan {asterisk_chan} acknowledged within firing period."
                )

                # Also mark any related oncall records as done to stop backup calls
                if msg_chk_sum:
                    await _mark_related_oncall_records_done(msg_chk_sum, current_time)

                return True
            else:
                logging.info(
                    f"Call with asterisk_chan {asterisk_chan} not acknowledged as it's outside the firing period."
                )
                await Calls.update(
                    {
                        Calls.acknowledge_at: current_time,
                    }
                ).where(Calls.asterisk_chan == asterisk_chan)
                return False
        else:
            logging.warning(
                f"Call with asterisk_chan {asterisk_chan} has missing first_dial or seconds_to_forget."
            )
            return False
    except RuntimeError as e:
        if "RUNTIME_LOOP_IN_ERROR" in str(e):
            logging.error(f"Event loop error in update_acknowledgement: {e}")
            logging.error("RUNTIME_LOOP_ERROR_MESSAGE")
        raise
    except Exception as e:
        logging.error(f"Error in update_acknowledgement: {e}")
        raise


async def _mark_related_oncall_records_done(msg_chk_sum, current_time):
    """
    Marks all related oncall records with the same msg_chk_sum as cycle_done.

    This is called when any call (primary or backup) is acknowledged, to ensure
    that the backup call logic stops trying to initiate new calls for this message.

    Args:
        msg_chk_sum (str): The message checksum to match related calls.
        current_time (datetime): The current timestamp.

    Returns:
        None
    """
    try:
        result = await Calls.update(
            {
                Calls.cycle_done: True,
            }
        ).where(
            (Calls.msg_chk_sum == msg_chk_sum)
            & (Calls.oncall == True)
            & (Calls.cycle_done == False)
        )
        logging.info(
            f"Marked related oncall records as done for msg_chk_sum: {msg_chk_sum}"
        )
    except Exception as e:
        logging.error(f"Error marking related oncall records as done: {e}")


async def update_heard_at(asterisk_chan):
    """
    Updates the 'heard_at' timestamp for the specified Asterisk channel in the database.

    This asynchronous function sets the heard_at field to the current time for the matching call record.

    Args:
        asterisk_chan (str): The identifier of the Asterisk channel.

    Returns:
        None
    """

    try:
        await Calls.update(
            {Calls.heard_at: datetime.now(UTC).replace(tzinfo=None)}
        ).where(Calls.asterisk_chan == asterisk_chan)
    except RuntimeError as e:
        if "RUNTIME_LOOP_IN_ERROR" in str(e):
            logging.error(f"Event loop error in update_heard_at: {e}")
            logging.error("RUNTIME_LOOP_ERROR_MESSAGE")
        raise
    except Exception as e:
        logging.error(f"Error in update_heard_at: {e}")
        raise


async def get_msg_chk_sum(asterisk_chan):
    """
    Retrieves the message and its checksum for the specified Asterisk channel from the database.

    This asynchronous function queries the Calls table for the message and msg_chk_sum fields for the given channel.

    Args:
        asterisk_chan (str): The identifier of the Asterisk channel.

    Returns:
        tuple: A tuple containing the message and its checksum, or (None, None) if not found.
    """

    try:
        message_and_msg_chk_sum = await Calls.select(
            Calls.msg_chk_sum, Calls.message
        ).where(Calls.asterisk_chan == asterisk_chan)
        return (
            message_and_msg_chk_sum[0].get("message", None),
            message_and_msg_chk_sum[0].get("msg_chk_sum", None),
        )
    except IndexError:
        return None, None
    except RuntimeError as e:
        if "RUNTIME_LOOP_IN_ERROR" in str(e):
            logging.error(f"Event loop error in get_msg_chk_sum: {e}")
            logging.error("RUNTIME_LOOP_ERROR_MESSAGE")
        raise
    except Exception as e:
        logging.error(f"Error in get_msg_chk_sum: {e}")
        return None, None


async def select_calls():
    """
    Retrieves all call records from the Calls table in the database.

    This asynchronous function returns all stored call records.

    Returns:
        list: A list of all call records in the database.
    """

    try:
        return await Calls.select()
    except RuntimeError as e:
        if "RUNTIME_LOOP_IN_ERROR" in str(e):
            logging.error(f"Event loop error in select_calls: {e}")
            logging.error("RUNTIME_LOOP_ERROR_MESSAGE")
        raise
    except Exception as e:
        logging.error(f"Error in select_calls: {e}")
        return []
