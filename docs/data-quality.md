# Data quality

Every trip published by the TLC goes through the same gate in `NB_02_Bronze_To_Silver`: schema contract, removal of
exact duplicates, then ten rules evaluated on every row. Nothing is dropped silently: a row that fails at least one
rule is written to `silver_yellow_trips_rejected` together with the list of rules it failed, and the counts are logged
per month (`silver_dq_log`) and per rule (`silver_dq_rule_log`). The warehouse copies these logs into `agg.dq_month` and
`agg.dq_rule_month`, which feed the Pipeline and Quality page of the report.

## Result for 2025

| | Rows | Share of rows read |
|---|---:|---:|
| Rows read from the 12 TLC files | 48,722,602 | 100.00 % |
| Exact duplicates removed | 1 | 0.00 % |
| Rows accepted into Silver, then Gold | 45,531,235 | 93.45 % |
| Rows quarantined | 3,191,366 | 6.55 % |

Every accepted row reached the fact table: the Silver, staging and fact counts match for all 12 months
(see [reconciliation](#reconciliation-silver-to-gold)).

## Rules

A rule is an expression that is true when the row fails. A row can fail several rules, so the rule counts add up to
more than the number of quarantined rows.

| Rule | Fails when | Rows in 2025 |
|------|-----------|-------------:|
| `negative_amount` | fare, total or tip below zero (negative amounts usually mark refunds or voided trips) | 2,853,594 |
| `zero_length_trip` | distance of 0 and duration under 1 minute | 383,241 |
| `implausible_speed` | average speed above 100 mph on a trip of at least 1 minute | 4,650 |
| `invalid_duration` | dropoff before pickup, or a trip longer than 24 hours | 2,587 |
| `invalid_distance` | distance below 0 or above 200 miles | 2,238 |
| `outside_file_month` | pickup date outside the month of the file it comes from | 214 |
| `implausible_fare` | fare or total above $1,000 | 85 |
| `missing_timestamp` | pickup or dropoff timestamp missing | 0 |
| `missing_location` | pickup or dropoff zone missing | 0 |
| `invalid_passengers` | more than 9 passengers | 0 |

Rules that never fired in 2025 stay in place: they protect the pipeline against future files.

## By month

| Month | Rows read | Accepted | Quarantined | Reject rate | Silver time (s) |
|-------|----------:|---------:|------------:|------------:|----------------:|
| 2025-01 | 3,475,226 | 3,307,980 | 167,246 | 4.81 % | 78 |
| 2025-02 | 3,577,543 | 3,373,525 | 204,018 | 5.70 % | 85 |
| 2025-03 | 4,145,257 | 3,910,827 | 234,430 | 5.66 % | 87 |
| 2025-04 | 3,970,553 | 3,757,049 | 213,504 | 5.38 % | 103 |
| 2025-05 | 4,591,845 | 4,235,976 | 355,869 | 7.75 % | 93 |
| 2025-06 | 4,322,960 | 4,016,922 | 306,038 | 7.08 % | 114 |
| 2025-07 | 3,898,963 | 3,622,752 | 276,210 | 7.08 % | 91 |
| 2025-08 | 3,574,091 | 3,282,749 | 291,342 | 8.15 % | 90 |
| 2025-09 | 4,251,015 | 3,966,949 | 284,066 | 6.68 % | 89 |
| 2025-10 | 4,428,699 | 4,075,342 | 353,357 | 7.98 % | 91 |
| 2025-11 | 4,181,444 | 3,756,307 | 425,137 | 10.17 % | 99 |
| 2025-12 | 4,305,006 | 4,224,857 | 80,149 | 1.86 % | 94 |
| **2025** | **48,722,602** | **45,531,235** | **3,191,366** | **6.55 %** | **1,114** |

The reject rate is the share of quarantined rows among the rows left after duplicate removal. July holds the only
exact duplicate of the year. The twelve months are cleansed in about 19 minutes of Spark time in total.

## Reconciliation, Silver to Gold

`etl.usp_load_month` loads one month from Silver into staging and then into `fact.fact_trip` inside one transaction,
and compares the three row counts:

- if Silver has no row for the month, it raises error 50010;
- if the three counts differ, it writes the counts to `etl.load_control`, raises error 50020 and the pipeline stops;
- if they match, the month is marked as reconciled.

All 12 months of 2025 are reconciled: 45,531,235 rows in Silver, in staging and in the fact table.
