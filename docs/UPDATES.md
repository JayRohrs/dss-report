# Updates: you decide who gets one and when

Updates are built into the program, and **you (the owner) control them completely**. The program never goes online for updates unless the customer switches on the optional check (off by default), and even then nothing installs by itself. An update reaches a customer when you send them an update file, or when they choose to download one you have published; the program only installs it if the file is genuinely yours and that customer is allowed to have it.

## How it works

1. **You build and sign an update file** with `tools/update_tool.py` on your own machine (see below). It holds the new program files and a signed list of them.
2. **You get it to the customers you choose**, when you choose: send the file (email, a link, a USB stick), or publish it where the optional online check can list it (below).
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

## The optional online update check

Switched **off by default**. When the user ticks it and gives it an address, pressing **Check for updates now** (in settings > Updates, or `python -m dssreport update check`) does this and nothing more:

1. **One plain `GET`** of a small signed list (the *manifest*) from the address the user typed in settings.
2. The list names the available versions, each with its package file name, release date and a **SHA-256 fingerprint**. The program checks the list's signature with the update public key built into it, exactly as it checks an update file. A changed, unsigned, or wrongly signed list is ignored with a plain message.
3. It shows the versions newer than the installed one. **Nothing is downloaded yet.**
4. The user presses **Download** on one. One plain `GET` fetches that package from the **same folder** on the **same site** as the list. The program checks the fingerprint against the signed list, then verifies the package exactly like a hand-supplied file (signature, safe paths, nothing but program files, the licence's update period, any licence the owner addressed it to). If any check fails the download is thrown away.
5. The user presses **Install**. **Nothing ever installs automatically.** Install keeps a backup and can be rolled back, as for a manual file.

The manual route (build a file, send it, the user picks it in settings or runs `update install`) is unchanged and needs no online setting.

### It sends nothing about the user

The request is a `GET` for the address itself: no query string, no cookies, no licence id, no customer name, no settings, no program version, no computer or operating-system details, no username. Only a fixed generic set of headers goes out (`Host`, `User-Agent: dss-report-update-check`, `Accept`, `Connection`). Redirects are refused, so a request can never be handed on to another site. The only thing the host can learn is that someone asked for the file, which is true of any web page.

The address must start with `https://` and may not contain a user name, a `?` query or a `#` part (so nothing user-specific can be tacked on). Package names in the list must be plain file names ending `.dssupdate`: they cannot name another folder or site. The update list and every package are limited in size.

### Where it fits in the allowed network calls

The program's complete list of network calls is now: your **R365 address** (per connection), **Microsoft sign-in and Graph** (only if email is switched on), a **model on the same computer** (only if the summary is switched on), and **the update list address you set** (only if the update check is switched on, and only when you press the button). There is no telemetry, no analytics, no licence server. A test checks that no other part of the program can make a network call.

### Hosting: a static page or a release file you own

The owner hosts two kinds of file in **one folder** on any static host the owner controls: a static web page or folder (any web host, object storage, a documentation site) or the release files of a repository the owner owns:

```
https://<your-host>/<folder>/manifest.json
https://<your-host>/<folder>/dss-update-0.4.0.dssupdate
https://<your-host>/<folder>/dss-update-0.5.0.dssupdate
```

**The host is not trusted.** The security comes only from the signatures: someone who took over the host, or sits between the host and a customer, still cannot make the program install anything, because they cannot sign. The worst they can do is hide an update (serve nothing or an old list), which is why a customer can always fall back to the manual signed-file route. No real address is built into the program. The settings screen shows a placeholder (`https://updates.example.invalid/dss-report/manifest.json`) and the owner tells each customer the real address, or sends the address with the licence.

Because the check sends nothing about the customer, the host cannot tell customers apart or hold an update back from one of them. What you can still control: a package addressed to particular licences (`--licence-ids`) can be downloaded by anyone who can reach the folder, but **installs only on those licences** (everyone else sees "not released to your licence"). To keep a package away from some customers entirely, do not publish it; send it as a file. The licence's update period is enforced at the customer's end: a version released after it is listed with "Renew to get it" and offers no download button, and a lifetime licence is covered for every release date.

### Publishing an update online (owner)

```
python tools/update_tool.py make --private-key <key> --kid 2026-u --source <repo> --version 0.4.0 --release-date 2026-11-01 \
    --out releases/dss-update-0.4.0.dssupdate
python tools/update_tool.py manifest --private-key <key> --kid 2026-u --packages releases --out releases/manifest.json
```

Upload the `.dssupdate` files and `manifest.json` together to the one folder on your host. The `manifest` command lists every package in the folder. To withdraw a version, remove it from the folder and run `manifest` again. To pause updates, publish a manifest that lists nothing newer.

A signed list also carries an issue date. A host that serves an *older* list can only hide newer versions; it can never cause an older program to be installed, because a version must be newer than the one installed.

### Decisions left for you

1. The real update key pair (public half pasted into `UPDATE_PUBLIC_KEYS` before the first release; nothing about the key is in the repo).
2. The real hosting address, and how each customer is told it.
3. How you track which customer has which version (the program never reports it).
4. Whether to add an automatic periodic check later. Today the check runs only when a person presses the button.
