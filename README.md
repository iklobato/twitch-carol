# twitch logger

Grava tudo que acontece numa live da Twitch em um arquivo de texto: o chat, a
fala do streamer (transcrita) e os eventos (sub, timeout, ban, raid, follow,
pontos do canal, live on/off). Tudo no mesmo arquivo `chat-log.txt`, uma linha
por evento, na ordem em que acontece.

## O que ele grava

- **Chat**: mensagens, sub, resub, timeout, ban, raid, mensagem apagada (leitura
  anonima, funciona em qualquer canal).
- **Fala do streamer**: transcrita com o faster-whisper (linhas com 🎤).
- **Eventos do canal** (EventSub): live comecou/terminou, follow, resgate de
  pontos. Follow e pontos so funcionam no seu proprio canal ou onde voce e mod.

Roda tudo junto em um processo so, com asyncio.

## O que voce precisa

1. Python 3.11+.
2. `ffmpeg` instalado no sistema.
3. Uma conta de aplicativo na Twitch (de graca, em dev.twitch.tv/console/apps).

## Instalar

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configurar

Copie o exemplo e preencha:

```
cp env.example .env
```

O `.env` precisa de tres valores:

- `TWITCH_CHANNEL`: o login do canal (ex: `iklobato`), nao o numero.
- `TWITCH_CLIENT_ID`: o Client-ID do seu app da Twitch.
- `TWITCH_USER_TOKEN`: um user OAuth token com os scopes
  `moderator:read:followers` e `channel:read:redemptions`. Gere em
  twitchtokengenerator.com (Custom Scope Token).

O Client-ID e o token tem que ser do mesmo app, senao a Twitch recusa os
eventos. Nunca mande o `.env` para ninguem.

## Rodar

```
python stream_logger.py
```

Para um canal diferente do `.env`, sem editar o arquivo:

```
TWITCH_CHANNEL=nomedocanal python stream_logger.py
```

O resultado vai para `chat-log.txt` na mesma pasta. Para desligar, aperte
Control e C.

## Testes

```
python test_stream_logger.py
```

## Ajustes de transcricao (opcionais, no `.env`)

- `WHISPER_MODEL`: `base`, `small` (padrao), `medium`, `large-v3`. Maior = melhor
  e mais lento.
- `WHISPER_LANG`: idioma (padrao `pt`).
- `TRANSCRIBE_CHUNK_SECONDS`: tamanho do bloco de audio (padrao 20).
