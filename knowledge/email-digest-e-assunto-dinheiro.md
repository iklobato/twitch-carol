# Email semanal (digest) + assunto x dinheiro - estado da sessao 2026-11-08

Versao publica (logins de streamer trocados por "canal A..H", sem email e ids de mensagem).
Snapshot: 2026-11-09 02:20 UTC (2026-11-08 23:20 BRT). Cobre **somente** o que foi feito
nesta sessao:

1. Auditoria do email semanal/mensal (digest): como funciona e se esta funcionando em prod.
2. Envio de 1 email de amostra para o Henry.
3. Descoberta de que "assunto que mais deu dinheiro" quase nunca aparece, medicao da causa.
4. Conserto em 2 PRs (#104 e #105), mergeados em `dev`, rodando no app de dev.
   **Nada disso esta em producao (`main`) ainda.**

Leitor alvo: qualquer agente que pegue este trabalho depois. Todo numero abaixo foi medido
nesta sessao, com o comando e a saida real; o que nao foi verificado esta dito.

---

## 1. Resumo rapido

| Item | Estado em 2026-11-09 02:20 UTC |
|---|---|
| Email semanal/mensal em prod | LIGADO desde 2026-10-06, funcionando sozinho |
| Envios em prod | 28 (21 semanais + 7 mensais) para 6 canais; 26/26 conferidos `delivered` no Resend |
| Assunto x dinheiro (antes) | so 1,3% do dinheiro de outubro caia em algum assunto |
| PR #104 (dinheiro vai pro assunto mais perto) | MERGEADO em `dev` (8e9bc2d), deploy dev ACTIVE, provado no dev: 0,6% -> 69,6% |
| PR #105 (assunto cobre a live por blocos de 15 min) | MERGEADO em `dev` (0b1b222), deploy dev ACTIVE, **nao provado com IA real** |
| Producao | sem #104 e sem #105 ate o release `dev` -> `main` |

---

## 2. Email semanal/mensal (digest)

### 2.1 Como funciona (codigo em `main`/`dev`)

Fluxo, na ordem:

1. **Job** `send-digests` no app de prod (`deploy/app.yaml`, bloco `name: send-digests`):
   `kind: SCHEDULED`, cron `0 * * * *` UTC, roda `python scripts/send_email_digests.py`.
2. **Quem recebe** (`scripts/send_email_digests.py::_eligible_channels`): canal com
   `digest_weekly`/`digest_monthly = true` (default true, `core/models.py`) **e** `channels.email`
   preenchido. O email vem do login Twitch (escopo `user:read:email`).
3. **Quando** (`_due_now`): quando o relogio LOCAL do canal (`channels.timezone`) passa de
   `settings.digest_send_hour` (8). E `>=`, nao `==`: run atrasado ainda envia.
   - semanal: semana completa segunda->segunda no fuso do canal (`core/digest.py::last_week_bounds`)
   - mensal: mes anterior completo (`last_month_bounds`)
4. **Sem duplicata**: insere linha em `email_digest_log` ANTES de enviar (unique
   `channel_id, period, period_start`). `MailerError` = nao enviou, apaga a reserva e tenta na
   proxima hora. `MailerUncertain` (timeout) = mantem a reserva, nao tenta de novo.
5. **Conteudo** (`core/digest.py::build_period`, 100% SQL, zero LLM): totais vs periodo
   anterior, lives, melhores momentos, temas recorrentes, recordes, clips, dinheiro por assunto,
   top lives, sentimento, quem mais engajou/pagou, mapa de calor diario, churn de sub, reward.
   **So conta lives com `status = ready`** (`_period_streams`).
6. **Dicas keep/stop/improve** (`core/digest_insights.py`): LLM, cada dica cita um fato
   numerado, sem fato = descartada. LLM falhou = email sai sem dicas.
7. **Envio** (`core/mailer.py`): Resend, `From` = `DIGEST_FROM`
   (`StreamIntel <digest@notify.streamintel.cc>`), header `List-Unsubscribe` + one-click.
8. **Descadastro** (`apps/api/digest.py`): GET so mostra botao, POST desliga (scanners de email
   abrem links). Toggles tambem na tela do canal (`DigestSettings`).
9. Idioma = `channels.language` (idioma da tela), decisao do Henry de 2026-10-06.

### 2.2 Prova de que funciona em prod (medido 2026-11-09 ~00:30 UTC)

Job (DO API):
```
curl -s -H "Authorization: Bearer $(doctl auth token)" \
  "https://api.digitalocean.com/v2/apps/<app prod>/job-invocations?job_names=send-digests&per_page=200"
count 101 ... Counter({'SUCCEEDED': 101})
26ec915d SUCCEEDED 2026-11-09T00:03:19Z ...
```

Banco de prod (`email_digest_log`, 28 linhas, todas com `sent_at` e id do Resend):
```
(1, 'canal A', 'weekly', 2026-09-28, sent 2026-10-06 13:04 ...)
...
(28, 'canal B', 'weekly', 2026-11-01, sent 2026-11-08 23:03, '<id resend>')
CH [(28, 7, 28, 7)]   -> 28 canais, 7 com email, 28 com semanal ligado, 7 com email+semanal
```

Resend (paginando `GET /emails?limit=100&after=<id>`; a lista so volta ate 2026-10-11):
```
scanned 2301 oldest 2026-10-11 digest 26
Counter({'delivered': 26})
```

Envios por canal:

| Canal | Idioma | Semanais | Mensais | Total |
|---|---|---|---|---|
| canal A | pt | 5 | 2 | 7 |
| canal B | en | 5 | 1 | 6 |
| canal C | en | 4 | 1 | 5 |
| canal D | en | 3 | 1 | 4 |
| canal E | en | 3 | 1 | 4 |
| canal F | en | 1 | 1 | 2 |

### 2.3 Achados do digest (nao consertados, ninguem pediu ainda)

- **21 de 28 canais sem email** -> nunca recebem. Causa nao investigada.
- `iklobat` (canal do Henry) tem email mas 0 lives -> nunca recebe (`skipped (no lives)`).
- `canal A` fala pt mas esta com `timezone = UTC` -> recebe 05:00 BRT. Nao confirmado onde mora.
- `canal A`: 6 lives nos ultimos 7 dias, digest conta so 2 (so `ready`). As outras 4 nao foram
  investigadas (falha? processando?).
- Sem metrica de abertura/clique: nada consome webhooks do Resend.

### 2.4 Email de amostra enviado ao Henry

- 2026-11-09 01:11 UTC, para o email do Henry, assunto
  `[AMOSTRA] Seu resumo semanal do StreamIntel`, 
  `delivered`. Dados reais de prod do `canal A`, semana 02/11-09/11, pt, 2 lives, 5 dicas.
- Link de descadastro trocado por `<base>/#amostra-sem-descadastro` (clicar nao desliga ninguem).
- **NAO usar `scripts/send_email_digests.py --to` para amostra**: ele grava a reserva em
  `email_digest_log` para o canal real, e o streamer deixa de receber o envio de verdade daquela
  semana. A amostra foi montada no container chamando `build_last_period` + `with_insights` +
  `render_html` + `send_email` direto, com `db.rollback()` no fim.

---

## 3. Assunto x dinheiro (o problema principal desta sessao)

### 3.1 Pergunta e resposta curta

Pergunta: o streamer consegue ver qual assunto (da transcricao) deu mais dinheiro e mais
engajamento? Resposta antes do conserto: o codigo existe em 4 lugares (pagina da live, pagina
do canal, email, follows por assunto), mas na pratica quase sempre vazio.

### 3.2 Medicao de outubro em prod (antes do conserto)

Mes de outubro no fuso de cada canal, so leitura, 22 canais com live:
```
lives 359 | live_h 1930.2 | transcr_h 1523.0 | topics 616 | topic_win_h 20.5
money_ev 1903 | usd 6858.02 | in_win 87.5 | pad5 219.0 | pad15 299.0
in_win % 1.28 | pad15 % 4.36 | cover % 1.06 | transcr % 78.9 | sem assunto % 39.3
```
- Janela dos assuntos cobre 1,06% do tempo de live; dinheiro dentro: 1,3%.
- Aumentar a folga nao resolve (+15 min = 4,4%): o dinheiro fora esta a HORAS da janela
  (mediana canal B 126 min, canal C 463, canal G 1123).
- 39% do dinheiro (2.692 USD) esta em lives sem nenhuma janela de assunto.
- Rebuild dos 12 digests (6 que recebem, mensal out + semanal 26/10): so 3 com assunto+dinheiro,
  semanal 0 de 6. Secao some do email quando vazia, entao ninguem percebia.

### 3.3 As duas causas

1. **Janela minuscula**: janela = do 1o ao ultimo trecho de fala CITADO pelo insight TOPIC,
   +-60 s (`TOPIC_WINDOW_PADDING`). A IA cita poucos trechos -> 2-3 min numa live de horas.
   O codigo da janela estava copiado em 5 lugares (`apps/api/channel.py`, `apps/api/finance.py`,
   `apps/api/dashboard.py` x2, `core/follower_signals.py`).
2. **So os 12 primeiros trechos eram citaveis**: `workers/analyze/pipeline.py::_evidence_segment_context`
   fazia `.order_by(started_at).limit(EVIDENCE_SEGMENT_SAMPLE)` (12). Todo assunto so podia
   citar a abertura da live -> assuntos genericos tipo "Stream Greetings and Chat Interaction".

### 3.4 Decisao do Henry (AskUserQuestion, 2026-11-08)

- Fazer A (assunto cobre a live por blocos) **e** B (dinheiro vai pro assunto mais perto).
- B primeiro, num PR so; A num 2o PR.
- Follows por assunto **ficam fora** do "mais perto" (so contam dentro do assunto).
- Medir (so estimar) custo de reprocessar outubro.

### 3.5 PR #104 - B: dinheiro vai pro assunto mais perto

https://github.com/iklobato/twitch-carol/pull/104 - mergeado em `dev` 2026-11-09 01:55 UTC, commit `8e9bc2d`.

- Nova classe unica em `core/topics.py`: `TopicWindowReader(db).timeline(stream_ids)` ->
  `TopicTimeline`; `TopicTimeline.topic_at(stream_id, moment)` = assunto onde o momento cai,
  senao o mais perto da MESMA live; `None` so se a live nao tem assunto.
- Cada evento conta para 1 assunto so; sobreposicao -> o de melhor rank (antes contava 2x).
  Rank = ordem de `Insight.id` (gravados em ordem de rank em `_store_topics`).
- Usado por: dinheiro e mensagens do email (`core/digest.py`: `_topic_moments`,
  `_topic_message_counts`, `_topic_revenue`), `top_monetizing_topics` do canal
  (`apps/api/channel.py::_topic_revenue`), `by_topic` e `top_moments[].topic` da live
  (`apps/api/finance.py::stream_finance`).
- Removido: `_topic_windows_by_stream` (channel.py), `_topic_windows` (finance.py).
- Testes: `tests/test_topic_attribution.py` (6 testes, 5 falhavam antes);
  `tests/test_digest.py`: mensagens fora do unico assunto agora contam (3 -> 5).

### 3.6 PR #105 - A: assunto cobre a live pelos blocos de 15 min

https://github.com/iklobato/twitch-carol/pull/105 - mergeado em `dev` 2026-11-09 02:15 UTC, commit `0b1b222`.

- `workers/analyze/topic_blocks.py` (novo): `BlockSummary` (numero, inicio, fim, texto),
  `ShownBlocks.in_prompt` (so blocos cujo rotulo sobreviveu ao corte de budget do prompt),
  `TopicBlockClaims` (cada bloco pra 1 assunto, em ordem de rank; numero nao mostrado = descartado).
- `workers/analyze/pipeline.py`:
  - `_summarize_blocks` agora devolve `list[BlockSummary]` (numero = posicao na live, mantem
    buraco se um bloco foi pulado).
  - prompt de topicos mostra `B3 [10:30-10:45 UTC]: <resumo>` e pede `"block_ids"` por assunto,
    "give every block to the one topic it is mostly about".
  - `_store_topics` grava `evidence["blocks"] = [{"start": iso, "end": iso}, ...]` (sem migration);
    bloco so e reclamado depois que o assunto passou na validacao.
  - `_evidence_segment_context`: 12 trechos espalhados pela live (`SpreadSample` em
    `workers/analyze/evidence.py`). Afeta tambem o resumo geral (mesma funcao).
- `core/topics.py`: `TopicWindow` agora tem `insight_id` e `spans` (varios pedacos). Le
  `evidence["blocks"]`; sem blocos (lives antigas) usa trechos citados +-60 s.
  Metodos novos: `windows_of`, `every_window`, `window_for`.
- Migrados para a classe unica: barra de engajamento (`dashboard.py::_topic_engagement`),
  detalhe do assunto (`dashboard.py::topic_detail`, filtro `or_` por span), follows por assunto
  (`core/follower_signals.py::topic_to_follows`, so dentro).
- Testes: `tests/test_topic_blocks.py` (8 testes, todos falhavam antes).

### 3.7 Verificacao no app de dev (deploys `3c6c0500` e `5f2d3856`, ambos ACTIVE, healthz 200)

Banco do dev = so `iklobat`, 85 lives (julho-agosto 2026).
Depois do #104:
```
DV iklobat lives 85 lives_com_topico 68 money_ev 257 usd 781.84 dentro 5.0 creditado 543.84
DG iklobat 2026-08-02 lives 61 [('Marvel Rivals - Gameplay e Mecânica', 170.0, 1726), ('Vida Pessoal e Rotina', 60.0, 2467), ('Interação com Chat', 47.5, 5072)]
DG iklobat 2026-09-02 lives 24 [('Interações descontraídas com chat e', 35.0, 1770), ...]
```
Depois do #105:
```
EV iklobat usd 781.84 creditado 543.84 topicos_com_blocos 0
```
- 0,6% -> 69,6% do dinheiro ligado a assunto; os 238 USD restantes estao em 17 lives sem assunto.
- #105 nao mudou lives antigas (esperado). **Blocos ainda nao provados com IA real**: nenhuma
  live foi analisada no dev depois do deploy.
- Efeito colateral visivel: "Interação com Chat" pega 5.072 mensagens (o "mais perto" numa
  live com poucos assuntos joga quase tudo nele). O #105 resolve isso so em lives novas.

### 3.8 Custo de reprocessar outubro (so estimado, nada rodado)

```
TOK [(336 lives, in 10.635.780, out 993.091, haiku in 8.902.362, haiku out 774.756, avg in 31654, max in 88488, 1903.4 h, 21 lives >= 85k)]
NOINS [(20,)]   -> 20 lives de outubro sem nenhum insight
anthropic/claude-haiku-4.5   in/M 1.0  out/M 5.0     (OpenRouter /api/v1/models, 2026-11-09)
anthropic/claude-sonnet-4.6  in/M 3.0  out/M 15.0
```
- ~21 USD (Haiku ~12,80 + Sonnet ~8,50) para 336 lives. **E piso**: `tokens_in/out` e gravado
  no insert do insight; gasto depois do ultimo insert nao entra.
- Reprocessar = `run_analysis` APAGA todos os insights da live (inclusive o feedback que o
  streamer deu) e refaz recomendacoes.
- 21 lives batem perto do teto de 90k tokens de input (lives longas ja sao cortadas).

---

## 4. Proximos passos (em ordem)

1. [ ] **Provar o #105 com IA real no dev**: rodar `run_analysis` em 1 live do `iklobat`
       (~0,06 USD; apaga e recria os insights dessa live no dev). Conferir: quantos blocos
       ganharam assunto, se os assuntos deixaram de ser "saudacao", se o prompt coube.
       Oferecido ao Henry, **sem resposta ainda**.
2. [ ] Release `dev` -> `main` (decisao do Henry; deploy em prod so com OK dele).
3. [ ] Depois do release: repetir a medicao de outubro (secao 6.1) e medir novembro. So entao
       dizer que melhorou em prod.
4. [ ] Decidir reprocessamento das lives antigas (custo 3.8; perde feedback). Nao decidido.
5. [ ] Itens do digest em aberto (secao 2.3), nenhum pedido ainda.

## 5. O que monitorar

- **Job do digest**: `job-invocations?job_names=send-digests` deve ser 100% `SUCCEEDED`, 1 por hora.
- **Entrega**: novas linhas em `email_digest_log` com `sent_at`; conferir `last_event` no Resend
  (`GET https://api.resend.com/emails/<id>`, chave em `/Users/iklo/twitch/.env`, nao em `~/.claude/.env`).
- **Segunda 2026-11-09**: semanal de canal A (08:00 UTC), canal D, canal E,
  canal C, canal F (08:00 local de cada um).
- **Depois do release**: % do dinheiro em assunto (script 6.1). Esperado: perto de 100% nas
  lives que tem assunto; lives sem assunto continuam fora.
- **Lives novas analisadas depois do #105**: contar topicos com `evidence->'blocks'`; se 0,
  a IA nao esta devolvendo `block_ids` (ver resposta crua no log do worker-analyze).
- **Custo de IA** por live depois do #105 (prompt de topicos ficou um pouco maior).
- **Lives longas**: blocos cortados pelo budget do prompt (`TOPICS_PROMPT_INPUT_CAP` 3000)
  ficam sem assunto e caem no "mais perto".

## 6. Como reproduzir as medicoes

Rodar comando no container (o pty quebra com pipe; a 1a linha de saida vem colada em escape,
extrair com `grep -ao`):
```
(cat cmds.txt; sleep 60; echo exit) | timeout 110 script -q /dev/null doctl apps console <app-id> api > out.txt 2>&1
grep -ao "PREFIXO .*" out.txt | tr -d '\r'
```
`cmds.txt` = um heredoc `cat > /tmp/x.py <<'EOF' ... EOF`, depois `python /tmp/x.py; rm /tmp/x.py`.
Apps: prod `<app prod>`, dev `<app dev>` (`doctl apps list`).

### 6.1 % do dinheiro em assunto (codigo atual, depois do #104)
```python
from sqlalchemy import select
from core.db import session_factory
from core.models import Channel, Stream, StreamStatus, Event
from core.finance import MONEY_EVENT_TYPES, event_usd
from core.topics import TopicWindowReader
db = session_factory()()
for ch in db.scalars(select(Channel)).all():
    ids = list(db.scalars(select(Stream.id).where(Stream.channel_id == ch.id, Stream.status == StreamStatus.READY)))
    ev = db.scalars(select(Event).where(Event.stream_id.in_(ids), Event.type.in_(MONEY_EVENT_TYPES))).all() if ids else []
    tl = TopicWindowReader(db).timeline(ids)
    credited = sum(event_usd(e) for e in ev if tl.topic_at(e.stream_id, e.occurred_at))
    print("EV", ch.login, round(sum(event_usd(e) for e in ev), 2), round(credited, 2))
db.rollback()
```
Para um mes so, filtrar `Stream.started_at` pelos limites de
`core.digest.last_period_bounds(DigestPeriod.MONTHLY, now, channel_zone(ch))`.

### 6.2 Topicos com blocos (prova do #105)
```sql
select count(*) filter (where i.evidence ? 'blocks'), count(*)
from insights i join streams s on s.id = i.stream_id
where i.type = 'topic' and s.started_at >= '<data do deploy>';
```

## 7. Armadilhas encontradas nesta sessao

- `streams.status` no banco e minusculo (`'ready'`), nao `'READY'`.
- `TopicTimeline.windows_of` so existe a partir do #105; no #104 usar `windows_by_stream.get(...)`.
- Lista do Resend (`GET /emails`) so volta ~1 mes (ate 2026-10-11 nesta medicao); emails mais
  velhos so por id.
- `gh pr edit --base` falha com erro de "Projects (classic)"; trocar base via
  `gh api -X PATCH repos/iklobato/twitch-carol/pulls/<n> -f base=dev`.
- Testes locais: `uv run` no worktree quebra (onnxruntime sem wheel para Python 3.13); usar
  `/Users/iklo/twitch/.venv/bin/python -m pytest` e subir o postgres de teste com
  `docker compose -f deploy/docker-compose.yml up -d postgres` (porta 5433).
- Hooks do Henry: regras imutaveis valem tambem em testes (sem numero solto, funcao <= 20
  linhas, sem lista mutavel em modulo); o lint apaga import nao usado ao salvar, entao escrever
  o uso primeiro e o import por ultimo. Nao rodar `ruff format`: nesta sessao `--check` marcou
  5 arquivos tocados para reformatar por inteiro (linhas que ninguem mexeu), e a memoria do
  projeto ja proibe.
- Merge em `dev` dispara deploy automatico do app de dev (`deploy_on_push: true`, build ~8 min).
- Erros pre-existentes, nao confundir com regressao: 12 erros de `mypy` em 4 arquivos e
  1 `ruff` `UP042` em `core/models.py`.

## 8. Onde esta cada coisa

- Worktree usado: `/Users/iklo/twitch-worktrees/topic-timeline` (branch `feat/topic-blocks`,
  ja mergeada). Branches `fix/topic-money-nearest` e `feat/topic-blocks` continuam no GitHub.
- PRs: https://github.com/iklobato/twitch-carol/pull/104 , https://github.com/iklobato/twitch-carol/pull/105
- Memorias do agente: `streamintel-email-digest.md`, `streamintel-assunto-dinheiro-janela.md`
  em `~/.claude/projects/-Users-iklo-twitch/memory/`.
