#!/usr/bin/env python3
"""Test extraction service with a local image — no Telegram needed."""
import sys
from pathlib import Path
from extraction import extract_invoice, validate_totals

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_extraction.py <image_path> [brand_code]")
        sys.exit(1)

    img_path = Path(sys.argv[1])
    brand = sys.argv[2] if len(sys.argv) > 2 else "unassigned"

    with open(img_path, "rb") as f:
        img_bytes = f.read()

    print(f"Testing extraction for brand={brand} ...")
    result = extract_invoice(img_bytes, brand_code=brand, brand_name=brand.upper())
    result = validate_totals(result)

    print("\n--- Extracted ---")
    for k, v in result.items():
        if not k.startswith("_"):
            print(f"{k}: {v}")

    print(f"\nRaw response preview: {result.get('_raw_response', '')[:300]}...")

if __name__ == "__main__":
    main()
