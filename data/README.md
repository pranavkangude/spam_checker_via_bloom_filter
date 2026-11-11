# Data folder

The large datasets are **not** in Git (size and licence). Download them yourself and place the
files here. The Import page shows which ones are found.

| Loader | File to place in `data/` | Where to get it |
|---|---|---|
| Credit card fraud | `creditcard.csv` | Kaggle: https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud |
| Spam mails | `spam_ham_dataset.csv` (or `spam.csv`) | Kaggle: search for "Spam Mails Dataset" and check that it has a text column and a label column |

## How rows become blacklist keys

- **Credit card:** rows with `Class = 1` become `TXN-{row_index}-{Time}-{Amount}`, for example
  `TXN-541-406-0.0`. The V1 to V28 columns are PCA features, not identifiers, so a key is built from the row.
  `row_index` counts data rows from 0.
- **Spam:** rows labelled spam become `SPAM-` followed by 32 hex characters of the SHA-256 hash of the
  lower-cased, whitespace-normalised message text. Two messages with the same text give the same key,
  so the second one is counted as a duplicate.

## Sample files (committed)

`sample_creditcard.csv` (1,000 rows) and `sample_spam.csv` (300 rows) are **generated** with a fixed seed.
They only copy the column layout of the Kaggle files, contain no real data, and let you try the loaders
and run the tests without downloading anything.

## Limits

One request loads at most 200,000 keys (pass `limit` to load fewer). The credit card file has only 492
fraud rows, so it always loads in full.
