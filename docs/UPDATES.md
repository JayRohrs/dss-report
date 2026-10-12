# Updates: you decide who gets one and when

Updates are built into the program, and **you (the owner) control them completely**. There is no automatic update, no update server and no "check for updates": the program never goes online for updates. An update reaches a customer only when you send them an update file, and the program only installs it if the file is genuinely yours and that customer is allowed to have it.

## How it works

1. **You build and sign an update file** with `tools/update_tool.py` on your own machine (see below). It holds the new program files and a signed list of them.
2. **You send it to the customers you choose**, when you choose, however you like (email, a download link you control, a USB stick).
3. **The customer installs it** in settings (**2. Updates** > Choose the update file > Install update file), or with `python -m dssreport update install <file>`.
4. **The program checks, on the customer's computer, before it changes anything:**
   - the file is signed by your update key (a public key built into the program) and nothing inside it has been changed;
   - every file matches its signed fingerprint, only program files are inside it, no path leads outside the program folder, there are no links, no extra unlisted files, nothing oversized, and every Python file at least compiles;
   - the version is newer than what is installed (and meets the update's "minimum version" if you set one);
   - the customer has a valid licence file, and the update's release date is **inside the licence's "updates until" date**;
   - if you addressed the update to particular licences, this licence is one of them.
5. **If everything passes**, only the program files are replaced. A copy of what was replaced is kept. The program says to close and reopen it.
6. **If anything fails**, nothing is changed, and the message says why in plain words. If writing fails half-way, everything is put back automatically.

**Never touched by an update:** settings, saved passwords, the licence file, field-mapping files, and every report. An update can only write inside the program folder (`dssreport/`, `docs/`, the launcher, README/SECURITY and the mapping template); a package that tries anything else is refused whole.

**Going back:** one earlier version is kept. Settings > **Go back to the previous version**, or `python -m dssreport update rollback`.

## Your controls

| You want to... | You do this |
|---|---|
| Send an update to everyone | Send the file to everyone |
| Hold it back from some customers | Don't send it. It is useless to anyone who doesn't have the file |
| Send it only to certain licences | `--licence-ids id1,id2` when building (a licence's id is shown by `licence_tool.py show`). Anyone else who gets the file is refused: "not released to your licence" |
| Limit it to people who have paid for updates | Nothing extra: the licence's "updates until" date does it. An update released after that date is refused, with "Renew to get it" |
| Require an earlier version first | `--min-version 0.3.0` |
| Stop customers going back in time | The program won't install a version that isn't newer |

A customer whose update period has ended **keeps running their current version and keeps all their reports**. Only installing the newer file is refused.

## Building an update (owner, on your own machine)

```
python tools/licence_tool.py keygen --out <a folder outside every git folder> --kid 2026-u   # once; use a DIFFERENT pair from the licence key
python tools/update_tool.py make --private-key <that key file> --kid 2026-u --source <the repo folder> \
    --version 0.4.0 --release-date 2026-11-01 [--min-version 0.3.0] [--licence-ids id1,id2] --out dss-update-0.4.0.dssupdate
```

- The update key is **separate from the licence key**, so one leaking can't be used for the other. Paste only its PUBLIC half into `UPDATE_PUBLIC_KEYS` in `dssreport/licence_keys.py`. It ships **empty**: until you do, no update can be installed ("no update key built in").
- Same key custody rules as the licence key (`docs/LICENSING.md`): outside every git folder, passphrase-protected, offline backup, only the public half in the product.
- Release the **first** build with the update public key already inside it, because a program can only check updates against the keys it already has. Rotating keys later means shipping the new public key in an update signed with the old one.

## Why not an automatic update check?

Because it would be a new network call, and the promise today is that the program only talks to your R365, Microsoft 365 (if switched on) and a model on the same computer. Offline signed files keep that promise and still give you full control.

If you do want the program to check for you, here is the design, **not built**, for you to decide:

- **Off by default and opt-in** in settings, with a plain sentence saying exactly what is sent.
- **Sends only what is needed**: the installed version, and (only if you want per-customer control) the licence id. No sales data, no location names, no settings, no computer identifiers, no analytics.
- **Fetches from one address you own**, https only, and gets back a small signed notice or the signed update file. Everything is still checked on the computer as above, so a fake server can't push code.
- **You control it from your side**: a signed notice per version and per licence id lets you release to some customers first, hold others, or pause.
- **Costs**: a server to run and secure, the licence id leaves the computer (a privacy statement is needed), and the README promise would have to change to name this address.

### Decisions for you

1. Offline signed files only (as built), or add the opt-in online check above?
2. If online: where it is hosted, and whether the licence id may be sent.
3. Who builds and sends updates, and how you keep track of which licence has which version.
4. Generate the real update key pair and paste the public half in before the first release.
