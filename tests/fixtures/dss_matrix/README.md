# DSS export test matrix

Invented Daily Sales Summary (DSS) list exports, one or more for each thing in `docs/R365_OPEN_QUESTIONS.md` that is still **unproven**. They exist so that:

1. we can show, today, what the program does when each unknown turns out one way or the other, and
2. when a real export arrives we know exactly which fixture to compare it with and what the real file must show.

**Nothing here is a real export.** Every place is "Sample ...", every amount is made up, there are no ids. A fixture describes a *possible* R365 file. It does not claim R365 produces it.

Each file has an entry in [`MANIFEST.toml`](MANIFEST.toml) (the plain-words note): what it probes, what the reader does with it today, and what a real export must show to settle the question. `tests/test_dss_matrix.py` checks every note against what the reader really does, and fails if a file has no note or the files drift from `build_fixtures.py`.

## The unknowns

| Id | Unknown (from `docs/R365_OPEN_QUESTIONS.md`) | Fixtures |
|---|---|---|
| Q1 | Which sign is a shortage? (Over/Short sign) | `over_short_signs_classic.csv`, `over_short_signs_beta.csv`, `format_numbers.csv` |
| Q2 | Does beta "In Progress" mean classic "Unapproved"? | `pair_classic.csv`, `pair_beta_lines_up.csv`, `pair_beta_does_not_line_up.csv`, `over_short_signs_beta.csv`, `headings_beta_gains_approval_column.csv` |
| Q3 | Why was one beta row missing? | `missing_row_classic_with_count.csv`, `missing_row_beta_no_count.csv`, `long_beta_250_no_count.csv`, `variant_beta_title_and_footer.xlsx` |
| Q4 | Can R365 download `.xlsx` or `.tsv` at all? | `variant_*.tsv`, `variant_*.xlsx` |
| Q5 | Is a very long list paged or capped? | `long_classic_300_complete.csv`, `long_classic_250_of_400.csv`, `long_beta_250_no_count.csv` |
| Q6 | Exact beta headings and footer (assumed); renamed or new headings | `headings_renamed_known.csv`, `headings_renamed_unknown.csv`, `headings_new_columns_beta.csv`, `headings_beta_gains_approval_column.csv`, `variant_beta_title_and_footer.xlsx` |
| Q7 | What does "Completed" mean for approval? | `pair_beta_does_not_line_up.csv` |
| Q8 | Format variants: byte-order mark, line ends, date and number spellings | `format_*.csv` |
| Q9 | Things the export does not carry: POS import, receipts, payment exceptions, R365's balance flag, who approved | `headings_new_columns_beta.csv` |

## Rebuilding

```bash
python tests/fixtures/dss_matrix/build_fixtures.py
```

The builder is deterministic. Only run it when a fixture is meant to change, and update `MANIFEST.toml` to match.

## When a real export arrives

Never commit it. Run `python -m dssreport export inspect <file>` (it prints headings, counts and formats, with no names or amounts), compare with the matching fixture's note in `MANIFEST.toml`, and record only the answer in words ("the beta list showed -23.50 for a known shortage"), with invented values.
