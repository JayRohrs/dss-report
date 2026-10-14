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


# A SEPARATE key signs program updates (see docs/UPDATES.md), so a leaked licence key can't be used to
# push code and vice versa. Same rules: public half only, empty here, private key kept by the owner
# outside every git folder. Until it is filled in, no update package can be installed.
UPDATE_PUBLIC_KEYS = {
    # "2026-u": "<64 hex characters of the update public key>",
}
