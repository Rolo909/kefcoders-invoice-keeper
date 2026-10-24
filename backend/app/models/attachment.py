import uuid

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.domain.enums import AttachmentKind
from app.models.base import CreatedAtMixin, UuidPkMixin, pg_enum


class Attachment(UuidPkMixin, CreatedAtMixin, Base):
    """Чек (файл) или ссылка, прикреплённые к конкретному периоду."""

    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'file' AND file_path IS NOT NULL AND url IS NULL)"
            " OR (kind = 'link' AND url IS NOT NULL AND file_path IS NULL)",
            name="file_or_link",
        ),
    )

    occurrence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payment_occurrences.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[AttachmentKind] = mapped_column(pg_enum(AttachmentKind, "attachment_kind"))
    url: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(Text)
    original_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(127))
    size: Mapped[int | None] = mapped_column(BigInteger)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
