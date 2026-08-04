# Convite beta para streamers

Comecou em 2026-07-24 como um broadcast de 220 contatos em 5 lotes. Estado em
2026-08-03:

| | |
|---|---|
| Remetente | `Henrique <henrique@send.streamintel.cc>`, reply-to `tiktachack@gmail.com` |
| Plano do Resend | Pro (50 mil/mes, sem teto diario). Julho fechou com 427 enviados |
| Emails coletados na base | **139.567** candidatos, 10.736 com email e nao contatados |
| Contatados de verdade | **541** (lotes 1, 6, 7, 8, 9 e 10), conferido na API do Resend |
| Na fila | 946 |
| Parados esperando traducao | **4.417 leads em ingles** |
| Reclamacao de spam desde o inicio | **zero** |
| Onde roda | so o actor do Apify; o droplet foi destruido em 2026-08-03 |

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
| lote-10 | 121 | enviado 2026-07-30 10h BRT pelo timer. 119 entregues, 2 bounce = 1,7%. **Ultimo lote que saiu** |

## Terceira leva: a rampa que nao aconteceu (agosto)

O plano era quatro degraus terca a quinta, cada um com o portao medindo o
anterior. **Nenhum deles saiu.** O droplet foi destruido em 2026-08-03, antes do
primeiro:

| Lote | Emails | Plano | O que houve |
|---|---|---|---|
| lote-11 | 200 | ter 2026-08-04 | nao saiu |
| lote-12 | 250 | qua 2026-08-05 | nao saiu |
| lote-13 | 300 | qui 2026-08-06 | nao saiu |
| lote-14 | 176 | ter 2026-08-11 | nao saiu |

O caro nao foi o atraso, foi o silencio: o historico do actor tinha sido semeado
em 2026-07-29 ja contando esses quatro lotes como enviados, para o handover
funcionar. Como o droplet nao cumpriu a parte dele, **657 pessoas ficaram marcadas
como contatadas sem nunca ter recebido nada** (457 dos lotes 11 a 14, e 200 que
eram os lotes 2 a 5 inteiros, orfaos desde a troca de broadcast por envio via
API). Nenhuma delas voltaria a ser escolhida, porque `already_contacted()` as
exclui para sempre.

Corrigido em 2026-08-03 refazendo o estado com a API do Resend como fonte da
verdade: `contatados` de 1.198 para 541, fila de 289 para 946, historico so com o
`lote-10`, `proximo_lote` de 15 para 11. **Nunca semear estado com trabalho que
ainda nao aconteceu.**

A rampa recomeca de onde parou de verdade: 121 (lote-10) -> 160, nao os 300 que o
plano ja supunha conquistados. Nenhum degrau sobe mais de um terco. Pular de 150
para 500 num dominio de duas semanas e o caminho curto para a caixa de spam. O
plano do Resend e Pro (50 mil/mes, sem teto diario), entao o limite aqui nao e
cota, e reputacao.

**Autenticacao conferida em 2026-07-29** (e por isso que a entrega esta em 96%):
DKIM publicado em `resend._domainkey.send.streamintel.cc`, SPF em
`send.send.streamintel.cc` (`include:amazonses.com`), DMARC em `streamintel.cc`
com `p=none` e relatorio chegando no Gmail, e o return-path apontando para o
feedback do SES.

## Desde 03/08: so o actor

O droplet foi destruido no meio da rampa, entao o handover deixou de ser uma data
e virou o unico caminho. Quem manda e o actor no Apify, com duas schedules:
colheita todo dia 03h (que qualifica e empilha na fila sozinha, sem ninguem montar
lote) e envio de segunda a sexta as 10h, ate `maximo_por_dia`, hoje **160**,
recalculado sobre o lote-10.

O teto e seguro por construcao: o portao roda antes de cada disparo, entao se a
rampa nao aguentar o envio nao sai, independente do teto configurado. Mas o portao
mede entrega, nunca tamanho: quem impede o salto de 121 para 300 e o teto, nao
ele.

Duas armadilhas do Apify, medidas em 2026-08-03 girando a chave do Resend:

- Variavel de ambiente e **assada na imagem**. Trocar o segredo nao muda nada para
  builds ja feitos; sem reconstruir o actor, o container segue com a chave velha e
  o Resend responde `400 API key is invalid` (nao 401).
- Para conferir a credencial **sem mandar email**, aponte `proximo_lote` para um
  lote ja enviado: o portao consulta o Resend antes de qualquer disparo, entao um
  run que chega em `PORTAO BLOQUEADO` ja provou que a chave funciona.

**Idioma e a trava principal da integridade.** A coleta varre portugues e ingles
(`sweep --idiomas pt,en`, gratuito), mas o `qualify` so deixa portugues entrar na
fila de envio. Os ~4.700 canais em ingles ficam guardados na base sem custo ate a
interface do app existir em ingles: convite em ingles levando para um dashboard em
portugues gera cadastro que desiste na primeira tela, e reclamacao de spam de quem
se sentiu enganado. Reclamacao de spam e o unico numero que o portao trata como
fatal.

**Limpeza: resolvida por acidente.** Havia um timer para 2026-08-12 03h
(`campanha-limpeza.timer`, fonte em `deploy/campanha/limpeza.sh`) que apagaria
`/opt/streamintel-campanha` e `/etc/streamintel-campanha.env`, com trava para nao
apagar nada se o `lote-14` nao tivesse saido. Ele nunca chegou a rodar: o droplet
foi destruido antes, e os dados de terceiros e a chave foram junto com o disco. O
resultado certo veio pelo caminho errado, e a trava (testada de verdade em
2026-07-29, quando recusou) nunca precisou agir.

Detalhe que vale para qualquer droplet: o IP `138.197.100.60` foi reciclado para
outro cliente da DigitalOcean em poucas horas, e a chave de host SSH mudou. Nao
faca ssh no IP de um droplet morto.

**Depois do ultimo lote**, dois acertos de integridade que valem mais que a
campanha: subir o DMARC de `p=none` para `quarantine` (hoje qualquer um pode
falsificar o dominio, e isso nao afeta a entrega do email proprio, que ja esta
alinhado), e manter volume constante em vez de silencio, porque dominio que manda
300 por dia e desaparece por semanas entrega pior do que um que manda pouco todo
dia. O `weekly_digest.py`, parado no repo, serve para isso.

Deixou de ser teoria: com a morte do droplet o dominio ficou **cinco dias em
silencio** (30/07 a 04/08). Nao ha como medir o estrago sozinho, mas e mais um
motivo para o lote-11 recomecar em 160 e nao em 300.

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

## ~~Agendamento no droplet~~ (historico, o droplet nao existe mais)

Ate 2026-08-03 os lotes ficavam agendados no droplet `lekture-sfu` por systemd,
instalados com `./deploy/campanha/instalar.sh`. **O droplet foi destruido e os
comandos abaixo nao servem mais**; o registro fica pelo desenho, que continua
valendo no actor.

O que sobreviveu conceitualmente: antes de cada disparo roda
`campaign_stats.py --portao <lote>`, e o envio so acontece se ele sair com 0. O
portao barra em quatro casos: o lote ja foi enviado (disparo repetido nao manda o
mesmo email de novo), o lote anterior nao saiu (a fila nao pula), bounce do
anterior em 3% ou mais, ou qualquer reclamacao de spam.

O que se perdeu na mudanca e vale recriar: o `OnFailure` do systemd mandava email
quando o portao barrava. No Apify isso nao existe por padrao, e um run que
**sucede sem enviar** (fila abaixo do minimo, ou portao barrando) nao avisa
ninguem. Conferir com `campaign_stats.py` depois do horario continua sendo a
unica forma de saber.

`Persistent=false` era de proposito: droplet fora do ar as 10h significava lote
nao enviado, em vez de disparo de madrugada sem ninguem olhando. O actor herda o
mesmo comportamento, porque schedule perdida no Apify tambem nao reexecuta.

## Como acompanhar hoje

```bash
set -a && . ./.env && set +a && python scripts/campaign_stats.py
```

`lote-N: X enviados` com bounce e spam por lote. Se o lote do dia aparecer como
`nao enviado`, o portao barrou ou o run falhou, e o log do run no Apify diz qual
dos dois.

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
