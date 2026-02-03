from piccolo.columns import JSONB, UUID, Boolean, Integer, SmallInt, Timestamp, Varchar
from piccolo.columns.defaults.timestamp import TimestampNow
from piccolo.columns.defaults.uuid import UUID4
from piccolo.table import Table


class AsteriskWsEvents(Table):
    """
    Represents an event received from the Asterisk WebSocket interface.

    This Piccolo ORM table stores the channel, event type, and associated JSON data for each event.
    """

    id = UUID(primary_key=True, default=UUID4())
    asterisk_chan = Varchar(length=64, default="")
    event_type = Varchar(length=64, default="")
    json_data = JSONB(default="{}")


class ScheduledCalls(Table):
    """
    Represents a scheduled call entry in the system.

    This Piccolo ORM table stores the phone number, message, checksum, and timestamps for each scheduled call.
    """

    id = UUID(primary_key=True, default=UUID4())
    phone = Varchar(length=64, default="")
    message = Varchar(length=1024, default="")
    call_chk_sum = Varchar(length=64, default="")
    inserted_at = Timestamp(default=TimestampNow())
    scheduled_at = Timestamp(default=TimestampNow())


class Users(Table):
    """
    Represents a user account in the system.

    This Piccolo ORM table stores user details including name, email, password, status, and metadata.
    """

    id = UUID(primary_key=True, default=UUID4())
    given_name = Varchar(length=128, default="")
    email = Varchar(length=128, unique=True)
    password = Varchar(length=1024, default="")
    is_active = Boolean(default=True)
    created_on = Timestamp(default=TimestampNow())
    last_login = Timestamp(null=True, default=None)
    annotations = Varchar(length=2048, default="")


class Calls(Table):
    """
    Represents a call record in the system, including call state and metadata.

    This Piccolo ORM table stores details about each call, such as phone number, message, channel, checksums, dial attempts, timing, and status flags.
    """

    id = UUID(primary_key=True, default=UUID4())
    phone = Varchar(length=64, default="")
    message = Varchar(length=1024, default="")
    asterisk_chan = Varchar(length=64, default="")
    msg_chk_sum = Varchar(length=64, default="")
    call_chk_sum = Varchar(length=64, default="")
    unique_chk_sum = Varchar(length=64, default="")
    times_to_dial = SmallInt(default=0)
    dialed_times = SmallInt(default=0)
    seconds_to_forget = Integer(default=0)
    first_dial = Timestamp(default=TimestampNow())
    last_dial = Timestamp(default=TimestampNow())
    heard_at = Timestamp(default=TimestampNow())
    acknowledge_at = Timestamp(default=TimestampNow())
    cycle_done = Boolean(default=False)
    oncall = Boolean(default=False)
    backup_callee = Boolean(default=False)
    call_backup_callee_number_calls = SmallInt(default=0)


class AddressBook(Table):
    """
    Represents the address book for the contacts.
    """

    id = UUID(primary_key=True, default=UUID4())
    name = Varchar(length=64, default="")
    surname = Varchar(length=64, default="")
    address = Varchar(length=256, default="")
    zip_code = Varchar(length=32, default="")
    city = Varchar(length=64, default="")
    state = Varchar(length=64, default="")
    country = Varchar(length=64, default="")
    phone_number = Varchar(length=64, default="")
    on_call_availability = JSONB(default="{}")
    created_time = Timestamp(default=TimestampNow())
    enabled = Boolean(default=False)
    annotations = Varchar(length=1024, default="")
