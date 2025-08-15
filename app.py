import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify

import graph_client

app = Flask(__name__)

# --------- Auth no bloqueante ---------
@app.get("/auth/start")
def auth_start():
    """
    Inicia el device code flow sin bloquear. Devuelve una página con el código
    y lanza un hilo que completará la autenticación en segundo plano.
    """
    try:
        data = graph_client.start_device_flow()
        if data.get("already"):
            return ("<h3>Ya estabas conectado ✔</h3>"
                    "<p>Cierra esta pestaña y presiona <b>Revisar estado</b> en la app.</p>")
        msg = data.get("message", "")
        ver = data.get("verification_uri")
        code = data.get("user_code")
        html = f"""
        <html><body style="font-family:system-ui">
        <h2>Conectar con OneDrive</h2>
        <p>1) Abre <a href="{ver}" target="_blank">{ver}</a></p>
        <p>2) Ingresa este código: <b style="font-size:20px">{code}</b></p>
        <p>3) Cuando Microsoft diga “Ya puede cerrar esta ventana”, vuelve a la app y pulsa <b>Revisar estado</b>.</p>
        <hr><pre style="white-space:pre-wrap">{msg}</pre>
        </body></html>
        """
        return html
    except Exception as e:
        return f"Error iniciando autenticación: {e}", 500


@app.get("/auth/status")
def auth_status():
    return graph_client.auth_status()


@app.get("/auth/clear")
def auth_clear():
    path = graph_client.TOKEN_CACHE_FILE
    try:
        if os.path.exists(path):
            os.remove(path)
        return {"ok": True, "cleared": True, "path": path}
    except Exception as e:
        return {"ok": False, "error": str(e), "path": path}, 500


# --------- API clientes ---------
@app.get("/api/clientes")
def api_clientes():
    numero = (request.args.get("usuario") or "").strip()
    if not numero:
        return jsonify({"ok": True, "items": []})
    try:
        token = graph_client.get_token(interactive=False)
    except Exception:
        return jsonify({"ok": False, "error": "No autenticado con OneDrive"})
    items = graph_client.get_clientes_por_usuario(token, numero)
    return jsonify({"ok": True, "items": items})


# --------- Formulario ---------
@app.get("/")
def index():
    return render_template("form.html")


@app.post("/submit")
def submit():
    try:
        token = graph_client.get_token(interactive=False)
    except Exception as e:
        return (f"<h3>OneDrive no conectado</h3>"
                f"<p>Primero autentícate en <a href='/auth/start' target='_blank'>/auth/start</a> "
                f"y luego presiona <b>Revisar estado</b>.</p>"
                f"<pre>{e}</pre>"), 401

    f = request.form
    producto = f.get("producto") or ""
    banco = f.get("banco") or ""
    tipo_bbva = f.get("tipo_bbva") or ""
    forma_pago = f.get("forma_pago") or ""
    numero_usuario = (f.get("numero_usuario") or "").strip()
    requiere_factura = True if f.get("requiere_factura") else False

    folio = f.get("folio") or ""
    autorizacion = f.get("autorizacion") or ""
    folio_movimiento = f.get("folio_movimiento") or ""

    folio = f.get("autoclear_folio", folio)
    autorizacion = f.get("autoclear_aut", autorizacion)
    folio_movimiento = f.get("autoclear_folmov", folio_movimiento)

    if producto.lower() == "tae":
        folio = ""
        autorizacion = ""
        folio_movimiento = ""

    importe = (f.get("importe") or "").strip()
    realizo = f.get("realizo") or ""
    observaciones = f.get("observaciones") or ""
    cliente_id = f.get("cliente_id") or ""
    cliente_nombre = f.get("cliente_nombre") or ""

    fecha_iso = f.get("fecha_iso") or datetime.now().strftime("%Y-%m-%d")

    file = request.files.get("comprobante")
    if not file:
        return "Falta comprobante.", 400

    uploaded = graph_client.upload_file_stream(
        token=token,
        file_stream=file.stream,
        original_filename=file.filename,
        cliente_nombre=cliente_nombre or cliente_id or "SIN_CLIENTE",
        fecha=datetime.fromisoformat(fecha_iso) if fecha_iso else None,
        rename_safe=True,
    )
    comprobante_url = uploaded.get("webUrl") or uploaded.get("@microsoft.graph.downloadUrl", "")

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
        "realizo": realizo,
        "comprobante_url": comprobante_url,
        "origen": "formulario",
    }

    template_local = "/data/central_base.xlsx"
    res1 = graph_client.add_solicitud_row(token, payload, template_local=template_local)
    res2 = graph_client.add_deps_row(token, payload)

    return render_template("success.html",
                           comprobante_url=comprobante_url,
                           res_detalle=res1, res_resumen=res2, payload=payload)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=True)
