import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify

import graph_client

app = Flask(__name__)

@app.get("/")
def index():
    # Verificamos rápido que hay token válido; si no, mostramos aviso arriba del form,
    # pero NUNCA bloqueamos la UI.
    ready, detail = graph_client.ensure_ready()
    return render_template("form.html", graph_ready=ready, graph_detail=detail)

@app.get("/api/ping")
def ping():
    ready, detail = graph_client.ensure_ready()
    return {"ok": ready, "detail": detail}

@app.get("/api/clientes")
def api_clientes():
    numero = (request.args.get("usuario") or "").strip()
    if not numero:
        return jsonify({"ok": True, "items": []})
    ready, detail = graph_client.ensure_ready()
    if not ready:
        return jsonify({"ok": False, "error": f"Graph no listo: {detail}"})
    token = graph_client.get_token()
    items = graph_client.get_clientes_por_usuario(token, numero)
    return jsonify({"ok": True, "items": items})

@app.post("/submit")
def submit():
    # Nunca pedimos login; si no hay token es error del servidor (credenciales)
    ready, detail = graph_client.ensure_ready()
    if not ready:
        return (f"<h3>Error de servidor</h3><p>OneDrive no está listo: {detail}</p>", 500)

    f = request.form
    producto = f.get("producto") or ""
    banco = f.get("banco") or ""
    tipo_bbva = f.get("tipo_bbva") or ""
    forma_pago = f.get("forma_pago") or ""
    numero_usuario = (f.get("numero_usuario") or "").strip()
    requiere_factura = True if f.get("requiere_factura") else False

    # BBVA variantes
    folio = f.get("folio") or ""
    autorizacion = f.get("autorizacion") or ""
    folio_movimiento = f.get("folio_movimiento") or ""

    folio = f.get("autoclear_folio", folio)
    autorizacion = f.get("autoclear_aut", autorizacion)
    folio_movimiento = f.get("autoclear_folmov", folio_movimiento)

    # Si TAE => sin folios
    if (f.get("producto") or "").lower() == "tae":
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

    token = graph_client.get_token()

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

    # si no existe el Excel lo genera local y lo sube
    template_local = "/data/central_base.xlsx"
    res1 = graph_client.add_solicitud_row(token, payload, template_local=template_local)
    res2 = graph_client.add_deps_row(token, payload)

    return render_template("success.html",
                           comprobante_url=comprobante_url,
                           res_detalle=res1, res_resumen=res2, payload=payload)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=True)
