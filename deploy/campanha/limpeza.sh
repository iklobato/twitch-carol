#!/usr/bin/env bash
# Apaga do droplet os dados da campanha depois do ultimo lote. Roda por timer em
# 2026-08-12, um dia depois do lote-14.
#
# Vive em /usr/local/sbin de proposito, e nao em /opt/streamintel-campanha: um
# script nao pode apagar o diretorio onde ele mesmo esta sendo lido.
set -euo pipefail

DEST=/opt/streamintel-campanha
ENV_FILE=/etc/streamintel-campanha.env
UV=/root/.local/bin/uv
ULTIMO="lote-14"

[[ -d $DEST ]] || { echo "$DEST nao existe, nada a apagar"; exit 0; }

cd "$DEST"
set -a
# shellcheck disable=SC1090  # caminho fixo definido acima, nao e entrada de usuario
. "$ENV_FILE"
set +a

# Trava: se o portao barrou algum lote no caminho, o ultimo nunca saiu, e apagar
# aqui jogaria a fila no lixo. Melhor falhar e mandar email.
if $UV run --no-project --with httpx python scripts/campaign_stats.py |
  grep -q "^$ULTIMO: nao enviado"; then
  echo "$ULTIMO ainda nao saiu: nao apago nada"
  exit 1
fi

resumo=$($UV run --no-project --with httpx python scripts/campaign_stats.py || true)
curl -sS -X POST https://api.resend.com/emails \
  -H "Authorization: Bearer ${RESEND_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg corpo "$resumo" '{
        from: "Henrique <henrique@send.streamintel.cc>",
        to: ["henrique@send.streamintel.cc"],
        subject: "campanha: lotes enviados, apagando os dados do droplet",
        text: $corpo
      }')" >/dev/null

cd /
for lote in lote-10 lote-11 lote-12 lote-13 lote-14; do
  systemctl disable "campanha@${lote}.timer" >/dev/null 2>&1 || true
done
rm -rf "$DEST"
rm -f "$ENV_FILE"
systemctl disable campanha-limpeza.timer >/dev/null 2>&1 || true
echo "apagados: $DEST e $ENV_FILE"
