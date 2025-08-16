# app/models.py
from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from .extensions import db


# Catálogos para UI (validación de formulario en rutas/servicios)
BANCOS = ["BBVA", "Banorte", "Azteca", "Scotiabank", "Santander"]
FORMAS = ["Deposito", "Transferencia"]
PRODUCTOS = ["TAE", "Pago de servicios"]


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class Comprobante(db.Model, TimestampMixin):
    """
    Archivo del comprobante (imagen/pdf) almacenado en Dropbox.
    - storage_path: nombre/clave con la que se guardó en /comprobantes/ de Dropbox.
    """
    __tablename__ = "comprobantes"

    id = db.Column(db.Integer, primary_key=True)

    # UUID real de Postgres para trazabilidad (no el filename).
    uuid = db.Column(UUID(as_uuid=True), default=uuid4, unique=True, nullable=False)

    file_name = db.Column(db.String(255), nullable=False)
    mime = db.Column(db.String(128), nullable=False)
    size = db.Column(db.Integer, nullable=False)  # bytes
    checksum_sha256 = db.Column(db.String(64), nullable=False)

    storage_path = db.Column(db.String(512), nullable=False)  # p.ej. "e7b2...df3.pdf"
    storage_status = db.Column(db.String(32), default="operativo", nullable=False)

    # Índices
    __table_args__ = (
        Index("idx_comprobantes_created_at", "created_at"),
    )


class FacturaOpcion(db.Model, TimestampMixin):
    """
    Opciones de facturación por número de usuario (5 dígitos).
    """
    __tablename__ = "factura_opciones"

    id = db.Column(db.Integer, primary_key=True)

    # 5 dígitos -> validado en UI; en BD reforzamos con un CHECK 0..99999
    numero_usuario = db.Column(db.Integer, nullable=False, index=True)
    titulo = db.Column(db.String(128), nullable=False)
    rfc = db.Column(db.String(13), nullable=False)
    email = db.Column(db.String(255), nullable=False)

    __table_args__ = (
        CheckConstraint("numero_usuario >= 0 AND numero_usuario <= 99999",
                        name="ck_factura_opciones_numero_usuario_5dig"),
        Index("idx_factura_opciones_created_at", "created_at"),
    )


class Deposito(db.Model, TimestampMixin):
    """
    Registro de depósito/transferencia reportado por el cliente.
    Reglas:
      - Si banco=BBVA y forma=Deposito:
          * bbva_tipo = practicaja => folio(4 díg) + autorizacion(6 díg)
          * bbva_tipo = caja       => folio_movimiento (en 'folio')
      - En otros bancos o Transferencia => 'referencia' único campo.
    """
    __tablename__ = "depositos"

    id = db.Column(db.Integer, primary_key=True)

    # Core
    banco = db.Column(db.String(32), nullable=False)         # de BANCOS
    forma_pago = db.Column(db.String(32), nullable=False)    # de FORMAS
    producto = db.Column(db.String(64), nullable=False)      # de PRODUCTOS
    fecha_operacion = db.Column(db.Date, nullable=False, index=True)

    # Usuario (5 dígitos)
    numero_usuario = db.Column(db.Integer, nullable=False, index=True)
    importe = db.Column(db.Numeric(12, 2), nullable=False)

    # BBVA (solo Depósito)
    bbva_tipo = db.Column(db.String(32))     # "practicaja" | "caja"
    folio = db.Column(db.String(32))         # practicaja/caja
    autorizacion = db.Column(db.String(16))  # 6 dígitos (practicaja)

    # Otros bancos / Transferencia
    referencia = db.Column(db.String(64))

    # Facturación
    requiere_factura = db.Column(db.Boolean, default=False, nullable=False)
    factura_opcion_id = db.Column(
        db.Integer,
        db.ForeignKey("factura_opciones.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    factura_opcion = db.relationship("FacturaOpcion", lazy="joined")

    # Comprobante (obligatorio)
    comprobante_id = db.Column(
        db.Integer,
        db.ForeignKey("comprobantes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    comprobante = db.relationship("Comprobante", lazy="joined")

    # Estado y extras
    estatus = db.Column(db.String(32), default="registrado", nullable=False)
    observaciones = db.Column(db.Text)

    __table_args__ = (
        # 5 dígitos reforzado a nivel BD
        CheckConstraint("numero_usuario >= 0 AND numero_usuario <= 99999",
                        name="ck_depositos_numero_usuario_5dig"),
        # Importe positivo
        CheckConstraint("importe > 0", name="ck_depositos_importe_pos"),
        # Índices compuestos útiles para filtros en admin
        Index("idx_depositos_banco_forma", "banco", "forma_pago"),
        Index("idx_depositos_estado_fecha", "estatus", "fecha_operacion"),
    )
