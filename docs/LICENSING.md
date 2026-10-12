# Licensing, in plain words

## What a licence is

A licence is one small file, sent to you by Jay Rohrs. It says:

- **who it is for** (the customer name),
- **how many Restaurant365 connections** you may run,
- **when it ends** (the expiry date),
- **which extras it includes** (feature flags, listed below),
- **"updates until"**: the last date for which new versions are included.

It carries a digital signature made with a private key that only Jay has. If anyone changes even one letter of the file, the signature stops matching and the program refuses it.

## Why nothing is sent anywhere

The program checks the signature **on your own computer**, using a public key built into the program. There is no licence server, no "phone home", no sign-up, no account and no network call for licensing. You can unplug the internet and the licence still works the same way. This keeps the promise in the README: your data, and now your licence, never leave your computer.

## Loading a licence

Open the settings screen, find **1. Licence**, press **Choose file**, pick the licence file, press **Load licence file**. The program checks it and, only if the signature is genuine, keeps a copy in its own folder (`%LOCALAPPDATA%\DssReport\licence.json`). A file that is changed, unsigned, signed by someone else, or not a licence at all is refused with a plain message, and any licence you already had is left untouched.

The Licence section shows, in plain words: the status line, the customer name, connections used out of allowed, the expiry date, the updates date, and what is included.

## What happens in each situation

The rule behind all of it: **a licence problem never deletes or hides a report you already have.** Past reports stay on disk and can always be opened; the "view the report" page, earlier reports and the "open in my mail app" link never check the licence.

| Situation | The settings line says | What still works | What stops |
|---|---|---|---|
| Valid | `Licence: valid for <customer> until <date>.` | Everything the licence includes, up to the connection limit | - |
| Expired | `Licence: expired on <date>...` | Existing connections keep running (up to the number licensed), existing reports, the extras the licence had, demo data | Adding a connection; updates; anything new |
| Not found | `Licence: not found...` | Existing reports, demo data, the basic checks on demo data | Connecting to R365 (nothing is licensed); the extras that need a flag |
| Not valid (changed, wrong key, damaged) | `Licence: not valid...` plus the reason | Same as "not found" | Same as "not found" |
| Over the limit (more connections set up than the licence allows) | `Licence: over limit...` | The first connections up to the limit | The extra ones show "not connected: Licence: over limit" in the report |
| Demo data | `Licence: demo mode (made-up data, no licence needed).` | Everything built so far, so a first-time viewer is never blocked | - |

The report itself says so too: a licence problem is shown as a box at the top ("Licence: expired on ... Your reports and existing connections keep working; renew to add connections or get updates.") and a valid licence as a quiet line at the bottom.

A connection that cannot run is **never hidden**: it appears in the report as `not connected: <reason>` (licence) or `could not connect: <reason>` (R365 unreachable or sign-in refused), at the top, and the headline says some locations are UNKNOWN. It is never counted as "nothing to review".

## Connections

One licence can cover several Restaurant365 instances. Each connection has its own name, address, user name, saved password (kept in the operating system's credential store under its own entry), its own field-mapping file, and its own show/hide choices for locations. The report covers all connected instances, grouped by connection, and one instance failing never hides the others.

Adding a connection (or switching a switched-off one back on) is checked against the licence: you get `Licence: over limit. Your licence allows 2 connections and 2 are already set up.` and nothing is saved. Removing one makes room.

## Features (flags)

The program asks one helper, `has_feature`, whether a flag is on. A licence file lists the flags it grants. **Everything built so far is in the base licence.**

| Flag | What it covers | In the base licence |
|---|---|---|
| `optional_rules` | The optional checks (today: payments add up to the sales total) | yes |
| `email_m365` | Creating or sending the email through Microsoft 365 (the "open in my mail app" link is not gated) | yes |
| `scheduling` | The automatic weekday run | yes |
| `local_ai` | The optional one-sentence summary from a model on your computer | yes |
| `hosted` | Future hosted features. Nothing is built. | no |
| `addons` | Future paid add-ons. Nothing is built. | no |

If a flag is missing, the feature says so in plain words ("Automatic schedule is not included in your licence...") and the rest of the program carries on. An unknown flag in a licence file is ignored.

## Updates

"Updates until" is the last date for which new versions are included. The program has no updater and never goes online. Each version knows its release date and the settings screen says whether it is inside or newer than your updates period. This is **shown, not enforced**: an older version keeps running forever, and a newer one is not blocked. Whether to enforce it is Jay's decision (see below).

---

## For Jay: making licences

The signing tool lives in `tools/` and is **not** part of the program customers receive (the installer copies only the `dssreport` folder, and a test checks that).

```
python tools/licence_tool.py keygen --out "D:\private-keys" --kid 2026-a
python tools/licence_tool.py sign --private-key "D:\private-keys\2026-a.private.key" --kid 2026-a \
    --customer "Customer Name" --instances 2 --expires 2027-03-31 --updates-until 2027-03-31 --out licence.json
python tools/licence_tool.py show licence.json
```

`sign` defaults to the base feature set; add `--features optional_rules,email_m365,...` to change it.

### The private key never goes in this repository

- `keygen` refuses to write a private key inside a git working folder.
- `.gitignore` blocks `*.private.key`, `*.pem`, `/keys/` and `licence.json`, and a test fails if a private key file appears in the repo.
- The real private key lives only on Jay's own machine (and a backup somewhere safe and offline). If it is lost, no new licences can be made that old programs accept; if it leaks, anyone can make licences, so treat it like a bank password.
- Tests never use it. Each test run makes a new throw-away key in memory and tells the program to trust only that.

### Before a release (this repository ships with no key)

`dssreport/licence_keys.py` is **empty on purpose**. Until the real PUBLIC key is pasted in, a development build says "no licence key built in" and no real licence can be accepted. To release:

1. Run `keygen` as above on your own machine; keep the private file out of the repo.
2. Paste the printed line (`"2026-a": "<64 hex characters>"`) into `PUBLIC_KEYS` in `dssreport/licence_keys.py`.
3. Make a test licence with `sign`, load it in settings, and check the status line.

To change keys later, add the new public key under a new key id and keep the old one so old licences still verify; new licences use the new `--kid`.

### What offline licensing can and cannot do

It stops casual sharing and lets Jay sell, renew and limit connections without running a server. It cannot stop someone who edits the program's own code on their own computer; the real protection there is the licence terms, not the software. That trade-off is the price of "nothing is sent anywhere".

### Decisions for Jay

1. **Expired licences keep existing connections running** (up to the number licensed) and only block adding new ones. The alternative is to stop connecting at expiry. The first matches "not a lockout"; tell me if you want the second.
2. **Missing or invalid licence allows no R365 connections** (reports and demo still work). Alternative: let existing connections run unlicensed.
3. **Enforce "updates until"?** Today it is only shown.
4. **Base features:** are all four current flags really in the base licence, or should some become paid add-ons?
5. **Key custody and release process:** where the private key lives, who can sign.
