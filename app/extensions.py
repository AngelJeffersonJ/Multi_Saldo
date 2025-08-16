# app/extensions.py
from flask_sqlalchemy import SQLAlchemy

# Extensiones (una sola instancia, reutilizable en toda la app)
db = SQLAlchemy()
