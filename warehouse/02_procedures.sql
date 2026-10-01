-- =====================================================================
-- WH_NYC_Taxi · Gold layer · Stored procedures
--   etl.usp_log_step          : structured run log
--   etl.usp_load_dimensions   : date, hour, zone, vendor, rate code, payment type, distance band
--   etl.usp_load_month        : Silver ➜ staging ➜ fact for one month, with reconciliation
--   etl.usp_build_aggregates  : serving aggregates and data quality snapshots
--   etl.usp_run_full          : orchestrates every month found in Silver for a year
-- =====================================================================

IF OBJECT_ID('etl.usp_log_step', 'P') IS NOT NULL DROP PROCEDURE etl.usp_log_step;
GO
CREATE PROCEDURE etl.usp_log_step
    @run_id        varchar(64),
    @step_name     varchar(100),
    @status        varchar(20),
    @rows_affected bigint = NULL,
    @message       varchar(4000) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @now datetime2(3) = SYSUTCDATETIME();
    IF @status = 'RUNNING'
        INSERT INTO etl.run_log (log_id, run_id, step_name, status, started_at, ended_at, rows_affected, message)
        SELECT ISNULL(MAX(log_id), 0) + 1, @run_id, @step_name, @status, @now, NULL, NULL, @message FROM etl.run_log;
    ELSE
    BEGIN
        -- close the open RUNNING row of this step if any, otherwise write a standalone row
        UPDATE etl.run_log
           SET status = @status, ended_at = @now, rows_affected = @rows_affected, message = @message
         WHERE run_id = @run_id AND step_name = @step_name AND status = 'RUNNING';
        IF @@ROWCOUNT = 0
            INSERT INTO etl.run_log (log_id, run_id, step_name, status, started_at, ended_at, rows_affected, message)
            SELECT ISNULL(MAX(log_id), 0) + 1, @run_id, @step_name, @status, @now, @now, @rows_affected, @message FROM etl.run_log;
    END
END
GO

-- ---------------------------------------------------------------------
IF OBJECT_ID('etl.usp_load_dimensions', 'P') IS NOT NULL DROP PROCEDURE etl.usp_load_dimensions;
GO
CREATE PROCEDURE etl.usp_load_dimensions
    @run_id varchar(64) = 'manual'
AS
BEGIN
    SET NOCOUNT ON;
    EXEC etl.usp_log_step @run_id, 'load_dimensions', 'RUNNING';
    BEGIN TRY
        -- ---------------- dim_date: 2024-01-01 .. 2026-12-31 with US federal holidays ----------------
        TRUNCATE TABLE dim.dim_date;
        ;WITH n0 AS (SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
                     UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9),
        nums AS (SELECT a.n + 10*b.n + 100*c.n + 1000*d.n AS n FROM n0 a CROSS JOIN n0 b CROSS JOIN n0 c CROSS JOIN n0 d),
        days AS (SELECT DATEADD(day, n, CAST('2024-01-01' AS date)) AS d FROM nums WHERE n <= DATEDIFF(day, '2024-01-01', '2026-12-31')),
        hol AS (SELECT CAST(h AS date) AS h, nm FROM (VALUES
            ('2024-01-01','New Year''s Day'),('2024-01-15','Martin Luther King Jr. Day'),('2024-02-19','Presidents'' Day'),
            ('2024-05-27','Memorial Day'),('2024-06-19','Juneteenth'),('2024-07-04','Independence Day'),('2024-09-02','Labor Day'),
            ('2024-10-14','Columbus Day'),('2024-11-11','Veterans Day'),('2024-11-28','Thanksgiving Day'),('2024-12-25','Christmas Day'),
            ('2025-01-01','New Year''s Day'),('2025-01-20','Martin Luther King Jr. Day'),('2025-02-17','Presidents'' Day'),
            ('2025-05-26','Memorial Day'),('2025-06-19','Juneteenth'),('2025-07-04','Independence Day'),('2025-09-01','Labor Day'),
            ('2025-10-13','Columbus Day'),('2025-11-11','Veterans Day'),('2025-11-27','Thanksgiving Day'),('2025-12-25','Christmas Day'),
            ('2026-01-01','New Year''s Day'),('2026-01-19','Martin Luther King Jr. Day'),('2026-02-16','Presidents'' Day'),
            ('2026-05-25','Memorial Day'),('2026-06-19','Juneteenth'),('2026-07-03','Independence Day (observed)'),('2026-09-07','Labor Day'),
            ('2026-10-12','Columbus Day'),('2026-11-11','Veterans Day'),('2026-11-26','Thanksgiving Day'),('2026-12-25','Christmas Day')) v(h, nm))
        INSERT INTO dim.dim_date (date_key, full_date, year_number, quarter_number, quarter_label, month_number, month_name, month_short,
                                  year_month, month_label, month_start, day_of_month, day_of_week, day_name, day_short, is_weekend,
                                  week_of_year, day_of_year, is_holiday, holiday_name, season, day_type)
        SELECT  YEAR(d) * 10000 + MONTH(d) * 100 + DAY(d),
                d, YEAR(d), DATEPART(quarter, d),
                CAST(YEAR(d) AS varchar(4)) + ' Q' + CAST(DATEPART(quarter, d) AS varchar(1)),
                MONTH(d), DATENAME(month, d), LEFT(DATENAME(month, d), 3),
                CAST(YEAR(d) AS varchar(4)) + '-' + RIGHT('0' + CAST(MONTH(d) AS varchar(2)), 2),
                LEFT(DATENAME(month, d), 3) + ' ' + CAST(YEAR(d) AS varchar(4)),
                DATEFROMPARTS(YEAR(d), MONTH(d), 1),
                DAY(d),
                (DATEDIFF(day, '2024-01-01', d) % 7) + 1,
                DATENAME(weekday, d), LEFT(DATENAME(weekday, d), 3),
                CASE WHEN (DATEDIFF(day, '2024-01-01', d) % 7) + 1 >= 6 THEN 1 ELSE 0 END,
                DATEPART(iso_week, d), DATEPART(dayofyear, d),
                CASE WHEN hol.h IS NULL THEN 0 ELSE 1 END, hol.nm,
                CASE WHEN MONTH(d) IN (12, 1, 2) THEN 'Winter' WHEN MONTH(d) IN (3, 4, 5) THEN 'Spring'
                     WHEN MONTH(d) IN (6, 7, 8) THEN 'Summer' ELSE 'Autumn' END,
                CASE WHEN hol.h IS NOT NULL THEN 'Holiday'
                     WHEN (DATEDIFF(day, '2024-01-01', d) % 7) + 1 >= 6 THEN 'Weekend' ELSE 'Weekday' END
        FROM days LEFT JOIN hol ON hol.h = days.d;

        -- ---------------- dim_hour ----------------
        TRUNCATE TABLE dim.dim_hour;
        ;WITH h AS (SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5
                    UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11
                    UNION ALL SELECT 12 UNION ALL SELECT 13 UNION ALL SELECT 14 UNION ALL SELECT 15 UNION ALL SELECT 16 UNION ALL SELECT 17
                    UNION ALL SELECT 18 UNION ALL SELECT 19 UNION ALL SELECT 20 UNION ALL SELECT 21 UNION ALL SELECT 22 UNION ALL SELECT 23)
        INSERT INTO dim.dim_hour (hour_key, hour_label, hour_12, day_part, day_part_order, is_rush_hour)
        SELECT n, RIGHT('0' + CAST(n AS varchar(2)), 2) + ':00',
               CASE WHEN n = 0 THEN '12 AM' WHEN n < 12 THEN CAST(n AS varchar(2)) + ' AM' WHEN n = 12 THEN '12 PM' ELSE CAST(n - 12 AS varchar(2)) + ' PM' END,
               CASE WHEN n < 6 THEN 'Night' WHEN n < 10 THEN 'Morning' WHEN n < 14 THEN 'Midday' WHEN n < 18 THEN 'Afternoon' WHEN n < 22 THEN 'Evening' ELSE 'Late night' END,
               CASE WHEN n < 6 THEN 1 WHEN n < 10 THEN 2 WHEN n < 14 THEN 3 WHEN n < 18 THEN 4 WHEN n < 22 THEN 5 ELSE 6 END,
               CASE WHEN n IN (7, 8, 9, 16, 17, 18) THEN 1 ELSE 0 END
        FROM h;

        -- ---------------- reference dimensions (TLC data dictionary, yellow trips, 2025 edition) ----------------
        TRUNCATE TABLE dim.dim_vendor;
        INSERT INTO dim.dim_vendor (vendor_key, vendor_name) VALUES
            (1, 'Creative Mobile Technologies'), (2, 'Curb Mobility'), (6, 'Myle Technologies'), (7, 'Helix'), (-1, 'Unknown');

        TRUNCATE TABLE dim.dim_rate_code;
        INSERT INTO dim.dim_rate_code (rate_code_key, rate_code_name) VALUES
            (1, 'Standard rate'), (2, 'JFK'), (3, 'Newark'), (4, 'Nassau or Westchester'), (5, 'Negotiated fare'), (6, 'Group ride'), (99, 'Unknown');

        TRUNCATE TABLE dim.dim_payment_type;
        INSERT INTO dim.dim_payment_type (payment_type_key, payment_type_name, is_electronic) VALUES
            (0, 'Flex fare', 1), (1, 'Credit card', 1), (2, 'Cash', 0), (3, 'No charge', 0), (4, 'Dispute', 0), (5, 'Unknown', 0), (6, 'Voided trip', 0);

        TRUNCATE TABLE dim.dim_distance_band;
        INSERT INTO dim.dim_distance_band (distance_band_key, distance_band, min_miles, max_miles) VALUES
            (1, '0 to 1 mi', 0, 1), (2, '1 to 2 mi', 1, 2), (3, '2 to 3 mi', 2, 3), (4, '3 to 5 mi', 3, 5),
            (5, '5 to 10 mi', 5, 10), (6, '10 to 20 mi', 10, 20), (7, 'Over 20 mi', 20, 999);

        -- ---------------- dim_zone from Silver (cross-database read of the lakehouse SQL endpoint) ----------------
        TRUNCATE TABLE stg.stg_taxi_zones;
        INSERT INTO stg.stg_taxi_zones (location_id, borough, zone_name, service_zone, is_airport, latitude, longitude, area_sq_mi)
        SELECT location_id, borough, zone, service_zone, CAST(is_airport AS bit), latitude, longitude, area_sq_mi
        FROM [LH_Silver].[dbo].[silver_taxi_zones];

        TRUNCATE TABLE dim.dim_zone;
        INSERT INTO dim.dim_zone (zone_key, zone_name, borough, service_zone, zone_full_name, is_airport, latitude, longitude, area_sq_mi)
        SELECT location_id, zone_name, borough, service_zone, zone_name + ' (' + borough + ')', is_airport, latitude, longitude, area_sq_mi
        FROM stg.stg_taxi_zones;
        IF NOT EXISTS (SELECT 1 FROM dim.dim_zone WHERE zone_key = 0)
            INSERT INTO dim.dim_zone (zone_key, zone_name, borough, service_zone, zone_full_name, is_airport, latitude, longitude, area_sq_mi)
            VALUES (0, 'Unmapped', 'Unknown', 'N/A', 'Unmapped (Unknown)', 0, NULL, NULL, NULL);

        DECLARE @n bigint = (SELECT COUNT(*) FROM dim.dim_date) + (SELECT COUNT(*) FROM dim.dim_zone);
        EXEC etl.usp_log_step @run_id, 'load_dimensions', 'SUCCEEDED', @n, 'dim_date, dim_hour, dim_zone, dim_vendor, dim_rate_code, dim_payment_type, dim_distance_band';
    END TRY
    BEGIN CATCH
        DECLARE @err varchar(4000) = ERROR_MESSAGE();
        EXEC etl.usp_log_step @run_id, 'load_dimensions', 'FAILED', NULL, @err;
        THROW;
    END CATCH
END
GO

-- ---------------------------------------------------------------------
IF OBJECT_ID('etl.usp_load_month', 'P') IS NOT NULL DROP PROCEDURE etl.usp_load_month;
GO
CREATE PROCEDURE etl.usp_load_month
    @year   smallint,
    @month  smallint,
    @run_id varchar(64) = 'manual'
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @step varchar(100) = 'load_month_' + CAST(@year AS varchar(4)) + '_' + RIGHT('0' + CAST(@month AS varchar(2)), 2);
    DECLARE @silver_rows bigint, @staged_rows bigint, @fact_rows bigint, @msg varchar(4000);
    EXEC etl.usp_log_step @run_id, @step, 'RUNNING';
    BEGIN TRY
        SELECT @silver_rows = COUNT_BIG(*) FROM [LH_Silver].[dbo].[silver_yellow_trips] WHERE [year] = @year AND [month] = @month;
        IF @silver_rows = 0
        BEGIN
            SET @msg = 'No Silver rows for ' + CAST(@year AS varchar(4)) + '-' + CAST(@month AS varchar(2));
            THROW 50010, @msg, 1;
        END

        -- ---------------- staging: replace the month ----------------
        DELETE FROM stg.stg_yellow_trips WHERE year_number = @year AND month_number = @month;
        INSERT INTO stg.stg_yellow_trips (trip_sk, vendor_id, pickup_datetime, dropoff_datetime, pickup_date, pickup_hour, passenger_count,
            trip_distance, duration_min, avg_speed_mph, rate_code_id, store_and_fwd_flag, pickup_location_id, dropoff_location_id,
            payment_type_id, fare_amount, extra, mta_tax, tip_amount, tip_pct, tolls_amount, improvement_surcharge, congestion_surcharge,
            airport_fee, cbd_congestion_fee, total_surcharges, total_amount, is_airport_trip, year_number, month_number)
        SELECT trip_sk, vendor_id, CAST(pickup_datetime AS datetime2(0)), CAST(dropoff_datetime AS datetime2(0)), pickup_date,
               CAST(pickup_hour AS smallint), CAST(passenger_count AS smallint),
               CAST(trip_distance AS decimal(9,2)), CAST(duration_min AS decimal(9,2)), CAST(avg_speed_mph AS decimal(9,2)),
               rate_code_id, LEFT(store_and_fwd_flag, 1), pickup_location_id, dropoff_location_id, payment_type_id,
               CAST(fare_amount AS decimal(10,2)), CAST(extra AS decimal(10,2)), CAST(mta_tax AS decimal(10,2)), CAST(tip_amount AS decimal(10,2)),
               CAST(tip_pct AS decimal(9,2)), CAST(tolls_amount AS decimal(10,2)), CAST(improvement_surcharge AS decimal(10,2)),
               CAST(congestion_surcharge AS decimal(10,2)), CAST(airport_fee AS decimal(10,2)), CAST(cbd_congestion_fee AS decimal(10,2)),
               CAST(total_surcharges AS decimal(10,2)), CAST(total_amount AS decimal(10,2)), CAST(is_airport_trip AS bit),
               CAST([year] AS smallint), CAST([month] AS smallint)
        FROM [LH_Silver].[dbo].[silver_yellow_trips]
        WHERE [year] = @year AND [month] = @month;
        SELECT @staged_rows = COUNT_BIG(*) FROM stg.stg_yellow_trips WHERE year_number = @year AND month_number = @month;

        -- ---------------- fact: replace the month (transactional) ----------------
        BEGIN TRANSACTION;
        DELETE FROM fact.fact_trip WHERE year_number = @year AND month_number = @month;
        INSERT INTO fact.fact_trip (trip_sk, date_key, hour_key, pickup_zone_key, dropoff_zone_key, vendor_key, rate_code_key, payment_type_key,
            distance_band_key, pickup_datetime, dropoff_datetime, passenger_count, trip_distance, duration_min, avg_speed_mph, fare_amount,
            extra, mta_tax, tip_amount, tolls_amount, improvement_surcharge, congestion_surcharge, airport_fee, cbd_congestion_fee,
            total_surcharges, total_amount, is_airport_trip, is_tipped, year_number, month_number)
        SELECT  s.trip_sk,
                YEAR(s.pickup_date) * 10000 + MONTH(s.pickup_date) * 100 + DAY(s.pickup_date),
                s.pickup_hour,
                CASE WHEN pz.zone_key IS NULL THEN 0 ELSE s.pickup_location_id END,
                CASE WHEN dz.zone_key IS NULL THEN 0 ELSE s.dropoff_location_id END,
                CASE WHEN v.vendor_key IS NULL THEN -1 ELSE s.vendor_id END,
                CASE WHEN rc.rate_code_key IS NULL THEN 99 ELSE s.rate_code_id END,
                CASE WHEN pt.payment_type_key IS NULL THEN 5 ELSE s.payment_type_id END,
                CASE WHEN s.trip_distance < 1 THEN 1 WHEN s.trip_distance < 2 THEN 2 WHEN s.trip_distance < 3 THEN 3 WHEN s.trip_distance < 5 THEN 4
                     WHEN s.trip_distance < 10 THEN 5 WHEN s.trip_distance < 20 THEN 6 ELSE 7 END,
                s.pickup_datetime, s.dropoff_datetime, s.passenger_count, s.trip_distance, s.duration_min, s.avg_speed_mph, s.fare_amount,
                s.extra, s.mta_tax, s.tip_amount, s.tolls_amount, s.improvement_surcharge, s.congestion_surcharge, s.airport_fee, s.cbd_congestion_fee,
                s.total_surcharges, s.total_amount, s.is_airport_trip,
                CASE WHEN s.tip_amount > 0 THEN 1 ELSE 0 END,
                s.year_number, s.month_number
        FROM stg.stg_yellow_trips s
        LEFT JOIN dim.dim_zone pz         ON pz.zone_key = s.pickup_location_id
        LEFT JOIN dim.dim_zone dz         ON dz.zone_key = s.dropoff_location_id
        LEFT JOIN dim.dim_vendor v        ON v.vendor_key = s.vendor_id
        LEFT JOIN dim.dim_rate_code rc    ON rc.rate_code_key = s.rate_code_id
        LEFT JOIN dim.dim_payment_type pt ON pt.payment_type_key = s.payment_type_id
        WHERE s.year_number = @year AND s.month_number = @month;
        COMMIT TRANSACTION;

        SELECT @fact_rows = COUNT_BIG(*) FROM fact.fact_trip WHERE year_number = @year AND month_number = @month;

        -- ---------------- reconciliation and control ----------------
        DELETE FROM etl.load_control WHERE year_number = @year AND month_number = @month;
        INSERT INTO etl.load_control (year_number, month_number, silver_rows, staged_rows, fact_rows, is_reconciled, last_run_id, last_loaded_at)
        VALUES (@year, @month, @silver_rows, @staged_rows, @fact_rows,
                CASE WHEN @silver_rows = @staged_rows AND @staged_rows = @fact_rows THEN 1 ELSE 0 END, @run_id, SYSUTCDATETIME());

        IF NOT (@silver_rows = @staged_rows AND @staged_rows = @fact_rows)
        BEGIN
            SET @msg = 'Reconciliation failed: silver=' + CAST(@silver_rows AS varchar(20)) + ' staged=' + CAST(@staged_rows AS varchar(20)) + ' fact=' + CAST(@fact_rows AS varchar(20));
            THROW 50020, @msg, 1;
        END

        SET @msg = 'silver=' + CAST(@silver_rows AS varchar(20)) + ' staged=' + CAST(@staged_rows AS varchar(20)) + ' fact=' + CAST(@fact_rows AS varchar(20)) + ' reconciled';
        EXEC etl.usp_log_step @run_id, @step, 'SUCCEEDED', @fact_rows, @msg;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
        DECLARE @err varchar(4000) = ERROR_MESSAGE();
        EXEC etl.usp_log_step @run_id, @step, 'FAILED', NULL, @err;
        THROW;
    END CATCH
END
GO

-- ---------------------------------------------------------------------
IF OBJECT_ID('etl.usp_build_aggregates', 'P') IS NOT NULL DROP PROCEDURE etl.usp_build_aggregates;
GO
CREATE PROCEDURE etl.usp_build_aggregates
    @run_id varchar(64) = 'manual'
AS
BEGIN
    SET NOCOUNT ON;
    EXEC etl.usp_log_step @run_id, 'build_aggregates', 'RUNNING';
    BEGIN TRY
        -- ---------------- monthly KPIs ----------------
        TRUNCATE TABLE agg.monthly_kpi;
        INSERT INTO agg.monthly_kpi (year_number, month_number, year_month, trips, revenue, fare_revenue, tips, surcharges, tolls, passengers,
                                     miles, minutes, airport_trips, card_trips, days_in_month, avg_fare, avg_distance, avg_duration, avg_tip_pct, trips_per_day)
        SELECT  f.year_number, f.month_number,
                CAST(f.year_number AS varchar(4)) + '-' + RIGHT('0' + CAST(f.month_number AS varchar(2)), 2),
                COUNT_BIG(*), SUM(f.total_amount), SUM(f.fare_amount), SUM(f.tip_amount), SUM(f.total_surcharges), SUM(f.tolls_amount),
                SUM(CAST(ISNULL(f.passenger_count, 1) AS bigint)), SUM(f.trip_distance), SUM(f.duration_min),
                SUM(CAST(f.is_airport_trip AS int)), SUM(CASE WHEN f.payment_type_key = 1 THEN 1 ELSE 0 END),
                COUNT(DISTINCT f.date_key),
                AVG(f.fare_amount), AVG(f.trip_distance), AVG(f.duration_min),
                ISNULL(100.0 * SUM(CASE WHEN f.payment_type_key = 1 THEN f.tip_amount ELSE 0 END) / NULLIF(SUM(CASE WHEN f.payment_type_key = 1 THEN f.fare_amount ELSE 0 END), 0), 0),
                ISNULL(CAST(COUNT_BIG(*) AS decimal(14,1)) / NULLIF(COUNT(DISTINCT f.date_key), 0), 0)
        FROM fact.fact_trip f
        GROUP BY f.year_number, f.month_number;

        -- ---------------- daily by borough ----------------
        TRUNCATE TABLE agg.daily_borough;
        INSERT INTO agg.daily_borough (date_key, borough, trips, revenue, avg_fare, avg_duration)
        SELECT f.date_key, z.borough, COUNT_BIG(*), SUM(f.total_amount), AVG(f.fare_amount), AVG(f.duration_min)
        FROM fact.fact_trip f JOIN dim.dim_zone z ON z.zone_key = f.pickup_zone_key
        GROUP BY f.date_key, z.borough;

        -- ---------------- weekday x hour demand profile ----------------
        TRUNCATE TABLE agg.hourly_weekday;
        ;WITH slots AS (
            SELECT d.day_of_week, COUNT(*) AS n_days
            FROM dim.dim_date d
            WHERE d.date_key BETWEEN (SELECT MIN(date_key) FROM fact.fact_trip) AND (SELECT MAX(date_key) FROM fact.fact_trip)
            GROUP BY d.day_of_week)
        INSERT INTO agg.hourly_weekday (day_of_week, day_short, hour_key, hour_label, trips, trips_per_slot, revenue, avg_fare, avg_duration, avg_speed_mph)
        SELECT d.day_of_week, MIN(d.day_short), f.hour_key, MIN(h.hour_label), COUNT_BIG(*),
               ISNULL(CAST(COUNT_BIG(*) AS decimal(14,1)) / NULLIF(MIN(s.n_days), 0), 0),
               SUM(f.total_amount), AVG(f.fare_amount), AVG(f.duration_min), ISNULL(AVG(f.avg_speed_mph), 0)
        FROM fact.fact_trip f
        JOIN dim.dim_date d ON d.date_key = f.date_key
        JOIN dim.dim_hour h ON h.hour_key = f.hour_key
        JOIN slots s ON s.day_of_week = d.day_of_week
        GROUP BY d.day_of_week, f.hour_key;

        -- ---------------- zone to zone flows (ranked) ----------------
        TRUNCATE TABLE agg.zone_flow;
        INSERT INTO agg.zone_flow (pickup_zone_key, dropoff_zone_key, trips, revenue, avg_fare, avg_distance, avg_duration, flow_rank)
        SELECT pickup_zone_key, dropoff_zone_key, trips, revenue, avg_fare, avg_distance, avg_duration,
               ROW_NUMBER() OVER (ORDER BY trips DESC)
        FROM (SELECT f.pickup_zone_key, f.dropoff_zone_key, COUNT_BIG(*) AS trips, SUM(f.total_amount) AS revenue,
                     AVG(f.fare_amount) AS avg_fare, AVG(f.trip_distance) AS avg_distance, AVG(f.duration_min) AS avg_duration
              FROM fact.fact_trip f
              WHERE f.pickup_zone_key > 0 AND f.dropoff_zone_key > 0
              GROUP BY f.pickup_zone_key, f.dropoff_zone_key) x;

        -- ---------------- zone monthly (pickups and dropoffs) ----------------
        TRUNCATE TABLE agg.zone_monthly;
        INSERT INTO agg.zone_monthly (zone_key, year_number, month_number, pickups, dropoffs, pickup_revenue, avg_fare, avg_tip_pct)
        SELECT z.zone_key, z.year_number, z.month_number,
               SUM(z.pickups), SUM(z.dropoffs), SUM(z.pickup_revenue),
               ISNULL(SUM(z.pickup_revenue) / NULLIF(SUM(z.pickups), 0), 0),   -- dropoff-only zones have no pickups
               ISNULL(100.0 * SUM(z.card_tips) / NULLIF(SUM(z.card_fares), 0), 0)
        FROM (
            SELECT pickup_zone_key AS zone_key, year_number, month_number, COUNT_BIG(*) AS pickups, CAST(0 AS bigint) AS dropoffs,
                   SUM(total_amount) AS pickup_revenue,
                   SUM(CASE WHEN payment_type_key = 1 THEN tip_amount ELSE 0 END) AS card_tips,
                   SUM(CASE WHEN payment_type_key = 1 THEN fare_amount ELSE 0 END) AS card_fares
            FROM fact.fact_trip GROUP BY pickup_zone_key, year_number, month_number
            UNION ALL
            SELECT dropoff_zone_key, year_number, month_number, 0, COUNT_BIG(*), 0, 0, 0
            FROM fact.fact_trip GROUP BY dropoff_zone_key, year_number, month_number) z
        GROUP BY z.zone_key, z.year_number, z.month_number;

        -- ---------------- data quality snapshots from Silver (latest run per month) ----------------
        TRUNCATE TABLE agg.dq_month;
        INSERT INTO agg.dq_month (year_number, month_number, year_month, source_file, rows_read, exact_duplicates, rows_valid, rows_rejected,
                                  reject_pct, silver_duration_s, processed_at, run_id)
        SELECT [year], [month], CAST([year] AS varchar(4)) + '-' + RIGHT('0' + CAST([month] AS varchar(2)), 2), source_file, rows_read, exact_duplicates,
               rows_valid, rows_rejected, CAST(reject_pct AS decimal(9,4)), duration_s, CAST(processed_at AS datetime2(0)), run_id
        FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY [year], [month] ORDER BY processed_at DESC) AS rn
              FROM [LH_Silver].[dbo].[silver_dq_log]) q
        WHERE rn = 1;

        TRUNCATE TABLE agg.dq_rule_month;
        INSERT INTO agg.dq_rule_month (year_number, month_number, year_month, rule_name, rule_label, rejected_rows)
        SELECT r.[year], r.[month], m.year_month, r.[rule],
               CASE r.[rule] WHEN 'outside_file_month' THEN 'Pickup outside file month' WHEN 'missing_timestamp' THEN 'Missing timestamp'
                           WHEN 'invalid_duration' THEN 'Negative or over 24 h duration' WHEN 'zero_length_trip' THEN 'Zero distance and under 1 min'
                           WHEN 'invalid_distance' THEN 'Negative or over 200 mi' WHEN 'negative_amount' THEN 'Negative fare, tip or total'
                           WHEN 'implausible_fare' THEN 'Fare or total over $1,000' WHEN 'implausible_speed' THEN 'Speed over 100 mph'
                           WHEN 'missing_location' THEN 'Missing pickup or dropoff zone' WHEN 'invalid_passengers' THEN 'More than 9 passengers'
                           ELSE r.[rule] END,
               r.rejected_rows
        FROM [LH_Silver].[dbo].[silver_dq_rule_log] r
        JOIN agg.dq_month m ON m.year_number = r.[year] AND m.month_number = r.[month] AND m.run_id = r.run_id
        WHERE r.[rule] <> 'none';

        DECLARE @n bigint = (SELECT COUNT_BIG(*) FROM agg.zone_flow) + (SELECT COUNT_BIG(*) FROM agg.daily_borough) + (SELECT COUNT_BIG(*) FROM agg.zone_monthly);
        EXEC etl.usp_log_step @run_id, 'build_aggregates', 'SUCCEEDED', @n, 'monthly_kpi, daily_borough, hourly_weekday, zone_flow, zone_monthly, dq_month, dq_rule_month';
    END TRY
    BEGIN CATCH
        DECLARE @err varchar(4000) = ERROR_MESSAGE();
        EXEC etl.usp_log_step @run_id, 'build_aggregates', 'FAILED', NULL, @err;
        THROW;
    END CATCH
END
GO

-- ---------------------------------------------------------------------
IF OBJECT_ID('etl.usp_run_full', 'P') IS NOT NULL DROP PROCEDURE etl.usp_run_full;
GO
CREATE PROCEDURE etl.usp_run_full
    @year   smallint,
    @run_id varchar(64) = 'manual'
AS
BEGIN
    SET NOCOUNT ON;
    EXEC etl.usp_load_dimensions @run_id;
    DECLARE @m smallint = 1;
    WHILE @m <= 12
    BEGIN
        IF EXISTS (SELECT 1 FROM [LH_Silver].[dbo].[silver_yellow_trips] WHERE [year] = @year AND [month] = @m)
            EXEC etl.usp_load_month @year, @m, @run_id;
        SET @m = @m + 1;
    END
    EXEC etl.usp_build_aggregates @run_id;
END
GO

-- ---------------------------------------------------------------------
-- Statistics on the join keys of the fact table (query optimiser hints)
-- ---------------------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM sys.stats WHERE name = 'st_fact_trip_date') CREATE STATISTICS st_fact_trip_date ON fact.fact_trip (date_key);
GO
IF NOT EXISTS (SELECT 1 FROM sys.stats WHERE name = 'st_fact_trip_pickup_zone') CREATE STATISTICS st_fact_trip_pickup_zone ON fact.fact_trip (pickup_zone_key);
GO
IF NOT EXISTS (SELECT 1 FROM sys.stats WHERE name = 'st_fact_trip_dropoff_zone') CREATE STATISTICS st_fact_trip_dropoff_zone ON fact.fact_trip (dropoff_zone_key);
GO
IF NOT EXISTS (SELECT 1 FROM sys.stats WHERE name = 'st_fact_trip_month') CREATE STATISTICS st_fact_trip_month ON fact.fact_trip (month_number);
GO
