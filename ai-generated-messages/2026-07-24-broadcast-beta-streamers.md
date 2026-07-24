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

## Checklist antes de disparar cada lote

- [ ] bounce duro do lote anterior abaixo de 3%
- [ ] zero reclamacao de spam
- [ ] abertura acima de 15%
- [ ] enviar entre terca e quinta, 10h
- [ ] tirar da lista quem respondeu "sair" no lote anterior
