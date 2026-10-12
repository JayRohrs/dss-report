# Security notes

- **Never commit real data.** Real sales figures, location names or exports must stay on your computer, outside this repository. `.gitignore` blocks `data/`, `private/`, `input/`, `out/` and all `.csv`, `.json`, `.xls`, `.xlsx` files except under `examples/` and `tests/fixtures/`. If real data is ever committed, treat it as exposed: removing it from the latest commit does not remove it from history.
- **No credentials in the repo.** The tool needs none. If you later write an adapter that needs a key or password, read it from an environment variable or a file outside the repository, and never write it into code, `rules.toml` or a commit.
- **No network use.** Nothing is sent anywhere. The optional summary only contacts an address on the same computer (`localhost`, `127.0.0.1`); other addresses are refused.
- **Generated reports contain your figures.** Treat `out/` like the data it came from.
- **Adapters are code that runs on your computer.** Only use adapters you or someone you trust wrote, and keep them read-only.
- All data in this repository is made up.

To report a problem, contact Jay Rohrs directly rather than posting details publicly.
