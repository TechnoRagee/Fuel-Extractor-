# Comprehensive Scraping Architecture & Guide for IOCL Locator (`locator.iocl.com`)

This document provides a complete technical specification, reverse-engineered architecture, data schema, and execution guide for extracting the entire dataset of **Indian Oil Corporation Limited (IOCL)** outlets from [locator.iocl.com](https://locator.iocl.com/).

---

## 1. Executive Summary & Website Analysis

The Indian Oil Corporation Limited (IOCL) store locator (`locator.iocl.com`) is the single source of truth for all IndianOil retail touchpoints across India. It is hosted on the enterprise **SingleInterface** multi-location platform.

### Target Coverage:
1. **IOCL Retail Petrol & Diesel Stations / Fuel Bunks**: ~**39,555** stations nationwide (including XP95, XP100, XTRAGREEN, EV Charging Stations, CNG pumps).
2. **Indane LPG Gas Agencies / Distributorships**: ~**14,500+** distributors nationwide.
3. **Total Outlets**: **~54,000+ locations** across all 28 States and 8 Union Territories.

---

## 2. Website Architecture & Scraping Vector

### A. Sitemap Index Hierarchy (Fastest & Most Reliable Ingestion Vector)
Instead of crawling recursive web pages or simulating headless browser clicks (which is brittle and slow), the site publishes complete, machine-readable XML sitemap indexes that are updated daily:

| Category | Root Sitemap Index URL | Sub-Sitemaps | Total Outlets |
| :--- | :--- | :--- | :--- |
| **Retail Fuel Stations** | `https://locator.iocl.com/sitemap.xml` | ~1,131 `.xml.gz` files | **~39,555** |
| **Indane LPG Agencies** | `https://locator.iocl.com/indane/sitemap.xml` | ~978 `.xml.gz` files | **~14,500+** |

Each sub-sitemap is compressed with Gzip (`.xml.gz`) organized by State and City/District (e.g., `.../sitemap/google/99528/maharashtra/mumbai.xml.gz`).

### B. URL Anatomy
Each outlet URL follows a standardized permalink structure:
```text
https://locator.iocl.com/indianoil-[dealer-slug]-[outlet-type]-[locality]-[city]-[outlet_id]/Home
https://locator.iocl.com/indane/indane-[agency-slug]-gas-agency-[locality]-[city]-[outlet_id]/Home
```
- **Outlet ID**: The numeric ID at the end of the URL slug (e.g., `238914`, `297441`).

### C. Rich Embedded JSON-LD Schemas
Every outlet `/Home` page embeds structured `application/ld+json` schema graphs conforming to [Schema.org](https://schema.org):
1. **`BreadcrumbList`**: Contains strict regional hierarchy:
   - Position 1: `Home`
   - Position 2: `State` (e.g. "Dadra And Nagar Haveli", "Maharashtra", "Tamil Nadu")
   - Position 3: `City / District` (e.g. "Silvassa", "Mumbai", "Chennai")
   - Position 4: `Locality / Area` (e.g. "Amboli", "Andheri West", "T Nagar")
   - Position 5: `Outlet Name`
2. **`GasStation` / `Store` / `LocalBusiness`**: Contains verified operational attributes:
   - Official Name & Dealer Trade Name (`alternateName`)
   - Exact GPS Coordinates (`geo.latitude`, `geo.longitude`)
   - Detailed Address & Postal Code (`streetAddress`, `postalCode`)
   - Official Phone Numbers & Dealer Email Address
   - Contact Person / Outlet Manager Name
   - Weekly Working Hours / Timings
   - Accepted Payment Modes (Cash, Credit Card, UPI, etc.)
   - Facilities / Amenities (Toilet, Free Air, Clean Drinking Water, EV Charging, etc.)
   - Customer Review Aggregates (`ratingValue`, `ratingCount`)
   - Google Maps navigation link (`hasMap`)

---

## 3. Complete Data Schema & Field Dictionary

| Field Name | Type | Description | Sample Value |
| :--- | :--- | :--- | :--- |
| `outlet_id` | `VARCHAR(32)` | Unique numeric identifier for the station | `238914` |
| `category` | `VARCHAR(32)` | Outet category (`Retail_Fuel` or `Indane_LPG`) | `Retail_Fuel` |
| `outlet_name` | `VARCHAR(255)` | Brand entity name | `IndianOil` |
| `dealer_name` | `VARCHAR(255)` | Official trade / dealership name | `Ratan Petrolium Dadra` |
| `outlet_type` | `VARCHAR(64)` | Schema entity type | `GasStation` / `Store` |
| `state` | `VARCHAR(100)` | State or Union Territory | `Dadra And Nagar Haveli` |
| `city` | `VARCHAR(100)` | District / City | `Silvassa` |
| `locality` | `VARCHAR(100)` | Locality / Sector / Village | `Amboli` |
| `street_address` | `TEXT` | Street address / Survey No. | `No 11001/16/17/18/19/20/12001/2, Dadra` |
| `pincode` | `VARCHAR(12)` | 6-digit Postal PIN code | `396230` |
| `country` | `VARCHAR(32)` | Country | `India` |
| `latitude` | `DECIMAL(10,7)` | WGS84 Latitude | `20.3236000` |
| `longitude` | `DECIMAL(10,7)` | WGS84 Longitude | `72.9636000` |
| `telephone` | `VARCHAR(64)` | Contact phone number / mobile | `+919825171189` |
| `email` | `VARCHAR(128)` | Dealership email address | `ratanpetroleum56@gmail.com` |
| `contact_person`| `VARCHAR(128)` | Manager or proprietor name | `Kalaben M Delkar` |
| `opening_hours` | `TEXT` | Operating schedules across days | `Monday: 06:00 AM-10:00 PM; ...` |
| `payment_modes` | `TEXT` | Accepted payment mechanisms | `Cash, Credit Card, Debit Card, Online Payment` |
| `amenities` | `TEXT` | On-site amenities & services | `Kerbside Parking; Clean Drinking Water, Free Air Facility, Toilet` |
| `rating_value` | `DECIMAL(3,2)` | Average customer rating (1-5) | `3.7` |
| `rating_count` | `INTEGER` | Total number of ratings | `276` |
| `page_url` | `TEXT` | Official outlet permalink | `https://locator.iocl.com/...-238914/Home` |
| `map_url` | `TEXT` | Location map directions link | `https://locator.iocl.com/...-238914/Map` |

---

## 4. Production Scraper Implementation

The workspace includes a standalone script: [`iocl_scraper.py`](file:///c:/Users/User/OneDrive/Desktop/Fuel%20Extractor/iocl_scraper.py).

### Core Features of the Scraper:
1. **Two-Stage Ingestion Pipeline**:
   - **Stage 1 (Discovery)**: Downloads all `.xml.gz` sitemaps concurrently and extracts unique outlet URLs within ~30 seconds.
   - **Stage 2 (Extraction)**: Scrapes individual outlet HTML pages in parallel with thread pooling, extracting structured JSON-LD data.
2. **Built-in Resumption & Deduplication**:
   - Stores scraped records in a local SQLite database (`iocl_outlets.db`).
   - If interrupted, restarting the script immediately resumes without re-scraping existing outlet IDs.
3. **Anti-Blocking & Robust HTTP Client**:
   - Custom browser User-Agent headers to prevent 403 Forbidden errors.
   - Automatic exponential backoff and retry handling.
4. **Multi-Format Export**:
   - Concurrent writes to SQLite database (`iocl_outlets.db`) and CSV file (`iocl_outlets.csv`).

---

## 5. Usage & Execution Instructions

### Prerequisites
Python 3.8+ (no heavy dependencies required; uses Python standard library `urllib`, `sqlite3`, `gzip`, `xml.etree`).

### Command Line Execution

#### A. Quick Test Run (e.g., 50 records)
```bash
python iocl_scraper.py --limit 50
```

#### B. Scrape Only Retail Fuel Stations (Petrol/Diesel/EV)
```bash
python iocl_scraper.py --category fuel --workers 30 --csv iocl_fuel_stations.csv
```

#### C. Scrape Only Indane LPG Distributors
```bash
python iocl_scraper.py --category lpg --workers 30 --csv indane_distributors.csv
```

#### D. Full Nationwide Extraction (All ~54,000 Outlets)
```bash
python iocl_scraper.py --workers 30
```

#### E. Export SQLite Database to Formatted Excel (.xlsx)
```bash
# Standard Excel export (All Outlets + State Summary sheet)
python db_to_excel.py

# Custom output file
python db_to_excel.py --db iocl_outlets.db --output iocl_full_data.xlsx

# Export with separate worksheet tabs for each Indian State / UT
python db_to_excel.py --separate-sheets
```

### CLI Parameters:
- `--workers <int>`: Concurrency level (Default: `25`, recommended `20-40`).
- `--limit <int>`: Limit extraction count for testing.
- `--category [all|fuel|lpg]`: Target category (Default: `all`).
- `--csv <filepath>`: Target output CSV file (Default: `iocl_outlets.csv`).
- `--db <filepath>`: Target output SQLite database (Default: `iocl_outlets.db`).

---

## 6. Storage & Database Schema

### SQLite / PostgreSQL Schema
```sql
CREATE TABLE IF NOT EXISTS iocl_outlets (
    outlet_id VARCHAR(32) PRIMARY KEY,
    category VARCHAR(32) NOT NULL,
    outlet_name VARCHAR(255),
    dealer_name VARCHAR(255),
    outlet_type VARCHAR(64),
    state VARCHAR(100),
    city VARCHAR(100),
    locality VARCHAR(100),
    street_address TEXT,
    pincode VARCHAR(12),
    country VARCHAR(32) DEFAULT 'India',
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),
    telephone VARCHAR(64),
    email VARCHAR(128),
    contact_person VARCHAR(128),
    opening_hours TEXT,
    payment_modes TEXT,
    amenities TEXT,
    rating_value DECIMAL(3, 2),
    rating_count INTEGER,
    page_url TEXT,
    map_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_outlets_state_city ON iocl_outlets(state, city);
CREATE INDEX idx_outlets_pincode ON iocl_outlets(pincode);
CREATE INDEX idx_outlets_geo ON iocl_outlets(latitude, longitude);
```

---

## 7. Performance & Resource Estimates

| Metric | Retail Fuel Stations | Indane LPG Agencies | Combined Dataset |
| :--- | :--- | :--- | :--- |
| **Total Target Records** | ~39,555 | ~14,500+ | **~54,000+** |
| **Sitemap Discovery Time** | ~25 seconds | ~20 seconds | **~45 seconds** |
| **Worker Threads** | 30 concurrent | 30 concurrent | **30 concurrent** |
| **Scraping Speed** | 25 - 40 pages / sec | 25 - 40 pages / sec | **25 - 40 pages / sec** |
| **Total Estimated Time** | ~20 - 25 minutes | ~8 - 10 minutes | **~30 - 35 minutes** |
| **Total Data Volume** | ~25 MB (CSV) | ~10 MB (CSV) | **~35 MB (CSV) / ~60 MB (SQLite)** |

---

## 8. Incremental Updates & Maintenance

To perform weekly or monthly delta updates:
1. Run the script against the sitemap index.
2. The scraper queries `iocl_outlets.db` for existing IDs.
3. Newly added petrol stations or gas agencies are scraped and inserted automatically.
4. To force-update existing records with new ratings or timings, clear or truncate the database table before running.
