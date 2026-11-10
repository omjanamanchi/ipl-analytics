"""IPL Analytics - Flask application factory."""
from flask import Flask
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
    # Phase 3: from .report import bp as report_bp; app.register_blueprint(report_bp)

    @app.context_processor
    def nav_helpers():
        return {"has_endpoint": lambda name: name in app.view_functions}

    return app
