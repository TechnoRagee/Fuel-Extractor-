"""
BPCL (Bharat Petroleum Corporation Limited) Fuel Station / Retail Outlet Scraper.
Extracts nationwide petrol pumps via official REST API into SQLite database and CSV.
Features:
- OAuth 2.0 automatic token acquisition and refresh
- Nationwide spatial coordinate mesh and district seed coverage
- Multi-threaded concurrent processing with polite rate-limiting
- Thread-safe SQLite batch commits with unique ro_id deduplication
- Resumable state persistence via bpcl_checkpoint.json
"""

import sys
import os
import time
import json
import sqlite3
import argparse
import ssl
import threading
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# =====================================================================
# Configuration & Constants
# =====================================================================

DB_FILE = "bpcl_outlets.db"
CHECKPOINT_FILE = "bpcl_checkpoint.json"
CSV_FILE = "bpcl_outlets.csv"

TOKEN_URL = "https://api.cep.bpcl.in/authorizationserver/oauth/token"
RO_LOCATOR_URL = "https://api.cep.bpcl.in/retail/v2/bpcl/retail/rolocators"

CLIENT_ID = "hybrislogin"
CLIENT_SECRET = "nimda"

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Origin": "https://hellobpcl.in",
    "Referer": "https://hellobpcl.in/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# SSL context
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
            ro_id TEXT PRIMARY KEY,
            name TEXT,
            display_name TEXT,
            line1 TEXT,
            line2 TEXT,
            town TEXT,
            district TEXT,
            state TEXT,
            state_iso TEXT,
            postal_code TEXT,
            formatted_address TEXT,
            cellphone TEXT,
            email TEXT,
            latitude REAL,
            longitude REAL,
            fuels_available TEXT,
            amenities TEXT,
            created_at TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bpcl_state ON outlets (state)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bpcl_district ON outlets (district)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bpcl_pincode ON outlets (postal_code)")
    conn.commit()
    conn.close()

def get_db_count(db_path=DB_FILE):
    """Returns the total number of unique outlets currently in DB."""
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
# OAuth Token Manager
# =====================================================================

class TokenManager:
    """Thread-safe OAuth token manager with auto-refresh."""
    def __init__(self):
        self._token = None
        self._expiry = 0
        self._lock = threading.Lock()

    def get_token(self):
        with self._lock:
            now = time.time()
            # If token exists and is valid for at least another 60 seconds
            if self._token and now < (self._expiry - 60):
                return self._token

            # Request new token
            payload = {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "client_credentials"
            }
            data = urllib.parse.urlencode(payload).encode("utf-8")
            req_headers = HTTP_HEADERS.copy()
            req_headers["Content-Type"] = "application/x-www-form-urlencoded"

            req = urllib.request.Request(TOKEN_URL, data=data, headers=req_headers)
            try:
                with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    self._token = res.get("access_token")
                    expires_in = res.get("expires_in", 7200)
                    self._expiry = now + expires_in
                    return self._token
            except Exception as e:
                print(f"[TOKEN ERROR] Failed to fetch OAuth token: {e}")
                if self._token:
                    return self._token  # Fallback to existing token
                raise

token_manager = TokenManager()

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
    return {"processed_indices": [], "last_updated": None}

def save_checkpoint(processed_indices):
    """Saves scraping checkpoint."""
    data = {
        "processed_indices": processed_indices,
        "processed_count": len(processed_indices),
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# =====================================================================
# India Geo Grid Generator
# =====================================================================

# Major seed coordinates across Indian states, capitals, industrial hubs, and highways
KEY_REGIONAL_SEEDS = [
    # North
    ("Delhi NCR", 28.6139, 77.2090), ("Noida", 28.5355, 77.3910), ("Gurugram", 28.4595, 77.0266),
    ("Chandigarh", 30.7333, 76.7794), ("Amritsar", 31.6340, 74.8723), ("Ludhiana", 30.9010, 75.8573),
    ("Jammu", 32.7266, 74.8570), ("Srinagar", 34.0837, 74.7973), ("Shimla", 31.1048, 77.1734),
    ("Dehradun", 30.3165, 78.0322), ("Haridwar", 29.9457, 78.1642), ("Agra", 27.1767, 78.0081),
    ("Lucknow", 26.8467, 80.9462), ("Kanpur", 26.4499, 80.3319), ("Varanasi", 25.3176, 82.9739),
    ("Prayagraj", 25.4358, 81.8463), ("Meerut", 28.9845, 77.7064), ("Bareilly", 28.3670, 79.4304),
    ("Gorakhpur", 26.7606, 83.3732), ("Jhansi", 25.4484, 78.5685), ("Aligarh", 27.8974, 78.0880),
    # West
    ("Mumbai", 19.0760, 72.8777), ("Pune", 18.5204, 73.8567), ("Nagpur", 21.1458, 79.0882),
    ("Nashik", 19.9975, 73.7898), ("Aurangabad", 19.8762, 75.3433), ("Solapur", 17.6599, 75.9064),
    ("Kolhapur", 16.7050, 74.2433), ("Amravati", 20.9374, 77.7796), ("Nanded", 19.1383, 77.3210),
    ("Ahmedabad", 23.0225, 72.5714), ("Surat", 21.1702, 72.8311), ("Vadodara", 22.3072, 73.1812),
    ("Rajkot", 22.3039, 70.8022), ("Bhavnagar", 21.7645, 72.1519), ("Jamnagar", 22.4707, 70.0577),
    ("Gandhinagar", 23.2156, 72.6369), ("Panaji", 15.4909, 73.8278), ("Margao", 15.2832, 73.9862),
    # Central
    ("Bhopal", 23.2599, 77.4126), ("Indore", 22.7196, 75.8577), ("Gwalior", 26.2183, 78.1828),
    ("Jabalpur", 23.1815, 79.9864), ("Ujjain", 23.1765, 75.7885), ("Raipur", 21.2514, 81.6296),
    ("Bilaspur", 22.0797, 82.1409), ("Durg-Bhilai", 21.1904, 81.2849),
    # East
    ("Kolkata", 22.5726, 88.3639), ("Howrah", 22.5958, 88.2636), ("Siliguri", 26.7271, 88.3953),
    ("Asansol", 23.6739, 86.9524), ("Durgapur", 23.5204, 87.3119), ("Patna", 25.5941, 85.1376),
    ("Gaya", 24.7914, 85.0002), ("Muzaffarpur", 26.1209, 85.3647), ("Bhagalpur", 25.2425, 86.9842),
    ("Ranchi", 23.3441, 85.3096), ("Jamshedpur", 22.8046, 86.2029), ("Dhanbad", 23.7957, 86.4304),
    ("Bhubaneswar", 20.2961, 85.8245), ("Cuttack", 20.4625, 85.8828), ("Rourkela", 22.2604, 84.8536),
    ("Puri", 19.8135, 85.8312),
    # South
    ("Bengaluru", 12.9716, 77.5946), ("Mysuru", 12.2958, 76.6394), ("Hubballi", 15.3647, 75.1240),
    ("Mangaluru", 12.9141, 74.8560), ("Belagavi", 15.8497, 74.4977), ("Kalaburagi", 17.3297, 76.8343),
    ("Chennai", 13.0827, 80.2707), ("Coimbatore", 11.0168, 76.9558), ("Madurai", 9.9252, 78.1198),
    ("Tiruchirappalli", 10.7905, 78.7047), ("Salem", 11.6643, 78.1460), ("Tirunelveli", 8.7139, 77.7567),
    ("Hyderabad", 17.3850, 78.4867), ("Warangal", 17.9689, 79.5941), ("Nizamabad", 18.6725, 78.0941),
    ("Khammam", 17.2473, 80.1514), ("Vijayawada", 16.5062, 80.6480), ("Visakhapatnam", 17.6868, 83.2185),
    ("Guntur", 16.3067, 80.4365), ("Nellore", 14.4426, 79.9865), ("Kurnool", 15.8281, 78.0373),
    ("Tirupati", 13.6288, 79.4192), ("Thiruvananthapuram", 8.5241, 76.9366), ("Kochi", 9.9312, 76.2673),
    ("Kozhikode", 11.2588, 75.7804), ("Thrissur", 10.5276, 76.2144), ("Kannur", 11.8745, 75.3704),
    # North-East
    ("Guwahati", 26.1445, 91.7362), ("Silchar", 24.8170, 92.7985), ("Dibrugarh", 27.4728, 94.9120),
    ("Jorhat", 26.7509, 94.2037), ("Shillong", 25.5788, 91.8933), ("Imphal", 24.8170, 93.9368),
    ("Aizawl", 23.7271, 92.7176), ("Agartala", 23.8315, 91.2868), ("Kohima", 25.6751, 94.1086),
    ("Dimapur", 25.9096, 93.7266), ("Itanagar", 27.0844, 93.6053), ("Gangtok", 27.3389, 88.6065),
    # Rajasthan & West
    ("Jaipur", 26.9124, 75.7873), ("Jodhpur", 26.2389, 73.0243), ("Udaipur", 24.5854, 73.7125),
    ("Kota", 25.2138, 75.8648), ("Bikaner", 28.0229, 73.3119), ("Ajmer", 26.4499, 74.6399),
    ("Alwar", 27.5530, 76.6346), ("Bhilwara", 25.3216, 74.6409), ("Sriganganagar", 29.9038, 73.8772),
]

def generate_spatial_grid(step=0.30):
    """
    Generates a full spatial coordinate mesh covering India with 0.30 deg (~33km) spacing.
    Includes regional seed centers and filters to India landmass boundaries.
    """
    points = []
    seen = set()

    # 1. Add regional seed centers first
    for name, lat, lon in KEY_REGIONAL_SEEDS:
        key = (round(lat, 3), round(lon, 3))
        if key not in seen:
            seen.add(key)
            points.append((lat, lon, name))

    # 2. Add grid points across India bounding box (8.0°N to 35.5°N, 68.5°E to 97.0°E)
    lat = 8.2
    while lat <= 35.5:
        lon = 68.8
        while lon <= 96.5:
            # Approximate filter for India land boundary polygon
            is_valid = False
            # South India
            if 8.2 <= lat < 16.0 and 74.5 <= lon <= 80.5:
                is_valid = True
            # Peninsular & Central
            elif 16.0 <= lat < 22.0 and 72.5 <= lon <= 87.5:
                is_valid = True
            # West / North / East India
            elif 22.0 <= lat < 29.5 and 68.8 <= lon <= 90.0:
                is_valid = True
            # North-East India
            elif 22.0 <= lat < 29.5 and 89.5 <= lon <= 96.5:
                is_valid = True
            # Far North (Punjab, Haryana, HP, UK, J&K)
            elif 29.5 <= lat <= 35.5 and 73.5 <= lon <= 81.0:
                is_valid = True

            if is_valid:
                key = (round(lat, 3), round(lon, 3))
                if key not in seen:
                    seen.add(key)
                    points.append((lat, lon, f"Grid_{lat:.2f}_{lon:.2f}"))
            lon += step
        lat += step

    return points

# =====================================================================
# API Request & Extraction Handler
# =====================================================================

def parse_outlet_record(pos):
    """Extracts clean dictionary of fields from a raw BPCL API outlet item."""
    ro_id = str(pos.get("roId") or pos.get("name") or "").strip()
    if not ro_id:
        return None

    name = pos.get("name") or ""
    display_name = pos.get("displayName") or name

    addr = pos.get("address") or {}
    line1 = addr.get("line1") or ""
    line2 = addr.get("line2") or ""
    town = addr.get("town") or ""
    district = addr.get("district") or ""
    postal_code = addr.get("postalCode") or ""
    formatted_address = addr.get("formattedAddress") or ""
    cellphone = addr.get("cellphone") or pos.get("telephone") or ""
    email = addr.get("email") or pos.get("email") or ""

    region = addr.get("region") or {}
    state = region.get("name") or ""
    state_iso = region.get("isocode") or ""

    geo = pos.get("geoPoint") or {}
    latitude = geo.get("latitude")
    longitude = geo.get("longitude")

    # Fuels
    fuels = pos.get("fuelAvailable")
    fuels_str = ""
    if isinstance(fuels, list):
        fuels_str = ", ".join(str(f) for f in fuels if f)
    elif isinstance(fuels, str):
        fuels_str = fuels

    # Amenities
    amenities = pos.get("amenities") or pos.get("features")
    amenities_str = ""
    if isinstance(amenities, list):
        amenities_str = ", ".join(str(a) for a in amenities if a)
    elif isinstance(amenities, dict):
        amenities_str = ", ".join(k for k, v in amenities.items() if v)
    elif isinstance(amenities, str):
        amenities_str = amenities

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "ro_id": ro_id,
        "name": name,
        "display_name": display_name,
        "line1": line1,
        "line2": line2,
        "town": town,
        "district": district,
        "state": state,
        "state_iso": state_iso,
        "postal_code": postal_code,
        "formatted_address": formatted_address,
        "cellphone": cellphone,
        "email": email,
        "latitude": latitude,
        "longitude": longitude,
        "fuels_available": fuels_str,
        "amenities": amenities_str,
        "created_at": created_at
    }

# Thread safety and error monitoring
consecutive_errors = 0
error_lock = threading.Lock()

def fetch_outlets_at_coord(lat, lon, radius=50000, delay=0.5, max_retries=4):
    """
    Queries BPCL REST API for retail outlets within radius meters of (lat, lon).
    Implements polite rate-limiting, exponential backoff, and auto-cooldown.
    """
    global consecutive_errors

    if delay > 0:
        time.sleep(delay)

    url = f"{RO_LOCATOR_URL}?latitude={lat}&longitude={lon}&radius={radius}"

    for attempt in range(max_retries):
        try:
            token = token_manager.get_token()
            headers = HTTP_HEADERS.copy()
            headers["Authorization"] = f"Bearer {token}"

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                pos_list = data.get("pointOfServices", [])
                outlets = []
                for item in pos_list:
                    parsed = parse_outlet_record(item)
                    if parsed:
                        outlets.append(parsed)

                # Reset error counter on success
                with error_lock:
                    consecutive_errors = 0

                return outlets

        except urllib.error.HTTPError as e:
            if e.code == 404:
                # 404 with NoDataFound means no stations in this radius
                with error_lock:
                    consecutive_errors = 0
                return []
            elif e.code in (401, 403):
                # Token expired / refresh needed
                token_manager._token = None
                time.sleep(1.5 * (attempt + 1))
            elif e.code == 429:
                # Rate limited -> backoff
                with error_lock:
                    consecutive_errors += 1
                    if consecutive_errors >= 3:
                        print(f"\n[!] Rate-limit detected. Cooling down for 20 seconds...")
                        time.sleep(20)
                        consecutive_errors = 0
                time.sleep(4.0 * (attempt + 1))
            else:
                time.sleep(2.0 * (attempt + 1))

        except Exception as e:
            time.sleep(2.0 * (attempt + 1))

    return []

# =====================================================================
# Main Scraper Execution Engine
# =====================================================================

def run_scraper(workers=6, delay=0.2, radius=40000, max_points=None, reset=False):
    """Runs nationwide BPCL scraping pipeline."""
    if reset:
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
            print(f"[x] Removed existing {DB_FILE}")
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
            print(f"[x] Removed existing {CHECKPOINT_FILE}")

    init_database(DB_FILE)
    initial_count = get_db_count(DB_FILE)

    # 1. Generate grid
    all_points = generate_spatial_grid()
    total_grid_points = len(all_points)

    # 2. Checkpoint filtering
    checkpoint = load_checkpoint()
    processed_set = set(checkpoint.get("processed_indices", []))

    pending_tasks = []
    for idx, (lat, lon, label) in enumerate(all_points):
        if idx not in processed_set:
            pending_tasks.append((idx, lat, lon, label))

    if max_points and max_points > 0:
        pending_tasks = pending_tasks[:max_points]

    print("=" * 70)
    print(" BHARAT PETROLEUM (BPCL) FUEL STATIONS EXTRACTOR")
    print("=" * 70)
    print(f"  * Total Grid Points:     {total_grid_points:,}")
    print(f"  * Already Processed:     {len(processed_set):,}")
    print(f"  * Pending in This Run:   {len(pending_tasks):,}")
    print(f"  * Existing DB Outlets:   {initial_count:,}")
    print(f"  * Workers (Threads):     {workers}")
    print(f"  * Search Radius:         {radius // 1000} km ({radius:,} m)")
    print(f"  * Polite Delay:          {delay}s")
    print("=" * 70)

    if not pending_tasks:
        print("[OK] All grid points have already been processed! Nothing to do.")
        return

    db_lock = threading.Lock()
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cur = conn.cursor()

    processed_indices_list = list(processed_set)
    newly_added = 0
    start_time = time.time()
    last_checkpoint_time = time.time()
    batch_buffer = []

    def save_batch():
        nonlocal newly_added
        if not batch_buffer:
            return
        with db_lock:
            cur.executemany("""
                INSERT OR IGNORE INTO outlets (
                    ro_id, name, display_name, line1, line2, town, district,
                    state, state_iso, postal_code, formatted_address, cellphone,
                    email, latitude, longitude, fuels_available, amenities, created_at
                ) VALUES (
                    :ro_id, :name, :display_name, :line1, :line2, :town, :district,
                    :state, :state_iso, :postal_code, :formatted_address, :cellphone,
                    :email, :latitude, :longitude, :fuels_available, :amenities, :created_at
                )
            """, batch_buffer)
            newly_added += cur.rowcount
            conn.commit()
            batch_buffer.clear()

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_info = {
                executor.submit(fetch_outlets_at_coord, lat, lon, radius, delay): (idx, label, lat, lon)
                for (idx, lat, lon, label) in pending_tasks
            }

            done_count = 0
            total_tasks = len(pending_tasks)

            for future in as_completed(future_to_info):
                idx, label, lat, lon = future_to_info[future]
                done_count += 1
                found_count = 0
                try:
                    outlets = future.result()
                    if outlets:
                        found_count = len(outlets)
                        with db_lock:
                            cur.executemany("""
                                INSERT OR IGNORE INTO outlets (
                                    ro_id, name, display_name, line1, line2, town, district,
                                    state, state_iso, postal_code, formatted_address, cellphone,
                                    email, latitude, longitude, fuels_available, amenities, created_at
                                ) VALUES (
                                    :ro_id, :name, :display_name, :line1, :line2, :town, :district,
                                    :state, :state_iso, :postal_code, :formatted_address, :cellphone,
                                    :email, :latitude, :longitude, :fuels_available, :amenities, :created_at
                                )
                            """, outlets)
                            newly_added += cur.rowcount
                            conn.commit()
                except Exception as e:
                    pass

                processed_indices_list.append(idx)

                # Periodic checkpoint save every 5 points or 10 seconds
                if time.time() - last_checkpoint_time > 10 or done_count % 5 == 0:
                    save_checkpoint(processed_indices_list)
                    last_checkpoint_time = time.time()

                # Live progress line
                elapsed = time.time() - start_time
                rate = done_count / max(elapsed, 0.001)
                total_in_db = initial_count + newly_added
                pct = (done_count / total_tasks) * 100
                print(
                    f"[{done_count:>3}/{total_tasks} | {pct:>5.1f}%] "
                    f"Point: {label[:18]:<18} | "
                    f"Found: {found_count:>3} | "
                    f"DB Total: {total_in_db:>5,} (+{newly_added:>4,}) | "
                    f"Speed: {rate:>4.1f} pts/s",
                    flush=True
                )

        # Final commit and checkpoint
        save_checkpoint(processed_indices_list)

    finally:
        conn.close()

    total_time = time.time() - start_time
    final_count = get_db_count(DB_FILE)

    print("\n" + "=" * 70)
    print(" [OK] SCRAPING SESSION COMPLETE")
    print("=" * 70)
    print(f"  * Points Processed:      {len(pending_tasks):,}")
    print(f"  * Total Unique in DB:    {final_count:,} (+{newly_added:,} this run)")
    print(f"  * Time Taken:            {total_time / 60:.1f} minutes ({total_time:.1f}s)")
    print(f"  * Database File:         {DB_FILE}")
    print("=" * 70)

# =====================================================================
# CLI Arguments
# =====================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Bharat Petroleum (BPCL) Fuel Stations across India.")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent worker threads (default: 4)")
    parser.add_argument("--delay", type=float, default=0.5, help="Polite delay between queries in seconds (default: 0.5)")
    parser.add_argument("--radius", type=int, default=50000, help="Search radius per query in meters (default: 50000 = 50km)")
    parser.add_argument("--max-points", type=int, default=None, help="Limit number of grid points to process (optional)")
    parser.add_argument("--reset", action="store_true", help="Reset database and checkpoint before starting")

    args = parser.parse_args()
    run_scraper(
        workers=args.workers,
        delay=args.delay,
        radius=args.radius,
        max_points=args.max_points,
        reset=args.reset
    )
