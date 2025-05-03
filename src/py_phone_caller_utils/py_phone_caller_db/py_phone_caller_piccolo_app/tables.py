from piccolo.columns import (JSONB, UUID, Boolean, Integer, SmallInt,
                             Timestamp, Varchar)
from piccolo.table import Table


class AsteriskWsEvents(Table):
    """
    Represents an event received from the Asterisk WebSocket interface.

    This Piccolo ORM table stores the channel, event type, and associated JSON data for each event.
    """

    id = UUID(primary_key=True)
    asterisk_chan = Varchar(length=64)
    event_type = Varchar(length=64)
    json_data = JSONB()


class ScheduledCalls(Table):
    """
    Represents a scheduled call entry in the system.

    This Piccolo ORM table stores the phone number, message, checksum, and timestamps for each scheduled call.
    """

    id = UUID(primary_key=True)
    phone = Varchar(length=64)
    message = Varchar(length=1024)
    call_chk_sum = Varchar(length=64)
    inserted_at = Timestamp()
    scheduled_at = Timestamp()


class Users(Table):
    """
    Represents a user account in the system.

    This Piccolo ORM table stores user details including name, email, password, status, and metadata.
    """

    id = UUID(primary_key=True)
    given_name = Varchar(length=128)
    email = Varchar(length=128, unique=True)
    password = Varchar(length=1024)
    is_active = Boolean(default=True)
    created_on = Timestamp()
    last_login = Timestamp(null=True, default=None)
    annotations = Varchar(length=2048)


class Calls(Table):
    """
    Represents a call record in the system, including call state and metadata.

    This Piccolo ORM table stores details about each call, such as phone number, message, channel, checksums, dial attempts, timing, and status flags.
    """

    id = UUID(primary_key=True)
    phone = Varchar(length=64)
    message = Varchar(length=1024)
    asterisk_chan = Varchar(length=64)
    msg_chk_sum = Varchar(length=64)
    call_chk_sum = Varchar(length=64)
    unique_chk_sum = Varchar(length=64)
    times_to_dial = SmallInt()
    dialed_times = SmallInt()
    seconds_to_forget = Integer()
    first_dial = Timestamp()
    last_dial = Timestamp()
    heard_at = Timestamp()
    acknowledge_at = Timestamp()
    cycle_done = Boolean(default=False)
