"""Research-style e-commerce app conversion and retention analysis.

This script is intentionally more detailed than a simple portfolio pipeline.
It is written like a reproducible research workflow:

1. Define business/research questions.
2. Audit raw data quality.
3. Clean and standardize event logs.
4. Engineer behavioral metrics.
5. Analyze conversion, retention, cohort behavior, RFM segments, products,
   brands, categories, price buckets, and timing patterns.
6. Generate publication-style tables and visualizations.

The raw files are large, so all raw CSVs are read directly from the ZIP archive
with pandas chunks.

Example:
    python scripts/research_style_ecommerce_analysis.py ^
        --zip-path "C:/path/to/archive.zip" ^
        --output-dir research_outputs
"""

from __future__ import annotations

import argparse
import json
import math
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter


# ---------------------------------------------------------------------------
# 1. Research configuration
# ---------------------------------------------------------------------------


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

PRICE_BUCKET_ORDER = [
    "non-positive",
    "$0-1",
    "$1-5",
    "$5-10",
    "$10-20",
    "$20-50",
    "$50-100",
    "$100+",
]


@dataclass
class AnalysisConfig:
    zip_path: Path
    output_dir: Path
    chunksize: int = 500_000
    max_rows_per_file: Optional[int] = None
    top_n: int = 30
    random_seed: int = 42

    @property
    def table_dir(self) -> Path:
        return self.output_dir / "tables"

    @property
    def figure_dir(self) -> Path:
        return self.output_dir / "figures"

    @property
    def report_dir(self) -> Path:
        return self.output_dir / "report"


# ---------------------------------------------------------------------------
# 2. Utility functions
# ---------------------------------------------------------------------------


def month_from_file_name(file_name: str) -> str:
    year, month_abbr = Path(file_name).stem.split("-")
    return f"{year}-{MONTH_ABBR[month_abbr]}"


def ensure_output_dirs(config: AnalysisConfig) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.table_dir.mkdir(parents=True, exist_ok=True)
    config.figure_dir.mkdir(parents=True, exist_ok=True)
    config.report_dir.mkdir(parents=True, exist_ok=True)


def list_monthly_csv_files(zip_path: Path) -> List[str]:
    with zipfile.ZipFile(zip_path) as archive:
        files = [name for name in archive.namelist() if name.lower().endswith(".csv")]
    return sorted(files, key=month_from_file_name)


def safe_divide(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def add_numeric_frame(base: Optional[pd.DataFrame], new: pd.DataFrame) -> pd.DataFrame:
    if base is None:
        return new.copy()
    return base.add(new, fill_value=0)


def money_formatter(value: float, _position: int) -> str:
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:.0f}"


def percent_formatter(value: float, _position: int) -> str:
    return f"{value * 100:.0f}%"


def integer_formatter(value: float, _position: int) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.0f}K"
    return f"{value:.0f}"


def write_table(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def prepare_table_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy that is safe for Excel export.

    Excel cannot store timezone-aware datetimes. Research tables may contain
    UTC timestamps for user first/last seen fields, so these are converted to
    readable timezone-free strings before writing the workbook.
    """
    out = df.copy()
    for column in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[column]):
            if getattr(out[column].dt, "tz", None) is not None:
                out[column] = out[column].dt.tz_convert(None)
        elif out[column].dtype == "object":
            out[column] = out[column].map(
                lambda value: value.isoformat() if isinstance(value, pd.Timestamp) else value
            )
    return out


def set_plot_style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 140,
            "savefig.dpi": 180,
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


# ---------------------------------------------------------------------------
# 3. Data cleaning and feature engineering
# ---------------------------------------------------------------------------


def clean_chunk(raw_chunk: pd.DataFrame) -> pd.DataFrame:
    """Clean one raw chunk and create reusable analytical columns."""
    chunk = raw_chunk.copy()

    text_columns = [
        "event_time",
        "event_type",
        "product_id",
        "category_id",
        "category_code",
        "brand",
        "user_id",
        "user_session",
    ]
    for column in text_columns:
        chunk[column] = chunk[column].astype("string").fillna("").str.strip()

    chunk["event_type"] = chunk["event_type"].str.lower()
    chunk["price"] = pd.to_numeric(chunk["price"], errors="coerce").fillna(0.0).astype("float64")

    # Parse timestamps once and reuse them for month/date/hour/week features.
    event_time_clean = chunk["event_time"].str.replace(" UTC", "", regex=False)
    chunk["event_time_dt"] = pd.to_datetime(event_time_clean, errors="coerce", utc=True)
    chunk["event_month"] = chunk["event_time_dt"].dt.strftime("%Y-%m").fillna("(missing)")
    chunk["event_date"] = chunk["event_time_dt"].dt.strftime("%Y-%m-%d").fillna("(missing)")
    chunk["event_week"] = chunk["event_time_dt"].dt.strftime("%Y-W%U").fillna("(missing)")
    chunk["event_hour"] = chunk["event_time_dt"].dt.hour.astype("Int64").astype("string").str.zfill(2).fillna("(missing)")

    chunk["brand_clean"] = chunk["brand"].str.lower()
    chunk["brand_clean"] = chunk["brand_clean"].mask(chunk["brand_clean"].eq(""), "(missing)")

    category_code = chunk["category_code"]
    category_id = chunk["category_id"]
    chunk["category_key"] = np.where(
        category_code.ne(""),
        category_code,
        np.where(category_id.ne(""), "category_id:" + category_id.astype(str), "(missing)"),
    )

    chunk["is_valid_event_type"] = chunk["event_type"].isin(EVENT_TYPES)
    chunk["is_view"] = chunk["event_type"].eq("view").astype(np.int8)
    chunk["is_cart"] = chunk["event_type"].eq("cart").astype(np.int8)
    chunk["is_remove_from_cart"] = chunk["event_type"].eq("remove_from_cart").astype(np.int8)
    chunk["is_purchase"] = chunk["event_type"].eq("purchase").astype(np.int8)
    chunk["purchase_revenue"] = np.where(chunk["is_purchase"].eq(1), chunk["price"], 0.0)

    price = chunk["price"]
    bucket_conditions = [
        price.le(0),
        price.gt(0) & price.lt(1),
        price.ge(1) & price.lt(5),
        price.ge(5) & price.lt(10),
        price.ge(10) & price.lt(20),
        price.ge(20) & price.lt(50),
        price.ge(50) & price.lt(100),
        price.ge(100),
    ]
    chunk["price_bucket"] = np.select(bucket_conditions, PRICE_BUCKET_ORDER, default="unknown")
    chunk["is_non_positive_price"] = chunk["price"].le(0).astype(np.int8)

    return chunk


def aggregate_events_by_key(chunk: pd.DataFrame, key: str) -> pd.DataFrame:
    return (
        chunk.groupby(key, dropna=False)
        .agg(
            events=("event_type", "size"),
            view_events=("is_view", "sum"),
            cart_events=("is_cart", "sum"),
            remove_from_cart_events=("is_remove_from_cart", "sum"),
            purchase_events=("is_purchase", "sum"),
            revenue=("purchase_revenue", "sum"),
            non_positive_price_events=("is_non_positive_price", "sum"),
        )
        .sort_index()
    )


def finalize_dimension_table(df: pd.DataFrame, key_name: str, top_n: Optional[int] = None) -> pd.DataFrame:
    out = df.reset_index().rename(columns={df.index.name or "index": key_name})
    count_columns = [
        "events",
        "view_events",
        "cart_events",
        "remove_from_cart_events",
        "purchase_events",
        "non_positive_price_events",
    ]
    for column in count_columns:
        out[column] = out[column].fillna(0).round().astype("int64")
    out["revenue"] = out["revenue"].fillna(0).astype(float).round(2)
    out["purchase_per_view_rate"] = np.where(out["view_events"].gt(0), out["purchase_events"] / out["view_events"], 0.0)
    out["cart_per_view_rate"] = np.where(out["view_events"].gt(0), out["cart_events"] / out["view_events"], 0.0)
    out["avg_purchase_price"] = np.where(out["purchase_events"].gt(0), out["revenue"] / out["purchase_events"], 0.0)
    out = out.sort_values(["revenue", "purchase_events"], ascending=False)
    return out.head(top_n).reset_index(drop=True) if top_n else out.reset_index(drop=True)


def wilson_confidence_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial conversion rate."""
    if total == 0:
        return 0.0, 0.0
    p = successes / total
    denominator = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) / total) + (z**2 / (4 * total**2))) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


# ---------------------------------------------------------------------------
# 4. Cohort, retention, and segmentation
# ---------------------------------------------------------------------------


def build_month_to_month_retention(months: List[str], active_sets: Dict[str, set], buyer_sets: Dict[str, set]) -> pd.DataFrame:
    rows = []
    for current_month, next_month in zip(months[:-1], months[1:]):
        active_users = active_sets[current_month]
        buyers = buyer_sets[current_month]
        retained_active = len(active_users & active_sets[next_month])
        repeat_buyers = len(buyers & buyer_sets[next_month])
        rows.append(
            {
                "month": current_month,
                "next_month": next_month,
                "active_users": len(active_users),
                "active_users_retained_next_month": retained_active,
                "active_next_month_retention_rate": safe_divide(retained_active, len(active_users)),
                "buyers": len(buyers),
                "buyers_repeat_purchase_next_month": repeat_buyers,
                "buyer_repeat_purchase_next_month_rate": safe_divide(repeat_buyers, len(buyers)),
            }
        )
    return pd.DataFrame(rows)


def build_cohort_matrix(months: List[str], monthly_sets: Dict[str, set]) -> pd.DataFrame:
    rows = []
    users_seen_before: set = set()

    for start_index, cohort_month in enumerate(months):
        cohort_users = monthly_sets[cohort_month] - users_seen_before
        users_seen_before |= monthly_sets[cohort_month]
        cohort_size = len(cohort_users)

        row = {"cohort_month": cohort_month, "cohort_size": cohort_size}
        for offset, month in enumerate(months[start_index:]):
            retained = len(cohort_users & monthly_sets[month]) if cohort_size else 0
            row[f"m{offset}_count"] = retained
            row[f"m{offset}_rate"] = safe_divide(retained, cohort_size)
        rows.append(row)

    return pd.DataFrame(rows)


def make_behavior_segments(user_summary: pd.DataFrame) -> pd.DataFrame:
    users = user_summary.copy()
    users["behavior_segment"] = "Other active users"
    users.loc[(users["view_events"] > 0) & (users["cart_events"] == 0) & (users["purchase_events"] == 0), "behavior_segment"] = "Browser only"
    users.loc[(users["cart_events"] > 0) & (users["purchase_events"] == 0), "behavior_segment"] = "Cart abandoner"
    users.loc[(users["purchase_events"] > 0) & (users["revenue"] <= users.loc[users["purchase_events"] > 0, "revenue"].quantile(0.90)), "behavior_segment"] = "Buyer"
    users.loc[(users["purchase_events"] > 0) & (users["revenue"] > users.loc[users["purchase_events"] > 0, "revenue"].quantile(0.90)), "behavior_segment"] = "High-value buyer"

    segment_summary = (
        users.groupby("behavior_segment")
        .agg(
            users=("events", "size"),
            events=("events", "sum"),
            view_events=("view_events", "sum"),
            cart_events=("cart_events", "sum"),
            purchase_events=("purchase_events", "sum"),
            revenue=("revenue", "sum"),
        )
        .reset_index()
    )
    segment_summary["revenue_per_user"] = np.where(segment_summary["users"] > 0, segment_summary["revenue"] / segment_summary["users"], 0.0)
    segment_summary["purchase_events_per_user"] = np.where(segment_summary["users"] > 0, segment_summary["purchase_events"] / segment_summary["users"], 0.0)
    return segment_summary.sort_values("revenue", ascending=False).reset_index(drop=True)


def quantile_score(series: pd.Series, labels: List[int]) -> pd.Series:
    """Assign stable quantile scores, including for very small samples."""
    if len(series) < len(labels):
        rank_pct = series.rank(method="first", pct=True)
        bins = np.linspace(0, 1, len(labels) + 1)
        score = pd.cut(rank_pct, bins=bins, labels=labels, include_lowest=True)
        return score.astype(int)
    return pd.qcut(series.rank(method="first"), len(labels), labels=labels).astype(int)


def make_rfm_segments(user_summary: pd.DataFrame, max_event_time: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    users = user_summary.copy()
    buyers = users.loc[users["purchase_events"] > 0].copy()
    if buyers.empty:
        return users, pd.DataFrame()

    buyers["recency_days"] = (max_event_time - buyers["last_event_time"]).dt.total_seconds() / 86_400
    buyers["frequency"] = buyers["purchase_events"]
    buyers["monetary"] = buyers["revenue"]

    buyers["r_score"] = quantile_score(-buyers["recency_days"], [1, 2, 3, 4, 5])
    buyers["f_score"] = quantile_score(buyers["frequency"], [1, 2, 3, 4, 5])
    buyers["m_score"] = quantile_score(buyers["monetary"], [1, 2, 3, 4, 5])
    buyers["rfm_score"] = buyers["r_score"] + buyers["f_score"] + buyers["m_score"]

    buyers["rfm_segment"] = "Regular buyers"
    buyers.loc[(buyers["r_score"] >= 4) & (buyers["f_score"] >= 4) & (buyers["m_score"] >= 4), "rfm_segment"] = "Champions"
    buyers.loc[(buyers["r_score"] >= 4) & (buyers["f_score"] <= 2), "rfm_segment"] = "New buyers"
    buyers.loc[(buyers["r_score"] <= 2) & (buyers["f_score"] >= 4), "rfm_segment"] = "At-risk loyal buyers"
    buyers.loc[(buyers["m_score"] >= 4) & (buyers["f_score"] <= 2), "rfm_segment"] = "High-value occasional buyers"
    buyers.loc[(buyers["r_score"] <= 2) & (buyers["f_score"] <= 2), "rfm_segment"] = "Inactive buyers"

    rfm_summary = (
        buyers.groupby("rfm_segment")
        .agg(
            users=("events", "size"),
            avg_recency_days=("recency_days", "mean"),
            avg_frequency=("frequency", "mean"),
            avg_monetary=("monetary", "mean"),
            total_revenue=("monetary", "sum"),
        )
        .reset_index()
        .sort_values("total_revenue", ascending=False)
    )
    return buyers.reset_index(), rfm_summary.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 5. Main chunked analysis
# ---------------------------------------------------------------------------


def run_research_analysis(config: AnalysisConfig) -> Dict[str, pd.DataFrame]:
    ensure_output_dirs(config)
    np.random.seed(config.random_seed)

    csv_files = list_monthly_csv_files(config.zip_path)
    months = [month_from_file_name(file_name) for file_name in csv_files]

    missing_counts = Counter()
    event_type_counts = Counter()
    duplicate_rows_within_chunk = 0
    invalid_event_type_rows = 0
    total_rows = 0
    min_event_time = None
    max_event_time = None

    monthly_agg = None
    daily_agg = None
    weekly_agg = None
    hourly_agg = None
    brand_agg = None
    category_agg = None
    product_agg = None
    price_bucket_agg = None

    user_numeric = None
    user_first_seen: Dict[str, pd.Timestamp] = {}
    user_last_seen: Dict[str, pd.Timestamp] = {}
    product_brand: Dict[str, str] = {}
    product_category: Dict[str, str] = {}

    active_users_by_month = {month: set() for month in months}
    view_users_by_month = {month: set() for month in months}
    cart_users_by_month = {month: set() for month in months}
    buyers_by_month = {month: set() for month in months}

    session_sets_by_month = {
        month: {
            "all": set(),
            "view": set(),
            "cart": set(),
            "purchase": set(),
        }
        for month in months
    }
    file_profile_rows = []

    with zipfile.ZipFile(config.zip_path) as archive:
        for file_name in csv_files:
            expected_month = month_from_file_name(file_name)
            rows_in_file = 0
            file_min_time = None
            file_max_time = None

            print(f"[start] {file_name}", flush=True)
            with archive.open(file_name) as raw_file:
                reader = pd.read_csv(
                    raw_file,
                    chunksize=config.chunksize,
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

                for chunk_id, raw_chunk in enumerate(reader, start=1):
                    if config.max_rows_per_file is not None:
                        remaining = config.max_rows_per_file - rows_in_file
                        if remaining <= 0:
                            break
                        raw_chunk = raw_chunk.head(remaining)

                    chunk = clean_chunk(raw_chunk)
                    row_count = len(chunk)
                    rows_in_file += row_count
                    total_rows += row_count

                    for column in RAW_COLUMNS:
                        if column == "price":
                            missing_counts[column] += int(pd.to_numeric(raw_chunk[column], errors="coerce").isna().sum())
                        else:
                            missing_counts[column] += int(raw_chunk[column].astype("string").fillna("").str.strip().eq("").sum())

                    duplicate_rows_within_chunk += int(raw_chunk.duplicated().sum())
                    invalid_event_type_rows += int((~chunk["is_valid_event_type"]).sum())
                    event_type_counts.update(chunk["event_type"].value_counts().to_dict())

                    chunk_min_time = chunk["event_time_dt"].min()
                    chunk_max_time = chunk["event_time_dt"].max()
                    if pd.notna(chunk_min_time):
                        min_event_time = chunk_min_time if min_event_time is None else min(min_event_time, chunk_min_time)
                        file_min_time = chunk_min_time if file_min_time is None else min(file_min_time, chunk_min_time)
                    if pd.notna(chunk_max_time):
                        max_event_time = chunk_max_time if max_event_time is None else max(max_event_time, chunk_max_time)
                        file_max_time = chunk_max_time if file_max_time is None else max(file_max_time, chunk_max_time)

                    monthly_agg = add_numeric_frame(monthly_agg, aggregate_events_by_key(chunk, "event_month"))
                    daily_agg = add_numeric_frame(daily_agg, aggregate_events_by_key(chunk, "event_date"))
                    weekly_agg = add_numeric_frame(weekly_agg, aggregate_events_by_key(chunk, "event_week"))
                    hourly_agg = add_numeric_frame(hourly_agg, aggregate_events_by_key(chunk, "event_hour"))
                    brand_agg = add_numeric_frame(brand_agg, aggregate_events_by_key(chunk, "brand_clean"))
                    category_agg = add_numeric_frame(category_agg, aggregate_events_by_key(chunk, "category_key"))
                    product_agg = add_numeric_frame(product_agg, aggregate_events_by_key(chunk, "product_id"))
                    price_bucket_agg = add_numeric_frame(price_bucket_agg, aggregate_events_by_key(chunk, "price_bucket"))

                    valid_user_chunk = chunk.loc[chunk["user_id"].ne("")]
                    if not valid_user_chunk.empty:
                        user_chunk_numeric = (
                            valid_user_chunk.groupby("user_id")
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
                        user_numeric = add_numeric_frame(user_numeric, user_chunk_numeric)

                        user_first = valid_user_chunk.groupby("user_id")["event_time_dt"].min()
                        user_last = valid_user_chunk.groupby("user_id")["event_time_dt"].max()
                        for user_id, first_seen in user_first.items():
                            if pd.notna(first_seen) and (user_id not in user_first_seen or first_seen < user_first_seen[user_id]):
                                user_first_seen[user_id] = first_seen
                        for user_id, last_seen in user_last.items():
                            if pd.notna(last_seen) and (user_id not in user_last_seen or last_seen > user_last_seen[user_id]):
                                user_last_seen[user_id] = last_seen

                    # Monthly unique-user sets for funnel and retention.
                    user_id = chunk["user_id"]
                    valid_user = user_id.ne("")
                    active_users_by_month[expected_month].update(user_id[valid_user].unique().tolist())
                    view_users_by_month[expected_month].update(chunk.loc[valid_user & chunk["event_type"].eq("view"), "user_id"].unique().tolist())
                    cart_users_by_month[expected_month].update(chunk.loc[valid_user & chunk["event_type"].eq("cart"), "user_id"].unique().tolist())
                    buyers_by_month[expected_month].update(chunk.loc[valid_user & chunk["event_type"].eq("purchase"), "user_id"].unique().tolist())

                    # Monthly unique-session sets for session-level funnel analysis.
                    session_id = chunk["user_session"]
                    valid_session = session_id.ne("")
                    session_sets_by_month[expected_month]["all"].update(session_id[valid_session].unique().tolist())
                    session_sets_by_month[expected_month]["view"].update(chunk.loc[valid_session & chunk["event_type"].eq("view"), "user_session"].unique().tolist())
                    session_sets_by_month[expected_month]["cart"].update(chunk.loc[valid_session & chunk["event_type"].eq("cart"), "user_session"].unique().tolist())
                    session_sets_by_month[expected_month]["purchase"].update(chunk.loc[valid_session & chunk["event_type"].eq("purchase"), "user_session"].unique().tolist())

                    # Product metadata fallback for readable product table.
                    product_meta = chunk[["product_id", "brand_clean", "category_key"]].drop_duplicates("product_id")
                    for row in product_meta.itertuples(index=False):
                        product_id = str(row.product_id)
                        if product_id and product_id not in product_brand and row.brand_clean != "(missing)":
                            product_brand[product_id] = str(row.brand_clean)
                        if product_id and product_id not in product_category and row.category_key != "(missing)":
                            product_category[product_id] = str(row.category_key)

                    if chunk_id % 2 == 0:
                        print(f"[progress] {file_name}: {rows_in_file:,} rows", flush=True)

            file_profile_rows.append(
                {
                    "file_name": file_name,
                    "month": expected_month,
                    "rows": rows_in_file,
                    "min_event_time": file_min_time,
                    "max_event_time": file_max_time,
                    "unique_sessions": len(session_sets_by_month[expected_month]["all"]),
                }
            )
            print(f"[done] {file_name}: {rows_in_file:,} rows", flush=True)

    if max_event_time is None:
        raise RuntimeError("No valid event_time values were found.")

    monthly_summary = finalize_monthly_summary(months, monthly_agg, active_users_by_month, view_users_by_month, cart_users_by_month, buyers_by_month, session_sets_by_month)
    conversion_ci = build_conversion_confidence_intervals(monthly_summary)
    data_quality = build_data_quality_table(missing_counts, total_rows, duplicate_rows_within_chunk, invalid_event_type_rows)
    file_profile = pd.DataFrame(file_profile_rows)
    month_to_month_retention = build_month_to_month_retention(months, active_users_by_month, buyers_by_month)
    active_cohort = build_cohort_matrix(months, active_users_by_month)
    purchase_cohort = build_cohort_matrix(months, buyers_by_month)

    daily_trend = finalize_dimension_table(daily_agg, "date").sort_values("date")
    weekly_trend = finalize_dimension_table(weekly_agg, "week").sort_values("week")
    hourly_pattern = finalize_dimension_table(hourly_agg, "hour").sort_values("hour")
    top_brands = finalize_dimension_table(brand_agg, "brand", top_n=config.top_n)
    top_categories = finalize_dimension_table(category_agg, "category_key", top_n=config.top_n)
    top_products = finalize_dimension_table(product_agg, "product_id", top_n=config.top_n)
    top_products.insert(1, "brand", top_products["product_id"].map(product_brand).fillna(""))
    top_products.insert(2, "category_key", top_products["product_id"].map(product_category).fillna(""))

    price_buckets = finalize_dimension_table(price_bucket_agg, "price_bucket")
    price_buckets["price_bucket"] = pd.Categorical(price_buckets["price_bucket"], categories=PRICE_BUCKET_ORDER, ordered=True)
    price_buckets = price_buckets.sort_values("price_bucket").reset_index(drop=True)
    price_buckets["price_bucket"] = price_buckets["price_bucket"].astype(str)

    user_summary = finalize_user_summary(user_numeric, user_first_seen, user_last_seen)
    behavior_segments = make_behavior_segments(user_summary)
    rfm_user_level, rfm_segments = make_rfm_segments(user_summary, max_event_time)

    summary_json = {
        "project": "E-commerce App User Conversion and Retention Analysis",
        "workflow": "research_style_analysis",
        "config": {key: str(value) for key, value in asdict(config).items()},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "months": months,
        "row_count": int(total_rows),
        "min_event_time": str(min_event_time),
        "max_event_time": str(max_event_time),
        "event_type_counts": {str(key): int(value) for key, value in event_type_counts.items()},
        "unique_active_users": int(len(set().union(*active_users_by_month.values()))),
        "unique_buyers": int(len(set().union(*buyers_by_month.values()))),
        "total_revenue": float(monthly_summary["revenue"].sum()),
        "total_purchase_events": int(monthly_summary["purchase_events"].sum()),
        "average_next_month_active_retention": float(month_to_month_retention["active_next_month_retention_rate"].mean()),
        "research_questions": [
            "How do users move from product views to carts and purchases?",
            "How stable is user retention across monthly cohorts?",
            "Which brands, categories, products, and price buckets drive revenue and conversion?",
            "Which user segments are most valuable or most likely to churn?",
            "What data quality risks should be considered before business decisions?",
        ],
    }

    tables = {
        "data_quality_audit": data_quality,
        "file_profile": file_profile,
        "monthly_kpi_summary": monthly_summary,
        "conversion_confidence_intervals": conversion_ci,
        "retention_month_to_month": month_to_month_retention,
        "active_user_cohort_retention": active_cohort,
        "purchase_cohort_retention": purchase_cohort,
        "daily_trend": daily_trend,
        "weekly_trend": weekly_trend,
        "hourly_pattern": hourly_pattern,
        "top_brands": top_brands,
        "top_categories": top_categories,
        "top_products": top_products,
        "price_bucket_analysis": price_buckets,
        "user_behavior_segments": behavior_segments,
        "rfm_segments": rfm_segments,
        "rfm_user_level_sample": rfm_user_level.head(10_000),
    }

    for table_name, table in tables.items():
        write_table(table, config.table_dir / f"{table_name}.csv")

    with (config.report_dir / "research_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary_json, f, indent=2)

    with pd.ExcelWriter(config.output_dir / "research_analysis_workbook.xlsx", engine="openpyxl") as writer:
        for table_name, table in tables.items():
            prepare_table_for_excel(table).to_excel(writer, sheet_name=table_name[:31], index=False)

    make_all_figures(config, tables)
    write_research_methodology_report(config, summary_json, tables)

    print(f"[complete] Research-style outputs written to {config.output_dir}", flush=True)
    return tables


def finalize_monthly_summary(
    months: List[str],
    monthly_agg: pd.DataFrame,
    active_users_by_month: Dict[str, set],
    view_users_by_month: Dict[str, set],
    cart_users_by_month: Dict[str, set],
    buyers_by_month: Dict[str, set],
    session_sets_by_month: Dict[str, Dict[str, set]],
) -> pd.DataFrame:
    monthly = finalize_dimension_table(monthly_agg, "month")
    monthly = monthly.set_index("month").reindex(months).fillna(0).reset_index()

    rows = []
    for row in monthly.to_dict("records"):
        month = row["month"]
        sessions = session_sets_by_month[month]
        active_users = len(active_users_by_month[month])
        view_users = len(view_users_by_month[month])
        cart_users = len(cart_users_by_month[month])
        buyers = len(buyers_by_month[month])

        session_all = sessions["all"]
        session_view = sessions["view"]
        session_cart = sessions["cart"]
        session_purchase = sessions["purchase"]

        row.update(
            {
                "active_users": active_users,
                "view_users": view_users,
                "cart_users": cart_users,
                "buyers": buyers,
                "sessions": len(session_all),
                "sessions_with_view": len(session_view),
                "sessions_with_cart": len(session_cart),
                "sessions_with_purchase": len(session_purchase),
                "sessions_view_and_cart": len(session_view & session_cart),
                "sessions_cart_and_purchase": len(session_cart & session_purchase),
                "sessions_view_and_purchase": len(session_view & session_purchase),
                "sessions_full_funnel": len(session_view & session_cart & session_purchase),
                "avg_item_price": safe_divide(row["revenue"], row["purchase_events"]),
                "aov_purchase_session": safe_divide(row["revenue"], len(session_purchase)),
                "revenue_per_buyer": safe_divide(row["revenue"], buyers),
                "user_view_to_cart_rate": safe_divide(cart_users, view_users),
                "user_cart_to_purchase_rate": safe_divide(buyers, cart_users),
                "user_view_to_purchase_rate": safe_divide(buyers, view_users),
                "active_user_purchase_rate": safe_divide(buyers, active_users),
                "session_view_to_cart_rate": safe_divide(len(session_view & session_cart), len(session_view)),
                "session_cart_to_purchase_rate": safe_divide(len(session_cart & session_purchase), len(session_cart)),
                "session_view_to_purchase_rate": safe_divide(len(session_view & session_purchase), len(session_view)),
                "session_purchase_rate": safe_divide(len(session_purchase), len(session_all)),
                "cart_remove_event_ratio": safe_divide(row["remove_from_cart_events"], row["cart_events"]),
            }
        )
        rows.append(row)

    return pd.DataFrame(rows)


def build_conversion_confidence_intervals(monthly_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in monthly_summary.to_dict("records"):
        purchase_low, purchase_high = wilson_confidence_interval(int(row["buyers"]), int(row["active_users"]))
        cart_low, cart_high = wilson_confidence_interval(int(row["buyers"]), int(row["cart_users"]))
        rows.append(
            {
                "month": row["month"],
                "active_users": int(row["active_users"]),
                "buyers": int(row["buyers"]),
                "active_user_purchase_rate": row["active_user_purchase_rate"],
                "active_user_purchase_rate_ci_low": purchase_low,
                "active_user_purchase_rate_ci_high": purchase_high,
                "cart_users": int(row["cart_users"]),
                "user_cart_to_purchase_rate": row["user_cart_to_purchase_rate"],
                "user_cart_to_purchase_rate_ci_low": cart_low,
                "user_cart_to_purchase_rate_ci_high": cart_high,
            }
        )
    return pd.DataFrame(rows)


def build_data_quality_table(missing_counts: Counter, total_rows: int, duplicate_rows_within_chunk: int, invalid_event_type_rows: int) -> pd.DataFrame:
    rows = []
    for column in RAW_COLUMNS:
        missing = int(missing_counts[column])
        rows.append(
            {
                "quality_check": f"missing_{column}",
                "affected_rows": missing,
                "affected_rate": safe_divide(missing, total_rows),
                "interpretation": "Missing values in raw column",
            }
        )

    rows.extend(
        [
            {
                "quality_check": "duplicate_rows_within_chunk",
                "affected_rows": int(duplicate_rows_within_chunk),
                "affected_rate": safe_divide(duplicate_rows_within_chunk, total_rows),
                "interpretation": "Exact duplicated raw records detected within each processing chunk",
            },
            {
                "quality_check": "invalid_event_type",
                "affected_rows": int(invalid_event_type_rows),
                "affected_rate": safe_divide(invalid_event_type_rows, total_rows),
                "interpretation": "Events outside expected view/cart/remove_from_cart/purchase taxonomy",
            },
        ]
    )
    return pd.DataFrame(rows)


def finalize_user_summary(user_numeric: pd.DataFrame, user_first_seen: Dict[str, pd.Timestamp], user_last_seen: Dict[str, pd.Timestamp]) -> pd.DataFrame:
    users = user_numeric.reset_index().rename(columns={"index": "user_id"})
    users["user_id"] = users["user_id"].astype(str)
    for column in ["events", "view_events", "cart_events", "remove_from_cart_events", "purchase_events"]:
        users[column] = users[column].fillna(0).round().astype("int64")
    users["revenue"] = users["revenue"].fillna(0.0).astype(float)
    users["first_event_time"] = users["user_id"].map(user_first_seen)
    users["last_event_time"] = users["user_id"].map(user_last_seen)
    users["cart_to_purchase_flag"] = ((users["cart_events"] > 0) & (users["purchase_events"] > 0)).astype(int)
    users["cart_abandonment_flag"] = ((users["cart_events"] > 0) & (users["purchase_events"] == 0)).astype(int)
    users["purchase_rate_per_event"] = np.where(users["events"] > 0, users["purchase_events"] / users["events"], 0.0)
    return users


# ---------------------------------------------------------------------------
# 6. Visualization functions
# ---------------------------------------------------------------------------


def make_all_figures(config: AnalysisConfig, tables: Dict[str, pd.DataFrame]) -> None:
    set_plot_style()
    plot_data_quality(tables["data_quality_audit"], config.figure_dir / "01_data_quality_audit.png")
    plot_monthly_revenue_and_conversion(tables["monthly_kpi_summary"], config.figure_dir / "02_monthly_revenue_conversion.png")
    plot_event_mix(tables["monthly_kpi_summary"], config.figure_dir / "03_event_mix_by_month.png")
    plot_user_funnel(tables["monthly_kpi_summary"], config.figure_dir / "04_user_funnel_by_month.png")
    plot_cohort_heatmap(tables["active_user_cohort_retention"], config.figure_dir / "05_active_user_cohort_heatmap.png", "Active User Cohort Retention")
    plot_cohort_heatmap(tables["purchase_cohort_retention"], config.figure_dir / "06_purchase_cohort_heatmap.png", "Purchase Cohort Retention")
    plot_top_brands(tables["top_brands"], config.figure_dir / "07_top_brands_revenue.png")
    plot_price_bucket_conversion(tables["price_bucket_analysis"], config.figure_dir / "08_price_bucket_conversion.png")
    plot_daily_revenue(tables["daily_trend"], config.figure_dir / "09_daily_revenue_trend.png")
    plot_hourly_pattern(tables["hourly_pattern"], config.figure_dir / "10_hourly_purchase_pattern.png")
    plot_behavior_segments(tables["user_behavior_segments"], config.figure_dir / "11_user_behavior_segments.png")
    plot_rfm_segments(tables["rfm_segments"], config.figure_dir / "12_rfm_segments.png")


def plot_data_quality(data_quality: pd.DataFrame, path: Path) -> None:
    subset = data_quality.loc[data_quality["quality_check"].str.startswith("missing_")].copy()
    subset["field"] = subset["quality_check"].str.replace("missing_", "", regex=False)
    subset = subset.sort_values("affected_rate", ascending=True)

    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.barh(subset["field"], subset["affected_rate"], color="#B45309", alpha=0.88)
    ax.xaxis.set_major_formatter(FuncFormatter(percent_formatter))
    ax.set_title("Missing Value Rate by Field")
    ax.set_xlabel("Missing rate")
    ax.grid(axis="x")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_monthly_revenue_and_conversion(monthly: pd.DataFrame, path: Path) -> None:
    fig, ax1 = plt.subplots(figsize=(9, 4.8))
    ax1.bar(monthly["month"], monthly["revenue"], color="#2563EB", alpha=0.84, label="Revenue")
    ax1.set_ylabel("Revenue")
    ax1.yaxis.set_major_formatter(FuncFormatter(money_formatter))
    ax1.grid(axis="y")

    ax2 = ax1.twinx()
    ax2.plot(monthly["month"], monthly["active_user_purchase_rate"], color="#0F766E", marker="o", linewidth=2.5, label="Active user purchase rate")
    ax2.set_ylabel("Active user purchase rate")
    ax2.yaxis.set_major_formatter(FuncFormatter(percent_formatter))
    ax1.set_title("Monthly Revenue and Active User Purchase Rate")

    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    fig.legend(handles1 + handles2, labels1 + labels2, loc="upper center", bbox_to_anchor=(0.5, 0.02), ncol=2, frameon=False)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_event_mix(monthly: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.8))
    bottoms = np.zeros(len(monthly))
    columns = ["view_events", "cart_events", "remove_from_cart_events", "purchase_events"]
    colors = ["#2563EB", "#0F766E", "#B45309", "#9333EA"]
    for column, color in zip(columns, colors):
        ax.bar(monthly["month"], monthly[column], bottom=bottoms, label=column.replace("_", " ").title(), color=color, alpha=0.88)
        bottoms += monthly[column].to_numpy()
    ax.set_ylabel("Events")
    ax.yaxis.set_major_formatter(FuncFormatter(integer_formatter))
    ax.set_title("Event Composition by Month")
    ax.legend(frameon=False, ncol=2)
    ax.grid(axis="y")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_user_funnel(monthly: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.8))
    x = np.arange(len(monthly))
    width = 0.24
    funnel_cols = ["view_users", "cart_users", "buyers"]
    labels = ["View users", "Cart users", "Buyers"]
    colors = ["#2563EB", "#B45309", "#0F766E"]
    for idx, (column, label, color) in enumerate(zip(funnel_cols, labels, colors)):
        ax.bar(x + (idx - 1) * width, monthly[column], width=width, label=label, color=color)
    ax.set_xticks(x)
    ax.set_xticklabels(monthly["month"])
    ax.yaxis.set_major_formatter(FuncFormatter(integer_formatter))
    ax.set_ylabel("Unique users")
    ax.set_title("Monthly Unique-User Funnel")
    ax.legend(frameon=False)
    ax.grid(axis="y")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_cohort_heatmap(cohort: pd.DataFrame, path: Path, title: str) -> None:
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
            color = "white" if float(value) > 0.50 else "#172033"
            ax.text(col_idx, row_idx, f"{float(value) * 100:.1f}%", ha="center", va="center", fontsize=8, color=color)

    colorbar = fig.colorbar(image, ax=ax, fraction=0.035, pad=0.04)
    colorbar.ax.yaxis.set_major_formatter(FuncFormatter(percent_formatter))
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_top_brands(brands: pd.DataFrame, path: Path) -> None:
    subset = brands.loc[brands["brand"].ne("(missing)")].head(12).sort_values("revenue")
    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    ax.barh(subset["brand"], subset["revenue"], color="#2563EB")
    ax.xaxis.set_major_formatter(FuncFormatter(money_formatter))
    ax.set_xlabel("Revenue")
    ax.set_title("Top Named Brands by Revenue")
    ax.grid(axis="x")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_price_bucket_conversion(price_buckets: pd.DataFrame, path: Path) -> None:
    subset = price_buckets.loc[price_buckets["price_bucket"].ne("non-positive")]
    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    ax.bar(subset["price_bucket"], subset["purchase_per_view_rate"], color="#0F766E", alpha=0.9)
    ax.yaxis.set_major_formatter(FuncFormatter(percent_formatter))
    ax.set_xlabel("Price bucket")
    ax.set_ylabel("Purchase / view rate")
    ax.set_title("Conversion Rate by Price Bucket")
    ax.grid(axis="y")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_daily_revenue(daily: pd.DataFrame, path: Path) -> None:
    subset = daily.copy()
    subset["date"] = pd.to_datetime(subset["date"], errors="coerce")
    subset = subset.dropna(subset=["date"]).sort_values("date")
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.plot(subset["date"], subset["revenue"], color="#2563EB", linewidth=1.8)
    ax.yaxis.set_major_formatter(FuncFormatter(money_formatter))
    ax.set_ylabel("Revenue")
    ax.set_title("Daily Revenue Trend")
    ax.grid(axis="y")
    fig.autofmt_xdate(rotation=30)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_hourly_pattern(hourly: pd.DataFrame, path: Path) -> None:
    subset = hourly.loc[hourly["hour"].ne("(missing)")].copy()
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.bar(subset["hour"].astype(str), subset["purchase_events"], color="#B45309", alpha=0.9)
    ax.yaxis.set_major_formatter(FuncFormatter(integer_formatter))
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Purchase events")
    ax.set_title("Purchase Events by Hour")
    ax.grid(axis="y")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_behavior_segments(segments: pd.DataFrame, path: Path) -> None:
    subset = segments.sort_values("users", ascending=True)
    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    ax.barh(subset["behavior_segment"], subset["users"], color="#2563EB")
    ax.xaxis.set_major_formatter(FuncFormatter(integer_formatter))
    ax.set_xlabel("Users")
    ax.set_title("User Behavior Segment Size")
    ax.grid(axis="x")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_rfm_segments(rfm_segments: pd.DataFrame, path: Path) -> None:
    if rfm_segments.empty:
        return
    subset = rfm_segments.sort_values("total_revenue", ascending=True)
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.barh(subset["rfm_segment"], subset["total_revenue"], color="#0F766E")
    ax.xaxis.set_major_formatter(FuncFormatter(money_formatter))
    ax.set_xlabel("Total revenue")
    ax.set_title("RFM Segments by Revenue")
    ax.grid(axis="x")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 7. Research methodology report
# ---------------------------------------------------------------------------


def write_research_methodology_report(config: AnalysisConfig, summary: dict, tables: Dict[str, pd.DataFrame]) -> None:
    monthly = tables["monthly_kpi_summary"]
    retention = tables["retention_month_to_month"]
    data_quality = tables["data_quality_audit"]
    top_brands = tables["top_brands"]
    top_price = tables["price_bucket_analysis"].loc[tables["price_bucket_analysis"]["price_bucket"].ne("non-positive")]

    best_month = monthly.sort_values("revenue", ascending=False).iloc[0]
    best_brand = top_brands.loc[top_brands["brand"].ne("(missing)")].iloc[0]
    best_price_bucket = top_price.sort_values("purchase_per_view_rate", ascending=False).iloc[0]

    report = f"""# Research-Style E-commerce App Analysis

## Research Questions

{chr(10).join(f"- {question}" for question in summary["research_questions"])}

## Data Scope

- Rows processed: {summary["row_count"]:,}
- Months analyzed: {", ".join(summary["months"])}
- Date range: {summary["min_event_time"]} to {summary["max_event_time"]}
- Purchase events: {summary["total_purchase_events"]:,}
- Purchase revenue: ${summary["total_revenue"]:,.2f}

## Methodology

1. Read monthly CSV files directly from the source ZIP archive using pandas chunks.
2. Standardized event types, timestamp fields, brand/category keys, user/session identifiers, and price buckets.
3. Separated non-positive price records from normal pricing analysis for auditability.
4. Calculated monthly user funnel metrics, session funnel metrics, retention rates, and Wilson confidence intervals.
5. Built active-user and buyer cohort retention matrices.
6. Generated behavior segments and RFM buyer segments.
7. Produced visual outputs for data quality, revenue trend, funnel, cohort retention, brand revenue, price conversion, time patterns, and user segments.

## Key Findings

- Highest revenue month: {best_month["month"]} (${best_month["revenue"]:,.2f})
- Average next-month active retention: {retention["active_next_month_retention_rate"].mean() * 100:.2f}%
- Top named brand by revenue: {best_brand["brand"]} (${best_brand["revenue"]:,.2f})
- Best normal price bucket by purchase/view rate: {best_price_bucket["price_bucket"]} ({best_price_bucket["purchase_per_view_rate"] * 100:.2f}%)

## Data Quality Notes

```text
{data_quality.to_string(index=False)}
```

## Output Files

- Tables: `{config.table_dir}`
- Figures: `{config.figure_dir}`
- Workbook: `{config.output_dir / "research_analysis_workbook.xlsx"}`
"""
    (config.report_dir / "research_methodology_report.md").write_text(report, encoding="utf-8")


# ---------------------------------------------------------------------------
# 8. CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a research-style e-commerce app conversion and retention analysis.")
    parser.add_argument("--zip-path", required=True, type=Path, help="Path to raw ZIP archive.")
    parser.add_argument("--output-dir", default=Path("research_outputs"), type=Path, help="Directory for research outputs.")
    parser.add_argument("--chunksize", default=500_000, type=int, help="Rows per pandas chunk.")
    parser.add_argument("--max-rows-per-file", default=None, type=int, help="Optional row cap for fast testing.")
    parser.add_argument("--top-n", default=30, type=int, help="Top N rows for brand/product/category tables.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    config = AnalysisConfig(
        zip_path=args.zip_path,
        output_dir=args.output_dir,
        chunksize=args.chunksize,
        max_rows_per_file=args.max_rows_per_file,
        top_n=args.top_n,
    )
    run_research_analysis(config)
