"""
================================================================================
Indian Oil Corporation Limited (IOCL) Official Locator Scraper
Target: https://locator.iocl.com/ (Retail Petrol Pumps & Indane LPG Agencies)
================================================================================
Features:
- Discovers all sub-sitemaps dynamically from XML sitemap indexes (39,555+ fuel stations)
- Local URL caching (discovered_urls.json) for instant sub-second startups on restarts
- Multithreaded concurrent fetching with rate limiting & exponential backoff
- Resilient SSL context and HTTP session handling
- Parses full JSON-LD schema (BreadcrumbList, GasStation, Store, LocalBusiness)
- Extracts exact State, City, Locality, Coordinates, Full Address, Phone, Email, Amenities, Hours, Ratings
- Supports resume/checkpointing (skips already scraped IDs in SQLite / CSV)
- Real-time progress tracking with throughput estimation
================================================================================
"""

import os
import re
import json
import gzip
import io
import time
import csv
import ssl
import sqlite3
import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
import xml.etree.ElementTree as ET

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'

# SSL Context bypass for legacy or non-standard root certs
SSL_CTX = ssl._create_unverified_context()

SITEMAP_INDEXES = {
    'Retail_Fuel': 'https://locator.iocl.com/sitemap.xml',
}

CACHE_FILE = 'discovered_urls.json'

FIELDS = [
    "outlet_id",
    "category",
    "outlet_name",
    "dealer_name",
    "outlet_type",
    "state",
    "city",
    "locality",
    "street_address",
    "pincode",
    "country",
    "latitude",
    "longitude",
    "telephone",
    "email",
    "contact_person",
    "opening_hours",
    "payment_modes",
    "amenities",
    "rating_value",
    "rating_count",
    "page_url",
    "map_url"
]

HTTP_HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'same-origin',
    'Referer': 'https://locator.iocl.com/'
}

consecutive_403_count = 0

def fetch_url(url, timeout=15, retries=3, delay_between=0.0):
    global consecutive_403_count
    if delay_between > 0:
        time.sleep(delay_between)

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HTTP_HEADERS)
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as response:
                consecutive_403_count = 0
                return response.read()
        except urllib.error.HTTPError as he:
            if he.code in (403, 429):
                consecutive_403_count += 1
                if consecutive_403_count >= 5:
                    logging.warning(f"[RATE LIMITED] Received {he.code} Forbidden/RateLimited from server. Auto-cooling down for 30s...")
                    time.sleep(30)
                    consecutive_403_count = 0
                else:
                    time.sleep(2 * (attempt + 1))
            else:
                time.sleep(1 * (attempt + 1))
        except Exception as e:
            if attempt == retries - 1:
                logging.debug(f"Failed to fetch {url}: {e}")
                return None
            time.sleep(1 * (attempt + 1))
    return None

def extract_sitemap_urls(sitemap_index_url, category_name, max_workers=10):
    logging.info(f"[{category_name}] Fetching sitemap index: {sitemap_index_url}")
    raw_index = fetch_url(sitemap_index_url, timeout=20, retries=5)
    if not raw_index:
        logging.error(f"Could not load sitemap index {sitemap_index_url}")
        return []
    
    try:
        root = ET.fromstring(raw_index)
    except Exception as e:
        logging.error(f"XML parse error on sitemap index: {e}")
        return []

    sub_sitemaps = [
        elem.text for elem in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
        if elem.text and elem.text.endswith('.gz')
    ]
    logging.info(f"[{category_name}] Found {len(sub_sitemaps)} compressed sub-sitemaps. Downloading in parallel...")

    outlet_urls = []
    
    def process_sub_sitemap(sub_url):
        urls = []
        raw_sub = fetch_url(sub_url, timeout=15)
        if raw_sub:
            try:
                decomp = gzip.GzipFile(fileobj=io.BytesIO(raw_sub)).read()
                sub_root = ET.fromstring(decomp)
                for elem in sub_root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc'):
                    if elem.text and elem.text.endswith('/Home'):
                        urls.append(elem.text)
            except Exception as e:
                logging.debug(f"Error parsing gz sitemap {sub_url}: {e}")
        return urls

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_sub_sitemap, sm): sm for sm in sub_sitemaps}
        for future in as_completed(futures):
            urls = future.result()
            outlet_urls.extend(urls)

    unique_urls = list(dict.fromkeys(outlet_urls))
    logging.info(f"[{category_name}] Discovered {len(unique_urls)} unique outlet Home URLs.")
    return unique_urls

def get_all_target_urls(refresh_cache=False, max_workers=25):
    """Loads URLs from local cache or fetches from sitemaps."""
    if not refresh_cache and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                total = sum(len(v) for v in data.values())
                logging.info(f"Loaded {total} target URLs from local cache '{CACHE_FILE}'.")
                return data
        except Exception as e:
            logging.warning(f"Failed to read cache file: {e}. Re-fetching...")

    all_urls = {}
    for cat, sitemap_url in SITEMAP_INDEXES.items():
        urls = extract_sitemap_urls(sitemap_url, cat, max_workers=max_workers)
        all_urls[cat] = urls

    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_urls, f, indent=2)
        logging.info(f"Cached {sum(len(v) for v in all_urls.values())} URLs to '{CACHE_FILE}'.")
    except Exception as e:
        logging.warning(f"Could not write cache file: {e}")

    return all_urls

def parse_outlet_html(url, category, raw_html):
    try:
        html = raw_html.decode('utf-8', errors='ignore')
    except Exception:
        return None

    outlet_id_match = re.search(r'-(\d+)/Home', url)
    outlet_id = outlet_id_match.group(1) if outlet_id_match else ""

    record = {k: "" for k in FIELDS}
    record["outlet_id"] = outlet_id
    record["category"] = category
    record["page_url"] = url
    record["country"] = "India"

    schemas = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL)
    for s in schemas:
        try:
            data = json.loads(s.strip())
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                
                itype = item.get('@type', '')

                # Breadcrumbs for Hierarchy (State, City, Locality)
                if itype == 'BreadcrumbList':
                    elements = item.get('itemListElement', [])
                    if isinstance(elements, list):
                        sorted_elems = sorted(elements, key=lambda x: x.get('position', 0))
                        for elem in sorted_elems:
                            pos = elem.get('position')
                            name = elem.get('item', {}).get('name', '')
                            if pos == 2:
                                record['state'] = name
                            elif pos == 3:
                                record['city'] = name
                            elif pos == 4:
                                record['locality'] = name

                # Business / GasStation / Store Details
                if itype in ['GasStation', 'Store', 'LocalBusiness', 'AutoRepair', 'AutomotiveBusiness']:
                    record['outlet_type'] = itype
                    if item.get('name'):
                        record['outlet_name'] = item.get('name')
                    if item.get('alternateName'):
                        record['dealer_name'] = item.get('alternateName')
                    if item.get('hasMap'):
                        record['map_url'] = item.get('hasMap')

                    # Telephone
                    tels = item.get('telephone', '')
                    if isinstance(tels, list):
                        record['telephone'] = ", ".join(filter(None, tels))
                    elif isinstance(tels, str):
                        record['telephone'] = tels

                    # Contact Point
                    cp = item.get('contactPoint', {})
                    if isinstance(cp, dict):
                        if cp.get('name'):
                            record['contact_person'] = cp.get('name')
                        if cp.get('email') and not record['email']:
                            record['email'] = cp.get('email')

                    # Geo coordinates
                    geo = item.get('geo', {})
                    if isinstance(geo, dict):
                        if geo.get('latitude'):
                            record['latitude'] = str(geo.get('latitude'))
                        if geo.get('longitude'):
                            record['longitude'] = str(geo.get('longitude'))

                    # Address
                    addr = item.get('address', {})
                    if isinstance(addr, list) and len(addr) > 0:
                        addr = addr[0]
                    if isinstance(addr, dict):
                        if addr.get('streetAddress'):
                            record['street_address'] = addr.get('streetAddress')
                        if addr.get('addressLocality') and not record['locality']:
                            record['locality'] = addr.get('addressLocality')
                        if addr.get('addressRegion') and not record['city']:
                            record['city'] = addr.get('addressRegion')
                        if addr.get('postalCode'):
                            record['pincode'] = str(addr.get('postalCode'))
                        if addr.get('email'):
                            record['email'] = addr.get('email')

                    # Payment
                    if item.get('paymentAccepted'):
                        record['payment_modes'] = item.get('paymentAccepted')

                    # Rating
                    rating = item.get('aggregateRating', {})
                    if isinstance(rating, dict):
                        if rating.get('ratingValue') is not None:
                            record['rating_value'] = str(rating.get('ratingValue'))
                        if rating.get('ratingCount') is not None:
                            record['rating_count'] = str(rating.get('ratingCount'))

                    # Amenities
                    amenities = item.get('amenityFeature', [])
                    if isinstance(amenities, list):
                        amenity_list = []
                        for am in amenities:
                            val = am.get('value', [])
                            if isinstance(val, list):
                                amenity_list.extend([str(v) for v in val if v])
                            elif isinstance(val, str) and val:
                                amenity_list.append(val)
                        if amenity_list:
                            record['amenities'] = "; ".join(amenity_list)
                            
                    # Hours
                    hours = item.get('openingHoursSpecification', [])
                    if isinstance(hours, list) and hours:
                        h_strs = [f"{h.get('dayOfWeek', '')}: {h.get('opens', '')}-{h.get('closes', '')}" for h in hours if isinstance(h, dict)]
                        record['opening_hours'] = "; ".join(h_strs)
        except Exception:
            continue

    # Fallback Geo Coordinates from meta
    if not record['latitude']:
        geo_meta = re.search(r'<meta[^>]*name=["\']geo\.position["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
        if geo_meta:
            coords = geo_meta.group(1).split(';')
            if len(coords) == 2:
                record['latitude'] = coords[0].strip()
                record['longitude'] = coords[1].strip()

    return record

def init_db(db_path='iocl_outlets.db'):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cols_sql = ", ".join([f"{f} TEXT" for f in FIELDS if f != "outlet_id"])
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS outlets (
            outlet_id TEXT PRIMARY KEY,
            {cols_sql}
        )
    """)
    conn.commit()
    return conn

def get_existing_ids(db_path='iocl_outlets.db'):
    if not os.path.exists(db_path):
        return set()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT outlet_id FROM outlets")
    rows = cur.fetchall()
    conn.close()
    return set(r[0] for r in rows)

CHECKPOINT_FILE = 'checkpoint.json'

def save_checkpoint(completed, total, last_id=None):
    checkpoint = {
        "completed": completed,
        "total": total,
        "last_outlet_id": last_id,
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    try:
        with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
            json.dump(checkpoint, f, indent=2)
    except Exception:
        pass

def run_scraper(categories=None, max_workers=8, delay=0.2, output_csv='iocl_outlets.csv', db_path='iocl_outlets.db', limit=None, refresh_cache=False):
    if categories is None:
        categories = ['Retail_Fuel']

    conn = init_db(db_path)
    existing_ids = get_existing_ids(db_path)
    logging.info(f"Loaded {len(existing_ids)} previously scraped records from SQLite database.")

    url_map = get_all_target_urls(refresh_cache=refresh_cache, max_workers=max_workers)

    all_tasks = []
    for cat in categories:
        urls = url_map.get(cat, [])
        for u in urls:
            m = re.search(r'-(\d+)/Home', u)
            oid = m.group(1) if m else ""
            if oid not in existing_ids:
                all_tasks.append((u, cat))
            else:
                logging.debug(f"Skipping already scraped {oid}")

    if limit:
        all_tasks = all_tasks[:limit]

    total_tasks = len(all_tasks)
    logging.info(f"Total new outlets to scrape: {total_tasks}")
    if total_tasks == 0:
        logging.info("All outlets are already scraped and up-to-date!")
        conn.close()
        return

    csv_file_exists = os.path.exists(output_csv)
    csv_file = open(output_csv, 'a', newline='', encoding='utf-8')
    csv_writer = csv.DictWriter(csv_file, fieldnames=FIELDS)
    if not csv_file_exists:
        csv_writer.writeheader()

    completed = 0
    start_time = time.time()
    batch_db = []

    def commit_batch():
        nonlocal batch_db
        if batch_db:
            try:
                cur = conn.cursor()
                placeholders = ", ".join(["?"] * len(FIELDS))
                for rec in batch_db:
                    vals = [rec[f] for f in FIELDS]
                    cur.execute(f"INSERT OR REPLACE INTO outlets VALUES ({placeholders})", vals)
                conn.commit()
                csv_file.flush()
                batch_db = []
            except Exception as e:
                logging.error(f"Error committing batch to DB: {e}")

    def worker(task):
        url, cat = task
        raw = fetch_url(url, timeout=15, delay_between=delay)
        if raw:
            return parse_outlet_html(url, cat, raw)
        return None

    last_id = None
    interrupted = False

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(worker, task): task for task in all_tasks}
            for future in as_completed(futures):
                try:
                    record = future.result()
                    completed += 1
                    if record and record.get('outlet_id'):
                        last_id = record['outlet_id']
                        csv_writer.writerow(record)
                        batch_db.append(record)

                    # Auto-checkpoint and commit every 10 records
                    if len(batch_db) >= 10:
                        commit_batch()
                        save_checkpoint(completed, total_tasks, last_id)

                    if completed % 50 == 0 or completed == total_tasks:
                        elapsed = time.time() - start_time
                        rate = completed / elapsed if elapsed > 0 else 0
                        logging.info(f"Progress: {completed}/{total_tasks} ({completed/total_tasks*100:.1f}%) | Rate: {rate:.1f} pages/s")
                except Exception as ex:
                    logging.debug(f"Task error: {ex}")

    except (KeyboardInterrupt, SystemExit):
        interrupted = True
        print("\n" + "="*70)
        logging.info("[PAUSED] Interrupted by user (Ctrl+C). Saving safe checkpoint...")
        commit_batch()
        save_checkpoint(completed, total_tasks, last_id)
        csv_file.flush()
        csv_file.close()
        conn.close()
        total_in_db = len(get_existing_ids(db_path))
        print("="*70)
        print(f" [CHECKPOINT SAVED]")
        print(f" - Scraped in this session : {completed} outlets")
        print(f" - Total saved in database : {total_in_db} outlets")
        print(f" - Remaining to scrape     : {total_tasks - completed} outlets")
        print(f" - Database file           : {db_path}")
        print(f" - CSV file                : {output_csv}")
        print(f" - Checkpoint state        : {CHECKPOINT_FILE}")
        print(f"\n To resume anytime, just run:")
        print(f"   python iocl_scraper.py --workers {max_workers} --delay {delay}")
        print("="*70 + "\n")
        return

    # Final commit when completed normally
    commit_batch()
    save_checkpoint(completed, total_tasks, last_id)
    csv_file.close()
    conn.close()
    logging.info(f"[SUCCESS] Scraping completed! {completed} outlets saved to '{output_csv}' and '{db_path}'.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Scrape IOCL Locator (Petrol Pumps & Fuel Stations)')
    parser.add_argument('--workers', type=int, default=8, help='Number of concurrent worker threads (Default: 8)')
    parser.add_argument('--delay', type=float, default=0.2, help='Polite delay in seconds per request (Default: 0.2)')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of outlets (for testing)')
    parser.add_argument('--refresh-sitemap', action='store_true', help='Force re-fetch sitemap index and sub-sitemaps')
    parser.add_argument('--csv', default='iocl_outlets.csv', help='Output CSV filename')
    parser.add_argument('--db', default='iocl_outlets.db', help='Output SQLite database filename')

    args = parser.parse_args()

    run_scraper(
        categories=['Retail_Fuel'],
        max_workers=args.workers,
        delay=args.delay,
        output_csv=args.csv,
        db_path=args.db,
        limit=args.limit,
        refresh_cache=args.refresh_sitemap
    )
