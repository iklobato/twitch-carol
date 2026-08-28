FROM apify/actor-python:3.12

COPY .actor/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# So o que a colheita usa. O resto do repo (api, workers, web) nao entra: imagem
# menor, e nada de segredo de producao viaja junto.
COPY core/config.py core/twitch.py ./core/
# O __init__.py do repo tem 0 byte, e arquivo vazio nao chega no build do Apify.
RUN touch ./core/__init__.py
COPY scripts/prospect_leads.py scripts/build_campaign_batches.py \
     scripts/send_campaign_batch.py scripts/campaign_stats.py ./scripts/
# Todos os corpos de campanha (pt e en); enviar descobre os idiomas pelo nome.
COPY ai-generated-messages/broadcast-body.html \
     ai-generated-messages/broadcast-body-en.html ./ai-generated-messages/
COPY .actor/main.py ./

CMD ["python3", "main.py"]
