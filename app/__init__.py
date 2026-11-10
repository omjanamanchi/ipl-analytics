"""IPL Auction War Room - Flask application factory."""
from flask import Flask

from . import db
from .config import database_conninfo, flask_secret_key


def create_app(conninfo: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = flask_secret_key()
    db.init_pool(conninfo or database_conninfo())

    from .routes import bp as core_bp
    app.register_blueprint(core_bp)
    # Feature blueprints are added while building (see plan.md, Phase 2 and 3):
    #   from .draft import bp as draft_bp;   app.register_blueprint(draft_bp)
    #   from .report import bp as report_bp; app.register_blueprint(report_bp)

    @app.context_processor
    def nav_helpers():
        return {"has_endpoint": lambda name: name in app.view_functions}

    return app
