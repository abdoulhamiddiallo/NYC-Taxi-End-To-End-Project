# Data model

## Gold star schema (`WH_NYC_Taxi`)

The grain of `fact.fact_trip` is one valid taxi trip. Vendor, rate code, payment type and zone codes that the TLC data
dictionary does not list are mapped to an `Unknown` member, so a trip never loses its row because of an unexpected code.

```mermaid
erDiagram
    FACT_TRIP }o--|| DIM_DATE : "date_key"
    FACT_TRIP }o--|| DIM_HOUR : "hour_key"
    FACT_TRIP }o--|| DIM_ZONE : "pickup_zone_key"
    FACT_TRIP }o--|| DIM_ZONE : "dropoff_zone_key"
    FACT_TRIP }o--|| DIM_VENDOR : "vendor_key"
    FACT_TRIP }o--|| DIM_RATE_CODE : "rate_code_key"
    FACT_TRIP }o--|| DIM_PAYMENT_TYPE : "payment_type_key"
    FACT_TRIP }o--|| DIM_DISTANCE_BAND : "distance_band_key"

    FACT_TRIP {
        bigint trip_sk PK
        int date_key FK
        smallint hour_key FK
        int pickup_zone_key FK
        int dropoff_zone_key FK
        datetime2 pickup_datetime
        decimal trip_distance
        decimal duration_min
        decimal fare_amount
        decimal tip_amount
        decimal cbd_congestion_fee
        decimal total_amount
        bit is_airport_trip
    }
    DIM_DATE {
        int date_key PK
        date full_date
        varchar month_label
        varchar day_name
        bit is_holiday
        varchar day_type
    }
    DIM_HOUR {
        smallint hour_key PK
        varchar day_part
        bit is_rush_hour
    }
    DIM_ZONE {
        int zone_key PK
        varchar zone_name
        varchar borough
        bit is_airport
        float latitude
        float longitude
    }
    DIM_VENDOR {
        int vendor_key PK
        varchar vendor_name
    }
    DIM_RATE_CODE {
        int rate_code_key PK
        varchar rate_code_name
    }
    DIM_PAYMENT_TYPE {
        int payment_type_key PK
        varchar payment_type_name
        bit is_electronic
    }
    DIM_DISTANCE_BAND {
        smallint distance_band_key PK
        varchar distance_band
    }
```

| Schema | Tables | Role |
|--------|--------|------|
| `stg` | `stg_yellow_trips`, `stg_taxi_zones` | One month at a time, replaced on each load |
| `dim` | `dim_date` (2024 to 2026 calendar with US federal holidays and day type), `dim_hour` (day parts, rush hours 7 to 10 am and 4 to 7 pm), `dim_zone` (TLC taxi zones with centroids, plus an Unmapped member), `dim_vendor`, `dim_rate_code`, `dim_payment_type`, `dim_distance_band` | Conformed dimensions, loaded by `etl.usp_load_dimensions` |
| `fact` | `fact_trip` (45,531,235 rows, 30 columns) | Loaded month by month by `etl.usp_load_month` |
| `agg` | `monthly_kpi`, `daily_borough`, `hourly_weekday`, `zone_flow`, `zone_monthly`, `dq_month`, `dq_rule_month` | Serving aggregates, rebuilt by `etl.usp_build_aggregates` |
| `etl` | `run_log`, `load_control` | Step log of every procedure and reconciliation status of every month |

Primary keys are declared `NOT ENFORCED` for the optimiser, and the pipeline maintains statistics on the fact join keys.

## Semantic model (`SM_NYC_Taxi`)

![Model view of SM_NYC_Taxi](images/semantic-model.png)

A Direct Lake model on the warehouse tables. Relationships are single direction, many to one, and declared with
`relyOnReferentialIntegrity`: the reconciliation step guarantees the keys, so Direct Lake can use inner joins.

| Model table | Source | Role |
|-------------|--------|------|
| `Trips` | `fact.fact_trip` | Fact table, hidden; carries the 117 measures |
| `Date`, `Hour` | `dim.dim_date`, `dim.dim_hour` | Calendar, day type, hour and day part |
| `Pickup Zone`, `Dropoff Zone` | `dim.dim_zone` (role playing) | Zone, borough, airport flag, centroid for the map |
| `Vendor`, `Rate Code`, `Payment Type`, `Distance Band` | `dim.*` | Descriptive dimensions |
| `Zone Flow` | `agg.zone_flow` | Ranked origin to destination pairs |
| `Demand Profile` | `agg.hourly_weekday` | Weekday by hour profile |
| `Data Quality`, `Data Quality Rules` | `agg.dq_month`, `agg.dq_rule_month` | Quality gate results |
| `Load Control`, `Run Log` | `etl.load_control`, `etl.run_log` | Reconciliation and run history |

| From | To |
|------|----|
| `Trips[date_key]` | `Date[date_key]` |
| `Trips[hour_key]` | `Hour[hour_key]` |
| `Trips[pickup_zone_key]` | `Pickup Zone[zone_key]` |
| `Trips[dropoff_zone_key]` | `Dropoff Zone[zone_key]` |
| `Trips[vendor_key]` | `Vendor[vendor_key]` |
| `Trips[rate_code_key]` | `Rate Code[rate_code_key]` |
| `Trips[payment_type_key]` | `Payment Type[payment_type_key]` |
| `Trips[distance_band_key]` | `Distance Band[distance_band_key]` |
| `Zone Flow[pickup_zone_key]` | `Pickup Zone[zone_key]` |
| `Zone Flow[dropoff_zone_key]` | `Dropoff Zone[zone_key]` |
| `Data Quality Rules[Rule Month]` | `Data Quality[DQ Month]` |

The full list of measures, with their DAX, is in [measures.md](measures.md).
