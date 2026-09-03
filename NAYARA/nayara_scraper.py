"""
Nayara Energy (formerly Essar Oil) Fuel Stations Scraper.
Extracts nationwide Nayara retail outlets (~6,500+ petrol pumps) via backend REST API.
Features:
- Automated Chrome TLS impersonation using curl_cffi to bypass Cloudflare/WAF
- Dynamic CSRF token and cookie session management
- Intelligent nationwide spatial grid with 50 km search radius
- Address parsing for Village, Taluka, District, State, and Pincode
- Live fuel prices (Petrol and Diesel rates per station)
- Thread-safe SQLite batch commits with unique cms_code deduplication
- Resumable state persistence via nayara_checkpoint.json
"""

import sys
import os
import time
import json
import sqlite3
import argparse
import re
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from curl_cffi import requests
from bs4 import BeautifulSoup

# =====================================================================
# Configuration & Constants
# =====================================================================

DB_FILE = "nayara_outlets.db"
CHECKPOINT_FILE = "nayara_checkpoint.json"
LOCATOR_PAGE_URL = "https://www.nayaraenergy.com/petrol-pump-near-me"
API_URL = "https://www.nayaraenergy.com/get-code-ro-radius"

# =====================================================================
# Database Setup
# =====================================================================

def init_database(db_path=DB_FILE):
    """Initializes SQLite database with outlets table."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS outlets (
            cms_code TEXT PRIMARY KEY,
            ro_name TEXT,
            address TEXT,
            village TEXT,
            taluka TEXT,
            district TEXT,
            state TEXT,
            pincode TEXT,
            latitude REAL,
            longitude REAL,
            efp TEXT,
            petrol_price REAL,
            diesel_price REAL,
            created_at TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_nayara_state ON outlets (state)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_nayara_district ON outlets (district)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_nayara_pincode ON outlets (pincode)")
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
# Session & CSRF Token Manager
# =====================================================================

class NayaraSessionManager:
    """Manages curl_cffi session, cookies, and CSRF token."""
    def __init__(self):
        self.lock = threading.Lock()
        self.session = None
        self.csrf_token = None
        self.refresh()

    def refresh(self):
        with self.lock:
            try:
                self.session = requests.Session()
                r = self.session.get(LOCATOR_PAGE_URL, impersonate="chrome124", timeout=20)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, "html.parser")
                    elem = soup.find("meta", {"name": "csrf-token"})
                    if elem and elem.get("content"):
                        self.csrf_token = elem["content"]
                        return True
            except Exception as e:
                pass
        return False

    def get_session_and_headers(self):
        with self.lock:
            if not self.csrf_token or not self.session:
                self.refresh()
            headers = {
                "X-CSRF-TOKEN": self.csrf_token,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": LOCATOR_PAGE_URL,
                "Origin": "https://www.nayaraenergy.com"
            }
            return self.session, headers

session_mgr = NayaraSessionManager()

# =====================================================================
# Address Parsing Utilities
# =====================================================================

def parse_address_components(address_str, address1_fallback=""):
    """Extracts village, taluka, district, state, and pincode from address string."""
    village = address1_fallback.strip()
    taluka = ""
    district = ""
    state = ""
    pincode = ""

    if not address_str:
        return village, taluka, district, state, pincode

    # 1. State
    m_state = re.search(r'State\s*[-:]\s*([^,]+)', address_str, re.I)
    if m_state:
        state = m_state.group(1).strip()

    # 2. District
    m_dist = re.search(r'Distt?\.?\s*[-:]\s*([^,]+)', address_str, re.I)
    if m_dist:
        district = m_dist.group(1).strip()

    # 3. Taluka
    m_tal = re.search(r'Taluka\s*[-:]\s*([^,]+)', address_str, re.I)
    if m_tal:
        taluka = m_tal.group(1).strip()

    # 4. Village
    m_vil = re.search(r'Village\s*[-:]\s*([^,]+)', address_str, re.I)
    if m_vil:
        village = m_vil.group(1).strip()

    # 5. Pincode
    m_pin = re.search(r'\b([0-9]{6})\b', address_str)
    if m_pin:
        pincode = m_pin.group(1).strip()

    return village, taluka, district, state, pincode

# =====================================================================
# Spatial Grid Mesh Generation
# =====================================================================

INDIA_BOUNDS = {
    "min_lat": 8.1,
    "max_lat": 35.5,
    "min_lon": 68.7,
    "max_lon": 97.2
}

def is_point_in_india(lat, lon):
    """Rough bounding polygon filter for Indian subcontinent."""
    if lat > 32.5 and (lon < 73.5 or lon > 79.5):
        return False
    if lat < 12.0 and (lon < 75.0 or lon > 80.5):
        return False
    if lon > 89.0 and lat < 21.5:
        return False
    if lon < 70.0 and lat > 24.5:
        return False
    if lon < 73.0 and lat < 16.0:
        return False
    return True

def generate_spatial_grid(step_deg=0.40):
    """Generates a regular coordinate mesh spanning India (~44 km spacing)."""
    grid_points = []
    lat = INDIA_BOUNDS["min_lat"]
    while lat <= INDIA_BOUNDS["max_lat"]:
        lon = INDIA_BOUNDS["min_lon"]
        while lon <= INDIA_BOUNDS["max_lon"]:
            if is_point_in_india(lat, lon):
                grid_points.append((round(lat, 4), round(lon, 4)))
            lon += step_deg
        lat += step_deg
    return grid_points

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
    return {"completed_points": [], "last_updated": None}

def save_checkpoint(completed_points):
    """Saves scraping checkpoint."""
    data = {
        "completed_points": completed_points,
        "completed_count": len(completed_points),
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# =====================================================================
# API Worker Handler
# =====================================================================

def query_radius(lat, lon, radius=50, delay=0.3, max_retries=3):
    """Queries Nayara /get-code-ro-radius API for a given coordinate."""
    if delay > 0:
        time.sleep(delay)

    payload = {
        "curr_lat": str(lat),
        "curr_long": str(lon),
        "radius": str(radius)
    }

    for attempt in range(max_retries):
        try:
            session, headers = session_mgr.get_session_and_headers()
            r = session.post(API_URL, data=payload, headers=headers, impersonate="chrome124", timeout=15)
            
            if r.status_code == 200:
                try:
                    data = r.json()
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict):
                        return data.get("data", []) or []
                except Exception:
                    return []

            elif r.status_code in (419, 403):
                # CSRF or session expired, refresh
                session_mgr.refresh()
                time.sleep(1.0)
            else:
                time.sleep(1.0)

        except Exception:
            time.sleep(1.0)

    return []

# =====================================================================
# Main Scraper Execution Engine
# =====================================================================

def run_scraper(workers=4, delay=0.3, radius=50, max_points=None, reset=False):
    """Runs nationwide Nayara Energy scraping pipeline."""
    if reset:
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
            print(f"[x] Removed existing {DB_FILE}")
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
            print(f"[x] Removed existing {CHECKPOINT_FILE}")

    init_database(DB_FILE)
    initial_count = get_db_count(DB_FILE)

    # 1. Generate spatial mesh
    all_points = generate_spatial_grid(step_deg=0.38) # ~42 km spacing
    total_points = len(all_points)

    # 2. Checkpoint filtering
    checkpoint = load_checkpoint()
    completed_set = set(tuple(p) for p in checkpoint.get("completed_points", []))

    pending_points = [p for p in all_points if tuple(p) not in completed_set]

    if max_points and max_points > 0:
        pending_points = pending_points[:max_points]

    print("=" * 70)
    print(" NAYARA ENERGY FUEL STATIONS EXTRACTOR")
    print("=" * 70)
    print(f"  * Total Mesh Points:     {total_points:,}")
    print(f"  * Already Completed:     {len(completed_set):,}")
    print(f"  * Pending in This Run:   {len(pending_points):,}")
    print(f"  * Search Radius:         {radius} km")
    print(f"  * Existing DB Outlets:   {initial_count:,}")
    print(f"  * Workers (Threads):     {workers}")
    print(f"  * Polite Delay:          {delay}s")
    print("=" * 70)

    if not pending_points:
        print("[OK] All mesh grid points have already been processed! Nothing to do.")
        return

    db_lock = threading.Lock()
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cur = conn.cursor()

    completed_points_list = list(completed_set)
    newly_added = 0
    start_time = time.time()
    last_checkpoint_time = time.time()

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_point = {
                executor.submit(query_radius, lat, lon, radius, delay): (lat, lon)
                for lat, lon in pending_points
            }

            done_count = 0
            total_tasks = len(pending_points)

            for future in as_completed(future_to_point):
                lat, lon = future_to_point[future]
                done_count += 1
                try:
                    pumps = future.result()
                    if pumps:
                        with db_lock:
                            for p in pumps:
                                cms_code = str(p.get("cms_code") or "").strip()
                                if not cms_code:
                                    continue

                                ro_name = str(p.get("ro_name") or "").strip()
                                address = str(p.get("address") or "").strip()
                                address1 = str(p.get("address1") or "").strip()
                                
                                village, taluka, district, state, pincode = parse_address_components(address, address1)
                                
                                try:
                                    latitude = float(p.get("latitude"))
                                    longitude = float(p.get("longitude"))
                                except (TypeError, ValueError):
                                    latitude, longitude = None, None

                                efp = str(p.get("efp") or "").strip()

                                try:
                                    petrol_price = float(p.get("PETROL")) if p.get("PETROL") else None
                                except (TypeError, ValueError):
                                    petrol_price = None

                                try:
                                    diesel_price = float(p.get("DIESEL")) if p.get("DIESEL") else None
                                except (TypeError, ValueError):
                                    diesel_price = None

                                created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                                cur.execute("""
                                    INSERT OR IGNORE INTO outlets (
                                        cms_code, ro_name, address, village, taluka,
                                        district, state, pincode, latitude, longitude,
                                        efp, petrol_price, diesel_price, created_at
                                    ) VALUES (
                                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                                    )
                                """, (
                                    cms_code, ro_name, address, village, taluka,
                                    district, state, pincode, latitude, longitude,
                                    efp, petrol_price, diesel_price, created_at
                                ))
                                newly_added += cur.rowcount
                            conn.commit()

                except Exception:
                    pass

                completed_points_list.append([lat, lon])

                if time.time() - last_checkpoint_time > 10 or done_count % 10 == 0:
                    save_checkpoint(completed_points_list)
                    last_checkpoint_time = time.time()

                elapsed = time.time() - start_time
                rate = done_count / max(elapsed, 0.001)
                total_in_db = initial_count + newly_added
                pct = (done_count / total_tasks) * 100
                print(
                    f"[{done_count:>4}/{total_tasks} | {pct:>5.1f}%] "
                    f"DB Total: {total_in_db:>5,} (+{newly_added:>4,}) | "
                    f"Point: ({lat:>7.4f}, {lon:>7.4f}) | "
                    f"Speed: {rate:>4.1f} pts/s",
                    flush=True
                )

        save_checkpoint(completed_points_list)

    finally:
        conn.close()

    total_time = time.time() - start_time
    final_count = get_db_count(DB_FILE)

    print("\n" + "=" * 70)
    print(" [OK] SCRAPING SESSION COMPLETE")
    print("=" * 70)
    print(f"  * Grid Points Processed: {len(pending_points):,}")
    print(f"  * Total Unique in DB:    {final_count:,} (+{newly_added:,} this run)")
    print(f"  * Time Taken:            {total_time / 60:.1f} minutes ({total_time:.1f}s)")
    print(f"  * Database File:         {DB_FILE}")
    print("=" * 70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Nayara Energy Fuel Stations across India.")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent worker threads (default: 4)")
    parser.add_argument("--delay", type=float, default=0.3, help="Polite delay between requests in seconds (default: 0.3)")
    parser.add_argument("--radius", type=int, default=50, help="Search radius in km (default: 50)")
    parser.add_argument("--max-points", type=int, default=None, help="Limit number of grid points for quick test runs")
    parser.add_argument("--reset", action="store_true", help="Reset database and checkpoint before starting")

    args = parser.parse_args()
    run_scraper(
        workers=args.workers,
        delay=args.delay,
        radius=args.radius,
        max_points=args.max_points,
        reset=args.reset
    )
