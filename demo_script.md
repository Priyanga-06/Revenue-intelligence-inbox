# Revenue Intelligence Inbox — Three-Minute Narrated Demo Script

## Recording Checklist

- [ ] Close all unnecessary browser tabs and applications
- [ ] Set screen resolution to 1920x1080
- [ ] Enable system audio recording (for narration)
- [ ] Open the app at http://localhost:8501 in a clean browser window
- [ ] Verify sample data is loaded (check dashboard shows 32 conversations)
- [ ] Have a test CSV ready for the import demo
- [ ] Test screen recording software before starting
- [ ] Speak clearly at a moderate pace
- [ ] Do not claim a recording exists until it has actually been recorded

---

## Timed Narration

### 0:00–0:35 — Dashboard and Key Metrics

**On screen:** Executive Dashboard page

> "Welcome to the Revenue Intelligence Inbox. This is the Executive Dashboard, our sales operations command center. The top row shows our key metrics — total conversations, calls versus meetings, high-priority items, and conversations needing manager attention. Below that, open follow-ups, total pipeline value, and sentiment breakdown. Every metric here is calculated live from the stored conversation records."

> "The charts show sentiment distribution, routing category distribution, activity trends by day, and conversation volume by owner. I can apply filters by date, owner, priority, sentiment, or routing category — and every metric and chart updates instantly to reflect the filtered data."

**Action:** Briefly demonstrate a filter (e.g., select an owner) and show metrics updating.

---

### 0:35–1:15 — Open a Conversation and Explain Transcript Evidence and Routing

**On screen:** Conversation Inbox page

> "Let me open the Conversation Inbox. Here I can browse all records, search by keyword, and inspect individual conversations. Let me select one."

**Action:** Click on a conversation in the detail view.

> "This shows the full transcript along with the routing analysis. The routing engine examined the transcript and assigned this conversation a category — in this case, High-intent sales opportunity — with a priority level and a specific evidence excerpt pulled directly from the transcript text."

> "You can see the exact reason for the routing decision, the supporting evidence, and the recommended next action. This is explainable routing — every decision links back to what the customer actually said."

---

### 1:15–1:55 — Show an Ambiguous Routing Decision and Manual Correction

**On screen:** Routing Review page

> "Now let's look at the Routing Review page. Some conversations have conflicting signals — for example, a customer who says they want to move forward but is also evaluating competitors. The routing engine detects these conflicts and flags them for human review rather than forcing a potentially wrong classification."

**Action:** Select a conversation flagged as "Needs human review."

> "Here's an example. The automated engine found both high-intent signals and competitor signals, so it flagged this for manager review. The automated suggestion, confidence level, and evidence are all displayed. As a manager, I can approve, reject, or override the routing decision."

**Action:** Apply a manual override — change the category and reason, then click "Apply Override."

> "I'll override the category to High-intent sales opportunity since the buying signals are stronger. The original automated result is preserved, and this change is recorded in the audit log. The manual override will be preserved even if the underlying data is re-imported unchanged."

---

### 1:55–2:35 — Re-import Identical Data and Then Updated Data, Demonstrating Real Counts

**On screen:** Import & Data Quality page

> "Now let's demonstrate the duplicate and update handling — a core feature. I'll click the Run Duplicate/Update Demo button."

**Action:** Click "Run Duplicate/Update Demo."

> "This runs a genuine test using the real import functions and database. Step one: import a new record — one inserted. Step two: import the exact same record again — one unchanged, zero inserted, count stays the same. Step three: modify the transcript and import again — one updated, count still the same."

> "The verification confirms: record count never increased, step one inserted, step two was unchanged, and step three updated. This proves that re-importing the same file will never inflate our record count, and changes are handled as updates, not duplicates."

---

### 2:35–3:00 — Download Exports, Show Manifest, and Explain Findings and Rejected Decision

**On screen:** Reports & Exports page

> "Finally, let's generate exports. The app creates a ZIP containing conversations CSV, conversations JSON, routing review CSV, findings JSON, and a manifest with SHA-256 checksums for each file."

**Action:** Click "Generate & Download ZIP."

> "The manifest includes the export timestamp in UTC, record counts per file, applied filters, checksums computed from actual file bytes, the app version, and the dataset type — synthetic in this case."

> "Below that, we have three evidence-linked findings: competitor risk concentration, high-intent opportunities, and support issues — each with supporting metrics, conversation IDs, and transcript evidence excerpts."

> "And here's our rejected decision: we rejected keyword-only routing because a word like 'competitor' can appear in a positive or negative context. Instead, we chose context-aware deterministic rules with human review for ambiguous cases."

> "That's the Revenue Intelligence Inbox. Thank you for watching."

---

## Post-Recording Notes

- This script assumes the app is running locally with sample data loaded.
- The demo uses **synthetic data** — all findings should be labeled as synthetic-data findings.
- Do not claim a deployment URL exists unless the app has actually been deployed and verified.
- Total target time: 3 minutes. Adjust pacing as needed but do not exceed 3:30.
