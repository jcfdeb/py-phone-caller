import hashlib
import hmac
import logging
import os
import secrets
import string

import asyncpg
from werkzeug.security import check_password_hash, generate_password_hash

from py_phone_caller_utils.config import settings
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import (
    Users,
)


logging.basicConfig(
    format=settings.logs.log_formatter, level=settings.logs.log_level, force=True
)

LEGACY_PASSWORD_HASH_METHODS = {"sha512"}
UI_USER_RESET_PASSWORD_ENV_VAR = "UI_USER_RESET_PASSWORD"


def _split_password_hash(password_hash):
    try:
        method, salt, hashval = password_hash.split("$", 2)
    except (AttributeError, ValueError):
        return None, None, None
    return method, salt, hashval


def is_legacy_password_hash(password_hash):
    method, _, _ = _split_password_hash(password_hash)
    return method in LEGACY_PASSWORD_HASH_METHODS


def _check_legacy_password_hash(password_hash, password):
    method, salt, hashval = _split_password_hash(password_hash)
    if method not in LEGACY_PASSWORD_HASH_METHODS or not salt or not hashval:
        return False

    try:
        hashlib.new(method)
    except ValueError:
        logging.warning("Unsupported legacy password hash method: %s", method)
        return False

    candidate_hash = hmac.new(
        salt.encode("utf-8"), password.encode("utf-8"), method
    ).hexdigest()
    return hmac.compare_digest(candidate_hash, hashval)


def check_user_password(password_hash, password):
    if not password_hash or password is None:
        return False

    try:
        return check_password_hash(password_hash, password)
    except ValueError as exc:
        if _check_legacy_password_hash(password_hash, password):
            logging.warning(
                "Authenticated using a legacy password hash. The password should be rehashed."
            )
            return True

        logging.warning("Rejected unsupported password hash: %s", exc)
        return False


def is_admin_password_setup_requested():
    return os.environ.get(UI_USER_RESET_PASSWORD_ENV_VAR, "").lower() == "true"


async def hashed_password(password):
    """
    Generates a hashed version of the provided password for secure storage.

    This asynchronous function uses Werkzeug's generate_password_hash to hash the password.

    Args:
        password (str): The plain text password to hash.

    Returns:
        str: The hashed password.
    """
    return generate_password_hash(password)


async def insert_user(given_name, email, password):
    """
    Inserts a new user record into the Users table with the provided details.

    This asynchronous function creates the Users table if it does not exist, hashes the password, inserts the user, and handles unique constraint violations.

    Args:
        given_name (str): The given name of the user.
        email (str): The email address of the user.
        password (str): The plain text password for the user.

    Returns:
        str or None: An error message if the user already exists, or None on success.
    """
    try:
        await Users.insert(
            Users(
                given_name=given_name,
                email=email,
                password=await hashed_password(password),
            )
        )
    except asyncpg.exceptions.UniqueViolationError:
        return f"The user '{email}' already exists."


async def select_user(email):
    """
    Retrieves a user record from the Users table based on the provided email address.

    This asynchronous function ensures the Users table exists and returns the first matching user record.

    Args:
        email (str): The email address of the user to retrieve.

    Returns:
        dict or None: The user record as a dictionary if found, or None if no user matches the email.
    """
    return await Users.select().where(Users.email == email).first()


def select_user_id(email):
    """
    Retrieves the unique user ID for the given email address from the Users table.

    This function ensures the Users table exists, queries for the user ID, and returns it as a string if found.

    Args:
        email (str): The email address of the user.

    Returns:
        str or None: The user ID as a string if found, or None if no user matches the email.
    """
    result = Users.select(Users.id).where(Users.email == email).first().run_sync()
    try:
        return str(result.get("id"))
    except AttributeError:
        return None


def load_user_by_id(user_id):
    """
    Retrieves a user record from the Users table based on the provided user ID.

    This function ensures the Users table exists, queries for the user by ID, and returns the user record if found.

    Args:
        user_id (str): The unique identifier of the user.

    Returns:
        dict or None: The user record as a dictionary if found, or None if no user matches the ID.
    """
    result = Users.select().where(Users.id == user_id).first().run_sync()
    try:
        return result
    except AttributeError:
        return None


async def update_password(email, password):
    """
    Updates the password for the user with the specified email address.

    This asynchronous function hashes the new password and updates the Users table accordingly.

    Args:
        email (str): The email address of the user whose password is to be updated.
        password (str): The new plain text password.

    Returns:
        None
    """
    rows_updated = await Users.update(
        {Users.password: await hashed_password(password)}
    ).where(Users.email == email)
    logging.info(f"Updated password for user '{email}'. Rows affected: {rows_updated}")


def generate_complex_password(length=40):
    """
    Generates a random complex password consisting of ASCII letters and digits.

    This function creates a password of the specified length using a secure random choice of characters.

    Args:
        length (int, optional): The desired length of the password. Defaults to 40.

    Returns:
        str: The generated complex password.
    """
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def is_users_table_empty():
    """
    Checks if the Users table in the database is empty.

    This function ensures the Users table exists, counts the number of records, and returns True if there are no users.

    Returns:
        bool: True if the Users table is empty, False otherwise.
    """
    count = Users.count().run_sync()
    return count == 0


async def is_users_table_empty_async():
    """
    Checks asynchronously if the Users table in the database is empty.

    Returns:
        bool: True if the Users table is empty, False otherwise.
    """
    count = await Users.count()
    return count == 0


async def ensure_admin_user_exists(admin_email, given_name="Admin"):
    """
    Ensures that an admin user exists during initial database bootstrap.

    This asynchronous function checks for the admin user by email. If the admin
    user is missing, it only creates one when the Users table is empty and
    explicit password setup was requested, avoiding silent admin recreation in
    existing installations.

    Args:
        admin_email (str): The email address of the admin user.
        given_name (str, optional): The given name for the admin user. Defaults to "Admin".

    Returns:
        str or None: The generated password if a new admin user was created, or None if the user already exists.
    """
    user = await select_user(admin_email)
    if not user:
        if not await is_users_table_empty_async():
            logging.warning(
                "Admin user '%s' is missing, but existing users are present. "
                "Skipping automatic admin recreation.",
                admin_email,
            )
            return None

        if not is_admin_password_setup_requested():
            logging.warning(
                "Admin user '%s' is missing and the Users table is empty, but "
                "%s is not set to true. Skipping automatic admin creation.",
                admin_email,
                UI_USER_RESET_PASSWORD_ENV_VAR,
            )
            return None

        password = generate_complex_password()
        await insert_user(given_name, admin_email, password)
        logging.info(
            f"Created initial admin user '{admin_email}' with password: {password}"
        )
        return password
    else:
        logging.debug(f"Admin user '{admin_email}' already exists.")
    return None


async def reset_admin_password_if_needed(admin_email):
    """
    Resets the admin user's password if the environment variable UI_USER_RESET_PASSWORD is set to true.

    This asynchronous function generates a new password, updates the admin user's password, logs the change, and returns the new password if a reset is performed.

    Args:
        admin_email (str): The email address of the admin user.

    Returns:
        str or None: The new password if the reset was performed, or None otherwise.
    """
    reset_env_val = os.environ.get(UI_USER_RESET_PASSWORD_ENV_VAR, "")
    reset_password = is_admin_password_setup_requested()

    if reset_password:
        logging.info(
            f"Checking if password reset is needed. UI_USER_RESET_PASSWORD='{reset_env_val}' -> {reset_password}"
        )
        user = await select_user(admin_email)
        if not user:
            logging.warning(
                "Admin user '%s' is missing. Skipping password reset because no "
                "admin account was found.",
                admin_email,
            )
            return None

        password = generate_complex_password()
        logging.info(f"Attempting to reset password for user '{admin_email}'...")
        await update_password(admin_email, password)
        logging.info(
            f"Successfully reset password for user '{admin_email}' to: {password}"
        )
        return password
    return None
