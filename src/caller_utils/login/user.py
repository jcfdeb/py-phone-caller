from caller_utils.db.db_user import select_user_id


class User(object):
    def __init__(self, username):
        self.username = username

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(select_user_id(self.username))
