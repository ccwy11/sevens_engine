# SEVENS Engine — Day 0 Build

One engine, multiple inputs, one dashboard.

## What you have after Day 0
- 3 Telegram bots (SEVENS, Kuro Kare, Test) → one Neon Postgres database
- Scanner batch folder watcher → same database
- Shared extraction service with P&L taxonomy
- Raw receipts stored to Google Drive (or local temp fallback)
- Streamlit dashboard (local, port 8501) — expenses list, needs-review inbox, manual entry

## Office PC Setup (step by step)

### 1. Install Python 3.10+ and Git

### 2. Clone / copy this folder to the office PC

### 3. Create virtual environment
```bash
cd sevens-engine
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Create `.env` file
Copy `.env.example` to `.env` and fill in:

```
DATABASE_URL=postgresql://user:pass@host.neon.tech/dbname?sslmode=require
MOONSHOT_KEY=sk-xxx
BOT_CONFIG=123:abc|sevens|SevensBot;456:def|kuro_kare|KuroKareBot;789:ghi|unassigned|TestBot
DASHBOARD_PASSWORD=your_password
```

**Get these from:**
- **Neon DB URL**: neon.tech → create project → copy connection string
- **Moonshot key**: platform.moonshot.cn → API keys
- **Bot tokens**: Telegram @BotFather → /newbot (create 3 bots)

### 5. Run
```bash
python bot.py          # bots only
python scanner.py      # scanner watcher only
streamlit run dashboard.py   # dashboard only
python run.py          # everything together (recommended)
```

### 6. Scanner folders (auto-created)
```
scanner_inbox/
  sevens/       ← drop scans here for SEVENS
  kuro_kare/    ← drop scans here for Kuro Kare
  unassigned/   ← unknown brand
  processed/    ← moved after processing
  failed/       ← moved on error
```

### 7. Google Drive (optional — add later)
- Google Cloud Console → create service account → download JSON key
- Paste JSON into `GOOGLE_CREDENTIALS_JSON=` in `.env`
- Create Drive folder → copy ID into `GOOGLE_DRIVE_FOLDER_ID=`
- Until then, files store locally in `storage/receipts/`

## Next: Day 1–3
- Day 1: data validation rules, backfill scripts
- Day 2: dashboard hosted on Streamlit Cloud (public URL)
- Day 3: Keeta/Foodpanda import parsers, history migration

## Files
- `bot.py` — multi-token Telegram bot hub
- `scanner.py` — folder watcher for batch scans
- `extraction.py` — Moonshot OCR + P&L taxonomy
- `database.py` — Neon Postgres schema + CRUD
- `drive.py` — Google Drive upload/download (with local fallback)
- `dashboard.py` — Streamlit viewer + review inbox + manual entry
- `config.py` — env loader + bot token parser
# sevens_engine
