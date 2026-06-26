# twitch-carol

Um ajudante automático para a sua live na Twitch.

Ele fica ligado junto com a sua transmissão e cuida de três coisas sozinho:
mostra avisos bonitos na tela quando alguém te ajuda, vigia o chat para tirar
mensagens feias, e avisa na tela quando você recebe um Pix.

Tudo funciona junto, em um programa só.

## O que ele faz

### 1. Avisos de inscrição (sub) na tela
Quando alguém se inscreve no seu canal, renova a inscrição ou dá inscrições de
presente para outras pessoas, aparece um aviso animado na sua transmissão
agradecendo. Você não precisa ficar olhando o chat para perceber.

Funciona para:
- Inscrição nova
- Renovação de inscrição (com a mensagem que a pessoa escreveu)
- Inscrição dada de presente

### 2. Vigia o chat e tira mensagem feia
O programa lê as mensagens do chat e compara com uma lista de palavras proibidas
(palavrão, ofensa, conteúdo adulto). Quando alguém manda uma mensagem feia, ele
apaga na hora. Se você quiser, ele também pode deixar a pessoa de castigo
(timeout) por um tempo.

A lista de palavras já vem pronta em português e você pode aumentar ou diminuir
quando quiser. É um arquivo de texto simples.

### 3. Avisos de Pix (doação) na tela
Quando alguém te manda um Pix pelo LivePix, aparece um aviso na sua transmissão
com o valor e o nome de quem ajudou. Assim seus espectadores veem o
agradecimento ao vivo.

### Onde os avisos aparecem
Os avisos são mostrados por uma "telinha" (chamada de overlay) que você coloca
dentro do OBS. É a mesma ideia dos alertas de Streamlabs e StreamElements.

## O que você precisa antes de começar

1. Um computador com o programa Python instalado (versão 3.11 ou mais nova).
2. O OBS (o programa que você usa para transmitir).
3. Uma conta de aplicativo na Twitch (é de graça, criada no site de
   desenvolvedores da Twitch).
4. Uma conta no LivePix com acesso de aplicativo (para receber os avisos de Pix).

Se você não tem as contas de aplicativo da Twitch e do LivePix, peça ajuda para
alguém de confiança que entenda um pouco. É algo que se faz uma vez só.

## Como instalar (passo a passo)

Abra o programa "Terminal" do seu computador e digite os comandos abaixo, um de
cada vez, apertando Enter depois de cada linha.

1. Entrar na pasta do projeto:
   ```
   cd caminho/para/twitch-carol
   ```

2. Criar um espaço separado para o programa:
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Instalar as peças que o programa precisa:
   ```
   pip install -r requirements.txt
   ```

Pronto, está instalado. Você só faz isso uma vez.

## Como configurar

O programa precisa saber as suas senhas e códigos de acesso. Eles ficam em um
arquivo chamado `.env`.

1. Faça uma cópia do arquivo de exemplo:
   ```
   cp env.example .env
   ```

2. Abra o arquivo `.env` em qualquer editor de texto e preencha os campos vazios.
   O próprio arquivo tem uma explicação curta ao lado de cada campo. Os
   principais são:
   - Os dados da sua conta de aplicativo da Twitch.
   - Os dados da sua conta de aplicativo do LivePix.
   - Uma "senha secreta" que você inventa para o Pix (qualquer texto serve, só
     não conte para ninguém).

Importante: esse arquivo `.env` tem informação sigilosa. Nunca mande ele para
ninguém e nunca coloque na internet.

## Como ligar o programa

Com tudo instalado e configurado, ligue o programa assim:

```
source .venv/bin/activate
python main.py
```

Deixe essa janela aberta enquanto estiver transmitindo. Para desligar, clique na
janela e aperte as teclas Control e C ao mesmo tempo.

Na primeira vez, a Twitch vai pedir para você autorizar o programa. Basta abrir o
endereço que aparece na tela e clicar em permitir, com a conta do robô e com a
sua conta de canal.

## Como colocar os avisos no OBS

1. No OBS, crie uma nova "Fonte" do tipo "Fonte do Navegador" (Browser Source).
2. No campo de endereço, coloque:
   ```
   http://127.0.0.1:8080/overlay
   ```
3. Posicione a telinha onde você quiser na sua transmissão.

A partir daí, todo aviso de inscrição e de Pix vai aparecer ali sozinho.

## Como mudar a lista de palavras proibidas

A lista fica no arquivo `nsfw_words_pt.txt`. É um texto comum, com uma palavra
por linha. Para deixar o chat mais limpo, é só adicionar mais palavras, uma
embaixo da outra. Para liberar alguma palavra, é só apagar a linha dela.

As linhas que começam com `#` são só comentários para te ajudar a se organizar.
Elas não contam como palavra proibida.

## Perguntas comuns

**Os avisos não aparecem no OBS.**
Confira se o programa está ligado (a janela do Terminal precisa estar aberta) e
se o endereço da Fonte do Navegador está exatamente igual ao de cima.

**O aviso de Pix não chega.**
O LivePix precisa conseguir falar com o seu computador pela internet. Para isso
você usa um programa que cria um endereço público temporário (por exemplo o
ngrok). Depois coloque esse endereço público nas configurações de aviso do
LivePix. Se precisar, peça ajuda para configurar essa parte.

**O programa tirou uma mensagem que não era ruim.**
Abra o arquivo `nsfw_words_pt.txt` e apague a palavra que causou isso.

**O programa deixou passar uma mensagem ruim.**
Abra o arquivo `nsfw_words_pt.txt` e adicione a palavra que faltou.
