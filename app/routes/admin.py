# app/routes/admin.py
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, session, current_app, abort
)
from hmac import compare_digest
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
from uuid import uuid4
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import Deposito, Comprobante
from ..storage.base import get_storage

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

# ---------- vistas ----------
@bp.get("/registros")
def registros():
    if not _is_authed():
        return redirect(url_for("admin.login"))
    return render_template("admin/registros.html")

# ---------- util: crear comprobante placeholder ----------
def _create_placeholder_comprobante() -> Comprobante:
    """
    Crea un comprobante ficticio para satisfacer NOT NULL en comprobante_id cuando
    se añade una fila desde el grid sin archivo real todavía.
    """
    dummy = Comprobante(
        uuid=uuid4().hex,
        file_name="(pendiente)",
        mime="application/octet-stream",
        size=0,
        checksum_sha256="0"*64,
        storage_path=f"placeholder/{uuid4().hex}",
        storage_status="pendiente",
    )
    db.session.add(dummy)
    db.session.flush()  # para obtener dummy.id sin cerrar la transacción
    return dummy

# ---------- serializador ----------
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

# ---------- API: crear (para botón Agregar) ----------
@bp.post("/api/depositos")
def api_depositos_create():
    if not _is_authed():
        return abort(401)

    payload = request.get_json(silent=True) or {}

    try:
        # 1) crear comprobante ficticio para cumplir NOT NULL
        dummy = _create_placeholder_comprobante()

        # 2) defaults seguros (ajusta si tu modelo tiene constraints extra)
        #    Nota: numero_usuario = 0 temporalmente es válido (puedes editarlo después)
        dep = Deposito(
            fecha_operacion = payload.get("fecha_operacion") or date.today(),
            banco           = payload.get("banco")         or "BBVA",
            forma_pago      = payload.get("forma_pago")    or "Deposito",
            producto        = payload.get("producto")      or "TAE",
            numero_usuario  = int(payload.get("numero_usuario") or 0),
            importe         = Decimal(str(payload.get("importe") or "0.00")),
            bbva_tipo       = payload.get("bbva_tipo")     or None,
            folio           = payload.get("folio")         or None,
            autorizacion    = payload.get("autorizacion")  or None,
            referencia      = payload.get("referencia")    or None,
            requiere_factura= True if payload.get("requiere_factura") in (True, "true", "True", "1", 1) else False,
            estatus         = payload.get("estatus")       or "registrado",
            observaciones   = payload.get("observaciones") or None,
            comprobante_id  = dummy.id,
            created_at      = datetime.utcnow(),
            updated_at      = datetime.utcnow(),
        )

        db.session.add(dep)
        db.session.commit()
        return jsonify(_serialize_dep(dep)), 201

    except (SQLAlchemyError, ValueError, InvalidOperation) as e:
        db.session.rollback()
        current_app.logger.exception("Error al crear depósito")
        return jsonify({"error": f"No se pudo crear: {e}"}), 400

# ---------- API: actualizar ----------
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
            # ISO date string -> date
            value = date.fromisoformat(value)

        setattr(dep, field, value)
        dep.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(_serialize_dep(dep))

    except (SQLAlchemyError, ValueError, InvalidOperation) as e:
        db.session.rollback()
        return jsonify({"error": f"No se pudo guardar: {e}"}), 400

# ---------- API: eliminar ----------
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
