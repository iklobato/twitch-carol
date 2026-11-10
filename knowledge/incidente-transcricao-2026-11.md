# Incidente: transcricao de producao parada de 05/11 a 10/11 - estado da sessao 2026-11-10

Snapshot: 2026-11-10 16:23 UTC (13:23 BRT). Cobre **somente** o que foi feito nesta sessao: como o
incidente foi achado, as 2 causas, os 2 hotfixes em producao, o reprocessamento e a protecao do
audio. Achado durante o ensaio da captura redundante (`knowledge/captura-redundante-standby.md`).

Leitor alvo: qualquer agente que continue. Todo numero foi medido nesta sessao (consultas so de
leitura pelo console do app, salvo onde diz "escrita"); o que nao foi verificado esta na secao 9.

---

## 1. Resumo rapido

| Item | Estado em 2026-11-10 16:23 UTC |
|---|---|
| Causa 1: PyAV 19 | consertada por https://github.com/iklobato/twitch-carol/pull/113 (`av>=18,<19`), em producao desde 12:36 UTC |
| Causa 2: 400 raro do OpenRouter derrubava live longa inteira | consertada por https://github.com/iklobato/twitch-carol/pull/114, em producao desde 14:45 UTC |
| Lives sem transcricao/relatorio | 70 reenfileiradas as 12:38 UTC (escrita, OK do Henry) |
| Fila agora | 71 na fila, 1 rodando, 3 terminadas desde o reenfileiramento, 0 falhas permanentes |
| Previsao de fim | ~2026-11-11 13:00 UTC (medida as 15:58: 2.512 arquivos de audio, ~2 arquivos/min) |
| Audio em risco | nenhum: 18 lives de 03-05/11 copiadas para `rescue/`; as demais expiram depois do fim previsto |
| `dev` | **ainda sem #113 e #114**: transcricao quebrada la |

---

## 2. Causa 1: PyAV 19 (05/11 01:39 UTC ate 10/11 12:36 UTC)

- Ultima transcricao boa em producao: 2026-11-04 22:50 UTC. De 05/11 a 09/11: 66 jobs `failed`.
- Erro em todo job: `TypeError: open() got an unexpected keyword argument 'metadata_errors'`.
- O deploy do release #99 (commit c0906af) foi em 2026-11-05 01:39 UTC. O `deploy/Dockerfile`
  instala as dependencias do `pyproject.toml` com **pip**, sem o `uv.lock`, e pegou PyAV 19.0.2
  (lancado 2026-10-21). O PyAV 19 removeu `metadata_errors`, que o `decode_audio` do
  faster-whisper 1.2.1 ainda passa. O `uv.lock` estava em 18.0.0, por isso testes e maquina local
  nunca viram.
- Reproduzido em venv limpo: av 19.0.2 da o mesmo TypeError, av 18.0.0 decodifica.
- Conserto (#113): `"av>=18,<19"` no `pyproject.toml` + `uv lock`. Simulando o pip da imagem, resolve
  av 18.1.0 e decodifica. Conferido no container: `av18.1.0`.
- Ninguem foi avisado: os alertas do Grafana nao entregam (SMTP nao configurado).

## 3. Causa 2: 400 do servico de transcricao (achado no reprocessamento)

- O servico e o OpenRouter (`/audio/transcriptions`), ~US$ 0,012 por hora de audio (campo
  `usage.cost`).
- Lives longas mandam milhares de pedacos de fala (live 1175: 3.217). O servico recusa raramente um
  pedaco com 400. O codigo tratava 400 como definitivo: jogava fora a live inteira e recomecava do
  zero (54 min perdidos numa live de 149 arquivos), falhando de vez na 3a tentativa.
- Diagnostico: o menor (0,62 s) e o maior (417,6 s, 13,4 MB) pedaco da live 1175 passam com 200
  quando enviados sozinhos. Nao e tamanho.
- Mensagem real (logada depois do #114, 15:42:58 UTC):
  `transcription endpoint returned 400: {"error":{"message":"Provider returned 400","code":400}}`.
  O OpenRouter repassa o 400 do provedor sem motivo. Na 2a tentativa do mesmo pedaco passou.
- Conserto (#114, `workers/transcribe/pipeline.py`):
  - 400 tem nova tentativa por pedaco, como 429 e 5xx (401 continua sem).
  - A resposta do servico vai para o log e para o erro.
  - Pedaco que falha de vez e pulado (`ChunkFailureBudget`); o log do job mostra `untranscribed`.
  - A live ainda falha se mais de 1% dos pedacos falhar (`MAX_FAILED_CHUNK_SHARE`): servico fora.
- Prova em producao: a live de 149 arquivos terminou as 15:57:24 UTC com
  `{'speech': 5613, 'music': 213, 'guest_conversation': 0, 'silence': 710, 'untranscribed': 0}` e a
  analise dela terminou em seguida.

---

## 4. Reprocessamento (escrita em producao, com OK do Henry)

- 12:38 UTC: 70 jobs `transcribe` com erro `metadata_errors`, de 05/11 em diante, um por live, sem
  transcricao boa: `status='queued', attempts=0`, e a live volta para `queued_transcription`.
  Resultado: `RQ: requeued jobs 70 streams 70`.
- 15:00 UTC: a live 1175 ficou presa como `running` no worker que morreu no deploy do #114 e foi
  devolvida a mao (`R1175=jobs1:streams1`).
- A fila escolhe a ordem pela proxima live provavel do canal (`core/worker_loop.py:pick_next_job`),
  nao pela idade da live.

## 5. Protecao do audio (escrita no bucket, com OK do Henry)

- O audio em `audio/` expira em ~7 dias. Medido: lives de 02/11 para tras ja tem 0 arquivos; de
  04/11 ainda tinham. A env `AUDIO_RETENTION_DAYS=365` do app **nao** e a regra real do bucket, e a
  chave do app nao consegue ler a regra (`AccessDenied` em `GetBucketLifecycleConfiguration`).
- Copia no proprio bucket (`copy_object`, mesmo tamanho conferido arquivo a arquivo) para
  `rescue/audio/...`, prefixo sem regra de expiracao:
  - 13:20 UTC: 328 arquivos, 757 MB, 7 lives (1128 de 03/11 com 196 arquivos; 1142, 1144, 1146,
    1147, 1148, 1149 de 04/11).
  - 14:03 UTC: 488 arquivos, 1,1 GB, 11 lives de 05/11 (1150-1153, 1155, 1157-1162).
- Se o original expirar antes da transcricao: copiar `rescue/audio/{canal}/{live}/` de volta para
  `audio/{canal}/{live}/` e reenfileirar o job daquela live.
- As copias ficam ate alguem apagar. Apagar so depois que a live tiver transcricao `done`.

---

## 6. Como medir o estado da fila

Dentro do container `api` de producao (`doctl apps console 9154182f-3392-4bfd-b76c-8da53ea52aa9 api`,
embrulhado em `script -q /dev/null` porque precisa de TTY), consultas so de leitura:

```
select type, status::text, count(*) from jobs
 where type in ('transcribe','analyze') and created_at >= '2026-11-04' group by 1,2;
select count(*) from jobs where type='transcribe' and status::text='done'
 and finished_at > '2026-11-10 12:38';
```

Log do worker: `doctl apps logs 9154182f-3392-4bfd-b76c-8da53ea52aa9 worker-transcribe --type run`.
Linhas que importam: `transcribe done: {...}`, `transcription endpoint returned 400: ...`,
`speech chunk skipped`, `transcribe failed permanently`.

## 7. O que monitorar

| O que | Ate quando | Sinal de problema |
|---|---|---|
| Fila de transcricao zerar | ~11/11 13:00 UTC | `transcribe failed permanently` no log, ou a contagem de `done` parar por mais de ~1h30 |
| `untranscribed` nos `transcribe done` | sempre | valor alto numa live = o servico recusou muitos pedacos |
| Lives de 06/11 | audio expira ~14/11 00:00 UTC | se a fila atrasar, copiar para `rescue/` como em 5 |
| Novos deploys | sempre | qualquer biblioteca pode mudar de versao no build (ver 8.1) |

---

## 8. O que falta e proximos passos

1. **Levar #113 e #114 para a `dev`** (merge de `main` em `dev`): a dev transcreve quebrado.
2. Dockerfile instalar pelo `uv.lock` (`uv export --frozen`), para nenhuma biblioteca mudar sozinha
   num build. Mudanca de build: PR separado, revisar com calma.
3. Travar o job na fila (`SELECT ... FOR UPDATE SKIP LOCKED` em `pick_next_job`) para poder rodar
   mais de um worker de transcricao. Hoje dois workers pegariam a mesma live.
4. Retomar a transcricao de onde parou em vez de recomecar a live do zero numa nova tentativa.
5. Alerta que chega em alguem: `transcribe failed permanently` passou 5 dias sem ninguem saber.
6. Depois que a fila zerar: conferir que as 18 lives de `rescue/` estao `done` e decidir se apaga
   as copias.

---

## 9. Erros cometidos nesta sessao (para nao repetir)

- **13:32 UTC, worker de transcricao derrubado por mim**: um diagnostico rodando DENTRO do container
  `worker-transcribe` guardou na memoria todos os pedacos de fala de 105 arquivos e estourou os 2 GB.
  O worker reiniciou e perdeu a 2a tentativa da live 1175. Diagnostico pesado vai no
  `worker-analyze` ou fora, guardando so o necessario.
- **14:50 UTC**: script de reenfileirar com `interval :i` (parametro nao e aceito em literal de
  interval no Postgres) falhou 3 vezes antes de eu ler o erro. Usar `make_interval(secs => N)`.

## 10. Nao verificado

- Quantas lives de 06/11 em diante entram na fila por dia (a previsao de fim nao conta isso).
- O preco exato da transcricao das 70 lives (estimado pelo `usage.cost` de um pedaco).
- Se o 400 do OpenRouter vem sempre do mesmo provedor por tras.
