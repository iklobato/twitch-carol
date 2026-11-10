# Redesign do frontend (apps/web) - estado da sessao 2026-11-09/10

Snapshot: 2026-11-10 16:23 UTC (13:23 BRT), revisado no fim da sessao. Cobre **somente** o que
foi feito nesta sessao:

1. Analise do frontend atual: telas, dados, problemas de leitura.
2. Design novo em um canvas (5 telas), feito antes de qualquer codigo.
3. Plano de 6 PRs, aprovado pelo Henry.
4. PRs 1, 2 e 3 implementados, rodados local no navegador e abertos contra `dev`.
   **Nada disso esta em producao (`main`).**

Leitor alvo: qualquer agente que pegue este trabalho depois. Numero aqui foi medido nesta
sessao; o que nao foi verificado esta dito na secao 9.

Outros trabalhos da mesma sessao, em arquivos proprios: `knowledge/captura-redundante-standby.md`
(segundo worker de captura) e `knowledge/incidente-transcricao-2026-11.md` (transcricao de producao
parada de 05/11 a 10/11). Os PRs 4 a 6 do redesign ficaram parados por causa deles.

---

## 1. Resumo rapido

| Item | Estado em 2026-11-10 16:23 UTC |
|---|---|
| PR 1 shell + rotas + Settings | https://github.com/iklobato/twitch-carol/pull/107 MERGEADO em `dev` (51a473a), deploy dev ACTIVE |
| PR 2 Home | https://github.com/iklobato/twitch-carol/pull/108 MERGEADO em `dev` (f87c7e4), deploy dev ACTIVE as 02:18 UTC (17 min depois do merge), bundle conferido |
| PR 3 relatorio da live em abas | https://github.com/iklobato/twitch-carol/pull/109 ABERTO, esperando o Henry (traz tambem o conserto do teste com corrida e o hifen) |
| Este documento | https://github.com/iklobato/twitch-carol/pull/110 ABERTO |
| PRs 4, 5, 6 | nao comecados |
| Producao (`main`, 0898765) | sem nenhum PR do redesign; desde a manha recebeu so os hotfixes #113 e #114 do incidente de transcricao |
| Backend | nao mudou. Sem migracao, sem endpoint novo, sem dependencia nova |
| Testes web | 50 antes da sessao, 61 em `dev` hoje, 64 no branch do PR 3 |

---

## 2. Por que (o que a analise achou no frontend antigo)

Lido na `origin/dev` 0b1b222 em 2026-11-09. Stack: React 18 + Vite 6 + Tailwind 4 + chart.js,
rota por hash (`apps/web/src/router.ts`), textos em `apps/web/src/locales/{en,pt}.ts`.

- 4 links no topo: lista de lives, "Meu canal", "Meus seguidores", "Financeiro". Cada tela
  empilhava 10 a 15 secoes com o mesmo peso. Nada dizia o que olhar primeiro.
- Dinheiro aparecia em 4 lugares: `ChannelView`, `FinanceView`, `OverviewSection` e
  `FinanceSection` dentro do relatorio da live.
- Idioma e email de resumo (`LanguageSettings`, `DigestSettings`) ficavam no topo de "Meu canal".
- Relatorio da live (`StreamReport.tsx`, 682 linhas) tinha ~12 blocos em fila e buscava tudo
  ao abrir.
- O link de sair estava fixo como "Sair" em todos os idiomas (`App.tsx`).

Todos os dados que o design novo usa **ja existiam** nos endpoints: `/api/me`, `/api/streams*`,
`/api/finance`, `/api/followers`, `/api/channel`, `/api/queue`. Por isso o redesign e so frontend.

---

## 3. Design

- Canvas (privado, do Henry): https://claude.ai/artifact/JdrD5eSsLa3Q1dmfngdZ82
  5 telas: Home, Lives (relatorio com abas), Money, Audience, Settings. Menu lateral.
- Dados do canvas: nomes e US$ vem do seed de dev; as outras contagens sao de exemplo.
- Paleta (agora tokens do Tailwind em `apps/web/src/index.css`, bloco `@theme`):
  fundo `canvas #0e0e11`, `panel #16161b`, `line #24242c`, texto `ink #ededf0`,
  `ink-muted #a1a1aa`, `ink-faint #8e8e98`, roxo `accent #a78bfa` para chat e destaque,
  verde `money #34d399` **so para dinheiro**, `alert #f87171`.
- Fontes: Inter (texto) e Space Grotesk (titulos, classe `font-display`), via Google Fonts
  em `apps/web/index.html`.
- Sem emoji nas telas novas, sem card com borda colorida a esquerda, sem degrade.

### Decisoes do Henry (2026-11-09)

| Pergunta | Resposta |
|---|---|
| Como entregar | 6 PRs, um por tela, todos contra `dev` |
| Fontes | Google Fonts no `index.html` |
| Onde ficam crescimento, melhores dias, assuntos recorrentes e VODs (hoje em "Meu canal") | bloco "Tendencias" na tela Lives |

---

## 4. Os 6 PRs: o que cada um faz e o estado

| # | PR | Estado | O que muda |
|---|---|---|---|
| 1 | https://github.com/iklobato/twitch-carol/pull/107 | mergeado | menu lateral, tokens, fontes, rotas novas, tela Settings |
| 2 | https://github.com/iklobato/twitch-carol/pull/108 | mergeado | Home: proximo passo da IA, "precisa de atencao" completo, grafico da ultima live, dinheiro por live |
| 3 | https://github.com/iklobato/twitch-carol/pull/109 | aberto | relatorio da live em abas, carga sob demanda, cores novas nos blocos do relatorio |
| 4 | - | a fazer | Money: `FinanceView` com visual novo, dicas da IA no topo, ritmo das metas (sai de `ChannelView.tsx`, funcoes de pace das metas) |
| 5 | - | a fazer | Audience: `FollowersView` (901 linhas) em 4 grupos + fieis, VIPs e "% que escreve" de `/api/channel` |
| 6 | - | a fazer | bloco "Tendencias" na tela Lives, apagar `ChannelView.tsx`, `#/channel` vira alias de Home, limpar chaves de texto sem uso |

Todo PR: texto novo em `en.ts` **e** `pt.ts` (chave faltando quebra o build, `pt.ts` e tipado
contra `en.ts`), `npm test`, `tsc --noEmit`, `npm run build`, rodar local no navegador.

---

## 5. Implementacao atual (o que esta no codigo)

### 5.1 PR 1 (em `dev`)

- `apps/web/src/router.ts`: views `home | channel | audience | money | settings | stream | search`.
  Tabela `STATIC_ROUTES` com aliases: `#/finance` -> money, `#/followers` -> audience.
  Usa `Object.hasOwn` (ver 6.1). `#/channel` **continua** abrindo `ChannelView` ate o PR 6.
- `apps/web/src/components/Sidebar.tsx`: menu lateral; `aria-current="page"` na tela aberta;
  relatorio de live e busca deixam "Home" acesa (`ACTIVE_FOR_VIEW`). No celular vira faixa no topo.
  Item "Meu canal" e temporario (comentario `ponytail:` no arquivo).
- `apps/web/src/views/SettingsView.tsx`: `LanguageSettings` + `DigestSettings` + permissoes da
  Twitch (`me.scopes`, de `/api/me`, sem chamada extra) + sair. Bloco de permissoes some se
  `scopes` vier vazio. Data de conexao **nao** aparece (exigiria `/api/channel`, pesado).
- `App.tsx`: layout com menu lateral, busca, `@login`, sair com `t('app.logout')`.

### 5.2 PR 2 (em `dev`)

- `apps/web/src/components/OverviewSection.tsx`
  - `pickAttention(followers, channel)`: lista **todos** os itens (pico de follow, >=10 suspeitos,
    metas >=80% nao batidas), cada um com link (`#/audience` ou `#/money`). Substituiu
    `pickHighlight`, que mostrava so 1 item e caia na dica da IA.
  - Card "Proximo passo": `channel.recommendations[0]` com os `facts`.
  - `chatPath(points, w, h)`: linha SVG do chat na ultima live, dados de
    `/api/streams/{id}/timeline`. Menos de 2 pontos = sem grafico.
- `apps/web/src/views/StreamsList.tsx`
  - Valor por live: `/api/finance?period=all` buscado **uma vez por visita**, `by_stream`
    vira `Map<stream_id, usd>`. `earnedLabel`: sem receita mostra "-", nunca "$0.00".
    (Entrou em `dev` como travessao U+2014; o PR 3 troca por hifen, regra de estilo do projeto.)
  - Emojis sairam das linhas de numeros.
- `PeriodPicker.tsx`: visual novo, `aria-pressed`.

### 5.3 PR 3 (branch `feat/redesign-live-report`, aberto)

- `apps/web/src/views/StreamReport.tsx`
  - `availableTabs(peaks, topics)`: Momentos so se tem pico, Assuntos so se tem assunto;
    "O que melhorar", Dinheiro e Chat sempre.
  - Abas com `role=tablist/tab/tabpanel`. Dinheiro, comunidade e chatters so buscam dados ao
    abrir a aba (os componentes buscam sozinhos ao montar).
  - `actionable` continua buscado no topo porque o resumo rapido usa a retencao.
  - Clicar num pico (grafico ou resumo rapido) abre Momentos e depois rola ate ele
    (`goToPeak` + `pendingPeak`).
- Commits no branch: 041bd57 (abas + cores), 922dd98 (conserto do teste com corrida, 6.2),
  0210d56 ("-" no lugar do travessao em `earnedLabel`).
- Cores trocadas de zinc/purple/orange para os tokens em `StreamReport.tsx`,
  `ActionableSection.tsx`, `FinanceSection.tsx`, `CommunitySection.tsx`, `ChattersSection.tsx`,
  `PipelineStepper.tsx`. Cores com significado (sentimento vermelho -> verde) ficaram.

---

## 6. Descobertas e armadilhas

### 6.1 `'toString' in obj` vira rota
Um teste novo pegou: com `clean in STATIC_ROUTES`, `#/toString` virava rota valida (o `in`
olha o prototype). Conserto: `Object.hasOwn`. Teste em `router.test.ts`.

### 6.2 Teste da Home com corrida (consertado no PR 3)
`OverviewSection.test.tsx` esperava o titulo "Overview" e lia o numero de seguidores na hora.
O titulo aparece quando **qualquer** das 4 chamadas responde. Falhou 1 vez numa rodada
completa; depois passou 6 vezes seguidas. Conserto: `findByText` para cada numero.
**Esse teste com corrida esta em `dev` ate o PR 3 entrar.**

### 6.3 Hook local `~/.claude/hooks/quality.sh` falha em todo `.ts`
Roda `npx tsc --noEmit` na raiz do repo (sem `tsconfig`), pega um `tsc` 7.0.2 global, imprime a
ajuda e sai com erro. **Nao e erro do codigo.** Rodar o typecheck certo:
`npx tsc --noEmit -p apps/web` (ou dentro de `apps/web`). Hook nao foi consertado.

### 6.4 Push na `dev` faz deploy sozinho
App de dev `3f70eb48-2543-4e97-a9ae-e008317dbbac` (`streamintel-dev`): todos os componentes
com `branch: dev`, `deploy_on_push: true` (conferido com `doctl apps spec get`). O
`deploy/app.yaml` do repo so mostra `main`: e o spec do app de prod, nao o de dev.

### 6.5 Conferir se o codigo novo esta no ar sem login
`/api/me` sem cookie da 401 e a landing aparece. Para provar o deploy sem logar, olhar o
bundle servido:
```
JS=$(curl -s https://dev.streamintel.cc/ | grep -o 'assets/index-[A-Za-z0-9_-]*\.js')
curl -s https://dev.streamintel.cc/$JS | grep -o '"overview.nextStep"'   # existe so depois do PR 2
```
PR 1 foi conferido assim em 2026-11-10, depois do deploy ACTIVE de 01:20:53 UTC (`"app.nav.money"` e
`#/settings` no bundle).

### 6.6 Landing tem video em loop
Em Playwright, `waitUntil: 'networkidle'` nunca termina na landing (deslogado). Usar `load`.

### 6.7 Tela Audience antiga rola de lado no celular
Com o canal `sim_streamer`, 390px: `scrollWidth > innerWidth` em `#/audience`. E do
`FollowersView` antigo; resolver no PR 5.

### 6.8 Dados do seed local
- canal 4 `sim_streamer`: 10 lives, tem receita (`/api/finance?period=all` = US$ 67.50,
  9 linhas em `by_stream`) e 6 recomendacoes. Bom para ver Home e relatorio com dados.
  Live 6: 1 pico, 4 assuntos. Live 19: chat todo em 1 minuto (sem grafico, esperado).
- canal 5 `mock_streamer`: 6 lives, quase tudo zero, sem recomendacao.
- canal 3 `iklobat`: 0 lives.

---

## 7. Como rodar local (frontend contra a API real)

Feito e funcionando em 2026-11-10. Comandos a partir do worktree do repo.

```
docker compose -p deploy -f deploy/docker-compose.yml up -d postgres valkey   # 5433 e 6380
uv sync --python 3.12            # onnxruntime 1.19.2 nao tem wheel para 3.13
# chave descartavel, so local; NUNCA a do .env de prod
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > /tmp/local-fernet.key
FERNET_KEY=$(cat /tmp/local-fernet.key) .venv/bin/alembic upgrade head
FERNET_KEY=$(cat /tmp/local-fernet.key) .venv/bin/uvicorn apps.api.main:app --host 127.0.0.1 --port 8080
(cd apps/web && npx vite --port 5173 --strictPort)    # o proxy do vite aponta /api e /auth para 8080
```

Login sem Twitch: gerar o cookie `session` com a mesma chave e por no navegador em `localhost`:
```
FERNET_KEY=$(cat /tmp/local-fernet.key) .venv/bin/python -c "from core.crypto import create_session_token; print(create_session_token(4))"
```
Abrir http://localhost:5173 (o vite escuta em `[::1]`, use `localhost`, nao `127.0.0.1`).

Observacoes:
- Nao subir os workers: o `../.env` de prod entra no compose e eles falariam com servicos reais.
- O volume `deploy_pgdata` e o mesmo do compose da pasta principal do repo.

### Verificacao no navegador usada nesta sessao
Script Node com o `playwright-core` do pacote global `@playwright/mcp`, ligado por CDP no Brave
compartilhado (`127.0.0.1:9222`): abre uma aba propria, poe o cookie, visita cada rota em
1440x900 e 390x844, salva print, e imprime `aria-current`, rolagem lateral, erros de console e
respostas `/api` >= 400. Fecha so a propria aba. Os scripts ficaram no scratchpad da sessao,
**nao** no repo.

---

## 8. O que monitorar

| O que | Como | Quando |
|---|---|---|
| Tempo de deploy da dev | `doctl apps list-deployments 3f70eb48-2543-4e97-a9ae-e008317dbbac --format Phase,Progress,Cause` | a cada merge. PR 1 levou ~6 min; PR 2 levou 17 min (merge 02:01, `BUILDING 8/23` as 02:13, ACTIVE 02:18 UTC). Causa da diferenca nao investigada. Se der `ERROR`, ler o log do build |
| Codigo de cada PR no ar | grep do bundle (6.5) por uma chave nova do PR | depois do deploy ACTIVE. PR 2 conferido as 02:18 UTC: `assets/index-Y7w_KlH5.js` tem `"overview.nextStep"` e `period=all` |
| Telas logadas na dev | abrir dev.streamintel.cc logado, desktop e celular | ninguem conferiu ainda (Brave compartilhado sem login na dev) |
| Chamadas novas por visita | Home agora faz +1 `/api/finance?period=all` e +1 `/api/streams/{id}/timeline`; relatorio faz menos chamadas ao abrir (abas sob demanda) | apos ir para prod, se a API ficar lenta |
| Google Fonts | fontes vem de `fonts.googleapis.com`; se cair, cai para a fonte do sistema | so visual |

---

## 9. O que falta e proximos passos (em ordem)

1. Henry decide o merge do https://github.com/iklobato/twitch-carol/pull/109 (traz tambem o
   conserto do teste com corrida, 6.2).
2. PR 4 Money, PR 5 Audience (com o conserto de 6.7), PR 6 Tendencias + apagar `ChannelView`.
3. No PR 6: `#/channel` vira alias de Home em `router.ts`, e conferir os links em
   `apps/web/public/howto.en.html` e `howto.pt.html` (3 links para `#/channel` em cada, medido em
   2026-11-10; o numero 11 dito antes na sessao contava o repo inteiro e estava errado).
4. Release `dev` -> `main` quando os 6 estiverem prontos (decisao do Henry). So depois disso
   alguma coisa do redesign chega em producao.

Pequenos pendentes, sem PR:
- Botoes "Util / Nao util" ainda tem emoji no texto (`feedback.useful`, `feedback.notUseful`).
- Abas do relatorio funcionam com Tab e clique; setas do teclado entre abas nao.
- Nada disso foi testado com leitor de tela.

Nao verificado nesta sessao:
- Nenhuma tela foi vista logada em dev.streamintel.cc.
- Nao rodei Lighthouse nem medi tempo de carga.
- O grafico de chat na Home so foi visto vazio no seed (lives com 1 ponto); a linha foi provada
  por teste unitario (`chatPath`), nao em tela com dado real.

---

## 10. Estado local deixado na maquina do Henry

- Worktrees: `/Users/iklo/twitch-worktrees/redesign` (branch `feat/redesign-live-report`),
  `/Users/iklo/twitch-worktrees/knowledge-redesign` (este documento), `/Users/iklo/twitch-worktrees/capture`
  (captura) e `/Users/iklo/twitch-worktrees/hotfix-av` (hotfixes da `main`).
- Rodando: API local na 8080 (agora o codigo do worktree `capture`), vite na 5173 (worktree
  `redesign`), containers `deploy-postgres-1` e `deploy-valkey-1`.
- Banco local migrado de `0022` para `0030` (migracoes da `dev`, incluindo as da captura). A pasta principal do repo esta
  na branch `perf/chat-channel-index` com uma migracao `0025` propria sem commit: pode conflitar
  com a `0025` da `dev` quando voltar a ela. Nao testado.
