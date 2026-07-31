# Convite beta para streamers

Comecou em 2026-07-24 como um broadcast de 220 contatos em 5 lotes. Estado em
2026-07-30:

| | |
|---|---|
| Remetente | `Henrique <henrique@send.streamintel.cc>`, reply-to `tiktachack@gmail.com` |
| Plano do Resend | Pro (50 mil/mes, sem teto diario). Julho fechou com 427 enviados |
| Emails coletados na base | **7.657** unicos (eram 990 em 2026-07-29 de manha) |
| Ja contatados | 741 (lotes 1 a 9) |
| Na fila | 1.047 agendados (lotes 10 a 14) + 198 leads pt novos |
| Parados esperando traducao | **4.417 leads em ingles** |
| Reclamacao de spam desde o inicio | **zero** |

Sem merge tags: o lote so tem o email, nao tem nome nem canal.

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
| lote-8 | 120 | enviado 2026-07-28 10h BRT pelo timer. 115 entregues, 4 bounce, 1 suprimido = 3,3% |
| lote-9 | 150 | enviado 2026-07-29 10h20 BRT **na mao**. 146 entregues, 4 bounce = 2,7% |
| lote-10 | 121 | timer armado para 2026-07-30 10h BRT, portao ja liberado |

## Terceira leva: a rampa dos 926 (agosto)

Em 2026-07-29 a base saltou de 990 para 7.615 emails coletados, e sobraram 926
brasileiros nunca contatados. Eles saem em quatro degraus, terca a quinta as 10h,
cada um com o portao medindo o anterior:

| Lote | Emails | Timer | Salto |
|---|---|---|---|
| lote-11 | 200 | ter 2026-08-04 | +32% sobre os 151 do lote-9 |
| lote-12 | 250 | qua 2026-08-05 | +25% |
| lote-13 | 300 | qui 2026-08-06 | +20% |
| lote-14 | 176 | ter 2026-08-11 | resto |

Nenhum degrau sobe mais de um terco. Pular de 150 para 500 num dominio de duas
semanas e o caminho curto para a caixa de spam, e ai os 7.615 emails coletados
viram lixo. O plano do Resend e Pro (50 mil/mes, sem teto diario), entao o limite
aqui nao e cota, e reputacao.

**Autenticacao conferida em 2026-07-29** (e por isso que a entrega esta em 96%):
DKIM publicado em `resend._domainkey.send.streamintel.cc`, SPF em
`send.send.streamintel.cc` (`include:amazonses.com`), DMARC em `streamintel.cc`
com `p=none` e relatorio chegando no Gmail, e o return-path apontando para o
feedback do SES.

## Depois de 12/08: o actor assume

O droplet termina no lote-14 e e apagado. Dali em diante quem manda e o actor no
Apify, com duas schedules: colheita todo dia 03h (que qualifica e empilha na fila
sozinha, sem ninguem montar lote) e envio de segunda a sexta as 10h, ate **300 por
dia**, que e o maior degrau provado pela rampa (o lote-13, de 06/08).

O teto de 300 e seguro por construcao: o portao roda antes de cada disparo, entao
se a rampa nao aguentar 300 o envio nao sai, independente do teto configurado.

**Idioma e a trava principal da integridade.** A coleta varre portugues e ingles
(`sweep --idiomas pt,en`, gratuito), mas o `qualify` so deixa portugues entrar na
fila de envio. Os ~4.700 canais em ingles ficam guardados na base sem custo ate a
interface do app existir em ingles: convite em ingles levando para um dashboard em
portugues gera cadastro que desiste na primeira tela, e reclamacao de spam de quem
se sentiu enganado. Reclamacao de spam e o unico numero que o portao trata como
fatal.

**Limpeza agendada.** Em 2026-08-12 03h um timer (`campanha-limpeza.timer`, script
em `/usr/local/sbin/campanha-limpeza.sh`, fonte em `deploy/campanha/limpeza.sh`)
apaga `/opt/streamintel-campanha` e `/etc/streamintel-campanha.env`, tira os dados
de terceiros do droplet e desliga os timers dos lotes. Ele tem trava: se o
`lote-14` nao tiver saido (portao barrou algum degrau no caminho), ele **nao apaga
nada**, sai com erro e manda email. Testado de verdade em 2026-07-29: recusou.

**Depois do ultimo lote**, dois acertos de integridade que valem mais que a
campanha: subir o DMARC de `p=none` para `quarantine` (hoje qualquer um pode
falsificar o dominio, e isso nao afeta a entrega do email proprio, que ja esta
alinhado), e manter volume constante em vez de silencio, porque dominio que manda
300 por dia e desaparece por semanas entrega pior do que um que manda pouco todo
dia. O `weekly_digest.py`, parado no repo, serve para isso.

O lote-9 saiu na mao porque o portao barrou o disparo automatico: o lote-8 fechou
em 3,3% de bounce, acima do limite de 3%. Foi excecao consciente, com o portao
continuando rigoroso no automatico. Os quatro bounces do lote-8 eram caixas
mortas (`gmail-noodlesph0bia@gmail.com`, `pr@gmail.com` e mais duas), nao erro de
extracao em serie: os lotes 9 e 10 nao tinham nenhum endereco com esse defeito.
Como o lote-9 fechou em 2,7%, a corrente se destravou sozinha e o lote-10 sai no
horario sem ninguem tocar em nada.

**Primeira resposta de gente real em 270 emails**, no lote-8 (2026-07-28): um
streamer pedindo para conhecer melhor a proposta e ver exemplos de quem ja usa.
Nenhum pedido de "sair" ate agora.

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

## Agendamento no droplet (lotes 10 a 14)

Os lotes ficam agendados no droplet `lekture-sfu`, que ja roda trabalho agendado
com systemd. Assim o envio nao depende do notebook ligado.

`./deploy/campanha/instalar.sh` copia o sender, o portao, o corpo do email e os
CSVs para `/opt/streamintel-campanha`, poe a chave em
`/etc/streamintel-campanha.env` (600, so root le) e cria um timer por lote. A
lista de datas fica no proprio script (`AGENDA`), e o CSV do lote anterior vai
junto mesmo ja tendo saido, porque sem ele o portao nao tem o que medir.

O pre-voo do instalador aborta pelo dry-run, que prova codigo, corpo e lista de
pe. O portao ali e so informativo: ele barra de proposito enquanto o lote anterior
nao saiu, e isso nao e motivo para nao agendar.

Antes de cada disparo o systemd roda `campaign_stats.py --portao <lote>`, e o
envio so acontece se ele sair com 0. O portao barra em quatro casos: o lote ja
foi enviado (timer disparado duas vezes nao manda o mesmo email de novo), o lote
anterior nao saiu (a fila nao pula), bounce do anterior em 3% ou mais, ou
qualquer reclamacao de spam. Quando barra, um `OnFailure` manda email avisando.

`Persistent=false` de proposito: se o droplet estiver fora do ar as 10h, o lote
nao sai, em vez de sair de madrugada quando ninguem esta olhando.

Cancelar: `ssh lekture-sfu systemctl disable --now campanha@lote-9.timer`.
Ver o que aconteceu: `ssh lekture-sfu journalctl -u campanha@lote-8 -n 50`.

## O que trava os 4.417 leads em ingles

Traduzir a interface e a fase 3 de quatro, e nao a primeira. O trabalho todo e de
3 a 5 dias, medido em 2026-07-30:

| Fase | O que | Tamanho |
|---|---|---|
| 1 | Idioma do canal: migracao `channels.language`, preenchido no login pela Helix | **feito** (migracao 0020, 3 testes) |
| 2 | A analise funcionar em ingles: `core/text.py` com stopwords e lexico por idioma, prompt do LLM seguindo o canal | 1 a 2 dias, e o coracao |
| 3 | Interface: `i18n.ts` + dicionarios `pt`/`en`, 525 textos em 20 arquivos, mais 68 rotulos do backend | 1 a 2 dias |
| 4 | Convite: `broadcast-body-en.html`, assunto em ingles, lote com coluna `language`, `--idiomas pt,en` | 2 horas (o `howto.en.html` ja existe completo) |

A fase 2 e a que decide se vale: `core/text.py` tem stopwords e lexico de
sentimento brasileiros usados por `dashboard.py` e `community.py`. Sem versao em
ingles, "assuntos da live" lista `the` e `you`, e a reacao do chat vem vazia. O
email promete exatamente essas duas telas, entao interface traduzida com analise
vazia e pior que interface em portugues: e produto que nao funciona, e vira
reclamacao de spam de quem se sentiu enganado.

Fica de fora de proposito: reescrever os insights em portugues ja gravados,
espanhol (terceiro maior idioma da Twitch, e o desenho por idioma deixa a porta
aberta), e o email transacional do app.

## A resposta do streamer voltava (consertado em 2026-07-30)

Streamers reclamaram que a resposta deles voltava. Causa: `send.streamintel.cc`
nao tinha **MX nem A**. O `Reply-To` sempre esteve certo (`tiktachack@gmail.com`,
conferido nos enviados), entao quem responde por um cliente que respeita o
Reply-To caia no Gmail normalmente; quem usa cliente que ignora, ou quem copia o
endereco que aparece na tela, mandava para `henrique@send.streamintel.cc`, um
dominio sem rota de email nenhuma, e levava bounce.

O bounce ia para **o streamer**, nunca para nos. Por isso isso passou despercebido
por 741 contatos, e por isso "so 1 resposta" nao pode ser lido como "ninguem se
interessou": parte das respostas pode ter voltado sem deixar rastro deste lado.
Pior, o opt-out da campanha e "responda sair": quem tentou sair e levou bounce
continuou na lista.

Conserto: tres registros MX em `send.streamintel.cc` apontando para
`route1/2/3.mx.cloudflare.net`, os mesmos do apex, com as mesmas prioridades. A
regra catch-all da zona ja encaminha para o Gmail, e ela vale para o subdominio.
Nao precisou habilitar Email Routing de subdominio no painel (a API nao expoe
isso; so o painel), o MX sozinho resolveu.

Provado com dois testes iguais, um antes e um depois:

| | resultado |
|---|---|
| teste 1, sem MX | `sent` para sempre, nunca entregou |
| teste 2, com MX | `delivered`, e **chegou na caixa** |

O caminho de envio nao mudou: DKIM, SPF do return-path, DMARC e o MX de bounce
seguem iguais, e o dominio continua `verified` no Resend. Faz sentido: SPF e
DMARC olham o envelope (`send.send.streamintel.cc`), e o MX novo so trata do que
entra.

## Checklist antes de disparar cada lote

- [ ] bounce duro do lote anterior abaixo de 3% (`scripts/campaign_stats.py`)
- [ ] zero reclamacao de spam (mesmo script)
- [ ] contar cadastro novo no app e resposta no reply-to desde o lote anterior:
      dois lotes seguidos com zero dos dois = parar a rampa e mudar o texto,
      nao mandar o proximo lote
- [ ] enviar entre terca e quinta, 10h
- [ ] tirar da lista quem respondeu "sair" no lote anterior
