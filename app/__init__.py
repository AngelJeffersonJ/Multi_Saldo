# app/__init__.py
from flask import Flask
from .config import get_config
from .models import db


def create_app():
    app = Flask(__name__)
    app.config.from_object(get_config())

    # CORS opcional: si el paquete no está, no bloquea el arranque
    try:
        from flask_cors import CORS  # type: ignore
        CORS(app, resources={r"/*": {"origins": "*"}})
    except Exception:
        pass

    # DB
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        # Mensaje útil en logs si faltara la URL (evita un traceback poco claro)
        app.logger.error(
            "Falta SQLALCHEMY_DATABASE_URI: asegúrate de definir DATABASE_URL en Railway."
        )
    db.init_app(app)

    # Blueprints
    from .routes import public, admin
    app.register_blueprint(public.bp)
    app.register_blueprint(admin.bp)

    # CLI helper: crea las tablas (¡cuidado que hace drop_all()!)
    @app.cli.command("initdb")
    def initdb():
        from click import echo
        with app.app_context():
            db.drop_all()
            db.create_all()
            echo("OK: Base de datos inicializada (drop_all + create_all).")

    return app
