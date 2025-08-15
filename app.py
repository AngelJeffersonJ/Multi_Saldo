import os
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify

from graph_client import (
    get_token,
    upload_file_stream,
    add_solicitud_row,
    add_deps_row,
    get_clientes_por_usuario,
)

load_dotenv()  # local; en Railway usa variables del panel

app = Flask(__name__, template_folder="templates")

@app.route("/", methods=["GET"])
def index():
    return render_template("form.html")

@app.route("/api/clientes", methods=["GET"])
def api_clientes():
    try:
        numero_usuario = (request.args.get("usuario") or "").strip()
        if not numero_usuario:
            return jsonify({"ok": True, "items": []})
        token = get_token()
        items = get_clientes_por_usuario(token, numero_usuario)
        return jsonify({"ok": True, "items": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/submit", methods=["POST"])
def submit():
    try:
        token = get_token()

        # ----- Campos del formulario -----
        fecha_iso = request.form.get("fecha_iso") or datetime.now().strftime("%Y-%m-%d")
        banco = (request.form.get("banco") or "").strip()
        forma_pago = (request.form.get("forma_pago") or "").strip()
        producto = (request.form.get("producto") or "").strip()
        importe = (request.form.get("importe") or "").strip()

        tipo_bbva = (request.form.get("tipo_bbva") or "").strip() if banco == "BBVA" else ""

        # Folios según UI (todos llegan por su nombre final)
        folio = (request.form.get("folio") or "").strip()
        autorizacion = (request.form.get("autorizacion") or "").strip()
        folio_movimiento = (request.form.get("folio_movimiento") or "").strip()

        numero_usuario = (request.form.get("numero_usuario") or "").strip()
        requiere_factura = bool(request.form.get("requiere_factura"))
        realizo = (request.form.get("realizo") or "").strip()
        observaciones_extra = (request.form.get("observaciones") or "").strip()

        cliente_id = (request.form.get("cliente_id") or "").strip()
        cliente_nombre = (request.form.get("cliente_nombre") or "").strip()

        # Comprobante (obligatorio)
        comp_file = request.files.get("comprobante")
        if not comp_file or comp_file.filename == "":
            return "Archivo de comprobante requerido", 400

        # ----- Subir comprobante a OneDrive -----
        # Estructura: /Comprobantes/<Cliente>/<YYYY>/<MM>/<DD>/
        uploaded = upload_file_stream(
            token=token,
            file_stream=comp_file.stream,
            original_filename=comp_file.filename,
            cliente_nombre=cliente_nombre or cliente_id or "SIN_CLIENTE",
            fecha=datetime.fromisoformat(fecha_iso) if fecha_iso else None,
            rename_safe=True,
        )
        comprobante_url = uploaded.get("@microsoft.graph.downloadUrl", "") or uploaded.get("webUrl", "")

        # ----- Payload común -----
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
            "realizo": realizo,
            "observaciones": observaciones_extra,
            "cliente_id": cliente_id,
            "cliente_nombre": cliente_nombre,
            "comprobante_url": comprobante_url,
            "origen": "formulario",
        }

        # ----- Escribir en Excel: detalle (Solicitudes) -----
        add_solicitud_row(token, payload, template_local="central_solicitudes_base.xlsx")

        # ----- Escribir en Excel: resumen (Deps) -----
        add_deps_row(token, payload)

        return render_template("success.html",
                               cliente=cliente_nombre or cliente_id or "(sin cliente)",
                               fecha=fecha_iso, banco=banco, importe=importe)
    except Exception as e:
        return f"Error: {e}", 500


if __name__ == "__main__":
    # Útil para debug local
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=True)
