from piccolo.columns import (UUID, Boolean, Integer, SmallInt, Timestamp,
                             Varchar)
from piccolo.table import Table
from piccolo_conf import DB


class Calls(Table, db=DB):
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
