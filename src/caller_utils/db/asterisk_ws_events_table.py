from piccolo.columns import JSONB, UUID, Varchar
from piccolo.table import Table
from piccolo_conf import DB


class AsteriskWsEvents(Table, db=DB):
    id = UUID(primary_key=True)
    asterisk_chan = Varchar(length=64)
    event_type = Varchar(length=64)
    json_data = JSONB()
