import json
import base64
import io
import requests
import time
from typing import List, Dict
from PIL import Image
from config import MOONSHOT_KEY, MOONSHOT_BASE, MOONSHOT_MODEL

EXTRACTION_PROMPT = """You are an invoice extraction engine for a Hong Kong restaurant group.

Extract ALL details from this receipt/invoice image and reply with ONLY a valid JSON object. No markdown, no explanation, no text outside the JSON.

The restaurant brand for this invoice is: {brand_name}

Taxonomy rules for categorization:
- Category must be one of: Food Ingredients, non-food Ingredients, Operating expenses, Utilities, UNCATEGORIZED
- SubCategory for Food Ingredients must be one of: Meat, Veg, Seasoning, Toppings, Rice, Soy, Egg, Poultry, DRIED SEAFOOD
- SubCategory for non-food Ingredients: use a descriptive name or null
- SubCategory for Operating expenses/Utilities: use a descriptive name or null

JSON schema required:
{{
  "date": "YYYY-MM-DD or null",
  "invoice_no": "string or null",
  "vendor": "string or null",
  "total": number or null,
  "tax": number or null,
  "currency": "3-letter code (default HKD)",
  "category": "one of: Food Ingredients, non-food Ingredients, Operating expenses, Utilities, UNCATEGORIZED",
  "sub_category": "from taxonomy above or null",
  "confidence": "high|medium|low",
  "notes": "string or empty",
  "items": [
    {{
      "item_name": "string",
      "qty": number,
      "unit_price": number,
      "amount": number,
      "sub_category": "from taxonomy above or null"
    }}
  ]
}}

Important:
- Extract line items from the table/listed products. If unclear, return empty items array.
- Amounts should be numbers (no commas, no currency symbols).
- If the receipt is handwritten or very blurry, set confidence to low.
- If brand is "unassigned", just extract normally — a human will assign the brand later.
- Default currency is HKD if not visible on receipt.
"""

MAX_DIM = 1600
JPEG_Q = 80


def compress_image(image_bytes: bytes) -> bytes:
    """Resize large phone photos to ~300-500 KB before base64 encoding."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        # Convert palette/RGBA/etc to RGB for JPEG
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((MAX_DIM, MAX_DIM))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=JPEG_Q, optimize=True)
        return buf.getvalue()
    except Exception:
        # If Pillow fails (e.g. PDF), return original
        return image_bytes


def extract_invoice(image_bytes: bytes, brand_code: str = "unassigned", brand_name: str = "") -> dict:
    compressed = compress_image(image_bytes)
    b64 = base64.b64encode(compressed).decode()
    prompt = EXTRACTION_PROMPT.format(brand_name=brand_name or brand_code.upper())
    url = f"{MOONSHOT_BASE}/chat/completions"
    headers = {"Authorization": f"Bearer {MOONSHOT_KEY}", "Content-Type": "application/json"}
    body = {
        "model": MOONSHOT_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ]
        }],
        "temperature": 0.1
    }

    for attempt in range(4):
        try:
            r = requests.post(url, json=body, headers=headers, timeout=(10, 180))
            if r.status_code == 200:
                break
            if r.status_code == 429 and attempt < 3:
                wait = 20 * (attempt + 1)
                print(f"Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            r.raise_for_status()
        except requests.exceptions.Timeout:
            if attempt < 3:
                print(f"Moonshot timed out, retry {attempt + 1}/3...")
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except requests.exceptions.RequestException as e:
            if attempt == 3:
                raise
            time.sleep(5)
            continue
    else:
        r.raise_for_status()

    text = r.json()["choices"][0]["message"]["content"].strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {
            "date": None, "invoice_no": None, "vendor": None,
            "total": None, "tax": None, "currency": "HKD",
            "category": "UNCATEGORIZED", "sub_category": None,
            "confidence": "low", "notes": f"Parse error. Raw: {text[:500]}",
            "items": []
        }

    parsed["_raw_response"] = text
    parsed["_brand_code"] = brand_code
    return parsed


def validate_totals(data: dict) -> dict:
    items = data.get("items", [])
    if items:
        calc_total = sum(i.get("amount", 0) or 0 for i in items)
        declared = data.get("total") or 0
        if declared and abs(calc_total - declared) > 0.5:
            data["notes"] = (data.get("notes", "") + f" [Total mismatch: items sum {calc_total:.2f} vs declared {declared:.2f}]").strip()
            if data.get("confidence") == "high":
                data["confidence"] = "medium"
    return data