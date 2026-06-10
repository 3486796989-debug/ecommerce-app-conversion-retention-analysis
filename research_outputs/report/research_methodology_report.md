# Research-Style E-commerce App Analysis

## Research Questions

- How do users move from product views to carts and purchases?
- How stable is user retention across monthly cohorts?
- Which brands, categories, products, and price buckets drive revenue and conversion?
- Which user segments are most valuable or most likely to churn?
- What data quality risks should be considered before business decisions?

## Data Scope

- Rows processed: 20,692,840
- Months analyzed: 2019-10, 2019-11, 2019-12, 2020-01, 2020-02
- Date range: 2019-10-01 00:00:00+00:00 to 2020-02-29 23:59:59+00:00
- Purchase events: 1,287,007
- Purchase revenue: $6,348,004.87

## Methodology

1. Read monthly CSV files directly from the source ZIP archive using pandas chunks.
2. Standardized event types, timestamp fields, brand/category keys, user/session identifiers, and price buckets.
3. Separated non-positive price records from normal pricing analysis for auditability.
4. Calculated monthly user funnel metrics, session funnel metrics, retention rates, and Wilson confidence intervals.
5. Built active-user and buyer cohort retention matrices.
6. Generated behavior segments and RFM buyer segments.
7. Produced visual outputs for data quality, revenue trend, funnel, cohort retention, brand revenue, price conversion, time patterns, and user segments.

## Key Findings

- Highest revenue month: 2019-11 ($1,531,016.90)
- Average next-month active retention: 14.86%
- Top named brand by revenue: runail ($343,433.19)
- Best normal price bucket by purchase/view rate: $0-1 (35.26%)

## Data Quality Notes

```text
              quality_check  affected_rows  affected_rate                                                       interpretation
         missing_event_time              0       0.000000                                         Missing values in raw column
         missing_event_type              0       0.000000                                         Missing values in raw column
         missing_product_id              0       0.000000                                         Missing values in raw column
        missing_category_id              0       0.000000                                         Missing values in raw column
      missing_category_code       20339246       0.982912                                         Missing values in raw column
              missing_brand        8757117       0.423196                                         Missing values in raw column
              missing_price              0       0.000000                                         Missing values in raw column
            missing_user_id              0       0.000000                                         Missing values in raw column
       missing_user_session           4598       0.000222                                         Missing values in raw column
duplicate_rows_within_chunk        1109095       0.053598   Exact duplicated raw records detected within each processing chunk
         invalid_event_type              0       0.000000 Events outside expected view/cart/remove_from_cart/purchase taxonomy
```

## Output Files

- Tables: `C:\Users\ujun6\Documents\Codex\2026-06-10\files-mentioned-by-the-user-archive\outputs\ecommerce_app_user_conversion_retention_analysis\research_outputs\tables`
- Figures: `C:\Users\ujun6\Documents\Codex\2026-06-10\files-mentioned-by-the-user-archive\outputs\ecommerce_app_user_conversion_retention_analysis\research_outputs\figures`
- Workbook: `C:\Users\ujun6\Documents\Codex\2026-06-10\files-mentioned-by-the-user-archive\outputs\ecommerce_app_user_conversion_retention_analysis\research_outputs\research_analysis_workbook.xlsx`
