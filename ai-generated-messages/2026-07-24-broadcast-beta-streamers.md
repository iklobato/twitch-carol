# Broadcast beta streamers (220 contatos, 5 lotes)

Data: 2026-07-24
Remetente: `Henrique <henrique@send.streamintel.cc>` | reply-to: `tiktachack@gmail.com`
Lista: `data/campaign/lote-1..5.csv`
Sem merge tags: a lista so tem o email, nao tem nome nem canal.

## Assuntos

- **A** (lotes 1 e 2): `Ferramenta que analisa suas lives na Twitch (gratis na fase de testes)`
- **B** (so no lote 3, metade a metade com o A): `Qual assunto da sua live realmente paga?`

O vencedor do lote 3 vai nos lotes 4 e 5.

## Corpo (texto)

Oi, tudo bem?

Achei seu contato na bio publica do seu canal na Twitch.

Sou o Henrique, engenheiro de software. Criei o Stream Intel, uma ferramenta que analisa o historico das suas lives na Twitch com IA e mostra:

- Quais assuntos e momentos da live fazem o chat reagir mais
- O que gera mais bits e subs por hora de transmissao
- Seus melhores horarios, jogos e formatos, com base nos seus proprios dados
- Pontos de melhoria apontados por IA, live a live
- O que voce falou que ganhou ou perdeu seguidores

Por enquanto totalmente gratuito durante a fase de testes. A conexao e pelo login oficial da Twitch, somente leitura: nao posta nada, nao altera nada, e voce revoga quando quiser.

Telas e exemplos: https://streamintel.cc/howto

Duvidas ou feedback, e so responder este email, sou um humano!

Abraco,
Henrique Lobato
Criador do Stream Intel
iklobato.com | streamintel.cc

Se nao quiser receber outros emails meus, responda "sair" que removo seu contato.

## HTML do broadcast

Sem imagem, sem botao colorido, sem tabela de layout: email cold com cara de
newsletter cai mais em spam e converte menos. Isso aqui parece email escrito a mao.

O "responda sair" fica como esta, e o link de descadastro do Resend entra numa
linha pequena embaixo: a API de broadcast recusa conteudo sem ele, e o Gmail
exige o header List-Unsubscribe de quem manda em volume.

```html
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.55;color:#1a1a1a;max-width:560px">
  <p>Oi, tudo bem?</p>
  <p>Achei seu contato na bio pública do seu canal na Twitch.</p>
  <p>Sou o Henrique, engenheiro de software. Criei o <strong>Stream Intel</strong>, uma ferramenta que analisa o histórico das suas lives na Twitch com IA e mostra:</p>
  <ul style="padding-left:20px">
    <li>Quais assuntos e momentos da live fazem o chat reagir mais</li>
    <li>O que gera mais bits e subs por hora de transmissão</li>
    <li>Seus melhores horários, jogos e formatos, com base nos seus próprios dados</li>
    <li>Pontos de melhoria apontados por IA, live a live</li>
    <li>O que você falou que ganhou ou perdeu seguidores</li>
  </ul>
  <p>Por enquanto totalmente gratuito durante a fase de testes. A conexão é pelo login oficial da Twitch, somente leitura: não posta nada, não altera nada, e você revoga quando quiser.</p>
  <p>Telas e exemplos: <a href="https://streamintel.cc/howto" style="color:#7b3fe4;font-weight:600">https://streamintel.cc/howto</a></p>
  <p>Dúvidas ou feedback, é só responder este email, sou um humano!</p>
  <p>Abraço,<br>
  Henrique Lobato<br>
  <span style="color:#666">Criador do Stream Intel<br>
  iklobato.com | streamintel.cc</span></p>
  <p>Se não quiser receber outros emails meus, responda "sair" que removo seu contato.</p>
  <p style="font-size:12px;color:#888"><a href="{{{RESEND_UNSUBSCRIBE_URL}}}" style="color:#888">Descadastrar com um clique</a></p>
</div>
```

## Segunda leva: lotes 6 a 10 (521 leads novos)

Lista vinda do `scripts/prospect_leads.py` (streamers pt de 100 a 5.000
seguidores, nao-parceiros, nunca contatados). Rampa de 5 dias, um lote por dia:

| Lote | Emails | Status |
|---|---|---|
| lote-6 | 50 | enviado 2026-07-24 22:51 (BRT) |
| lote-7 | 80 | enviado 2026-07-24 23:00 (BRT) |
| lote-8 | 120 | agendado 2026-07-28 (terca) 10h BRT |
| lote-9 | 150 | esperando o portao do lote-8 |
| lote-10 | 121 | esperando |

Situacao em 2026-07-25 21h BRT, 150 enviados (lotes 1, 6 e 7): **150 entregues,
0 bounce, 0 spam, 0 resposta** na caixa do reply-to. Numeros medidos com
`python scripts/campaign_stats.py`, nao estimados.

Nao existe numero de abertura, e nao vai existir: o `open_tracking` esta
desligado no dominio. Pixel de rastreio pesa contra um dominio novo, e o numero
que ele daria vem inflado pelo Gmail e pelo Apple Mail. Quem decide o proximo
lote e cadastro no app e resposta no reply-to.

Os lotes 6 e 7 sairam com poucos minutos de diferenca, e nao com um dia entre
eles como a rampa pede. Sairam tambem numa sexta a noite, o pior horario da
semana, o que explica bem o silencio: 130 emails, nenhuma resposta. Por isso o
lote-8 volta para a janela de terca a quinta as 10h.

Envio: `RESEND_API_KEY=... python scripts/send_campaign_batch.py lote-8`
(sempre com `--dry-run` antes).
Conferir entrega: `RESEND_API_KEY=... python scripts/campaign_stats.py`.

Esses lotes saem pela API `/emails/batch`, nao por broadcast. Consequencia: o
marcador `{{{RESEND_UNSUBSCRIBE_URL}}}` do HTML acima so vale no broadcast, e o
sender **remove esse paragrafo inteiro** no envio por API. Nao tire o marcador do
arquivo, o sender falha de proposito se ele sumir.

Por que remover em vez de trocar por um mailto: link apontando para fora do
dominio remetente e sinal de spam, e o Resend acusa isso na revisao da campanha.
O opt-out continua existindo em dois lugares: a linha "responda sair" no corpo e
o cabecalho `List-Unsubscribe`.

O cabecalho aponta para `tiktachack@gmail.com`, e nao para um endereco
`@streamintel.cc`, de proposito: em 2026-07-25 um teste de entrega para
`sair@streamintel.cc` ficou em `delivery_delayed` (o Email Routing da Cloudflare
adiou), ou seja, o endereco nao e destino confiavel. Endereco de descadastro que
nao chega e pior que um que nao casa com o dominio. Se o roteamento for
arrumado na Cloudflare, basta apontar `REPLY_TO` no sender para o endereco novo.

Atualizacao 2026-07-25: um novo teste para `sair@streamintel.cc` foi entregue e
chegou na caixa, ou seja, o roteamento voltou. Mesmo assim o `REPLY_TO` fica no
Gmail durante esta leva: trocar o endereco no meio da rampa mistura duas
variaveis, e o ganho (alinhar com o dominio remetente) e pequeno perto do risco
de um pedido de "sair" se perder num atraso da Cloudflare.

Lotes 6 e 7 sairam antes desta correcao, com o mailto do Gmail visivel no corpo.

## Agendamento no droplet (lotes 8, 9 e 10)

Os tres ultimos lotes ficam agendados no droplet `lekture-sfu`, que ja roda
trabalho agendado com systemd. Assim o envio nao depende do notebook ligado.

`./deploy/campanha/instalar.sh` copia o sender, o portao, o corpo do email e os
tres CSVs para `/opt/streamintel-campanha`, poe a chave em
`/etc/streamintel-campanha.env` (600, so root le) e cria um timer por lote:
terca 28, quarta 29 e quinta 30 de julho as 10h de Sao Paulo.

Antes de cada disparo o systemd roda `campaign_stats.py --portao <lote>`, e o
envio so acontece se ele sair com 0. O portao barra em quatro casos: o lote ja
foi enviado (timer disparado duas vezes nao manda o mesmo email de novo), o lote
anterior nao saiu (a fila nao pula), bounce do anterior em 3% ou mais, ou
qualquer reclamacao de spam. Quando barra, um `OnFailure` manda email avisando.

`Persistent=false` de proposito: se o droplet estiver fora do ar as 10h, o lote
nao sai, em vez de sair de madrugada quando ninguem esta olhando.

Cancelar: `ssh lekture-sfu systemctl disable --now campanha@lote-9.timer`.
Ver o que aconteceu: `ssh lekture-sfu journalctl -u campanha@lote-8 -n 50`.

## Checklist antes de disparar cada lote

- [ ] bounce duro do lote anterior abaixo de 3% (`scripts/campaign_stats.py`)
- [ ] zero reclamacao de spam (mesmo script)
- [ ] contar cadastro novo no app e resposta no reply-to desde o lote anterior:
      dois lotes seguidos com zero dos dois = parar a rampa e mudar o texto,
      nao mandar o proximo lote
- [ ] enviar entre terca e quinta, 10h
- [ ] tirar da lista quem respondeu "sair" no lote anterior
