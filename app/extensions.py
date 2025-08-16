# app/extensions.py
import os
import dropbox
from flask_sqlalchemy import SQLAlchemy

# Extensión de base de datos
db = SQLAlchemy()

# Cliente Dropbox (usa refresh token en vez de access token temporal)
def get_dropbox():
    """
    Retorna un cliente de Dropbox que se auto-refresca usando el refresh token.
    Debes haber definido en .env:
      DROPBOX_APP_KEY
      DROPBOX_APP_SECRET
      DROPBOX_REFRESH_TOKEN
    """
    return dropbox.Dropbox(
        app_key=os.environ["DROPBOX_APP_KEY"],
        app_secret=os.environ["DROPBOX_APP_SECRET"],
        oauth2_refresh_token=os.environ["DROPBOX_REFRESH_TOKEN"],
        timeout=60,
    )
