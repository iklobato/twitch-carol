"""channel spoken language (medido pelo Whisper, nao chutado pela Helix)

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-05

A 0020 tratou "idioma do canal" como uma coisa so, e isso estava errado: o
broadcaster_language da Twitch responde "en" para canal brasileiro (medido em
2026-08-05 no canal iklobat, que fala portugues). Como o mesmo campo escolhia a
tela E o idioma passado ao Whisper, o palpite errado nao trocava so o idioma da
interface, ele mandava transcrever audio em portugues como se fosse ingles, o
que devolve texto sem sentido e contamina todo insight construido em cima.

Agora sao dois campos: `language` e a lingua da tela e dos insights, fixada no
cadastro; `spoken_language` e o que a pessoa fala, detectado do proprio audio na
primeira transcricao. Nulo ate a primeira live ser transcrita.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("spoken_language", sa.String(length=8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("channels", "spoken_language")
