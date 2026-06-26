# twitch-carol

Um ajudante para a sua live na Twitch.

Ele funciona junto com a sua transmissão e cuida de três coisas: mostra avisos
na tela quando alguém te ajuda, vigia o chat e tira mensagens com palavrão, e
avisa na tela quando você recebe um Pix.

## O que ele faz

### 1. Avisos de inscrição (sub) na tela
Quando alguém se inscreve no seu canal, renova a inscrição ou dá inscrições de
presente para outras pessoas, aparece um aviso na sua transmissão agradecendo.

Funciona quando:
- Alguém se inscreve
- Alguém renova a inscrição (com a mensagem que a pessoa escreveu)
- Alguém dá inscrição de presente

### 2. Vigia o chat e tira mensagem
O programa lê as mensagens do chat e compara com uma lista de palavras
(palavrão, ofensa, conteúdo). Quando alguém manda uma dessas palavras, ele apaga
a mensagem na hora. Se você quiser, ele também pode deixar a pessoa de castigo
(timeout) por um tempo.

A lista já vem em português e você pode aumentar ou diminuir quando quiser. É um
arquivo de texto.

### 3. Avisos de Pix (doação) na tela
Quando alguém te manda um Pix pelo LivePix, aparece um aviso na sua transmissão
com o valor e o nome de quem ajudou.

### Onde os avisos aparecem
Os avisos são mostrados por uma telinha (chamada de overlay) que você coloca
dentro do OBS.

## O que você precisa antes de começar

1. Um computador com o programa Python (versão 3.11 ou acima).
2. O OBS (o programa que você usa para transmitir).
3. Uma conta de aplicativo na Twitch (é de graça; você cria no site de
   desenvolvedores da Twitch).
4. Uma conta no LivePix com acesso de aplicativo (para receber os avisos de Pix).

Se você não tem as contas de aplicativo da Twitch e do LivePix, peça ajuda para
alguém de confiança que entenda um pouco.

## Como instalar (passo a passo)

Abra o programa Terminal do seu computador e digite os comandos abaixo, um de
cada vez, apertando Enter depois de cada linha.

1. Entrar na pasta do projeto:
   ```
   cd caminho/para/twitch-carol
   ```

2. Criar um espaço para o programa:
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Instalar as peças que o programa precisa:
   ```
   pip install -r requirements.txt
   ```

Pronto.

## Como configurar

O programa precisa saber as suas senhas e códigos de acesso. Eles ficam em um
arquivo chamado `.env`.

1. Faça uma cópia do arquivo de exemplo:
   ```
   cp env.example .env
   ```

2. Abra o arquivo `.env` em qualquer editor de texto e preencha os campos. O
   arquivo tem uma explicação ao lado de cada campo. Os campos são:
   - Os dados da sua conta de aplicativo da Twitch.
   - Os dados da sua conta de aplicativo do LivePix.
   - Uma senha que você inventa para o Pix (qualquer texto serve; não conte para
     ninguém).

Atenção: esse arquivo `.env` tem as suas senhas. Nunca mande ele para ninguém e
nunca coloque na internet.

## Como ligar o programa

Depois de instalar e configurar, ligue o programa assim:

```
source .venv/bin/activate
python main.py
```

Não feche essa janela enquanto estiver transmitindo. Para desligar, clique na
janela e aperte as teclas Control e C ao mesmo tempo.

Na primeira vez, a Twitch vai pedir para você autorizar o programa. Basta abrir o
endereço que aparece na tela e clicar em permitir, com a conta do robô e com a
sua conta de canal.

## Como colocar os avisos no OBS

1. No OBS, crie uma Fonte do tipo Fonte do Navegador (Browser Source).
2. No campo de endereço, coloque:
   ```
   http://127.0.0.1:8080/overlay
   ```
3. Posicione a telinha onde você quiser na sua transmissão.

A partir daí, todo aviso de inscrição e de Pix vai aparecer ali.

## Como mudar a lista de palavras

A lista fica no arquivo `nsfw_words_pt.txt`. É um texto, com uma palavra por
linha. Para deixar o chat com menos palavrão, adicione mais palavras, uma
embaixo da outra. Para liberar alguma palavra, apague a linha dela.

As linhas que começam com `#` são comentários para te ajudar a se organizar.
Elas não contam como palavra da lista.

## Dúvidas

**Os avisos não aparecem no OBS.**
Confira se o programa está funcionando (a janela do Terminal precisa continuar
funcionando) e se o endereço da Fonte do Navegador é o que está acima.

**O aviso de Pix não chega.**
O LivePix precisa conseguir falar com o seu computador pela internet. Para isso
você usa um programa que cria um endereço na internet (por exemplo o ngrok).
Depois coloque esse endereço nas configurações de aviso do LivePix. Se precisar,
peça ajuda para configurar essa parte.

**O programa apagou uma mensagem que não devia.**
Abra o arquivo `nsfw_words_pt.txt` e apague a palavra que causou isso.

**O programa deixou passar uma mensagem que devia apagar.**
Abra o arquivo `nsfw_words_pt.txt` e adicione a palavra que faltou.
