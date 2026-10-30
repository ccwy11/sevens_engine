import os
import time
import json
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from extraction import extract_invoice, validate_totals
from database import save_invoice, enqueue_job
from drive import upload_file

SCANNER_FOLDER = Path(os.getenv("SCANNER_FOLDER", "scanner_inbox"))
SCANNER_FOLDER.mkdir(parents=True, exist_ok=True)

BRAND_FOLDERS = {
    "sevens": SCANNER_FOLDER / "sevens",
    "kuro_kare": SCANNER_FOLDER / "kuro_kare",
    "unassigned": SCANNER_FOLDER / "unassigned",
}
for p in BRAND_FOLDERS.values():
    p.mkdir(exist_ok=True)

def process_file(filepath: Path, brand: str = "unassigned"):
    if filepath.suffix.lower() not in (".pdf", ".jpg", ".jpeg", ".png"):
        return
    try:
        with open(filepath, "rb") as f:
            file_bytes = f.read()
        filename = filepath.name
        drive_id = upload_file(file_bytes, filename)

        extracted = extract_invoice(file_bytes, brand_code=brand, brand_name=brand.upper())
        extracted = validate_totals(extracted)

        payload = {
            "brand": brand,
            "input_channel": "scanner_batch",
            "date": extracted.get("date"),
            "invoice_no": extracted.get("invoice_no"),
            "vendor": extracted.get("vendor"),
            "total": extracted.get("total"),
            "tax": extracted.get("tax"),
            "currency": extracted.get("currency", "HKD"),
            "category": extracted.get("category", "UNCATEGORIZED"),
            "sub_category": extracted.get("sub_category"),
            "confidence": extracted.get("confidence", "low"),
            "prompt_version": "v1",
            "raw_json": {"response": extracted.get("_raw_response"), "parsed": {k: v for k, v in extracted.items() if not k.startswith("_")}},
            "drive_file_id": drive_id,
            "source_file": filename,
            "notes": extracted.get("notes", ""),
            "status": "pending" if extracted.get("confidence") == "high" else "needs_review",
            "items": extracted.get("items", [])
        }
        invoice_id = save_invoice(payload)
        print(f"[Scanner] Processed {filename} -> invoice #{invoice_id} (brand={brand}, conf={extracted.get('confidence')})")
        # Move to processed
        processed_dir = SCANNER_FOLDER / "processed" / brand
        processed_dir.mkdir(parents=True, exist_ok=True)
        filepath.rename(processed_dir / filename)
    except Exception as e:
        print(f"[Scanner] Error processing {filepath}: {e}")
        failed_dir = SCANNER_FOLDER / "failed"
        failed_dir.mkdir(exist_ok=True)
        filepath.rename(failed_dir / filepath.name)

class ScannerHandler(FileSystemEventHandler):
    def __init__(self, brand: str):
        self.brand = brand

    def on_created(self, event):
        if event.is_directory:
            return
        time.sleep(1)  # wait for file to finish writing
        process_file(Path(event.src_path), self.brand)

def run_scanner_watcher():
    observer = Observer()
    for brand, folder in BRAND_FOLDERS.items():
        if folder.exists():
            observer.schedule(ScannerHandler(brand), str(folder), recursive=False)
            print(f"[Scanner] Watching {folder} for brand={brand}")
    observer.start()
    print("[Scanner] Watcher started. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    from database import init_db
    init_db()
    run_scanner_watcher()
