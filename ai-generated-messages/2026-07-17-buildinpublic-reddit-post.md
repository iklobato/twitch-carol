# r/buildinpublic draft: StreamIntel (v2, casual/human)

**Title:**
built a twitch analytics tool that shows streamers where their money comes from, and the ai isn't allowed to make up numbers

**Body:**

been working on this for a few weeks and wanted to drop it here. it's a twitch analytics thing called streamintel (streamintel.cc).

why i started it: i kept running into streamers who had no idea what actually made them money, or why people left in the middle of a stream. twitch throws a pile of numbers at you but doesn't really tell you anything.

so the tool just watches your stream and turns it into a report afterwards. it grabs the chat, the events (subs, bits, follows, raids), viewer count and the audio. then it transcribes the audio, finds the moments where chat blew up, and tells you what set each one off.

per stream you get a short summary, your best moments, the main topics you talked about, and a few concrete things to try next time. theres also a money page (revenue by game, best time of day to earn, a heads up when one person is basically carrying your income) and a followers page (who your fans are, who went quiet, fake follower detection, and which of your followers are streamers you could collab with).

the part i'm most proud of is kind of nerdy. every number on the screen comes straight from sql. the ai only writes the words, and it has to point at a real row in the db to say anything. if it references something that isn't there, the insight gets thrown out. so it literally can't invent a stat. every insight links back to the actual chat messages or the exact thing you said.

stack is fastapi + react, postgres for everything (even the job queue and the dedup, no redis), whisper for transcription. the llm is swappable, runs fully local on my machine in dev and a hosted model in prod. deploys on a git push.

it's in beta and free to connect, read only, tokens are encrypted.

anyway, curious what people think, especially if you stream or have built analytics stuff before. what would actually make a report like this worth opening every week?
