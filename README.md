# ⛽ Fuel Extractor - Indian Oil Corporation Limited (IOCL) Locator Scraper

High-performance, resilient scraper and data extraction pipeline for all **Indian Oil Corporation Limited (IOCL)** retail fuel stations (~39,555 pumps) and Indane LPG distributorships (~14,500 agencies) across India from [locator.iocl.com](https://locator.iocl.com/).

---

## 🚀 Features

- **Pre-indexed Sitemap Discovery**: Includes all 39,555 outlet permalinks pre-cached in `discovered_urls.json`.
- **Rich JSON-LD Schema Extraction**: Extracts State, City, Locality, Pincode, GPS Coordinates (Latitude/Longitude), Dealer Name, Contact Person, Phone, Email, Operating Hours, Amenities, and Customer Ratings.
- **Resilient & Anti-Blocking**: Browser header simulation, polite rate-limiting, and automatic cooldown.
- **Dual-Storage & Instant Resume**: Real-time batch writes to SQLite (`iocl_outlets.db`) and CSV (`iocl_outlets.csv`) with checkpoint support (`checkpoint.json`).
- **Excel Formatter**: Built-in script (`db_to_excel.py`) that generates styled Excel reports with auto-sized columns and state-wise breakdown summaries.

---

## 📁 Repository Structure

```
├── iocl_scraper.py               # Main multithreaded extraction script
├── db_to_excel.py                # Database to styled Excel (.xlsx) converter
├── discovered_urls.json          # Cached inventory of 39,555 outlet URLs
├── IOCL_LOCATOR_SCRAPING_GUIDE.md# Comprehensive technical specification & documentation
├── iocl_outlets.db               # SQLite database (auto-generated)
├── iocl_outlets.csv              # CSV dataset (auto-generated)
└── iocl_outlets.xlsx             # Formatted Excel report (auto-generated)
```

---

## 🛠️ Installation & Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/TechnoRagee/Fuel-Extractor-.git
   cd Fuel-Extractor-
   ```

2. **Dependencies**:
   - The scraper uses **Python standard libraries only** (no pip packages needed).
   - For Excel export:
     ```bash
     pip install pandas openpyxl
     ```

---

## ⚡ Usage

### 1. Run the Scraper
To scrape fuel stations with recommended safe rate-limiting:
```bash
python iocl_scraper.py --workers 10 --delay 0.15
```

Options:
- `--workers <int>`: Number of concurrent threads (Default: `8`).
- `--delay <float>`: Polite delay in seconds per request (Default: `0.2`).
- `--limit <int>`: Limit number of outlets for quick testing (e.g. `--limit 50`).

### 2. Export to Excel
Generate a formatted Excel workbook with summary statistics:
```bash
python db_to_excel.py
```
Or generate individual worksheet tabs for each State:
```bash
python db_to_excel.py --separate-sheets
```

---

## 📊 Extracted Data Schema

| Field Name | Type | Description |
| :--- | :--- | :--- |
| `outlet_id` | `VARCHAR(32)` | Unique IOCL station identifier |
| `outlet_name` | `VARCHAR(255)` | Brand entity name (`IndianOil`) |
| `dealer_name` | `VARCHAR(255)` | Dealership / trade name |
| `state` | `VARCHAR(100)` | State / Union Territory |
| `city` | `VARCHAR(100)` | District / City |
| `locality` | `VARCHAR(100)` | Locality / Area / Sector |
| `street_address` | `TEXT` | Full street address |
| `pincode` | `VARCHAR(12)` | Postal PIN code |
| `latitude` / `longitude` | `DECIMAL` | Precise GPS coordinates |
| `telephone` | `VARCHAR(64)` | Official phone / contact number |
| `email` | `VARCHAR(128)` | Dealership email |
| `contact_person` | `VARCHAR(128)` | Proprietor / Station manager name |
| `opening_hours` | `TEXT` | Weekly operating timings |
| `amenities` | `TEXT` | Clean water, air, toilets, EV charging, etc. |
| `rating_value` | `DECIMAL` | Average rating score |
| `rating_count` | `INTEGER` | Total customer ratings |
| `page_url` / `map_url` | `TEXT` | Permalink & Google Map link |
