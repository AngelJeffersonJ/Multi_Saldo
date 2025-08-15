# scripts/archive_month_onedrive_to_local.py
import os
import argparse
import pathlib
import time
import zipfile
from typing import Dict, Any, List

import requests
from dotenv import load_dotenv

from graph_client import get_token, COMPROBANTES_ROOT

GRAPH_API = "https://graph.microsoft.com/v1.0"
load_dotenv()

def _h(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}

def _get_by_path(token: str, path: str) -> Dict[str, Any]:
    url = f"{GRAPH_API}{path}"
    r = requests.get(url, headers=_h(token), timeout=60)
    r.raise_for_status()
    return r.json()

def _list_children(token: str, item_id: str) -> List[Dict[str, Any]]:
    url = f"{GRAPH_API}/me/drive/items/{item_id}/children?$select=id,name,folder,file,size,@microsoft.graph.downloadUrl"
    out = []
    while url:
        r = requests.get(url, headers=_h(token), timeout=120)
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return out

def _download_file(token: str, item: Dict[str, Any], dest_path: pathlib.Path):
    # Preferimos downloadUrl si viene en listado (más rápido)
    dl = item.get("@microsoft.graph.downloadUrl")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dl:
        with requests.get(dl, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024*256):
                    if chunk:
                        f.write(chunk)
        return
    # Fallback a /content
    url = f"{GRAPH_API}/me/drive/items/{item['id']}/content"
    with requests.get(url, headers=_h(token), stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024*256):
                if chunk:
                    f.write(chunk)

def archive_month(year: int, month: int, out_dir: str, zip_after: bool=False, sleep_between: float=0.0):
    token = get_token()
    # Raíz: /Comprobantes
    root = _get_by_path(token, COMPROBANTES_ROOT)
    root_id = root["id"]
    clients = _list_children(token, root_id)
    print(f"[INFO] Clientes detectados: {len(clients)}")

    saved_files = 0
    for c in clients:
        if "folder" not in c:
            continue
        client_id = c["id"]
        client_name = c["name"]
        # Año
        years = _list_children(token, client_id)
        yitem = next((y for y in years if y.get("folder") and y["name"] == f"{year:04d}"), None)
        if not yitem:
            continue
        # Mes
        months = _list_children(token, yitem["id"])
        mitem = next((m for m in months if m.get("folder") and m["name"] == f"{month:02d}"), None)
        if not mitem:
            continue
        # Días
        days = _list_children(token, mitem["id"])
        for d in days:
            if "folder" not in d:
                continue
            files = _list_children(token, d["id"])
            for f in files:
                if "file" not in f:
                    continue
                rel_path = pathlib.Path(client_name) / f"{year:04d}" / f"{month:02d}" / d["name"] / f["name"]
                dest = pathlib.Path(out_dir) / rel_path
                if dest.exists():
                    continue
                try:
                    _download_file(token, f, dest)
                    saved_files += 1
                    print(f"[OK] {rel_path}")
                except Exception as e:
                    print(f"[WARN] No se pudo descargar {rel_path}: {e}")
                if sleep_between > 0:
                    time.sleep(sleep_between)

    if zip_after and saved_files > 0:
        zip_name = pathlib.Path(out_dir) / f"Comprobantes_{year:04d}_{month:02d}.zip"
        print(f"[ZIP] Empaquetando en {zip_name} ...")
        with zipfile.ZipFile(zip_name, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p in pathlib.Path(out_dir).rglob("*"):
                if p.is_file() and p.name.endswith(".zip") is False:
                    z.write(p, arcname=p.relative_to(out_dir))

    print(f"[DONE] Archivos guardados: {saved_files}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Descarga todos los comprobantes de un mes desde OneDrive a local.")
    parser.add_argument("--year", type=int, required=True, help="Año, e.g. 2025")
    parser.add_argument("--month", type=int, required=True, help="Mes 1-12")
    parser.add_argument("--out", type=str, required=True, help="Directorio local de salida")
    parser.add_argument("--zip", action="store_true", help="Comprimir en zip al terminar")
    parser.add_argument("--sleep", type=float, default=0.0, help="Sleep entre descargas (seg) para evitar throttle")
    args = parser.parse_args()

    archive_month(args.year, args.month, args.out, zip_after=args.zip, sleep_between=args.sleep)
