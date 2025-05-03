from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, url_for)
from flask_login import login_required
from werkzeug.security import check_password_hash

from py_phone_caller_utils.py_phone_caller_db.db_user import update_password
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import \
    Users

users_blueprint = Blueprint(
    "users_blueprint",
    __name__,
    template_folder="templates/users",
    static_folder="static",
    static_url_path="/users/static",
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

    if search_query:
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
        search_query=search_query,
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
        logout_url=url_for("home_blueprint.logout"),
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

    # ToDo: password length from configuration instead of hardcoded here
    if len(new_password) < 17:
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Password must be at least 17 characters long",
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

    if not check_password_hash(user["password"], old_password):
        return (
            jsonify({"success": False, "message": "Current password is incorrect"}),
            400,
        )

    await update_password(user["email"], new_password)

    return jsonify({"success": True, "message": "Password changed successfully"}), 200
