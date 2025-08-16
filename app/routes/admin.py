# app/routes/admin.py
from __future__ import annotations

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, session, current_app, abort
)
from hmac import compare_digest
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from ..extensions import db
from ..models import Deposito, Comprobante
from ..storage.base import get_storage

bp = Blueprint("admin", __name__, url_prefix="/admin")


# ---------- helpers de auth ----------
def _consteq(a: str | None, b: str | None) -> bool:
    """Comparación constante para evitar timing attacks."""
    a = (a or "").strip()
    b = (b or "").strip()
    return compare_digest(a, b)


def _is_authed() -> bool:
    return bool(session.get("admin_authed"))


def _require_auth():
    if not _is_authed():
        abort(401)


# ---------- helpers de parsing ----------
def _to_bool(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in ("1", "true", "t", "yes", "y", "on")


def _to_int_or_none(v):
    if v in (None, "", "None"):
        return None
    return int(v)


def _to_decimal_or_none(v):
    if v in (None, "", "None"):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise ValueError("importe inválido")


def _to_date_or_none(v):
    if not v:
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()
    # acepta "YYYY-MM-DD" o "DD/MM/YYYY"
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError("fecha inválida (usa AAAA-MM-DD)")


# ---------- auth ----------
@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username", "")
        pwd = request.form.get("password", "")
        if _consteq(user, current_app.config.get("ADMIN_USER")) and _consteq(
            pwd, current_app.config.get("ADMIN_PASSWORD")
        ):
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


# ---------- serialización ----------
def _serialize_dep(d: Deposito) -> dict:
    return {
        "id": d.id,
        "fecha_operacion": d.fecha_operacion.isoformat() if d.fecha_operacion else "",
        "banco": d.banco,
        "forma_pago": d.forma_pago,
        "producto": d.producto,
        "numero_usuario": d.numero_usuario,
        "importe": str(d.importe) if d.importe is not None else "",
        "bbva_tipo": d.bbva_tipo or "",
        "folio": d.folio or "",
        "autorizacion": d.autorizacion or "",
        "referencia": d.referencia or "",
        "requiere_factura": bool(d.requiere_factura),
        "estatus": d.estatus or "registrado",
        "observaciones": d.observaciones or "",
        "comprobante_id": d.comprobante_id,
    }


# ---------- API para el grid ----------
@bp.get("/api/depositos")
def api_depositos_list():
    _require_auth()

    q_banco = request.args.get("banco")
    q_forma = request.args.get("forma_pago")
    q_usuario = request.args.get("numero_usuario")

    query = Deposito.query
    if q_banco:
        query = query.filter(Deposito.banco == q_banco)
    if q_forma:
        query = query.filter(Deposito.forma_pago == q_forma)
    if q_usuario:
        # permite “contiene” para búsqueda rápida
        query = query.filter(Deposito.numero_usuario.cast(db.String).like(f"%{q_usuario}%"))

    rows = query.order_by(Deposito.id.desc()).all()
    current_app.logger.info("Admin API -> %d depósito(s) devueltos", len(rows))
    return jsonify([_serialize_dep(r) for r in rows])


@bp.post("/api/depositos")
def api_depositos_create():
    """Crear registro mínimo para el botón 'Agregar' del grid."""
    _require_auth()
    data = request.get_json(silent=True) or {}

    d = Deposito(
        banco=data.get("banco") or "BBVA",
        forma_pago=data.get("forma_pago") or "Deposito",
        producto=data.get("producto") or "TAE",
        estatus=data.get("estatus") or "registrado",
    )
    # Campos opcionales iniciales si vienen:
    if "fecha_operacion" in data:
        d.fecha_operacion = _to_date_or_none(data.get("fecha_operacion"))
    if "numero_usuario" in data:
        d.numero_usuario = _to_int_or_none(data.get("numero_usuario"))
    if "importe" in data:
        d.importe = _to_decimal_or_none(data.get("importe"))
    d.bbva_tipo = data.get("bbva_tipo") or None
    d.folio = data.get("folio") or None
    d.autorizacion = data.get("autorizacion") or None
    d.referencia = data.get("referencia") or None
    d.requiere_factura = _to_bool(data.get("requiere_factura"))
    d.observaciones = data.get("observaciones") or None

    db.session.add(d)
    db.session.commit()
    return jsonify(_serialize_dep(d)), 201


@bp.patch("/api/depositos/<int:dep_id>")
def api_depositos_update(dep_id: int):
    _require_auth()
    payload = request.get_json(silent=True) or {}
    field = payload.get("field")
    value = payload.get("value")

    if not field:
        return jsonify({"error": "field requerido"}), 400

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
        if field == "fecha_operacion":
            value = _to_date_or_none(value)
        elif field == "numero_usuario":
            value = _to_int_or_none(value)
        elif field == "importe":
            value = _to_decimal_or_none(value)
        elif field == "requiere_factura":
            value = _to_bool(value)

        setattr(dep, field, value)
        db.session.commit()
        return jsonify(_serialize_dep(dep))
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"No se pudo guardar: {e}"}), 400


@bp.delete("/api/depositos/<int:dep_id>")
def api_depositos_delete(dep_id: int):
    _require_auth()
    dep = Deposito.query.get_or_404(dep_id)
    try:
        db.session.delete(dep)
        db.session.commit()
        return "", 204
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"No se pudo eliminar: {e}"}), 400


# ---------- Link de comprobante ----------
@bp.get("/comprobante/<int:comp_id>/link")
def comprobante_link(comp_id: int):
    _require_auth()
    comp = Comprobante.query.get_or_404(comp_id)
    try:
        storage = get_storage()
        try:
            url = storage.get_shared_link(comp.storage_path)  # intento permanente
        except Exception:
            url = storage.get_temporary_link(comp.storage_path)  # fallback temporal
        return redirect(url)
    except Exception as e:
        # Si el archivo fue eliminado de Dropbox u otro error, avisamos y volvemos a la vista
        flash(f"No se pudo obtener el comprobante: {e}", "danger")
        return redirect(url_for("admin.registros"))


# ---------- debug ----------
@bp.get("/debug/db")
def debug_db():
    _require_auth()
    from sqlalchemy import inspect
    info = {
        "uri": str(current_app.config.get("SQLALCHEMY_DATABASE_URI"))[:80] + "...",
        "tables": inspect(db.engine).get_table_names(),
        "count_depositos": db.session.query(Deposito).count(),
    }
    return jsonify(info)
