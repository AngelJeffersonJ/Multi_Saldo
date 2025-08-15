import os
from flask import Flask, request, render_template, jsonify
from dotenv import load_dotenv

load_dotenv()

from graph_client import (
    get_token, has_valid_token, start_device_auth,
    upload_file_stream, add_solicitud_row, add_deps_row,
    get_clientes_por_usuario,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 35 * 1024 * 1024  # 35 MB por archivo

@app.get("/healthz")
def healthz():
    return "ok", 200

@app.get("/")
def index():
    return render_template("form.html")

@app.get("/auth/status")
def auth_status():
    try:
        return jsonify({"ok": has_valid_token()})
    except Exception:
        return jsonify({"ok": False})

@app.get("/auth/start")
def auth_start():
    try:
        msg = start_device_auth()
        html = f"""
        <h2>Conectar OneDrive</h2>
        <p>1) Abre <a href="https://microsoft.com/devicelogin" target="_blank">https://microsoft.com/devicelogin</a></p>
        <p>2) Pega el código que verás a continuación y completa el inicio de sesión con tu cuenta.</p>
        <hr>
        <pre style="white-space:pre-wrap;border:1px solid #ddd;padding:10px;border-radius:8px;">{msg}</pre>
        <p>3) Vuelve al formulario y pulsa <b>Revisar estado</b>.</p>
        <p><a href="/">Volver al formulario</a></p>
        """
        return html
    except Exception as e:
        return f"Error iniciando autenticación: {e}", 500

@app.get("/api/clientes")
def api_clientes():
    usuario = (request.args.get("usuario") or "").strip()
    if not usuario:
        return jsonify({"ok": True, "items": []})
    try:
        token = get_token()  # requiere sesión
    except Exception:
        # Sin sesión no podemos leer el Excel → devuelve vacío (el banner ya te avisa)
        return jsonify({"ok": True, "items": []})

    try:
        items = get_clientes_por_usuario(token, usuario)
        return jsonify({"ok": True, "items": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/submit")
def submit():
    form = request.form
    files = request.files

    payload = {
        "fecha_iso": form.get("fecha_iso") or "",
        "banco": form.get("banco") or "",
        "forma_pago": form.get("forma_pago") or "",
        "producto": form.get("producto") or "",
        "importe": form.get("importe") or "",
        "tipo_bbva": form.get("tipo_bbva") or "",
        "folio": form.get("folio") or form.get("autoclear_folio") or "",
        "autorizacion": form.get("autorizacion") or form.get("autoclear_aut") or "",
        "folio_movimiento": form.get("folio_movimiento") or form.get("autoclear_folmov") or "",
        "numero_usuario": form.get("numero_usuario") or "",
        "requiere_factura": bool(form.get("requiere_factura")),
        "observaciones": form.get("observaciones") or "",
        "realizo": form.get("realizo") or "",
        "cliente_id": form.get("cliente_id") or "",
        "cliente_nombre": form.get("cliente_nombre") or "",
        "origen": "formulario",
    }

    # 1) token
    try:
        token = get_token()
    except Exception:
        return (
            "Autenticación requerida con OneDrive. Abre <a href=\"/auth/start\">/auth/start</a>, completa el login y vuelve a intentar.",
            401,
        )

    # 2) subir comprobante
    comp = files.get("comprobante")
    if comp and comp.filename:
        up = upload_file_stream(
            token=token,
            file_stream=comp.stream,
            original_filename=comp.filename,
            cliente_nombre=payload.get("cliente_nombre") or payload.get("cliente_id") or "SIN_CLIENTE",
        )
        payload["comprobante_url"] = up.get("@microsoft.graph.downloadUrl") or up.get("webUrl") or ""
    else:
        payload["comprobante_url"] = ""

    # 3) escribir excel (detalle + deps)
    add_solicitud_row(token, payload, template_local="data/central_template.xlsx")
    add_deps_row(token, payload)

    return render_template("success.html", payload=payload)

if __name__ == "__main__":
    # Para pruebas locales:  flask run  o  python app.py
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
