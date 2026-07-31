"""channel language (idioma do canal, vindo da Helix)

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-30

O idioma do canal decide tres coisas que hoje sao fixas em portugues: o idioma da
tela, o idioma em que o LLM escreve os insights, e qual lexico de sentimento e
qual lista de stopwords a analise de chat usa. Sem esse campo nao ha como atender
streamer de fora do Brasil: a analise devolveria "the" e "you" como assuntos da
live e reacao de chat vazia.

Default 'pt' porque todo canal cadastrado hoje e brasileiro.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column(
            "language",
            sa.String(length=8),
            nullable=False,
            server_default="pt",
        ),
    )


def downgrade() -> None:
    op.drop_column("channels", "language")
