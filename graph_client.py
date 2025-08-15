import os
import io
import time
import json
import urllib.parse
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
import msal
from dotenv import load_dotenv

load_dotenv()

TENANT_ID = os.getenv("TENANT_ID", "common")
CLIENT_ID = os.getenv("CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
GRAPH_MODE = os.getenv("GRAPH_MODE", "daemon").lower()  # "daemon" o "device"
GRAPH_DRIVE_USER = os.getenv("GRAPH_DRIVE_USER", "").strip()

EXCEL_RELATIVE = os.getenv("EXCEL_RELATIVE", "Documentos/resultados/central_solicitudes.xlsx")
COMPROBANTES_RELATIVE = os.getenv("COMPROBANTES_RELATIVE", "Comprobantes")

TOKEN_CACHE_FILE = os.getenv("TOKEN_CACHE_FILE", "msal_token_cache.json")

WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Hoja1")
TABLE_NAME = os.getenv("TABLE_NAME", "Solicitudes")
CLIENTS_WORKSHEET = os.getenv("CLIENTS_WORKSHEET", "Clientes")
CLIENTS_TABLE = os.getenv("CLIENTS_TABLE", "Clientes")
DEPS_WORKSHEET = os.getenv("DEPS_WORKSHEET", "Depositos")
DEPS_TABLE = os.getenv("DEPS_TABLE", "Deps")

GRAPH_API = "https://graph.microsoft.com/v1.0"

# ---------- AUTH ----------
def _authority() -> str:
    return f"https://login.microsoftonline.com/{TENANT_ID}"

def _load_cache() -> msal.SerializableTokenCache:
    os.makedirs(os.path.dirname(TOKEN_CACHE_FILE) or ".", exist_ok=True)
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_FILE) and os.path.getsize(TOKEN_CACHE_FILE) > 5:
        try:
            with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                cache.deserialize(f.read())
        except Exception:
            pass
    return cache

def _save_cache(cache: msal.SerializableTokenCache):
    if cache.has_state_changed:
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            f.write(cache.serialize())

def _drive_prefix() -> str:
    # En modo daemon NO existe /me; hay que apuntar al usuario destino
    if GRAPH_MODE == "daemon":
        if not GRAPH_DRIVE_USER:
            raise RuntimeError("Falta GRAPH_DRIVE_USER (usuario destino del OneDrive) en modo daemon.")
        return f"/users/{urllib.parse.quote(GRAPH_DRIVE_USER)}/drive"
    else:
        return "/me/drive"

def _path_drive_root(relative: str) -> str:
    # Ej: relative = "Documentos/..." ->   /users/{upn}/drive/root:/Documentos/...
    rel = relative.lstrip("/").rstrip("/")
    return f"{_drive_prefix()}/root:/{rel}"

def get_token() -> str:
    if GRAPH_MODE == "daemon":
        if not (CLIENT_ID and CLIENT_SECRET and TENANT_ID):
            raise RuntimeError("Faltan CLIENT_ID/CLIENT_SECRET/TENANT_ID para modo daemon.")
        app = msal.ConfidentialClientApplication(
            client_id=CLIENT_ID,
            client_credential=CLIENT_SECRET,
            authority=_authority(),
        )
        # En client credentials NO se usan scopes tipo 'User.Read'; se usa el recurso '.default'
        result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" not in result:
            raise RuntimeError(f"Error token app: {result.get('error')} {result.get('error_description')}")
        return result["access_token"]
    else:
        # (fallback) device flow para pruebas locales
        cache = _load_cache()
        app = msal.PublicClientApplication(client_id=CLIENT_ID, authority=_authority(), token_cache=cache)
        accounts = app.get_accounts()
        if accounts:
            res = app.acquire_token_silent(["User.Read"], account=accounts[0])
            if res and "access_token" in res:
                _save_cache(cache)
                return res["access_token"]
        flow = app.initiate_device_flow(scopes=["User.Read"])
        if "user_code" not in flow:
            raise RuntimeError("No se pudo iniciar device flow.")
        res = app.acquire_token_by_device_flow(flow)
        if "access_token" not in res:
            raise RuntimeError(f"Fallo autenticación: {res.get('error')} - {res.get('error_description')}")
        _save_cache(cache)
        return res["access_token"]

def ensure_ready():
    try:
        token = get_token()
        r = requests.get(f"{GRAPH_API}{_drive_prefix()}/root", headers={"Authorization": f"Bearer {token}"}, timeout=20)
        if r.status_code == 200:
            return True, "ok"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)

def _h(token: str, json_ct=True) -> Dict[str, str]:
    h = {"Authorization": f"Bearer {token}"}
    if json_ct:
        h["Content-Type"] = "application/json"
    return h

# ---------- OneDrive helpers ----------
def _get_driveitem_by_path(token: str, relative_path: str) -> Dict[str, Any]:
    url = f"{GRAPH_API}{_path_drive_root(relative_path)}"
    r = requests.get(url, headers=_h(token), timeout=60)
    if r.status_code != 200:
        raise FileNotFoundError(f"No encontrado {relative_path}: {r.status_code} {r.text[:200]}")
    return r.json()

def _get_item_json(token: str, item_id: str) -> Dict[str, Any]:
    r = requests.get(f"{GRAPH_API}/me/drive/items/{item_id}", headers=_h(token), timeout=60)
    if r.status_code == 200:
        return r.json()
    # Cuando usamos /users/{upn}, el item sigue siendo del mismo drive; /me puede fallar en app perms.
    # Usamos el drive del usuario destino:
    r2 = requests.get(f"{GRAPH_API}{_drive_prefix()}/items/{item_id}", headers=_h(token), timeout=60)
    r2.raise_for_status()
    return r2.json()

def _ensure_folder(token: str, parent_item_id: str, name: str) -> str:
    url = f"{GRAPH_API}{_drive_prefix()}/items/{parent_item_id}/children?$select=id,name,folder"
    r = requests.get(url, headers=_h(token), timeout=60)
    r.raise_for_status()
    for it in r.json().get("value", []):
        if it.get("folder") and it["name"] == name:
            return it["id"]
    body = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "rename"}
    rc = requests.post(f"{GRAPH_API}{_drive_prefix()}/items/{parent_item_id}/children", headers=_h(token), json=body, timeout=60)
    rc.raise_for_status()
    return rc.json()["id"]

def _ensure_path_chain(token: str, relative_root: str, chain: List[str]) -> Dict[str, Any]:
    root_item = _get_driveitem_by_path(token, relative_root)
    current_id = root_item["id"]
    for part in chain:
        current_id = _ensure_folder(token, current_id, part)
    return _get_item_json(token, current_id)

# ---------- Upload ----------
def upload_large_with_session(token: str, folder_item_id: str, final_name: str, fileobj, chunk_size=8*1024*1024):
    create_url = f"{GRAPH_API}{_drive_prefix()}/items/{folder_item_id}:/{urllib.parse.quote(final_name)}:/createUploadSession"
    r = requests.post(create_url, headers=_h(token), json={}, timeout=60)
    r.raise_for_status()
    upload_url = r.json()["uploadUrl"]

    fileobj.seek(0, io.SEEK_END)
    total = fileobj.tell()
    fileobj.seek(0)
    start = 0

    while start < total:
        end = min(start + chunk_size, total) - 1
        fileobj.seek(start)
        chunk = fileobj.read(end - start + 1)
        headers = {"Content-Length": str(len(chunk)), "Content-Range": f"bytes {start}-{end}/{total}"}
        resp = requests.put(upload_url, headers=headers, data=chunk, timeout=300)
        if resp.status_code in (200, 201):
            return resp.json()
        if resp.status_code == 202:
            start = end + 1
            continue
        if resp.status_code in (429, 503):
            time.sleep(float(resp.headers.get("Retry-After", "2")))
            continue
        resp.raise_for_status()

def upload_file_stream(token: str, file_stream, original_filename: str, cliente_nombre: str,
                       fecha: Optional[datetime] = None, rename_safe: bool = True) -> Dict[str, Any]:
    fecha = fecha or datetime.now()
    chain = [
        (cliente_nombre or "SIN_CLIENTE").strip() or "SIN_CLIENTE",
        f"{fecha:%Y}", f"{fecha:%m}", f"{fecha:%d}",
    ]
    dest_folder = _ensure_path_chain(token, COMPROBANTES_RELATIVE, chain)
    folder_id = dest_folder["id"]

    name, ext = os.path.splitext(original_filename)
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name).strip("_") or "comprobante"
    final_name = f"{safe}_{fecha:%Y%m%d_%H%M%S}_{hashlib.md5((original_filename+str(time.time())).encode()).hexdigest()[:8]}{ext.lower()}" if rename_safe else original_filename

    file_stream.seek(0, io.SEEK_END)
    size = file_stream.tell()
    file_stream.seek(0)

    if size < 4 * 1024 * 1024:
        put_url = f"{GRAPH_API}{_drive_prefix()}/items/{folder_id}:/{urllib.parse.quote(final_name)}:/content"
        r = requests.put(put_url, headers={"Authorization": f"Bearer {token}"}, data=file_stream, timeout=300)
        r.raise_for_status()
        return r.json()
    else:
        return upload_large_with_session(token, folder_id, final_name, file_stream)

# ---------- Excel base local ----------
def _generate_local_base_excel(path: str):
    from openpyxl import Workbook
    wb = Workbook()

    ws = wb.active
    ws.title = WORKSHEET_NAME
    ws.append([
        "fecha_iso","banco","forma_pago","producto","importe","tipo_bbva",
        "folio","autorizacion","folio_movimiento","numero_usuario","requiere_factura",
        "observaciones","cliente_id","cliente_nombre","comprobante_url","origen","realizo"
    ])

    ws2 = wb.create_sheet(DEPS_WORKSHEET)
    ws2.append(["Fecha banco","Cliente","Monto","Movimiento","Ficha","Realizó","Observaciones","Factura"])

    ws3 = wb.create_sheet(CLIENTS_WORKSHEET)
    ws3.append(["cliente_id","cliente_nombre","rfc","razon_social","cfdi","uso_cfdi","direccion","contacto","email","numero_usuario"])

    wb.save(path)

# ---------- Excel utils ----------
def _ensure_excel_exists(token: str, template_local: Optional[str] = None) -> Dict[str, Any]:
    try:
        return _get_driveitem_by_path(token, EXCEL_RELATIVE)
    except FileNotFoundError:
        pass

    if template_local:
        if not os.path.exists(template_local):
            os.makedirs(os.path.dirname(template_local) or ".", exist_ok=True)
            _generate_local_base_excel(template_local)
        with open(template_local, "rb") as f:
            data = f.read()
        put_url = f"{GRAPH_API}{_path_drive_root(EXCEL_RELATIVE) }:/content"
        r = requests.put(put_url, headers={"Authorization": f"Bearer {token}"}, data=data, timeout=300)
        r.raise_for_status()
        return r.json()
    raise FileNotFoundError("No existe el Excel central en OneDrive y no se proporcionó template_local.")

def _ensure_table_exists(token: str, file_id: str, worksheet_name: str, table_name: str) -> str:
    base = f"{GRAPH_API}{_drive_prefix()}/items/{file_id}/workbook/worksheets('{urllib.parse.quote(worksheet_name)}')"
    r = requests.get(f"{base}/tables", headers=_h(token), timeout=60)
    r.raise_for_status()
    for t in r.json().get("value", []):
        if t.get("name") == table_name:
            return t["id"]

    ru = requests.get(f"{base}/usedRange(valuesOnly=true)", headers=_h(token), timeout=60)
    ru.raise_for_status()
    address = ru.json().get("address")
    body = {"address": address, "hasHeaders": True}
    rc = requests.post(f"{base}/tables", headers=_h(token), json=body, timeout=60)
    rc.raise_for_status()
    tid = rc.json()["id"]
    rn = requests.patch(f"{GRAPH_API}{_drive_prefix()}/items/{file_id}/workbook/tables/{tid}",
                        headers=_h(token), json={"name": table_name}, timeout=60)
    if rn.status_code not in (200, 204):
        raise RuntimeError(f"Tabla creada pero sin poder renombrar: {rn.status_code} {rn.text[:200]}")
    return tid

def append_rows(token: str, file_id: str, table_id: str, rows: List[List[Any]]):
    url = f"{GRAPH_API}{_drive_prefix()}/items/{file_id}/workbook/tables/{table_id}/rows/add"
    for _ in range(3):
        r = requests.post(url, headers=_h(token), json={"values": rows}, timeout=60)
        if r.status_code in (200, 201):
            return
        if r.status_code in (423, 429, 503):
            time.sleep(float(r.headers.get("Retry-After", "2")))
            continue
        raise RuntimeError(f"No se pudieron agregar filas: {r.status_code} {r.text[:200]}")
    raise RuntimeError("Reintentos agotados al agregar filas")

def map_payload_to_row(p: Dict[str, Any]) -> List[Any]:
    return [
        p.get("fecha_iso") or "", p.get("banco") or "", p.get("forma_pago") or "",
        p.get("producto") or "", p.get("importe") or "", p.get("tipo_bbva") or "",
        p.get("folio") or "", p.get("autorizacion") or "", p.get("folio_movimiento") or "",
        p.get("numero_usuario") or "", "Sí" if p.get("requiere_factura") else "No",
        p.get("observaciones") or "", p.get("cliente_id") or "", p.get("cliente_nombre") or "",
        p.get("comprobante_url") or "", p.get("origen") or "formulario",
        p.get("realizo") or "",
    ]

def ensure_excel_and_table(token: str, template_local: Optional[str] = None):
    wb_item = _ensure_excel_exists(token, template_local=template_local)
    table_id = _ensure_table_exists(token, wb_item["id"], WORKSHEET_NAME, TABLE_NAME)
    return wb_item, table_id

# ---------- Resumen Deps ----------
import locale
try:
    locale.setlocale(locale.LC_TIME, "es_MX.UTF-8")
except Exception:
    try:
        locale.setlocale(locale.LC_TIME, "es_ES.UTF-8")
    except Exception:
        pass

def _fmt_fecha_dd_mmm(fecha_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(fecha_iso)
        return dt.strftime("%d-%b").lower().replace(".", "")
    except Exception:
        return fecha_iso or ""

def map_payload_to_deps_row(p: Dict[str, Any]) -> List[Any]:
    fecha_banco = _fmt_fecha_dd_mmm(p.get("fecha_iso") or "")
    cliente = p.get("cliente_id") or p.get("cliente_nombre") or ""
    importe = str(p.get("importe") or "").strip()

    banco = (p.get("banco") or "").upper()
    tipo_bbva = (p.get("tipo_bbva") or "").lower()
    folio = (p.get("folio") or "").strip()
    aut = (p.get("autorizacion") or "").strip()
    folmov = (p.get("folio_movimiento") or "").strip()
    producto = (p.get("producto") or "").lower()

    if "tae" in producto:
        movimiento = ""
    elif banco == "BBVA" and tipo_bbva == "practicaja" and (folio or aut):
        movimiento = f"Folio {folio}" + (f"/ Aut {aut}" if aut else "")
    elif banco == "BBVA" and tipo_bbva == "ventanilla" and folmov:
        movimiento = f"Folio/Mov {folmov}"
    elif folio:
        movimiento = f"Ref {folio}"
    else:
        movimiento = "-"

    forma_pago = (p.get("forma_pago") or "").lower()
    ficha = "s c" if forma_pago in ("depósito", "deposito") else ("transfer" if forma_pago == "transferencia" else "")

    realizo = p.get("realizo") or ""

    extra = (p.get("observaciones") or "").strip()
    observaciones = extra if "tae" in producto else (".p/pago DEP PS" + (f"  {extra}" if extra else ""))

    factura = "Sí" if p.get("requiere_factura") else "No"

    return [fecha_banco, cliente, importe, movimiento, ficha, realizo, observaciones, factura]

def ensure_excel_and_deps_table(token: str):
    wb_item = _ensure_excel_exists(token)
    table_id = _ensure_table_exists(token, wb_item["id"], DEPS_WORKSHEET, DEPS_TABLE)
    return wb_item, table_id

def add_deps_row(token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    wb_item, table_id = ensure_excel_and_deps_table(token)
    row = map_payload_to_deps_row(payload)
    append_rows(token, wb_item["id"], table_id, [row])
    return {"ok": True, "excel": wb_item.get("name"), "tabla": DEPS_TABLE}

def add_solicitud_row(token: str, payload: Dict[str, Any], template_local: Optional[str] = None):
    wb_item, table_id = ensure_excel_and_table(token, template_local=template_local)
    row = map_payload_to_row(payload)
    append_rows(token, wb_item["id"], table_id, [row])
    return {"ok": True, "excel": wb_item.get("name"), "tabla": TABLE_NAME}

# ---------- Clientes ----------
def get_clientes_por_usuario(token: str, numero_usuario: str) -> List[Dict[str, Any]]:
    wb = _get_driveitem_by_path(token, EXCEL_RELATIVE)
    tabs = requests.get(
        f"{GRAPH_API}{_drive_prefix()}/items/{wb['id']}/workbook/worksheets('{urllib.parse.quote(CLIENTS_WORKSHEET)}')/tables",
        headers=_h(token), timeout=60)
    if tabs.status_code != 200:
        return []
    table_id = None
    for t in tabs.json().get("value", []):
        if t.get("name") == CLIENTS_TABLE:
            table_id = t["id"]
            break
    if not table_id:
        return []

    rng = requests.get(f"{GRAPH_API}{_drive_prefix()}/items/{wb['id']}/workbook/tables/{table_id}/range",
                       headers=_h(token), timeout=60)
    if rng.status_code != 200:
        return []
    values = rng.json().get("values", [])
    if not values:
        return []
    headers = [str(h or "").strip() for h in values[0]]
    rows = values[1:]

    def col(name): return headers.index(name) if name in headers else None
    idx_num = col("numero_usuario"); idx_id = col("cliente_id"); idx_nombre = col("cliente_nombre"); idx_rfc = col("rfc")

    found = []
    for r in rows:
        r = list(r) + [""] * (len(headers) - len(r))
        target = str(numero_usuario).strip()
        hit = (
            (idx_num is not None and str(r[idx_num]).strip() == target) or
            (idx_id is not None and str(r[idx_id]).strip() == target) or
            any(str(c).strip() == target for c in r)
        )
        if hit:
            found.append({
                "cliente_id": r[idx_id] if idx_id is not None else "",
                "cliente_nombre": r[idx_nombre] if idx_nombre is not None else "",
                "rfc": r[idx_rfc] if idx_rfc is not None else "",
                "raw": dict(zip(headers, r))
            })
    return found
