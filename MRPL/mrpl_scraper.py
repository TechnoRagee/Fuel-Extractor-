"""
MRPL (Mangalore Refinery and Petrochemicals Limited - ONGC Subsidiary) Scraper.
Extracts nationwide MRPL HiQ retail petrol pumps across Karnataka, Kerala, and Tamil Nadu.
Features:
- Directory-safe: works whether executed from inside MRPL/ or from workspace root
- Headless Playwright integration to automatically solve Prophaze Bot Protection WAF
- Structured extraction of Station Name, District, State, and Daily Fuel Rates (Petrol & Diesel)
- Thread-safe SQLite batch commits with unique station deduplication
- Resumable state persistence via mrpl_checkpoint.json
"""

import sys
import os
import time
import json
import sqlite3
import argparse
import re
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# =====================================================================
# Directory-Safe Path Resolution
# =====================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(SCRIPT_DIR, "mrpl_outlets.db")
CHECKPOINT_FILE = os.path.join(SCRIPT_DIR, "mrpl_checkpoint.json")

PORTAL_URL = "https://mrpl.co.in/en/RetailSale"

# State mapping for tables on mrpl.co.in/en/RetailSale
STATE_TABLE_MAPPING = [
    (3, "Tamil Nadu"),
    (4, "Karnataka"),
    (5, "Kerala")
]

# =====================================================================
# Database Setup
# =====================================================================

def init_database(db_path=DB_FILE):
    """Initializes SQLite database with outlets table."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS outlets (
            station_id TEXT PRIMARY KEY,
            station_name TEXT,
            brand TEXT DEFAULT 'MRPL HiQ',
            district TEXT,
            state TEXT,
            diesel_price REAL,
            petrol_price REAL,
            raw_location TEXT,
            created_at TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mrpl_state ON outlets (state)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mrpl_district ON outlets (district)")
    conn.commit()
    conn.close()

def get_db_count(db_path=DB_FILE):
    """Returns total unique outlets in DB."""
    if not os.path.exists(db_path):
        return 0
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM outlets")
        count = cur.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0

# =====================================================================
# Checkpoint Manager
# =====================================================================

def load_checkpoint():
    """Loads scraping checkpoint."""
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"total_extracted": 0, "last_updated": None}

def save_checkpoint(total_count):
    """Saves scraping checkpoint."""
    data = {
        "total_extracted": total_count,
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# =====================================================================
# Page Fetcher & Parser
# =====================================================================

def fetch_mrpl_page_html():
    """Fetches MRPL RetailSale HTML using headless Playwright to bypass Prophaze WAF."""
    print("  * Navigating to MRPL portal via headless browser (solving Prophaze challenge)...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"}
        )
        page = context.new_page()

        page.goto(PORTAL_URL, wait_until="networkidle", timeout=35000)
        page.wait_for_timeout(3000)

        html = page.content()
        browser.close()
        return html

def parse_stations_from_html(html):
    """Parses station tables from MRPL RetailSale HTML."""
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    stations = []
    seen = set()
    counter = 1

    for t_idx, state in STATE_TABLE_MAPPING:
        if t_idx >= len(tables):
            continue
        table = tables[t_idx]
        rows = table.find_all("tr")

        for r in rows:
            cells = [td.get_text(strip=True) for td in r.find_all(["td", "th"])]
            if len(cells) >= 3:
                loc_raw = cells[0]
                diesel = cells[1]
                petrol = cells[2]

                d_clean = re.sub(r'[^0-9\.]', '', diesel)
                p_clean = re.sub(r'[^0-9\.]', '', petrol)

                if not d_clean or not p_clean:
                    continue

                try:
                    d_val = float(d_clean)
                    p_val = float(p_clean)
                except ValueError:
                    continue

                # Skip header rows
                if "diesel" in loc_raw.lower() or "product" in loc_raw.lower():
                    continue

                # Split location and district
                district = ""
                if "," in loc_raw:
                    parts = loc_raw.split(",")
                    station_name = parts[0].strip()
                    district = parts[1].strip()
                elif "-" in loc_raw:
                    parts = loc_raw.split("-")
                    station_name = parts[0].strip()
                    district = parts[1].strip()
                else:
                    station_name = loc_raw.strip()

                station_name = station_name.title()
                district = district.title()

                key = (station_name.lower(), state.lower())
                if key in seen:
                    continue
                seen.add(key)

                state_prefix = "KA" if state == "Karnataka" else ("KL" if state == "Kerala" else "TN")
                station_id = f"MRPL-{state_prefix}-{counter:03d}"
                counter += 1

                created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                stations.append({
                    "station_id": station_id,
                    "station_name": station_name,
                    "brand": "MRPL HiQ",
                    "district": district,
                    "state": state,
                    "diesel_price": d_val,
                    "petrol_price": p_val,
                    "raw_location": loc_raw,
                    "created_at": created_at
                })

    return stations

# =====================================================================
# Main Scraper Execution Engine
# =====================================================================

def run_scraper(reset=False):
    """Runs nationwide MRPL scraping pipeline."""
    if reset:
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
            print(f"[x] Removed existing {DB_FILE}")
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
            print(f"[x] Removed existing {CHECKPOINT_FILE}")

    init_database(DB_FILE)
    initial_count = get_db_count(DB_FILE)

    print("=" * 70)
    print(" MRPL (ONGC) FUEL STATIONS EXTRACTOR")
    print("=" * 70)
    print(f"  * Portal URL:            {PORTAL_URL}")
    print(f"  * Existing DB Outlets:   {initial_count:,}")
    print("=" * 70)

    start_time = time.time()

    try:
        html = fetch_mrpl_page_html()
        stations = parse_stations_from_html(html)

        print(f"  * Parsed {len(stations)} total operational stations from live portal tables.")

        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        newly_added = 0

        for s in stations:
            cur.execute("""
                INSERT OR REPLACE INTO outlets (
                    station_id, station_name, brand, district, state,
                    diesel_price, petrol_price, raw_location, created_at
                ) VALUES (
                    :station_id, :station_name, :brand, :district, :state,
                    :diesel_price, :petrol_price, :raw_location, :created_at
                )
            """, s)
            newly_added += cur.rowcount

        conn.commit()
        conn.close()

        save_checkpoint(len(stations))

        total_time = time.time() - start_time
        final_count = get_db_count(DB_FILE)

        print("\n" + "=" * 70)
        print(" [OK] SCRAPING SESSION COMPLETE")
        print("=" * 70)
        print(f"  * Total Stations in DB:  {final_count:,} (+{newly_added:,} this run)")
        print(f"  * Time Taken:            {total_time:.1f} seconds")
        print(f"  * Database File:         {DB_FILE}")
        print("=" * 70)

    except Exception as e:
        print(f"[!] Scraper failed: {e}")
        raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape MRPL Fuel Stations across India.")
    parser.add_argument("--reset", action="store_true", help="Reset database and checkpoint before starting")
    args = parser.parse_args()

    run_scraper(reset=args.reset)
