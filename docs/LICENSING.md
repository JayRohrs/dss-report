# Licensing, in plain words

## What a licence is

A licence is one small file, sent to you by Jay Rohrs. It says:

- **who it is for** (the customer name),
- **how many Restaurant365 connections** you may run (a number, or the word `unlimited`),
- **when it ends** (the expiry date),
- **which extras it includes** (feature flags, listed below),
- **"updates until"**: the last date for which new versions are included, or the word `lifetime`.

It carries a digital signature made with a private key that only Jay has. If anyone changes even one letter of the file, the signature stops matching and the program refuses it.

## Why nothing is sent anywhere

The program checks the signature **on your own computer**, using a public key built into the program. There is no licence server, no "phone home", no sign-up, no account and no network call for licensing. You can unplug the internet and the licence still works the same way. This keeps the promise in the README: your data, and now your licence, never leave your computer.

## Loading a licence

Open the settings screen, find **1. Licence**, press **Choose file**, pick the licence file, press **Load licence file**. The program checks it and, only if the signature is genuine, keeps a copy in its own folder (`%LOCALAPPDATA%\DssReport\licence.json`). A file that is changed, unsigned, signed by someone else, or not a licence at all is refused with a plain message, and any licence you already had is left untouched.

The Licence section shows, in plain words: the status line, the customer name, connections used out of allowed, the expiry date, the updates date, and what is included.

## Renewal reminders

From **30 days before** the end date, a plain notice appears at the top of the settings screen, in the Licence section, and at the top of every report and report email: `Licence expires in N days (on <date>). Renew to keep adding connections and getting updates.` After the end date it reads `Licence expired on <date> — renew to add connections or get updates.` These are reminders only. They never block a report.

## What happens in each situation

The rule behind all of it: **a licence problem never deletes or hides a report you already have.** Past reports stay on disk and can always be opened; the "view the report" page, earlier reports and the "open in my mail app" link never check the licence.

| Situation | The settings line says | What still works | What stops |
|---|---|---|---|
| Valid | `Licence: valid for <customer> until <date>.` | Everything the licence includes, up to the connection limit | - |
| Expired | `Licence: expired on <date>...` plus the renewal notice | Existing connections keep running (up to the number licensed), existing reports, the extras the licence had, demo data | Adding a connection; updates; anything new |
| Not found | `Licence: not found...` | Existing reports and demo data | Connecting to R365 (no connections are licensed); the extras that need a flag |
| Not valid (changed, wrong key, damaged) | `Licence: not valid...` plus the reason | Same as "not found" | Same as "not found" |
| Over the limit (more connections set up than the licence allows) | `Licence: over limit...` | The first connections up to the limit | The extra ones show "not connected: Licence: over limit" in the report |
| Demo data | `Licence: demo mode (made-up data, no licence needed).` | Everything built so far, so a first-time viewer is never blocked | - |

The report itself says so too: a licence problem is shown as a box at the top ("Licence: expired on ... Your reports and existing connections keep working; renew to add connections or get updates.") and a valid licence as a quiet line at the bottom.

A connection that cannot run is **never hidden**: it appears in the report as `not connected: <reason>` (licence) or `could not connect: <reason>` (R365 unreachable or sign-in refused), at the top, and the headline says some locations are UNKNOWN. It is never counted as "nothing to review".

## Connections

One licence can cover several Restaurant365 instances. Each connection has its own name, address, user name, saved password (kept in the operating system's credential store under its own entry), its own field-mapping file, and its own show/hide choices for locations. The report covers all connected instances, grouped by connection, and one instance failing never hides the others.

Adding a connection (or switching a switched-off one back on) is checked against the licence: you get `Licence: over limit. Your licence allows 2 connections and 2 are already set up.` and nothing is saved. Removing one makes room.

## Connections and flags come only from the file

The number of connections (a whole number, or `unlimited`) and the list of flags are read from the licence file and nowhere else. The program contains no prices, no plan or tier names and no built-in allowance: with no valid licence it allows zero connections. So terms can change, for example one connection for one customer, several for another, `unlimited` for the owner's own company, just by issuing a different file. A licence may be issued for 1 connection and is checked exactly like any other. Who gets what, and at what price, is the owner's business and lives outside the program.

## Features (flags)

The program asks one helper, `has_feature`, whether a flag is on. A licence file lists the flags it grants. The four flags for everything built so far are normally listed in a licence; the tool's default is to list all four.

| Flag | What it covers | Built today |
|---|---|---|
| `optional_rules` | The optional checks (today: payments add up to the sales total) | yes |
| `email_m365` | Creating or sending the email through Microsoft 365 (the "open in my mail app" link is not gated) | yes |
| `scheduling` | The automatic weekday run | yes |
| `local_ai` | The optional one-sentence summary from a model on your computer | yes |
| `hosted` | Future hosted features. Nothing is built. | no |
| `addons` | Future paid add-ons. Nothing is built. | no |

If a flag is missing, the feature says so in plain words ("Automatic schedule is not included in your licence...") and the rest of the program carries on. An unknown flag in a licence file is ignored.

## Updates

"Updates until" is the last date for which new versions are included, or the explicit word `lifetime` (no end; shown in settings as "Updates: lifetime"). Any other value makes the file refused as damaged, so a typo can never turn into lifetime updates. The program only looks for updates if the customer switches on the optional online check; otherwise the owner sends an update file (see `docs/UPDATES.md`). Running an older or a newer version is never blocked, and the settings screen only shows whether this version is inside your updates period. The date is used at one point: an update file released **after** your "updates until" date is not installed, with a plain "Renew to get it". Your current version and all your reports keep working.

---

## For Jay: making licences

The signing tool lives in `tools/` and is **not** part of the program customers receive (the installer copies only the `dssreport` folder, and a test checks that).

```
python tools/licence_tool.py keygen --out "D:\private-keys" --kid 2026-a
python tools/licence_tool.py sign --private-key "D:\private-keys\2026-a.private.key" --kid 2026-a \
    --customer "Customer Name" --instances 2 --expires 2027-03-31 --updates-until 2027-03-31 --out licence.json
python tools/licence_tool.py show licence.json
```

`sign` lists all four current flags by default; add `--features optional_rules,email_m365,...` to change it. `--instances` takes a number or `unlimited`; `--updates-until` takes a date or `lifetime`.

### Key custody: the private key is the owner's job, outside this repository

The private key is what makes a licence real. Whoever holds it can issue licences. Treat it like the keys to the business.

1. **Keep it outside every git folder.** Not in this repository, not in any other repository, not in a folder that is a copy of one. `keygen` refuses to write it inside a git working folder, `.gitignore` blocks `*.private.key` and `*.pem`, and a test fails if a key file appears in this repo.
2. **Passphrase-protect it.** `keygen` asks for a passphrase (at least 12 characters) and saves the key file encrypted with it; it will not make an unprotected key. Use a long passphrase kept in a password manager, not in a file next to the key. Signing asks for it each time.
3. **Keep an offline backup.** At least one copy on a USB drive or similar, stored somewhere safe and not connected to the internet, plus a second copy in a different place. Test that the backup works (sign a test licence with it). Back up the passphrase separately from the key.
4. **Only the public key is ever copied into the product.** The public half (64 hex characters) goes into `dssreport/licence_keys.py`. The private key file, its passphrase, and anything derived from them never go in the repository, the installer, a chat, an email or a ticket.
5. **If the key is lost or leaked:** a lost key means no new licences can be made that existing programs accept; a leaked key means anyone can make licences. Either way, make a new pair with a new key id, put the new public key in the next release alongside the old one (so existing licences still verify), and issue new licences with the new key id.

Nothing about the key goes in this repo beyond the public half. Tests never use the real key: each run makes a throw-away key in memory.

### Before a release (this repository ships with no key)

`dssreport/licence_keys.py` is **empty on purpose**. Until the real PUBLIC key is pasted in, a development build says "no licence key built in" and no real licence can be accepted. To release:

1. Run `keygen` as above on your own machine; keep the private file out of the repo.
2. Paste the printed line (`"2026-a": "<64 hex characters>"`) into `PUBLIC_KEYS` in `dssreport/licence_keys.py`.
3. Make a test licence with `sign`, load it in settings, and check the status line.

To change keys later, add the new public key under a new key id and keep the old one so old licences still verify; new licences use the new `--kid`.

### What offline licensing can and cannot do

It stops casual sharing and lets Jay sell, renew and limit connections without running a server. It cannot stop someone who edits the program's own code on their own computer; the real protection there is the licence terms, not the software. That trade-off is the price of "nothing is sent anywhere".

### Decided

- An expired licence keeps existing connections running (up to the number licensed) and never blocks reports; it blocks adding connections and gets the renewal notice.
- A missing or invalid licence allows no R365 connections; reports and demo data still work.
- "Updates until" decides which update files may be installed (a date, or `lifetime`); it never blocks running a version or viewing a report. The optional online update check is built, off by default (see `docs/UPDATES.md`).
- The four current flags are normally listed in a licence. Connections and flags come only from the file.

### Still open

1. Where the real private key lives, who can sign, and the backup arrangement (owner's job, outside the repo).
2. The real update key pair and hosting address (see `docs/UPDATES.md`).
