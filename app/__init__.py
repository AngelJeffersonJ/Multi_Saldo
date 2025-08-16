from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from .config import Config

# Inicializar extensiones
db = SQLAlchemy()
migrate = Migrate()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    CORS(app)

    # Public
    from .routes import public
    app.register_blueprint(public.bp)

    # Admin  <<<<<< agrega estas dos líneas
    from .routes import admin
    app.register_blueprint(admin.bp)

    @app.cli.command("initdb")
    def initdb_command():
        db.drop_all()
        db.create_all()
        print("Base de datos inicializada correctamente.")

    return app
