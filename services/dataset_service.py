"""Built-in dataset loaders (C12, PRD F-03 way 2).

Each loader streams a CSV from data/ and turns the rows that belong on a blacklist
into keys. The keys go through filter_service.add_many(), so the usual rules apply:
normalisation, duplicate counting, all-or-nothing, one snapshot save, and the
summary invariant rows_read = rows_added + rows_duplicate + rows_invalid.

Key rules (TRD section 7):
  creditcard  rows with Class == 1 -> "TXN-{row_index}-{Time}-{Amount}"
              (V1..V28 are PCA features, not IDs, so a key is built from the row)
  spam        rows labelled spam   -> "SPAM-" + SHA-256 of the normalised text
              (the Enron-based dataset has no sender address; the text is the identity)
The *_sample datasets are small generated files that ship with the project so the
loaders can be demonstrated without downloading anything.
"""
from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Iterator, Optional

from services import filter_service
from services.errors import NotFoundError, PayloadTooLargeError, ValidationError

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_DATASET_KEYS = 200_000          # TRD section 13: web-triggered imports

DATASETS = {
    "creditcard": {
        "title": "Kaggle Credit Card Fraud",
        "description": "Fraudulent transactions (Class = 1) become blacklist keys such as TXN-541-406-0.0. "
                       "The full file has 492 frauds in 284,807 rows.",
        "files": ["creditcard.csv"],
        "download": "https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud",
        "key_type": "transaction_id", "label": "fraud", "source": "creditcard",
    },
    "spam": {
        "title": "Kaggle Spam Mails",
        "description": "Spam e-mails become blacklist keys made from a hash of the message text.",
        "files": ["spam_ham_dataset.csv", "spam.csv"],
        "download": "https://www.kaggle.com/datasets",
        "key_type": "other", "label": "spam", "source": "spam",
    },
    "creditcard_sample": {
        "title": "Credit card sample (generated)",
        "description": "A 1,000-row generated file in the Kaggle credit card format. Good for trying the loader.",
        "files": ["sample_creditcard.csv"],
        "download": None,
        "key_type": "transaction_id", "label": "fraud", "source": "creditcard", "kind": "creditcard",
    },
    "spam_sample": {
        "title": "Spam sample (generated)",
        "description": "A 300-row generated file in the spam e-mail format. Good for trying the loader.",
        "files": ["sample_spam.csv"],
        "download": None,
        "key_type": "other", "label": "spam", "source": "spam", "kind": "spam",
    },
}


def _find_file(spec: dict) -> Optional[Path]:
    for name in spec["files"]:
        path = DATA_DIR / name
        if path.is_file():
            return path
    return None


def list_datasets() -> list[dict]:
    """Every loader and whether its file is present (BACKEND_SCHEMA 4.6)."""
    out = []
    for name, spec in DATASETS.items():
        path = _find_file(spec)
        out.append({
            "name": name,
            "title": spec["title"],
            "description": spec["description"],
            "available": path is not None,
            "path": f"data/{(path.name if path else spec['files'][0])}",
            "expected_files": spec["files"],
            "download_url": spec["download"],
            "key_type": spec["key_type"],
            "label": spec["label"],
        })
    return out


# ---- row readers ---------------------------------------------------------------

def _open_rows(path: Path):
    """Yield csv rows as lists. A file that is not valid CSV is a 400, not a crash."""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            yield from csv.reader(handle)
    except csv.Error as exc:
        raise ValidationError(f"{path.name} could not be parsed as CSV: {exc}", field="name")
    except OSError as exc:
        raise NotFoundError(f"{path.name} could not be read: {exc.strerror or exc}", field="name")


def _column(header: list[str], *names: str) -> Optional[int]:
    lowered = [h.strip().lower() for h in header]
    for wanted in names:
        if wanted in lowered:
            return lowered.index(wanted)
    return None


def _creditcard_keys(path: Path) -> Iterator[str]:
    rows = _open_rows(path)
    header = next(rows, None)
    if header is None:
        raise ValidationError(f"{path.name} is empty", field="name")
    c_time, c_amount, c_class = (_column(header, n) for n in ("time", "amount", "class"))
    if None in (c_time, c_amount, c_class):
        raise ValidationError(f"{path.name} must have the columns Time, Amount and Class", field="name")
    need = max(c_time, c_amount, c_class)
    for index, row in enumerate(rows):
        if not row:
            continue
        if len(row) <= need:
            yield ""                                  # short row: counted as invalid
            continue
        if row[c_class].strip().strip('"') not in ("1", "1.0"):
            continue
        yield f"TXN-{index}-{row[c_time].strip()}-{row[c_amount].strip()}"


_SPACE = re.compile(r"\s+")


def _spam_keys(path: Path) -> Iterator[str]:
    rows = _open_rows(path)
    header = next(rows, None)
    if header is None:
        raise ValidationError(f"{path.name} is empty", field="name")
    c_text = _column(header, "text", "message", "v2", "email")
    c_label = _column(header, "label", "category", "v1", "class")
    c_num = _column(header, "label_num")
    if c_text is None or (c_label is None and c_num is None):
        raise ValidationError(f"{path.name} must have a text column and a label column", field="name")
    need = max(i for i in (c_text, c_label, c_num) if i is not None)
    for row in rows:
        if not row:
            continue
        if len(row) <= need:
            yield ""
            continue
        is_spam = (row[c_num].strip() == "1") if c_num is not None else (row[c_label].strip().lower() == "spam")
        if not is_spam:
            continue
        text = _SPACE.sub(" ", row[c_text].strip().lower())
        if not text:
            yield ""                                  # spam row without text: invalid
            continue
        yield "SPAM-" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:32]


_READERS = {"creditcard": _creditcard_keys, "spam": _spam_keys}


def _limited(keys: Iterator[str], limit: Optional[int]) -> Iterator[str]:
    """limit given: stop quietly after that many keys. No limit: more than the cap is a 413."""
    for count, key in enumerate(keys, start=1):
        if limit is not None:
            if count > limit:
                return
        elif count > MAX_DATASET_KEYS:
            raise PayloadTooLargeError(
                f"this dataset has more than {MAX_DATASET_KEYS:,} keys; pass a limit of at most "
                f"{MAX_DATASET_KEYS:,} or use the command line", field="limit")
        yield key


def load_dataset(name, limit=None) -> dict:
    """Load a dataset into the blacklist. Returns the import summary (BACKEND_SCHEMA 4.5)."""
    if not isinstance(name, str) or name not in DATASETS:
        raise ValidationError(f"name must be one of {', '.join(DATASETS)}", field="name")
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValidationError("limit must be a whole number of at least 1", field="limit")
        if limit > MAX_DATASET_KEYS:
            raise PayloadTooLargeError(f"limit is at most {MAX_DATASET_KEYS:,} per request", field="limit")
    spec = DATASETS[name]
    path = _find_file(spec)
    if path is None:
        raise NotFoundError(
            f"{' or '.join(spec['files'])} was not found in the data folder. "
            f"Download it{' from ' + spec['download'] if spec['download'] else ''} and place it in data/.",
            field="name")
    reader = _READERS[spec.get("kind", name)]
    keys = _limited(reader(path), limit)
    return filter_service.add_many(
        keys, spec["key_type"], spec["label"], source=spec["source"], file_name=path.name)
