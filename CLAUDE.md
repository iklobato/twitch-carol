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

**Medido em 2026-10-25:** `dev` esta 4 commits a frente de `main` (o PR de
release #99 leva os quatro). Producao roda a migracao **`0027`**, a `dev` roda a
**`0028`** (`campaign_clicks` + `channels.signup_ref`). Enquanto o #99 nao entrar,
o modelo da `dev` explode contra o banco de producao em qualquer `select(Channel)`
(`column channels.signup_ref does not exist`): para medir producao, use um
worktree da `main` ou rode SQL cru dentro do container (abaixo).

**O banco de producao so aceita conexao de dentro do app** (trusted sources).
`psql` daqui da timeout. O caminho que funciona, so leitura:

```bash
CMD='python -c "import os,psycopg;c=psycopg.connect(os.environ[\"DATABASE_URL\"].replace(\"postgresql+psycopg\",\"postgresql\"));print(c.execute(\"select version_num from alembic_version\").fetchone())"'
(echo "$CMD"; sleep 20; echo exit) | script -q /dev/null doctl apps console 9154182f-3392-4bfd-b76c-8da53ea52aa9 api
```

O `doctl apps console` exige o **id completo** do app (o prefixo `9154182f` da
`400 invalid uuid`). A saida vem com codigo de terminal no meio: filtre com
`tr -d '\r' | grep -ao 'SEU_MARCADOR.*'`, nao com `grep '^...'`.

**Deploy com live no ar custa audio, nao a live.** Reiniciar o worker de captura
perde ate ~10 min de audio de cada live aberta. A janela vazia medida e 13h-14h
BRT; a madrugada e das piores (3 lives no ar as 00:20 BRT de 2026-10-25). Conte as
lives abertas (`streams` com `ended_at` nulo) antes de soltar um release.

## A campanha de email nao esta neste repo, esta em outra branch

`feat/campanha-beta` carrega `scripts/send_campaign_batch.py`,
`scripts/campaign_stats.py`, `scripts/prospect_leads.py`, `.actor/` e
`publish_actor.py`. Ela nunca foi para `dev` nem `main` de proposito. O trabalho
corrente esta na branch `fix/campaign-gate-en-track` (PR #77, aberto, base
`feat/campanha-beta`); o manual completo da campanha e a secao "Prospeccao e
convite beta" do `README.md` dessa branch.

O sender e um **actor do Apify** (`streamintel-campanha`, `QonxRkaUpM4tcPsWs`).
Agendamentos em `America/Sao_Paulo`: colheita 03:00 todo dia (06:00 UTC) e envio
10:00 de segunda a sexta (13:00 UTC). **Push no git nao deploya o actor**: so o
`publish_actor.py` daquela branch.

**O unico pedaco da campanha que vive neste repo e a medicao do funil.** O link
do email e `/howto?ref=<lote>`. `/howto` grava a visita em `campaign_clicks` e
guarda o lote no cookie `campaign_ref` (30 dias); `/auth/login` grava o clique;
canal **novo** criado no callback recebe `channels.signup_ref`. Canal que ja
existia nunca recebe. Codigo em `core/campaign.py`; ref fora do padrao
`lote-[a-z0-9-]{1,24}` e ignorado; erro de banco ali nunca derruba a pagina nem
o login. Funil por lote:

```sql
select ref,
       count(*) filter (where step = 'howto') as visitas,
       count(*) filter (where step = 'login') as cliques_connect,
       (select count(*) from channels c where c.signup_ref = k.ref) as cadastros
from campaign_clicks k group by ref order by ref;
```

Visita pode vir inflada por antivirus de email que abre link sozinho; clique no
Connect e cadastro nao.

**O login NAO e so leitura.** `core/twitch.py` pede `clips:edit` e o worker de
captura cria clip quando o chat explode (`MAX_CLIPS_PER_STREAM = 10`). Ate
2026-10-25 o email, o `/howto` e a landing diziam "read-only, nunca postamos
nada"; um streamer pegou a diferenca por email. Nenhum texto de venda pode voltar
a dizer "read-only" enquanto o escopo existir.

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

**A conta do Apify e dividida e tem teto.** Teto de US$ 40/mes (era 29 ate
2026-10-25), ciclo do dia 25 ao 24. Quando estoura, todo run morre com
`403 Monthly usage hard limit exceeded` e os agendamentos param sem log nenhum
(foi o que parou a campanha de 17/10 a 24/10). A busca no Google da colheita usa
o proxy `GOOGLE_SERP` direto do `prospect_leads.py`, entao **esse gasto nao
aparece no custo do run**, so em `GET /v2/users/me/usage/monthly`. E o freio
`teto_usd` do actor compara com o gasto da **conta inteira**, nao so da campanha.

**A listagem do Resend so guarda uns 27 dias.** `GET /emails` em 2026-10-25
voltava ate 2026-09-28. Tudo que conta bounce por lote (o portao) so enxerga
lotes recentes. Consequencia lida no codigo: quando o ultimo lote de uma trilha
some da listagem, o portao responde `<lote> nao foi enviado, nao pulo a fila` e
**a trilha trava para sempre** ate alguem mexer na mao.

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

## Estado em 2026-10-25 (data na frente de cada fato: confira antes de confiar)

Feito e provado:
- Medicao do funil da campanha (`campaign_clicks`, `signup_ref`, migracao
  `0028`) e texto sem "read-only" no `/howto` e na landing: PR #100, na `dev`,
  provado em dev.streamintel.cc (visita e clique gravados, linhas de teste
  apagadas). O cadastro so esta coberto por teste automatico, nao por login real.
- Release #99 (`dev` -> `main`, leva o #100 e o log de JSON invalido do LLM)
  agendado para 2026-10-25 13:07 BRT, com contagem de lives antes.

O que falta no produto (nao reconferido desde 2026-09-21):
- Alertas do Grafana nao chegam em ninguem (SMTP nao configurado).
- `/metrics` da API responde 404; so existe uptime externo.
- `clips:edit` e obrigatorio no login; torna-lo opcional e pedido de streamer
  (decisao de produto em aberto).
- Erro de lint antigo: `core/models.py` `UnfollowReason(str, enum.Enum)` (UP042).

Estado da campanha, numeros e proximos passos: secao "Prospeccao e convite beta"
do `README.md` da branch `fix/campaign-gate-en-track`.

