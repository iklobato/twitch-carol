# Arquitetura do StreamIntel

Referência de responsabilidades de cada componente da infraestrutura, para
humanos e agentes. Reflete o estado atual: prod 100% no DigitalOcean App
Platform, DNS na Cloudflare, e sem Valkey em produção (fila e dedup vivem no
Postgres).

Dois princípios atravessam tudo:

- **Números vêm sempre de SQL; o LLM só escreve texto que cita fatos já
  calculados.** Nenhum número exibido sai do modelo.
- **O Postgres é a única dependência de estado em produção.** A fila de jobs é
  a tabela `jobs` (workers fazem poll), e o dedup do EventSub é a tabela
  `eventsub_messages`. Nada de fila/cache externo no caminho principal.

## Fluxo (diagrama)

```mermaid
flowchart TB
    Browser([Navegador do streamer])

    subgraph edge[Borda]
      DNS[DNS Cloudflare<br/>streamintel.cc + TLS]
    end

    subgraph app[App Platform]
      WEB[web<br/>React estatico]
      API[api<br/>FastAPI]
      WC[worker-capture]
      WT[worker-transcribe]
      WA[worker-analyze]
      MIG[migrate<br/>PRE_DEPLOY]
    end

    subgraph data[Managed - estado]
      PG[(Postgres + pool<br/>dados / fila jobs / dedup)]
      SP[(Spaces<br/>audio + backups)]
    end

    subgraph ext[Externo]
      TW[Twitch<br/>EventSub / Helix / IRC / OAuth]
      OR[OpenRouter<br/>LLM + Whisper]
      SE[Sentry]
    end

    subgraph obs[Observabilidade]
      MON[Droplet monitoramento<br/>Prometheus + Grafana]
    end

    Browser --> DNS --> WEB --> API
    API -->|registra subs| TW
    TW -->|webhooks / OAuth| API
    API -->|stream.online cria Stream| PG

    TW -->|chat IRC / viewers / HLS| WC
    WC -->|poll CAPTURING| PG
    WC -->|ChatMessage / ViewerSample| PG
    WC -->|segmentos Opus| SP
    WC -->|enfileira transcribe| PG
    WC -->|cria clip nos picos Helix| TW

    WT -->|pega job| PG
    WT -->|baixa audio| SP
    WT -->|Whisper| OR
    WT -->|TranscriptSegment / enfileira analyze| PG

    WA -->|pega job| PG
    WA -->|LLM| OR
    WA -->|Peak / Insight / Recs / READY| PG

    API -->|le dados| PG
    API --> WEB

    MIG -->|alembic upgrade| PG
    MON -->|probe HTTPS| API
    MON -->|grafana_ro read-only| PG
    API -.erros.-> SE
    WC -.erros.-> SE
```

## Componentes (em ordem de fluxo)

| # | Componente | Onde roda | Responsabilidade | Consome (input) | Gera (output) | Inicia / Termina |
|---|---|---|---|---|---|---|
| 1 | **DNS (Cloudflare)** | Managed | Resolve `streamintel.cc` pra borda do app e emite TLS; encaminha o email do apex (Email Routing). O subdomínio `send.` saiu daqui em 2026-08-09: o MX dele aponta pro droplet `mail.iklobato.com`, onde vive a caixa `henrique@send.streamintel.cc` | Query DNS, email de entrada | Registros A/AAAA/CNAME (DNS-only, sem proxy: a borda do App Platform já é Cloudflare) e MX | Sempre ativo (zona provisionada) |
| 2 | **web** (React) | App Platform, static site | Renderiza o dashboard no navegador | JSON da `api` (`/api/*`) | HTML/UI no browser | Servido por request; buildado no deploy |
| 3 | **api** (FastAPI) | App Platform, service | OAuth, registro de EventSub, ingestão de webhook, serve o dashboard | Requests HTTP, tokens OAuth, notificações EventSub assinadas, leitura do PG | Respostas JSON; linhas `Stream`/`Event`/`Follower`; subs registradas na Twitch | Sobe no deploy; long-running (`/healthz`) |
| 4 | **Twitch** (EventSub/Helix/IRC/OAuth) | Externo | A fonte de tudo: eventos de live, chat, viewers, auth; e o destino dos clips criados | Nossos pedidos de subscription, OAuth e criação de clips (Helix `/clips`) | Webhooks (online/offline/follow/sub/bits), Helix, chat IRC, tokens, o clip criado | Sempre ativo; emite conforme a live |
| 5 | **worker-capture** | App Platform, worker | Captura a live: chat, viewers, audio; e auto-clipa os picos de chat ao vivo | IRC (chat), Helix `/streams` (viewers+titulo), HLS via streamlink | `ChatMessage`, `ViewerSample`, segmentos Opus para o Spaces, job `transcribe`, `TwitchClip` (clip nos picos via Helix `/clips`, scope `clips:edit`, com cooldown e teto por stream) | **Inicia:** `stream.online` cria `Stream` (CAPTURING), worker faz poll (3s). **Termina:** `stream.offline` ou Helix offline 3x seguidas |
| 6 | **worker-transcribe** | App Platform, worker | Transcreve o audio pos-live | Job `transcribe` (tabela `jobs`), audio baixado do Spaces, Whisper via OpenRouter | `TranscriptSegment`, job `analyze` | **Inicia:** job `transcribe` em QUEUED (poll 5s). **Termina:** done -> `QUEUED_ANALYSIS`; ou falha apos 3 tentativas |
| 7 | **worker-analyze** | App Platform, worker | Gera insights/picos/recomendacoes | Job `analyze`, chat/viewers/transcricao do PG, LLM via OpenRouter | `Peak`, `Insight`, `*Recommendation`; stream -> READY | **Inicia:** job `analyze` em QUEUED. **Termina:** done -> stream `READY` |
| 8 | **Postgres** + pool PgBouncer | Managed, nyc3 | Fonte unica de verdade: dados, fila de jobs, dedup EventSub | Escritas SQL de api/workers | Resultados de query; a fila (`jobs`); o dedup (`eventsub_messages`) | Sempre ativo (managed). Nunca tirar o pool: cluster compartilhado, ~50 conexoes |
| 9 | **Spaces** (`streamintel-audio`) | Managed, nyc3 | Storage do audio das lives e backups | Upload de segmentos (capture) | Download de audio (transcribe) | Sempre ativo; lifecycle 7d/30d |
| 10 | **OpenRouter** | Externo (API) | Backend remoto de LLM e de transcricao | Audio (transcribe) / prompt + fatos SQL (analyze) | Texto transcrito / JSON de insights | Chamado por job |
| 11 | **Sentry** | Externo (SaaS) | Captura de erros da api/workers | Excecoes instrumentadas | Nada (quota esgotada ate renovar) | Sempre ativo; sem entrega enquanto sem quota |
| 12 | **migrate** | App Platform, PRE_DEPLOY job | Aplica migracoes antes de cada deploy | Scripts alembic + `DATABASE_URL` | Schema atualizado | **Inicia:** antes de todo deploy. **Termina:** sucesso -> deploy segue; falha -> deploy ERROR (funciona como canario) |
| 13 | **Droplet de monitoramento** (`financialdata-monitoring`) | Droplet, compartilhado | Prometheus + Grafana + blackbox + alertas | Probe do site + leitura do PG via `grafana_ro` (read-only) | Dashboards e alertas | Sempre ativo |
| 14 | **~~Valkey~~** (`financialdata-valkey`) | Managed, nyc1 | Fora de producao (fila e dedup foram pro PG) | Apenas chaves `sim:*` do simulador local | Nada em prod | Desativado em prod em 2026-07-16/17 |
| 15 | **~~Droplet `stream-intel`~~** | (destruido) | Era o prod antigo (rsync + docker compose) | - | - | Destruido 2026-07-16; snapshot `stream-intel-pre-retire-20260716` guardado |

## Idioma (duas coisas diferentes)

Um canal carrega **dois** idiomas, e confundi-los ja quebrou o produto uma vez:

| Coluna | O que decide | De onde vem |
|---|---|---|
| `channels.language` | idioma da tela e do texto que o LLM escreve | fixado em **ingles** no cadastro (`SIGNUP_LANGUAGE`); canal antigo mantem `pt` |
| `channels.spoken_language` | stopwords e lexico de sentimento do chat | **declarado pelo streamer** na tela de cadastro; a deteccao do Whisper so preenche quem ainda nao declarou |

**O produto e servido em ingles, e portugues e a excecao.** Quem ainda nao fez
login cai na regra do navegador, e ela e a mesma em todo lugar: navegador `pt*`
le portugues, qualquer outro le ingles. Vale para o app (`resolveLang` em
`apps/web/src/i18n.ts`), para a pagina de venda `/howto` (`DEFAULT_LANG` em
`apps/api/marketing.py`) e para o default da coluna `channels.language`. Ate
2026-08-13 a `/howto` e a coluna faziam o contrario, mandando quem chegava em
espanhol ou frances para uma pagina em portugues e depois para um painel em
ingles.

A `/howto` e servida **pela api**, nao pelo site estatico: o App Platform nao
resolve URL sem extensao. As duas grafias (`/howto` e `/howto.html`) estao
listadas no ingress do `deploy/app.yaml` porque **rota casa por segmento de
caminho, nao por prefixo de string**: enquanto so `/howto` estava la, a forma
`.html` caia no 404 do site estatico, em producao, e nenhum teste via porque
teste bate direto na api. A escolha do idioma da pagina: `?lang=` na URL, senao
o cookie `howto_lang`, senao o idioma do canal logado, senao o navegador.

O `broadcaster_language` da Twitch responde `en` para canal que fala portugues
(medido no `iklobat`), e enquanto um campo so alimentava as duas coisas esse
palpite nao trocava so a tela: mandava o Whisper transcrever audio em portugues
como ingles. Ele nao traduz, transcreve foneticamente, e o validador de
evidencia so confere se o id citado existe, nunca se o texto quer dizer algo.

Hoje o Whisper roda **sem receber idioma** e reporta o que ouviu. Para canal que
declarou, divergencia vira aviso no log, nunca sobrescrita.

`channels.timezone` tambem vem do cadastro (lido do navegador, sem perguntar) e
decide os chatters por dia, o agrupamento por dia na lista de lives, o periodo
que mais rende e o melhor dia da semana.

## Isolamento entre contas

O produto e multi-tenant e o dado e do streamer. **Nenhum canal pode ler ou
escrever dado de outro.**

Como isso e garantido hoje:

| Camada | Mecanismo |
|---|---|
| Sessao | cookie assinado -> `CurrentChannel` (`apps/api/deps.py`) |
| Rota com `{stream_id}` | `_owned_stream()` compara `stream.channel_id` com o da sessao |
| Id aninhado (`peak_id`, `insight_id`) | conferido contra o stream do dono, nao so contra o proprio id |
| Consulta agregada | filtra por `channel.id` na propria query |

Toda recusa responde **404, nunca 403**: 403 ja informa que o id existe e
pertence a outra pessoa.

Tres lugares olham fora do canal de proposito: `/api/queue` (le os jobs de todos
para calcular sua posicao, mas devolve so o seu e uma contagem anonima),
`/api/stats` (agregado publico da plataforma; com poucos canais isso ja e um
numero pequeno, atencao conforme crescer) e `admin/impersonate` (allowlist em
`ADMIN_LOGINS`, exige login real e gera log).

**A armadilha desta base:** `Insight` so conhece o `stream_id`, entao consulta
que filtra apenas pelo insight varre a plataforma inteira. Foi assim que
`topic_to_follows` creditou a um streamer o assunto da live de outro. Sempre faca
join com `Stream` e filtre por `channel_id`.

`tests/test_isolation.py` e a rede: le as rotas do schema OpenAPI da aplicacao e
tenta todas as que recebem `{stream_id}` como outro canal, entao endpoint novo
entra na varredura no dia em que e escrito.

Resumo em uma frase: **DNS -> web -> api (login + registra EventSub) -> Twitch
dispara `stream.online` -> capture (chat/viewers/audio) -> transcribe
(audio->texto) -> analyze (texto->insights) -> api/web mostram o relatorio**,
com Postgres e Spaces como lastro em todas as etapas e OpenRouter fazendo o
trabalho pesado de IA.
