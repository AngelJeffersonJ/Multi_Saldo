import os
from dotenv import load_dotenv

# Cargar variables desde .env
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))

class Config:

    ADMIN_USER = os.getenv("ADMIN_USER", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

    # Clave secreta para sesiones / CSRF
    SECRET_KEY = os.getenv("SECRET_KEY", "dev_secret_key")

    # Base de datos Railway (Postgres)
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Almacenamiento de comprobantes
    STORAGE_PROVIDER = os.getenv("STORAGE_PROVIDER", "local")
    DROPBOX_TOKEN = os.getenv("DROPBOX_TOKEN")

    # Entorno Flask
    FLASK_ENV = os.getenv("FLASK_ENV", "production")
