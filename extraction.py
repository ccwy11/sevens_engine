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

# Global rate-limit smoothing: enforce at least 3 seconds between ANY Moonshot calls
_last_call_ts = 0.0


def _smooth_gap(min_gap: float = 3.0):
    """Sleep if needed so we don't fire requests too rapidly."""
    global _last_call_ts
    elapsed = time.time() - _last_call_ts
    if elapsed < min_gap:
        time.sleep(min_gap - elapsed)
    _last_call_ts = time.time()


def compress_image(image_bytes: bytes) -> tuple[bytes, str]:
    """
    Resize large photos to ~300-500 KB before base64 encoding.
    Returns (compressed_bytes, mime_type).
    If compression fails, returns original bytes with inferred MIME type.
    """
    # Try to detect original format
    mime = "image/jpeg"
    if image_bytes[:8].startswith(b"\x89PNG"):
        mime = "image/png"
    elif image_bytes[:3] == b"GIF":
        mime = "image/gif"
    elif image_bytes[:4] == b"RIFF":
        mime = "image/webp"

    # If already small, skip compression
    if len(image_bytes) < 800_000:  # < ~800 KB is fine
        return image_bytes, mime

    try:
        img = Image.open(io.BytesIO(image_bytes))
        orig_mode = img.mode
        # Convert to RGB for JPEG output
        if orig_mode in ("RGBA", "P", "LA", "L"):
            img = img.convert("RGB")
        elif orig_mode != "RGB":
            img = img.convert("RGB")

        img.thumbnail((MAX_DIM, MAX_DIM))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=JPEG_Q, optimize=True)
        compressed = buf.getvalue()

        # Only use compressed if it actually got smaller
        if len(compressed) < len(image_bytes):
            return compressed, "image/jpeg"
        else:
            return image_bytes, mime
    except Exception as e:
        print(f"[compress_image] Warning: compression failed ({e}), using original.")
        return image_bytes, mime


def _build_request_body(prompt: str, b64: str, mime_type: str):
    """Build the Moonshot API request body."""
    return {
        "model": MOONSHOT_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}}
            ]
        }],
     
    }


def _call_moonshot(image_bytes: bytes, brand_code: str, brand_name: str, use_compressed: bool = True) -> dict:
    """Single Moonshot call. Returns parsed dict or raises on unrecoverable error."""
    if use_compressed:
        data_to_send, mime_type = compress_image(image_bytes)
    else:
        # Detect MIME without compression
        mime_type = "image/jpeg"
        if image_bytes[:8].startswith(b"\x89PNG"):
            mime_type = "image/png"
        data_to_send = image_bytes

    b64 = base64.b64encode(data_to_send).decode()
    prompt = EXTRACTION_PROMPT.format(brand_name=brand_name or brand_code.upper())
    url = f"{MOONSHOT_BASE}/chat/completions"
    headers = {"Authorization": f"Bearer {MOONSHOT_KEY}", "Content-Type": "application/json"}
    body = _build_request_body(prompt, b64, mime_type)

    r = requests.post(url, json=body, headers=headers, timeout=(10, 180))
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


def extract_invoice(image_bytes: bytes, brand_code: str = "unassigned", brand_name: str = "") -> dict:
    _smooth_gap(min_gap=3.0)

    # Attempt 1: compressed (or original if already small)
    for attempt in range(2):
        try:
            # First try: compressed. Second try (only on 400): uncompressed original.
            use_compressed = (attempt == 0)
            return _call_moonshot(image_bytes, brand_code, brand_name, use_compressed=use_compressed)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else 0
            if status == 400 and attempt == 0:
                print(f"[Moonshot] 400 Bad Request with compressed image, retrying with original...")
                time.sleep(2)
                continue
            if status == 429:
                # Exponential backoff for 429
                wait = 30 * (2 ** attempt)
                print(f"[Moonshot] 429 rate limited, attempt {attempt + 1}/2, waiting {wait}s...")
                time.sleep(wait)
                continue
            # Any other HTTP error — retry once then fail soft
            if attempt == 0:
                print(f"[Moonshot] HTTP {status}, retrying once...")
                time.sleep(5)
                continue
            return _soft_fail(brand_code, f"HTTP {status}: {e}")
        except requests.exceptions.Timeout:
            if attempt == 0:
                print("[Moonshot] Timeout, retrying with original image...")
                time.sleep(5)
                continue
            return _soft_fail(brand_code, "Moonshot timed out after 2 attempts")
        except requests.exceptions.RequestException as e:
            if attempt == 0:
                print(f"[Moonshot] Request error: {e}, retrying once...")
                time.sleep(5)
                continue
            return _soft_fail(brand_code, f"Request error: {e}")

    return _soft_fail(brand_code, "All attempts exhausted")


def _soft_fail(brand_code: str, note: str) -> dict:
    """Return a structured soft failure so the bot doesn't crash."""
    return {
        "date": None, "invoice_no": None, "vendor": None,
        "total": None, "tax": None, "currency": "HKD",
        "category": "UNCATEGORIZED", "sub_category": None,
        "confidence": "low",
        "notes": f"[API_ERROR] {note}. Please retry in 2 minutes.",
        "items": [],
        "_rate_limited": True,
        "_raw_response": "",
        "_brand_code": brand_code
    }


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