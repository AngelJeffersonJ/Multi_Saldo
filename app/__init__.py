# app/__init__.py
from flask import Flask
from .config import get_config
from .extensions import db


def create_app():
    app = Flask(__name__)
    app.config.from_object(get_config())

    # CORS opcional (si no está instalado, no falla)
    try:
        from flask_cors import CORS  # type: ignore
        CORS(app, resources={r"/*": {"origins": "*"}})
    except Exception:
        pass

    # DB
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        app.logger.error("Falta SQLALCHEMY_DATABASE_URI: define DATABASE_URL en Railway.")
    db.init_app(app)

    # Importa modelos para que SQLAlchemy los registre (evita circulares)
    with app.app_context():
        from . import models  # noqa: F401

    # Healthcheck MUY ligero (no toca DB ni Dropbox)
    @app.get("/healthz")
    def healthz():
        return "ok", 200

    # Blueprints (solo se registran; nada de trabajo en import)
    from .routes import public, admin
    app.register_blueprint(public.bp)
    app.register_blueprint(admin.bp)

    # CLI: initdb (¡hace drop_all + create_all!)
    @app.cli.command("initdb")
    def initdb():
        from click import echo
        with app.app_context():
            db.drop_all()
            db.create_all()
            echo("OK: Base de datos inicializada.")

    return app
