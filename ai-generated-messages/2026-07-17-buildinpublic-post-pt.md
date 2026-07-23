# Post buildinpublic: StreamIntel (versão PT-BR, casual/humano)

oi, faz umas semanas que tô trabalhando nisso e queria compartilhar aqui. é uma ferramenta de analytics pra twitch chamada streamintel https://streamintel.cc/howto

por que comecei: passei a assistir bastante twitch ultimamente, e me veio essa ideia de que o streamer podia saber qual assunto ou tema traz mais dinheiro pra ele. tem muita gente tentando viver de twitch.

a ferramenta simplesmente acompanha a sua live e transforma ela num relatório depois. ela pega o chat, os eventos (subs, bits, follows, raids), a contagem de viewers e o áudio. aí transcreve o áudio, acha os momentos onde o chat explodiu e cruza todos os dados, e te diz o que causou cada um.

por live você recebe um resumo curto, seus melhores momentos, os principais assuntos que você falou, e algumas coisas concretas pra testar na próxima. tem também uma página de dinheiro (receita por jogo, melhor horário do dia pra faturar, um aviso quando uma pessoa só tá basicamente segurando toda a sua renda) e uma página de seguidores (quem são seus fãs, quem sumiu, detecção de fake follower, e quais dos seus seguidores são streamers com quem você podia fazer collab).

a parte que mais me orgulho é meio nerd. todo número na tela vem direto do sql. a ia só escreve o texto, e ela tem que apontar pra uma linha real no banco pra dizer qualquer coisa. se ela citar algo que não existe, o insight é descartado. então ela literalmente não consegue inventar um dado. todo insight tem link de volta pras mensagens reais do chat ou pra coisa exata que você falou.

o stack é fastapi + react, postgres pra tudo (até a fila de jobs e o dedup, sem redis), whisper pra transcrição. a llm é trocável, roda 100% local na minha máquina em dev e um modelo hospedado em prod. deploy é num git push.

tá em beta e de graça pra conectar por enquanto, só leitura, tokens são criptografados claro

enfim, curioso pra saber o que acham, principalmente se você faz live ou já construiu coisa de analytics antes. o que faria um relatório desse valer a pena de abrir toda semana?

resumindo, o que ele faz e por que isso ajuda quem faz live:

- resumo de cada live: você entende como foi sua live sem reassistir horas de vod
- momentos de pico explicados: sabe o que fez o chat bombar, pra repetir e pra saber o que clipar
- assuntos ranqueados: descobre qual conteúdo seu prende mais a galera
- receita por jogo e por assunto: vê de onde vem sua grana de verdade, não no chute
- melhor horário do dia pra faturar: sabe quando vale mais a pena estar ao vivo
- aviso de dependência: te avisa quando uma pessoa só tá segurando quase toda sua renda (risco se ela sai)
- quedas de audiência com causa provável: sabe onde e por que perdeu gente no meio da live
- página de seguidores: quem são seus fãs, quem sumiu, quem é fake, e quais seguidores são streamers pra fazer collab
- recomendações pra próxima live: dicas concretas do que fazer mais e do que ajustar
- tudo com evidência clicável: cada número tem link pro dado real, então você confia no que tá vendo (não é achismo de ia)
