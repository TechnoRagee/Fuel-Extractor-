# ⛽ Fuel Extractor - India Fuel Station Scrapers (IOCL, BPCL & HPCL)

High-performance, resilient scraper and data extraction pipeline for India's "Big Three" oil marketing companies:
1. **Indian Oil Corporation Limited (IOCL)**: All retail outlets and petrol pumps (~39,555 pumps).
2. **Bharat Petroleum Corporation Limited (BPCL)**: All retail outlets and petrol pumps (~22,000+ pumps) via official REST API.
3. **Hindustan Petroleum Corporation Limited (HPCL)**: All retail outlets and petrol pumps (~24,026 pumps) via SingleInterface locator.

---

## 🚀 Features

### 🔵 Indian Oil (IOCL)
- **Pre-indexed Permalinks**: Discovered 39,555 outlet URLs in `discovered_urls.json`.
- **JSON-LD Structured Extraction**: State, City, Locality, Pincode, GPS (Lat/Lon), Dealer Name, Contact Person, Phone, Email, Timings, Amenities, and Ratings.
- **Resilient & Anti-Blocking**: Polite rate-limiting (`--delay`), auto-cooldown, SQLite database (`iocl_outlets.db`), and formatted Excel export (`db_to_excel.py`).

### 🟡 Bharat Petroleum (BPCL)
- **Official High-Speed REST API**: Direct integration with BPCL CEP REST API (`https://api.cep.bpcl.in/retail/v2/bpcl/retail/rolocators`).
- **OAuth 2.0 Auto-Refresh**: Fully automated headless token generation and background refresh.
- **Nationwide Spatial Mesh**: Intelligent 50 km coordinate grid covering all 28 states, 8 UTs, and ~750 districts.
- **Rich Schema**: Station Name, Address Line 1 & 2, City, District, State, Pincode, GPS Coords, Cellphone, Email, Available Fuels (Speed, Petrol, Diesel, CNG), and Amenities.
- **Multi-Tab Excel Report**: Built-in state distribution summary and individual state sheets with BPCL navy branding (`bpcl_db_to_excel.py`).

### 🔴 Hindustan Petroleum (HPCL)
- **Pre-indexed Sitemaps**: Discovered all 24,026 outlet permalinks across 1,038 district archives in `hpcl_discovered_urls.json`.
- **Schema.org Structured Extraction**: GasStation and BreadcrumbList JSON-LD graphs with Dealership Name, Address, City, State, Pincode, GPS Latitude/Longitude, Phone, Email, Contact Person, and Map links.
- **Multi-Tab Excel Report**: State-wise distribution summary and top state worksheets with HPCL crimson red branding (`hpcl_db_to_excel.py`).

---

## 📁 Repository Structure

```
├── iocl_scraper.py               # IOCL scraper
├── db_to_excel.py                # IOCL Excel exporter
├── discovered_urls.json          # 39,555 IOCL URLs
│
├── bpcl_scraper.py               # BPCL scraper (REST API)
├── bpcl_db_to_excel.py           # BPCL Excel exporter
├── bpcl_checkpoint.json          # BPCL resumable checkpoint
├── bpcl_outlets.db               # BPCL SQLite database
├── bpcl_outlets.xlsx             # Formatted BPCL Excel report
│
├── hpcl_scraper.py               # HPCL scraper
├── hpcl_db_to_excel.py           # HPCL Excel exporter
├── hpcl_discovered_urls.json     # 24,026 HPCL URLs
├── hpcl_checkpoint.json          # HPCL resumable checkpoint
├── hpcl_outlets.db               # HPCL SQLite database
└── hpcl_outlets.xlsx             # Formatted HPCL Excel report
```

---

## 🛠️ Installation & Dependencies

```bash
pip install pandas openpyxl
```

---

## ⚡ Usage

### 🔴 Hindustan Petroleum (HPCL) Scraper

1. **Run Scraper**:
   ```bash
   python hpcl_scraper.py --workers 8 --delay 0.2
   ```
   Options:
   - `--workers <int>`: Number of concurrent threads (Default: `8`).
   - `--delay <float>`: Polite delay in seconds per request (Default: `0.2`).
   - `--limit <int>`: Limit number of outlets for quick runs (e.g. `--limit 50`).
   - `--reset`: Reset database and checkpoint to start fresh.

2. **Export to Multi-Sheet Excel & CSV**:
   ```bash
   python hpcl_db_to_excel.py
   ```

---

### 🟡 Bharat Petroleum (BPCL) Scraper

1. **Run Scraper**:
   ```bash
   python bpcl_scraper.py --workers 4 --delay 0.5
   ```

2. **Export to Excel & CSV**:
   ```bash
   python bpcl_db_to_excel.py
   ```

---

### 🔵 Indian Oil (IOCL) Scraper

1. **Run Scraper**:
   ```bash
   python iocl_scraper.py --workers 8 --delay 0.2
   ```

2. **Export to Excel**:
   ```bash
   python db_to_excel.py
   ```

---

## 📊 Extracted Data Schemas

### BPCL Schema
| Field Name | Description | Example |
| :--- | :--- | :--- |
| `ro_id` | Unique Retail Outlet ID | `0000185560` |
| `name` / `display_name` | Dealership / Station Name | `SHREE SAI PETROLEUM BHARAT PETROLEUM DEALERS` |
| `line1` / `line2` | Address Lines | `PEN KHOPOLI ROAD, AT- HORALE VILLAGE` |
| `town` / `district` | City & District | `KHALAPUR, RAIGAD` |
| `state` / `state_iso` | State & ISO Code | `Maharashtra (IN-20)` |
| `postal_code` | Pincode | `410203` |
| `cellphone` / `email` | Contact Info | `9920666021, shreesa185560@bpclretail.in` |
| `latitude` / `longitude`| GPS Coordinates | `18.775375, 73.228878` |
| `fuels_available` | Available Fuels | `DIESEL, PETROL, SPEED` |
| `amenities` | Station Amenities | `Automation, Pure_Sure, Air_Filling, 24/7` |
