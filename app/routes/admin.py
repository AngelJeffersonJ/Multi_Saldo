# app/routes/admin.py
from flask import Blueprint, render_template, redirect, request, flash, url_for, session, jsonify, current_app
from functools import wraps
from decimal import Decimal, InvalidOperation
from datetime import datetime
from ..models import Deposito, Comprobante
from ..extensions import db
from ..storage.base import get_storage

bp = Blueprint("admin", __name__, url_prefix="/admin")

# --------- Auth helpers ---------
def admin_required(f):
    @wraps(f)
    def _wrap(*args, **kwargs):
        if not session.get("admin_authed"):
            return redirect(url_for("admin.login", next=request.path))
        return f(*args, **kwargs)
    return _wrap

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        if u == current_app.config.get("ADMIN_USER") and p == current_app.config.get("ADMIN_PASSWORD"):
            session["admin_authed"] = True
            nxt = request.args.get("next") or url_for("admin.registros")
            return redirect(nxt)
        flash("Credenciales inválidas", "danger")
    return render_template("admin/login.html")

@bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("admin.login"))

# --------- Vistas HTML ---------
@bp.get("/registros")
@admin_required
def registros():
    return render_template("admin/registros.html")

# --------- API para grid ---------
@bp.get("/api/depositos")
@admin_required
def api_depositos_list():
    rows = (Deposito.query
            .order_by(Deposito.created_at.desc())
            .all())
    data = []
    for d in rows:
        data.append({
            "id": d.id,
            "banco": d.banco,
            "forma_pago": d.forma_pago,
            "producto": d.producto,
            "fecha_operacion": d.fecha_operacion.strftime("%Y-%m-%d"),
            "numero_usuario": f"{d.numero_usuario:05d}",
            "importe": float(d.importe),
            "bbva_tipo": d.bbva_tipo or "",
            "folio": d.folio or "",
            "autorizacion": d.autorizacion or "",
            "referencia": d.referencia or "",
            "requiere_factura": d.requiere_factura,
            "estatus": d.estatus,
            "observaciones": d.observaciones or "",
            "comprobante_id": d.comprobante_id,
        })
    return jsonify(data)

@bp.patch("/api/depositos/<int:dep_id>")
@admin_required
def api_depositos_update(dep_id):
    d = Deposito.query.get_or_404(dep_id)
    body = request.get_json(force=True) or {}
    field = body.get("field")
    value = body.get("value")

    # Campos permitidos a editar desde el grid
    editable = {
        "banco", "forma_pago", "producto", "fecha_operacion",
        "numero_usuario", "importe", "bbva_tipo", "folio",
        "autorizacion", "referencia", "requiere_factura",
        "estatus", "observaciones"
    }
    if field not in editable:
        return jsonify({"ok": False, "error": "Campo no editable"}), 400

    try:
        if field == "fecha_operacion":
            d.fecha_operacion = datetime.strptime(value, "%Y-%m-%d").date()
        elif field == "numero_usuario":
            if not (str(value).isdigit() and len(str(value)) == 5):
                return jsonify({"ok": False, "error": "numero_usuario debe ser 5 dígitos"}), 400
            d.numero_usuario = int(value)
        elif field == "importe":
            d.importe = Decimal(str(value))
        elif field == "requiere_factura":
            d.requiere_factura = bool(value)
        else:
            setattr(d, field, (value or "").strip())
        db.session.commit()
        return jsonify({"ok": True})
    except (InvalidOperation, ValueError) as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400

@bp.delete("/api/depositos/<int:dep_id>")
@admin_required
def api_depositos_delete(dep_id):
    d = Deposito.query.get_or_404(dep_id)
    db.session.delete(d)
    db.session.commit()
    return jsonify({"ok": True})

# --------- Comprobantes ---------
@bp.get("/comprobantes/<int:comp_id>/link")
@admin_required
def comprobante_link(comp_id: int):
    comp = Comprobante.query.get_or_404(comp_id)
    storage = get_storage()
    # Preferimos compartido; si no, temporal. Si el archivo no existe, mensaje claro.
    try:
        url = storage.get_shared_link(comp.storage_path)
    except FileNotFoundError:
        flash("El comprobante ya no existe en Dropbox (fue eliminado).", "danger")
        return redirect(url_for("admin.registros"))
    except Exception as e1:
        try:
            url = storage.get_temporary_link(comp.storage_path)
        except FileNotFoundError:
            flash("El comprobante ya no existe en Dropbox (fue eliminado).", "danger")
            return redirect(url_for("admin.registros"))
        except Exception as e2:
            flash(f"No se pudo obtener enlace (compartido/temporal fallaron): {e1} / {e2}", "danger")
            return redirect(url_for("admin.registros"))
    return redirect(url)
