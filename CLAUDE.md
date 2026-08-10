# StreamIntel: o que um agente precisa saber antes de mexer

Analisa lives da Twitch com IA: captura chat/audio/viewers ao vivo, transcreve
depois, e devolve o que o chat curtiu, o que rendeu dinheiro e onde a audiencia
caiu. `ARCHITECTURE.md` tem o fluxo componente a componente e o `README.md` tem
como rodar. Este arquivo tem o resto: o que ja custou caro descobrir.

## O ambiente e a branch: erre isso e voce olha o lugar errado

| Branch | Ambiente | App |
|---|---|---|
| `main` | https://streamintel.cc | `9154182f-3392-4bfd-b76c-8da53ea52aa9` |
| `dev` | https://dev.streamintel.cc | `3f70eb48-2543-4e97-a9ae-e008317dbbac` |

Fluxo: `feat/* -> PR -> dev -> PR -> main`. **Nunca commite direto em `dev` ou
`main`.** Push na branch deploya sozinho (`deploy_on_push: true`).

**`dev` esta 25+ commits a frente de `main`.** Todo o trabalho de idioma (i18n,
colunas `language`/`spoken_language`, Whisper sem idioma forcado) esta so na
`dev`. Producao roda a migracao **`0019`** e **nao tem essas colunas**.

Consequencia pratica: **o modelo da `dev` nao roda contra o banco de producao**.
`select(Channel)` explode com `column channels.language does not exist`. Para
medir producao, use um worktree da `main`.

## A campanha de email nao esta neste repo, esta em outra branch

`feat/campanha-beta` carrega `scripts/send_campaign_batch.py`,
`scripts/campaign_stats.py`, `scripts/prospect_leads.py` e `.actor/`. Ela nunca
foi para `dev` nem `main` de proposito: nada da campanha roda no produto.

O sender e um **actor do Apify** (`streamintel-campanha`, `QonxRkaUpM4tcPsWs`),
com dois agendamentos: colheita 03:00 diaria e envio 10:00 de segunda a sexta.

## Armadilhas medidas, nao teoricas

**O container do actor pode estar atras do repo, e o numero do build nao conta
isso.** Em 2026-08-09 o actor servia codigo de antes de 05/08, cinco de doze
arquivos atrasados, enquanto rodava todo dia parecendo atual. Sempre compare os
`sourceFiles` do actor com o worktree antes de acreditar que batem.

**Nao existe CLI do Apify nesta maquina.** Publique com
`PUT /v2/acts/{id}/versions/0.1` mandando `{sourceType, sourceFiles}`, e depois
`POST /v2/acts/{id}/builds?version=0.1&tag=latest`. **Omita `envVars` no PUT**:
a leitura devolve segredo como `valueHash`, e reenviar isso da 400. Sem o campo,
as quatro variaveis ficam intactas.

**O modelo responde JSON dentro de uma cerca ```json.** `anthropic/claude-haiku`
faz isso mesmo com `response_format=json_object`. Use sempre
`core.llm.parse_json_object`, nunca `json.loads` cru. Foi assim que producao
passou 25 dias descartando em silencio toda recomendacao de canal, de seguidor e
o follower AI: os tres leitores tinham copia propria de `json.loads`.

**Bloco vazio some da tela.** O front usa `{lista.length > 0 && (...)}` em todo
lugar, entao feature sem dado fica indistinguivel de feature que nao existe. Foi
o que escondeu o problema acima. Ao adicionar bloco novo, escreva o estado vazio.

**`last_event: bounced` do Resend junta coisas diferentes.** Caixa cheia e falha
temporaria voltam iguais a caixa inexistente; so `GET /emails/{id}` traz
`bounce.type` (`Permanent`/`Transient`). Contar tudo junto quase barrou um lote
por causa de uma caixa cheia.

**Um teste parametrizado com lista vazia passa sem testar nada.**
`tests/test_isolation.py` le as rotas do OpenAPI, e nao de `app.routes`, porque
esta versao do FastAPI embrulha os routers incluidos e devolve so os quatro
endpoints de documentacao. A primeira versao do arquivo passava testando zero
rotas. Por isso existe um teste separado so para afirmar quantas rotas a varredura
encontrou.

**Extrair email com regex larga pega lixo.** O padrao
`[A-Za-z0-9.-]+\.[A-Za-z]{2,}` casa `fulano@gmail.com...........EU` inteiro,
porque aceita ponto repetido. Exija rotulos separados por um unico ponto.

## Regra de produto: nenhum usuario ve dado de outro

Vale para a API e tambem para o marketing: nada de "seu canal em destaque no
site", nada de citar quanto outro streamer usa. Toda rota que recebe id responde
**404, nunca 403** (403 ja conta que o id existe e e de outra pessoa).

Cuidado com o padrao que ja vazou: **`Insight` so conhece o `stream_id`**, entao
consulta que filtra so pelo insight alcanca a plataforma inteira. Sempre faca o
join com `Stream` e filtre por `channel_id`. Aconteceu em
`core/follower_signals.py`, e o painel de um streamer citava a live de outro.

`tests/test_isolation.py` e a rede embaixo disso. Rota nova com `{stream_id}`
entra na varredura sozinha.

## Antes de dizer que um numero existe, olhe se a tela mostra

Ter dado no banco nao e ter recurso funcionando. Medido em 2026-08-09:

- "Assuntos que mais monetizam" aparecia para **1 de 7** usuarios na visao geral
  e **1 de 44** lives. A janela de um assunto e "trechos citados + 60s", que
  cobre ~1,5% do tempo no ar, entao o evento de dinheiro cai fora.
- A regra da janela esta escrita **duas vezes** (`apps/api/channel.py` e
  `apps/api/finance.py`). Mudar uma faz as telas discordarem.

## Comandos que economizam tempo

```bash
# Testes precisam de Postgres. Se a porta 5433 estiver ocupada por outro projeto:
docker run -d --name si-test-pg -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app \
  -e POSTGRES_DB=app -p 5434:5432 postgres:16-alpine
FERNET_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())") \
TEST_DATABASE_URL=postgresql+psycopg://app:app@localhost:5434/stream_intel_test \
TEST_ADMIN_DATABASE_URL=postgresql+psycopg://app:app@localhost:5434/app \
  pytest -q
```

`ruff format` **nao** representa o repo: 105 de 165 arquivos mudariam. Siga o
arquivo vizinho (88 colunas), nao o formatador.

`tests/test_api_dashboard.py::test_day_chatters_are_unique_across_lives` falha
entre 00:00 e ~01:30 UTC: ele monta lives de 90 e 30 minutos atras, que caem em
dias diferentes depois da meia-noite. E fragilidade do teste.

## Email do dominio

Envio da campanha e do produto sai pelo **Resend**, do subdominio
`send.streamintel.cc`, nunca do apex: reclamacao de spam em campanha fria nao
pode queimar o dominio do produto.

Desde 2026-08-09 existe a caixa **`henrique@send.streamintel.cc`** de verdade,
com IMAP no droplet `mail.iklobato.com` (docker-mailserver). O MX de
`send.streamintel.cc` aponta para la; o do apex continua no Cloudflare Email
Routing. **`send.send.streamintel.cc` e outro registro**, o return-path de bounce
do Resend: nao mexa nele, e o que alimenta o portao da campanha.

O droplet nao entrega direto (a DigitalOcean bloqueia a porta 25 de saida): ele
relaya pelo Resend, entao **so envia por dominio verificado la**.
