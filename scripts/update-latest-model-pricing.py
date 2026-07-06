#!/usr/bin/env python3
"""
update-latest-model-pricing.py — Fetch latest model pricing from GitHub Copilot docs.

Scrapes https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing
and updates observability/model-pricing.json with current pricing.

Usage:
    python3 scripts/update-latest-model-pricing.py
    python3 scripts/update-latest-model-pricing.py --dry-run
    python3 scripts/update-latest-model-pricing.py --output path/to/pricing.json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError, HTTPError
except ImportError:
    print("ERROR: urllib not available", file=sys.stderr)
    sys.exit(1)

PRICING_URL = "https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing"
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_OUTPUT = REPO_ROOT / "observability" / "model-pricing.json"


def fetch_page(url: str) -> str:
    """Fetch HTML content from URL."""
    req = Request(url, headers={"User-Agent": "SDLC-Pipeline-Pricing-Updater/1.0"})
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except (URLError, HTTPError) as e:
        print(f"ERROR: Failed to fetch {url}: {e}", file=sys.stderr)
        sys.exit(1)


def parse_pricing_table(html: str) -> dict:
    """
    Parse model pricing from the GitHub docs HTML page.

    Looks for table rows containing model names and pricing columns.
    Returns dict of model_name -> {provider, input_per_1m_tokens, output_per_1m_tokens}.
    """
    models = {}

    # Pattern to match table rows with model pricing data
    # GitHub docs format: | Model | Provider | Input/1M | Output/1M | ...
    row_pattern = re.compile(
        r"<tr[^>]*>.*?<td[^>]*>(.*?)</td>.*?<td[^>]*>(.*?)</td>.*?"
        r"<td[^>]*>\$?([\d.]+)</td>.*?<td[^>]*>\$?([\d.]+)</td>",
        re.DOTALL
    )

    for match in row_pattern.finditer(html):
        model_name = re.sub(r"<[^>]+>", "", match.group(1)).strip().lower()
        provider = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        try:
            input_price = float(match.group(3))
            output_price = float(match.group(4))
        except ValueError:
            continue

        if model_name and input_price >= 0 and output_price >= 0:
            models[model_name] = {
                "provider": provider,
                "input_per_1m_tokens": input_price,
                "output_per_1m_tokens": output_price,
            }

    return models


def load_existing(path: Path) -> dict:
    """Load existing pricing JSON file."""
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"_metadata": {}, "models": {}}


def merge_pricing(existing: dict, fetched: dict) -> dict:
    """Merge fetched pricing into existing, preserving manual entries."""
    result = existing.copy()
    result["_metadata"] = {
        "source": PRICING_URL,
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "update_script": "scripts/update-latest-model-pricing.py",
    }

    if "models" not in result:
        result["models"] = {}

    # Update existing models and add new ones
    for model_name, pricing in fetched.items():
        result["models"][model_name] = pricing

    return result


def main():
    parser = argparse.ArgumentParser(description="Update model pricing from GitHub Copilot docs")
    parser.add_argument("--dry-run", action="store_true", help="Print fetched pricing without writing")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON file path")
    args = parser.parse_args()

    print(f"Fetching pricing from: {PRICING_URL}")
    html = fetch_page(PRICING_URL)

    fetched_models = parse_pricing_table(html)

    if not fetched_models:
        print("WARNING: No pricing data parsed from page.", file=sys.stderr)
        print("The page structure may have changed. Keeping existing pricing file.", file=sys.stderr)
        print("Please update observability/model-pricing.json manually if needed.", file=sys.stderr)
        sys.exit(0)

    print(f"Parsed {len(fetched_models)} models from docs")

    if args.dry_run:
        print("\n--- Fetched Pricing (dry-run) ---")
        print(json.dumps(fetched_models, indent=2))
        return

    existing = load_existing(args.output)
    merged = merge_pricing(existing, fetched_models)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
        f.write("\n")

    print(f"Updated {args.output} with {len(fetched_models)} models")


if __name__ == "__main__":
    main()
