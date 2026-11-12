# Manual testing checklist

Run this on a clean start before submission. Use Windows, Python 3.10.11 and Chrome or Edge.
Tick each line. A line that fails is a bug: note the page, what you did, and any message.

## 0. Start clean

```powershell
cd <project folder>
.venv\Scripts\Activate.ps1
rmdir /s /q storage          # skip this if there is no storage folder
python app.py
```

Open http://127.0.0.1:5000. Open the browser console (F12, Console tab) and keep it open.
It should stay free of red errors on every page.

## 1. Setup and dashboard
- [ ] The first page you see is **Setup** (any other address also lands there).
- [ ] Type 1,000,000 items and 1% -> shows **9,585,059** bits and **7** hashes.
- [ ] Type 0 or letters in the item box -> a clear message under the box, no crash.
- [ ] Create the filter (choose **Counting** so removal can be tested) -> the Dashboard opens.
- [ ] Dashboard shows 0 items, the grid is nearly empty, and "Within capacity".
- [ ] Visiting /setup again sends you back to the Dashboard.

## 2. Blacklist
- [ ] Add `fraud_txn_1` (type Transaction ID, label Fraud) -> success message, table shows it.
- [ ] Add the same item again -> a friendly "already on the blacklist" message, no second row.
- [ ] Add one item of each type: `scam@evil-mail.com` (Email), `http://phish.example.com/login` (URL), `203.0.113.42` (IP), `+91 98765 43210` (Phone). The phone is shown as `+919876543210`.
- [ ] Search box and the type/label filters narrow the table. Clear them to see everything.
- [ ] Remove one item (Counting filter) -> it disappears and the dashboard count drops by one.

## 3. Check
- [ ] `fraud_txn_1` -> **Blacklisted**, with highlighted squares, "Filter says: Probably present", "Database says: Found".
- [ ] `clean_txn_9` -> **Clean**, database not used.
- [ ] Switch to **Filter only** and check `fraud_txn_1` -> "Possibly blacklisted".
- [ ] Press Enter in the box to check. Empty box -> a message under the box.
- [ ] The Recent checks list on the right updates after every check.

## 4. Batch check (Check page, Batch tab)
- [ ] Paste 5 lines (include `fraud_txn_1` twice and one unknown id). The counter under the box says "5 items".
- [ ] Run -> the summary adds up (Clean + Blacklisted + False positives + Invalid = Items checked).
- [ ] Click the verdict chips under the summary -> the table filters.
- [ ] **Download CSV** saves `bloomguard-batch-results.csv`; it opens with one row per item.
- [ ] Upload a `.csv` with a header row and a column name typed in the Column box -> works.
- [ ] Upload a `.png` or a file over 20 MB -> a clear error, nothing breaks.
- [ ] Open History: batch checks are **not** listed there (by design).

## 5. Import
- [ ] Built-in datasets: the two samples show **Ready**; the full Kaggle ones show **Missing** with a download link (unless you put the files in `data/`).
- [ ] Load **credit card (sample)** -> summary with rows added (60 on a fresh database). Load it again -> rows added 0, duplicates 60.
- [ ] Load **spam (sample)** with a limit of 10 -> adds 10.
- [ ] Upload your own CSV -> summary: rows read = added + duplicates + invalid.
- [ ] Use the synthetic generator for 1,000 keys -> added.

## 6. History
- [ ] The checks from step 3 are listed, newest first. Filter chips narrow by verdict.
- [ ] Clear history asks for confirmation, then empties the list.

## 7. Lab pages
- [ ] **Benchmark**: sizes `1,000 10,000`, 20,000 queries, 2 repeats -> a progress bar, then four charts and a table. Memory saved is well above 1x; false negatives show 0.
- [ ] Run a second benchmark, then click the earlier run in the list -> it reopens.
- [ ] Sizes `300,000` -> a clear message about the 200,000 limit.
- [ ] **Experiments**: run all three kinds (n 10,000, trials 20,000). Each draws a chart where the measured line follows the formula, and shows "Matches the formula".
- [ ] **Download CSV** works. Saved experiments reopen.
- [ ] **Visualizer**: add `hello`, `world`, `bloom`; look up `hello` (Probably present, 3 outlined squares) and `zebra` (usually "Definitely not present"); press **Search for one** to find a false positive; Reset asks for confirmation.
- [ ] Reload the Visualizer page: the words are still there (the server keeps the demo filter until it restarts).

## 8. Settings, persistence and recovery
- [ ] Stop the server (Ctrl+C) and start it again: the dashboard numbers and `fraud_txn_1` are unchanged.
- [ ] Stop the server, delete `storage\filter_state.bin`, start again: the dashboard shows "The filter was rebuilt on startup" and checks still work.
- [ ] Settings -> Rebuild with a larger item count: the filter size changes, the blacklist is unchanged.
- [ ] Settings -> Reset needs you to type `RESET`; afterwards every page sends you to Setup.

## 9. Layout and look
- [ ] Make the window narrow (or press F12, then the device toolbar, pick iPhone SE / 360 px): no sideways scrolling, the menu button opens the navigation, tables turn into stacked cards.
- [ ] Press Tab repeatedly on any page: a visible outline follows the focus. The first Tab shows "Skip to content".
- [ ] Open http://127.0.0.1:5000/nothing -> a styled "Page not found" page with buttons back.
- [ ] Set Windows to dark mode: the app stays light and readable.

## 10. Automated tests
```powershell
pytest -q        # expect: 465 passed
```
