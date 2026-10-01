-- =====================================================================
-- WH_NYC_Taxi · Gold layer · Schemas and tables
-- Layers: stg (staging fed from Silver) ➜ dim / fact (star schema) ➜ agg (serving aggregates)
-- etl schema: run log, load control, reconciliation
-- All statements are idempotent (drop-and-create) so the build can be replayed.
-- =====================================================================

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'stg')  EXEC('CREATE SCHEMA stg');
GO
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'dim')  EXEC('CREATE SCHEMA dim');
GO
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'fact') EXEC('CREATE SCHEMA fact');
GO
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'agg')  EXEC('CREATE SCHEMA agg');
GO
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'etl')  EXEC('CREATE SCHEMA etl');
GO

-- ---------------------------------------------------------------------
-- ETL control tables
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS etl.run_log;
CREATE TABLE etl.run_log (
    log_id          bigint          NOT NULL,
    run_id          varchar(64)     NOT NULL,
    step_name       varchar(100)    NOT NULL,
    status          varchar(20)     NOT NULL,   -- RUNNING | SUCCEEDED | FAILED
    started_at      datetime2(3)    NOT NULL,
    ended_at        datetime2(3)    NULL,
    rows_affected   bigint          NULL,
    message         varchar(4000)   NULL
);
GO

DROP TABLE IF EXISTS etl.load_control;
CREATE TABLE etl.load_control (
    year_number     smallint        NOT NULL,
    month_number    smallint        NOT NULL,
    silver_rows     bigint          NOT NULL,
    staged_rows     bigint          NOT NULL,
    fact_rows       bigint          NOT NULL,
    is_reconciled   bit             NOT NULL,
    last_run_id     varchar(64)     NOT NULL,
    last_loaded_at  datetime2(3)    NOT NULL
);
GO

-- ---------------------------------------------------------------------
-- Staging (one month at a time, replaced on each load)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS stg.stg_yellow_trips;
CREATE TABLE stg.stg_yellow_trips (
    trip_sk                 bigint          NOT NULL,
    vendor_id               int             NULL,
    pickup_datetime         datetime2(0)    NOT NULL,
    dropoff_datetime        datetime2(0)    NOT NULL,
    pickup_date             date            NOT NULL,
    pickup_hour             smallint        NOT NULL,
    passenger_count         smallint        NULL,
    trip_distance           decimal(9,2)    NULL,
    duration_min            decimal(9,2)    NULL,
    avg_speed_mph           decimal(9,2)    NULL,
    rate_code_id            int             NULL,
    store_and_fwd_flag      varchar(1)      NULL,
    pickup_location_id      int             NOT NULL,
    dropoff_location_id     int             NOT NULL,
    payment_type_id         int             NULL,
    fare_amount             decimal(10,2)   NULL,
    extra                   decimal(10,2)   NULL,
    mta_tax                 decimal(10,2)   NULL,
    tip_amount              decimal(10,2)   NULL,
    tip_pct                 decimal(9,2)    NULL,
    tolls_amount            decimal(10,2)   NULL,
    improvement_surcharge   decimal(10,2)   NULL,
    congestion_surcharge    decimal(10,2)   NULL,
    airport_fee             decimal(10,2)   NULL,
    cbd_congestion_fee      decimal(10,2)   NULL,
    total_surcharges        decimal(10,2)   NULL,
    total_amount            decimal(10,2)   NULL,
    is_airport_trip         bit             NOT NULL,
    year_number             smallint        NOT NULL,
    month_number            smallint        NOT NULL
);
GO

DROP TABLE IF EXISTS stg.stg_taxi_zones;
CREATE TABLE stg.stg_taxi_zones (
    location_id     int             NOT NULL,
    borough         varchar(50)     NOT NULL,
    zone_name       varchar(100)    NOT NULL,
    service_zone    varchar(50)     NOT NULL,
    is_airport      bit             NOT NULL,
    latitude        float           NULL,
    longitude       float           NULL,
    area_sq_mi      float           NULL
);
GO

-- ---------------------------------------------------------------------
-- Dimensions
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS dim.dim_date;
CREATE TABLE dim.dim_date (
    date_key        int             NOT NULL,   -- yyyymmdd
    full_date       date            NOT NULL,
    year_number     smallint        NOT NULL,
    quarter_number  smallint        NOT NULL,
    quarter_label   varchar(7)      NOT NULL,   -- 2025 Q1
    month_number    smallint        NOT NULL,
    month_name      varchar(12)     NOT NULL,
    month_short     varchar(3)      NOT NULL,
    year_month      varchar(7)      NOT NULL,   -- 2025-01
    month_label     varchar(8)      NOT NULL,   -- Jan 2025
    month_start     date            NOT NULL,
    day_of_month    smallint        NOT NULL,
    day_of_week     smallint        NOT NULL,   -- 1 = Monday ... 7 = Sunday
    day_name        varchar(9)      NOT NULL,
    day_short       varchar(3)      NOT NULL,
    is_weekend      bit             NOT NULL,
    week_of_year    smallint        NOT NULL,
    day_of_year     smallint        NOT NULL,
    is_holiday      bit             NOT NULL,
    holiday_name    varchar(40)     NULL,
    season          varchar(6)      NOT NULL,
    day_type        varchar(8)      NOT NULL    -- Weekday | Weekend | Holiday
);
GO

DROP TABLE IF EXISTS dim.dim_hour;
CREATE TABLE dim.dim_hour (
    hour_key        smallint        NOT NULL,   -- 0..23
    hour_label      varchar(5)      NOT NULL,   -- 08:00
    hour_12         varchar(5)      NOT NULL,   -- 8 AM
    day_part        varchar(12)     NOT NULL,   -- Night, Morning, Midday, Afternoon, Evening
    day_part_order  smallint        NOT NULL,
    is_rush_hour    bit             NOT NULL
);
GO

DROP TABLE IF EXISTS dim.dim_zone;
CREATE TABLE dim.dim_zone (
    zone_key        int             NOT NULL,   -- = TLC LocationID
    zone_name       varchar(100)    NOT NULL,
    borough         varchar(50)     NOT NULL,
    service_zone    varchar(50)     NOT NULL,
    zone_full_name  varchar(160)    NOT NULL,   -- Zone (Borough)
    is_airport      bit             NOT NULL,
    latitude        float           NULL,
    longitude       float           NULL,
    area_sq_mi      float           NULL
);
GO

DROP TABLE IF EXISTS dim.dim_vendor;
CREATE TABLE dim.dim_vendor (
    vendor_key      int             NOT NULL,
    vendor_name     varchar(60)     NOT NULL
);
GO

DROP TABLE IF EXISTS dim.dim_rate_code;
CREATE TABLE dim.dim_rate_code (
    rate_code_key   int             NOT NULL,
    rate_code_name  varchar(40)     NOT NULL
);
GO

DROP TABLE IF EXISTS dim.dim_payment_type;
CREATE TABLE dim.dim_payment_type (
    payment_type_key    int         NOT NULL,
    payment_type_name   varchar(30) NOT NULL,
    is_electronic       bit         NOT NULL
);
GO

DROP TABLE IF EXISTS dim.dim_distance_band;
CREATE TABLE dim.dim_distance_band (
    distance_band_key   smallint    NOT NULL,
    distance_band       varchar(20) NOT NULL,
    min_miles           decimal(6,2) NOT NULL,
    max_miles           decimal(6,2) NOT NULL
);
GO

-- ---------------------------------------------------------------------
-- Fact (grain = one taxi trip)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS fact.fact_trip;
CREATE TABLE fact.fact_trip (
    trip_sk                 bigint          NOT NULL,
    date_key                int             NOT NULL,
    hour_key                smallint        NOT NULL,
    pickup_zone_key         int             NOT NULL,
    dropoff_zone_key        int             NOT NULL,
    vendor_key              int             NOT NULL,
    rate_code_key           int             NOT NULL,
    payment_type_key        int             NOT NULL,
    distance_band_key       smallint        NOT NULL,
    pickup_datetime         datetime2(0)    NOT NULL,
    dropoff_datetime        datetime2(0)    NOT NULL,
    passenger_count         smallint        NULL,
    trip_distance           decimal(9,2)    NULL,
    duration_min            decimal(9,2)    NULL,
    avg_speed_mph           decimal(9,2)    NULL,
    fare_amount             decimal(10,2)   NULL,
    extra                   decimal(10,2)   NULL,
    mta_tax                 decimal(10,2)   NULL,
    tip_amount              decimal(10,2)   NULL,
    tolls_amount            decimal(10,2)   NULL,
    improvement_surcharge   decimal(10,2)   NULL,
    congestion_surcharge    decimal(10,2)   NULL,
    airport_fee             decimal(10,2)   NULL,
    cbd_congestion_fee      decimal(10,2)   NULL,
    total_surcharges        decimal(10,2)   NULL,
    total_amount            decimal(10,2)   NULL,
    is_airport_trip         bit             NOT NULL,
    is_tipped               bit             NOT NULL,
    year_number             smallint        NOT NULL,
    month_number            smallint        NOT NULL
);
GO

-- ---------------------------------------------------------------------
-- Serving aggregates (rebuilt by etl.usp_build_aggregates)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS agg.monthly_kpi;
CREATE TABLE agg.monthly_kpi (
    year_number     smallint        NOT NULL,
    month_number    smallint        NOT NULL,
    year_month      varchar(7)      NOT NULL,
    trips           bigint          NOT NULL,
    revenue         decimal(14,2)   NOT NULL,
    fare_revenue    decimal(14,2)   NOT NULL,
    tips            decimal(14,2)   NOT NULL,
    surcharges      decimal(14,2)   NOT NULL,
    tolls           decimal(14,2)   NOT NULL,
    passengers      bigint          NOT NULL,
    miles           decimal(14,2)   NOT NULL,
    minutes         decimal(16,2)   NOT NULL,
    airport_trips   bigint          NOT NULL,
    card_trips      bigint          NOT NULL,
    days_in_month   smallint        NOT NULL,
    avg_fare        decimal(10,2)   NOT NULL,
    avg_distance    decimal(9,2)    NOT NULL,
    avg_duration    decimal(9,2)    NOT NULL,
    avg_tip_pct     decimal(9,2)    NOT NULL,
    trips_per_day   decimal(12,1)   NOT NULL
);
GO

DROP TABLE IF EXISTS agg.daily_borough;
CREATE TABLE agg.daily_borough (
    date_key        int             NOT NULL,
    borough         varchar(50)     NOT NULL,
    trips           bigint          NOT NULL,
    revenue         decimal(14,2)   NOT NULL,
    avg_fare        decimal(10,2)   NOT NULL,
    avg_duration    decimal(9,2)    NOT NULL
);
GO

DROP TABLE IF EXISTS agg.hourly_weekday;
CREATE TABLE agg.hourly_weekday (
    day_of_week     smallint        NOT NULL,
    day_short       varchar(3)      NOT NULL,
    hour_key        smallint        NOT NULL,
    hour_label      varchar(5)      NOT NULL,
    trips           bigint          NOT NULL,
    trips_per_slot  decimal(12,1)   NOT NULL,   -- trips divided by the number of such weekday-hours in the data
    revenue         decimal(14,2)   NOT NULL,
    avg_fare        decimal(10,2)   NOT NULL,
    avg_duration    decimal(9,2)    NOT NULL,
    avg_speed_mph   decimal(9,2)    NOT NULL
);
GO

DROP TABLE IF EXISTS agg.zone_flow;
CREATE TABLE agg.zone_flow (
    pickup_zone_key     int         NOT NULL,
    dropoff_zone_key    int         NOT NULL,
    trips               bigint      NOT NULL,
    revenue             decimal(14,2) NOT NULL,
    avg_fare            decimal(10,2) NOT NULL,
    avg_distance        decimal(9,2)  NOT NULL,
    avg_duration        decimal(9,2)  NOT NULL,
    flow_rank           int         NOT NULL
);
GO

DROP TABLE IF EXISTS agg.zone_monthly;
CREATE TABLE agg.zone_monthly (
    zone_key        int             NOT NULL,
    year_number     smallint        NOT NULL,
    month_number    smallint        NOT NULL,
    pickups         bigint          NOT NULL,
    dropoffs        bigint          NOT NULL,
    pickup_revenue  decimal(14,2)   NOT NULL,
    avg_fare        decimal(10,2)   NOT NULL,
    avg_tip_pct     decimal(9,2)    NOT NULL
);
GO

DROP TABLE IF EXISTS agg.dq_month;
CREATE TABLE agg.dq_month (
    year_number         smallint    NOT NULL,
    month_number        smallint    NOT NULL,
    year_month          varchar(7)  NOT NULL,
    source_file         varchar(80) NOT NULL,
    rows_read           bigint      NOT NULL,
    exact_duplicates    bigint      NOT NULL,
    rows_valid          bigint      NOT NULL,
    rows_rejected       bigint      NOT NULL,
    reject_pct          decimal(9,4) NOT NULL,
    silver_duration_s   int         NOT NULL,
    processed_at        datetime2(0) NOT NULL,
    run_id              varchar(64) NOT NULL
);
GO

DROP TABLE IF EXISTS agg.dq_rule_month;
CREATE TABLE agg.dq_rule_month (
    year_number     smallint        NOT NULL,
    month_number    smallint        NOT NULL,
    year_month      varchar(7)      NOT NULL,
    rule_name       varchar(60)     NOT NULL,
    rule_label      varchar(60)     NOT NULL,
    rejected_rows   bigint          NOT NULL
);
GO

-- ---------------------------------------------------------------------
-- Primary keys (informational, NOT ENFORCED, for the optimiser and for modelling tools).
-- Fabric Warehouse accepts them only through ALTER TABLE, never inline in CREATE TABLE.
-- ---------------------------------------------------------------------
ALTER TABLE dim.dim_date          ADD CONSTRAINT pk_dim_date          PRIMARY KEY NONCLUSTERED (date_key)          NOT ENFORCED;
GO
ALTER TABLE dim.dim_hour          ADD CONSTRAINT pk_dim_hour          PRIMARY KEY NONCLUSTERED (hour_key)          NOT ENFORCED;
GO
ALTER TABLE dim.dim_zone          ADD CONSTRAINT pk_dim_zone          PRIMARY KEY NONCLUSTERED (zone_key)          NOT ENFORCED;
GO
ALTER TABLE dim.dim_vendor        ADD CONSTRAINT pk_dim_vendor        PRIMARY KEY NONCLUSTERED (vendor_key)        NOT ENFORCED;
GO
ALTER TABLE dim.dim_rate_code     ADD CONSTRAINT pk_dim_rate_code     PRIMARY KEY NONCLUSTERED (rate_code_key)     NOT ENFORCED;
GO
ALTER TABLE dim.dim_payment_type  ADD CONSTRAINT pk_dim_payment_type  PRIMARY KEY NONCLUSTERED (payment_type_key)  NOT ENFORCED;
GO
ALTER TABLE dim.dim_distance_band ADD CONSTRAINT pk_dim_distance_band PRIMARY KEY NONCLUSTERED (distance_band_key) NOT ENFORCED;
GO
ALTER TABLE fact.fact_trip        ADD CONSTRAINT pk_fact_trip         PRIMARY KEY NONCLUSTERED (trip_sk)           NOT ENFORCED;
GO
