"""IPL Analytics - Flask application factory."""
from flask import Flask, session
from flask_wtf.csrf import CSRFProtect

from . import db
from .config import database_conninfo, flask_secret_key

csrf = CSRFProtect()


def create_app(conninfo: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = flask_secret_key()
    db.init_pool(conninfo or database_conninfo())
    csrf.init_app(app)

    from .routes import bp as core_bp
    app.register_blueprint(core_bp)

    from .draft import bp as draft_bp
    app.register_blueprint(draft_bp)

    from .report import bp as report_bp
    app.register_blueprint(report_bp)

    from .auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from .players import bp as players_bp
    app.register_blueprint(players_bp)

    @app.context_processor
    def nav_helpers():
        return {"has_endpoint": lambda name: name in app.view_functions}

    @app.context_processor
    def inject_current_user():
        """Expose current_user dict to all templates."""
        user_id = session.get("user_id")
        if user_id:
            from .db import query_one
            row = query_one(
                "SELECT user_id, display_name FROM app_user WHERE user_id = %s",
                (user_id,),
            )
            if row:
                return {"current_user": dict(row), "is_guest": False}
        if session.get("is_guest"):
            return {"current_user": None, "is_guest": True}
        return {"current_user": None, "is_guest": False}

    return app
