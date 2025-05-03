import logging
import os
import secrets
import string

import asyncpg
from werkzeug.security import generate_password_hash

from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import \
    Users


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
    await Users.create_table(if_not_exists=True)
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
    await Users.create_table(if_not_exists=True)
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
    Users.create_table(if_not_exists=True)
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
    Users.create_table(if_not_exists=True)
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
    await Users.create_table(if_not_exists=True)
    await Users.update({Users.password: await hashed_password(password)}).where(
        Users.email == email
    )


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
    Users.create_table(if_not_exists=True)
    count = Users.count().run_sync()
    return count == 0


async def ensure_admin_user_exists(admin_email, given_name="Admin"):
    """
    Ensures that an admin user exists in the Users table, creating one if necessary.

    This asynchronous function checks for the admin user by email, creates the user with a generated password if not found, and returns the password if created.

    Args:
        admin_email (str): The email address of the admin user.
        given_name (str, optional): The given name for the admin user. Defaults to "Admin".

    Returns:
        str or None: The generated password if a new admin user was created, or None if the user already exists.
    """
    await Users.create_table(if_not_exists=True)
    user = await select_user(admin_email)

    if not user:
        password = generate_complex_password()
        await insert_user(given_name, admin_email, password)
        logging.info(f"Created admin user '{admin_email}' with password: {password}")
        return password
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
    reset_password = os.environ.get("UI_USER_RESET_PASSWORD", "").lower() == "true"

    if reset_password:
        password = generate_complex_password()
        await update_password(admin_email, password)
        logging.info(f"Reset password for user '{admin_email}' to: {password}")
        return password
    return None
