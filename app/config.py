# app/config.py
import os
import re
from dotenv import load_dotenv

# En local carga .env; en Railway las vars ya vienen del entorno
load_dotenv()


def _normalize_db_url(url: str | None) -> str | None:
    """
    Normaliza la URL de Postgres para SQLAlchemy + psycopg2:
      - postgres:// -> postgresql+psycopg2://
      - Añade sslmode=require SOLO si es endpoint público (proxy.rlwy.net)
      - NO añade sslmode si es endpoint interno (*.railway.internal)
    """
    if not url:
        return None

    # Asegurar esquema correcto para SQLAlchemy/psycopg2
    url = re.sub(r'^postgres://', 'postgresql+psycopg2://', url)
    url = re.sub(r'^postgresql://', 'postgresql+psycopg2://', url)

    # ¿Es interno de Railway?
    is_internal = ".railway.internal" in url
    has_ssl = "sslmode=" in url

    # Si NO es interno y no trae sslmode, lo agregamos
    if (not is_internal) and (not has_ssl):
        sep = '&' if '?' in url else '?'
        url = f"{url}{sep}sslmode=require"

    return url


class Config:
    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    JSON_SORT_KEYS = False

    # Base de datos
    # Railway expone normalmente DATABASE_URL (puedes dejar RAILWAY_DATABASE_URL como fallback)
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(
        os.getenv("DATABASE_URL") or os.getenv("RAILWAY_DATABASE_URL")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Almacenamiento de comprobantes
    STORAGE_PROVIDER = os.getenv("STORAGE_PROVIDER", "dropbox")  # 'dropbox' (actual)
    DROPBOX_TOKEN = os.getenv("DROPBOX_TOKEN")

    # Admin simple
    ADMIN_USER = os.getenv("ADMIN_USER", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")


def get_config():
    """Factory para cargar la config en create_app()."""
    return Config
