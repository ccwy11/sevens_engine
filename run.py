import asyncio
import threading
import sys
from database import init_db

def start_scanner():
    try:
        from scanner import run_scanner_watcher
        run_scanner_watcher()
    except Exception as e:
        print(f"[Scanner] Could not start: {e}")

def start_dashboard():
    import subprocess
    subprocess.run([sys.executable, "-m", "streamlit", "run", "dashboard.py", "--server.port", "8501"])

async def main():
    init_db()
    print("Database initialized.")

    # Start scanner in background thread
    scanner_thread = threading.Thread(target=start_scanner, daemon=True)
    scanner_thread.start()

    # Start dashboard in background thread
    dashboard_thread = threading.Thread(target=start_dashboard, daemon=True)
    dashboard_thread.start()

    # Run bots (main thread / asyncio loop)
    from bot import run_bots
    await run_bots()

if __name__ == "__main__":
    asyncio.run(main())
