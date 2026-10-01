"""Generate the Direct Lake semantic model (TMDL) for WH_NYC_Taxi and its base64 API payload (build/)."""
import base64, json, pathlib, uuid

ROOT  = pathlib.Path(__file__).resolve().parent.parent
CFG   = json.loads((ROOT / "config" / "fabric.json").read_text(encoding="utf-8"))
WS    = CFG["workspace_id"]
WH    = CFG["warehouse_id"]
EP    = CFG["warehouse_sql_endpoint"]
OUT   = ROOT / "semantic-model" / "SM_NYC_Taxi.SemanticModel"
BUILD = ROOT / "build"                      # API payloads, not versioned
NS  = uuid.UUID("6f1b0d0e-2c3a-4d5e-9f10-1a2b3c4d5e6f")
def tag(*parts): return str(uuid.uuid5(NS, "|".join(parts)))

# ---------------------------------------------------------------------------------------------
# Table definitions: (model table name, warehouse schema, warehouse table, columns, hidden_all)
# column tuple: (model name, source column, dataType, options dict)
# options: hidden, key, fmt, sortBy, cat (dataCategory), summarize, desc
# ---------------------------------------------------------------------------------------------
I, S, DT, DEC, DBL, B = "int64", "string", "dateTime", "decimal", "double", "boolean"

TABLES = [
 ("Date", "dim", "dim_date", [
    ("date_key", "date_key", I, dict(hidden=True, key=True)),
    ("Date", "full_date", DT, dict(fmt="d MMM yyyy", desc="Calendar date of pickup")),
    ("Year", "year_number", I, dict(fmt="0")),
    ("Quarter", "quarter_label", S, {}),
    ("Quarter Number", "quarter_number", I, dict(hidden=True)),
    ("Month Number", "month_number", I, dict(hidden=True)),
    ("Month", "month_name", S, dict(sortBy="Month Number")),
    ("Mon", "month_short", S, dict(sortBy="Month Number")),
    ("Year Month", "year_month", S, dict(hidden=True)),
    ("Month Label", "month_label", S, dict(sortBy="Year Month", desc="Jan 2025 style label")),
    ("Month Start", "month_start", DT, dict(hidden=True, fmt="d MMM yyyy")),
    ("Day", "day_of_month", I, dict(fmt="0")),
    ("Day of Week", "day_of_week", I, dict(hidden=True)),
    ("Day Name", "day_name", S, dict(sortBy="Day of Week")),
    ("Day Short", "day_short", S, dict(sortBy="Day of Week")),
    ("Is Weekend", "is_weekend", B, {}),
    ("Week", "week_of_year", I, dict(fmt="0")),
    ("Day of Year", "day_of_year", I, dict(hidden=True)),
    ("Is Holiday", "is_holiday", B, {}),
    ("Holiday", "holiday_name", S, {}),
    ("Season", "season", S, {}),
    ("Day Type", "day_type", S, dict(desc="Weekday, Weekend or Holiday")),
 ], False),
 ("Hour", "dim", "dim_hour", [
    ("hour_key", "hour_key", I, dict(hidden=True, key=True)),
    ("Hour", "hour_label", S, dict(sortBy="hour_key")),
    ("Hour 12", "hour_12", S, dict(sortBy="hour_key")),
    ("Day Part", "day_part", S, dict(sortBy="Day Part Order")),
    ("Day Part Order", "day_part_order", I, dict(hidden=True)),
    ("Is Rush Hour", "is_rush_hour", B, {}),
 ], False),
 ("Pickup Zone", "dim", "dim_zone", [
    ("zone_key", "zone_key", I, dict(hidden=True, key=True)),
    ("Pickup Zone", "zone_name", S, {}),
    ("Pickup Borough", "borough", S, {}),
    ("Pickup Service Zone", "service_zone", S, {}),
    ("Pickup Zone (Borough)", "zone_full_name", S, {}),
    ("Pickup Is Airport", "is_airport", B, {}),
    ("Pickup Latitude", "latitude", DBL, dict(cat="Latitude", summarize="none", hidden=True)),
    ("Pickup Longitude", "longitude", DBL, dict(cat="Longitude", summarize="none", hidden=True)),
    ("Pickup Area sq mi", "area_sq_mi", DBL, dict(hidden=True)),
 ], False),
 ("Dropoff Zone", "dim", "dim_zone", [
    ("zone_key", "zone_key", I, dict(hidden=True, key=True)),
    ("Dropoff Zone", "zone_name", S, {}),
    ("Dropoff Borough", "borough", S, {}),
    ("Dropoff Service Zone", "service_zone", S, {}),
    ("Dropoff Zone (Borough)", "zone_full_name", S, {}),
    ("Dropoff Is Airport", "is_airport", B, {}),
    ("Dropoff Latitude", "latitude", DBL, dict(cat="Latitude", summarize="none", hidden=True)),
    ("Dropoff Longitude", "longitude", DBL, dict(cat="Longitude", summarize="none", hidden=True)),
 ], False),
 ("Vendor", "dim", "dim_vendor", [
    ("vendor_key", "vendor_key", I, dict(hidden=True, key=True)),
    ("Vendor", "vendor_name", S, {}),
 ], False),
 ("Rate Code", "dim", "dim_rate_code", [
    ("rate_code_key", "rate_code_key", I, dict(hidden=True, key=True)),
    ("Rate Code", "rate_code_name", S, dict(sortBy="rate_code_key")),
 ], False),
 ("Payment Type", "dim", "dim_payment_type", [
    ("payment_type_key", "payment_type_key", I, dict(hidden=True, key=True)),
    ("Payment Type", "payment_type_name", S, dict(sortBy="payment_type_key")),
    ("Is Electronic", "is_electronic", B, {}),
 ], False),
 ("Distance Band", "dim", "dim_distance_band", [
    ("distance_band_key", "distance_band_key", I, dict(hidden=True, key=True)),
    ("Distance Band", "distance_band", S, dict(sortBy="distance_band_key")),
    ("Min Miles", "min_miles", DEC, dict(hidden=True)),
    ("Max Miles", "max_miles", DEC, dict(hidden=True)),
 ], False),
 ("Trips", "fact", "fact_trip", [
    ("trip_sk", "trip_sk", I, dict(key=True)),
    ("date_key", "date_key", I, {}), ("hour_key", "hour_key", I, {}),
    ("pickup_zone_key", "pickup_zone_key", I, {}), ("dropoff_zone_key", "dropoff_zone_key", I, {}),
    ("vendor_key", "vendor_key", I, {}), ("rate_code_key", "rate_code_key", I, {}),
    ("payment_type_key", "payment_type_key", I, {}), ("distance_band_key", "distance_band_key", I, {}),
    ("pickup_datetime", "pickup_datetime", DT, {}), ("dropoff_datetime", "dropoff_datetime", DT, {}),
    ("passenger_count", "passenger_count", I, {}), ("trip_distance", "trip_distance", DEC, {}),
    ("duration_min", "duration_min", DEC, {}), ("avg_speed_mph", "avg_speed_mph", DEC, {}),
    ("fare_amount", "fare_amount", DEC, {}), ("extra", "extra", DEC, {}), ("mta_tax", "mta_tax", DEC, {}),
    ("tip_amount", "tip_amount", DEC, {}), ("tolls_amount", "tolls_amount", DEC, {}),
    ("improvement_surcharge", "improvement_surcharge", DEC, {}), ("congestion_surcharge", "congestion_surcharge", DEC, {}),
    ("airport_fee", "airport_fee", DEC, {}), ("cbd_congestion_fee", "cbd_congestion_fee", DEC, {}),
    ("total_surcharges", "total_surcharges", DEC, {}), ("total_amount", "total_amount", DEC, {}),
    ("is_airport_trip", "is_airport_trip", B, {}), ("is_tipped", "is_tipped", B, {}),
    ("year_number", "year_number", I, {}), ("month_number", "month_number", I, {}),
 ], True),
 ("Zone Flow", "agg", "zone_flow", [
    ("pickup_zone_key", "pickup_zone_key", I, dict(hidden=True)), ("dropoff_zone_key", "dropoff_zone_key", I, dict(hidden=True)),
    ("Flow Trips", "trips", I, dict(fmt="#,0")), ("Flow Revenue", "revenue", DEC, dict(fmt="$#,0")),
    ("Flow Avg Fare", "avg_fare", DEC, dict(fmt="$#,0.00", summarize="average")),
    ("Flow Avg Distance", "avg_distance", DEC, dict(fmt="#,0.0", summarize="average")),
    ("Flow Avg Duration", "avg_duration", DEC, dict(fmt="#,0.0", summarize="average")),
    ("Flow Rank", "flow_rank", I, dict(fmt="0", summarize="none")),
 ], False),
 ("Demand Profile", "agg", "hourly_weekday", [
    ("Weekday Number", "day_of_week", I, dict(hidden=True)), ("Weekday", "day_short", S, dict(sortBy="Weekday Number")),
    ("Hour Number", "hour_key", I, dict(hidden=True)), ("Hour Slot", "hour_label", S, dict(sortBy="Hour Number")),
    ("Slot Trips", "trips", I, dict(fmt="#,0")), ("Trips per Slot", "trips_per_slot", DEC, dict(fmt="#,0")),
    ("Slot Revenue", "revenue", DEC, dict(fmt="$#,0")), ("Slot Avg Fare", "avg_fare", DEC, dict(fmt="$#,0.00", summarize="average")),
    ("Slot Avg Duration", "avg_duration", DEC, dict(fmt="#,0.0", summarize="average")),
    ("Slot Avg Speed", "avg_speed_mph", DEC, dict(fmt="#,0.0", summarize="average")),
 ], False),
 ("Data Quality", "agg", "dq_month", [
    ("DQ Year", "year_number", I, dict(hidden=True)), ("DQ Month Number", "month_number", I, dict(hidden=True)),
    ("DQ Month", "year_month", S, {}), ("Source File", "source_file", S, {}),
    ("Rows Read", "rows_read", I, dict(fmt="#,0")), ("Exact Duplicates", "exact_duplicates", I, dict(fmt="#,0")),
    ("Rows Valid", "rows_valid", I, dict(fmt="#,0")), ("Rows Rejected", "rows_rejected", I, dict(fmt="#,0")),
    ("Reject Pct", "reject_pct", DEC, dict(fmt="0.00", summarize="average")),
    ("Silver Seconds", "silver_duration_s", I, dict(fmt="#,0")), ("Processed At", "processed_at", DT, dict(fmt="d MMM yyyy HH:mm")),
    ("DQ Run", "run_id", S, dict(hidden=True)),
 ], False),
 ("Data Quality Rules", "agg", "dq_rule_month", [
    ("Rule Year", "year_number", I, dict(hidden=True)), ("Rule Month Number", "month_number", I, dict(hidden=True)),
    ("Rule Month", "year_month", S, {}), ("Rule", "rule_name", S, dict(hidden=True)), ("Rule Label", "rule_label", S, {}),
    ("Rule Rejected Rows", "rejected_rows", I, dict(fmt="#,0")),
 ], False),
 ("Load Control", "etl", "load_control", [
    ("Load Year", "year_number", I, dict(hidden=True)), ("Load Month Number", "month_number", I, dict(fmt="0", summarize="none")),
    ("Silver Rows", "silver_rows", I, dict(fmt="#,0")), ("Staged Rows", "staged_rows", I, dict(fmt="#,0")),
    ("Fact Rows", "fact_rows", I, dict(fmt="#,0")), ("Is Reconciled", "is_reconciled", B, {}),
    ("Load Run", "last_run_id", S, dict(hidden=True)), ("Loaded At", "last_loaded_at", DT, dict(fmt="d MMM yyyy HH:mm")),
 ], False),
 ("Run Log", "etl", "run_log", [
    ("log_id", "log_id", I, dict(hidden=True, key=True)), ("Run", "run_id", S, {}), ("Step", "step_name", S, {}),
    ("Status", "status", S, {}), ("Started", "started_at", DT, dict(fmt="d MMM HH:mm:ss")), ("Ended", "ended_at", DT, dict(fmt="d MMM HH:mm:ss")),
    ("Rows Affected", "rows_affected", I, dict(fmt="#,0")), ("Message", "message", S, {}),
 ], False),
]

RELS = [  # (from table, from col, to table, to col, active)
 ("Trips", "date_key", "Date", "date_key", True),
 ("Trips", "hour_key", "Hour", "hour_key", True),
 ("Trips", "pickup_zone_key", "Pickup Zone", "zone_key", True),
 ("Trips", "dropoff_zone_key", "Dropoff Zone", "zone_key", True),
 ("Trips", "vendor_key", "Vendor", "vendor_key", True),
 ("Trips", "rate_code_key", "Rate Code", "rate_code_key", True),
 ("Trips", "payment_type_key", "Payment Type", "payment_type_key", True),
 ("Trips", "distance_band_key", "Distance Band", "distance_band_key", True),
 ("Zone Flow", "pickup_zone_key", "Pickup Zone", "zone_key", True),
 ("Zone Flow", "dropoff_zone_key", "Dropoff Zone", "zone_key", True),
 ("Data Quality Rules", "Rule Month", "Data Quality", "DQ Month", True),
]

# ---------------------------------------------------------------------------------------------
# Measures (table Trips) : (name, dax, format, folder, description)
# ---------------------------------------------------------------------------------------------
M = []
def m(name, dax, fmt="#,0", folder="Core", desc=""): M.append((name, dax, fmt, folder, desc))
m("Trips", "COUNTROWS ( Trips )", "#,0", "Core", "Number of valid yellow taxi trips")
m("Revenue", "SUM ( Trips[total_amount] )", "$#,0", "Core", "Total amount charged to passengers, including fare, tips, tolls and surcharges")
m("Fare Revenue", "SUM ( Trips[fare_amount] )", "$#,0", "Core")
m("Tips", "SUM ( Trips[tip_amount] )", "$#,0", "Core")
m("Tolls", "SUM ( Trips[tolls_amount] )", "$#,0", "Core")
m("Surcharges", "SUM ( Trips[total_surcharges] )", "$#,0", "Core")
m("Congestion Surcharge", "SUM ( Trips[congestion_surcharge] )", "$#,0", "Fees")
m("CBD Congestion Fee", "SUM ( Trips[cbd_congestion_fee] )", "$#,0", "Fees", "Manhattan congestion relief zone fee, in force since 5 January 2025")
m("Airport Fee", "SUM ( Trips[airport_fee] )", "$#,0", "Fees")
m("MTA Tax", "SUM ( Trips[mta_tax] )", "$#,0", "Fees")
m("Improvement Surcharge", "SUM ( Trips[improvement_surcharge] )", "$#,0", "Fees")
m("Extras", "SUM ( Trips[extra] )", "$#,0", "Fees")
m("Passengers", "SUM ( Trips[passenger_count] )", "#,0", "Core")
m("Miles", "SUM ( Trips[trip_distance] )", "#,0", "Core")
m("Minutes", "SUM ( Trips[duration_min] )", "#,0", "Core")
m("Hours on Meter", "[Minutes] / 60", "#,0", "Core")
m("Avg Fare", "AVERAGE ( Trips[fare_amount] )", "$#,0.00", "Averages")
m("Avg Total", "AVERAGE ( Trips[total_amount] )", "$#,0.00", "Averages")
m("Avg Tip", "AVERAGE ( Trips[tip_amount] )", "$#,0.00", "Averages")
m("Avg Distance", "AVERAGE ( Trips[trip_distance] )", "#,0.00", "Averages", "Average trip distance in miles")
m("Avg Duration", "AVERAGE ( Trips[duration_min] )", "#,0.0", "Averages", "Average trip duration in minutes")
m("Avg Speed", "AVERAGE ( Trips[avg_speed_mph] )", "#,0.0", "Averages", "Average trip speed in mph")
m("Avg Passengers", "AVERAGE ( Trips[passenger_count] )", "#,0.00", "Averages")
m("Revenue per Mile", "DIVIDE ( [Revenue], [Miles] )", "$#,0.00", "Averages")
m("Revenue per Minute", "DIVIDE ( [Revenue], [Minutes] )", "$#,0.00", "Averages")
m("Revenue per Trip", "DIVIDE ( [Revenue], [Trips] )", "$#,0.00", "Averages")
m("Card Trips", "CALCULATE ( [Trips], Trips[payment_type_key] = 1 )", "#,0", "Payments")
m("Cash Trips", "CALCULATE ( [Trips], Trips[payment_type_key] = 2 )", "#,0", "Payments")
m("Card Share", "DIVIDE ( [Card Trips], [Trips] )", "0.0%", "Payments")
m("Cash Share", "DIVIDE ( [Cash Trips], [Trips] )", "0.0%", "Payments")
m("Card Tips", "CALCULATE ( SUM ( Trips[tip_amount] ), Trips[payment_type_key] = 1 )", "$#,0", "Payments")
m("Card Fares", "CALCULATE ( SUM ( Trips[fare_amount] ), Trips[payment_type_key] = 1 )", "$#,0", "Payments")
m("Tip Rate", "DIVIDE ( [Card Tips], [Card Fares] )", "0.0%", "Payments", "Tips as a share of fares on card payments (cash tips are not recorded)")
m("Tipped Trips", "CALCULATE ( [Trips], Trips[is_tipped] = TRUE () )", "#,0", "Payments")
m("Tipped Share", "DIVIDE ( [Tipped Trips], [Card Trips] )", "0.0%", "Payments", "Share of card trips with a tip")
m("Airport Trips", "CALCULATE ( [Trips], Trips[is_airport_trip] = TRUE () )", "#,0", "Airports")
m("Airport Share", "DIVIDE ( [Airport Trips], [Trips] )", "0.0%", "Airports")
m("Airport Revenue", "CALCULATE ( [Revenue], Trips[is_airport_trip] = TRUE () )", "$#,0", "Airports")
m("Days", "CALCULATE ( DISTINCTCOUNT ( Trips[date_key] ) )", "#,0", "Time")
m("Trips per Day", "DIVIDE ( [Trips], [Days] )", "#,0", "Time")
m("Revenue per Day", "DIVIDE ( [Revenue], [Days] )", "$#,0", "Time")
m("Trips per Hour of Day", "DIVIDE ( [Trips], [Days] * 24 )", "#,0", "Time")
m("Trips PM", "CALCULATE ( [Trips], DATEADD ( 'Date'[Date], -1, MONTH ) )", "#,0", "Time", "Trips in the previous month")
m("Trips MoM", "VAR pm = [Trips PM] RETURN IF ( pm > 0, DIVIDE ( [Trips] - pm, pm ) )", "+0.0%;-0.0%;0.0%", "Time")
m("Revenue PM", "CALCULATE ( [Revenue], DATEADD ( 'Date'[Date], -1, MONTH ) )", "$#,0", "Time")
m("Revenue MoM", "VAR pm = [Revenue PM] RETURN IF ( pm > 0, DIVIDE ( [Revenue] - pm, pm ) )", "+0.0%;-0.0%;0.0%", "Time")
m("Avg Fare PM", "CALCULATE ( [Avg Fare], DATEADD ( 'Date'[Date], -1, MONTH ) )", "$#,0.00", "Time")
m("Avg Fare MoM", "VAR pm = [Avg Fare PM] RETURN IF ( pm > 0, DIVIDE ( [Avg Fare] - pm, pm ) )", "+0.0%;-0.0%;0.0%", "Time")
m("Trips YTD", "CALCULATE ( [Trips], DATESYTD ( 'Date'[Date] ) )", "#,0", "Time")
m("Revenue YTD", "CALCULATE ( [Revenue], DATESYTD ( 'Date'[Date] ) )", "$#,0", "Time")
m("Weekend Trips", "CALCULATE ( [Trips], 'Date'[Is Weekend] = TRUE () )", "#,0", "Time")
m("Weekend Share", "DIVIDE ( [Weekend Trips], [Trips] )", "0.0%", "Time")
m("Rush Hour Trips", "CALCULATE ( [Trips], 'Hour'[Is Rush Hour] = TRUE () )", "#,0", "Time")
m("Rush Hour Share", "DIVIDE ( [Rush Hour Trips], [Trips] )", "0.0%", "Time")
m("Trips Share", "DIVIDE ( [Trips], CALCULATE ( [Trips], REMOVEFILTERS ( 'Pickup Zone' ), REMOVEFILTERS ( 'Dropoff Zone' ), REMOVEFILTERS ( 'Payment Type' ), REMOVEFILTERS ( 'Distance Band' ), REMOVEFILTERS ( 'Hour' ), REMOVEFILTERS ( 'Vendor' ), REMOVEFILTERS ( 'Rate Code' ) ) )", "0.0%", "Shares", "Share of trips against all zones, hours, payments and vendors in the selected period")
m("Revenue Share", "DIVIDE ( [Revenue], CALCULATE ( [Revenue], REMOVEFILTERS ( 'Pickup Zone' ), REMOVEFILTERS ( 'Dropoff Zone' ), REMOVEFILTERS ( 'Payment Type' ), REMOVEFILTERS ( 'Distance Band' ), REMOVEFILTERS ( 'Hour' ), REMOVEFILTERS ( 'Vendor' ), REMOVEFILTERS ( 'Rate Code' ) ) )", "0.0%", "Shares")
m("Pickup Zone Rank", "IF ( HASONEVALUE ( 'Pickup Zone'[Pickup Zone] ), RANKX ( ALL ( 'Pickup Zone'[Pickup Zone] ), [Trips], , DESC, DENSE ) )", "0", "Shares")
m("Dropoff Zone Rank", "IF ( HASONEVALUE ( 'Dropoff Zone'[Dropoff Zone] ), RANKX ( ALL ( 'Dropoff Zone'[Dropoff Zone] ), [Trips], , DESC, DENSE ) )", "0", "Shares")
m("Peak Hour", "VAR t = TOPN ( 1, ALLSELECTED ( 'Hour'[Hour] ), [Trips], DESC ) RETURN MAXX ( t, 'Hour'[Hour] )", "", "Labels", "Hour of day with the most pickups")
m("Busiest Day", "VAR t = TOPN ( 1, ALLSELECTED ( 'Date'[Day Name] ), [Trips], DESC ) RETURN MAXX ( t, 'Date'[Day Name] )", "", "Labels")
m("Top Pickup Zone", "VAR t = TOPN ( 1, ALLSELECTED ( 'Pickup Zone'[Pickup Zone] ), [Trips], DESC ) RETURN MAXX ( t, 'Pickup Zone'[Pickup Zone] )", "", "Labels")
m("Top Dropoff Zone", "VAR t = TOPN ( 1, ALLSELECTED ( 'Dropoff Zone'[Dropoff Zone] ), [Trips], DESC ) RETURN MAXX ( t, 'Dropoff Zone'[Dropoff Zone] )", "", "Labels")
m("Top Borough", "VAR t = TOPN ( 1, ALLSELECTED ( 'Pickup Zone'[Pickup Borough] ), [Trips], DESC ) RETURN MAXX ( t, 'Pickup Zone'[Pickup Borough] )", "", "Labels")
m("Period Label", "VAR d1 = MIN ( 'Date'[Date] ) VAR d2 = MAX ( 'Date'[Date] ) RETURN IF ( ISBLANK ( d1 ), \"\", FORMAT ( d1, \"d MMM yyyy\" ) & \"  to  \" & FORMAT ( d2, \"d MMM yyyy\" ) )", "", "Labels")
m("Trips Label", "FORMAT ( [Trips], \"#,0\" ) & \" trips\"", "", "Labels")
m("Trips per Day Label", "FORMAT ( [Trips per Day], \"#,0\" ) & \" trips per day\"", "", "Labels")
m("Revenue per Day Label", "FORMAT ( [Revenue per Day], \"$#,0\" ) & \" per day\"", "", "Labels")
m("Avg Distance Label", "FORMAT ( [Avg Distance], \"0.0\" ) & \" mi  ·  \" & FORMAT ( [Avg Speed], \"0.0\" ) & \" mph\"", "", "Labels")
m("Avg Duration Label", "FORMAT ( [Avg Duration], \"0.0\" ) & \" min per trip\"", "", "Labels")
m("Tip Rate Label", "FORMAT ( [Tipped Share], \"0%\" ) & \" of card trips tip\"", "", "Labels")
m("Card Share Label", "FORMAT ( [Card Share], \"0%\" ) & \" by card\"", "", "Labels")
m("Airport Label", "FORMAT ( [Airport Share], \"0.0%\" ) & \" of trips\"", "", "Labels")
m("Trips MoM Label", "VAR v = [Trips MoM] RETURN IF ( ISBLANK ( v ), \"first month\", FORMAT ( v, \"+0.0%;-0.0%;0.0%\" ) & \" vs previous month\" )", "", "Labels")
m("Revenue MoM Label", "VAR v = [Revenue MoM] RETURN IF ( NOT HASONEVALUE ( 'Date'[Year Month] ), [Revenue per Day Label], IF ( ISBLANK ( v ), \"first month of the data\", FORMAT ( v, \"+0.0%;-0.0%;0.0%\" ) & \" vs previous month\" ) )", "", "Labels", "Month over month change when one month is selected, revenue per day otherwise")
m("Avg Fare MoM Label", "VAR v = [Avg Fare MoM] RETURN IF ( NOT HASONEVALUE ( 'Date'[Year Month] ), FORMAT ( [Avg Total], \"$0.00\" ) & \" paid in total per trip\", IF ( ISBLANK ( v ), \"first month of the data\", FORMAT ( v, \"+0.0%;-0.0%;0.0%\" ) & \" vs previous month\" ) )", "", "Labels", "Month over month change when one month is selected, average total paid otherwise")
# KPI context lines: one specific fact under each KPI card (no repeated sentence across a page)
m("Fare and Tip Label", "FORMAT ( [Avg Fare], \"$0.00\" ) & \" fare  ·  \" & FORMAT ( [Avg Tip], \"$0.00\" ) & \" tip\"", "", "Labels")
m("Miles Label", "FORMAT ( [Miles] / 1000000, \"0.0\" ) & \"M miles on the meter\"", "", "Labels")
m("Hours Label", "FORMAT ( [Hours on Meter] / 1000000, \"0.0\" ) & \"M hours on the meter\"", "", "Labels")
m("Cash Share Label", "FORMAT ( [Cash Share], \"0.0%\" ) & \" paid in cash\"", "", "Labels")
m("CBD Fee per Trip Label", "FORMAT ( DIVIDE ( [CBD Congestion Fee], [Trips] ), \"$0.00\" ) & \" per trip on average\"", "", "Labels")
m("Airport Revenue Label", "FORMAT ( DIVIDE ( [Airport Revenue], [Revenue] ), \"0.0%\" ) & \" of revenue\"", "", "Labels")
m("Top Pickup Zone Label", "VAR t = TOPN ( 1, ALLSELECTED ( 'Pickup Zone'[Pickup Zone] ), [Trips], DESC ) RETURN FORMAT ( MAXX ( t, [Trips] ), \"#,0\" ) & \" pickups\"", "", "Labels")
m("Top Dropoff Zone Label", "VAR t = TOPN ( 1, ALLSELECTED ( 'Dropoff Zone'[Dropoff Zone] ), [Trips], DESC ) RETURN FORMAT ( MAXX ( t, [Trips] ), \"#,0\" ) & \" dropoffs\"", "", "Labels")
m("Top Borough Label", "VAR t = TOPN ( 1, ALLSELECTED ( 'Pickup Zone'[Pickup Borough] ), [Trips], DESC ) RETURN FORMAT ( DIVIDE ( MAXX ( t, [Trips] ), [Trips] ), \"0.0%\" ) & \" of pickups\"", "", "Labels")
m("Peak Hour Label", "VAR t = TOPN ( 1, ALLSELECTED ( 'Hour'[Hour] ), [Trips], DESC ) RETURN FORMAT ( MAXX ( t, [Trips per Day] ), \"#,0\" ) & \" pickups per day\"", "", "Labels")
m("Busiest Day Label", "VAR t = TOPN ( 1, ALLSELECTED ( 'Date'[Day Name] ), [Trips], DESC ) RETURN FORMAT ( MAXX ( t, [Trips per Day] ), \"#,0\" ) & \" trips per day\"", "", "Labels")
m("Rush Hour Label", "\"7 to 10 am and 4 to 7 pm\"", "", "Labels")
m("Weekend Trips Label", "FORMAT ( [Weekend Trips], \"#,0\" ) & \" weekend trips\"", "", "Labels")
m("Files Label", "FORMAT ( [DQ Months], \"0\" ) & \" monthly Parquet files\"", "", "Quality")
m("Accepted Label", "FORMAT ( DIVIDE ( [DQ Rows Valid], [DQ Rows Read] ), \"0.0%\" ) & \" of the rows read\"", "", "Quality")
m("Quarantine Label", "\"kept with their failed rules\"", "", "Quality")
m("Top Rule Label", "VAR t = TOPN ( 1, ALL ( 'Data Quality Rules'[Rule Label] ), [DQ Rule Rows], DESC ) RETURN \"Top: \" & MAXX ( t, 'Data Quality Rules'[Rule Label] )", "", "Quality")
m("Duplicates Label", "\"dropped before the rules run\"", "", "Quality")
m("Step Recency", "VAR cur = MAX ( 'Run Log'[Started] ) RETURN IF ( NOT ISBLANK ( cur ), COUNTROWS ( FILTER ( ALL ( 'Run Log'[Started] ), 'Run Log'[Started] >= cur ) ) )", "0", "Quality", "1 for the most recent run log step, 2 for the one before, and so on")
# Data quality and ops measures
m("DQ Rows Read", "SUM ( 'Data Quality'[Rows Read] )", "#,0", "Quality")
m("DQ Rows Valid", "SUM ( 'Data Quality'[Rows Valid] )", "#,0", "Quality")
m("DQ Rows Rejected", "SUM ( 'Data Quality'[Rows Rejected] )", "#,0", "Quality")
m("DQ Duplicates", "SUM ( 'Data Quality'[Exact Duplicates] )", "#,0", "Quality")
m("DQ Reject Rate", "DIVIDE ( [DQ Rows Rejected], [DQ Rows Valid] + [DQ Rows Rejected] )", "0.00%", "Quality")
m("DQ Months", "DISTINCTCOUNT ( 'Data Quality'[DQ Month] )", "0", "Quality")
m("DQ Rule Rows", "SUM ( 'Data Quality Rules'[Rule Rejected Rows] )", "#,0", "Quality")
m("DQ Rule Share", "DIVIDE ( [DQ Rule Rows], CALCULATE ( [DQ Rule Rows], REMOVEFILTERS ( 'Data Quality Rules'[Rule Label] ) ) )", "0.0%", "Quality")
m("Silver Minutes", "DIVIDE ( SUM ( 'Data Quality'[Silver Seconds] ), 60 )", "#,0.0", "Quality")
m("Months Loaded", "COUNTROWS ( 'Load Control' )", "0", "Quality")
m("Months Reconciled", "CALCULATE ( COUNTROWS ( 'Load Control' ), 'Load Control'[Is Reconciled] = TRUE () )", "0", "Quality")
m("Reconciliation Label", "FORMAT ( [Months Reconciled], \"0\" ) & \" of \" & FORMAT ( [Months Loaded], \"0\" ) & \" months reconciled\"", "", "Quality")
m("Fact Rows Loaded", "SUM ( 'Load Control'[Fact Rows] )", "#,0", "Quality")
m("Run Steps", "COUNTROWS ( 'Run Log' )", "#,0", "Quality")
m("Failed Steps", "CALCULATE ( COUNTROWS ( 'Run Log' ), 'Run Log'[Status] = \"FAILED\" )", "#,0", "Quality")
m("Step Seconds", "SUMX ( 'Run Log', DATEDIFF ( 'Run Log'[Started], 'Run Log'[Ended], SECOND ) )", "#,0", "Quality")
m("Last Load", "MAX ( 'Load Control'[Loaded At] )", "d MMM yyyy HH:mm", "Quality")
# Demand profile measures
m("Profile Trips", "SUM ( 'Demand Profile'[Slot Trips] )", "#,0", "Profile")
m("Profile Trips per Slot", "SUM ( 'Demand Profile'[Trips per Slot] )", "#,0", "Profile", "Average pickups in one weekday hour slot across the year")
m("Profile Avg Speed", "AVERAGE ( 'Demand Profile'[Slot Avg Speed] )", "#,0.0", "Profile")
m("Profile Avg Fare", "AVERAGE ( 'Demand Profile'[Slot Avg Fare] )", "$#,0.00", "Profile")
# Flow measures
m("Flow Trips Total", "SUM ( 'Zone Flow'[Flow Trips] )", "#,0", "Flows")
m("Flow Revenue Total", "SUM ( 'Zone Flow'[Flow Revenue] )", "$#,0", "Flows")

# ---------------------------------------------------------------------------------------------
def ind(s, n=1): return "\n".join(("\t" * n + l) if l else l for l in s.split("\n"))

def emit_table(name, schema, entity, cols, hidden_all):
    q = f"'{name}'" if " " in name else name
    out = [f"table {q}"]
    if hidden_all: out.append("\tisHidden")
    if name == "Date": out.append("\tdataCategory: Time")
    out.append("")
    if name == "Trips":
        for (mn, dax, fmt, folder, desc) in M:
            if desc: out.append(f"\t/// {desc}")
            out.append(f"\tmeasure '{mn}' =\n\t\t\t{dax}")
            if fmt: out.append(f"\t\tformatString: {fmt}")
            out.append(f"\t\tdisplayFolder: {folder}")
            out.append("")
    for (cn, src, dt, o) in cols:
        cq = f"'{cn}'" if " " in cn or "(" in cn else cn
        if o.get("desc"): out.append(f"\t/// {o['desc']}")
        out.append(f"\tcolumn {cq}")
        out.append(f"\t\tdataType: {dt}")
        if dt == "dateTime" and name == "Date" and cn == "Date": out.append("\t\tisKey")
        if o.get("hidden") or hidden_all: out.append("\t\tisHidden")
        if o.get("fmt"): out.append(f"\t\tformatString: {o['fmt']}")
        elif dt == "int64" and not o.get("key"): out.append("\t\tformatString: #,0")
        if o.get("cat"): out.append(f"\t\tdataCategory: {o['cat']}")
        if o.get("sortBy"):
            sb = o["sortBy"]; sbq = f"'{sb}'" if " " in sb else sb
            out.append(f"\t\tsortByColumn: {sbq}")
        AGG = ("Zone Flow", "Demand Profile", "Data Quality", "Data Quality Rules", "Load Control", "Run Log")
        summ = o.get("summarize") or ("sum" if (dt in ("int64", "decimal", "double") and name in AGG and not o.get("hidden") and not o.get("key")) else "none")
        out.append(f"\t\tsummarizeBy: {summ}")
        out.append(f"\t\tsourceColumn: {src}")
        out.append("")
    if name == "Date":
        out.append("\thierarchy Calendar")
        for lvl, col in [("Year", "Year"), ("Quarter", "Quarter"), ("Month", "Month"), ("Date", "Date")]:
            out.append(f"\n\t\tlevel {lvl}\n\t\t\tcolumn: {col}")
        out.append("")
    out.append(f"\tpartition {q} = entity\n\t\tmode: directLake\n\t\tsource\n\t\t\tentityName: {entity}\n\t\t\tschemaName: {schema}\n\t\t\texpressionSource: DatabaseQuery")
    out.append("")
    return "\n".join(out) + "\n"

def emit_model():
    lines = ["model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3", "\tdiscourageImplicitMeasures",
             "\tsourceQueryCulture: en-US", "", "\tannotation __PBI_TimeIntelligenceEnabled = 0", "\tannotation PBI_QueryOrder = [\"DatabaseQuery\"]", ""]
    for t in TABLES:
        n = t[0]; lines.append("ref table " + (f"'{n}'" if " " in n else n))
    lines += ["", "expression DatabaseQuery =",
              "\t\tlet", f"\t\t    database = Sql.Database(\"{EP}\", \"{WH}\")", "\t\tin", "\t\t    database",
              "", "\tannotation PBI_IncludeFutureArtifacts = False", ""]
    return "\n".join(lines)

def emit_rels():
    out = []
    for (ft, fc, tt, tc, active) in RELS:
        q = lambda t, c: (f"'{t}'" if " " in t else t) + "." + (f"'{c}'" if " " in c else c)
        out.append(f"relationship {tag('rel', ft, fc, tt, tc)}")
        if not active: out.append("\tisActive: false")
        # Keys are validated by the reconciliation step, so Direct Lake can skip the blank row and use inner joins
        out.append("\trelyOnReferentialIntegrity")
        out.append(f"\tfromColumn: {q(ft, fc)}")
        out.append(f"\ttoColumn: {q(tt, tc)}")
        out.append("")
    return "\n".join(out)

def build():
    files = {}
    files["definition/database.tmdl"] = "database\n\tcompatibilityLevel: 1604\n"
    files["definition/model.tmdl"] = emit_model()
    files["definition/relationships.tmdl"] = emit_rels()
    for t in TABLES:
        files[f"definition/tables/{t[0]}.tmdl"] = emit_table(*t)
    files["definition.pbism"] = json.dumps({"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
                                            "version": "4.2", "settings": {}}, indent=2)
    OUT.mkdir(parents=True, exist_ok=True)
    parts = []
    for path, content in files.items():
        p = OUT / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content, encoding="utf-8")
        parts.append({"path": path, "payload": base64.b64encode(content.encode("utf-8")).decode(), "payloadType": "InlineBase64"})
    payload = {"parts": parts}
    BUILD.mkdir(exist_ok=True)
    (BUILD / "SM_NYC_Taxi.definition.json").write_text(json.dumps(payload, separators=(",", ":")))
    print(f"{len(parts)} parts, {len(M)} measures, definition json {len(json.dumps(payload, separators=(',', ':')))} chars")

if __name__ == "__main__":
    build()
