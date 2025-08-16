# app/routes/admin.py
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, session, current_app, abort
)
from hmac import compare_digest
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import Deposito, Comprobante
from ..storage.base import get_storage
from ..models import FacturaOpcion
import re

bp = Blueprint("admin", __name__, url_prefix="/admin")

# ---------- helpers de auth ----------
def _consteq(a: str | None, b: str | None) -> bool:
    a = (a or "").strip()
    b = (b or "").strip()
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

# ---------- vista ----------
@bp.get("/registros")
def registros():
    if not _is_authed():
        return redirect(url_for("admin.login"))
    return render_template("admin/registros.html")

# ---------- util ----------
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

# ---------- API: listar ----------
@bp.get("/api/depositos")
def api_depositos_list():
    if not _is_authed():
        return abort(401)

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
    return jsonify([_serialize_dep(r) for r in rows])

# ---------- API: actualizar (edición real) ----------
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
            value = None if value in (None, "", "None") else int(value)
        elif field == "requiere_factura":
            value = True if value in (True, "true", "True", "1", 1) else False
        elif field == "importe":
            value = Decimal(str(value or "0"))
        elif field == "fecha_operacion" and isinstance(value, str) and value:
            value = date.fromisoformat(value)

        setattr(dep, field, value)
        dep.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(_serialize_dep(dep))

    except (SQLAlchemyError, ValueError, InvalidOperation) as e:
        db.session.rollback()
        return jsonify({"error": f"No se pudo guardar: {e}"}), 400

# ---------- API: eliminar (Supr) ----------
@bp.delete("/api/depositos/<int:dep_id>")
def api_depositos_delete(dep_id: int):
    if not _is_authed():
        return abort(401)
    dep = Deposito.query.get_or_404(dep_id)
    try:
        db.session.delete(dep)
        db.session.commit()
        return ("", 204)
    except SQLAlchemyError as e:
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
            url = storage.get_temporary_link(comp.storage_path)  # temporal
        return redirect(url)
    except Exception as e:
        flash(f"No se pudo obtener enlace: {e}", "danger")
        return redirect(url_for("admin.registros"))


@bp.route("/fiscales", methods=["GET", "POST"])
def fiscales():
    if not _is_authed():
        return redirect(url_for("admin.login"))

    q = (request.args.get("numero_usuario") or "").strip()
    opciones = []
    if q.isdigit():
        opciones = (FacturaOpcion.query
                    .filter(FacturaOpcion.numero_usuario == int(q))
                    .order_by(FacturaOpcion.titulo.asc())
                    .all())

    if request.method == "POST":
        # alta rápida
        nu     = (request.form.get("numero_usuario") or "").strip()
        titulo = (request.form.get("titulo") or "").strip()
        rfc    = (request.form.get("rfc") or "").strip().upper()
        email  = (request.form.get("email") or "").strip()

        ok = True
        if not (nu.isdigit() and len(nu) == 5):
            flash("El número de usuario debe ser 5 dígitos.", "danger"); ok = False
        if not titulo:
            flash("La razón social (título) es obligatoria.", "danger"); ok = False
        if rfc and not re.match(r"^[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}$", rfc):
            flash("RFC no tiene formato válido (persona moral/física MX).", "danger"); ok = False

        if ok:
            fo = FacturaOpcion(numero_usuario=int(nu), titulo=titulo, rfc=rfc, email=email)
            db.session.add(fo)
            db.session.commit()
            flash("Opción fiscal guardada.", "success")
            return redirect(url_for("admin.fiscales", numero_usuario=nu))

    return render_template("admin/fiscales.html", opciones=opciones, q=q)

@bp.post("/fiscales/<int:oid>/update")
def fiscales_update(oid: int):
    if not _is_authed():
        return abort(401)
    fo = FacturaOpcion.query.get_or_404(oid)
    fo.titulo = (request.form.get("titulo") or "").strip()
    rfc = (request.form.get("rfc") or "").strip().upper()
    if rfc and not re.match(r"^[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}$", rfc):
        flash("RFC no tiene formato válido.", "danger")
    else:
        fo.rfc = rfc
    fo.email = (request.form.get("email") or "").strip()
    db.session.commit()
    flash("Opción actualizada.", "success")
    return redirect(url_for("admin.fiscales", numero_usuario=fo.numero_usuario))


@bp.post("/fiscales/<int:oid>/delete")
def fiscales_delete(oid: int):
    if not _is_authed():
        return abort(401)
    fo = FacturaOpcion.query.get_or_404(oid)
    nu = fo.numero_usuario
    db.session.delete(fo)
    db.session.commit()
    flash("Opción eliminada.", "success")
    return redirect(url_for("admin.fiscales", numero_usuario=nu))

# ---------- debug ----------
@bp.get("/debug/db")
def debug_db():
    if not _is_authed():
        return abort(401)
    from sqlalchemy import inspect
    info = {
        "uri": str(current_app.config.get("SQLALCHEMY_DATABASE_URI"))[:60] + "...",
        "tables": inspect(db.engine).get_table_names(),
        "count": db.session.query(Deposito).count()
    }
    return jsonify(info)
