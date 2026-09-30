# NEWITY Document Checklist Tracker

A small web tool that replaces the SBA loan document-checklist spreadsheet. Processors can see, at a glance, which applications need attention and update a document's status in a click. Leadership gets a pipeline dashboard.

It runs locally in a browser. There is nothing to install besides Python.

## Run it (about 2 minutes)

Requires Python 3.10 or newer.

**Windows (PowerShell or Git Bash)**

```
python -m venv venv
venv\Scripts\activate          # Git Bash: source venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn app.main:app
```

**Mac / Linux**

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app
```

Then open **http://127.0.0.1:8000**.

On first start the app creates a local SQLite database (`newity.db`) and loads the 60 applications from `data/document_checklist.csv`. To reset to that starting state, stop the server and delete `newity.db`.

Run the tests with `python -m pytest -q`. They use a temporary database, so they never touch your data.

## What it does

| Page | Purpose |
| --- | --- |
| **Applications** (`/`) | Every application ranked most-severe first. Filter by processor. Badges show expired / expiring / stalled at a glance. |
| **Application detail** | Update each document's status, received date, expiration date and notes inline. Add or remove documents. Previous / next buttons walk the ranked list. |
| **New / edit application** | Manual entry with validation. A new application starts with the 12 standard documents as Pending. |
| **Import** (`/import`) | Upload a CSV in the spreadsheet's format. New applications and documents are added; duplicates and invalid rows are skipped and listed with the reason. Existing data is never overwritten. |
| **Dashboard** (`/dashboard`) | Pipeline progress ring (complete / in progress / stalled), headline counts, the 10 most urgent applications, the expired and expiring documents, and workload by processor. This is the weekly leadership summary. |

### The rules, in plain English

- **Outstanding** document: status is Pending or Expired.
- **Expiring soon**: expires within 30 days. **Expired**: the date has passed, or the status is set to Expired.
- **Not Required** documents are never flagged.
- **Stalled** application: not complete and no activity for 14 days. "Activity" is any edit to the application or its documents. For loaded data it is the latest application or received date.
- **Complete** application: every document is Approved or Not Required.
- **Severity score** (used for ranking): expired 10, expiring soon 5, pending 3 per document, doubled for the tax returns and bank statements, plus 5 if the application is stalled. Ties break by application ID.
- Marking a document **Received** fills in today's date and suggests an expiration: 90 days for bank statements, 3 years for tax returns. Both can be changed.

The weights sit at the top of `app/logic.py` and are easy to tune.

## Scope: what is built and what is not

**Built**: everything in the table above, plus duplicate detection on import and route-level tests for every page.

**V2, not built: email alerts.** The brief mentioned alerts, and I cut them on purpose. Email needs a mail provider, credentials, a scheduler that runs when nobody has the page open, and de-duplication so people are not emailed the same warning every day. That is real infrastructure that would have used the time budget without improving the core tracking. The dashboard and the ranked list already surface the same information whenever someone opens the tool. The natural V2 is a daily job that reuses `attention_documents()` and `is_stalled()` from `app/logic.py`, so the rules stay in one place.

**Also left out** (ideas for later):

- Changing a document's status straight from the list view (today you open the application).
- A change history of who changed what.
- Deleting or archiving whole applications.
- Logins and permissions. This is a single-team tool on one machine.

## Known limitations

- **The sample data is old.** The provided CSV is dated December 2025 to early 2026, so relative to today almost every application looks stalled and many documents look expired. That is the rules working as designed, not a bug. Anything you add or edit today starts fresh.
- The processor list is the three names in the data plus any others found in the database. There is no processor management screen.
- The processor filter on the list is lost after adding, editing or removing something.
- Documents imported with a non-standard type name work everywhere, but cannot be re-added after removing them (the add menu only offers the 12 standard types).
- SQLite and a single process are plenty at this scale, but this is not built for many people editing at once.

## Project layout

```
app/
  main.py         routes
  logic.py        all business rules (statuses, severity, stalled, summary)
  importer.py     CSV import and duplicate detection
  seed.py         first-run load of data/document_checklist.csv
  models.py       Application and Document tables
  templates/      Jinja pages       static/  CSS and a little JS
data/             the provided sample spreadsheet
demo_data/        CSVs to try on the Import page (see below)
tests/            unit tests (logic) and functional tests (routes)
```

Stack: Python, FastAPI, SQLAlchemy + SQLite, Jinja2, Pico.css (loaded from a CDN, so the first page load needs internet). No build step.

## Demo files for the Import page

Upload these in order from the Import page. Dates are set around late September 2026, so the new applications show as recently active rather than stalled.

1. `demo_data/1_new_applications.csv`: 3 new applications, 13 documents, nothing wrong. One bank statement is about to expire and one document is already expired.
2. `demo_data/2_duplicates_and_errors.csv`: 2 rows are skipped as duplicates and 4 are rejected, each listed with its row number and a plain-English reason. The valid rows still import.
3. `demo_data/3_missing_column.csv`: the whole file is refused with "Missing column(s): notes" and nothing is imported.
4. `demo_data/4_mixed_pipeline.csv`: 5 new applications in different states, for showing off the dashboard: one complete, one stalled (48 days quiet), one with two documents expiring soon, one high-severity with two expired tax returns, and one in progress. Import it once; a second upload skips everything as duplicates.

## Other deliverables

The demo video and the AI usage log are submitted separately alongside this repository.
