# Turning on email

Jarvis reads your mail over IMAP using an **app password** — a separate
password that only this program knows. Your real Google password is never
typed into it, and you can revoke the app password on its own at any time
without changing anything else.

This takes about two minutes.

---

## 1. Two-step verification has to be on

App passwords only exist on accounts with 2-step verification enabled.

Go to **myaccount.google.com/security** and check that 2-Step Verification
says **On**. If it does not, turn it on first — it needs your phone.

## 2. Create the app password

Go to **myaccount.google.com/apppasswords**

If that page says the option is not available, it is one of three things:

- 2-step verification is not on yet (step 1)
- you are signed into the wrong Google account — check the avatar, top right
- your Workspace administrator has switched app passwords off for the whole
  organisation. If that is you, it is in the Google Admin console under
  Security → Access and data control → Less secure apps. If it is not you,
  whoever runs your Workspace has to allow it.

Type a name — `Jarvis` is fine, it is only a label — and press **Create**.

Google shows you sixteen letters in four blocks, like `abcd efgh ijkl mnop`.
**Copy it now.** The page will not show it again.

## 3. Put it in settings.txt

Open `settings.txt` in Notepad and fill in the two lines:

```
GMAIL_ADDRESS=you@yourcompany.com
GMAIL_APP_PASSWORD=abcd efgh ijkl mnop
```

The spaces do not matter — paste it however Google gave it to you.

## 4. Check it

Run **check.bat**. Under `Email` it should say `Connected to you@...`.

---

## If it will not connect

**"The mail server rejected the login"** — the app password is wrong, or it is
your normal password rather than an app password. Create a fresh one; they are
free and you can have several.

**"IMAP is switched off"** — in Gmail, go to Settings (the gear) → See all
settings → Forwarding and POP/IMAP → Enable IMAP → Save Changes. On a
Workspace account an administrator may have disabled it for everyone.

**Nothing happens for a long time, then it fails** — a firewall or VPN is
blocking port 993. That is the standard secure IMAP port.

---

## What it can and cannot do with your mail

Can:

- list what has arrived recently
- search by sender, subject, or any text
- read a message out loud
- write a reply into your Drafts folder

Cannot:

- delete anything, ever
- move, archive, or label anything
- mark anything as read — messages are fetched in a way that leaves the unread
  flag alone, so opening one by voice does not change what you see in Gmail

Sending is possible but switched behind a spoken confirmation, and the
assistant is instructed to prefer drafting. If you would rather it could never
send at all, delete the `GMAIL_APP_PASSWORD` line after you have the drafts
working — reading uses the same credential, so this is all-or-nothing for now.
