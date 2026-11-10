# Captura redundante (worker standby) - estado da sessao 2026-11-10

Snapshot: 2026-11-10 16:23 UTC (13:23 BRT). Cobre **somente** o que foi feito nesta sessao para
"nao perder nenhuma live": um segundo consumidor de captura, separado do oficial, que grava as
mesmas lives para o oficial poder ficar fora do ar (deploy, crash) sem perda.

Leitor alvo: qualquer agente que continue este trabalho. Numeros medidos nesta sessao; o que nao
foi verificado esta na secao 9. Incidente de transcricao achado no ensaio: ver
`knowledge/incidente-transcricao-2026-11.md`.

---

## 1. Resumo rapido

| Item | Estado em 2026-11-10 16:23 UTC |
|---|---|
| PR A: duplicata segura + audio que nao se sobrescreve | https://github.com/iklobato/twitch-carol/pull/111 MERGEADO em `dev` (64dfe95) |
| PR B: Helix abre live quando o webhook stream.online se perde | https://github.com/iklobato/twitch-carol/pull/112 MERGEADO em `dev` (850a1d8) |
| App standby na DEV | `streamintel-dev-capture-standby`, id `34944dd8-b16c-489d-80eb-04dd8b46514b`, ACTIVE desde 11:26 UTC |
| Ensaio com live real na dev | feito 11:46-12:12 UTC: captura, chat, viewers, clips e parada do oficial OK; transcricao NAO conferida (ver 6) |
| Producao (`main`, 0898765) | **sem #111 e #112**, um unico worker de captura, sem standby |
| App standby de producao | NAO criado |

---

## 2. O pedido e as decisoes do Henry

Pedido (2026-11-10): "consumer adicional detached para capturar as lives mesmo que duplicado,
de forma conseguirmos ter downtime no consumer oficial".

| Pergunta | Decisao |
|---|---|
| Onde roda o standby | app separado no App Platform (um deploy do app oficial nao o reinicia) |
| Escopo | PR A + PR B + Infra C (app standby) |
| Secrets do app novo | copiar do container da dev direto para arquivo 600, apagado depois |
| Ensaio sem live do Henry | live publica de terceiro na dev, dados apagados no fim |

---

## 3. Por que nao bastava subir um segundo worker (achados no codigo)

Lido em `origin/dev` 0b1b222 antes de mudar:

1. **Restart no meio da live sobrescrevia audio.** O ffmpeg numerava `000.ogg`, `001.ogg`... por
   processo e o upload usava `audio/{canal}/{live}/{seq:03d}.ogg`. Um restart (todo deploy com live
   no ar) subia um `000.ogg` novo por cima do antigo, e a transcricao calculava o horario como
   `seq x 600s`, entao o trecho ficava no horario errado. Bug real em producao hoje.
2. Chat sem indice unico em `message_id`: 2 workers = 2 linhas por mensagem.
3. Viewer samples sem trava: 2 por minuto.
4. Fechamento da live (`_finalize`) le-e-grava sem condicao: 2 transcricoes enfileiradas.
5. Clips: os 2 criariam clip no canal real do streamer.
6. A live so comecava pelo webhook `stream.online` (`apps/api/eventsub.py`): API fora = live perdida
   para qualquer numero de workers.
7. `worker-capture` de producao fica no mesmo app que api e workers: um segundo worker no mesmo app
   reinicia junto em todo deploy.

Medido em producao (so leitura, 2026-11-10): 7 linhas de chat duplicadas (lives 39-44, incidente de
2026-07-16), 17 minutos com 2 viewer samples (julho), chat 400 MB em 6 particoes, no maximo 1 live
aberta por canal.

---

## 4. O que esta no codigo (`dev`)

### 4.1 PR A (#111)
- `core/models.py`: indice unico `uq_chat_messages_message_sent (message_id, sent_at)` e
  `uq_viewer_samples_stream_sampled (stream_id, sampled_at)`.
- `workers/capture/collectors.py`: chat e viewer gravam com `INSERT ... ON CONFLICT DO NOTHING`;
  `sampled_at` cortado no minuto; metodos `ingest`, `flush`, `sample_once` agora publicos.
- `workers/capture/session.py`: `_claim` faz `UPDATE ... WHERE status='capturing'`; so quem muda o
  status enfileira a transcricao. `CaptureSession.for_live(stream, channel)` monta a sessao.
- `core/config.py`: `CaptureRole` (`primary`/`standby`), env `CAPTURE_ROLE`, padrao `primary`.
- `workers/capture/clip_detector.py`: `SpikeDetectorFactory().for_role(role)`; standby recebe
  `NeverClipDetector`.
- `workers/capture/live_sessions.py` (`LiveSessions`): para a sessao quando a live sai da lista
  `capturing`, inclusive quando o OUTRO worker a finalizou. Bug achado rodando 2 workers juntos:
  sem isso o mais lento ficava no IRC do canal para sempre.
- Audio: ffmpeg com `-segment_atclocktime 1 -strftime 1`, arquivo `%s.ogg` (inicio em epoch);
  chave `audio/{canal}/{live}/{epoch}-{role}.ogg` (`core/storage.py:audio_key`).
- `workers/transcribe/segments.py`: `SegmentNameParser` (nome novo = epoch; nome antigo `NNN.ogg` =
  seq x 600) e `AudioCoverage` (le os arquivos em ordem de inicio e guarda so os segundos ainda nao
  cobertos). Cada segundo gravado entra uma vez, venha do primary, do standby ou de um restart.
- Migration `0029`: apaga as 7 duplicatas de chat (mantem a linha cuja live contem o horario),
  cria o indice do chat particao por particao com `CREATE INDEX CONCURRENTLY` + `ATTACH`, cria o
  indice de viewers concorrente e remove o antigo `ix_viewer_samples_stream_sampled`.

### 4.2 PR B (#112)
- `core/twitch.py`: `HelixLiveStreams.live(user_ids)`, Get Streams em lotes de 100 (app token).
- `workers/capture/missed_lives.py` (`MissedLiveFinder`): a cada 60s abre a live de canal no ar sem
  linha; ignora live que ja tem linha com inicio a ate 2 min do inicio da Helix.
- `core/streams.py`: `start_stream` com `ON CONFLICT DO NOTHING` no indice parcial e le de volta a
  linha vencedora.
- Migration `0030`: `uq_streams_one_open_per_channel` (`channel_id` WHERE `status='capturing' AND
  ended_at IS NULL`), concorrente.

---

## 5. Infra na dev

- App standby: `streamintel-dev-capture-standby` (`34944dd8-b16c-489d-80eb-04dd8b46514b`),
  componente `worker-capture-standby`, `apps-s-1vcpu-0.5gb`, branch `dev`, **`deploy_on_push:
  false`**: para atualizar, `doctl apps create-deployment 34944dd8-b16c-489d-80eb-04dd8b46514b`.
- Envs: `CAPTURE_ROLE=standby` + DATABASE_URL, FERNET_KEY, TWITCH_CLIENT_ID/SECRET, SPACES_* (5),
  DB_DISABLE_PREPARED_STATEMENTS, AUDIO_RETENTION_DAYS, SENTRY_ENVIRONMENT.
- Papel conferido dentro dos containers: standby = `standby`, `worker-capture` da dev = `primary`.
- Firewall do Postgres compartilhado (cluster `9ef05287-e724-4f61-afd1-616f88cbdf64`): adicionada
  regra `app:34944dd8...` (eram 10 regras, ficaram 11).
- GOTCHA: a DigitalOcean recusa criar app com secret criptografado de outro app:
  `secret env value must not be encrypted before app is created`. O `EV[...]` de um app nao serve
  para outro; foi preciso o valor em texto (copiado do container `worker-capture` da dev para um
  arquivo 600, app criado, arquivo apagado, nada impresso).

---

## 6. Ensaio com live real (dev, 2026-11-10)

Sem live do Henry: canal publico de terceiro **japabigodin** (no ar desde 03:32 UTC, ~3.700
viewers) cadastrado na dev como channel id 9, sem token (ninguem cria clip nem escreve no canal).

| Passo | Resultado medido |
|---|---|
| PR B: sem webhook, a Helix abre a live | 11:47:00 primary loga `live opened from Helix (stream.online webhook missed)`; standby comeca no mesmo segundo; 1 linha so (live 123) |
| Derrubar o oficial | `doctl apps restart 3f70eb48... --components worker-capture` as 11:55:08; voltou 11:56:05 e retomou a mesma live |
| Encerrar a live | `mark_stream_offline` as 12:12:08 (como o webhook faria) |
| Fechamento | primary enfileirou 1 transcricao; standby logou `live already finalized by another capture worker` |
| Chat | 215 linhas, 215 ids distintos, 0 duplicatas; o chat nao parou no minuto 11:55 (28 mensagens) com o oficial fora a partir de 11:55:08 |
| Viewers | 26 amostras em 26 minutos distintos |
| Clips | 0 |
| Audio | 8 arquivos: `...225-standby`, `...226-primary`, `...404-standby` (janela 11:50-12:00 inteira so do standby: o arquivo do primary se perdeu no restart), `...772-primary` (restart), `...2000/2004`, `...2600/2604` |
| Transcricao | **FALHOU** com `TypeError: open() got an unexpected keyword argument 'metadata_errors'`: incidente do PyAV 19, que tambem estava quebrando producao. Ver `knowledge/incidente-transcricao-2026-11.md` |

Teste local antes (2 workers + simulacao de 3 min): 826 mensagens viraram 826 linhas, 1
transcricao, as 2 copias de audio viraram 1 trecho de 180s na logica de transcricao.

---

## 7. O que falta e proximos passos (em ordem)

1. **Levar #113 e #114 (PyAV e 400) para a `dev`**: a dev ainda tem PyAV 19 e transcreve quebrado.
   `main` tem os 2 consertos, `dev` nao.
2. Conferir a transcricao da live 123 na dev (reenfileirar o job, que esta `failed`) e confirmar
   que a cobertura de audio usa o standby na janela 11:50-12:00.
3. **Apagar os dados do ensaio na dev**: channel 9 (japabigodin), live 123, chat, viewers, jobs,
   transcript e `audio/9/123/` no Spaces. **Enquanto o canal 9 existir, uma live NOVA dele sera
   capturada na dev pelos 2 workers.**
4. Release `dev` -> `main` (decisao do Henry). Leva junto o redesign (PRs 107-109).
5. Criar o app standby de producao (mesmo procedimento da secao 5, apontando para `main`), com OK
   do Henry. Nunca rodar 2 workers em producao sem o #111 la: duplicaria tudo como em 16/07.

---

## 8. O que monitorar

| O que | Como |
|---|---|
| Standby da dev vivo | `doctl apps logs 34944dd8-b16c-489d-80eb-04dd8b46514b worker-capture-standby --type run --tail 50`: `GET /helix/streams` a cada minuto com 200 |
| Ninguem duplicando | depois de cada live: `select count(*) from (select 1 from chat_messages where stream_id=X group by message_id, sent_at having count(*)>1) d` deve dar 0 |
| Standby nao pode atrasar o oficial | nunca fazer deploy dos 2 apps ao mesmo tempo |
| Custo | 1 worker 0,5 GB a mais na dev (preco nao conferido) e audio gravado 2x (~14,4 MB/h por copia a 32 kbit/s) |

---

## 9. Nao verificado

- Transcricao de uma live capturada pelos 2 workers em ambiente real (bloqueada pelo incidente).
- Nenhuma live de canal cadastrado de verdade na dev passou pelo standby.
- Preco do app standby.
- Se a Twitch reenvia o webhook stream.online quando a API esta fora.
