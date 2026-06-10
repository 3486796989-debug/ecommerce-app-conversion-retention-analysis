"""Generate charts, HTML report, README, and notebook for the DA portfolio project."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


plt.rcParams.update(
    {
        "figure.dpi": 140,
        "savefig.dpi": 160,
        "font.family": "DejaVu Sans",
        "axes.edgecolor": "#CBD5E1",
        "axes.labelcolor": "#172033",
        "axes.titleweight": "bold",
        "axes.titlesize": 12,
        "xtick.color": "#475569",
        "ytick.color": "#475569",
        "grid.color": "#E2E8F0",
        "grid.linewidth": 0.8,
    }
)


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def money(value: float) -> str:
    return f"${value:,.2f}"


def integer(value: float) -> str:
    return f"{int(round(value)):,}"


def read_tables(data_dir: Path) -> Dict[str, pd.DataFrame]:
    table_names = [
        "kpi_monthly_summary",
        "retention_month_to_month",
        "active_cohort_retention",
        "purchase_cohort_retention",
        "daily_trend",
        "hourly_pattern",
        "top_brands",
        "top_categories",
        "top_products",
        "price_bucket_analysis",
        "data_quality_summary",
        "file_profile",
        "user_frequency_summary",
    ]
    return {name: pd.read_csv(data_dir / f"{name}.csv") for name in table_names}


def save_monthly_revenue_chart(monthly: pd.DataFrame, figure_dir: Path) -> str:
    path = figure_dir / "01_monthly_revenue_and_purchase_rate.png"
    fig, ax1 = plt.subplots(figsize=(9, 4.8))
    ax1.bar(monthly["month"], monthly["revenue"], color="#2563EB", alpha=0.86, label="Revenue")
    ax1.set_ylabel("Revenue")
    ax1.yaxis.set_major_formatter(lambda x, _: f"${x/1_000_000:.1f}M")
    ax1.grid(axis="y")

    ax2 = ax1.twinx()
    ax2.plot(monthly["month"], monthly["active_user_purchase_rate"], color="#0F766E", marker="o", linewidth=2.5, label="Active user purchase rate")
    ax2.set_ylabel("Active user purchase rate")
    ax2.yaxis.set_major_formatter(lambda x, _: f"{x*100:.1f}%")

    ax1.set_title("Monthly Revenue and Active User Purchase Rate")
    fig.legend(loc="upper center", bbox_to_anchor=(0.5, 0.02), ncol=2, frameon=False)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path.name


def save_funnel_chart(monthly: pd.DataFrame, figure_dir: Path) -> str:
    path = figure_dir / "02_monthly_user_funnel.png"
    fig, ax = plt.subplots(figsize=(9, 4.8))
    funnel_columns = ["view_users", "cart_users", "buyers"]
    colors = ["#2563EB", "#B45309", "#0F766E"]
    x = np.arange(len(monthly))
    width = 0.23
    for idx, column in enumerate(funnel_columns):
        ax.bar(x + (idx - 1) * width, monthly[column], width=width, label=column.replace("_", " ").title(), color=colors[idx])
    ax.set_xticks(x)
    ax.set_xticklabels(monthly["month"])
    ax.set_ylabel("Unique users")
    ax.yaxis.set_major_formatter(lambda value, _: f"{value/1000:.0f}K")
    ax.set_title("Monthly User Funnel: View to Cart to Purchase")
    ax.legend(frameon=False)
    ax.grid(axis="y")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path.name


def save_cohort_heatmap(cohort: pd.DataFrame, figure_dir: Path, file_name: str, title: str) -> str:
    path = figure_dir / file_name
    rate_columns = [column for column in cohort.columns if column.endswith("_rate")]
    matrix = cohort[rate_columns].astype(float).to_numpy()
    matrix = np.ma.masked_invalid(matrix)

    fig, ax = plt.subplots(figsize=(9, 4.8))
    image = ax.imshow(matrix, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    ax.set_title(title)
    ax.set_xticks(np.arange(len(rate_columns)))
    ax.set_xticklabels([column.replace("_rate", "").upper() for column in rate_columns])
    ax.set_yticks(np.arange(len(cohort)))
    ax.set_yticklabels(cohort["cohort_month"])
    ax.set_xlabel("Months after cohort month")
    ax.set_ylabel("Cohort month")

    for row_idx in range(matrix.shape[0]):
        for col_idx in range(matrix.shape[1]):
            value = matrix[row_idx, col_idx]
            if np.ma.is_masked(value):
                continue
            text_color = "white" if float(value) > 0.5 else "#172033"
            ax.text(col_idx, row_idx, f"{float(value)*100:.1f}%", ha="center", va="center", fontsize=8, color=text_color)

    cbar = fig.colorbar(image, ax=ax, fraction=0.035, pad=0.04)
    cbar.ax.yaxis.set_major_formatter(lambda value, _: f"{value*100:.0f}%")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path.name


def save_top_brand_chart(brands: pd.DataFrame, figure_dir: Path) -> str:
    path = figure_dir / "05_top_brands_by_revenue.png"
    top_brands = brands.loc[brands["brand"].ne("(missing)")].head(10).sort_values("revenue")
    fig, ax = plt.subplots(figsize=(8.6, 5))
    ax.barh(top_brands["brand"], top_brands["revenue"], color="#2563EB")
    ax.set_xlabel("Revenue")
    ax.xaxis.set_major_formatter(lambda value, _: f"${value/1000:.0f}K")
    ax.set_title("Top Named Brands by Purchase Revenue")
    ax.grid(axis="x")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path.name


def save_price_bucket_chart(price_buckets: pd.DataFrame, figure_dir: Path) -> str:
    path = figure_dir / "06_price_bucket_conversion.png"
    normal_prices = price_buckets.loc[price_buckets["price_bucket"].ne("non-positive")]

    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    ax.bar(normal_prices["price_bucket"], normal_prices["purchase_per_view_rate"], color="#0F766E", alpha=0.88)
    ax.set_ylabel("Purchase / view rate")
    ax.yaxis.set_major_formatter(lambda value, _: f"{value*100:.0f}%")
    ax.set_xlabel("Price bucket")
    ax.set_title("Conversion Rate by Price Bucket")
    ax.grid(axis="y")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path.name


def save_daily_revenue_chart(daily: pd.DataFrame, figure_dir: Path) -> str:
    path = figure_dir / "07_daily_revenue_trend.png"
    daily = daily.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.plot(daily["date"], daily["revenue"], color="#2563EB", linewidth=1.8)
    ax.set_ylabel("Revenue")
    ax.yaxis.set_major_formatter(lambda value, _: f"${value/1000:.0f}K")
    ax.set_title("Daily Revenue Trend")
    ax.grid(axis="y")
    fig.autofmt_xdate(rotation=30)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path.name


def save_hourly_purchase_chart(hourly: pd.DataFrame, figure_dir: Path) -> str:
    path = figure_dir / "08_hourly_purchase_pattern.png"
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.bar(hourly["hour"].astype(str), hourly["purchase_events"], color="#B45309", alpha=0.9)
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Purchase events")
    ax.set_title("Purchase Events by Hour")
    ax.grid(axis="y")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path.name


def format_table(df: pd.DataFrame, columns: List[str], percent_cols: List[str] = None, money_cols: List[str] = None, int_cols: List[str] = None, limit: int = 10) -> str:
    percent_cols = percent_cols or []
    money_cols = money_cols or []
    int_cols = int_cols or []
    out = df[columns].head(limit).copy()
    for column in percent_cols:
        out[column] = out[column].astype(float).map(pct)
    for column in money_cols:
        out[column] = out[column].astype(float).map(money)
    for column in int_cols:
        out[column] = out[column].astype(float).map(integer)
    return out.to_html(index=False, classes="data-table", border=0)


def build_insights(summary: dict, tables: Dict[str, pd.DataFrame]) -> List[str]:
    monthly = tables["kpi_monthly_summary"]
    retention = tables["retention_month_to_month"]
    brands = tables["top_brands"]
    prices = tables["price_bucket_analysis"]

    top_named_brand = brands.loc[brands["brand"].ne("(missing)")].iloc[0]
    normal_prices = prices.loc[prices["price_bucket"].ne("non-positive")]
    best_price = normal_prices.sort_values("purchase_per_view_rate", ascending=False).iloc[0]
    latest = monthly.iloc[-1]

    return [
        f"The project processed {summary['row_count']:,} app events across {len(summary['months'])} months, with {summary['total_purchase_events']:,} purchase events.",
        f"Total observed purchase revenue is {money(summary['total_revenue'])}; {summary['highest_revenue_month']} is the strongest revenue month.",
        f"The latest month, {latest['month']}, converted {pct(latest['active_user_purchase_rate'])} of active users into buyers.",
        f"Average next-month active retention is {pct(summary['avg_next_month_active_retention'])}, which indicates a clear opportunity for lifecycle CRM.",
        f"Among named brands, {top_named_brand['brand']} leads revenue at {money(top_named_brand['revenue'])}.",
        f"The best normal price bucket by purchase-per-view rate is {best_price['price_bucket']} at {pct(best_price['purchase_per_view_rate'])}.",
        "Non-positive price records are separated from normal pricing analysis because they may represent refunds, discounts, or data quality issues.",
    ]


def build_recommendations(tables: Dict[str, pd.DataFrame]) -> List[str]:
    monthly = tables["kpi_monthly_summary"]
    brands = tables["top_brands"].loc[tables["top_brands"]["brand"].ne("(missing)")].head(5)
    prices = tables["price_bucket_analysis"].loc[tables["price_bucket_analysis"]["price_bucket"].ne("non-positive")]
    best_prices = prices.sort_values("purchase_per_view_rate", ascending=False).head(2)
    latest = monthly.iloc[-1]

    return [
        f"Prioritize cart recovery. Latest user cart-to-purchase conversion is {pct(latest['user_cart_to_purchase_rate'])}, so abandoned-cart push/email tests should be a first experiment.",
        "Create repeat-purchase journeys for recent buyers using replenishment reminders, loyalty offers, and post-purchase education.",
        f"Use high-demand brands such as {', '.join(brands['brand'].tolist())} in search suggestions, homepage modules, and campaign landing pages.",
        f"Design bundle and cross-sell tests around high-converting price buckets such as {', '.join(best_prices['price_bucket'].tolist())}.",
        "Improve product metadata capture, especially brand and category code fields, before building personalization or recommendation models.",
        "Audit non-positive price purchase records separately so revenue and pricing analysis stay clean.",
    ]


def write_html_report(project_root: Path, report_dir: Path, summary: dict, tables: Dict[str, pd.DataFrame], figures: Dict[str, str]) -> None:
    monthly = tables["kpi_monthly_summary"]
    data_quality = tables["data_quality_summary"]
    brands = tables["top_brands"]
    products = tables["top_products"]
    categories = tables["top_categories"]
    prices = tables["price_bucket_analysis"]

    insights = build_insights(summary, tables)
    recommendations = build_recommendations(tables)

    cards = [
        ("Events", f"{summary['row_count']:,}", f"{summary['months'][0]} to {summary['months'][-1]}"),
        ("Active Users", f"{summary['unique_active_users']:,}", "Observed users"),
        ("Buyers", f"{summary['unique_buyers']:,}", "Purchased at least once"),
        ("Revenue", money(summary["total_revenue"]), "Purchase event value"),
        ("Latest Purchase Rate", pct(summary["latest_active_user_purchase_rate"]), summary["latest_month"]),
        ("Avg Next-Month Retention", pct(summary["avg_next_month_active_retention"]), "Active users"),
    ]

    card_html = "".join(
        f"""
        <div class="metric">
          <div class="metric-label">{label}</div>
          <div class="metric-value">{value}</div>
          <div class="metric-detail">{detail}</div>
        </div>
        """
        for label, value, detail in cards
    )
    insight_html = "".join(f"<li>{item}</li>" for item in insights)
    recommendation_html = "".join(f"<li>{item}</li>" for item in recommendations)

    monthly_table = format_table(
        monthly,
        [
            "month",
            "active_users",
            "cart_users",
            "buyers",
            "active_user_purchase_rate",
            "user_cart_to_purchase_rate",
            "revenue",
            "aov_purchase_session",
        ],
        percent_cols=["active_user_purchase_rate", "user_cart_to_purchase_rate"],
        money_cols=["revenue", "aov_purchase_session"],
        int_cols=["active_users", "cart_users", "buyers"],
        limit=len(monthly),
    )
    brand_table = format_table(
        brands.loc[brands["brand"].ne("(missing)")],
        ["brand", "purchase_events", "revenue", "purchase_per_view_rate"],
        percent_cols=["purchase_per_view_rate"],
        money_cols=["revenue"],
        int_cols=["purchase_events"],
        limit=12,
    )
    product_table = format_table(
        products,
        ["product_id", "brand", "purchase_events", "revenue", "purchase_per_view_rate"],
        percent_cols=["purchase_per_view_rate"],
        money_cols=["revenue"],
        int_cols=["purchase_events"],
        limit=12,
    )
    category_table = format_table(
        categories,
        ["category_key", "purchase_events", "revenue", "purchase_per_view_rate"],
        percent_cols=["purchase_per_view_rate"],
        money_cols=["revenue"],
        int_cols=["purchase_events"],
        limit=12,
    )
    price_table = format_table(
        prices,
        ["price_bucket", "view_events", "purchase_events", "purchase_per_view_rate", "revenue"],
        percent_cols=["purchase_per_view_rate"],
        money_cols=["revenue"],
        int_cols=["view_events", "purchase_events"],
        limit=len(prices),
    )
    quality_table = format_table(
        data_quality,
        ["field", "missing_values", "missing_rate"],
        percent_cols=["missing_rate"],
        int_cols=["missing_values"],
        limit=len(data_quality),
    )

    css = """
    :root {
      --ink: #172033;
      --muted: #5B6475;
      --line: #D8DEE9;
      --soft: #F6F8FB;
      --blue: #2563EB;
      --panel: #FFFFFF;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      color: var(--ink);
      background: #F3F5F8;
      line-height: 1.55;
    }
    header { background: #111827; color: #fff; padding: 44px 7vw 36px; }
    header p { max-width: 960px; color: #DDE5F2; font-size: 17px; margin: 12px 0 0; }
    h1 { font-size: clamp(34px, 5vw, 56px); line-height: 1.05; margin: 0; letter-spacing: 0; }
    h2 { font-size: 25px; margin: 0 0 14px; }
    h3 { font-size: 17px; margin: 20px 0 10px; }
    main { padding: 28px 7vw 56px; }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 24px;
      margin: 18px 0;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }
    .metric { border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: var(--soft); }
    .metric-label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .05em; }
    .metric-value { font-size: 24px; line-height: 1.25; font-weight: 760; margin-top: 5px; }
    .metric-detail { color: var(--muted); font-size: 13px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; }
    img.chart { width: 100%; border: 1px solid var(--line); border-radius: 8px; background: #fff; }
    table.data-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }
    table.data-table th, table.data-table td { border-bottom: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }
    table.data-table th { background: var(--soft); color: var(--muted); font-weight: 650; }
    li + li { margin-top: 8px; }
    .note { color: var(--muted); font-size: 13px; }
    footer { color: var(--muted); padding: 0 7vw 34px; font-size: 13px; }
    @media (max-width: 720px) {
      header, main, footer { padding-left: 18px; padding-right: 18px; }
      section { padding: 18px; }
      .grid { grid-template-columns: 1fr; }
      table.data-table { display: block; overflow-x: auto; white-space: nowrap; }
    }
    """

    report_html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>E-commerce App User Conversion and Retention Analysis</title>
  <style>{css}</style>
</head>
<body>
  <header>
    <h1>E-commerce App User Conversion and Retention Analysis</h1>
    <p>Data Analyst portfolio project using pandas, NumPy, and matplotlib to diagnose user conversion, monthly retention, revenue quality, and merchandising opportunities.</p>
  </header>
  <main>
    <section>
      <h2>Executive Summary</h2>
      <ul>{insight_html}</ul>
      <div class="metrics">{card_html}</div>
    </section>
    <section>
      <h2>Business KPI Dashboard</h2>
      {monthly_table}
      <div class="grid">
        <img class="chart" src="figures/{figures['monthly_revenue']}" alt="Monthly revenue and purchase rate" />
        <img class="chart" src="figures/{figures['funnel']}" alt="Monthly user funnel" />
      </div>
    </section>
    <section>
      <h2>Cohort Retention</h2>
      <div class="grid">
        <img class="chart" src="figures/{figures['active_cohort']}" alt="Active user cohort retention" />
        <img class="chart" src="figures/{figures['purchase_cohort']}" alt="Purchase cohort retention" />
      </div>
      <p class="note">Cohorts are based on each user's first observed active month or first observed purchase month.</p>
    </section>
    <section>
      <h2>Merchandising Analysis</h2>
      <div class="grid">
        <div>
          <h3>Top Named Brands</h3>
          {brand_table}
        </div>
        <img class="chart" src="figures/{figures['top_brands']}" alt="Top brands by revenue" />
      </div>
      <h3>Top Products</h3>
      {product_table}
      <h3>Top Categories</h3>
      {category_table}
    </section>
    <section>
      <h2>Pricing and Timing</h2>
      <div class="grid">
        <div>
          <h3>Price Buckets</h3>
          {price_table}
        </div>
        <img class="chart" src="figures/{figures['price_bucket']}" alt="Price bucket conversion" />
        <img class="chart" src="figures/{figures['daily_revenue']}" alt="Daily revenue trend" />
        <img class="chart" src="figures/{figures['hourly_purchase']}" alt="Hourly purchase events" />
      </div>
    </section>
    <section>
      <h2>Recommendations</h2>
      <ul>{recommendation_html}</ul>
    </section>
    <section>
      <h2>Data Quality</h2>
      {quality_table}
      <p class="note">Category code and brand fields have meaningful missingness. The analysis keeps those records, labels them clearly, and uses category ID fallback where needed.</p>
    </section>
  </main>
  <footer>Generated from pandas analysis outputs in <code>data/processed</code>.</footer>
</body>
</html>
"""

    (report_dir / "ecommerce_conversion_retention_report.html").write_text(report_html, encoding="utf-8")


def write_readme(project_root: Path, summary: dict, tables: Dict[str, pd.DataFrame]) -> None:
    insights = build_insights(summary, tables)
    recommendations = build_recommendations(tables)

    readme = f"""# E-commerce App User Conversion and Retention Analysis

Data Analyst portfolio project using **Python, pandas, NumPy, and matplotlib**.

## Business Objective

Analyze e-commerce app behavior logs to understand:

- How users move through the funnel from product view to cart to purchase
- How monthly active users and buyers retain over time
- Which brands, products, categories, and price buckets drive purchase value
- What data quality issues may affect reporting and business decisions

## Dataset

- Source archive: `{summary['source_zip']}`
- Rows processed: {summary['row_count']:,}
- Date range: {summary['min_event_time']} to {summary['max_event_time']}
- Months analyzed: {', '.join(summary['months'])}

## Key Findings

{chr(10).join(f'- {item}' for item in insights)}

## Business Recommendations

{chr(10).join(f'- {item}' for item in recommendations)}

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
.\\.venv\\Scripts\\python -m pip install -r requirements.txt
.\\.venv\\Scripts\\python scripts\\01_run_pandas_analysis.py --zip-path "C:/Users/ujun6/Desktop/archive (1).zip" --output-dir data/processed
.\\.venv\\Scripts\\python scripts\\02_generate_report.py --data-dir data/processed --report-dir report --project-root .
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
"""
    (project_root / "README.md").write_text(readme, encoding="utf-8")


def write_notebook(project_root: Path) -> None:
    notebook_dir = project_root / "notebooks"
    notebook_dir.mkdir(parents=True, exist_ok=True)
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# E-commerce App User Conversion and Retention Analysis\n",
                    "\n",
                    "Portfolio-style notebook using pandas, NumPy, and matplotlib. The full raw-data processing pipeline lives in `scripts/01_run_pandas_analysis.py`; this notebook reads the processed outputs and walks through the business findings.\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "from pathlib import Path\n",
                    "import pandas as pd\n",
                    "import numpy as np\n",
                    "import matplotlib.pyplot as plt\n",
                    "\n",
                    "DATA_DIR = Path('../data/processed')\n",
                    "monthly = pd.read_csv(DATA_DIR / 'kpi_monthly_summary.csv')\n",
                    "retention = pd.read_csv(DATA_DIR / 'retention_month_to_month.csv')\n",
                    "brands = pd.read_csv(DATA_DIR / 'top_brands.csv')\n",
                    "prices = pd.read_csv(DATA_DIR / 'price_bucket_analysis.csv')\n",
                    "monthly.head()\n",
                ],
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["## Monthly Funnel KPIs\n"],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "monthly[['month', 'active_users', 'cart_users', 'buyers', 'active_user_purchase_rate', 'revenue']]\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "fig, ax1 = plt.subplots(figsize=(9, 4))\n",
                    "ax1.bar(monthly['month'], monthly['revenue'], color='#2563EB', alpha=.85)\n",
                    "ax1.set_ylabel('Revenue')\n",
                    "ax2 = ax1.twinx()\n",
                    "ax2.plot(monthly['month'], monthly['active_user_purchase_rate'], color='#0F766E', marker='o')\n",
                    "ax2.set_ylabel('Active user purchase rate')\n",
                    "plt.title('Monthly Revenue and Purchase Rate')\n",
                    "plt.show()\n",
                ],
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["## Retention\n"],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "retention[['month', 'next_month', 'active_next_month_retention_rate', 'buyer_repeat_purchase_next_month_rate']]\n",
                ],
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["## Merchandising and Pricing\n"],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "brands.query(\"brand != '(missing)'\").head(10)[['brand', 'purchase_events', 'revenue', 'purchase_per_view_rate']]\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "prices.query(\"price_bucket != 'non-positive'\")[['price_bucket', 'view_events', 'purchase_events', 'purchase_per_view_rate', 'revenue']]\n",
                ],
            },
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    (notebook_dir / "ecommerce_app_user_conversion_retention_analysis.ipynb").write_text(
        json.dumps(notebook, indent=2),
        encoding="utf-8",
    )


def generate(data_dir: Path, report_dir: Path, project_root: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    figure_dir = report_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)

    tables = read_tables(data_dir)
    summary = json.loads((data_dir / "executive_summary.json").read_text(encoding="utf-8"))

    figures = {
        "monthly_revenue": save_monthly_revenue_chart(tables["kpi_monthly_summary"], figure_dir),
        "funnel": save_funnel_chart(tables["kpi_monthly_summary"], figure_dir),
        "active_cohort": save_cohort_heatmap(tables["active_cohort_retention"], figure_dir, "03_active_user_cohort_retention.png", "Active User Cohort Retention"),
        "purchase_cohort": save_cohort_heatmap(tables["purchase_cohort_retention"], figure_dir, "04_purchase_cohort_retention.png", "Purchase Cohort Retention"),
        "top_brands": save_top_brand_chart(tables["top_brands"], figure_dir),
        "price_bucket": save_price_bucket_chart(tables["price_bucket_analysis"], figure_dir),
        "daily_revenue": save_daily_revenue_chart(tables["daily_trend"], figure_dir),
        "hourly_purchase": save_hourly_purchase_chart(tables["hourly_pattern"], figure_dir),
    }

    write_html_report(project_root, report_dir, summary, tables, figures)
    write_readme(project_root, summary, tables)
    write_notebook(project_root)

    print(f"[complete] Wrote report assets to {report_dir}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate DA portfolio report from pandas analysis outputs.")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    generate(args.data_dir, args.report_dir, args.project_root)
