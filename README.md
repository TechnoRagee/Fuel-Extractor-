# ⛽ Fuel Extractor - India Fuel Station Scrapers (IOCL & BPCL)

High-performance, resilient scraper and data extraction pipeline for India's major oil marketing companies:
1. **Indian Oil Corporation Limited (IOCL)**: All retail outlets and petrol pumps (~39,555 pumps).
2. **Bharat Petroleum Corporation Limited (BPCL)**: All retail outlets and petrol pumps (~20,000+ pumps) via official REST API.

---

## 🚀 Features

### 🔵 Indian Oil (IOCL)
- **Pre-indexed Permalinks**: Discovered 39,555 outlet URLs in `discovered_urls.json`.
- **JSON-LD Structured Extraction**: State, City, Locality, Pincode, GPS (Lat/Lon), Dealer Name, Contact Person, Phone, Email, Timings, Amenities, and Ratings.
- **Resilient & Anti-Blocking**: Polite rate-limiting (`--delay`), auto-cooldown, SQLite database (`iocl_outlets.db`), and formatted Excel export (`db_to_excel.py`).

### 🟡 Bharat Petroleum (BPCL)
- **Official High-Speed REST API**: Direct integration with BPCL CEP REST API (`https://api.cep.bpcl.in/retail/v2/bpcl/retail/rolocators`).
- **OAuth 2.0 Auto-Refresh**: Fully automated headless token generation and refresh.
- **Nationwide Spatial Mesh**: Intelligent coordinate grid covering all 28 states, 8 UTs, and ~750 districts.
- **Rich Schema**: Station Name, Address Line 1 & 2, City, District, State, Pincode, GPS Coords, Cellphone, Email, Available Fuels (Speed, Petrol, Diesel, CNG), and Amenities.
- **Multi-Tab Excel Report**: Built-in state distribution summary and individual state sheets with BPCL navy branding (`bpcl_db_to_excel.py`).

---

## 📁 Repository Structure

```
├── iocl_scraper.py               # Main multithreaded IOCL scraper
├── db_to_excel.py                # IOCL database to Excel converter
├── bpcl_scraper.py               # Main multithreaded BPCL scraper (REST API)
├── bpcl_db_to_excel.py           # BPCL database to multi-sheet Excel & CSV converter
├── discovered_urls.json          # Cached inventory of 39,555 IOCL URLs
├── IOCL_LOCATOR_SCRAPING_GUIDE.md# IOCL technical specification & guide
├── iocl_outlets.db               # IOCL SQLite database
├── bpcl_outlets.db               # BPCL SQLite database
├── bpcl_outlets.xlsx             # Formatted BPCL Excel report
└── bpcl_outlets.csv              # Formatted BPCL CSV dataset
```

---

## 🛠️ Installation & Dependencies

1. **Dependencies**:
   - Both scrapers use standard Python libraries.
   - For Excel export:
     ```bash
     pip install pandas openpyxl
     ```

---

## ⚡ Usage

### 🟡 Bharat Petroleum (BPCL) Scraper

1. **Run Scraper**:
   ```bash
   python bpcl_scraper.py --workers 6 --delay 0.2
   ```
   Options:
   - `--workers <int>`: Number of concurrent threads (Default: `6`).
   - `--delay <float>`: Polite delay in seconds per request (Default: `0.2`).
   - `--radius <int>`: Search radius in meters (Default: `40000` = 40 km).
   - `--max-points <int>`: Limit number of grid points for quick runs (e.g. `--max-points 25`).
   - `--reset`: Reset database and checkpoint to start fresh.

2. **Export to Multi-Sheet Excel & CSV**:
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
