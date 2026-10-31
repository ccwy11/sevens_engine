import asyncio
import os
import sys
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from config import BOT_CONFIG, DASHBOARD_PASSWORD
from extraction import extract_invoice, validate_totals
from database import save_invoice, update_invoice_status
from drive import upload_file

# Map brand code -> display name
BRAND_NAMES = {
    "sevens": "SEVENS",
    "kuro_kare": "Kuro Kare",
    "unassigned": "Unassigned / Test"
}

# Limit concurrent Moonshot vision calls so 3 simultaneous receipts don't fire 3 giants at once
LLM_SEM = asyncio.Semaphore(2)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, brand: str):
    msg = update.message
    photo = msg.photo[-1] if msg.photo else None
    doc = msg.document

    file_obj = photo or doc
    if not file_obj:
        await msg.reply_text("Please send a photo or PDF of the receipt.")
        return

    await msg.reply_text("⏳ Processing receipt...")

    try:
        tg_file = await file_obj.get_file()
        bytes_data = await tg_file.download_as_bytearray()
        bytes_data = bytes(bytes_data)

        ext = "jpg"
        if doc and doc.file_name:
            ext = doc.file_name.split(".")[-1].lower()[:4]
        filename = f"{brand}_{msg.message_id}_{msg.date.strftime('%Y%m%d_%H%M%S')}.{ext}"

        drive_id = upload_file(bytes_data, filename, "image/jpeg" if ext in ("jpg", "jpeg", "png") else "application/pdf")

        # Offload blocking LLM call to a thread so the event loop stays responsive for other bots
        async with LLM_SEM:
            extracted = await asyncio.to_thread(
                extract_invoice,
                bytes_data,
                brand_code=brand,
                brand_name=BRAND_NAMES.get(brand, brand)
            )
        extracted = validate_totals(extracted)

        # Rate-limited soft failure: save the raw file, tell user to retry
        if extracted.get("_rate_limited"):
            payload = {
                "brand": brand,
                "input_channel": f"{brand}_bot",
                "date": None,
                "invoice_no": None,
                "vendor": None,
                "total": None,
                "tax": None,
                "currency": "HKD",
                "category": "UNCATEGORIZED",
                "sub_category": None,
                "confidence": "low",
                "prompt_version": "v1",
                "raw_json": {"response": "", "parsed": {}},
                "drive_file_id": drive_id,
                "source_file": filename,
                "notes": extracted.get("notes", ""),
                "status": "needs_review",
                "items": []
            }
            invoice_id = save_invoice(payload)
            await msg.reply_text(
                f"⏳ Receipt #{invoice_id} saved, but Moonshot is rate-limited right now.\n"
                f"Please retry this receipt in 2 minutes, or review it in the dashboard later.\n"
                f"File: {filename}"
            )
            return

        payload = {
            "brand": brand,
            "input_channel": f"{brand}_bot",
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

        items_summary = ""
        for it in extracted.get("items", [])[:5]:
            items_summary += f"\n- {it.get('item_name', 'Item')}: {it.get('qty', 1)} x {it.get('unit_price', 0):.2f} = {it.get('amount', 0):.2f}"
        if len(extracted.get("items", [])) > 5:
            items_summary += f"\n... and {len(extracted['items']) - 5} more items"

        status_emoji = "✅" if extracted.get("confidence") == "high" else "⚠️"
        reply = (
            f"{status_emoji} Receipt #{invoice_id}\n"
            f"Brand: {BRAND_NAMES.get(brand, brand)}\n"
            f"Vendor: {extracted.get('vendor') or 'N/A'}\n"
            f"Date: {extracted.get('date') or 'N/A'}\n"
            f"Total: {extracted.get('total') or 'N/A'} {extracted.get('currency', 'HKD')}\n"
            f"Category: {extracted.get('category')} / {extracted.get('sub_category') or '-'}\n"
            f"Confidence: {extracted.get('confidence', 'low').upper()}"
            f"{items_summary}\n\n"
            f"{'Review in dashboard if confidence is low.' if extracted.get('confidence') != 'high' else ''}"
        )
        await msg.reply_text(reply)

    except Exception as e:
        print(f"Error processing receipt: {e}")
        await msg.reply_text(f"❌ Error processing receipt. Saved for manual review.\nError: {str(e)[:200]}")

async def make_handler(brand: str):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await handle_photo(update, context, brand)
    return handler

async def run_bots():
    apps = []
    for bot in BOT_CONFIG:
        if not bot["token"]:
            print(f"Skipping {bot['name']} — no token")
            continue
        app = Application.builder().token(bot["token"]).build()
        app.add_handler(MessageHandler(filters.PHOTO | filters.Document.PDF, await make_handler(bot["brand"])))
        apps.append((bot["name"], app))
        print(f"Registered bot: {bot['name']} -> brand={bot['brand']}")

    if not apps:
        print("No bots configured. Set BOT_CONFIG env var.")
        sys.exit(1)

    await asyncio.gather(*[app.initialize() for _, app in apps])
    await asyncio.gather(*[app.start() for _, app in apps])
    await asyncio.gather(*[app.updater.start_polling() for _, app in apps])

    print("All bots polling. Press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        for _, app in apps:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

if __name__ == "__main__":
    from database import init_db
    init_db()
    print("Database initialized.")
    asyncio.run(run_bots())