# Jarvis

A voice assistant that runs on your own Windows PC. You say "hey jarvis", it
listens, and it can answer questions, go through your email, find and read your
files, and open your programs.

---

## Getting started

Double-click **setup.bat**. It installs what it needs, opens `settings.txt` for
you to paste your API key into, and then checks everything works.

After that, **run.bat** starts it.

Three other files, for when you need them:

- **check.bat** — tests every part in turn and says what is wrong in plain
  English. Run this first whenever something misbehaves.
- **talk.bat** — the same assistant, but you type instead of speaking. Useful
  for trying things out without a microphone.
- **settings.txt** — everything you can change. It is commented throughout.

---

## What it costs to run

Two separate things, and only one of them costs money.

**Claude** is charged per use, by Anthropic, on your own API key. For one
person using it through a working day, expect roughly **$20–60 a month**. You
can see the running total and set a hard spending cap in the Anthropic console.

**Everything else is free.** The voice it speaks with uses Microsoft's neural
voices, which cost nothing. The speech recognition runs on your own PC, so it
costs nothing and works offline.

---

## Where your data goes

The microphone is transcribed **on your own machine**. Room audio never leaves
the PC — not the audio it ignored, and not the audio it acted on.

What does get sent to Anthropic is the text of what you said to it, plus
whatever a tool returned that it needs in order to answer — the subject lines
it just read, for instance. That is the same trade as typing into any AI
assistant, but it is worth knowing rather than assuming.

Your email password is never sent anywhere except to Google, and it is an app
password rather than your real one, so it can be revoked on its own.

`activity.log` records everything it heard, said, and did, so you can go back
and check. Turn it off with `LOG_ACTIONS=false` if you would rather not have
the record.

---

## What it will not do without asking

Anything that cannot be taken back stops and asks out loud first:

- sending an email (drafting does not ask)
- writing or overwriting a file

Anything actively destructive is not built at all. It cannot delete a file, and
it cannot delete, move, or archive an email. It cannot mark your mail as read
either — messages are fetched in a way that leaves the unread flag alone.

It can only see one folder, set by `WORKSPACE` in settings.txt. Every path is
resolved and checked against that folder before anything is opened, so a
misheard filename cannot walk out of it.

It can only launch programs from a fixed list. Adding one means editing
settings.txt — it is never handed a command line to run.

---

## How it is put together

```
run.bat  ->  jarvis/main.py        the loop: wake, listen, think, speak
             jarvis/audio/
               listen.py           microphone, wake word, knowing when you stopped
               stt.py              Whisper, running locally
               tts.py              speech out, with an offline fallback voice
             jarvis/brain.py       the conversation with Claude
             jarvis/tools/         what it is actually able to do
               email_gmail.py      read, search, draft, send
               files.py            find, read, write - inside one folder
               apps.py             open programs and web pages
               system.py           the clock, and what it can do
             check.py              diagnostics
```

Two deliberate choices worth explaining, because both look like the wrong call
until you know why:

**Speech recognition runs locally rather than through an API.** It is slower to
start (the model loads once, in about three seconds) and it is more to install.
In exchange, an always-on microphone is not streaming your office to a paid
endpoint, and the running cost of listening is zero.

**It thinks before it answers, even though that is slower.** Claude is asked to
reason at low effort rather than not at all. With reasoning switched off
entirely, the model will occasionally *say* "checking your email" instead of
actually calling the tool — the sentence comes out of the speakers and nothing
happens. Low effort keeps it quick without that failure.

---

## If something goes wrong

Run **check.bat**. It tests the API key, the speakers, the microphone, the
recogniser, the wake word and the email login separately, and tells you which
one failed and what to do about it.

The two most common problems:

**It cannot hear you.** Windows blocks microphone access for desktop apps by
default on some machines. Settings → Privacy & security → Microphone → let
desktop apps use it.

**The wake word does not trigger.** Set `PUSH_TO_TALK=true` in settings.txt and
press Enter to talk instead. Works everywhere, useful in a noisy room.

---

## Tested

- 36 checks on the conversation loop, including the full tool round-trip, a
  declined confirmation, and history trimming that cannot leave the
  conversation in a state the API rejects
- 86 checks on the tools, mostly on the boundaries: escaping the workspace
  folder by relative path, absolute path or symlink; non-web URL schemes;
  programs that are not on the list
- The voice pipeline end to end: four spoken phrases synthesised, played
  through the recogniser, and transcribed back word for word, at about half a
  second each
