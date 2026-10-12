# Local AI sentence - plan (design only, no code yet)

Status: **design only.** The program already supports an optional one-sentence summary from a model
running on the same computer (`[ai]` in `rules.toml`, off by default). This note is about making that easy
to turn on, and what to do when a computer is too small. Nothing here is built.

The rule that does not change: **the report is complete and correct without any AI.** A model sentence is
decoration. It is checked against the computed facts and thrown away if it disagrees (`summary.py`).

## 1. Offering a small model in the installer

1. After the main install, the installer asks one plain question: *"Add a one-sentence plain-English summary to each report? This downloads a small program and a language model (about N GB) and runs it on your computer. You can skip this; the report works the same without it."* Default: **No**.
2. If yes, run the **minimum-spec check** first (section 2). If the computer is too small, say so plainly and offer the hosted option (section 3) or skip.
3. Download the local model server and one small instruction-following model **only after the explicit yes**, from the publisher's official download address, and verify the published checksum before running anything. If verification fails: stop, delete, tell the user.
4. Choose the model by a short list kept in one file (name, size, minimum RAM, licence). The licence must allow commercial use inside a paid product; check before listing a model.
5. Write the answers into the settings **instead of the placeholder**: `[ai] enabled = true`, `endpoint = "http://localhost:<port>"`, `model = "<chosen name>"`. The installer fills in the model name; nobody types it.
6. Self-test with the demo report: ask for a sentence, run it through `sentence_agrees()`, show the user the result. If it fails twice, switch AI back off and say why.
7. The uninstaller offers to remove the model and server (they are large).

## 2. Minimum-spec check (read-only, local)

| Check | Suggested minimum | How (standard library) |
|---|---|---|
| 64-bit Windows 10/11 | required | `platform`, `struct.calcsize("P")` |
| Free memory | about 8 GB total RAM, 4 GB free | Windows `GlobalMemoryStatusEx` via `ctypes` |
| Free disk | 6 GB free on the install drive | `shutil.disk_usage` |
| CPU | 4 cores | `os.cpu_count()` |
| GPU | not required | - |

Numbers are placeholders to be set after timing a real model on a typical office laptop; measure
time-to-sentence and set a maximum acceptable wait (the report must never wait on it: it is generated
after the report is saved, with a short timeout, then the page is rewritten or the template sentence stays).

## 3. Fallback: "use hosted AI" (Jay could bill for this later)

For computers that fail the check, or owners who prefer not to run a model.

- **Opt-in per computer, off by default**, with a plain warning: *this sends a short summary of counts and location names (never dollar figures, receipts or personal data) to a service run by Jay Rohrs.* It breaks the "your data never leaves your computer" promise for that one sentence, so it must be a deliberate choice and visible in settings.
- **What is sent:** exactly the facts block already built for the local model (period, number of locations, which need a look, how many are UNKNOWN). Location names are customer data - say so, and offer "send numbers only, use generic names" (Location A, B).
- **Same safety check:** the returned sentence goes through `sentence_agrees()`; a disagreeing sentence is discarded and the template sentence used.
- **Where it talks to:** a single address Jay controls, https only, per-customer key stored in the OS credential store (like the R365 password), never in a file. The settings screen gets one more tick and nothing else.
- **Billing hooks, not built now:** each customer has an ID and key; the service counts requests per key per month. Price and invoicing are Jay's decision. Do not store card details in this program.
- **Needed before building:** a hosted endpoint with its own privacy notice and data-processing terms, a retention rule (suggest: do not store prompts or replies), rate limits, and a kill switch.

## Decisions for Jay

1. Is a local model worth the install size and support cost, or is hosted-only simpler?
2. Which model(s) and licence?
3. Is "hosted AI" something you want to sell and support? If yes, who hosts it and what do customers sign?
