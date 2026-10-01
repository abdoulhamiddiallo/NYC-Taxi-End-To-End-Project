# Runbook

## Daily operations

| Task | How |
|------|-----|
| Load the full year | Run `PL_01_NYC_Taxi_Medallion` with its default parameters (`year` 2025, `months` 1 to 12) |
| Load or replay some months | Run `PL_01` with `months`, for example `[11, 12]`. Each month is idempotent and reconciled |
| Download a month again | Run `PL_01` with `force_download` set to `true` |
| Refresh dimensions and aggregates only | Run `PL_01` with an empty `months` array `[]` |
| Change a stored procedure | Edit `warehouse/02_procedures.sql`, run `python pipelines/gen_pipelines.py`, deploy the pipeline definitions, then run `PL_03_Refresh_Serving_Layer` |
| Change the report | Edit `report/gen_report.py`, run `python tools/sync_notebook.py`, deploy `NB_03_Deploy_Report`, then run `PL_02_Deploy_Report` |
| Check the last run | Pipeline and Quality page of the report, or `SELECT * FROM etl.run_log ORDER BY started_at DESC` in the warehouse |

The org app `NYC Taxi Explorer` reads the live report, so its audience sees a redeployed report at once.

## Before every commit

```bash
python tools/check_repo.py
```

The script regenerates the semantic model, the report, the pipelines and `docs/measures.md`, and fails when a committed
file differs from what the generators produce. It also checks that `NB_03` carries the same report code as
`report/gen_report.py`, that every measure and column used by the report exists in the model, that every visual fits
in its page, and that no file holds an em dash, a CRLF line ending or a personal file path. The same script runs in
GitHub Actions on every push.

## Deploying to a new workspace

1. Create the workspace on a Fabric capacity, then the lakehouses `LH_Bronze` and `LH_Silver` and the warehouse
   `WH_NYC_Taxi`.
2. Put the new ids in `config/fabric.json` (workspace, warehouse, SQL endpoint, lakehouses) and in the constants at the
   top of `NB_01` and `NB_02`.
3. Import the three notebooks from `notebooks/` and attach `LH_Bronze` to `NB_01` and `LH_Silver` to `NB_02` as
   default lakehouses. Put the notebook ids in `config/fabric.json`.
4. Run `python pipelines/gen_pipelines.py` and create the four pipelines from the JSON files, either by pasting each
   definition in the pipeline JSON editor or through the REST API
   (`POST /v1/workspaces/{workspaceId}/items` with a `pipeline-content.json` part).
5. Run `PL_00_Build_Warehouse`, then `PL_01_NYC_Taxi_Medallion`.
6. Run `python semantic-model/gen_model.py` and create `SM_NYC_Taxi` from the payload written to `build/` (REST
   `POST /v1/workspaces/{workspaceId}/semanticModels`).
7. Run `PL_02_Deploy_Report`: `NB_03` finds the semantic model by name and creates `RPT_NYC_Taxi`.
8. Create the org app from New item, Org app, add `RPT_NYC_Taxi`, choose the theme and save.

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| `etl.usp_load_month` fails with error 50010 | The Silver partition of that month is empty. Run `PL_01` for the month with `force_download` set to `true` |
| `etl.usp_load_month` fails with error 50020 | Silver, staging and fact counts differ. The counts are in `etl.load_control`; replay the month |
| The warehouse does not see new Silver rows | The SQL endpoint metadata was not refreshed. `PL_01` runs `NB_02` in `sync` mode for that; run it again |
| A KPI shows an error after a model change | Validate the measure with `EVALUATE ROW("x", [Measure])` in a DAX query before deploying |
| Spark activities queue for a long time | The capacity runs one Spark session at a time; stop idle notebook sessions |
