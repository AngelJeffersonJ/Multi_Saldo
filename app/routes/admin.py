# app/routes/admin.py
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, session, current_app, abort
)
from hmac import compare_digest  # sustituto de safe_str_cmp
from ..extensions import db
from ..models import Deposito, Comprobante
from ..storage.base import get_storage

bp = Blueprint("admin", __name__, url_prefix="/admin")

# ---------- helpers de auth ----------
def _consteq(a: str | None, b: str | None) -> bool:
    """Comparación constante para evitar timing attacks."""
    a = (a or "").strip()
    b = (b or "").strip()
    # compare_digest opera sobre str a partir de Py3.3; también vale .encode()
    return compare_digest(a, b)

def _is_authed() -> bool:
    return bool(session.get("admin_authed"))

# ---------- auth ----------
@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username", "")
        pwd = request.form.get("password", "")
        if _consteq(user, current_app.config["ADMIN_USER"]) and _consteq(pwd, current_app.config["ADMIN_PASSWORD"]):
            session["admin_authed"] = True
            flash("Bienvenido.", "success")
            return redirect(url_for("admin.registros"))
        flash("Usuario o contraseña incorrectos.", "danger")
    return render_template("admin/login.html")

@bp.get("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada.", "success")
    return redirect(url_for("admin.login"))

# ---------- vistas ----------
@bp.get("/registros")
def registros():
    if not _is_authed():
        return redirect(url_for("admin.login"))
    return render_template("admin/registros.html")

# ---------- API para el grid ----------
def _serialize_dep(d: Deposito) -> dict:
    return {
        "id": d.id,
        "fecha_operacion": d.fecha_operacion.isoformat() if d.fecha_operacion else "",
        "banco": d.banco,
        "forma_pago": d.forma_pago,
        "producto": d.producto,
        "numero_usuario": d.numero_usuario,
        "importe": str(d.importe) if d.importe is not None else "0.00",
        "bbva_tipo": d.bbva_tipo or "",
        "folio": d.folio or "",
        "autorizacion": d.autorizacion or "",
        "referencia": d.referencia or "",
        "requiere_factura": bool(d.requiere_factura),
        "estatus": d.estatus or "registrado",
        "observaciones": d.observaciones or "",
        "comprobante_id": d.comprobante_id,
    }

@bp.get("/api/depositos")
def api_depositos_list():
    if not _is_authed():
        return abort(401)

    # filtros opcionales
    q_banco = request.args.get("banco")
    q_forma = request.args.get("forma_pago")
    q_usuario = request.args.get("numero_usuario")

    query = Deposito.query
    if q_banco:
        query = query.filter(Deposito.banco == q_banco)
    if q_forma:
        query = query.filter(Deposito.forma_pago == q_forma)
    if q_usuario:
        query = query.filter(Deposito.numero_usuario.like(f"%{q_usuario}%"))

    rows = query.order_by(Deposito.id.desc()).all()
    current_app.logger.info("Admin API -> %d depósito(s) devueltos", len(rows))
    return jsonify([_serialize_dep(r) for r in rows])

@bp.patch("/api/depositos/<int:dep_id>")
def api_depositos_update(dep_id: int):
    if not _is_authed():
        return abort(401)
    payload = request.get_json(silent=True) or {}
    field = payload.get("field")
    value = payload.get("value")

    dep = Deposito.query.get_or_404(dep_id)

    editable = {
        "fecha_operacion", "banco", "forma_pago", "producto",
        "numero_usuario", "importe", "bbva_tipo", "folio",
        "autorizacion", "referencia", "requiere_factura",
        "estatus", "observaciones"
    }
    if field not in editable:
        return jsonify({"error": f"Campo no editable: {field}"}), 400

    try:
        if field == "numero_usuario":
            value = int(value) if value not in (None, "", "None") else None
        elif field == "requiere_factura":
            value = bool(value)
        setattr(dep, field, value)
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"No se pudo guardar: {e}"}), 400

@bp.delete("/api/depositos/<int:dep_id>")
def api_depositos_delete(dep_id: int):
    if not _is_authed():
        return abort(401)
    dep = Deposito.query.get_or_404(dep_id)
    try:
        db.session.delete(dep)
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"No se pudo eliminar: {e}"}), 400

# ---------- Link de comprobante ----------
@bp.get("/comprobante/<int:comp_id>/link")
def comprobante_link(comp_id: int):
    if not _is_authed():
        return abort(401)
    comp = Comprobante.query.get_or_404(comp_id)
    try:
        storage = get_storage()
        try:
            url = storage.get_shared_link(comp.storage_path)  # permanente
        except Exception:
            url = storage.get_temporary_link(comp.storage_path)  # fallback temporal
        return redirect(url)
    except Exception as e:
        flash(f"No se pudo obtener enlace: {e}", "danger")
        return redirect(url_for("admin.registros"))

@bp.get("/debug/db")
def debug_db():
    if not _is_authed(): return abort(401)
    from sqlalchemy import inspect
    info = {
        "uri": str(current_app.config.get("SQLALCHEMY_DATABASE_URI"))[:60] + "...",
        "tables": inspect(db.engine).get_table_names(),
        "count": db.session.query(Deposito).count()
    }
    return jsonify(info)
