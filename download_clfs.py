import os
import zipfile
import glob
import requests
import pandas as pd
import mysql.connector
import subprocess

# =========================
# CONFIG
# =========================
BASE_URL = "https://www.cms.gov"
PAGE_URL = "https://www.cms.gov/medicare/payment/fee-schedules/clinical-laboratory-fee-schedule-clfs/files/26clabq3"

DOWNLOAD_DIR = r"C:\Users\YourUsername\Downloads\clfs_data"
ZIP_NAME = "26clabq3.zip"
ZIP_PATH = os.path.join(DOWNLOAD_DIR, ZIP_NAME)
FINAL_SQL_PATH = os.path.join(DOWNLOAD_DIR, "final_output.sql")

# MySQL Config
DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = "your_password_here"
DB_NAME = "medicare_fee"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
session = requests.Session()

# =========================
# STEP 1: GET ZIP PATH
# =========================
def get_zip_path():
    print("[INFO] Loading CMS page...")

    res = session.get(PAGE_URL)
    res.raise_for_status()

    import re
    match = re.search(r'/files/zip/.*?\.zip', res.text)

    if not match:
        raise Exception("ZIP path not found on page")

    zip_path = match.group(0)
    print(f"[INFO] Found ZIP path: {zip_path}")
    return zip_path

# =========================
# STEP 2: DOWNLOAD
# =========================
def accept_and_download(zip_path):
    print("[INFO] Downloading file...")

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": PAGE_URL
    }

    download_url = f"{BASE_URL}{zip_path}"

    res = session.get(download_url, headers=headers, stream=True)
    res.raise_for_status()

    with open(ZIP_PATH, "wb") as f:
        for chunk in res.iter_content(8192):
            if chunk:
                f.write(chunk)

    print(f"[SUCCESS] Downloaded: {ZIP_PATH}")

# =========================
# STEP 3: EXTRACT
# =========================
def extract_zip():
    print("[INFO] Extracting ZIP...")
    with zipfile.ZipFile(ZIP_PATH, 'r') as zip_ref:
        zip_ref.extractall(DOWNLOAD_DIR)

# =========================
# STEP 4: FIND TXT
# =========================
def get_txt_file():
    txt_files = glob.glob(os.path.join(DOWNLOAD_DIR, "*.txt"))
    if not txt_files:
        raise Exception("No TXT file found")
    return txt_files[0]

# =========================
# STEP 5: PROCESS FILE
# =========================
def process_file(txt_file):
    print("[INFO] Reading TXT file...")

    try:
        df = pd.read_csv(txt_file, sep="|", dtype=str)
    except:
        df = pd.read_fwf(txt_file, dtype=str)

    df.fillna("", inplace=True)

    print("\n[INFO] File preview:\n")
    print(df.head())

    return df

# =========================
# STEP 6: GENERATE SQL
# =========================
def generate_sql(txt_file):
    print("[INFO] Generating SQL...")

    mysql_path = txt_file.replace("\\", "/")

    sql = f"""
SET GLOBAL local_infile = 1;

CREATE DATABASE IF NOT EXISTS {DB_NAME};
USE {DB_NAME};

DROP TABLE IF EXISTS HCPCS;

CREATE TABLE HCPCS (
    YEAR INT,
    HCPCS VARCHAR(10),
    MODIFIER VARCHAR(5),
    EFF_DATE DATE,
    INDICATOR CHAR(1),
    RATE DECIMAL(10,2)
);

LOAD DATA LOCAL INFILE '{mysql_path}'
INTO TABLE HCPCS
FIELDS TERMINATED BY '~'
LINES TERMINATED BY '\\n'
IGNORE 1 LINES
(
    YEAR,
    HCPCS,
    MODIFIER,
    @EFF_DATE,
    INDICATOR,
    RATE,
    @SHORTDESC
)
SET EFF_DATE = STR_TO_DATE(@EFF_DATE, '%Y%m%d');

SELECT COUNT(*) AS total_rows FROM HCPCS;
SELECT * FROM HCPCS LIMIT 1000;
"""
    return sql

# =========================
# STEP 7: SAVE SQL
# =========================
def save_sql(sql_text):
    with open(FINAL_SQL_PATH, "w", encoding="utf-8") as f:
        f.write(sql_text)

    print(f"[SUCCESS] SQL file created: {FINAL_SQL_PATH}")

# =========================
# STEP 8: OPEN SQL IN VS CODE
# =========================
def open_in_vscode():
    print("[INFO] Opening SQL file in VS Code...")
    try:
        subprocess.run(["code", FINAL_SQL_PATH], shell=True)
    except Exception as e:
        print(f"[WARNING] Could not open VS Code: {e}")

# =========================
# STEP 9: EXECUTE SQL (FIXED)
# =========================
def execute_sql_file():
    print("[INFO] Executing SQL file properly...")

    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            allow_local_infile=True
        )

        cursor = conn.cursor()
        print("[SUCCESS] Connected to MySQL!")

        with open(FINAL_SQL_PATH, "r", encoding="utf-8") as f:
            sql_script = f.read()

        print("\n[INFO] Running full SQL script...\n")

        for result in cursor.execute(sql_script, multi=True):
            try:
                if result.with_rows:
                    rows = result.fetchall()
                    columns = [col[0] for col in result.description]

                    print("\n" + "="*60)
                    print("📊 RESULT TABLE")
                    print("="*60)

                    if rows:
                        df = pd.DataFrame(rows, columns=columns)
                        print(df.to_string(index=False))
                    else:
                        print("[INFO] No rows returned")

                else:
                    print(f"[SUCCESS] Rows affected: {result.rowcount}")

            except Exception as inner_err:
                print(f"[WARNING] Skipped result: {inner_err}")

        conn.commit()
        print("\n[SUCCESS] SQL execution completed!")

    except Exception as err:
        print(f"[ERROR] {err}")

    finally:
        try:
            cursor.close()
            conn.close()
        except:
            pass

# =========================
# MAIN
# =========================
def main():
    zip_path = get_zip_path()
    accept_and_download(zip_path)

    extract_zip()

    txt_file = get_txt_file()
    print(f"[INFO] Found TXT file: {txt_file}")

    process_file(txt_file)

    sql = generate_sql(txt_file)
    save_sql(sql)

    open_in_vscode()   # optional
    execute_sql_file() # ✅ correct execution

# =========================
# RUN
# =========================
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}")