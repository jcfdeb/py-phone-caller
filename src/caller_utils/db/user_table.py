from piccolo.columns import UUID, Boolean, Timestamp, Varchar
from piccolo.table import Table
from piccolo_conf import DB


class Users(Table, db=DB):
    id = UUID(primary_key=True)
    given_name = Varchar(length=128)
    email = Varchar(length=128, unique=True)
    password = Varchar(length=1024)
    is_active = Boolean(default=True)
    created_on = Timestamp()
    last_login = Timestamp(null=True, default=None)
