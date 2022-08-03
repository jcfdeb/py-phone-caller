import datetime
import logging

from calls_table import Calls

import caller_utils.caller_configuration as conf

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
    """Function to insert a 'new' record"""
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
            last_dial=datetime.datetime.min,
            heard_at=datetime.datetime.min,
            acknowledge_at=datetime.datetime.min,
        )
    )
    logging.info(
        f"New cycle for the number '{phone}' with the message '{message}' starting at '{first_dial}'."
    )


async def update_the_call_db_record(
    call_chk_sum, current_call_id, current_dialed_times, asterisk_chan, phone, message
):
    """Updates the call record when a retry is placed when inside the 'seconds_to_forget' period"""
    await Calls.update(
        {
            Calls.last_dial: datetime.datetime.utcnow(),
            Calls.dialed_times: current_dialed_times + 1,
            Calls.asterisk_chan: asterisk_chan,
        }
    ).where(Calls.call_chk_sum == call_chk_sum and Calls.id == current_call_id)
    logging.info(
        f"Updating the call status for the number '{phone}' with the message '{message}'. UUID: '{current_call_id}'"
    )


async def get_first_dial_age(call_chk_sum, current_call_id):
    """Helper to calculate the call record age"""
    first_dial_age = await Calls.raw(
        "SELECT AGE((SELECT timezone('utc', now())),first_dial) FROM"
        + f" calls WHERE call_chk_sum='{call_chk_sum}' AND id='{current_call_id}'"
    )
    return first_dial_age[0].get("age")


async def get_current_call_id(seconds_to_forget, call_chk_sum):
    """Getting the current call ID based on the 'seconds_to_forget' parameter"""
    current_call_id = await Calls.raw(
        "SELECT id from calls where ((AGE((SELECT timezone('utc', now())),first_dial))"
        + f" < (SELECT {seconds_to_forget} * '1 seconds'::interval)) AND call_chk_sum='{str(call_chk_sum)}';",
    )
    return current_call_id[0].get("id", None)


async def get_dialed_times(seconds_to_forget, call_chk_sum):
    """Getting the number of dials of a given alert"""
    dialed_times = await Calls.raw(
        "SELECT dialed_times from calls where ((AGE((SELECT timezone('utc', now())),first_dial)) "
        + f"< (SELECT {seconds_to_forget} * '1 seconds'::interval)) AND call_chk_sum='{call_chk_sum}';"
    )
    return dialed_times[0].get("dialed_times", None)


async def check_call_yet_present(call_chk_sum, phone, message):
    """Verify for the call record existence, returning the 'call_chk_sum'"""
    try:
        call_yet_present = await Calls.select(Calls.call_chk_sum).where(
            Calls.call_chk_sum == call_chk_sum
        )
        logging.info(
            f"Call received for the number '{phone}' with the message '{message}'."
        )
        return call_yet_present[0].get("call_chk_sum", None)
    except Exception:
        logging.info(
            f"No previous call in the DB, for the number '{phone}' with the message '{message}'."
        )


async def update_acknowledgement(asterisk_chan):
    """Tries to update the DB record when a GET request arrives from the Asterisk PBX (press 4 for Ack.)"""
    await Calls.update(
        {Calls.acknowledge_at: datetime.datetime.utcnow(), Calls.cycle_done: True}
    ).where(Calls.asterisk_chan == asterisk_chan)


async def update_heard_at(asterisk_chan):
    """When the Asterisk PBX plays the audio message, ww update the DB record when a GET request comes in"""
    await Calls.update({Calls.heard_at: datetime.datetime.utcnow()}).where(
        Calls.asterisk_chan == asterisk_chan
    )


async def get_msg_chk_sum(asterisk_chan):
    """Retrieve the 'msg_chk_sum' from the DB, is used as part of name for the audio file"""
    message_and_msg_chk_sum = await Calls.select(
        Calls.msg_chk_sum, Calls.message
    ).where(Calls.asterisk_chan == asterisk_chan)
    return (
        message_and_msg_chk_sum[0].get("message", None),
        message_and_msg_chk_sum[0].get("msg_chk_sum", None),
    )


async def select_calls():
    """Returns the list of the received calls from a SELECT from the 'calls' table"""
    return await Calls.select()
