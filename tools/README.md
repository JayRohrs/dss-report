# tools/ - not part of the shipped program

`licence_tool.py` makes licence keys and signs licences. It is kept out of the `dssreport` package (the installer
copies only that folder) because it handles the PRIVATE signing key.

- Never commit a private key. `keygen` refuses to write one inside a git working folder, `.gitignore` blocks
  `*.private.key` and `*.pem`, and a test fails if one is found.
- The real private key lives only with Jay Rohrs, outside this repository.
- Tests generate a throw-away key in memory every run and never use a real one.

`update_tool.py` builds and signs update packages and the signed list for the optional online check (see `docs/UPDATES.md`). Use a separate key pair for updates.

See `docs/LICENSING.md`.
