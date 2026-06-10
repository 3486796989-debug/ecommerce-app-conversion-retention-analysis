"""Pandas-based data analysis pipeline for the e-commerce app dataset.

This script is written in a Data Analyst portfolio style:
1. Load large monthly CSV files from the source ZIP with pandas chunks.
2. Clean and standardize event, user, product, brand, category, and price fields.
3. Build business KPI tables for conversion, retention, revenue, and merchandising.
4. Export tidy CSV tables plus an Excel workbook for stakeholder review.

The dataset is large, so the script uses chunked processing instead of loading
all raw rows into memory at once.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd


MONTH_ABBR = {
    "Jan": "01",
    "Feb": "02",
    "Mar": "03",
    "Apr": "04",
    "May": "05",
    "Jun": "06",
    "Jul": "07",
    "Aug": "08",
    "Sep": "09",
    "Oct": "10",
    "Nov": "11",
    "Dec": "12",
}

RAW_COLUMNS = [
    "event_time",
    "event_type",
    "product_id",
    "category_id",
    "category_code",
    "brand",
    "price",
    "user_id",
    "user_session",
]

EVENT_TYPES = ["view", "cart", "remove_from_cart", "purchase"]
COUNT_COLUMNS = [
    "events",
    "view_events",
    "cart_events",
    "remove_from_cart_events",
    "purchase_events",
]


def month_from_file_name(file_name: str) -> str:
    year, month_abbr = Path(file_name).stem.split("-")
    return f"{year}-{MONTH_ABBR[month_abbr]}"


def safe_divide(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def add_frame(existing: Optional[pd.DataFrame], new: pd.DataFrame) -> pd.DataFrame:
    if existing is None:
        return new.copy()
    return existing.add(new, fill_value=0)


def standardize_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    """Clean raw chunk and create reusable analytical fields."""
    chunk = chunk.copy()

    for column in ["event_time", "event_type", "product_id", "category_id", "category_code", "brand", "user_id", "user_session"]:
        chunk[column] = chunk[column].astype("string").fillna("")

    chunk["price"] = pd.to_numeric(chunk["price"], errors="coerce").fillna(0.0).astype("float64")
    chunk["event_type"] = chunk["event_type"].str.strip().str.lower()
    chunk["brand_clean"] = chunk["brand"].str.strip().str.lower()
    chunk["brand_clean"] = chunk["brand_clean"].mask(chunk["brand_clean"].eq(""), "(missing)")

    category_code = chunk["category_code"].str.strip()
    category_id = chunk["category_id"].str.strip()
    chunk["category_key"] = np.where(
        category_code.ne(""),
        category_code,
        np.where(category_id.ne(""), "category_id:" + category_id.astype(str), "(missing)"),
    )

    chunk["date"] = chunk["event_time"].str.slice(0, 10)
    chunk["hour"] = chunk["event_time"].str.slice(11, 13)

    chunk["is_view"] = chunk["event_type"].eq("view").astype(np.int8)
    chunk["is_cart"] = chunk["event_type"].eq("cart").astype(np.int8)
    chunk["is_remove_from_cart"] = chunk["event_type"].eq("remove_from_cart").astype(np.int8)
    chunk["is_purchase"] = chunk["event_type"].eq("purchase").astype(np.int8)
    chunk["purchase_revenue"] = np.where(chunk["is_purchase"].eq(1), chunk["price"], 0.0)

    price = chunk["price"]
    conditions = [
        price.le(0),
        price.gt(0) & price.lt(1),
        price.ge(1) & price.lt(5),
        price.ge(5) & price.lt(10),
        price.ge(10) & price.lt(20),
        price.ge(20) & price.lt(50),
        price.ge(50) & price.lt(100),
        price.ge(100),
    ]
    labels = ["non-positive", "$0-1", "$1-5", "$5-10", "$10-20", "$20-50", "$50-100", "$100+"]
    chunk["price_bucket"] = np.select(conditions, labels, default="unknown")

    return chunk


def aggregate_by_key(chunk: pd.DataFrame, key: str) -> pd.DataFrame:
    grouped = (
        chunk.groupby(key, dropna=False)
        .agg(
            events=("event_type", "size"),
            view_events=("is_view", "sum"),
            cart_events=("is_cart", "sum"),
            remove_from_cart_events=("is_remove_from_cart", "sum"),
            purchase_events=("is_purchase", "sum"),
            revenue=("purchase_revenue", "sum"),
        )
        .sort_index()
    )
    return grouped


def finalize_dimension_table(df: pd.DataFrame, key_name: str, top_n: Optional[int] = None) -> pd.DataFrame:
    out = df.reset_index().rename(columns={df.index.name or "index": key_name})
    for column in COUNT_COLUMNS:
        out[column] = out[column].fillna(0).round().astype("int64")
    out["revenue"] = out["revenue"].fillna(0).astype(float).round(2)
    out["purchase_per_view_rate"] = np.where(out["view_events"].gt(0), out["purchase_events"] / out["view_events"], 0.0)
    out["avg_purchase_price"] = np.where(out["purchase_events"].gt(0), out["revenue"] / out["purchase_events"], 0.0)
    out = out.sort_values(["revenue", "purchase_events"], ascending=False)
    return out.head(top_n).reset_index(drop=True) if top_n else out.reset_index(drop=True)


def build_cohort_retention(months: List[str], monthly_sets: Dict[str, set]) -> pd.DataFrame:
    previous_users: set = set()
    rows = []

    for cohort_month in months:
        cohort_users = monthly_sets[cohort_month] - previous_users
        previous_users |= monthly_sets[cohort_month]
        cohort_size = len(cohort_users)

        row = {"cohort_month": cohort_month, "cohort_size": cohort_size}
        for offset, retention_month in enumerate(months[months.index(cohort_month) :]):
            retained_count = len(cohort_users & monthly_sets[retention_month]) if cohort_size else 0
            row[f"m{offset}_count"] = retained_count
            row[f"m{offset}_rate"] = safe_divide(retained_count, cohort_size)
        rows.append(row)

    return pd.DataFrame(rows)


def summarize_user_frequency(months: List[str], monthly_sets: Dict[str, set], buyer_sets: Dict[str, set]) -> pd.DataFrame:
    all_active_users = set().union(*monthly_sets.values())
    all_buyers = set().union(*buyer_sets.values())

    active_distribution = Counter(sum(user in monthly_sets[month] for month in months) for user in all_active_users)
    buyer_distribution = Counter(sum(user in buyer_sets[month] for month in months) for user in all_buyers)

    rows = []
    for month_count in range(1, len(months) + 1):
        rows.append(
            {
                "months_count": month_count,
                "active_users": active_distribution[month_count],
                "buyers": buyer_distribution[month_count],
            }
        )
    return pd.DataFrame(rows)


def save_excel_workbook(output_dir: Path, tables: Dict[str, pd.DataFrame]) -> None:
    workbook_path = output_dir / "ecommerce_analysis_outputs.xlsx"
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        for sheet_name, table in tables.items():
            clean_sheet_name = sheet_name[:31]
            table.to_excel(writer, sheet_name=clean_sheet_name, index=False)


def analyze(zip_path: Path, output_dir: Path, chunksize: int, max_rows_per_file: Optional[int]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as archive:
        csv_files = sorted(
            [name for name in archive.namelist() if name.lower().endswith(".csv")],
            key=month_from_file_name,
        )

    months = [month_from_file_name(name) for name in csv_files]

    monthly_stats = defaultdict(lambda: defaultdict(float))
    event_type_counts = Counter()
    missing_counts = Counter()
    file_profile_rows = []

    active_users_by_month = {month: set() for month in months}
    view_users_by_month = {month: set() for month in months}
    cart_users_by_month = {month: set() for month in months}
    buyers_by_month = {month: set() for month in months}

    daily_agg: Optional[pd.DataFrame] = None
    hourly_agg: Optional[pd.DataFrame] = None
    brand_agg: Optional[pd.DataFrame] = None
    category_agg: Optional[pd.DataFrame] = None
    product_agg: Optional[pd.DataFrame] = None
    price_bucket_agg: Optional[pd.DataFrame] = None

    product_brand = {}
    product_category = {}

    total_rows = 0
    min_event_time = None
    max_event_time = None

    with zipfile.ZipFile(zip_path) as archive:
        for file_name in csv_files:
            month = month_from_file_name(file_name)
            processed_in_file = 0
            file_min_time = None
            file_max_time = None

            session_sets = {
                "all": set(),
                "view": set(),
                "cart": set(),
                "purchase": set(),
            }
            purchase_session_revenue = defaultdict(float)

            print(f"[start] {file_name}", flush=True)
            with archive.open(file_name) as raw_file:
                reader = pd.read_csv(
                    raw_file,
                    chunksize=chunksize,
                    usecols=RAW_COLUMNS,
                    dtype={
                        "event_time": "string",
                        "event_type": "string",
                        "product_id": "string",
                        "category_id": "string",
                        "category_code": "string",
                        "brand": "string",
                        "user_id": "string",
                        "user_session": "string",
                    },
                    keep_default_na=False,
                    low_memory=False,
                )

                for chunk_number, raw_chunk in enumerate(reader, start=1):
                    if max_rows_per_file is not None:
                        remaining = max_rows_per_file - processed_in_file
                        if remaining <= 0:
                            break
                        raw_chunk = raw_chunk.head(remaining)

                    chunk = standardize_chunk(raw_chunk)
                    row_count = len(chunk)
                    processed_in_file += row_count
                    total_rows += row_count

                    for column in RAW_COLUMNS:
                        if column == "price":
                            missing_counts[column] += int(pd.to_numeric(raw_chunk[column], errors="coerce").isna().sum())
                        else:
                            missing_counts[column] += int(raw_chunk[column].astype("string").fillna("").eq("").sum())

                    chunk_min_time = chunk["event_time"].min()
                    chunk_max_time = chunk["event_time"].max()
                    min_event_time = chunk_min_time if min_event_time is None else min(min_event_time, chunk_min_time)
                    max_event_time = chunk_max_time if max_event_time is None else max(max_event_time, chunk_max_time)
                    file_min_time = chunk_min_time if file_min_time is None else min(file_min_time, chunk_min_time)
                    file_max_time = chunk_max_time if file_max_time is None else max(file_max_time, chunk_max_time)

                    event_counts = chunk["event_type"].value_counts()
                    event_type_counts.update(event_counts.to_dict())

                    monthly_stats[month]["total_events"] += row_count
                    monthly_stats[month]["revenue"] += chunk["purchase_revenue"].sum()
                    for event_type in EVENT_TYPES:
                        monthly_stats[month][f"{event_type}_events"] += int(event_counts.get(event_type, 0))

                    user_id = chunk["user_id"]
                    valid_user = user_id.ne("")
                    active_users_by_month[month].update(user_id[valid_user].unique().tolist())
                    view_users_by_month[month].update(chunk.loc[valid_user & chunk["event_type"].eq("view"), "user_id"].unique().tolist())
                    cart_users_by_month[month].update(chunk.loc[valid_user & chunk["event_type"].eq("cart"), "user_id"].unique().tolist())
                    buyers_by_month[month].update(chunk.loc[valid_user & chunk["event_type"].eq("purchase"), "user_id"].unique().tolist())

                    session_id = chunk["user_session"]
                    valid_session = session_id.ne("")
                    session_sets["all"].update(session_id[valid_session].unique().tolist())
                    session_sets["view"].update(chunk.loc[valid_session & chunk["event_type"].eq("view"), "user_session"].unique().tolist())
                    session_sets["cart"].update(chunk.loc[valid_session & chunk["event_type"].eq("cart"), "user_session"].unique().tolist())
                    session_sets["purchase"].update(chunk.loc[valid_session & chunk["event_type"].eq("purchase"), "user_session"].unique().tolist())

                    purchase_sessions = chunk.loc[valid_session & chunk["event_type"].eq("purchase")]
                    if not purchase_sessions.empty:
                        purchase_revenue_by_session = purchase_sessions.groupby("user_session")["price"].sum()
                        for session, revenue in purchase_revenue_by_session.items():
                            purchase_session_revenue[str(session)] += float(revenue)

                    daily_agg = add_frame(daily_agg, aggregate_by_key(chunk, "date"))
                    hourly_agg = add_frame(hourly_agg, aggregate_by_key(chunk, "hour"))
                    brand_agg = add_frame(brand_agg, aggregate_by_key(chunk, "brand_clean"))
                    category_agg = add_frame(category_agg, aggregate_by_key(chunk, "category_key"))
                    product_agg = add_frame(product_agg, aggregate_by_key(chunk, "product_id"))
                    price_bucket_agg = add_frame(price_bucket_agg, aggregate_by_key(chunk, "price_bucket"))

                    product_meta = chunk[["product_id", "brand_clean", "category_key"]].drop_duplicates("product_id")
                    for row in product_meta.itertuples(index=False):
                        product_id = str(row.product_id)
                        if product_id and product_id not in product_brand and row.brand_clean != "(missing)":
                            product_brand[product_id] = str(row.brand_clean)
                        if product_id and product_id not in product_category and row.category_key != "(missing)":
                            product_category[product_id] = str(row.category_key)

                    if chunk_number % 2 == 0:
                        print(f"[progress] {file_name}: {processed_in_file:,} rows", flush=True)

            sessions_all = session_sets["all"]
            sessions_view = session_sets["view"]
            sessions_cart = session_sets["cart"]
            sessions_purchase = session_sets["purchase"]

            monthly_stats[month]["sessions"] = len(sessions_all)
            monthly_stats[month]["sessions_with_view"] = len(sessions_view)
            monthly_stats[month]["sessions_with_cart"] = len(sessions_cart)
            monthly_stats[month]["sessions_with_purchase"] = len(sessions_purchase)
            monthly_stats[month]["sessions_view_and_cart"] = len(sessions_view & sessions_cart)
            monthly_stats[month]["sessions_cart_and_purchase"] = len(sessions_cart & sessions_purchase)
            monthly_stats[month]["sessions_view_and_purchase"] = len(sessions_view & sessions_purchase)
            monthly_stats[month]["sessions_full_funnel"] = len(sessions_view & sessions_cart & sessions_purchase)

            file_profile_rows.append(
                {
                    "file_name": file_name,
                    "month": month,
                    "rows": processed_in_file,
                    "min_event_time": file_min_time,
                    "max_event_time": file_max_time,
                    "unique_sessions": len(sessions_all),
                }
            )
            print(f"[done] {file_name}: {processed_in_file:,} rows, {len(sessions_all):,} sessions", flush=True)

    monthly_rows = []
    for month in months:
        stats = monthly_stats[month]
        active_users = len(active_users_by_month[month])
        view_users = len(view_users_by_month[month])
        cart_users = len(cart_users_by_month[month])
        buyers = len(buyers_by_month[month])
        revenue = float(stats["revenue"])
        purchase_events = int(stats["purchase_events"])
        sessions = int(stats["sessions"])
        sessions_with_view = int(stats["sessions_with_view"])
        sessions_with_cart = int(stats["sessions_with_cart"])
        sessions_with_purchase = int(stats["sessions_with_purchase"])

        monthly_rows.append(
            {
                "month": month,
                "total_events": int(stats["total_events"]),
                "view_events": int(stats["view_events"]),
                "cart_events": int(stats["cart_events"]),
                "remove_from_cart_events": int(stats["remove_from_cart_events"]),
                "purchase_events": purchase_events,
                "active_users": active_users,
                "view_users": view_users,
                "cart_users": cart_users,
                "buyers": buyers,
                "sessions": sessions,
                "sessions_with_view": sessions_with_view,
                "sessions_with_cart": sessions_with_cart,
                "sessions_with_purchase": sessions_with_purchase,
                "sessions_view_and_cart": int(stats["sessions_view_and_cart"]),
                "sessions_cart_and_purchase": int(stats["sessions_cart_and_purchase"]),
                "sessions_view_and_purchase": int(stats["sessions_view_and_purchase"]),
                "sessions_full_funnel": int(stats["sessions_full_funnel"]),
                "revenue": round(revenue, 2),
                "avg_item_price": safe_divide(revenue, purchase_events),
                "aov_purchase_session": safe_divide(revenue, sessions_with_purchase),
                "revenue_per_buyer": safe_divide(revenue, buyers),
                "user_view_to_cart_rate": safe_divide(cart_users, view_users),
                "user_cart_to_purchase_rate": safe_divide(buyers, cart_users),
                "user_view_to_purchase_rate": safe_divide(buyers, view_users),
                "active_user_purchase_rate": safe_divide(buyers, active_users),
                "session_view_to_cart_rate": safe_divide(int(stats["sessions_view_and_cart"]), sessions_with_view),
                "session_cart_to_purchase_rate": safe_divide(int(stats["sessions_cart_and_purchase"]), sessions_with_cart),
                "session_view_to_purchase_rate": safe_divide(int(stats["sessions_view_and_purchase"]), sessions_with_view),
                "session_purchase_rate": safe_divide(sessions_with_purchase, sessions),
                "cart_remove_event_ratio": safe_divide(int(stats["remove_from_cart_events"]), int(stats["cart_events"])),
            }
        )

    monthly_summary = pd.DataFrame(monthly_rows)

    retention_rows = []
    for current_month, next_month in zip(months[:-1], months[1:]):
        active_current = active_users_by_month[current_month]
        buyers_current = buyers_by_month[current_month]
        retained_active = len(active_current & active_users_by_month[next_month])
        repeat_buyers = len(buyers_current & buyers_by_month[next_month])
        retention_rows.append(
            {
                "month": current_month,
                "next_month": next_month,
                "active_users": len(active_current),
                "active_users_retained_next_month": retained_active,
                "active_next_month_retention_rate": safe_divide(retained_active, len(active_current)),
                "buyers": len(buyers_current),
                "buyers_repeat_purchase_next_month": repeat_buyers,
                "buyer_repeat_purchase_next_month_rate": safe_divide(repeat_buyers, len(buyers_current)),
            }
        )
    month_to_month_retention = pd.DataFrame(retention_rows)

    active_cohort_retention = build_cohort_retention(months, active_users_by_month)
    purchase_cohort_retention = build_cohort_retention(months, buyers_by_month)
    user_frequency = summarize_user_frequency(months, active_users_by_month, buyers_by_month)

    daily_trend = finalize_dimension_table(daily_agg, "date").sort_values("date").reset_index(drop=True)
    daily_trend.insert(1, "month", daily_trend["date"].str.slice(0, 7))
    hourly_pattern = finalize_dimension_table(hourly_agg, "hour").sort_values("hour").reset_index(drop=True)

    brand_summary = finalize_dimension_table(brand_agg, "brand", top_n=100)
    category_summary = finalize_dimension_table(category_agg, "category_key", top_n=100)
    product_summary = finalize_dimension_table(product_agg, "product_id", top_n=100)
    product_summary.insert(1, "brand", product_summary["product_id"].map(product_brand).fillna(""))
    product_summary.insert(2, "category_key", product_summary["product_id"].map(product_category).fillna(""))

    price_bucket_summary = finalize_dimension_table(price_bucket_agg, "price_bucket")
    price_order = ["non-positive", "$0-1", "$1-5", "$5-10", "$10-20", "$20-50", "$50-100", "$100+"]
    price_bucket_summary["price_bucket"] = pd.Categorical(price_bucket_summary["price_bucket"], categories=price_order, ordered=True)
    price_bucket_summary = price_bucket_summary.sort_values("price_bucket").reset_index(drop=True)
    price_bucket_summary["price_bucket"] = price_bucket_summary["price_bucket"].astype(str)

    data_quality = pd.DataFrame(
        [
            {
                "field": column,
                "missing_values": int(missing_counts[column]),
                "missing_rate": safe_divide(int(missing_counts[column]), total_rows),
            }
            for column in RAW_COLUMNS
        ]
    )
    file_profile = pd.DataFrame(file_profile_rows)

    summary = {
        "project": "E-commerce App User Conversion and Retention Analysis",
        "analysis_style": "Pandas / NumPy / Matplotlib data analyst workflow",
        "source_zip": str(zip_path),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "months": months,
        "row_count": int(total_rows),
        "min_event_time": str(min_event_time),
        "max_event_time": str(max_event_time),
        "event_types": {str(k): int(v) for k, v in event_type_counts.items()},
        "unique_active_users": int(len(set().union(*active_users_by_month.values()))),
        "unique_buyers": int(len(set().union(*buyers_by_month.values()))),
        "total_revenue": float(monthly_summary["revenue"].sum()),
        "total_purchase_events": int(monthly_summary["purchase_events"].sum()),
        "highest_revenue_month": str(monthly_summary.sort_values("revenue", ascending=False).iloc[0]["month"]),
        "latest_month": str(monthly_summary.iloc[-1]["month"]),
        "latest_active_user_purchase_rate": float(monthly_summary.iloc[-1]["active_user_purchase_rate"]),
        "avg_next_month_active_retention": float(month_to_month_retention["active_next_month_retention_rate"].mean()),
        "notes": [
            "Revenue is calculated as the sum of purchase event prices.",
            "Monthly conversion rates are based on unique users.",
            "Session conversion rates are based on unique sessions within each monthly CSV.",
            "Cohort retention is based on first observed active or purchase month.",
            "Non-positive price records are kept but separated for data quality review.",
        ],
    }

    tables = {
        "kpi_monthly_summary": monthly_summary,
        "retention_month_to_month": month_to_month_retention,
        "active_cohort_retention": active_cohort_retention,
        "purchase_cohort_retention": purchase_cohort_retention,
        "daily_trend": daily_trend,
        "hourly_pattern": hourly_pattern,
        "top_brands": brand_summary,
        "top_categories": category_summary,
        "top_products": product_summary,
        "price_bucket_analysis": price_bucket_summary,
        "data_quality_summary": data_quality,
        "file_profile": file_profile,
        "user_frequency_summary": user_frequency,
    }

    for file_stem, table in tables.items():
        table.to_csv(output_dir / f"{file_stem}.csv", index=False)

    save_excel_workbook(output_dir, tables)
    with (output_dir / "executive_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"[complete] Wrote pandas analysis outputs to {output_dir}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pandas-based e-commerce conversion and retention analysis.")
    parser.add_argument("--zip-path", required=True, type=Path, help="Path to source ZIP archive.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory for processed tables and workbook.")
    parser.add_argument("--chunksize", type=int, default=500_000, help="Rows per pandas chunk.")
    parser.add_argument("--max-rows-per-file", type=int, default=None, help="Optional row cap for fast testing.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    analyze(args.zip_path, args.output_dir, args.chunksize, args.max_rows_per_file)
