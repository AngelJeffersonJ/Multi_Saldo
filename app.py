import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify

import graph_client

app = Flask(__name__)

# --------- Rutas de autenticación ---------
@app.get("/auth/start")
def auth_start():
    """
    Dispara Device Code Flow; se queda esperando a que completes el login
    (la página de Microsoft te dirá 'Ya puede cerrar esta ventana').
    """
    try:
        graph_client.get_token(interactive=True)
        return "<h3>Listo ✔</h3><p>Vuelve a la app y pulsa <b>Revisar estado</b>.</p>"
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


# --------- API de clientes (cards por número de usuario) ---------
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
    # Verificar token
    try:
        token = graph_client.get_token(interactive=False)
    except Exception as e:
        return (f"<h3>OneDrive no conectado</h3>"
                f"<p>Debes autenticarte: <a href='/auth/start'>/auth/start</a></p>"
                f"<pre>{e}</pre>"), 401

    # Recibir datos del form
    f = request.form
    producto = f.get("producto") or ""
    banco = f.get("banco") or ""
    tipo_bbva = f.get("tipo_bbva") or ""
    forma_pago = f.get("forma_pago") or ""
    numero_usuario = (f.get("numero_usuario") or "").strip()
    requiere_factura = True if f.get("requiere_factura") else False

    # Folios (según UI)
    folio = f.get("folio") or ""
    autorizacion = f.get("autorizacion") or ""
    folio_movimiento = f.get("folio_movimiento") or ""

    # Si BBVA practicaja, vienen en los campos con data-bind (autoclear_*)
    folio = f.get("autoclear_folio", folio)
    autorizacion = f.get("autoclear_aut", autorizacion)
    folio_movimiento = f.get("autoclear_folmov", folio_movimiento)

    # Si TAE, ocultamos y enviamos vacíos folios
    if producto.lower() == "tae":
        folio = ""
        autorizacion = ""
        folio_movimiento = ""

    importe = (f.get("importe") or "").strip()
    realizo = f.get("realizo") or ""
    observaciones = f.get("observaciones") or ""
    cliente_id = f.get("cliente_id") or ""
    cliente_nombre = f.get("cliente_nombre") or ""

    # Fecha
    fecha_iso = f.get("fecha_iso") or datetime.now().strftime("%Y-%m-%d")

    # Archivo
    file = request.files.get("comprobante")
    if not file:
        return "Falta comprobante.", 400

    # Subir a OneDrive
    uploaded = graph_client.upload_file_stream(
        token=token,
        file_stream=file.stream,
        original_filename=file.filename,
        cliente_nombre=cliente_nombre or cliente_id or "SIN_CLIENTE",
        fecha=datetime.fromisoformat(fecha_iso) if fecha_iso else None,
        rename_safe=True,
    )
    comprobante_url = uploaded.get("webUrl") or uploaded.get("@microsoft.graph.downloadUrl", "")

    # Armar payload y guardar en Excel (detalle + resumen)
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

    # Si el Excel central no existe la primera vez, se sube un template local en /data
    template_local = "/data/central_base.xlsx"
    res1 = graph_client.add_solicitud_row(token, payload, template_local=template_local)
    res2 = graph_client.add_deps_row(token, payload)

    return render_template("success.html",
                           comprobante_url=comprobante_url,
                           res_detalle=res1, res_resumen=res2, payload=payload)


if __name__ == "__main__":
    # Para correr local: python app.py
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=True)
