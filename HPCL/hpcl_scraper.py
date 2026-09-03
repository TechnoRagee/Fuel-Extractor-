"""
HPCL (Hindustan Petroleum Corporation Limited) Fuel Station Scraper.
Scrapes all nationwide petrol pumps (~24,026 outlets) from petrolpump.hpretail.in.
Features:
- Auto-indexes sitemap index if hpcl_discovered_urls.json is missing
- Parses structured Schema.org JSON-LD (GasStation and BreadcrumbList)
- Multi-threaded concurrent processing with polite rate-limiting
- Thread-safe SQLite batch commits with unique outlet_id deduplication
- Resumable state persistence via hpcl_checkpoint.json
"""

import sys
import os
import time
import json
import sqlite3
import argparse
import ssl
import re
import gzip
import threading
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# =====================================================================
# Configuration & Constants
# =====================================================================

DB_FILE = "hpcl_outlets.db"
CHECKPOINT_FILE = "hpcl_checkpoint.json"
URLS_FILE = "hpcl_discovered_urls.json"
MASTER_SITEMAP = "https://petrolpump.hpretail.in/sitemap.xml"

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://petrolpump.hpretail.in/",
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
            outlet_name TEXT,
            dealer_name TEXT,
            state TEXT,
            city TEXT,
            locality TEXT,
            street_address TEXT,
            pincode TEXT,
            latitude REAL,
            longitude REAL,
            telephone TEXT,
            email TEXT,
            contact_person TEXT,
            page_url TEXT,
            map_url TEXT,
            created_at TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_hpcl_state ON outlets (state)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_hpcl_city ON outlets (city)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_hpcl_pincode ON outlets (pincode)")
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
    """Fetches master sitemap index and all district .xml.gz files."""
    print("  * Fetching master sitemap index from HPCL locator...")
    req = urllib.request.Request(MASTER_SITEMAP, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, context=SSL_CTX, timeout=20) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    district_gz_urls = [elem.text for elem in root.iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
    print(f"  * Discovered {len(district_gz_urls):,} district sitemaps. Downloading in parallel...")

    all_urls = []
    def fetch_gz(url):
        try:
            r = urllib.request.Request(url, headers=HTTP_HEADERS)
            with urllib.request.urlopen(r, context=SSL_CTX, timeout=15) as resp:
                data = gzip.decompress(resp.read())
                sub_root = ET.fromstring(data)
                locs = [elem.text for elem in sub_root.iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
                return [l for l in locs if '/Home' in l]
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=25) as executor:
        results = executor.map(fetch_gz, district_gz_urls)
        for res in results:
            all_urls.extend(res)

    all_urls = sorted(list(set(all_urls)))
    with open(URLS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_urls, f, indent=2)

    print(f"  * Total {len(all_urls):,} HPCL outlet URLs cached to {URLS_FILE}")
    return all_urls

def load_urls():
    """Loads HPCL URLs from file or triggers discovery if missing."""
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
    """Loads scraping checkpoint from file."""
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
# HTML & JSON-LD Extraction Handler
# =====================================================================

consecutive_errors = 0
error_lock = threading.Lock()

def clean_location_name(text):
    """Strips common SingleInterface breadcrumb prefixes like 'Fuel station in' or 'Petrol pump in'."""
    if not text:
        return ""
    text = re.sub(r'^(?:Fuel station in|Petrol pump in|Gas station in|Hindustan Petroleum in|HPCL in)\s+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+(?:Fuel station|Petrol pump|Gas station)$', '', text, flags=re.IGNORECASE)
    return text.strip()

def parse_hpcl_page(html, page_url):
    """Extracts structured outlet fields from HTML and JSON-LD."""
    # Extract outlet ID from URL (e.g. ...-416926/Home -> 416926)
    m_id = re.search(r'-([0-9]+)/Home', page_url)
    outlet_id = m_id.group(1) if m_id else page_url.split('/')[-2]

    # Defaults
    outlet_name = "Hindustan Petroleum Corporation Limited"
    dealer_name = ""
    state = ""
    city = ""
    locality = ""
    street_address = ""
    pincode = ""
    latitude = None
    longitude = None
    telephone = ""
    email = ""
    contact_person = ""
    map_url = ""

    # Parse JSON-LD scripts
    scripts = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL)
    for s in scripts:
        try:
            data = json.loads(s.strip())
            items = data if isinstance(data, list) else [data]
            for item in items:
                item_type = item.get("@type")
                if item_type in ("GasStation", "Store", "AutoRepair"):
                    outlet_name = item.get("name") or outlet_name
                    dealer_name = item.get("alternateName") or dealer_name
                    map_url = item.get("hasMap") or map_url
                    
                    # Phones
                    telephones = item.get("telephone")
                    if isinstance(telephones, list) and telephones:
                        telephone = ", ".join(str(t) for t in telephones if t)
                    elif isinstance(telephones, str):
                        telephone = telephones

                    # Address
                    addr = item.get("address") or {}
                    if isinstance(addr, dict):
                        street_address = addr.get("streetAddress") or street_address
                        locality = addr.get("addressLocality") or locality
                        city = addr.get("addressRegion") or city
                        pincode = addr.get("postalCode") or pincode
                        if not email:
                            email = addr.get("email") or ""

                    # Coordinates
                    geo = item.get("geo") or {}
                    if isinstance(geo, dict):
                        try:
                            latitude = float(geo.get("latitude"))
                            longitude = float(geo.get("longitude"))
                        except (TypeError, ValueError):
                            pass

                    # Contact point
                    cp = item.get("contactPoint") or {}
                    if isinstance(cp, dict):
                        contact_person = cp.get("name") or contact_person
                        if not email:
                            email = cp.get("email") or ""

                elif item_type == "BreadcrumbList":
                    elements = item.get("itemListElement") or []
                    names = [el.get("item", {}).get("name") for el in elements if isinstance(el, dict) and el.get("item", {}).get("name")]
                    if len(names) >= 2:
                        state = clean_location_name(names[1])
                    if len(names) >= 3:
                        city = clean_location_name(names[2])
                    if len(names) >= 4:
                        locality = clean_location_name(names[3])

        except Exception:
            pass

    # Fallback to HTML meta or regex if state is still missing
    if not state:
        m_state = re.search(r'property=["\']business:contact_data:region["\']\s+content=["\']([^"\']+)["\']', html)
        if m_state:
            state = clean_location_name(m_state.group(1).strip())

    state = clean_location_name(state)
    city = clean_location_name(city)
    locality = clean_location_name(locality)

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "outlet_id": str(outlet_id).strip(),
        "outlet_name": outlet_name.strip(),
        "dealer_name": dealer_name.strip(),
        "state": state.strip(),
        "city": city.strip(),
        "locality": locality.strip(),
        "street_address": street_address.strip(),
        "pincode": str(pincode).strip(),
        "latitude": latitude,
        "longitude": longitude,
        "telephone": telephone.strip(),
        "email": email.strip(),
        "contact_person": contact_person.strip(),
        "page_url": page_url,
        "map_url": map_url,
        "created_at": created_at
    }

def fetch_outlet_page(url, delay=0.2, max_retries=3):
    """Fetches HPCL outlet webpage and returns parsed dict."""
    global consecutive_errors

    if delay > 0:
        time.sleep(delay)

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=HTTP_HEADERS)
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                parsed = parse_hpcl_page(html, url)
                with error_lock:
                    consecutive_errors = 0
                return parsed

        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                with error_lock:
                    consecutive_errors += 1
                    if consecutive_errors >= 3:
                        print(f"\n[!] Rate-limit detected (HTTP {e.code}). Cooling down for 20s...")
                        time.sleep(20)
                        consecutive_errors = 0
                time.sleep(2.0 * (attempt + 1))
            elif e.code == 404:
                return None
            else:
                time.sleep(1.0)
        except Exception:
            time.sleep(1.0)

    return None

# =====================================================================
# Main Scraper Execution Engine
# =====================================================================

def run_scraper(workers=8, delay=0.2, limit=None, reset=False):
    """Runs nationwide HPCL scraping pipeline."""
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
    print(" HINDUSTAN PETROLEUM (HPCL) FUEL STATIONS EXTRACTOR")
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
                                    outlet_id, outlet_name, dealer_name, state, city,
                                    locality, street_address, pincode, latitude, longitude,
                                    telephone, email, contact_person, page_url, map_url, created_at
                                ) VALUES (
                                    :outlet_id, :outlet_name, :dealer_name, :state, :city,
                                    :locality, :street_address, :pincode, :latitude, :longitude,
                                    :telephone, :email, :contact_person, :page_url, :map_url, :created_at
                                )
                            """, record)
                            newly_added += cur.rowcount
                            conn.commit()
                except Exception:
                    pass

                processed_urls_list.append(url)

                # Periodic checkpoint save
                if time.time() - last_checkpoint_time > 10 or done_count % 10 == 0:
                    save_checkpoint(processed_urls_list)
                    last_checkpoint_time = time.time()

                # Live progress line
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

# =====================================================================
# CLI Arguments
# =====================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Hindustan Petroleum (HPCL) Fuel Stations across India.")
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
