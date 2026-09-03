"""
Jio-bp (Reliance BP Mobility Limited) Fuel Stations Scraper.
Extracts nationwide Jio-bp retail mobility stations (~2,258 outlets) from mobilitystation.jiobp.com.
Features:
- Discovers and caches all 2,258 station URLs from official state sitemaps
- Parses structured Schema.org JSON-LD (LocalBusiness and BreadcrumbList)
- Multi-threaded processing with polite rate-limiting
- Thread-safe SQLite batch commits with unique outlet_id deduplication
- Resumable state persistence via jiobp_checkpoint.json
"""

import sys
import os
import time
import json
import sqlite3
import argparse
import ssl
import re
import threading
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# =====================================================================
# Configuration & Constants
# =====================================================================

DB_FILE = "jiobp_outlets.db"
CHECKPOINT_FILE = "jiobp_checkpoint.json"
URLS_FILE = "jiobp_discovered_urls.json"
MASTER_SITEMAP = "https://mobilitystation.jiobp.com/sitemap.xml"

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://mobilitystation.jiobp.com/",
}

SSL_CTX = ssl._create_unverified_context()

# =====================================================================
# Database Setup
# =====================================================================

def init_database(db_path=DB_FILE):
    """Initializes SQLite database with outlets table."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS outlets (
            outlet_id TEXT PRIMARY KEY,
            station_name TEXT,
            dealer_name TEXT,
            state TEXT,
            city TEXT,
            locality TEXT,
            street_address TEXT,
            pincode TEXT,
            latitude REAL,
            longitude REAL,
            telephone TEXT,
            rating_value REAL,
            review_count INTEGER,
            page_url TEXT,
            created_at TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_jiobp_state ON outlets (state)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_jiobp_city ON outlets (city)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_jiobp_pincode ON outlets (pincode)")
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
# Sitemap Discovery & URL Loader
# =====================================================================

def discover_all_urls():
    """Fetches master sitemap and all state sitemaps to index station URLs."""
    print("  * Fetching Jio-bp master sitemap index...")
    req = urllib.request.Request(MASTER_SITEMAP, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    state_sitemaps = [elem.text for elem in root.iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
    print(f"  * Discovered {len(state_sitemaps)} state sitemaps. Downloading station URLs in parallel...")

    all_urls = []
    def fetch_state_sitemap(url):
        try:
            r = urllib.request.Request(url, headers=HTTP_HEADERS)
            with urllib.request.urlopen(r, context=SSL_CTX, timeout=12) as s_resp:
                s_root = ET.fromstring(s_resp.read())
                locs = [elem.text for elem in s_root.iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
                return [l for l in locs if l and l.endswith('/Home')]
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_state_sitemap, state_sitemaps)
        for res in results:
            all_urls.extend(res)

    all_urls = sorted(list(set(all_urls)))
    with open(URLS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_urls, f, indent=2)

    print(f"  * Discovered total {len(all_urls):,} Jio-bp stations saved to {URLS_FILE}")
    return all_urls

def load_urls():
    """Loads station URLs from file or triggers discovery if missing."""
    if os.path.exists(URLS_FILE):
        try:
            with open(URLS_FILE, "r", encoding="utf-8") as f:
                urls = json.load(f)
                if urls:
                    return urls
        except Exception:
            pass
    return discover_all_urls()

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
    return {"processed_urls": [], "last_updated": None}

def save_checkpoint(processed_urls):
    """Saves scraping checkpoint."""
    data = {
        "processed_urls": processed_urls,
        "processed_count": len(processed_urls),
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# =====================================================================
# Page Parser
# =====================================================================

def parse_jiobp_page(html, page_url):
    """Extracts structured fields from Jio-bp station HTML."""
    # Extract outlet ID from URL (e.g. jio-bp-...-510354/Home -> 510354)
    m_id = re.search(r'-([0-9]+)/Home', page_url)
    outlet_id = m_id.group(1) if m_id else page_url.split('/')[-2]

    station_name = "Jio-bp"
    dealer_name = ""
    state = ""
    city = ""
    locality = ""
    street_address = ""
    pincode = ""
    latitude = None
    longitude = None
    telephone = ""
    rating_value = None
    review_count = 0

    # Parse JSON-LD blocks
    scripts = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL)
    for s in scripts:
        try:
            data = json.loads(s.strip())
            item_type = data.get("@type")
            if item_type in ("LocalBusiness", "GasStation", "Store"):
                station_name = data.get("name") or station_name
                telephone = data.get("telephone") or telephone

                # Address
                addr = data.get("address") or {}
                if isinstance(addr, dict):
                    street_address = addr.get("streetAddress") or street_address
                    locality = addr.get("addressLocality") or locality
                    state = addr.get("addressRegion") or state

                # Geo
                geo = data.get("geo") or {}
                if isinstance(geo, dict):
                    try:
                        latitude = float(geo.get("latitude"))
                        longitude = float(geo.get("longitude"))
                    except (TypeError, ValueError):
                        pass

                # Rating
                rating = data.get("aggregateRating") or {}
                if isinstance(rating, dict):
                    try:
                        rating_value = float(rating.get("ratingValue"))
                        review_count = int(rating.get("reviewCount", 0))
                    except (TypeError, ValueError):
                        pass

            elif item_type == "BreadcrumbList":
                items = data.get("itemListElement") or []
                names = [it.get("name") for it in items if isinstance(it, dict) and it.get("name")]
                # Breadcrumbs: [Stores, State, City/Locality, Area Pincode]
                if len(names) >= 2 and not state:
                    state = names[1]
                if len(names) >= 3:
                    city = names[2]
                if len(names) >= 4:
                    raw_pin = names[3]
                    m_pin = re.search(r'\b([0-9]{6})\b', raw_pin)
                    if m_pin:
                        pincode = m_pin.group(1)

        except Exception:
            pass

    # Extract dealer name from slug if available
    slug = page_url.replace("https://mobilitystation.jiobp.com/", "").replace("/Home", "")
    m_dealer = re.search(r'jio-bp-(.*?)-petrol-pump', slug)
    if m_dealer:
        dealer_name = m_dealer.group(1).replace('-', ' ').title()

    # Fallback pincode from address
    if not pincode and street_address:
        m_pin = re.search(r'\b([0-9]{6})\b', street_address)
        if m_pin:
            pincode = m_pin.group(1)

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "outlet_id": str(outlet_id).strip(),
        "station_name": station_name.strip(),
        "dealer_name": dealer_name.strip(),
        "state": state.strip(),
        "city": city.strip(),
        "locality": locality.strip(),
        "street_address": street_address.strip(),
        "pincode": str(pincode).strip(),
        "latitude": latitude,
        "longitude": longitude,
        "telephone": telephone.strip(),
        "rating_value": rating_value,
        "review_count": review_count,
        "page_url": page_url,
        "created_at": created_at
    }

def fetch_outlet_page(url, delay=0.2, max_retries=3):
    """Fetches a single station page and parses data."""
    if delay > 0:
        time.sleep(delay)

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=HTTP_HEADERS)
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=12) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                return parse_jiobp_page(html, url)
        except Exception:
            time.sleep(1.0)
    return None

# =====================================================================
# Main Scraper Execution Engine
# =====================================================================

def run_scraper(workers=8, delay=0.2, limit=None, reset=False):
    """Runs nationwide Jio-bp scraping pipeline."""
    if reset:
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
            print(f"[x] Removed existing {DB_FILE}")
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
            print(f"[x] Removed existing {CHECKPOINT_FILE}")

    init_database(DB_FILE)
    initial_count = get_db_count(DB_FILE)

    # 1. Load URLs
    all_urls = load_urls()
    total_urls = len(all_urls)

    # 2. Checkpoint filtering
    checkpoint = load_checkpoint()
    processed_set = set(checkpoint.get("processed_urls", []))

    pending_urls = [u for u in all_urls if u not in processed_set]

    if limit and limit > 0:
        pending_urls = pending_urls[:limit]

    print("=" * 70)
    print(" JIO-BP (RELIANCE) FUEL STATIONS EXTRACTOR")
    print("=" * 70)
    print(f"  * Total Discovered URLs: {total_urls:,}")
    print(f"  * Already Processed:     {len(processed_set):,}")
    print(f"  * Pending in This Run:   {len(pending_urls):,}")
    print(f"  * Existing DB Outlets:   {initial_count:,}")
    print(f"  * Workers (Threads):     {workers}")
    print(f"  * Polite Delay:          {delay}s")
    print("=" * 70)

    if not pending_urls:
        print("[OK] All outlet URLs have already been processed! Nothing to do.")
        return

    db_lock = threading.Lock()
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cur = conn.cursor()

    processed_urls_list = list(processed_set)
    newly_added = 0
    start_time = time.time()
    last_checkpoint_time = time.time()

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_url = {
                executor.submit(fetch_outlet_page, url, delay): url
                for url in pending_urls
            }

            done_count = 0
            total_tasks = len(pending_urls)

            for future in as_completed(future_to_url):
                url = future_to_url[future]
                done_count += 1
                try:
                    record = future.result()
                    if record:
                        with db_lock:
                            cur.execute("""
                                INSERT OR IGNORE INTO outlets (
                                    outlet_id, station_name, dealer_name, state, city,
                                    locality, street_address, pincode, latitude, longitude,
                                    telephone, rating_value, review_count, page_url, created_at
                                ) VALUES (
                                    :outlet_id, :station_name, :dealer_name, :state, :city,
                                    :locality, :street_address, :pincode, :latitude, :longitude,
                                    :telephone, :rating_value, :review_count, :page_url, :created_at
                                )
                            """, record)
                            newly_added += cur.rowcount
                            conn.commit()
                except Exception:
                    pass

                processed_urls_list.append(url)

                if time.time() - last_checkpoint_time > 10 or done_count % 10 == 0:
                    save_checkpoint(processed_urls_list)
                    last_checkpoint_time = time.time()

                elapsed = time.time() - start_time
                rate = done_count / max(elapsed, 0.001)
                total_in_db = initial_count + newly_added
                pct = (done_count / total_tasks) * 100
                print(
                    f"[{done_count:>4}/{total_tasks} | {pct:>5.1f}%] "
                    f"DB Total: {total_in_db:>5,} (+{newly_added:>4,}) | "
                    f"Speed: {rate:>4.1f} pages/s",
                    flush=True
                )

        save_checkpoint(processed_urls_list)

    finally:
        conn.close()

    total_time = time.time() - start_time
    final_count = get_db_count(DB_FILE)

    print("\n" + "=" * 70)
    print(" [OK] SCRAPING SESSION COMPLETE")
    print("=" * 70)
    print(f"  * Outlets Processed:     {len(pending_urls):,}")
    print(f"  * Total Unique in DB:    {final_count:,} (+{newly_added:,} this run)")
    print(f"  * Time Taken:            {total_time / 60:.1f} minutes ({total_time:.1f}s)")
    print(f"  * Database File:         {DB_FILE}")
    print("=" * 70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Jio-bp / Reliance Fuel Stations across India.")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent worker threads (default: 8)")
    parser.add_argument("--delay", type=float, default=0.2, help="Polite delay between requests in seconds (default: 0.2)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of outlets to process (optional)")
    parser.add_argument("--reset", action="store_true", help="Reset database and checkpoint before starting")

    args = parser.parse_args()
    run_scraper(
        workers=args.workers,
        delay=args.delay,
        limit=args.limit,
        reset=args.reset
    )
