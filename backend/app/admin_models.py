"""Existing Stage 02 audit and price-history tables (no schema creation)."""
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime

from app.models import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    detail: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StorePriceChange(Base):
    __tablename__ = "store_price_changes"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    store_id: Mapped[int] = mapped_column(BigInteger)
    product_id: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(20))
    recommendation_id: Mapped[int | None] = mapped_column(BigInteger)
    old_price_cents: Mapped[int] = mapped_column(BigInteger)
    new_price_cents: Mapped[int] = mapped_column(BigInteger)
    old_version: Mapped[int] = mapped_column(BigInteger)
    new_version: Mapped[int] = mapped_column(BigInteger)
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
