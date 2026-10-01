"""Generate the four Fabric Data Pipeline definitions (pipeline-content.json) from the SQL files and config/fabric.json."""
import json, re, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG  = json.loads((ROOT / "config" / "fabric.json").read_text(encoding="utf-8"))
OUT  = ROOT / "pipelines"

WS   = CFG["workspace_id"]
WH   = CFG["warehouse_id"]
EP   = CFG["warehouse_sql_endpoint"]
NB01 = CFG["notebooks"]["NB_01_Ingest_Bronze"]
NB02 = CFG["notebooks"]["NB_02_Bronze_To_Silver"]
NB03 = CFG["notebooks"]["NB_03_Deploy_Report"]

POLICY = {"timeout": "0.12:00:00", "retry": 0, "retryIntervalInSeconds": 30, "secureOutput": False, "secureInput": False}
WH_LS  = {"name": "WH_NYC_Taxi", "properties": {"annotations": [], "type": "DataWarehouse",
          "typeProperties": {"endpoint": EP, "artifactId": WH, "workspaceId": WS}}}

def expr(e): return {"value": e, "type": "Expression"}
def dep(*names): return [{"activity": n, "dependencyConditions": ["Succeeded"]} for n in names]

def notebook(name, nb_id, params, depends=(), description=""):
    return {"name": name, "description": description, "type": "TridentNotebook", "dependsOn": dep(*depends), "policy": POLICY,
            "typeProperties": {"notebookId": nb_id, "workspaceId": WS, "parameters": params, "sessionTag": "nyctaxi"}}

SQL_POLICY = {**POLICY, "retry": 2, "retryIntervalInSeconds": 60}

def sproc(name, proc, params, depends=(), description=""):
    return {"name": name, "description": description, "type": "SqlServerStoredProcedure", "dependsOn": dep(*depends), "policy": SQL_POLICY,
            "linkedService": WH_LS, "typeProperties": {"storedProcedureName": proc, "storedProcedureParameters": params}}

def script(name, batches, depends=(), description=""):
    return {"name": name, "description": description, "type": "Script", "dependsOn": dep(*depends), "policy": POLICY,
            "linkedService": WH_LS,
            "typeProperties": {"scripts": [{"type": "NonQuery", "text": b} for b in batches], "scriptBlockExecutionTimeout": "02:00:00"}}

def batches(sql_path):
    text = pathlib.Path(sql_path).read_text(encoding="utf-8")
    parts = re.split(r"^\s*GO\s*$", text, flags=re.M | re.I)
    out = []
    for p in parts:
        # drop pure comment/blank batches
        code = "\n".join(l for l in p.splitlines() if l.strip() and not l.strip().startswith("--"))
        if code.strip():
            out.append(p.strip() + "\n")
    return out

P = lambda name, typ, val: {"value": val, "type": typ}
PX = lambda name, typ, e: {"value": expr(e), "type": typ}

# ---------------------------------------------------------------- PL_00 : warehouse build
b1 = batches(ROOT / "warehouse" / "01_schemas_tables.sql")
b2 = batches(ROOT / "warehouse" / "02_procedures.sql")
pl00 = {"properties": {
    "description": "Builds the Gold warehouse from scratch: schemas, control tables, staging, star schema, aggregates and stored procedures. Existing tables are dropped and recreated, so run PL_01 afterwards.",
    "activities": [
        script("Create schemas and tables", b1, description=f"{len(b1)} T-SQL batches"),
        script("Create stored procedures", b2, depends=("Create schemas and tables",), description=f"{len(b2)} T-SQL batches"),
    ],
    "annotations": []}}

# ---------------------------------------------------------------- PL_01 : medallion run
STATS = [f"IF NOT EXISTS (SELECT 1 FROM sys.stats WHERE name = 'st_fact_trip_{n}') CREATE STATISTICS st_fact_trip_{n} ON fact.fact_trip ({c});\nUPDATE STATISTICS fact.fact_trip (st_fact_trip_{n});\n"
         for n, c in [("date", "date_key"), ("pickup_zone", "pickup_zone_key"), ("dropoff_zone", "dropoff_zone_key"), ("month", "month_number")]]
run_id = "@pipeline().RunId"
pl01 = {"properties": {
    "description": "Metadata-driven medallion run: lands the requested months (parallel), builds Silver, then loads the Gold star schema month by month and rebuilds the aggregates.",
    "parameters": {
        "year":           {"type": "int",   "defaultValue": 2025},
        "months":         {"type": "array", "defaultValue": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]},
        "force_download": {"type": "bool",  "defaultValue": False},
        "parallel_months":{"type": "int",   "defaultValue": 4}
    },
    "activities": [
        notebook("Land reference files", NB01,
                 {"dataset": P("dataset", "string", "reference"), "run_id": PX("run_id", "string", run_id)},
                 description="Taxi zone lookup CSV and shapefile into Bronze"),
        notebook("Build Silver taxi zones", NB02,
                 {"mode": P("mode", "string", "reference"), "run_id": PX("run_id", "string", run_id)},
                 depends=("Land reference files",), description="silver_taxi_zones with centroids"),
        {"name": "For each month - Bronze and Silver", "type": "ForEach", "dependsOn": dep("Build Silver taxi zones"),
         "typeProperties": {
             "items": expr("@pipeline().parameters.months"),
             "isSequential": False,
             "batchCount": 4,
             "activities": [
                 notebook("Land yellow month", NB01,
                          {"dataset": P("dataset", "string", "yellow"),
                           "year": PX("year", "int", "@pipeline().parameters.year"),
                           "month": PX("month", "int", "@item()"),
                           "force": PX("force", "bool", "@pipeline().parameters.force_download"),
                           "run_id": PX("run_id", "string", run_id)},
                          description="One monthly Parquet file into Bronze"),
                 notebook("Silver yellow month", NB02,
                          {"mode": P("mode", "string", "trips"),
                           "year": PX("year", "int", "@pipeline().parameters.year"),
                           "month": PX("month", "int", "@item()"),
                           "run_id": PX("run_id", "string", run_id)},
                          depends=("Land yellow month",), description="Quality gate, keys, Delta partition"),
             ]}},
        notebook("Sync Silver SQL endpoint", NB02,
                 {"mode": P("mode", "string", "sync"), "run_id": PX("run_id", "string", run_id)},
                 depends=("For each month - Bronze and Silver",),
                 description="Forces the metadata refresh of the Silver SQL analytics endpoint before the Warehouse reads it"),
        sproc("Load dimensions", "[etl].[usp_load_dimensions]",
              {"run_id": {"value": expr(run_id), "type": "String"}},
              depends=("Sync Silver SQL endpoint",), description="dim_date, dim_hour, dim_zone, reference dims"),
        {"name": "For each month - Gold", "type": "ForEach", "dependsOn": dep("Load dimensions"),
         "typeProperties": {
             "items": expr("@pipeline().parameters.months"),
             "isSequential": True,
             "activities": [
                 sproc("Load fact month", "[etl].[usp_load_month]",
                       {"year": {"value": expr("@pipeline().parameters.year"), "type": "Int16"},
                        "month": {"value": expr("@item()"), "type": "Int16"},
                        "run_id": {"value": expr(run_id), "type": "String"}},
                       description="Silver to staging to fact_trip, reconciled"),
             ]}},
        sproc("Build aggregates", "[etl].[usp_build_aggregates]",
              {"run_id": {"value": expr(run_id), "type": "String"}},
              depends=("For each month - Gold",), description="Serving aggregates and DQ snapshots"),
        script("Maintain statistics", STATS, depends=("Build aggregates",),
               description="Creates (once) and refreshes optimiser statistics on the fact join keys"),
    ],
    "annotations": []}}

# ---------------------------------------------------------------- PL_02 : report deployment (report as code)
pl02 = {"properties": {
    "description": "Deploys the Power BI report as code: runs NB_03, which generates the PBIR definition and creates or updates RPT_NYC_Taxi bound to SM_NYC_Taxi.",
    "parameters": {
        "report_name":         {"type": "string", "defaultValue": "RPT_NYC_Taxi"},
        "semantic_model_name": {"type": "string", "defaultValue": "SM_NYC_Taxi"},
        "pages":               {"type": "string", "defaultValue": "all"}
    },
    "activities": [
        notebook("Deploy report", NB03,
                 {"report_name": PX("report_name", "string", "@pipeline().parameters.report_name"),
                  "semantic_model_name": PX("semantic_model_name", "string", "@pipeline().parameters.semantic_model_name"),
                  "pages": PX("pages", "string", "@pipeline().parameters.pages")},
                 description="Generates the PBIR parts in Python and pushes them through the Fabric REST API"),
    ],
    "annotations": []}}

# ---------------------------------------------------------------- PL_03 : serving layer refresh (no reload of facts)
pl03 = {"properties": {
    "description": "Redeploys the stored procedures and rebuilds the serving aggregates from the loaded star schema, without touching staging, dimensions or facts.",
    "activities": [
        script("Deploy stored procedures", b2, description=f"{len(b2)} T-SQL batches, CREATE PROCEDURE only"),
        sproc("Build aggregates", "[etl].[usp_build_aggregates]",
              {"run_id": {"value": expr(run_id), "type": "String"}},
              depends=("Deploy stored procedures",), description="Serving aggregates and DQ snapshots"),
    ],
    "annotations": []}}

if __name__ == "__main__":
    for name, obj in [("PL_00_Build_Warehouse", pl00), ("PL_01_NYC_Taxi_Medallion", pl01),
                      ("PL_02_Deploy_Report", pl02), ("PL_03_Refresh_Serving_Layer", pl03)]:
        (OUT / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(name, len(obj["properties"]["activities"]), "activities")
