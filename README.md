# E-commerce App User Conversion and Retention Analysis

Data Analyst portfolio project using **Python, pandas, NumPy, and matplotlib**.

## Business Objective

Analyze e-commerce app behavior logs to understand:

- How users move through the funnel from product view to cart to purchase
- How monthly active users and buyers retain over time
- Which brands, products, categories, and price buckets drive purchase value
- What data quality issues may affect reporting and business decisions

## Dataset

- Source files: five monthly e-commerce app event CSVs covering October 2019 through February 2020
- Raw data policy: the original ZIP/CSV files are not committed because they are large; place the raw archive locally and pass its path through `--zip-path`
- Rows processed: 20,692,840
- Date range: 2019-10-01 00:00:00 UTC to 2020-02-29 23:59:59 UTC
- Months analyzed: 2019-10, 2019-11, 2019-12, 2020-01, 2020-02

## Key Findings

- The project processed 20,692,840 app events across 5 months, with 1,287,007 purchase events.
- Total observed purchase revenue is $6,348,004.87; 2019-11 is the strongest revenue month.
- The latest month, 2020-02, converted 6.59% of active users into buyers.
- Average next-month active retention is 14.86%, which indicates a clear opportunity for lifecycle CRM.
- Among named brands, runail leads revenue at $343,433.19.
- The best normal price bucket by purchase-per-view rate is $0-1 at 35.26%.
- Non-positive price records are separated from normal pricing analysis because they may represent refunds, discounts, or data quality issues.

## Business Recommendations

- Prioritize cart recovery. Latest user cart-to-purchase conversion is 28.86%, so abandoned-cart push/email tests should be a first experiment.
- Create repeat-purchase journeys for recent buyers using replenishment reminders, loyalty offers, and post-purchase education.
- Use high-demand brands such as runail, grattol, irisk, uno, strong in search suggestions, homepage modules, and campaign landing pages.
- Design bundle and cross-sell tests around high-converting price buckets such as $0-1, $1-5.
- Improve product metadata capture, especially brand and category code fields, before building personalization or recommendation models.
- Audit non-positive price purchase records separately so revenue and pricing analysis stay clean.

## Deliverables

- `scripts/01_run_pandas_analysis.py`: pandas chunked ETL and KPI generation
- `scripts/02_generate_report.py`: matplotlib charts, HTML report, README, and notebook generation
- `data/processed/ecommerce_analysis_outputs.xlsx`: Excel workbook for stakeholder review
- `data/processed/*.csv`: cleaned KPI and analysis tables
- `report/figures/*.png`: matplotlib chart outputs
- `report/ecommerce_conversion_retention_report.html`: final portfolio report
- `notebooks/ecommerce_app_user_conversion_retention_analysis.ipynb`: notebook-style walkthrough

## Reproduce

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python scripts\01_run_pandas_analysis.py --zip-path "path/to/archive.zip" --output-dir data/processed
.\.venv\Scripts\python scripts\02_generate_report.py --data-dir data/processed --report-dir report --project-root .
```

## Metric Definitions

- Revenue: sum of `price` for purchase events
- User conversion: monthly unique-user movement from view/cart to purchase
- Session conversion: monthly unique-session movement through the funnel
- Active retention: users active in one month who are active again in the next month
- Buyer retention: buyers in one month who purchase again in the next month
- Cohort retention: users grouped by first observed active or purchase month

## Data Quality Notes

- `category_code` has high missingness, so category analysis falls back to `category_id`.
- `brand` has meaningful missingness and is labeled as `(missing)`.
- Non-positive price records are kept for audit but separated from normal price bucket interpretation.
