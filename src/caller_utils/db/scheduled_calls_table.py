from piccolo.columns import UUID, Timestamp, Varchar
from piccolo.table import Table
from piccolo_conf import DB


class ScheduledCalls(Table, db=DB):
    id = UUID(primary_key=True)
    phone = Varchar(length=64)
    message = Varchar(length=1024)
    call_chk_sum = Varchar(length=64)
    inserted_at = Timestamp()
    scheduled_at = Timestamp()
