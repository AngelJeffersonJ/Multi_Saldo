import os
from flask import current_app

def get_storage():
    provider = current_app.config.get("STORAGE_PROVIDER", "dropbox")
    if provider == "dropbox":
        from . import dropboxfs as mod
        return mod.Provider(current_app)
    elif provider == "local":
        # Si luego agregas un localfs.py, cámbialo aquí.
        from . import dropboxfs as mod
        return mod.Provider(current_app)
    else:
        raise RuntimeError(f"Proveedor no soportado: {provider}")
