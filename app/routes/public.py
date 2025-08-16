from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from decimal import Decimal
from datetime import datetime
import hashlib, os

from .. import db
from ..models import FacturaOpcion, Deposito, Comprobante, BANCOS, FORMAS, PRODUCTOS
from ..storage.base import get_storage

bp = Blueprint("public", __name__)

def _validate(form, has_file: bool):
    errors = []

    if form.get("banco") not in BANCOS: errors.append("Banco inválido.")
    if form.get("forma_pago") not in FORMAS: errors.append("Forma de pago inválida.")
    if form.get("producto") not in PRODUCTOS: errors.append("Producto inválido.")

    try:
        datetime.strptime(form.get("fecha_operacion",""), "%Y-%m-%d")
    except:
        errors.append("Fecha inválida (YYYY-MM-DD).")

    nu = (form.get("numero_usuario","") or "").strip()
    if not (nu.isdigit() and len(nu)==5):
        errors.append("Número de usuario debe tener 5 dígitos.")

    # reglas de folio según banco/forma
    if form.get("banco")=="BBVA" and form.get("forma_pago")=="Deposito":
        t = form.get("bbva_tipo")
        if t not in ("practicaja","caja"):
            errors.append("Selecciona tipo BBVA (Practicaja o Caja).")
        if t=="practicaja":
            if not (form.get("folio_practicaja","").isdigit() and len(form.get("folio_practicaja"))==4):
                errors.append("Folio practicaja: 4 dígitos.")
            if not (form.get("autorizacion","").isdigit() and len(form.get("autorizacion"))==6):
                errors.append("Autorización: 6 dígitos.")
        elif t=="caja":
            if not form.get("folio_movimiento"):
                errors.append("Folio/Movimiento requerido.")
    else:
        if not form.get("folio_unico"):
            errors.append("Movimiento o folio requerido.")

    try:
        imp = Decimal(form.get("importe","0"))
        if imp <= 0: errors.append("Importe debe ser > 0.")
    except:
        errors.append("Importe inválido.")

    if not has_file:
        errors.append("Comprobante es obligatorio (JPG/PNG/PDF).")

    # lógica de factura:
    req = form.get("requiere_factura") == "on"
    if req and nu.isdigit() and len(nu)==5:
        count = FacturaOpcion.query.filter_by(numero_usuario=int(nu)).count()
        # si HAY opciones y no seleccionó una -> error
        if count>0 and not form.get("factura_opcion_id"):
            errors.append("Selecciona una opción de facturación.")
        # si NO hay opciones -> se ignora en el POST (no error)

    return errors

@bp.get("/")
def home():
    return redirect(url_for("public.registro"))

@bp.route("/registro", methods=["GET","POST"])
def registro():
    if request.method == "POST":
        form = request.form
        file = request.files.get("comprobante")

        errors = _validate(form, has_file=bool(file and file.filename))
        if errors:
            for e in errors: flash(e, "danger")
            return render_template("registro.html", bancos=BANCOS, formas=FORMAS, productos=PRODUCTOS)

        raw = file.read()
        storage = get_storage()
        storage_path = storage.upload(file.filename, raw)

        sha = hashlib.sha256(); sha.update(raw); checksum = sha.hexdigest()
        comp = Comprobante(
            uuid=os.path.splitext(storage_path)[0],
            file_name=file.filename, mime=file.mimetype, size=len(raw),
            checksum_sha256=checksum, storage_path=storage_path, storage_status="operativo"
        )
        db.session.add(comp); db.session.flush()

        # Normalización de factura (ignora si no hay opciones)
        nu_int = int(form["numero_usuario"])
        requiere_factura = (form.get("requiere_factura") == "on")
        factura_opcion_id = int(form["factura_opcion_id"]) if form.get("factura_opcion_id") else None
        if requiere_factura and not factura_opcion_id:
            if FacturaOpcion.query.filter_by(numero_usuario=nu_int).count() == 0:
                requiere_factura = False

        d = Deposito(
            banco=form["banco"],
            forma_pago=form["forma_pago"],
            producto=form["producto"],
            fecha_operacion=datetime.strptime(form["fecha_operacion"], "%Y-%m-%d").date(),
            numero_usuario=nu_int,
            importe=Decimal(form["importe"]),
            observaciones=(form.get("observaciones") or "").strip(),
            requiere_factura=requiere_factura,
            factura_opcion_id=factura_opcion_id if requiere_factura else None,
            comprobante_id=comp.id,
            estatus="registrado"
        )

        if d.banco=="BBVA" and d.forma_pago=="Deposito":
            t = form["bbva_tipo"]; d.bbva_tipo = t
            if t=="practicaja":
                d.folio = form["folio_practicaja"]
                d.autorizacion = form["autorizacion"]
            else:
                d.folio = form["folio_movimiento"]
        else:
            d.referencia = form["folio_unico"]

        db.session.add(d); db.session.commit()
        flash("Registro capturado correctamente.", "success")
        return redirect(url_for("public.registro"))

    return render_template("registro.html", bancos=BANCOS, formas=FORMAS, productos=PRODUCTOS)

@bp.get("/api/opciones_factura")
def api_opciones_factura():
    nu = request.args.get("numero_usuario", "")
    if not (nu.isdigit() and len(nu)==5):
        return jsonify([])
    rows = FacturaOpcion.query.filter(FacturaOpcion.numero_usuario==int(nu)).all()
    return jsonify([{"id":r.id,"titulo":r.titulo,"rfc":r.rfc,"email":r.email} for r in rows])
