"""quem ja usava nao passa pela tela de cadastro que nasceu depois dele

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-10

A 0022 adiciona `onboarded_at` nulo para todo mundo, e `needs_onboarding` e
exatamente `onboarded_at is None`. No front isso bloqueia o app inteiro
(`App.tsx`: se precisa de onboarding, a unica coisa renderizada e a tela). Sem
este backfill, todo canal que ja existia bate numa pergunta nova no primeiro
acesso depois do deploy, incluindo quem estava no meio do uso.

A pergunta e "em qual idioma voce transmite?", e para esses canais a resposta ja
foi medida, nao chutada: cada canal de producao com fala transcrita mediu
portugues por margem larga (800 a 1800 tokens so-portugues contra 11 a 24
so-ingles). Perguntar de novo o que ja se sabe e atrito puro.

`spoken_language` entra junto e nao e redundante. Hoje `chat_language()` cai em
`language`, que a 0020 preencheu com "pt", entao o lexico ja sairia certo. Mas a
tela de preferencias deixa trocar o idioma da interface, e no dia em que alguem
troca para ingles o chat em portugues passaria a ser lido com o dicionario
errado, devolvendo reacao vazia. Gravar a fala separado da tela e o ponto de ter
duas colunas.

A tela continua valendo para quem se cadastrar a partir daqui, que e o publico em
ingles para quem ela foi feita.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Só quem ainda não respondeu. Rodar de novo não desfaz escolha de ninguém,
    # e um canal que passou pela tela entre o deploy e esta migração fica como
    # ele declarou.
    op.execute(
        sa.text(
            "UPDATE channels "
            "   SET spoken_language = COALESCE(spoken_language, 'pt'), "
            "       onboarded_at = now() "
            " WHERE onboarded_at IS NULL"
        )
    )


def downgrade() -> None:
    """Sem volta de proposito: desfazer marcaria como nao-cadastrado quem de fato
    respondeu a tela depois desta migracao, e nao ha como distinguir um do outro.
    As colunas somem inteiras no downgrade da 0021 e da 0022, que e o caminho
    real de reverter isto."""
