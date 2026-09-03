# ⛽ Fuel Extractor - India Fuel Station Scrapers (Top 8 OMC Networks)

High-performance, resilient scraper and data extraction pipeline for India's major oil marketing companies, organized into autonomous, dedicated folders:

1. **[IOCL/](file:///c:/Users/User/OneDrive/Desktop/Fuel%20Extractor/IOCL)**: Indian Oil Corporation Limited (~39,555 pumps)
2. **[BPCL/](file:///c:/Users/User/OneDrive/Desktop/Fuel%20Extractor/BPCL)**: Bharat Petroleum Corporation Limited (~27,890 pumps)
3. **[HPCL/](file:///c:/Users/User/OneDrive/Desktop/Fuel%20Extractor/HPCL)**: Hindustan Petroleum Corporation Limited (~24,026 pumps)
4. **[JIO-BP/](file:///c:/Users/User/OneDrive/Desktop/Fuel%20Extractor/JIO-BP)**: Reliance BP Mobility Limited (All 2,256 stations nationwide)
5. **[NAYARA/](file:///c:/Users/User/OneDrive/Desktop/Fuel%20Extractor/NAYARA)**: Nayara Energy (~6,500+ pumps)
6. **[SHELL/](file:///c:/Users/User/OneDrive/Desktop/Fuel%20Extractor/SHELL)**: Shell India Retail (All 332 stations nationwide)
7. **[ESSAR/](file:///c:/Users/User/OneDrive/Desktop/Fuel%20Extractor/ESSAR)**: Essar Oil (Rebranded to Nayara Energy network)
8. **[MRPL/](file:///c:/Users/User/OneDrive/Desktop/Fuel%20Extractor/MRPL)**: Mangalore Refinery and Petrochemicals Limited - ONGC HiQ (All 172 stations)

---

## 📁 Repository Structure

```
├── IOCL/                             # Indian Oil Corporation Limited
│   ├── iocl_scraper.py               # Main IOCL scraper
│   ├── iocl_db_to_excel.py           # IOCL Excel exporter
│   ├── discovered_urls.json          # 39,555 pre-indexed IOCL outlet URLs
│   ├── checkpoint.json               # Checkpoint state file
│   ├── iocl_outlets.db               # SQLite database (39,547 records)
│   ├── iocl_outlets.xlsx             # Formatted Excel report
│   └── iocl_outlets.csv              # CSV dataset
│
├── BPCL/                             # Bharat Petroleum Corporation Limited
│   ├── bpcl_scraper.py               # Main BPCL REST API scraper
│   ├── bpcl_db_to_excel.py           # Multi-sheet Excel & CSV exporter
│   ├── bpcl_checkpoint.json          # Resumable checkpoint
│   ├── bpcl_outlets.db               # SQLite database (27,890 records)
│   ├── bpcl_outlets.xlsx             # Formatted Excel report
│   └── bpcl_outlets.csv              # Formatted CSV dataset
│
├── HPCL/                             # Hindustan Petroleum Corporation Limited
│   ├── hpcl_scraper.py               # Main HPCL JSON-LD scraper
│   ├── hpcl_db_to_excel.py           # Multi-sheet Excel & CSV exporter
│   ├── hpcl_discovered_urls.json     # 24,026 pre-indexed HPCL outlet URLs
│   ├── hpcl_checkpoint.json          # Resumable checkpoint
│   ├── hpcl_outlets.db               # SQLite database (24,026 records)
│   ├── hpcl_outlets.xlsx             # Formatted Excel report
│   └── hpcl_outlets.csv              # Formatted CSV dataset
│
├── JIO-BP/                           # Reliance BP Mobility Limited
│   ├── jiobp_scraper.py              # Main Jio-bp JSON-LD scraper
│   ├── jiobp_db_to_excel.py          # Multi-sheet Excel & CSV exporter
│   ├── jiobp_discovered_urls.json    # 2,258 pre-indexed station URLs
│   ├── jiobp_checkpoint.json         # Resumable checkpoint
│   ├── jiobp_outlets.db              # SQLite database (2,256 records)
│   ├── jiobp_outlets_master.xlsx     # Formatted Excel report
│   └── jiobp_outlets.csv             # Formatted CSV dataset
│
├── NAYARA/                           # Nayara Energy
│   ├── nayara_scraper.py             # Main Nayara spatial REST API scraper
│   ├── nayara_db_to_excel.py         # Multi-sheet Excel & CSV exporter
│   ├── nayara_checkpoint.json        # Resumable checkpoint
│   ├── nayara_outlets.db             # SQLite database
│   ├── nayara_outlets.xlsx           # Formatted Excel report
│   └── nayara_outlets.csv            # Formatted CSV dataset
│
├── SHELL/                            # Shell India
│   ├── shell_scraper.py              # Main Shell REST API scraper (All 332 stations)
│   ├── shell_db_to_excel.py          # Multi-sheet Excel & CSV exporter
│   ├── shell_checkpoint.json         # Resumable checkpoint
│   ├── shell_outlets.db              # SQLite database (332 records)
│   ├── shell_outlets.xlsx            # Formatted Excel report (Shell Red/Yellow)
│   └── shell_outlets.csv             # Formatted CSV dataset
│
├── ESSAR/                            # Essar Oil (Rebranded to Nayara Energy)
│   ├── ESSAR_TO_NAYARA_NOTICE.md     # Full acquisition & rebranding documentation
│   ├── essar_scraper.py              # Scraper / database sync bridge
│   ├── essar_db_to_excel.py          # Multi-sheet Excel & CSV exporter (Essar Red/Navy)
│   ├── essar_checkpoint.json         # Resumable checkpoint
│   ├── essar_outlets.db              # SQLite database
│   ├── essar_outlets.xlsx            # Formatted Excel report
│   └── essar_outlets.csv             # Formatted CSV dataset
│
├── MRPL/                             # Mangalore Refinery & Petrochemicals (ONGC HiQ)
│   ├── mrpl_scraper.py               # Main MRPL Playwright scraper (All 172 stations)
│   ├── mrpl_db_to_excel.py           # Multi-sheet Excel & CSV exporter (MRPL Navy/Gold)
│   ├── mrpl_checkpoint.json          # Resumable checkpoint
│   ├── mrpl_outlets.db               # SQLite database (172 records)
│   ├── mrpl_outlets.xlsx             # Formatted Excel report
│   └── mrpl_outlets.csv              # Formatted CSV dataset
│
├── README.md                         # Project documentation
└── .gitignore                        # Git ignore rules
```

---

## 🛠️ Installation & Dependencies

```bash
pip install pandas openpyxl curl_cffi beautifulsoup4 playwright
playwright install chromium
```

---

## ⚡ Usage (Running Each Scraper Independently)

Each folder is completely autonomous. Navigate into any folder and run:

### 1. 🔵 Indian Oil (IOCL)
```bash
cd IOCL
python iocl_scraper.py --workers 8 --delay 0.2
python iocl_db_to_excel.py
```

---

### 2. 🟡 Bharat Petroleum (BPCL)
```bash
cd BPCL
python bpcl_scraper.py --workers 4 --delay 0.5
python bpcl_db_to_excel.py
```

---

### 3. 🔴 Hindustan Petroleum (HPCL)
```bash
cd HPCL
python hpcl_scraper.py --workers 8 --delay 0.2
python hpcl_db_to_excel.py
```

---

### 4. 🔷 Reliance / Jio-bp
```bash
cd JIO-BP
python jiobp_scraper.py --workers 8 --delay 0.15
python jiobp_db_to_excel.py
```

---

### 5. 🟢 Nayara Energy
```bash
cd NAYARA
python nayara_scraper.py --workers 4 --delay 0.3
python nayara_db_to_excel.py
```

---

### 6. 🟡 Shell India
```bash
cd SHELL
python shell_scraper.py --workers 4 --delay 0.2
python shell_db_to_excel.py
```

---

### 7. 🔴 Essar Oil / Nayara
```bash
cd ESSAR
python essar_scraper.py --workers 4 --delay 0.3
python essar_db_to_excel.py
```

---

### 8. 🔵 MRPL (ONGC HiQ)
```bash
cd MRPL
python mrpl_scraper.py
python mrpl_db_to_excel.py
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
