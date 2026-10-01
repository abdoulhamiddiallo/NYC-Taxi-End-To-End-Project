# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "466a7632-1fdf-4b83-884d-f8b09624affc",
# META       "default_lakehouse_name": "LH_Bronze",
# META       "default_lakehouse_workspace_id": "1930c80d-7715-4f37-b0ee-bbc0aa665783"
# META     }
# META   }
# META }

# MARKDOWN ********************

# # NB_01 · Ingest raw NYC TLC files into the Bronze lakehouse
#
# **Role in the medallion flow**: Source files ➜ **Bronze (raw, immutable)**.
#
# This notebook is called by the orchestration pipeline once per dataset:
#
# | `dataset`   | What is landed                                                     | Parameters used |
# |-------------|--------------------------------------------------------------------|-----------------|
# | `yellow`    | One monthly Yellow Taxi Parquet file, exactly as published by TLC   | `year`, `month` |
# | `reference` | Taxi zone lookup CSV and taxi zone shapefile (zip)                   | none            |
#
# Design principles
#
# * **Immutable landing**: files are stored byte-for-byte as published, under a Hive style path `Files/raw/yellow/year=YYYY/month=MM/`.
# * **Idempotent**: a file already landed with the same size and SHA-256 is skipped unless `force = True`.
# * **Auditable**: every landing writes one row into the Delta table `bronze_ingestion_log` (size, hash, HTTP `Last-Modified`, run id, status).
# * **Resilient**: HTTP download uses streaming with retry and exponential back-off.

# PARAMETERS CELL ********************

dataset = "yellow"        # "yellow" | "reference"
year = 2025
month = 1
force = False             # True = re-download even if the file already exists with the same hash
base_url = "https://d37ci6vzurychx.cloudfront.net"
run_id = ""               # filled by the pipeline (@pipeline().RunId); auto-generated if empty

# CELL ********************

import hashlib, io, json, os, time, uuid, datetime as dt
import requests
from pyspark.sql import Row
from pyspark.sql import functions as F
from pyspark.sql.types import (StructType, StructField, StringType, IntegerType,
                               LongType, TimestampType, BooleanType)

WORKSPACE_ID = "1930c80d-7715-4f37-b0ee-bbc0aa665783"
BRONZE_ID    = "466a7632-1fdf-4b83-884d-f8b09624affc"
BRONZE_ROOT  = f"abfss://{WORKSPACE_ID}@onelake.dfs.fabric.microsoft.com/{BRONZE_ID}"
FILES_ROOT   = f"{BRONZE_ROOT}/Files"
LOG_TABLE    = f"{BRONZE_ROOT}/Tables/bronze_ingestion_log"

run_id = run_id or str(uuid.uuid4())
started_at = dt.datetime.utcnow()
print(f"run_id={run_id}  dataset={dataset}  year={year}  month={month}  force={force}")

# CELL ********************

def build_targets(dataset: str, year: int, month: int):
    """Return the list of (source_url, destination_path, file_name) to land for this call."""
    if dataset == "yellow":
        name = f"yellow_tripdata_{year}-{month:02d}.parquet"
        return [(f"{base_url}/trip-data/{name}",
                 f"{FILES_ROOT}/raw/yellow/year={year}/month={month:02d}/{name}", name)]
    if dataset == "reference":
        return [(f"{base_url}/misc/taxi_zone_lookup.csv", f"{FILES_ROOT}/raw/reference/taxi_zone_lookup.csv", "taxi_zone_lookup.csv"),
                (f"{base_url}/misc/taxi_zones.zip",       f"{FILES_ROOT}/raw/reference/taxi_zones.zip",       "taxi_zones.zip")]
    raise ValueError(f"Unknown dataset '{dataset}' (expected 'yellow' or 'reference')")


def http_head(url: str):
    r = requests.head(url, timeout=60, allow_redirects=True)
    r.raise_for_status()
    return int(r.headers.get("Content-Length", 0)), r.headers.get("Last-Modified", "")


def download_with_retry(url: str, local_path: str, attempts: int = 5) -> tuple[int, str]:
    """Stream the file to local disk; return (bytes, sha256). Retries with exponential back-off."""
    for attempt in range(1, attempts + 1):
        try:
            sha = hashlib.sha256()
            size = 0
            with requests.get(url, stream=True, timeout=300) as r:
                r.raise_for_status()
                with open(local_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                        if chunk:
                            f.write(chunk); sha.update(chunk); size += len(chunk)
            return size, sha.hexdigest()
        except Exception as e:
            if attempt == attempts:
                raise
            wait = 2 ** attempt
            print(f"  attempt {attempt} failed ({e}); retrying in {wait}s")
            time.sleep(wait)


def existing_hash(dest_path: str):
    """SHA-256 of an already landed file, or None if it does not exist."""
    if not notebookutils.fs.exists(dest_path):
        return None, 0
    tmp = f"/tmp/existing_{uuid.uuid4().hex}"
    notebookutils.fs.cp(dest_path, f"file:{tmp}", True)
    sha = hashlib.sha256(); size = 0
    with open(tmp, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            sha.update(chunk); size += len(chunk)
    os.remove(tmp)
    return sha.hexdigest(), size

# CELL ********************

LOG_SCHEMA = StructType([
    StructField("run_id", StringType()), StructField("dataset", StringType()),
    StructField("year", IntegerType()), StructField("month", IntegerType()),
    StructField("file_name", StringType()), StructField("source_url", StringType()),
    StructField("destination_path", StringType()), StructField("bytes", LongType()),
    StructField("sha256", StringType()), StructField("http_last_modified", StringType()),
    StructField("status", StringType()), StructField("message", StringType()),
    StructField("duration_s", IntegerType()), StructField("ingested_at", TimestampType()),
])

log_rows = []
for url, dest, name in build_targets(dataset, year, month):
    t0 = time.time()
    print(f"\n▶ {name}")
    try:
        remote_size, last_modified = http_head(url)
        prev_sha, prev_size = existing_hash(dest)
        if prev_sha and not force and prev_size == remote_size:
            print(f"  already landed ({prev_size:,} bytes, sha256={prev_sha[:12]}…) ➜ skipped")
            log_rows.append(Row(run_id, dataset, int(year), int(month), name, url, dest, int(prev_size), prev_sha,
                                last_modified, "SKIPPED", "identical size already landed", int(time.time() - t0), dt.datetime.utcnow()))
            continue
        local = f"/tmp/{name}"
        size, sha = download_with_retry(url, local)
        if remote_size and size != remote_size:
            raise IOError(f"size mismatch: downloaded {size} bytes, Content-Length {remote_size}")
        notebookutils.fs.mkdirs(os.path.dirname(dest))
        notebookutils.fs.cp(f"file:{local}", dest, True)
        os.remove(local)
        print(f"  landed {size:,} bytes  sha256={sha[:12]}…  ({time.time() - t0:.1f}s)")
        log_rows.append(Row(run_id, dataset, int(year), int(month), name, url, dest, int(size), sha,
                            last_modified, "LANDED", "", int(time.time() - t0), dt.datetime.utcnow()))
    except Exception as e:
        print(f"  FAILED: {e}")
        log_rows.append(Row(run_id, dataset, int(year), int(month), name, url, dest, 0, "",
                            "", "FAILED", str(e)[:1000], int(time.time() - t0), dt.datetime.utcnow()))

log_df = spark.createDataFrame(log_rows, LOG_SCHEMA)
log_df.write.format("delta").mode("append").option("mergeSchema", "true").save(LOG_TABLE)
display(log_df.select("file_name", "status", "bytes", "sha256", "duration_s", "message"))

# CELL ********************

STATUS, MESSAGE = 10, 11   # positional indexes in the log row
failed = [r for r in log_rows if r[STATUS] == "FAILED"]
result = {"run_id": run_id, "dataset": dataset, "year": year, "month": month,
          "landed": sum(1 for r in log_rows if r[STATUS] == "LANDED"),
          "skipped": sum(1 for r in log_rows if r[STATUS] == "SKIPPED"),
          "failed": len(failed)}
print(json.dumps(result))
if failed:
    raise RuntimeError(f"{len(failed)} file(s) failed to land: " + "; ".join(r[MESSAGE] for r in failed))
notebookutils.notebook.exit(json.dumps(result))
