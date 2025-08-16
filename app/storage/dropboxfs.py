# app/storage/dropboxfs.py
import os
import uuid
from dropbox.exceptions import ApiError, AuthError, BadInputError
from dropbox import files
from app.extensions import get_dropbox

class Provider:
    def __init__(self, app=None):
        # Inicializa el cliente Dropbox usando refresh token
        self.dbx = get_dropbox()
        self.base_dir = "/comprobantes"

    def _norm_path(self, storage_path: str) -> str:
        if not storage_path:
            raise ValueError("storage_path vacío")
        return storage_path if storage_path.startswith("/") else f"{self.base_dir}/{storage_path}"

    def upload(self, filename: str, raw_bytes: bytes) -> str:
        ext = os.path.splitext(filename)[1] or ".bin"
        name = f"{uuid.uuid4()}{ext}"
        path = self._norm_path(name)
        try:
            self.dbx.files_upload(raw_bytes, path, mode=files.WriteMode.overwrite)
        except BadInputError as e:
            raise RuntimeError("Dropbox: falta scope 'files.content.write'.") from e
        except AuthError as e:
            raise RuntimeError("Dropbox: refresh token inválido o credenciales incorrectas.") from e
        except ApiError as e:
            raise RuntimeError(f"Dropbox upload error: {str(e)}") from e
        return name

    def get_shared_link(self, storage_path: str) -> str:
        path = self._norm_path(storage_path)
        try:
            links = self.dbx.sharing_list_shared_links(path=path, direct_only=True).links
            if links:
                return links[0].url
            link = self.dbx.sharing_create_shared_link_with_settings(path)
            return link.url
        except ApiError as e:
            if "not_found" in str(e).lower():
                raise FileNotFoundError("Archivo eliminado/no encontrado en Dropbox") from e
            raise RuntimeError(f"Dropbox API error al compartir: {str(e)}") from e

    def get_temporary_link(self, storage_path: str) -> str:
        path = self._norm_path(storage_path)
        try:
            return self.dbx.files_get_temporary_link(path).link
        except ApiError as e:
            if "not_found" in str(e).lower():
                raise FileNotFoundError("Archivo eliminado/no encontrado en Dropbox") from e
            raise RuntimeError(f"Dropbox API error al obtener link temporal: {str(e)}") from e

    def stat(self, storage_path: str):
        path = self._norm_path(storage_path)
        return self.dbx.files_get_metadata(path)
