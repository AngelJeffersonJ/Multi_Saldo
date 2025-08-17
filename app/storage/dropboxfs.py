# app/storage/dropboxfs.py
import os
import uuid
import mimetypes
from dropbox.exceptions import ApiError, AuthError, BadInputError
from dropbox import files
from app.extensions import get_dropbox

class Provider:
    def __init__(self, app=None):
        self.dbx = get_dropbox()           # usa tu cliente inicializado con token
        self.base_dir = "/comprobantes"    # carpeta base en Dropbox

    def _norm_path(self, storage_path: str) -> str:
        if not storage_path:
            raise ValueError("storage_path vacío")
        p = storage_path.strip()
        if p.startswith("/"):
            return p
        # guardamos solo el nombre en BD; aquí anteponemos la carpeta base
        return f"{self.base_dir}/{p}"

    def upload(self, filename: str, raw_bytes: bytes) -> str:
        ext = os.path.splitext(filename)[1] or ".bin"
        name = f"{uuid.uuid4()}{ext}"                # guardaremos este "name" en BD
        path = self._norm_path(name)
        try:
            self.dbx.files_upload(raw_bytes, path, mode=files.WriteMode.overwrite)
        except BadInputError as e:
            raise RuntimeError("Dropbox: falta scope 'files.content.write'.") from e
        except AuthError as e:
            raise RuntimeError("Dropbox: token inválido o sin permisos.") from e
        except ApiError as e:
            raise RuntimeError(f"Dropbox upload error: {str(e)}") from e
        return name                                    # <- solo el nombre (sin carpeta)

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

    # === NUEVO: descarga bytes para servir inline desde Flask ===
    def download(self, storage_path: str):
        """
        Devuelve (data:bytes, mime:str, name:str).
        Requiere scopes: files.content.read (+ metadata.read).
        """
        path = self._norm_path(storage_path)
        try:
            md, resp = self.dbx.files_download(path)
            data = resp.content
            name = getattr(md, "name", None) or os.path.basename(path) or "archivo"
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
            return data, mime, name
        except ApiError as e:
            if "not_found" in str(e).lower():
                raise FileNotFoundError("Archivo eliminado/no encontrado en Dropbox") from e
            raise RuntimeError(f"Dropbox API error al descargar: {e}") from e
        except AuthError as e:
            raise RuntimeError("Dropbox: token inválido o sin 'files.content.read'.") from e
