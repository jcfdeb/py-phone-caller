import asyncpg
from user_table import Users
from werkzeug.security import check_password_hash, generate_password_hash


async def hashed_password(password):
    "Generates a password hash"
    return generate_password_hash(password, method="sha512")


async def insert_user(given_name, email, password):
    "Insert a new user record and crates the DB table if not exists"
    await Users.create_table(if_not_exists=True)
    try:
        await Users.insert(
            Users(
                given_name=given_name,
                email=email,
                password=await hashed_password(password),
            )
        )
    except asyncpg.exceptions.UniqueViolationError as err:
        return f"The user '{email}' already exists."


async def select_user(email):
    "Get all the user from the DB table"
    result = await Users.select().where(Users.email == email).first()
    return result


def select_user_id(email):
    """Get the user's id from the DB table"""
    result = Users.select(Users.id).where(Users.email == email).first().run_sync()
    try:
        return str(result.get("id"))
    except AttributeError:
        return None


def load_user_by_id(user_id):
    """Get the user's id from '@login_manager.user_loader' in 'app.py'"""
    result = Users.select().where(Users.id == user_id).first().run_sync()
    try:
        return result
    except AttributeError:
        return None


async def update_password(email, password):
    "Update the password of a given user"
    await Users.update({Users.password: await hashed_password(password)}).where(
        Users.email == email
    )
