# Stream Intel

Plataforma de analytics multimodal para streamers da Twitch. Captura chat,
eventos (EventSub) e áudio de cada live, transcreve com faster-whisper,
detecta picos por SQL e gera relatório com LLM local (llama.cpp): resumo,
explicação dos picos e assuntos ranqueados, sempre com evidência clicável
verificada contra o banco. Todo o processamento de IA roda em CPU local;
nenhuma API paga no caminho principal.

Produção de referência: https://streamintel.cc

## Arquitetura

```
apps/api           FastAPI: OAuth Twitch, webhook EventSub, API do dashboard
apps/web           React + Vite + Tailwind + Chart.js (build servido pelo Caddy)
workers/capture    IRC do chat, amostrador de viewers, gravador HLS->Opus
workers/transcribe VAD + faster-whisper (fila com prioridade por próxima live)
workers/analyze    picos por SQL + insights via llama.cpp com evidência validada
core               modelos, config, filas, crypto, cliente Twitch, métricas
scripts            simulador de live, seed de estados, benchmark, backup
deploy             Dockerfile, docker compose (dev + prod), Caddyfile
```

Serviços do compose: `api`, `worker-capture`, `worker-transcribe`,
`worker-analyze`, `valkey`, `caddy` e `postgres` (dev; em produção usamos um
Postgres gerenciado e o serviço local fica atrás do profile `local-db`).

## Desenvolvimento local

Pré-requisitos: Docker, uv, Node 20+.

```bash
uv sync                        # deps Python (.venv)
make web                       # build do frontend (apps/web/dist)
make up                        # sobe o stack (Caddy em http://localhost:8080)
```

Portas no host: web/api `8080`, Postgres `5433`, Valkey `6380`.
`deploy/sim.env` fornece defaults de dev (secret do EventSub, whisper tiny,
LLM 1.5B); qualquer valor no `.env` da raiz tem precedência.

Modelos locais (uma vez): baixe um GGUF para `data/models/` e confira o
caminho em `deploy/sim.env` (`LLM_GGUF_PATH`). O whisper baixa sozinho no
primeiro uso.

### Simulação de live (sem Twitch real)

```bash
uv run python scripts/simulate_stream.py --minutes 4 --audio caminho/audio.mp3
```

Publica chat/eventos/viewers/áudio pelos MESMOS caminhos de código da
captura real (webhook assinado, parser IRC). Ao final, a live percorre
transcrição -> análise -> `ready` sozinha.

Para popular o dashboard com todos os estados do pipeline (e uma live
analisável pelo LLM):

```bash
docker compose -f deploy/docker-compose.yml stop worker-transcribe worker-analyze
uv run python scripts/seed_pipeline_states.py            # canal mock
docker compose -f deploy/docker-compose.yml start worker-transcribe worker-analyze
```

### Testes e qualidade

```bash
make lint       # ruff + mypy
make test       # pytest (testes de banco usam o Postgres do compose)
make test-web   # vitest (frontend)
make test-all   # tudo
```

## Variáveis de ambiente

Documentadas em `deploy/env.example`. Essenciais em produção:
`TWITCH_CLIENT_ID/SECRET` (app em dev.twitch.tv com redirect
`https://SEU_DOMINIO/auth/callback`), `TWITCH_EVENTSUB_SECRET` (string
aleatória), `PUBLIC_BASE_URL` (https), `FERNET_KEY`, `DATABASE_URL`,
`SPACES_*` (áudio + backups; sem eles cai em disco local), `SIMULATION=0`.

## Deploy em produção (droplet DigitalOcean)

Layout de referência: 1 droplet s-4vcpu-8gb (docker) + Postgres gerenciado.
Para escalar, os workers movem-se para droplets próprios apontando para o
mesmo banco/Valkey; a imagem é a mesma, muda o `command`.

Do zero, num droplet limpo (imagem "Docker on Ubuntu"):

```bash
# 1. infra
doctl compute droplet create stream-intel --size s-4vcpu-8gb --region nyc3 \
  --image docker-20-04 --ssh-keys SUA_CHAVE --wait
ssh root@IP "ufw allow 80/tcp && ufw allow 443/tcp && mkdir -p /opt/stream-intel"

# 2. DNS: aponte um registro A do seu domínio para o IP do droplet

# 3. banco gerenciado (ou use o postgres do compose com --profile local-db)
doctl databases db create CLUSTER_ID streamintel
doctl databases user create CLUSTER_ID streamintel_app
doctl databases firewalls append CLUSTER_ID --rule droplet:DROPLET_ID
# conceda: ALTER SCHEMA public OWNER TO streamintel_app (como doadmin)

# 4. código e segredos
rsync -az --exclude .git --exclude .venv --exclude node_modules \
  --exclude data --exclude .env ./ root@IP:/opt/stream-intel/
ssh root@IP  # crie /opt/stream-intel/.env (veja deploy/env.example)
             # e /opt/stream-intel/deploy/.env com:
             #   SITE_ADDRESS=seu.dominio
             #   STREAMINTEL_DATABASE_URL=postgresql+psycopg://...sslmode=require

# 5. modelo LLM e subida
ssh root@IP "mkdir -p /opt/stream-intel/data/models && curl -L -o \
  /opt/stream-intel/data/models/qwen2.5-3b-instruct-q4_k_m.gguf \
  'https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf'"
ssh root@IP "cd /opt/stream-intel/deploy && docker compose \
  -f docker-compose.yml -f docker-compose.prod.yml up -d --build"
```

O Caddy emite o certificado TLS sozinho quando o DNS resolve. Migrações
rodam no boot da api. Depois do primeiro login em `https://SEU_DOMINIO`,
as subscriptions EventSub são registradas automaticamente e qualquer live
do canal passa a ser capturada.

Atualização de versão: repita o rsync do passo 4 e o `up -d --build` do
passo 5 (o cache de camadas torna rebuilds de código rápidos).

## Backup e restauração

Backup diário via cron no droplet (pg_dump -> gzip -> Spaces `backups/`
com retenção de 30 dias; sem Spaces, `data/backups/` com últimos 7):

```cron
0 9 * * * cd /opt/stream-intel/deploy && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T worker-capture python scripts/backup_db.py >> /var/log/stream-intel-backup.log 2>&1
```

Restauração:

```bash
# baixe o .sql.gz do Spaces (ou pegue em data/backups/), então:
gunzip -c stream-intel-DATA.sql.gz | \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T worker-capture \
  psql "$STREAMINTEL_DATABASE_URL_LIBPQ"   # URL sem o sufixo +psycopg
```

O banco gerenciado da DigitalOcean também mantém backups diários próprios
com point-in-time restore; este script é a camada extra e o caminho de
restauração portátil.

## Operação

- Logs (JSON estruturado): `docker compose ... logs -f api worker-capture`
- Healthchecks: api via `/healthz`; workers via ping no banco (`docker compose ps`)
- Reprocessar uma live: enfileire um job `analyze` para o stream
  (a análise é idempotente; veja `core/queues.enqueue_job`)
- Re-sincronizar EventSub: refaça o login no dashboard
- Trocar modelo LLM: troque o GGUF em `data/models/`, ajuste `LLM_GGUF_PATH`
  e reinicie `worker-analyze`
- Benchmark de transcrição: `docker compose ... exec worker-transcribe \
  python scripts/benchmark_transcription.py --audio /data/sim/arquivo.wav`

### Impersonar um cliente (suporte/debug)

Ver o dashboard como um cliente vê, para debugar valores ou dar suporte.
Acesso total: enquanto impersonando, a sessão age como a do cliente.

1. Libere seu login na allowlist: `ADMIN_LOGINS=seu_login` (csv para vários),
   e reinicie a `api`. Vazio = ninguém pode impersonar.
2. Faça login normal no dashboard com sua conta (a que está em `ADMIN_LOGINS`).
3. No header aparece um seletor **"Impersonar..."** com os canais cadastrados.
   Escolha um: a página recarrega já vendo o dashboard como aquele cliente.
4. Uma faixa vermelha "Vendo como @cliente" aparece no topo. Clique **Sair**
   para voltar à sua conta.

Via API (mesma coisa que o seletor faz): `POST /api/admin/impersonate/{login}`
e `POST /api/admin/impersonate/stop`, com o cookie de sessão do admin.

Início e fim ficam no log da `api` (`admin X impersonating Y`).
