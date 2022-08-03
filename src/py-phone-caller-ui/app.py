from calls import calls_blueprint
from flask import Flask, render_template, url_for
from flask_login import LoginManager
from home import home_blueprint
from login import login_blueprint
from schedule_call import schedule_call_blueprint
from ws_events import ws_events_blueprint

from caller_utils.db.db_user import load_user_by_id
from caller_utils.login.user import User

login_manager = LoginManager()
login_manager.session_protection = "strong" # TODO: Constant from config module needed here...

app = Flask(__name__)

app.config[
    "SECRET_KEY"
] = "00061a95-ee47-46df-9dce-a9bbf62c7ca5"  # TODO: configure it on the right module

login_manager.init_app(app)


@login_manager.unauthorized_handler
def unauthorized():
    # https://flask-login.readthedocs.io/en/latest/#customizing-the-login-process
    return render_template(
        "unauthorized.html", login_url=url_for("login_blueprint.login")
    )


@login_manager.user_loader
def load_user(user_id):
    """Executes a sync query against the database in order to get the user ID"""
    loaded_user = load_user_by_id(user_id)
    return User(username=loaded_user.get("email"))


app.register_blueprint(login_blueprint)
app.register_blueprint(home_blueprint)
app.register_blueprint(calls_blueprint)
app.register_blueprint(schedule_call_blueprint)
app.register_blueprint(ws_events_blueprint)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000) # TODO: This can be done through the configuration module
