"""add password reset challenges, authorizations, and session versioning

Revision ID: i3c4d5e6f7a8
Revises: h2b3c4d5e6f7
Create Date: 2026-07-13 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "i3c4d5e6f7a8"
down_revision = "h2b3c4d5e6f7"
branch_labels = None
depends_on = None


STATUS_VALUES = ("PENDING", "VERIFIED", "CONSUMED", "EXPIRED", "LOCKED", "CANCELLED")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "auth_version" not in {
        column["name"] for column in inspector.get_columns("sellers")
    }:
        op.add_column(
            "sellers",
            sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"),
        )

    # Create the named type explicitly so repeated deploys do not race with
    # SQLAlchemy's table-level enum creation hook.
    status_enum = postgresql.ENUM(
        *STATUS_VALUES,
        name="password_reset_challenge_status",
        create_type=False,
    )
    if bind.dialect.name == "postgresql":
        status_enum.create(bind, checkfirst=True)

    if "password_reset_challenges" not in inspector.get_table_names():
        op.create_table(
            "password_reset_challenges",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("email_normalized", sa.String(length=255), nullable=False),
            sa.Column("code_hash", sa.String(length=64), nullable=False),
            sa.Column("status", status_enum, nullable=False),
            sa.Column(
                "attempt_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("request_ip_hash", sa.String(length=64), nullable=True),
            sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint(
                "attempt_count >= 0", name="ck_password_reset_attempt_count_nonnegative"
            ),
            sa.CheckConstraint(
                "max_attempts > 0", name="ck_password_reset_max_attempts_positive"
            ),
        )
        op.create_index(
            "ix_password_reset_challenges_email",
            "password_reset_challenges",
            ["email_normalized"],
        )
        op.create_index(
            "ix_password_reset_challenges_seller_status",
            "password_reset_challenges",
            ["seller_id", "status"],
        )
        op.create_index(
            "ix_password_reset_challenges_expires_at",
            "password_reset_challenges",
            ["expires_at"],
        )
        if bind.dialect.name == "postgresql":
            op.create_index(
                "uq_password_reset_active_challenge",
                "password_reset_challenges",
                ["seller_id", "email_normalized"],
                unique=True,
                postgresql_where=sa.text("status IN ('PENDING', 'VERIFIED')"),
            )

    if "password_reset_authorizations" not in inspector.get_table_names():
        op.create_table(
            "password_reset_authorizations",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("challenge_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["challenge_id"], ["password_reset_challenges.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "token_hash", name="uq_password_reset_authorization_token_hash"
            ),
        )
        op.create_index(
            "ix_password_reset_authorizations_seller",
            "password_reset_authorizations",
            ["seller_id"],
        )
        op.create_index(
            "ix_password_reset_authorizations_expires_at",
            "password_reset_authorizations",
            ["expires_at"],
        )

    if "security_audit_events" not in inspector.get_table_names():
        op.create_table(
            "security_audit_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("email_hash", sa.String(length=64), nullable=True),
            sa.Column("request_ip_hash", sa.String(length=64), nullable=True),
            sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_security_audit_events_seller_created",
            "security_audit_events",
            ["seller_id", "created_at"],
        )
        op.create_index(
            "ix_security_audit_events_type_created",
            "security_audit_events",
            ["event_type", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "security_audit_events" in inspector.get_table_names():
        op.drop_index(
            "ix_security_audit_events_type_created", table_name="security_audit_events"
        )
        op.drop_index(
            "ix_security_audit_events_seller_created",
            table_name="security_audit_events",
        )
        op.drop_table("security_audit_events")

    if "password_reset_authorizations" in inspector.get_table_names():
        op.drop_index(
            "ix_password_reset_authorizations_expires_at",
            table_name="password_reset_authorizations",
        )
        op.drop_index(
            "ix_password_reset_authorizations_seller",
            table_name="password_reset_authorizations",
        )
        op.drop_table("password_reset_authorizations")

    if "password_reset_challenges" in inspector.get_table_names():
        if bind.dialect.name == "postgresql":
            op.drop_index(
                "uq_password_reset_active_challenge",
                table_name="password_reset_challenges",
            )
        op.drop_index(
            "ix_password_reset_challenges_expires_at",
            table_name="password_reset_challenges",
        )
        op.drop_index(
            "ix_password_reset_challenges_seller_status",
            table_name="password_reset_challenges",
        )
        op.drop_index(
            "ix_password_reset_challenges_email", table_name="password_reset_challenges"
        )
        op.drop_table("password_reset_challenges")

    if bind.dialect.name == "postgresql":
        sa.Enum(*STATUS_VALUES, name="password_reset_challenge_status").drop(
            bind, checkfirst=True
        )

    if "auth_version" in {
        column["name"] for column in inspector.get_columns("sellers")
    }:
        op.drop_column("sellers", "auth_version")
