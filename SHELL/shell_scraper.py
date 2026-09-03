"""
Shell India Fuel Stations Scraper.
Extracts all nationwide Shell retail fuel stations from official GeoApp / HighTide API.
Features:
- Queries official Shell REST API (shellretaillocator.geoapp.me/api/v2/locations/nearest_to)
- Automated Chrome TLS impersonation using curl_cffi
- Covers all operational Shell retail clusters across India
- Extracts Station Name, Address, City, State, Postcode, Phone, GPS (Lat/Lon), and Amenities
- Thread-safe SQLite batch commits with unique station_id deduplication
- Resumable state persistence via shell_checkpoint.json
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
from curl_cffi import requests

# =====================================================================
# Configuration & Constants
# =====================================================================

DB_FILE = "shell_outlets.db"
CHECKPOINT_FILE = "shell_checkpoint.json"
BASE_API = "https://shellretaillocator.geoapp.me/api/v2/locations/nearest_to"

# Regional search centers across all states/cities in India where Shell operates
SHELL_REGIONAL_CLUSTERS = [
    # Karnataka (Largest Shell network - Bangalore, Mysore, Hubli, etc.)
    (12.9716, 77.5946, "Bangalore Central"),
    (13.0827, 77.5877, "Bangalore North"),
    (12.8984, 77.6253, "Bangalore South"),
    (13.0033, 77.7289, "Whitefield"),
    (12.2958, 76.6394, "Mysore"),
    (15.3647, 75.1240, "Hubli-Dharwad"),
    (12.9141, 74.8560, "Mangalore"),
    (13.3409, 74.7421, "Udupi"),
    (13.9299, 75.5681, "Shimoga"),
    (14.4644, 75.9218, "Davanagere"),
    (15.8497, 74.4977, "Belgaum"),
    (13.3422, 77.1017, "Tumkur"),
    (12.5218, 76.8951, "Mandya"),
    (13.0068, 76.0996, "Hassan"),
    (12.4244, 75.7382, "Madikeri"),

    # Tamil Nadu (Chennai, Coimbatore, Salem, Trichy, etc.)
    (13.0827, 80.2707, "Chennai Central"),
    (12.9249, 80.1000, "Tambaram / OMR"),
    (13.1250, 80.1500, "Ambattur / Avadi"),
    (11.0168, 76.9558, "Coimbatore"),
    (11.6643, 78.1460, "Salem"),
    (10.7905, 78.7047, "Tiruchirappalli"),
    (9.9252, 78.1198, "Madurai"),
    (8.7139, 77.7567, "Tirunelveli"),
    (12.9165, 79.1325, "Vellore"),
    (11.3410, 77.7172, "Erode"),
    (11.9416, 79.8083, "Pondicherry"),

    # Telangana & Andhra Pradesh
    (17.3850, 78.4867, "Hyderabad Central"),
    (17.4401, 78.3489, "Gachibowli / Hitec City"),
    (17.5000, 78.5500, "Secunderabad"),
    (16.5062, 80.6480, "Vijayawada"),
    (16.3067, 80.4365, "Guntur"),
    (17.6868, 83.2185, "Visakhapatnam"),
    (14.4426, 79.9865, "Nellore"),
    (13.6288, 79.4192, "Tirupati"),
    (14.6819, 77.6006, "Anantapur"),
    (15.8281, 78.0373, "Kurnool"),
    (18.0000, 79.5882, "Warangal"),

    # Maharashtra
    (19.0760, 72.8777, "Mumbai"),
    (19.0330, 73.0297, "Navi Mumbai"),
    (19.2183, 72.9781, "Thane"),
    (18.5204, 73.8567, "Pune Central"),
    (18.6279, 73.8009, "Pimpri-Chinchwad"),
    (19.9975, 73.7898, "Nashik"),
    (19.8762, 75.3433, "Aurangabad"),
    (16.7050, 74.2433, "Kolhapur"),
    (17.6805, 74.0183, "Satara"),
    (16.8524, 74.5815, "Sangli"),

    # Gujarat
    (23.0225, 72.5714, "Ahmedabad Central"),
    (23.0707, 72.5178, "SG Highway Ahmedabad"),
    (21.1702, 72.8311, "Surat"),
    (22.3072, 73.1812, "Vadodara"),
    (22.3039, 70.8022, "Rajkot"),
    (21.7645, 72.1519, "Bhavnagar"),
    (22.4707, 70.0577, "Jamnagar"),
    (20.3893, 72.9106, "Vapi"),
    (20.5992, 72.9342, "Valsad"),
    (21.7051, 72.9959, "Bharuch"),
    (22.5645, 72.9289, "Anand"),
    (23.8500, 72.1200, "Patan / Mehsana"),

    # Assam & North East
    (26.1445, 91.7362, "Guwahati"),
    (26.1856, 91.7777, "Dispur / Khanapara"),
    (26.7509, 94.2037, "Jorhat"),
    (27.4728, 94.9120, "Dibrugarh"),
    (25.5788, 91.8933, "Shillong"),

    # Delhi NCR & North
    (28.6139, 77.2090, "Delhi"),
    (28.4595, 77.0266, "Gurugram"),
    (28.5355, 77.3910, "Noida")
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
            name TEXT,
            brand TEXT,
            street_address TEXT,
            city TEXT,
            state TEXT,
            postcode TEXT,
            telephone TEXT,
            latitude REAL,
            longitude REAL,
            amenities TEXT,
            page_url TEXT,
            created_at TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_shell_state ON outlets (state)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_shell_city ON outlets (city)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_shell_postcode ON outlets (postcode)")
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
# State Name Cleaner
# =====================================================================

def clean_state_name(state_raw):
    """Cleans numeric state codes (e.g. '37 Andhra Pradesh' -> 'Andhra Pradesh')."""
    if not state_raw:
        return ""
    state_clean = re.sub(r'^[0-9]+\s+', '', state_raw).strip()
    if state_clean.lower() == "megalaya":
        state_clean = "Meghalaya"
    elif state_clean.lower() == "navi mumbai":
        state_clean = "Maharashtra"
    return state_clean

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
    return {"completed_clusters": [], "last_updated": None}

def save_checkpoint(completed_clusters):
    """Saves scraping checkpoint."""
    data = {
        "completed_clusters": completed_clusters,
        "completed_count": len(completed_clusters),
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# =====================================================================
# API Request Handler
# =====================================================================

def fetch_cluster_stations(lat, lng, label, delay=0.2, max_retries=3):
    """Queries Shell API for nearest 50 stations around given coordinates."""
    if delay > 0:
        time.sleep(delay)

    url = f"{BASE_API}?lat={lat}&lng={lng}&limit=50&locale=en_IN&format=json&driving_distances=false"

    for attempt in range(max_retries):
        try:
            r = requests.get(url, impersonate="chrome124", timeout=12)
            if r.status_code == 200:
                data = r.json()
                return data.get("locations", [])
            elif r.status_code in (429, 503):
                time.sleep(2.0 * (attempt + 1))
            else:
                time.sleep(1.0)
        except Exception:
            time.sleep(1.0)

    return []

# =====================================================================
# Main Scraper Execution Engine
# =====================================================================

def run_scraper(workers=4, delay=0.2, reset=False):
    """Runs nationwide Shell India scraping pipeline."""
    if reset:
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
            print(f"[x] Removed existing {DB_FILE}")
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
            print(f"[x] Removed existing {CHECKPOINT_FILE}")

    init_database(DB_FILE)
    initial_count = get_db_count(DB_FILE)

    total_clusters = len(SHELL_REGIONAL_CLUSTERS)

    # Checkpoint filtering
    checkpoint = load_checkpoint()
    completed_set = set(checkpoint.get("completed_clusters", []))

    pending_clusters = [c for c in SHELL_REGIONAL_CLUSTERS if c[2] not in completed_set]

    print("=" * 70)
    print(" SHELL INDIA FUEL STATIONS EXTRACTOR")
    print("=" * 70)
    print(f"  * Total Regional Clusters: {total_clusters}")
    print(f"  * Already Processed:        {len(completed_set)}")
    print(f"  * Pending in This Run:      {len(pending_clusters)}")
    print(f"  * Existing DB Outlets:      {initial_count:,}")
    print(f"  * Workers (Threads):        {workers}")
    print(f"  * Polite Delay:             {delay}s")
    print("=" * 70)

    if not pending_clusters:
        print("[OK] All Shell regional clusters have already been processed! Nothing to do.")
        return

    db_lock = threading.Lock()
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cur = conn.cursor()

    completed_clusters_list = list(completed_set)
    newly_added = 0
    start_time = time.time()
    last_checkpoint_time = time.time()

    try:
        for idx, (lat, lng, label) in enumerate(pending_clusters, 1):
            stations = fetch_cluster_stations(lat, lng, label, delay=delay)
            
            cluster_added = 0
            if stations:
                with db_lock:
                    for s in stations:
                        if s.get("country_code") != "IN":
                            continue

                        station_id = str(s.get("id") or "").strip()
                        if not station_id:
                            continue

                        name = str(s.get("name") or "").strip()
                        brand = str(s.get("brand") or "Shell").strip()
                        street_address = str(s.get("address") or "").strip()
                        city = str(s.get("city") or "").strip()
                        state = clean_state_name(s.get("state") or "")
                        postcode = str(s.get("postcode") or "").strip()
                        telephone = str(s.get("telephone") or "").strip()
                        
                        try:
                            latitude = float(s.get("lat"))
                            longitude = float(s.get("lng"))
                        except (TypeError, ValueError):
                            latitude, longitude = None, None

                        amenities_list = s.get("amenities") or []
                        amenities_str = ", ".join(amenities_list) if isinstance(amenities_list, list) else str(amenities_list)

                        slug = re.sub(r'[^a-zA-Z0-9]+', '-', name.lower()).strip('-')
                        page_url = f"https://find.shell.com/in/fuel/{station_id}-{slug}/en_IN"
                        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                        cur.execute("""
                            INSERT OR IGNORE INTO outlets (
                                station_id, name, brand, street_address, city, state,
                                postcode, telephone, latitude, longitude, amenities, page_url, created_at
                            ) VALUES (
                                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                            )
                        """, (
                            station_id, name, brand, street_address, city, state,
                            postcode, telephone, latitude, longitude, amenities_str, page_url, created_at
                        ))
                        cluster_added += cur.rowcount
                        newly_added += cur.rowcount

                    conn.commit()

            completed_clusters_list.append(label)

            if time.time() - last_checkpoint_time > 10 or idx % 5 == 0:
                save_checkpoint(completed_clusters_list)
                last_checkpoint_time = time.time()

            elapsed = time.time() - start_time
            rate = idx / max(elapsed, 0.001)
            total_in_db = initial_count + newly_added
            pct = (idx / len(pending_clusters)) * 100

            print(
                f"[{idx:>2}/{len(pending_clusters)} | {pct:>5.1f}%] "
                f"Cluster: {label:<24} | "
                f"DB Total: {total_in_db:>4,} (+{newly_added:>3,}) | "
                f"Speed: {rate:>3.1f} req/s",
                flush=True
            )

        save_checkpoint(completed_clusters_list)

    finally:
        conn.close()

    total_time = time.time() - start_time
    final_count = get_db_count(DB_FILE)

    print("\n" + "=" * 70)
    print(" [OK] SCRAPING SESSION COMPLETE")
    print("=" * 70)
    print(f"  * Clusters Processed:    {len(pending_clusters):,}")
    print(f"  * Total Unique in DB:    {final_count:,} (+{newly_added:,} this run)")
    print(f"  * Time Taken:            {total_time / 60:.1f} minutes ({total_time:.1f}s)")
    print(f"  * Database File:         {DB_FILE}")
    print("=" * 70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Shell Fuel Stations across India.")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent worker threads (default: 4)")
    parser.add_argument("--delay", type=float, default=0.2, help="Polite delay between requests in seconds (default: 0.2)")
    parser.add_argument("--reset", action="store_true", help="Reset database and checkpoint before starting")

    args = parser.parse_args()
    run_scraper(
        workers=args.workers,
        delay=args.delay,
        reset=args.reset
    )
