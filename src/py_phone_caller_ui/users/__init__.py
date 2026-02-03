"""
Users blueprint for the Py Phone Caller UI.

Provides routes for managing user accounts, including adding, deleting, and
changing passwords.
"""

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash

from .constants import UI_ADMIN_USER, MIN_PASSWORD_LENGTH

from py_phone_caller_utils.py_phone_caller_db.db_user import (
    update_password,
    insert_user,
    generate_complex_password,
)
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import (
    Users,
)

users_blueprint = Blueprint(
    "users_blueprint",
    __name__,
    template_folder="templates/users",
)


@users_blueprint.route("/users")
@login_required
async def users():
    """
    Displays a paginated, searchable, and sortable list of user accounts for authenticated users.

    This asynchronous view retrieves user data, applies search and sorting filters, paginates the results,
    and renders the users.html template with the relevant context for the UI.

    Returns:
        flask.Response: The rendered HTML page displaying the user accounts.
    """

    search_query = request.args.get("search", "").lower()
    sort_by = request.args.get("sort_by", "given_name")
    sort_order = request.args.get("sort_order", "asc")

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)

    admin_email = UI_ADMIN_USER.lower()
    session_email = getattr(current_user, "username", "").lower()
    is_admin_session = session_email == admin_email

    all_users = await Users.select().order_by(Users.given_name)

    users_data = {}
    for idx, user in enumerate(all_users):
        users_data[idx] = {
            "id": str(user["id"]),
            "given_name": user["given_name"],
            "email": user["email"],
            "is_active": user["is_active"],
            "created_on": user["created_on"],
            "last_login": user["last_login"],
        }

    if not is_admin_session:
        users_data = {
            idx: data
            for idx, data in users_data.items()
            if str(data.get("email", "")).lower() == session_email
        }

    if search_query and is_admin_session:
        filtered_users = {}
        for idx, user_data in users_data.items():
            if any(search_query in str(value).lower() for value in user_data.values()):
                filtered_users[idx] = user_data
        users_data = filtered_users

    paginated_keys = list(users_data.keys())

    if sort_by == "given_name":
        paginated_keys.sort(
            key=lambda k: users_data[k].get("given_name", ""),
            reverse=(sort_order == "desc"),
        )
    elif sort_by == "email":
        paginated_keys.sort(
            key=lambda k: users_data[k].get("email", ""), reverse=(sort_order == "desc")
        )
    elif sort_by == "created_on":
        paginated_keys.sort(
            key=lambda k: users_data[k].get("created_on", ""),
            reverse=(sort_order == "desc"),
        )
    elif sort_by == "last_login":
        paginated_keys.sort(
            key=lambda k: users_data[k].get("last_login", "") or "",
            reverse=(sort_order == "desc"),
        )

    total_items = len(paginated_keys)
    total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 1

    page = max(1, min(page, total_pages)) if total_pages > 0 else 1

    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, total_items)
    paginated_keys = paginated_keys[start_idx:end_idx]

    return render_template(
        "users.html",
        search_query=search_query if is_admin_session else "",
        users_data=users_data,
        paginated_data=paginated_keys,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        sort_by=sort_by,
        sort_order=sort_order,
        home_url=url_for("home_blueprint.home"),
        calls_url=url_for("calls_blueprint.calls"),
        ws_events_url=url_for("ws_events_blueprint.ws_events"),
        schedule_call_url=url_for("schedule_call_blueprint.schedule_call"),
        users_url=url_for("users_blueprint.users"),
        address_book_url=url_for("address_book_blueprint.address_book"),
        logout_url=url_for("home_blueprint.logout"),
        admin_email=UI_ADMIN_USER,
        is_admin_session=is_admin_session,
        current_user_email=session_email,
    )


@users_blueprint.route("/users/change_password", methods=["POST"])
@login_required
async def change_password():
    """
    Handles user password change requests, validating input and updating the password if all checks pass.

    This asynchronous view checks the old password, validates the new password against security requirements,
    updates the password in the database, and returns a JSON response indicating success or failure.

    Returns:
        flask.Response: A JSON response with success status and message.
    """
    user_id = request.form.get("user_id")
    old_password = request.form.get("old_password")
    new_password = request.form.get("new_password")
    confirm_password = request.form.get("confirm_password")

    if not all([user_id, old_password, new_password, confirm_password]):
        return jsonify({"success": False, "message": "All fields are required"}), 400

    if new_password != confirm_password:
        return jsonify({"success": False, "message": "New passwords do not match"}), 400

    if len(new_password) < MIN_PASSWORD_LENGTH:
        return (
            jsonify(
                {
                    "success": False,
                    "message": f"Password must be at least {MIN_PASSWORD_LENGTH} characters long",
                }
            ),
            400,
        )

    if not any(char.isdigit() for char in new_password):
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Password must contain at least one number",
                }
            ),
            400,
        )

    if not any(char.isupper() for char in new_password):
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Password must contain at least one uppercase letter",
                }
            ),
            400,
        )

    if not any(char.islower() for char in new_password):
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Password must contain at least one lowercase letter",
                }
            ),
            400,
        )

    if not any(not char.isalnum() for char in new_password):
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Password must contain at least one special character",
                }
            ),
            400,
        )

    user = await Users.select().where(Users.id == user_id).first()
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    admin_email = UI_ADMIN_USER.lower()
    session_email = getattr(current_user, "username", "").lower()
    if user.get("email", "").lower() == admin_email and session_email != admin_email:
        return jsonify(
            {
                "success": False,
                "message": "Only the Admin can change the Admin password",
            }
        ), 403

    if session_email != admin_email and user.get("email", "").lower() != session_email:
        return jsonify(
            {"success": False, "message": "You can only change your own password"}
        ), 403

    if not check_password_hash(user["password"], old_password):
        return (
            jsonify({"success": False, "message": "Current password is incorrect"}),
            400,
        )

    await update_password(user["email"], new_password)

    return jsonify({"success": True, "message": "Password changed successfully"}), 200


@users_blueprint.route("/users/add", methods=["POST"])
@login_required
async def add_user():
    """
    Handles the endpoint for adding a new user. This method ensures that only
    an admin user can add new users via the UI, validates the provided data,
    prevents the creation of duplicate admin users, and inserts the user into
    the system with a generated complex password.

    This endpoint is restricted by the `login_required` decorator.

    :param methods: A list containing the HTTP methods allowed for this endpoint.
    :return: A JSON response indicating the result of the operation. The
        response includes success status, an optional message, and the password
        for the created user if the operation is successful.
    :rtype: flask.Response
    """

    if getattr(current_user, "username", "").lower() != UI_ADMIN_USER.lower():
        return jsonify({"success": False, "message": "Only Admin can add users"}), 403

    given_name = request.form.get("given_name", "").strip()
    email = request.form.get("email", "").strip().lower()

    if not given_name or not email:
        return jsonify(
            {"success": False, "message": "Name and Email are required"}
        ), 400

    if given_name.lower() == "admin" or email == UI_ADMIN_USER.lower():
        return jsonify(
            {"success": False, "message": "Admin user cannot be created from the UI"}
        ), 400

    password = generate_complex_password()
    error = await insert_user(given_name, email, password)
    if error:
        return jsonify({"success": False, "message": error}), 400

    return jsonify(
        {"success": True, "message": "User created successfully", "password": password}
    ), 200


@users_blueprint.route("/users/toggle_active", methods=["POST"])
@login_required
async def toggle_active():
    """
    Handles admin-only activation/deactivation of user accounts. The logged-in user
    must be an admin to modify other users' activation status. Additionally, certain
    restrictions are enforced, such as preventing modification of admin user accounts.
    The operation performs validity checks, retrieves user details from the database,
    updates the activation status if applicable, and returns a JSON response indicating
    the operation's success or failure.

    :param: None

    :raises 403: If the logged-in user does not have admin privileges.
    :raises 400: If the `user_id` is missing from the request or if the modification of
                 admin user accounts is attempted.
    :raises 404: If the specified user is not found in the database.

    :return: A JSON response indicating the success or failure of the operation.
    """

    if getattr(current_user, "username", "").lower() != UI_ADMIN_USER.lower():
        return jsonify(
            {"success": False, "message": "Only Admin can activate/deactivate users"}
        ), 403

    user_id = request.form.get("user_id")
    if not user_id:
        return jsonify({"success": False, "message": "user_id is required"}), 400

    user = await Users.select().where(Users.id == user_id).first()
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    if (
        user.get("email", "").lower() == UI_ADMIN_USER.lower()
        or str(user.get("given_name", "")).lower() == "admin"
    ):
        return jsonify(
            {
                "success": False,
                "message": "Admin user cannot be activated/deactivated from the UI",
            }
        ), 400

    new_status = not bool(user.get("is_active", True))
    await Users.update({Users.is_active: new_status}).where(Users.id == user_id)

    return jsonify(
        {"success": True, "message": "User status updated", "is_active": new_status}
    ), 200


@users_blueprint.route("/users/delete", methods=["POST"])
@login_required
async def delete_user():
    """
    Handles the deletion of a user.

    Only an administrator can perform this operation. This function checks
    the current user's privileges and ensures that the user being deleted is not an
    administrator (admin-level user or the default admin account). It validates input
    and performs necessary checks before deleting the user.

    :param user_id: The ID of the user to be deleted
    :type user_id: str
    :raises KeyError: If the provided `user_id` does not exist
    :raises PermissionError: If the current user does not have sufficient privileges
                             to perform the operation
    :raises ValueError: If the `user_id` is not provided or if an invalid user is
                        attempted to be deleted
    :return: A JSON response indicating the success or failure of the deletion request
    :rtype: flask.Response
    """

    if getattr(current_user, "username", "").lower() != UI_ADMIN_USER.lower():
        return jsonify(
            {"success": False, "message": "Only Admin can delete users"}
        ), 403

    user_id = request.form.get("user_id")
    if not user_id:
        return jsonify({"success": False, "message": "user_id is required"}), 400

    user = await Users.select().where(Users.id == user_id).first()
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    if (
        user.get("email", "").lower() == UI_ADMIN_USER.lower()
        or str(user.get("given_name", "")).lower() == "admin"
    ):
        return jsonify(
            {"success": False, "message": "Admin user cannot be deleted from the UI"}
        ), 400

    await Users.delete().where(Users.id == user_id)

    return jsonify({"success": True, "message": "User deleted"}), 200
