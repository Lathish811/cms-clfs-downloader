import os
import zipfile
import glob
import requests
import pandas as pd
import mysql.connector
import subprocess
import re
from pathlib import Path

# =========================
# CONFIG
# =========================
BASE_URL = "https://www.cms.gov"

# 🔹 TWO PAGE URLS
DME_PAGE = "https://www.cms.gov/medicare/payment/fee-schedules/dmepos/dmepos-fee-schedule/dme26"
ANES_PAGE = "https://www.cms.gov/anesthesiologists-information-center"

DOWNLOAD_DIR = r"C:\Projects\Automation-2\Output"
OUTPUT_SQL = os.path.join(DOWNLOAD_DIR, "final_output.sql")

DME_ZIP = os.path.join(DOWNLOAD_DIR, "dme.zip")
ANES_ZIP = os.path.join(DOWNLOAD_DIR, "anes.zip")

# MySQL
DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = "your_password_here"
DB_NAME = "medicare_fee"
EXECUTE_SQL = False  # Set to True if you want the script to run the generated SQL against MySQL.

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

session = requests.Session()

# =========================
# STEP 1: GET ZIP LINK
# =========================
def get_zip_link(page_url, keyword=None):
    print(f"[INFO] Loading page: {page_url}")

    res = session.get(page_url)
    res.raise_for_status()

    if keyword:
        pattern = rf'/files/zip/.*?{keyword}.*?\.zip'
    else:
        pattern = r'/files/zip/.*?\.zip'

    match = re.search(pattern, res.text, re.IGNORECASE)

    if not match:
        raise Exception(f"ZIP link not found in {page_url}")

    zip_path = match.group(0)
    print(f"[INFO] Found ZIP: {zip_path}")

    return f"{BASE_URL}{zip_path}"

# =========================
# STEP 2: DOWNLOAD
# =========================
def download(url, path):
    print(f"[INFO] Downloading: {url}")

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    res = session.get(url, headers=headers, stream=True)
    res.raise_for_status()

    with open(path, "wb") as f:
        for chunk in res.iter_content(8192):
            if chunk:
                f.write(chunk)

    print(f"[SUCCESS] Saved: {path}")

# =========================
# STEP 3: EXTRACT
# =========================
def extract(zip_path):
    print(f"[INFO] Extracting: {zip_path}")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(DOWNLOAD_DIR)

# =========================
# STEP 4: FIND SOURCE FILE
# =========================
def find_source_file(keywords, exts):
    files = []
    for ext in exts:
        files.extend(glob.glob(os.path.join(DOWNLOAD_DIR, f"*{ext}")))

    if not files:
        raise Exception(f"No source files found in {DOWNLOAD_DIR}")

    for keyword in keywords:
        for f in files:
            if keyword.lower() in os.path.basename(f).lower():
                return f

    return files[0]


def infer_csv_columns(csv_file, skip_lines):
    import csv

    with open(csv_file, newline='', encoding='utf-8', errors='ignore') as f:
        for _ in range(skip_lines):
            next(f, None)
        reader = csv.reader(f)
        header = next(reader, None)

    if not header:
        raise Exception(f"Could not determine CSV header for {csv_file}")

    columns = []
    for idx, name in enumerate(header, start=1):
        clean = name.strip()
        if not clean:
            clean = f"COL_{idx}"
        columns.append(clean)

    return columns

# =========================
# STEP 5: GENERATE SQL
# =========================
def generate_sql_block(txt_file, table_name):
    print(f"[INFO] Generating SQL for {table_name}")

    mysql_path = txt_file.replace("\\", "/")

    if table_name == "dme_table":
        create_sql = f"""
DROP TABLE IF EXISTS {table_name};

CREATE TABLE {table_name} (
    `PROCEDURE CD` VARCHAR(20),
    `STATE CD` VARCHAR(5),
    `PRICING YEAR` INT,
    `ALLOWANCE AMT` DECIMAL(12,4),
    `PROCD MOD CD1` VARCHAR(20),
    `PROCD MOD EFF DT1` DATE,
    `PROCD MOD CD2` VARCHAR(20)
);
"""
        load_columns = "`PROCEDURE CD`, `STATE CD`, `PRICING YEAR`, `ALLOWANCE AMT`, `PROCD MOD CD1`, @PROCD_MOD_EFF_DT1, `PROCD MOD CD2`, @EXTRA"
        set_clause = "SET `PROCD MOD EFF DT1` = STR_TO_DATE(@PROCD_MOD_EFF_DT1, '%Y%m%d');"
    elif table_name == "anes_table":
        create_sql = f"""
DROP TABLE IF EXISTS {table_name};

CREATE TABLE {table_name} (
    CONTRACTOR VARCHAR(20),
    LOCALITY VARCHAR(20),
    LOCALITY_NAME VARCHAR(100),
    WORK_GPCI DECIMAL(8,3),
    PE_GPCI DECIMAL(8,3),
    MP_GPCI DECIMAL(8,3),
    NON_QUAL_ANES DECIMAL(8,2),
    QUAL_ANES DECIMAL(8,2)
);
"""
        load_columns = "CONTRACTOR, LOCALITY, LOCALITY_NAME, WORK_GPCI, PE_GPCI, MP_GPCI, NON_QUAL_ANES, QUAL_ANES"
        set_clause = ""
    else:
        create_sql = f"""
DROP TABLE IF EXISTS {table_name};

CREATE TABLE {table_name} (
    YEAR INT,
    HCPCS VARCHAR(10),
    MODIFIER VARCHAR(5),
    EFF_DATE DATE,
    INDICATOR CHAR(1),
    RATE DECIMAL(10,2)
);
"""
        load_columns = "YEAR, HCPCS, MODIFIER, @EFF_DATE, INDICATOR, RATE, @EXTRA"
        set_clause = "SET EFF_DATE = STR_TO_DATE(@EFF_DATE, '%Y%m%d');"

    suffix = Path(txt_file).suffix.lower()
    if suffix == ".csv":
        if table_name == "dme_table":
            header_skip = 7
        elif table_name == "anes_table":
            header_skip = 4
        else:
            header_skip = 0

        if table_name not in ("dme_table", "anes_table"):
            columns = infer_csv_columns(txt_file, header_skip)
            column_defs = ",\n    ".join([f'`{col}` VARCHAR(255)' for col in columns])
            create_sql = f"""
DROP TABLE IF EXISTS {table_name};

CREATE TABLE {table_name} (
    {column_defs}
);
"""
            load_columns = ",\n    ".join([f'`{col}`' for col in columns])
            set_clause = ""

        delimiter = ','
        enclosed = "OPTIONALLY ENCLOSED BY '\"'"
        ignore_lines = header_skip + 1
    else:
        delimiter = '~'
        enclosed = ''
        ignore_lines = 0

    sql = f"""
{create_sql}
LOAD DATA LOCAL INFILE '{mysql_path}'
INTO TABLE {table_name}
FIELDS TERMINATED BY '{delimiter}'
{enclosed}
LINES TERMINATED BY '\n'
IGNORE {ignore_lines} LINES
(
    {load_columns}
)
{set_clause}

SELECT COUNT(*) AS total_rows FROM {table_name};
SELECT * FROM {table_name} LIMIT 1000;
"""
    return sql

# =========================
# STEP 6: SAVE SQL
# =========================
def save_sql(sql):
    with open(OUTPUT_SQL, "w", encoding="utf-8") as f:
        f.write(sql)

    print(f"[SUCCESS] SQL saved: {OUTPUT_SQL}")

# =========================
# STEP 7: EXECUTE SQL
# =========================
def execute_sql():
    print("[INFO] Executing SQL...")

    conn = mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        allow_local_infile=True
    )

    cursor = conn.cursor()

    with open(OUTPUT_SQL, "r", encoding="utf-8") as f:
        sql_script = f.read()

    for result in cursor.execute(sql_script, multi=True):
        try:
            if result.with_rows:
                rows = result.fetchall()
                cols = [c[0] for c in result.description]

                print("\n" + "="*50)
                print(f"📊 {cols}")
                print("="*50)

                if rows:
                    df = pd.DataFrame(rows, columns=cols)
                    print(df.to_string(index=False))
                else:
                    print("[INFO] No rows")

            else:
                print(f"[SUCCESS] Rows affected: {result.rowcount}")

        except Exception as e:
            print(f"[WARNING] {e}")

    conn.commit()
    cursor.close()
    conn.close()

    print("[SUCCESS] Execution completed!")

# =========================
# MAIN
# =========================
def main():

    # 🔹 GET LINKS
    dme_link = get_zip_link(DME_PAGE)
    anes_link = get_zip_link(ANES_PAGE, "anesthesia")

    # 🔹 DOWNLOAD
    download(dme_link, DME_ZIP)
    download(anes_link, ANES_ZIP)

    # 🔹 EXTRACT
    extract(DME_ZIP)
    extract(ANES_ZIP)

    # 🔹 GET SOURCE FILES
    dme_txt = find_source_file(["dmepos", "dme"], [".txt", ".csv"])
    anes_txt = find_source_file(["anesthesia", "anes", "anesthesiologists"], [".csv", ".txt"])

    print(f"[INFO] DME source: {dme_txt}")
    print(f"[INFO] ANES source: {anes_txt}")

    # 🔹 GENERATE SQL (2 TABLES)
    sql_script = f"""
SET GLOBAL local_infile = 1;

CREATE DATABASE IF NOT EXISTS {DB_NAME};
USE {DB_NAME};
"""

    sql_script += generate_sql_block(dme_txt, "dme_table")
    sql_script += "\n\n"
    sql_script += generate_sql_block(anes_txt, "anes_table")

    # 🔹 SAVE + (OPTIONALLY) EXECUTE
    save_sql(sql_script)
    subprocess.run(["code", OUTPUT_SQL], shell=True)

    if EXECUTE_SQL:
        execute_sql()
    else:
        print("[INFO] EXECUTE_SQL is False — skipping SQL execution. Set EXECUTE_SQL = True at the top of the script to run it automatically.")


# =========================
# RUN
# =========================
if __name__ == "__main__":
    main()