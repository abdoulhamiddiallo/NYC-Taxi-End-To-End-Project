# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "3f32a7f0-2ffa-4d40-9259-2858d1a630b9",
# META       "default_lakehouse_name": "LH_Silver",
# META       "default_lakehouse_workspace_id": "1930c80d-7715-4f37-b0ee-bbc0aa665783"
# META     }
# META   }
# META }

# MARKDOWN ********************

# # NB_02 · Bronze ➜ Silver: cleanse, conform, enrich
#
# **Role in the medallion flow**: Bronze raw files ➜ **Silver Delta tables** (typed, deduplicated, quality-gated, enriched).
#
# | `mode`      | Output tables                                                            | Parameters used |
# |-------------|--------------------------------------------------------------------------|-----------------|
# | `reference` | `silver_taxi_zones` (lookup CSV + centroid of each zone from the shapefile) | none          |
# | `trips`     | `silver_yellow_trips`, `silver_yellow_trips_rejected`, `silver_dq_log`, `silver_dq_rule_log` | `year`, `month` |
# | `sync`      | no table: forces the metadata sync of the Silver SQL analytics endpoint so the Warehouse sees the latest Delta tables | none |
#
# Engineering choices
#
# * **Schema contract**: every column is cast to an explicit type; columns that TLC adds over time (`cbd_congestion_fee`, `Airport_fee`) are created with `NULL` when absent, so the Silver schema is stable across months.
# * **Quality gate with quarantine**: no silent row drops. Each rule is evaluated for every row; rejected rows are kept in a quarantine table with the list of failed rules, and the counts are logged per rule.
# * **Deterministic surrogate key** `trip_sk` = `year*10^10 + month*10^8 + row number` after a stable sort, so re-running a month produces the same keys.
# * **Idempotent partition overwrite** (`replaceWhere` on `year`/`month`): a month can be re-processed any number of times without duplicates.
# * **Write optimisation**: Optimize Write, V-Order and a post-write `OPTIMIZE ... VORDER` on the partition, for the Warehouse and Direct Lake readers downstream.

# PARAMETERS CELL ********************

mode = "trips"            # "reference" | "trips" | "sync"
year = 2025
month = 1
run_id = ""               # filled by the pipeline (@pipeline().RunId); auto-generated if empty

# CELL ********************

import json, os, time, uuid, datetime as dt
from pyspark.sql import functions as F, Window
from pyspark.sql.types import *

WORKSPACE_ID = "1930c80d-7715-4f37-b0ee-bbc0aa665783"
BRONZE_ID    = "466a7632-1fdf-4b83-884d-f8b09624affc"
SILVER_ID    = "3f32a7f0-2ffa-4d40-9259-2858d1a630b9"
SILVER_SQL_ENDPOINT_ID = "3a3fcb3d-165c-4685-a32b-7ca36bc46812"   # SQL analytics endpoint of LH_Silver
ONELAKE      = "onelake.dfs.fabric.microsoft.com"
BRONZE_FILES = f"abfss://{WORKSPACE_ID}@{ONELAKE}/{BRONZE_ID}/Files"
SILVER_TBL   = f"abfss://{WORKSPACE_ID}@{ONELAKE}/{SILVER_ID}/Tables"

T_TRIPS    = f"{SILVER_TBL}/silver_yellow_trips"
T_REJECTED = f"{SILVER_TBL}/silver_yellow_trips_rejected"
T_ZONES    = f"{SILVER_TBL}/silver_taxi_zones"
T_DQ       = f"{SILVER_TBL}/silver_dq_log"
T_DQ_RULE  = f"{SILVER_TBL}/silver_dq_rule_log"

# Writer optimisations for downstream Warehouse / Direct Lake consumers
spark.conf.set("spark.sql.parquet.vorder.enabled", "true")
spark.conf.set("spark.microsoft.delta.optimizeWrite.enabled", "true")
spark.conf.set("spark.microsoft.delta.optimizeWrite.binSize", "1073741824")
# TLC timestamps are naive local (New York) values: keep the session in UTC so they pass through unchanged
spark.conf.set("spark.sql.session.timeZone", "UTC")

run_id = run_id or str(uuid.uuid4())
t_start = time.time()
print(f"run_id={run_id}  mode={mode}  year={year}  month={month}")

# MARKDOWN ********************

# ### Zone centroids without geospatial libraries
#
# The Fabric Spark runtime ships without `geopandas`/`pyproj`, and inline `pip install` would slow every pipeline run.
# The official `taxi_zones.zip` is an ESRI shapefile in EPSG:2263 (NAD83 / New York Long Island, US survey feet):
# the reader below parses the `.shp`/`.dbf` binary layout with the standard library, computes the area weighted
# centroid of each zone (holes and multi-part zones handled through signed ring areas) and converts it to WGS84
# with the Lambert Conformal Conic (2SP) inverse formulas from the EPSG guidance note 7-2 (validated against pyproj
# to 1e-13 degrees).

# CELL ********************

import math, struct, zipfile
# ---- EPSG:2263 parameters (NAD83 / New York Long Island (ftUS)) ----
_A, _F = 6378137.0, 1 / 298.257222101          # GRS80 ellipsoid
_E = math.sqrt(2 * _F - _F * _F)
_LAT1, _LAT2, _LAT0, _LON0 = map(math.radians, (40.66666666666666, 41.03333333333333, 40.16666666666666, -74.0))
_FT_US = 0.3048006096012192                    # metres per US survey foot
_FE, _FN = 300000.0, 0.0                       # false easting/northing in metres

def _m(lat): return math.cos(lat) / math.sqrt(1 - (_E * math.sin(lat)) ** 2)
def _t(lat): return math.tan(math.pi / 4 - lat / 2) / ((1 - _E * math.sin(lat)) / (1 + _E * math.sin(lat))) ** (_E / 2)
_N = (math.log(_m(_LAT1)) - math.log(_m(_LAT2))) / (math.log(_t(_LAT1)) - math.log(_t(_LAT2)))
_FF = _m(_LAT1) / (_N * _t(_LAT1) ** _N)
_R0 = _A * _FF * _t(_LAT0) ** _N

def to_wgs84(x_ft, y_ft):
    """EPSG:2263 easting/northing in US survey feet -> (latitude, longitude) in decimal degrees."""
    x = x_ft * _FT_US - _FE
    y = y_ft * _FT_US - _FN
    r = math.copysign(math.sqrt(x * x + (_R0 - y) ** 2), _N)
    t = (r / (_A * _FF)) ** (1 / _N)
    theta = math.atan2(x, _R0 - y)
    lon = theta / _N + _LON0
    lat = math.pi / 2 - 2 * math.atan(t)
    for _ in range(8):                         # fixed-point iteration converges in a handful of steps
        lat = math.pi / 2 - 2 * math.atan(t * ((1 - _E * math.sin(lat)) / (1 + _E * math.sin(lat))) ** (_E / 2))
    return math.degrees(lat), math.degrees(lon)

def _ring_area_centroid(pts):
    """Signed area and centroid of a closed ring (shoelace formula)."""
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        cross = x0 * y1 - x1 * y0
        a += cross; cx += (x0 + x1) * cross; cy += (y0 + y1) * cross
    if a == 0: return 0.0, 0.0, 0.0
    return a / 2, cx / (3 * a), cy / (3 * a)

def read_shapefile(shp_bytes):
    """Yields (record_index, [(area, cx, cy) per ring]) for every polygon record of an ESRI .shp file."""
    pos, n = 100, len(shp_bytes)                 # 100-byte file header
    idx = 0
    while pos < n:
        content_len = struct.unpack(">i", shp_bytes[pos + 4:pos + 8])[0] * 2
        rec = shp_bytes[pos + 8:pos + 8 + content_len]
        shape_type = struct.unpack("<i", rec[:4])[0]
        rings = []
        if shape_type in (5, 15, 25):            # Polygon, PolygonZ, PolygonM
            num_parts, num_points = struct.unpack("<ii", rec[36:44])
            parts = struct.unpack(f"<{num_parts}i", rec[44:44 + 4 * num_parts])
            base = 44 + 4 * num_parts
            pts = struct.unpack(f"<{2 * num_points}d", rec[base:base + 16 * num_points])
            xy = list(zip(pts[0::2], pts[1::2]))
            for i, start in enumerate(parts):
                end = parts[i + 1] if i + 1 < num_parts else num_points
                rings.append(_ring_area_centroid(xy[start:end]))
        yield idx, rings
        idx += 1
        pos += 8 + content_len

def read_dbf_column(dbf_bytes, name):
    """Returns the values of one column of an ESRI .dbf file (as stripped strings)."""
    n_rec, hdr_len, rec_len = struct.unpack("<IHH", dbf_bytes[4:12])
    fields, off = [], 32
    while dbf_bytes[off] != 0x0D:
        fname = dbf_bytes[off:off + 11].split(b"\x00")[0].decode("latin-1")
        flen = dbf_bytes[off + 16]
        fields.append((fname, flen)); off += 32
    start = 1                                    # first byte of each record is the deletion flag
    for fname, flen in fields:
        if fname.upper() == name.upper(): break
        start += flen
    else:
        raise KeyError(name)
    return [dbf_bytes[hdr_len + i * rec_len + start: hdr_len + i * rec_len + start + flen].decode("latin-1").strip()
            for i in range(n_rec)]

def zone_centroids(zip_path):
    """{location_id: (latitude, longitude, area_sq_mi)} from the TLC taxi_zones.zip (multi-part zones are area weighted)."""
    with zipfile.ZipFile(zip_path) as z:
        shp = next(n for n in z.namelist() if n.lower().endswith(".shp"))
        dbf = next(n for n in z.namelist() if n.lower().endswith(".dbf"))
        shp_bytes, dbf_bytes = z.read(shp), z.read(dbf)
    ids = read_dbf_column(dbf_bytes, "LocationID")
    out = {}
    for idx, rings in read_shapefile(shp_bytes):
        # outer rings have positive signed area (clockwise in shapefiles gives negative), holes the opposite sign;
        # summing signed contributions gives the net area and the area weighted centroid of the polygon
        area = sum(a for a, _, _ in rings)
        if area == 0: continue
        cx = sum(a * x for a, x, _ in rings) / area
        cy = sum(a * y for a, _, y in rings) / area
        lat, lon = to_wgs84(cx, cy)
        loc = int(ids[idx])
        sq_mi = abs(area) / 27_878_400.0          # square US survey feet per square mile
        if loc in out:                            # a zone split into several records: weight by area
            la, lo, ar = out[loc]
            out[loc] = ((la * ar + lat * sq_mi) / (ar + sq_mi), (lo * ar + lon * sq_mi) / (ar + sq_mi), ar + sq_mi)
        else:
            out[loc] = (lat, lon, sq_mi)
    return {k: (round(v[0], 6), round(v[1], 6), round(v[2], 4)) for k, v in out.items()}

# MARKDOWN ********************

# ## Reference data: taxi zones with centroids

# CELL ********************

def build_reference():
    lookup = (spark.read.option("header", True).csv(f"{BRONZE_FILES}/raw/reference/taxi_zone_lookup.csv")
              .select(F.col("LocationID").cast("int").alias("location_id"),
                      F.trim(F.col("Borough")).alias("borough"),
                      F.trim(F.col("Zone")).alias("zone"),
                      F.trim(F.col("service_zone")).alias("service_zone")))

    # Centroids from the official shapefile (pure Python reader defined above). Optional: the table is still built without them.
    centroids = None
    try:
        local_zip = "/tmp/taxi_zones.zip"
        notebookutils.fs.cp(f"{BRONZE_FILES}/raw/reference/taxi_zones.zip", f"file:{local_zip}", True)
        cen = zone_centroids(local_zip)
        centroids = spark.createDataFrame([(k, v[0], v[1], v[2]) for k, v in cen.items()],
                                          "location_id int, latitude double, longitude double, area_sq_mi double")
        print(f"centroids computed for {len(cen)} zones")
    except Exception as e:
        print(f"centroids unavailable ({e}); continuing without coordinates")

    zones = lookup
    if centroids is not None:
        zones = zones.join(centroids, "location_id", "left")
    else:
        zones = zones.withColumn("latitude", F.lit(None).cast("double")) \
                     .withColumn("longitude", F.lit(None).cast("double")) \
                     .withColumn("area_sq_mi", F.lit(None).cast("double"))

    zones = (zones
             .withColumn("borough", F.when(F.col("borough").isin("Unknown", "N/A") | F.col("borough").isNull(), "Unknown").otherwise(F.col("borough")))
             .withColumn("zone", F.coalesce(F.col("zone"), F.lit("Unknown")))
             .withColumn("service_zone", F.coalesce(F.col("service_zone"), F.lit("N/A")))
             .withColumn("is_airport", F.col("zone").rlike("(?i)airport"))
             .withColumn("latitude", F.col("latitude").cast("double"))
             .withColumn("longitude", F.col("longitude").cast("double"))
             .withColumn("area_sq_mi", F.round(F.col("area_sq_mi").cast("double"), 4))
             .withColumn("updated_at", F.current_timestamp())
             .orderBy("location_id"))
    zones.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(T_ZONES)
    print(f"silver_taxi_zones written: {zones.count()} rows")
    display(zones.limit(10))

if mode == "reference":
    build_reference()
    notebookutils.notebook.exit(json.dumps({"run_id": run_id, "mode": mode, "status": "OK"}))

# CELL ********************

def sync_sql_endpoint(timeout_s: int = 600):
    """Refresh the metadata of the Silver SQL analytics endpoint and wait for it.

    The endpoint discovers new Delta tables lazily; a Warehouse cross-database query issued right after a Spark write
    can otherwise fail with 'Invalid object name'. The refresh is a long running operation, polled here until done."""
    import sempy.fabric as fabric
    client = fabric.FabricRestClient()
    path = f"/v1/workspaces/{WORKSPACE_ID}/sqlEndpoints/{SILVER_SQL_ENDPOINT_ID}/refreshMetadata?preview=true"
    r = client.post(path, json={"timeout": {"timeUnit": "Seconds", "value": 300}})
    t0 = time.time()
    if r.status_code == 202:
        op = r.headers.get("x-ms-operation-id")
        while time.time() - t0 < timeout_s:
            time.sleep(int(r.headers.get("Retry-After", 5)))
            st = client.get(f"/v1/operations/{op}").json()
            if st.get("status") in ("Succeeded", "Failed"):
                break
        if st.get("status") != "Succeeded":
            raise RuntimeError(f"SQL endpoint metadata refresh did not succeed: {st}")
        try:
            tables = client.get(f"/v1/operations/{op}/result").json().get("value", [])
        except Exception:
            tables = []
    else:
        r.raise_for_status()
        tables = r.json().get("value", []) if r.text else []
    bad = [t for t in tables if t.get("status") not in (None, "Success", "NotRun")]
    print(f"SQL endpoint metadata refreshed in {time.time() - t0:.0f}s, {len(tables)} table(s) reported, {len(bad)} with issues")
    for t in tables:
        print(f"  {t.get('tableName')}: {t.get('status')} {t.get('error') or ''}")
    if bad:
        raise RuntimeError("some Silver tables failed to sync: " + ", ".join(t.get("tableName", "?") for t in bad))
    return len(tables)

if mode == "sync":
    n = sync_sql_endpoint()
    notebookutils.notebook.exit(json.dumps({"run_id": run_id, "mode": mode, "status": "OK", "tables": n}))

# MARKDOWN ********************

# ## Trips: schema contract

# CELL ********************

# Explicit contract: (source column, target column, type). Missing source columns are created as NULL.
CONTRACT = [
    ("VendorID",              "vendor_id",              "int"),
    ("tpep_pickup_datetime",  "pickup_datetime",        "timestamp"),
    ("tpep_dropoff_datetime", "dropoff_datetime",       "timestamp"),
    ("passenger_count",       "passenger_count",        "int"),
    ("trip_distance",         "trip_distance",          "double"),
    ("RatecodeID",            "rate_code_id",           "int"),
    ("store_and_fwd_flag",    "store_and_fwd_flag",     "string"),
    ("PULocationID",          "pickup_location_id",     "int"),
    ("DOLocationID",          "dropoff_location_id",    "int"),
    ("payment_type",          "payment_type_id",        "int"),
    ("fare_amount",           "fare_amount",            "double"),
    ("extra",                 "extra",                  "double"),
    ("mta_tax",               "mta_tax",                "double"),
    ("tip_amount",            "tip_amount",             "double"),
    ("tolls_amount",          "tolls_amount",           "double"),
    ("improvement_surcharge", "improvement_surcharge",  "double"),
    ("total_amount",          "total_amount",           "double"),
    ("congestion_surcharge",  "congestion_surcharge",   "double"),
    ("Airport_fee",           "airport_fee",            "double"),
    ("cbd_congestion_fee",    "cbd_congestion_fee",     "double"),
]

src_path = f"{BRONZE_FILES}/raw/yellow/year={year}/month={month:02d}/yellow_tripdata_{year}-{month:02d}.parquet"
raw = spark.read.parquet(src_path)
raw_cols = {c.lower(): c for c in raw.columns}
print("source columns:", raw.columns)

selected = []
for src, dst, typ in CONTRACT:
    actual = raw_cols.get(src.lower())
    selected.append(F.col(actual).cast(typ).alias(dst) if actual else F.lit(None).cast(typ).alias(dst))
typed = raw.select(*selected)
rows_read = typed.count()
print(f"rows read: {rows_read:,}")

# MARKDOWN ********************

# ## Quality gate: rules, quarantine, deterministic keys

# CELL ********************

dedup = typed.dropDuplicates()
rows_dedup = dedup.count()

d = dedup.withColumn("duration_min", (F.unix_timestamp("dropoff_datetime") - F.unix_timestamp("pickup_datetime")) / 60.0)
d = d.withColumn("avg_speed_mph", F.when(F.col("duration_min") > 0, F.col("trip_distance") / (F.col("duration_min") / 60.0)))

# Each rule: name ➜ boolean expression that is TRUE when the row FAILS the rule
RULES = {
    "outside_file_month":  (F.year("pickup_datetime") != year) | (F.month("pickup_datetime") != month),
    "missing_timestamp":   F.col("pickup_datetime").isNull() | F.col("dropoff_datetime").isNull(),
    "invalid_duration":    (F.col("duration_min") < 0) | (F.col("duration_min") > 24 * 60),
    "zero_length_trip":    (F.col("trip_distance") <= 0) & (F.col("duration_min") < 1),
    "invalid_distance":    (F.col("trip_distance") < 0) | (F.col("trip_distance") > 200),
    "negative_amount":     (F.col("fare_amount") < 0) | (F.col("total_amount") < 0) | (F.col("tip_amount") < 0),
    "implausible_fare":    (F.col("total_amount") > 1000) | (F.col("fare_amount") > 1000),
    "implausible_speed":   (F.col("duration_min") >= 1) & (F.col("avg_speed_mph") > 100),
    "missing_location":    F.col("pickup_location_id").isNull() | F.col("dropoff_location_id").isNull(),
    "invalid_passengers":  (F.col("passenger_count") > 9),
}
fails = F.array_compact(F.array(*[F.when(expr, F.lit(name)) for name, expr in RULES.items()]))
d = d.withColumn("failed_rules", fails)

valid    = d.filter(F.size("failed_rules") == 0).drop("failed_rules")
rejected = d.filter(F.size("failed_rules") > 0)

rule_counts = (d.select(F.explode("failed_rules").alias("rule")).groupBy("rule").count().collect())
rule_counts = {r["rule"]: r["count"] for r in rule_counts}

# Deterministic surrogate key: stable sort, then dense row numbering within the month
w = Window.orderBy("pickup_datetime", "dropoff_datetime", "pickup_location_id", "dropoff_location_id",
                   "total_amount", "trip_distance", "vendor_id")
base_key = year * 10_000_000_000 + month * 100_000_000
silver = (valid
    .withColumn("trip_sk", (F.lit(base_key) + F.row_number().over(w)).cast("long"))
    .withColumn("pickup_date", F.to_date("pickup_datetime"))
    .withColumn("pickup_hour", F.hour("pickup_datetime"))
    .withColumn("pickup_minute", F.minute("pickup_datetime"))
    .withColumn("duration_min", F.round("duration_min", 2))
    .withColumn("avg_speed_mph", F.round("avg_speed_mph", 2))
    .withColumn("tip_pct", F.round(F.when(F.col("fare_amount") > 0, 100.0 * F.col("tip_amount") / F.col("fare_amount")), 2))
    .withColumn("total_surcharges", F.round(F.coalesce("extra", F.lit(0.0)) + F.coalesce("mta_tax", F.lit(0.0))
                 + F.coalesce("improvement_surcharge", F.lit(0.0)) + F.coalesce("congestion_surcharge", F.lit(0.0))
                 + F.coalesce("airport_fee", F.lit(0.0)) + F.coalesce("cbd_congestion_fee", F.lit(0.0)), 2))
    .withColumn("is_airport_trip", F.col("pickup_location_id").isin(1, 132, 138) | F.col("dropoff_location_id").isin(1, 132, 138))
    .withColumn("year", F.lit(int(year))).withColumn("month", F.lit(int(month)))
    .withColumn("source_file", F.lit(os.path.basename(src_path)))
    .withColumn("run_id", F.lit(run_id))
    .withColumn("processed_at", F.current_timestamp())
    .select("trip_sk", "vendor_id", "pickup_datetime", "dropoff_datetime", "pickup_date", "pickup_hour", "pickup_minute",
            "passenger_count", "trip_distance", "duration_min", "avg_speed_mph", "rate_code_id", "store_and_fwd_flag",
            "pickup_location_id", "dropoff_location_id", "payment_type_id", "fare_amount", "extra", "mta_tax", "tip_amount",
            "tip_pct", "tolls_amount", "improvement_surcharge", "congestion_surcharge", "airport_fee", "cbd_congestion_fee",
            "total_surcharges", "total_amount", "is_airport_trip", "source_file", "run_id", "processed_at", "year", "month"))

rejected_out = (rejected
    .withColumn("failed_rules", F.concat_ws("|", "failed_rules"))
    .withColumn("year", F.lit(int(year))).withColumn("month", F.lit(int(month)))
    .withColumn("source_file", F.lit(os.path.basename(src_path)))
    .withColumn("run_id", F.lit(run_id))
    .withColumn("processed_at", F.current_timestamp()))

# MARKDOWN ********************

# ## Idempotent writes and layout optimisation

# CELL ********************

where = f"year = {int(year)} AND month = {int(month)}"

(silver.write.format("delta").mode("overwrite")
    .partitionBy("year", "month").option("replaceWhere", where).option("mergeSchema", "true")
    .save(T_TRIPS))
(rejected_out.write.format("delta").mode("overwrite")
    .partitionBy("year", "month").option("replaceWhere", where).option("mergeSchema", "true")
    .save(T_REJECTED))

rows_valid    = spark.read.format("delta").load(T_TRIPS).filter(where).count()
rows_rejected = spark.read.format("delta").load(T_REJECTED).filter(where).count()
assert rows_valid + rows_rejected == rows_dedup, "reconciliation failed: valid + rejected != deduplicated rows"

spark.sql(f"OPTIMIZE delta.`{T_TRIPS}` WHERE {where} VORDER")
spark.sql(f"ALTER TABLE delta.`{T_TRIPS}` SET TBLPROPERTIES ('delta.parquet.vorder.enabled' = 'true', 'delta.autoOptimize.optimizeWrite' = 'true')")

print(f"rows read {rows_read:,} | after dedup {rows_dedup:,} | valid {rows_valid:,} | quarantined {rows_rejected:,} "
      f"({100.0 * rows_rejected / max(rows_dedup, 1):.2f} %)")
print("rule counts:", json.dumps(rule_counts, indent=2))

# MARKDOWN ********************

# ## Data quality log

# CELL ********************

now = dt.datetime.utcnow()
duration_s = int(time.time() - t_start)
dq = spark.createDataFrame([(run_id, int(year), int(month), os.path.basename(src_path), int(rows_read), int(rows_dedup),
                             int(rows_read - rows_dedup), int(rows_valid), int(rows_rejected),
                             float(round(100.0 * rows_rejected / max(rows_dedup, 1), 4)), json.dumps(rule_counts), duration_s, now)],
    "run_id string, year int, month int, source_file string, rows_read long, rows_after_dedup long, exact_duplicates long, "
    "rows_valid long, rows_rejected long, reject_pct double, rule_counts_json string, duration_s int, processed_at timestamp")
dq.write.format("delta").mode("append").option("mergeSchema", "true").save(T_DQ)

rule_rows = [(run_id, int(year), int(month), rule, int(cnt), now) for rule, cnt in rule_counts.items()] or \
            [(run_id, int(year), int(month), "none", 0, now)]
spark.createDataFrame(rule_rows, "run_id string, year int, month int, rule string, rejected_rows long, processed_at timestamp") \
     .write.format("delta").mode("append").option("mergeSchema", "true").save(T_DQ_RULE)

result = {"run_id": run_id, "year": year, "month": month, "rows_read": rows_read, "rows_valid": rows_valid,
          "rows_rejected": rows_rejected, "duration_s": duration_s}
print(json.dumps(result))
notebookutils.notebook.exit(json.dumps(result))
