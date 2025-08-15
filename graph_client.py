import os
import io
import time
import json
import urllib.parse
import hashlib
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
import msal
from dotenv import load_dotenv

load_dotenv()

TENANT_ID = os.getenv("TENANT_ID", "common")
CLIENT_ID = os.getenv("CLIENT_ID", "")

RAW_SCOPES = os.getenv("GRAPH_SCOPES", "Files.ReadWrite.All,User.Read")

def _parse_scopes(raw: str):
    raw = raw.replace(" ", ",")
    toks = []
    for part in raw.split(","):
        t = part.strip().strip("[](){}\"'")
        if t and "=" not in t:
            toks.append(t)
    blocked = {"openid", "profile", "offline_access"}
    cleaned = [t for t in toks if t.lower() not in blocked]
    if not cleaned:
        cleaned = ["Files.ReadWrite.All", "User.Read"]
    out = []
    for t in cleaned:
        if t not in out:
            out.append(t)
    return out

SCOPES = _parse_scopes(RAW_SCOPES)

EXCEL_PATH = os.getenv("EXCEL_PATH", "/me/drive/root:/Documentos/resultados/central_solicitudes.xlsx")
COMPROBANTES_ROOT = os.getenv("COMPROBANTES_ROOT", "/me/drive/root:/Comprobantes")

TOKEN_CACHE_FILE = os.getenv("TOKEN_CACHE_FILE", "msal_token_cache.json")

WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Hoja1")
TABLE_NAME = os.getenv("TABLE_NAME", "Solicitudes")

CLIENTS_WORKSHEET = os.getenv("CLIENTS_WORKSHEET", "Clientes")
CLIENTS_TABLE = os.getenv("CLIENTS_TABLE", "Clientes")

DEPS_WORKSHEET = os.getenv("DEPS_WORKSHEET", "Depositos")
DEPS_TABLE = os.getenv("DEPS_TABLE", "Deps")

GRAPH_API = "https://graph.microsoft.com/v1.0"

# Archivos auxiliares para el flow
FLOW_INFO_FILE = "/data/device_flow_info.json"
FLOW_RESULT_FILE = "/data/device_flow_result.json"

# -------------------- AUTH --------------------
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
        os.makedirs(os.path.dirname(TOKEN_CACHE_FILE) or ".", exist_ok=True)
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            f.write(cache.serialize())

def _build_app(cache: Optional[msal.SerializableTokenCache] = None):
    cache = cache or _load_cache()
    return msal.PublicClientApplication(
        client_id=CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        token_cache=cache,
    ), cache

def get_token(interactive: bool = True) -> str:
    if not CLIENT_ID:
        raise RuntimeError("Falta CLIENT_ID")
    app, cache = _build_app()
    accounts = app.get_accounts()
    if accounts:
        res = app.acquire_token_silent(SCOPES, account=accounts[0])
        if res and "access_token" in res:
            _save_cache(cache)
            return res["access_token"]
    if interactive:
        # Como ya tenemos /auth/start no bloqueante, rara vez pasaremos por aquí.
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError("No se pudo iniciar device code flow.")
        res = app.acquire_token_by_device_flow(flow)
        if "access_token" not in res:
            raise RuntimeError(f"Fallo autenticación: {res.get('error')} - {res.get('error_description')}")
        _save_cache(cache)
        return res["access_token"]
    raise RuntimeError("No hay token en cache")

def start_device_flow() -> Dict[str, Any]:
    """
    Inicia el device code flow en un hilo (no bloquea).
    Devuelve verification_uri, user_code y message para mostrar al usuario.
    """
    app, cache = _build_app()
    # ¿ya hay token?
    accounts = app.get_accounts()
    if accounts:
        res = app.acquire_token_silent(SCOPES, account=accounts[0])
        if res and "access_token" in res:
            _save_cache(cache)
            return {"ok": True, "already": True}

    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError("No se pudo iniciar device code flow.")
    info = {
        "verification_uri": flow.get("verification_uri"),
        "user_code": flow.get("user_code"),
        "message": flow.get("message", ""),
        "expires_in": flow.get("expires_in"),
        "interval": flow.get("interval"),
    }
    os.makedirs(os.path.dirname(FLOW_INFO_FILE) or ".", exist_ok=True)
    with open(FLOW_INFO_FILE, "w", encoding="utf-8") as f:
        json.dump(info, f)

    def worker():
        res = app.acquire_token_by_device_flow(flow)
        _save_cache(cache)
        with open(FLOW_RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump(res, f)

    threading.Thread(target=worker, daemon=True).start()
    return info

def cache_info():
    path = TOKEN_CACHE_FILE
    return {
        "path": path,
        "exists": os.path.exists(path),
        "size": os.path.getsize(path) if os.path.exists(path) else 0,
        "scopes": SCOPES,
    }

def auth_status() -> Dict[str, Any]:
    """
    - ok=True si ya se puede llamar a Graph.
    - ok=False con detalle del estado si aún no.
    """
    info = cache_info()
    try:
        token = get_token(interactive=False)
        r = requests.get(f"{GRAPH_API}/me/drive/root", headers={"Authorization": f"Bearer {token}"}, timeout=20)
        return {"ok": r.status_code == 200, "detail": r.status_code, "cache": info}
    except Exception as e:
        flow = {}
        if os.path.exists(FLOW_INFO_FILE):
            try:
                with open(FLOW_INFO_FILE, "r", encoding="utf-8") as f:
                    flow = json.load(f)
            except Exception:
                pass
        res = {}
        if os.path.exists(FLOW_RESULT_FILE):
            try:
                with open(FLOW_RESULT_FILE, "r", encoding="utf-8") as f:
                    res = json.load(f)
            except Exception:
                pass
        return {"ok": False, "detail": str(e), "cache": info, "flow": flow, "result": res}

def _h(token: str, content_json: bool = True) -> Dict[str, str]:
    h = {"Authorization": f"Bearer {token}"}
    if content_json:
        h["Content-Type"] = "application/json"
    return h
