# Security notes

- **Never commit real data.** Real sales figures, location names or exports must stay on your computer, outside this repository. `.gitignore` blocks `data/`, `private/`, `input/`, `out/` and all `.csv`, `.json`, `.xls`, `.xlsx` files except under `examples/` and `tests/fixtures/`. If real data is ever committed, treat it as exposed: removing it from the latest commit does not remove it from history.
- **No credentials in the repo, in files, or in logs.** The R365 password and the Microsoft 365 sign-in token are kept only in the operating system's credential store (Windows Credential Manager; Linux `secret-tool`). If no secure store exists the program refuses to save them. They are never written to `settings.json`, `rules.toml`, reports, state or logs, and never shown in the settings page. `python -m dssreport forget-secrets` (also run by the uninstaller) removes them.
- **R365 is read-only.** The connector can only send GET requests, sends your sign-in only to the address you configured over https, refuses redirects and refuses next-page links that point to another website.
- **Microsoft 365 uses delegated sign-in.** You sign in on Microsoft's page; no password is stored. It asks for the least permission: create a draft. The extra permission to send is requested only if you tick "send automatically", which is off by default.
- **Private values stay out of the repo.** The real R365 field mapping, the R365 address and user name, the Microsoft app ID, tenant and email addresses are typed into the settings screen and kept in the user's own folder (`%LOCALAPPDATA%\DssReport`), never committed. The repo, docs, tests and screenshots use obviously fake placeholders only, and a test scans for real-looking addresses and IDs.
- **Network calls are only these:** your R365 address, Microsoft sign-in/Graph (if email is on), and a language model on this computer (if on). No analytics or telemetry.
- **The settings screen is local only.** It listens on 127.0.0.1, needs a random one-time token that exists only in the address the program opens, checks the Host and Origin headers, and never logs requests.
- **Generated reports contain your figures.** Treat the reports folder like the data it came from.
- **The installer** needs no administrator rights, downloads nothing itself (Python, if missing, comes from Windows' own winget) and installs under your user folder.
- All data in this repository is made up. No real tenant, credential or person is used anywhere, including the tests, which use local mock servers.

To report a problem, contact Jay Rohrs directly rather than posting details publicly.
