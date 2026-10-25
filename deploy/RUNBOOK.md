# Runbook: promover `dev` para produção

Procedimento para rodar com as mãos. O panorama de como o deploy funciona está no
[`README.md`](../README.md); aqui é a ordem dos comandos e o que conferir.

## Antes de começar

**O `gh` desta máquina fica ativo na conta errada.** O repo é `iklobato/twitch-carol`
e a conta ativa é `iklobato-brt`, então todo comando precisa do token explícito:

```bash
export GH="GH_TOKEN=$(gh auth token --user iklobato)"
```

Sem isso o `gh pr create` falha com `must be a collaborator`, o que não parece um
problema de conta. E `gh pr edit --base` falha **calado**: para trocar o alvo de um
PR use `gh api -X PATCH repos/iklobato/twitch-carol/pulls/<N> -f base=dev`.

## 1. Escolher a hora (o portão da live)

Todo deploy reinicia o `worker-capture`. Ele **retoma sozinho** qualquer live
marcada como `capturing` (é `restart-safe` por desenho, está escrito no docstring de
`workers/capture/main.py`), então o custo não é a live inteira:

| o que se perde num deploy com live no ar | quanto |
|---|---|
| chat | até 2 segundos (`CHAT_FLUSH_INTERVAL_SECONDS`) |
| áudio | até 10 minutos do segmento em voo (`AUDIO_SEGMENT_SECONDS = 600`) |
| a captura | nada, retoma no boot |

Dez minutos do áudio de alguém ainda vale escolher a hora. Os streamers do produto
são brasileiros e transmitem à noite, então **de manhã cedo é a janela**.

```bash
# pegue o cookie `session` de um navegador logado (você é admin)
python scripts/check_no_live.py --session "<cookie>"
```

Sai com `NINGUEM AO VIVO: pode subir` ou lista quem está. A lista de canais vem do
endpoint de admin, então ela não envelhece quando alguém novo se cadastra.

> Se quiser a checagem no banco em vez da Twitch, o enum é **minúsculo**:
> `select count(*) from streams where status::text = 'capturing'`. Escrever
> `'CAPTURING'` devolve **zero falso**, e isso já quase causou um deploy em cima de
> duas capturas ativas.

## 2. Conferir que a `dev` está verde

```bash
doctl apps list-deployments 3f70eb48-2543-4e97-a9ae-e008317dbbac --format ID,Phase,Cause | head -3
curl -s https://dev.streamintel.cc/healthz
```

A fase tem que ser `ACTIVE` para o commit que você quer promover. Se estiver
`ERROR`, **não promova**: a `main` vai falhar do mesmo jeito.

## 3. Abrir e mergear o PR

```bash
eval $GH gh pr create --base main --head dev --title "<o que vai>" --body "<por que>"
eval $GH gh pr merge <N> --merge --delete-branch=false
```

O merge dispara o deploy sozinho (`deploy_on_push: true`). Não há passo manual de
migração: o job `migrate` roda `alembic upgrade head` como PRE_DEPLOY.

## 4. Acompanhar

```bash
doctl apps list-deployments 9154182f-3392-4bfd-b76c-8da53ea52aa9 --format ID,Phase,Cause | head -3
```

Espere `ACTIVE`. Se der `ERROR`, **produção não caiu**: o job `migrate` é PRE_DEPLOY,
então build ruim ou migração ruim faz o deployment falhar e o anterior continua
servindo. É um canário de graça.

**Cuidado:** um deployment falho **não desfaz mudança de spec**. Se você tinha
aplicado um spec novo, o valor ruim fica e o próximo push falha igual.

## 5. Verificar

```bash
curl -s https://streamintel.cc/healthz
curl -s https://www.streamintel.cc/healthz
```

Depois abra o site, faça login e olhe a aba de seguidores. E rode a suíte que checa o
ambiente de fora:

```bash
E2E_BASE_URL=https://streamintel.cc \
E2E_APP_ID=9154182f-3392-4bfd-b76c-8da53ea52aa9 \
E2E_SESSION="<cookie>" \
  pytest tests/e2e -q
```

Ela é só leitura (todo request é GET), então é seguro apontar para produção. O que
ela cobre e por quê está em [`tests/e2e/README.md`](../tests/e2e/README.md).

## 6. Voltar atrás, se precisar

**Não existe rollback no `doctl`** (confirmado nos subcomandos). O caminho é reverter
o merge e empurrar:

```bash
git checkout main && git pull
git revert -m 1 <commit-do-merge>
git push origin main          # rebuilda em ~5 min
```

Voltar **só o código** é seguro quando as migrações do deploy foram aditivas (adicionar
coluna, preencher dado). Confira antes: se alguma apagou ou reescreveu coluna, o
código antigo pode não rodar contra o banco novo.

## Mudança de infra (spec), que é outra coisa

`git push` **não** aplica `deploy/app.yaml`. Componente novo, tamanho de instância e
variável de ambiente só entram com:

```bash
doctl apps spec get <APP_ID> > /tmp/spec-backup.yaml   # sempre guarde antes
doctl apps update <APP_ID> --spec deploy/app.yaml
```

Ordem importa: o código do componente novo precisa **já estar na branch** antes de
adicioná-lo ao spec, senão ele sobe e quebra procurando um módulo que não existe.
