import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
MOONSHOT_KEY = os.getenv("MOONSHOT_KEY", "")
MOONSHOT_BASE = os.getenv("MOONSHOT_BASE", "https://api.moonshot.cn/v1")
MOONSHOT_MODEL = os.getenv("MOONSHOT_MODEL", "moonshot-v1-8k")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "sevens2024")

def parse_bot_config():
    raw = os.getenv("BOT_CONFIG", "")
    bots = []
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("|")
        if len(parts) >= 3:
            bots.append({
                "token": parts[0].strip(),
                "brand": parts[1].strip(),
                "name": parts[2].strip()
            })
    return bots

BOT_CONFIG = parse_bot_config()
