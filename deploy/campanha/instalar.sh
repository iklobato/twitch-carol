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
AGENDA=("lote-8:2026-07-28" "lote-9:2026-07-29" "lote-10:2026-07-30")
HORA="10:00"
FUSO="America/Sao_Paulo"

: "${RESEND_API_KEY:?RESEND_API_KEY nao esta no ambiente (use o do .env)}"
[[ -f scripts/send_campaign_batch.py ]] || { echo "rode da raiz do repo"; exit 1; }

# Conteudo vem pelo stdin. As variaveis do heredoc sao expandidas aqui de
# proposito (caminhos e datas sao decididos neste script, nao no droplet).
escrever_no_droplet() {
  ssh "$HOST" "cat > '$1'"
}

# O lote-7 vai junto mesmo ja tendo sido enviado: sem a lista dele o portao nao
# consegue medir o bounce do lote anterior ao lote-8, e barra o primeiro disparo.
echo "== 1. codigo e listas para $HOST:$DEST"
ssh "$HOST" "install -d -m 700 $DEST"
rsync -a --relative \
  scripts/send_campaign_batch.py \
  scripts/campaign_stats.py \
  ai-generated-messages/broadcast-body.html \
  data/campaign/lote-7.csv \
  data/campaign/lote-8.csv data/campaign/lote-9.csv data/campaign/lote-10.csv \
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

echo "== 4. conferindo antes de ligar (nao envia nada)"
ssh "$HOST" "cd $DEST && set -a && . $ENV_FILE && set +a &&
  $UV run --no-project --with httpx python scripts/campaign_stats.py --portao lote-8 &&
  $UV run --no-project --with httpx python scripts/send_campaign_batch.py lote-8 --dry-run"

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
