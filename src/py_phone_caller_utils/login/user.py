from py_phone_caller_utils.py_phone_caller_db.db_user import select_user_id


class User(object):
    def __init__(self, username):
        """
        Initializes a User instance with the provided username.

        This constructor sets the username attribute for the user object.

        Args:
            username (str): The username of the user.
        """
        self.username = username

    @property
    def is_authenticated(self):
        """
        Indicates whether the user is authenticated.

        This property always returns True for User instances.

        Returns:
            bool: True, indicating the user is authenticated.
        """
        return True

    @property
    def is_active(self):
        """
        Indicates whether the user account is active.

        This property always returns True for User instances.

        Returns:
            bool: True, indicating the user account is active.
        """
        return True

    @property
    def is_anonymous(self):
        """
        Indicates whether the user is anonymous.

        This property always returns False for User instances.

        Returns:
            bool: False, indicating the user is not anonymous.
        """
        return False

    def get_id(self):
        """
        Retrieves the unique identifier for the user from the database.

        This method returns the user ID as a string based on the username.

        Returns:
            str: The unique identifier of the user.
        """
        return str(select_user_id(self.username))
