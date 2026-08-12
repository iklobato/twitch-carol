"""channel onboarding (o idioma da live passa a ser declarado, nao adivinhado)

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-05

A 0021 media o idioma da fala pelo Whisper, o que ja era melhor que o palpite da
Helix, mas ainda era inferencia. Agora a pessoa declara na entrada e a deteccao
vira conferencia.

Coluna propria em vez de reusar `spoken_language IS NULL` como marca: nulo ali
significa "ainda nao detectei", nao "ainda nao perguntei". Os canais que ja
existem estao exatamente nesse estado, e se um deles transmitir antes do proximo
login, o Whisper preencheria o campo e a tela nunca apareceria para ele.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("channels", "onboarded_at")
