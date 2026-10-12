"""The PUBLIC key(s) that licences are checked against. Public keys are safe to ship.

key id -> 32-byte Ed25519 public key, as 64 hex characters.

This is EMPTY in the repository on purpose: the real private key lives only with Jay Rohrs, outside
this repo, and is never committed. Before a release, generate the real pair with
`python tools/licence_tool.py keygen --out <a private folder outside the repo>` and paste the PUBLIC
half here (docs/LICENSING.md, "Before a release"). Until then no real licence can verify, and the
program says so plainly instead of pretending.

(Tests pass their own throw-away public keys directly and never use this table.)
"""

PUBLIC_KEYS = {
    # "2026-a": "<64 hex characters of the public key>",
}
