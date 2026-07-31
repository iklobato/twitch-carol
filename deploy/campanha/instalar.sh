#!/usr/bin/env bash
# Deixa os lotes 8, 9 e 10 do convite beta agendados no droplet lekture-sfu.
#
#   RESEND_API_KEY=... ./deploy/campanha/instalar.sh
#
# Roda daqui, da raiz do repo. E idempotente: rodar de novo so re-sincroniza os
# arquivos e reescreve as units. Nao envia nada agora; quem envia sao os timers,
# e antes de cada disparo o portao (campaign_stats.py --portao) confere o lote
# anterior e barra o envio se o bounce passar de 3% ou aparecer spam.
set -euo pipefail

HOST=lekture-sfu
DEST=/opt/streamintel-campanha
ENV_FILE=/etc/streamintel-campanha.env
UV=/root/.local/bin/uv
# Terca a quinta as 10h, subindo no maximo um terco por degrau: 151 (o maior
# ja enviado) -> 200 -> 250 -> 300 -> 176. O que sobra do dia vira o degrau da
# terca seguinte, porque a janela de melhor abertura e so terca a quinta.
AGENDA=("lote-11:2026-08-04" "lote-12:2026-08-05" "lote-13:2026-08-06" "lote-14:2026-08-11")
HORA="10:00"
FUSO="America/Sao_Paulo"

: "${RESEND_API_KEY:?RESEND_API_KEY nao esta no ambiente (use o do .env)}"
[[ -f scripts/send_campaign_batch.py ]] || { echo "rode da raiz do repo"; exit 1; }

# Conteudo vem pelo stdin. As variaveis do heredoc sao expandidas aqui de
# proposito (caminhos e datas sao decididos neste script, nao no droplet).
escrever_no_droplet() {
  ssh "$HOST" "cat > '$1'"
}

# O lote-10 vai junto mesmo ja tendo saido: sem a lista dele o portao nao
# consegue medir o bounce do lote anterior ao lote-11, e barra o disparo.
echo "== 1. codigo e listas para $HOST:$DEST"
ssh "$HOST" "install -d -m 700 $DEST"
rsync -a --relative \
  scripts/send_campaign_batch.py \
  scripts/campaign_stats.py \
  ai-generated-messages/broadcast-body.html \
  data/campaign/lote-10.csv \
  data/campaign/lote-11.csv data/campaign/lote-12.csv \
  data/campaign/lote-13.csv data/campaign/lote-14.csv \
  "$HOST:$DEST/"
rsync -a deploy/campanha/avisar.sh "$HOST:$DEST/avisar.sh"
ssh "$HOST" "chmod 700 $DEST/avisar.sh && chmod -R go-rwx $DEST"

echo "== 2. chave em $ENV_FILE (so root le)"
printf 'RESEND_API_KEY=%s\n' "$RESEND_API_KEY" |
  ssh "$HOST" "install -m 600 /dev/stdin $ENV_FILE"

echo "== 3. units"
escrever_no_droplet /etc/systemd/system/campanha@.service <<UNIT
[Unit]
Description=Envia %i do convite beta pelo Resend
After=network-online.target
Wants=network-online.target
OnFailure=campanha-falhou@%i.service

[Service]
Type=oneshot
WorkingDirectory=$DEST
EnvironmentFile=$ENV_FILE
Environment=TZ=$FUSO
ExecStartPre=$UV run --no-project --with httpx python scripts/campaign_stats.py --portao %i
ExecStart=$UV run --no-project --with httpx python scripts/send_campaign_batch.py %i
UNIT

escrever_no_droplet /etc/systemd/system/campanha-falhou@.service <<UNIT
[Unit]
Description=Avisa por email que %i nao saiu

[Service]
Type=oneshot
EnvironmentFile=$ENV_FILE
ExecStart=$DEST/avisar.sh %i
UNIT

for item in "${AGENDA[@]}"; do
  lote="${item%%:*}"
  data="${item##*:}"
  escrever_no_droplet "/etc/systemd/system/campanha@${lote}.timer" <<UNIT
[Unit]
Description=Agenda do ${lote}

[Timer]
OnCalendar=${data} ${HORA} ${FUSO}
Persistent=false

[Install]
WantedBy=timers.target
UNIT
done

ssh "$HOST" "systemctl daemon-reload"

PRIMEIRO="${AGENDA[0]%%:*}"
echo "== 4. conferindo antes de ligar (nao envia nada)"
# O dry-run e o que pode abortar: ele prova que o codigo, o corpo do email e a
# lista estao de pe. O portao aqui e so informativo, porque ele barra de proposito
# enquanto o lote anterior nao tiver saido, e isso nao e motivo para nao agendar.
ssh "$HOST" "cd $DEST && set -a && . $ENV_FILE && set +a &&
  $UV run --no-project --with httpx python scripts/send_campaign_batch.py $PRIMEIRO --dry-run"
echo "-- portao de $PRIMEIRO agora (informativo):"
ssh "$HOST" "cd $DEST && set -a && . $ENV_FILE && set +a &&
  $UV run --no-project --with httpx python scripts/campaign_stats.py --portao $PRIMEIRO" || true

echo "== 5. ligando os timers"
for item in "${AGENDA[@]}"; do
  ssh "$HOST" "systemctl enable --now campanha@${item%%:*}.timer"
done
ssh "$HOST" "systemctl list-timers 'campanha@*' --all --no-pager"

cat <<'FIM'

Pronto. Para cancelar um lote:
  ssh lekture-sfu systemctl disable --now campanha@lote-9.timer
Para ver o que aconteceu num disparo:
  ssh lekture-sfu journalctl -u campanha@lote-8 -n 50
FIM
