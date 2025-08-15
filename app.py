# app.py
import os
import io
from datetime import datetime
from flask import Flask, render_template, request, jsonify

from graph_client import (
    get_token, upload_file_stream,
    add_solicitud_row, add_deps_row, get_clientes_por_usuario
)

from dotenv import load_dotenv
load_dotenv()

TEMPLATE_LOCAL_XLSX = "central_solicitudes.xlsx"  # se genera solo si falta

ALLOWED_EXT = {"jpg", "jpeg", "png", "pdf"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


@app.get("/health")
def health():
    return "ok", 200


@app.get("/")
def form():
    return render_template("form.html")


@app.get("/api/clientes")
def api_clientes():
    numero = (request.args.get("usuario") or "").strip()
    if not numero:
        return jsonify({"ok": True, "items": []})
    try:
        token = get_token()
        items = get_clientes_por_usuario(token, numero)
        return jsonify({"ok": True, "items": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/submit")
def submit():
    try:
        token = get_token()
    except Exception as e:
        return f"Error de autenticación Microsoft: {e}", 500

    # Campos del formulario
    fecha_iso = (request.form.get("fecha_iso") or datetime.now().strftime("%Y-%m-%d")).strip()
    banco = (request.form.get("banco") or "").strip()
    forma_pago = (request.form.get("forma_pago") or "").strip()
    producto = (request.form.get("producto") or "").strip()
    importe = (request.form.get("importe") or "").strip()

    tipo_bbva = (request.form.get("tipo_bbva") or "").strip()
    folio = (request.form.get("folio") or "").strip()
    autorizacion = (request.form.get("autorizacion") or "").strip()
    folio_movimiento = (request.form.get("folio_movimiento") or "").strip()

    numero_usuario = (request.form.get("numero_usuario") or "").strip()
    requiere_factura = request.form.get("requiere_factura") == "on"
    observaciones = (request.form.get("observaciones") or "").strip()
    realizo = (request.form.get("realizo") or "").strip()

    cliente_id = (request.form.get("cliente_id") or "").strip()
    cliente_nombre = (request.form.get("cliente_nombre") or "").strip()

    # Si producto es TAE: forzar vacíos los campos de referencia
    if producto.lower() == "tae":
        tipo_bbva = ""
        folio = ""
        autorizacion = ""
        folio_movimiento = ""

    f = request.files.get("comprobante")
    if not f or f.filename == "":
        return "Falta adjuntar comprobante", 400
    if not allowed_file(f.filename):
        return "Formato de archivo no permitido (solo jpg/jpeg/png/pdf)", 400

    # Subir archivo a OneDrive
    file_bytes = io.BytesIO(f.read())
    file_bytes.seek(0)
    try:
        up = upload_file_stream(
            token=token,
            file_stream=file_bytes,
            original_filename=f.filename,
            cliente_nombre=cliente_nombre or "SIN_CLIENTE",
            fecha=datetime.fromisoformat(fecha_iso) if fecha_iso else datetime.now(),
        )
        web_url = up.get("webUrl", "")
    except Exception as e:
        return f"Error subiendo a OneDrive: {e}", 500

    payload = {
        "fecha_iso": fecha_iso,
        "banco": banco,
        "forma_pago": forma_pago,
        "producto": producto,
        "importe": importe,
        "tipo_bbva": tipo_bbva,
        "folio": folio,
        "autorizacion": autorizacion,
        "folio_movimiento": folio_movimiento,
        "numero_usuario": numero_usuario,
        "requiere_factura": requiere_factura,
        "observaciones": observaciones,
        "cliente_id": cliente_id,
        "cliente_nombre": cliente_nombre,
        "comprobante_url": web_url,
        "origen": "formulario",
        "realizo": realizo,
    }

    try:
        add_solicitud_row(token, payload, template_local=TEMPLATE_LOCAL_XLSX)
    except Exception as e:
        return f"Subí el archivo pero falló al escribir en Excel 'Solicitudes': {e}", 500

    try:
        add_deps_row(token, payload)
    except Exception as e:
        return f"Se escribió 'Solicitudes' pero falló resumen 'Depositos': {e}", 500

    return render_template("success.html", web_url=web_url, cliente_nombre=cliente_nombre, fecha=fecha_iso)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
