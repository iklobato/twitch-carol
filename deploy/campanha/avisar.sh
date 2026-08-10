#!/usr/bin/env bash
# Avisa por email que um lote da campanha nao saiu. Roda no OnFailure da unit,
# ou seja, so existe para o caso em que ninguem esta olhando o droplet.
set -euo pipefail

lote="${1:?uso: avisar.sh <lote>}"
: "${RESEND_API_KEY:?RESEND_API_KEY nao esta no ambiente}"

read -r -d '' corpo <<EOF || true
O envio do ${lote} nao aconteceu: o portao barrou ou o disparo falhou.
No droplet: journalctl -u campanha@${lote} -n 50
EOF

curl -sS -X POST https://api.resend.com/emails \
  -H "Authorization: Bearer ${RESEND_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg assunto "campanha: ${lote} nao saiu" --arg corpo "${corpo}" '{
        from: "Henrique <henrique@send.streamintel.cc>",
        to: ["henrique@send.streamintel.cc"],
        subject: $assunto,
        text: $corpo
      }')"
