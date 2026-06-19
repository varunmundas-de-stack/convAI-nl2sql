"""
CPG Sales ETL Pipeline — CSV → Postgres
========================================
Ingests flat CSV files into the star schema:
  - public.dim_product
  - public.dim_geography
  - public.dim_period
  - public.dim_salesorg
  - public.dim_distributor
  - client_<tenant>.fact_secondary_sales
  - client_<tenant>.fact_primary_sales

Usage:
  python cpg_etl.py --tenant nestle --secondary secondary_sales.csv
  python cpg_etl.py --tenant nestle --primary primary_sales.csv
  python cpg_etl.py --tenant nestle --secondary sec.csv --primary pri.csv
  python cpg_etl.py --tenant nestle --watch /data/drop_zone   # watch folder mode
"""

import argparse
import csv
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("cpg_etl")

# ── DB Connection ─────────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "sales_analytics"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASS", "postgres"),
    )


# ── Dimension upsert helpers ──────────────────────────────────────────────────

def upsert_dim_product(cur, rows: list[dict]) -> int:
    """Upsert dim_product from flat sales rows. Returns count upserted."""
    seen = {}
    for r in rows:
        key = r.get("sku_code", "").strip()
        if key and key not in seen:
            seen[key] = {
                "sku_code":    key,
                "sku_name":    r.get("product_desc", "").strip(),
                "brand":       r.get("brand", "").strip(),
                "category":    r.get("category", "").strip(),
                "sub_category":r.get("sub_category", "").strip(),
                "pack_size":   r.get("pack_size", "").strip(),
            }
    if not seen:
        return 0
    psycopg2.extras.execute_batch(cur, """
        INSERT INTO public.dim_product (sku_code, sku_name, brand, category, sub_category, pack_size)
        VALUES (%(sku_code)s, %(sku_name)s, %(brand)s, %(category)s, %(sub_category)s, %(pack_size)s)
        ON CONFLICT (sku_code) DO UPDATE SET
            sku_name    = EXCLUDED.sku_name,
            brand       = EXCLUDED.brand,
            category    = EXCLUDED.category,
            sub_category= EXCLUDED.sub_category,
            pack_size   = EXCLUDED.pack_size
    """, list(seen.values()), page_size=500)
    return len(seen)


def upsert_dim_geography(cur, rows: list[dict]) -> int:
    seen = {}
    for r in rows:
        key = (r.get("city","").strip(), r.get("state","").strip(), r.get("zone","").strip())
        if all(key) and key not in seen:
            seen[key] = {
                "zone":      key[2],
                "state":     key[1],
                "city":      key[0],
                "territory": r.get("territory", None),
                "geo_level": "city",
            }
    if not seen:
        return 0
    psycopg2.extras.execute_batch(cur, """
        INSERT INTO public.dim_geography (zone, state, city, territory, geo_level)
        VALUES (%(zone)s, %(state)s, %(city)s, %(territory)s, %(geo_level)s)
        ON CONFLICT (zone, state, city) DO UPDATE SET
            territory = EXCLUDED.territory,
            geo_level = EXCLUDED.geo_level
    """, list(seen.values()), page_size=500)
    return len(seen)


def upsert_dim_period(cur, rows: list[dict]) -> int:
    seen = set()
    records = []
    for r in rows:
        raw = r.get("invoice_date", "").strip()
        if not raw or raw in seen:
            continue
        try:
            d = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            continue
        seen.add(raw)
        # Simple fiscal calendar: fiscal year starts April 1
        fiscal_year  = d.year if d.month >= 4 else d.year - 1
        fiscal_month = ((d.month - 4) % 12) + 1
        fiscal_qtr   = (fiscal_month - 1) // 3 + 1
        iso_week     = d.isocalendar()[1]
        records.append({
            "date":           d,
            "fiscal_week":    iso_week,
            "fiscal_month":   fiscal_month,
            "fiscal_quarter": fiscal_qtr,
            "fiscal_year":    fiscal_year,
            "is_ytd":         d <= date.today(),
        })
    if not records:
        return 0
    psycopg2.extras.execute_batch(cur, """
        INSERT INTO public.dim_period (date, fiscal_week, fiscal_month, fiscal_quarter, fiscal_year, is_ytd)
        VALUES (%(date)s, %(fiscal_week)s, %(fiscal_month)s, %(fiscal_quarter)s, %(fiscal_year)s, %(is_ytd)s)
        ON CONFLICT (date) DO UPDATE SET
            fiscal_week    = EXCLUDED.fiscal_week,
            fiscal_month   = EXCLUDED.fiscal_month,
            fiscal_quarter = EXCLUDED.fiscal_quarter,
            fiscal_year    = EXCLUDED.fiscal_year,
            is_ytd         = EXCLUDED.is_ytd
    """, records, page_size=500)
    return len(records)


def upsert_dim_salesorg(cur, rows: list[dict]) -> int:
    seen = {}
    for r in rows:
        key = r.get("so_name", "").strip()
        if not key:
            continue
        zone = r.get("zone", "").strip()
        k = (key, zone)
        if k not in seen:
            seen[k] = {
                "so_code":  key,
                "asm_name": r.get("asm_name", "").strip() or None,
                "zsm_name": r.get("zsm_name", "").strip() or None,
                "zone":     zone or None,
            }
    if not seen:
        return 0
    psycopg2.extras.execute_batch(cur, """
        INSERT INTO public.dim_salesorg (so_code, asm_name, zsm_name, zone)
        VALUES (%(so_code)s, %(asm_name)s, %(zsm_name)s, %(zone)s)
        ON CONFLICT (so_code) DO UPDATE SET
            asm_name = EXCLUDED.asm_name,
            zsm_name = EXCLUDED.zsm_name,
            zone     = EXCLUDED.zone
    """, list(seen.values()), page_size=500)
    return len(seen)


def upsert_dim_distributor(cur, rows: list[dict]) -> int:
    seen = {}
    for r in rows:
        key = r.get("distributor_code", "").strip()
        if not key or key in seen:
            continue
        seen[key] = {
            "distributor_code": key,
            "distributor_name": r.get("distributor_name", "").strip() or None,
            "channel_type":     None,
            "beat_plan":        None,
            "geo_id":           None,
        }
    if not seen:
        return 0
    psycopg2.extras.execute_batch(cur, """
        INSERT INTO public.dim_distributor (distributor_code, distributor_name, channel_type, beat_plan, geo_id)
        VALUES (%(distributor_code)s, %(distributor_name)s, %(channel_type)s, %(beat_plan)s, %(geo_id)s)
        ON CONFLICT (distributor_code) DO UPDATE SET
            distributor_name = EXCLUDED.distributor_name
    """, list(seen.values()), page_size=500)
    return len(seen)


# ── Fact loaders ──────────────────────────────────────────────────────────────

def _safe_int(val) -> Optional[int]:
    try:
        return int(val) if val not in (None, "", "NULL", "null") else None
    except (ValueError, TypeError):
        return None


def _safe_float(val) -> Optional[float]:
    try:
        return float(val) if val not in (None, "", "NULL", "null") else None
    except (ValueError, TypeError):
        return None


def load_secondary_sales(cur, schema: str, rows: list[dict]) -> int:
    records = []
    for r in rows:
        invoice_date = r.get("invoice_date", "").strip()
        sku_code     = r.get("sku_code", "").strip()
        invoice_id   = r.get("invoice_id", "").strip()
        if not invoice_date or not sku_code or not invoice_id:
            continue
        records.append({
            "distributor_code": r.get("distributor_code", "").strip() or None,
            "distributor_name": r.get("distributor_name", "").strip() or None,
            "retailer_code":    r.get("retailer_code", "").strip() or None,
            "retailer_name":    r.get("retailer_name", "").strip() or None,
            "retailer_type":    r.get("retailer_type", "").strip() or None,
            "route_code":       r.get("route_code", "").strip() or None,
            "route_name":       r.get("route_name", "").strip() or None,
            "salesrep_code":    r.get("salesrep_code", "").strip() or None,
            "salesrep_name":    r.get("salesrep_name", "").strip() or None,
            "so_name":          r.get("so_name", "").strip() or None,
            "asm_name":         r.get("asm_name", "").strip() or None,
            "zsm_name":         r.get("zsm_name", "").strip() or None,
            "city":             r.get("city", "").strip() or None,
            "state":            r.get("state", "").strip() or None,
            "zone":             r.get("zone", "").strip() or None,
            "invoice_id":       invoice_id,
            "invoice_line_id":  r.get("invoice_line_id", "").strip() or None,
            "invoice_date":     invoice_date,
            "sku_code":         sku_code,
            "product_desc":     r.get("product_desc", "").strip() or None,
            "brand":            r.get("brand", "").strip() or None,
            "category":         r.get("category", "").strip() or None,
            "sub_category":     r.get("sub_category", "").strip() or None,
            "pack_size":        r.get("pack_size", "").strip() or None,
            "uom":              r.get("uom", "").strip() or None,
            "billed_qty":       _safe_int(r.get("billed_qty")),
            "billed_volume":    _safe_int(r.get("billed_volume")),
            "billed_weight":    _safe_int(r.get("billed_weight")),
            "currency":         r.get("currency", "INR").strip(),
            "gross_value":      _safe_int(r.get("gross_value")),
            "net_value":        _safe_int(r.get("net_value")),
            "tax_value":        _safe_int(r.get("tax_value")),
            "tax_rate":         _safe_int(r.get("tax_rate")),
        })
    if not records:
        return 0
    psycopg2.extras.execute_batch(cur, f"""
        INSERT INTO {schema}.fact_secondary_sales (
            distributor_code, distributor_name, retailer_code, retailer_name, retailer_type,
            route_code, route_name, salesrep_code, salesrep_name, so_name, asm_name, zsm_name,
            city, state, zone, invoice_id, invoice_line_id, invoice_date,
            sku_code, product_desc, brand, category, sub_category, pack_size, uom,
            billed_qty, billed_volume, billed_weight, currency,
            gross_value, net_value, tax_value, tax_rate
        ) VALUES (
            %(distributor_code)s, %(distributor_name)s, %(retailer_code)s, %(retailer_name)s, %(retailer_type)s,
            %(route_code)s, %(route_name)s, %(salesrep_code)s, %(salesrep_name)s, %(so_name)s, %(asm_name)s, %(zsm_name)s,
            %(city)s, %(state)s, %(zone)s, %(invoice_id)s, %(invoice_line_id)s, %(invoice_date)s,
            %(sku_code)s, %(product_desc)s, %(brand)s, %(category)s, %(sub_category)s, %(pack_size)s, %(uom)s,
            %(billed_qty)s, %(billed_volume)s, %(billed_weight)s, %(currency)s,
            %(gross_value)s, %(net_value)s, %(tax_value)s, %(tax_rate)s
        )
        ON CONFLICT (invoice_id, invoice_line_id, sku_code) DO UPDATE SET
            net_value    = EXCLUDED.net_value,
            gross_value  = EXCLUDED.gross_value,
            tax_value    = EXCLUDED.tax_value,
            billed_qty   = EXCLUDED.billed_qty
    """, records, page_size=1000)
    return len(records)


def load_primary_sales(cur, schema: str, rows: list[dict]) -> int:
    records = []
    for r in rows:
        invoice_date = r.get("invoice_date", "").strip()
        sku_code     = r.get("sku_code", "").strip()
        invoice_id   = r.get("invoice_id", "").strip()
        if not invoice_date or not sku_code or not invoice_id:
            continue
        records.append({
            "companywh_code":   r.get("companywh_code", "").strip() or None,
            "companywh_name":   r.get("companywh_name", "").strip() or None,
            "distributor_code": r.get("distributor_code", "").strip() or None,
            "distributor_name": r.get("distributor_name", "").strip() or None,
            "city":             r.get("city", "").strip() or None,
            "state":            r.get("state", "").strip() or None,
            "zone":             r.get("zone", "").strip() or None,
            "so_name":          r.get("so_name", "").strip() or None,
            "asm_name":         r.get("asm_name", "").strip() or None,
            "zsm_name":         r.get("zsm_name", "").strip() or None,
            "invoice_id":       invoice_id,
            "invoice_line_id":  r.get("invoice_line_id", "").strip() or None,
            "invoice_date":     invoice_date,
            "sku_code":         sku_code,
            "product_desc":     r.get("product_desc", "").strip() or None,
            "brand":            r.get("brand", "").strip() or None,
            "category":         r.get("category", "").strip() or None,
            "sub_category":     r.get("sub_category", "").strip() or None,
            "pack_size":        r.get("pack_size", "").strip() or None,
            "uom":              r.get("uom", "").strip() or None,
            "billed_qty":       _safe_int(r.get("billed_qty")),
            "billed_volume":    _safe_int(r.get("billed_volume")),
            "billed_weight":    _safe_int(r.get("billed_weight")),
            "currency":         r.get("currency", "INR").strip(),
            "gross_value":      _safe_int(r.get("gross_value")),
            "net_value":        _safe_int(r.get("net_value")),
            "tax_value":        _safe_int(r.get("tax_value")),
            "tax_rate":         _safe_int(r.get("tax_rate")),
        })
    if not records:
        return 0
    psycopg2.extras.execute_batch(cur, f"""
        INSERT INTO {schema}.fact_primary_sales (
            companywh_code, companywh_name, distributor_code, distributor_name,
            city, state, zone, so_name, asm_name, zsm_name,
            invoice_id, invoice_line_id, invoice_date,
            sku_code, product_desc, brand, category, sub_category, pack_size, uom,
            billed_qty, billed_volume, billed_weight, currency,
            gross_value, net_value, tax_value, tax_rate
        ) VALUES (
            %(companywh_code)s, %(companywh_name)s, %(distributor_code)s, %(distributor_name)s,
            %(city)s, %(state)s, %(zone)s, %(so_name)s, %(asm_name)s, %(zsm_name)s,
            %(invoice_id)s, %(invoice_line_id)s, %(invoice_date)s,
            %(sku_code)s, %(product_desc)s, %(brand)s, %(category)s, %(sub_category)s, %(pack_size)s, %(uom)s,
            %(billed_qty)s, %(billed_volume)s, %(billed_weight)s, %(currency)s,
            %(gross_value)s, %(net_value)s, %(tax_value)s, %(tax_rate)s
        )
        ON CONFLICT (invoice_id, invoice_line_id, sku_code) DO UPDATE SET
            net_value   = EXCLUDED.net_value,
            gross_value = EXCLUDED.gross_value,
            tax_value   = EXCLUDED.tax_value,
            billed_qty  = EXCLUDED.billed_qty
    """, records, page_size=1000)
    return len(records)


# ── Core ETL orchestrator ─────────────────────────────────────────────────────

def run_etl(tenant: str, secondary_csv: Optional[str] = None, primary_csv: Optional[str] = None):
    schema = f"client_{tenant.lower()}"
    log.info(f"Starting ETL | tenant={tenant} | schema={schema}")

    conn = get_conn()
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # --- Secondary sales ---
            if secondary_csv:
                log.info(f"Loading secondary sales from {secondary_csv}")
                with open(secondary_csv, newline="", encoding="utf-8-sig") as f:
                    rows = list(csv.DictReader(f))
                log.info(f"  Read {len(rows)} rows")

                n = upsert_dim_product(cur, rows);    log.info(f"  dim_product: {n} upserted")
                n = upsert_dim_geography(cur, rows);  log.info(f"  dim_geography: {n} upserted")
                n = upsert_dim_period(cur, rows);     log.info(f"  dim_period: {n} upserted")
                n = upsert_dim_salesorg(cur, rows);   log.info(f"  dim_salesorg: {n} upserted")
                n = upsert_dim_distributor(cur, rows);log.info(f"  dim_distributor: {n} upserted")
                n = load_secondary_sales(cur, schema, rows)
                log.info(f"  fact_secondary_sales: {n} rows loaded")

            # --- Primary sales ---
            if primary_csv:
                log.info(f"Loading primary sales from {primary_csv}")
                with open(primary_csv, newline="", encoding="utf-8-sig") as f:
                    rows = list(csv.DictReader(f))
                log.info(f"  Read {len(rows)} rows")

                n = upsert_dim_product(cur, rows);    log.info(f"  dim_product: {n} upserted")
                n = upsert_dim_geography(cur, rows);  log.info(f"  dim_geography: {n} upserted")
                n = upsert_dim_period(cur, rows);     log.info(f"  dim_period: {n} upserted")
                n = upsert_dim_salesorg(cur, rows);   log.info(f"  dim_salesorg: {n} upserted")
                n = upsert_dim_distributor(cur, rows);log.info(f"  dim_distributor: {n} upserted")
                n = load_primary_sales(cur, schema, rows)
                log.info(f"  fact_primary_sales: {n} rows loaded")

        conn.commit()
        log.info("ETL completed successfully ✅")

    except Exception as e:
        conn.rollback()
        log.error(f"ETL failed — rolled back: {e}", exc_info=True)
        raise
    finally:
        conn.close()


# ── Watch folder mode ─────────────────────────────────────────────────────────

def watch_folder(tenant: str, folder: str, poll_seconds: int = 30):
    """
    Watch a drop-zone folder for CSV files.
    Files named *secondary* → secondary sales, *primary* → primary sales.
    Processed files are moved to <folder>/processed/
    """
    drop_zone = Path(folder)
    processed = drop_zone.parent / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    log.info(f"Watching {drop_zone} every {poll_seconds}s for tenant={tenant}")

    while True:
        for csv_file in sorted(drop_zone.glob("*.csv")):
            name = csv_file.name.lower()
            sec = "secondary" in name or "sec_" in name
            pri = "primary" in name or "pri_" in name

            if not sec and not pri:
                log.warning(f"Skipping {csv_file.name} — name must contain 'secondary' or 'primary'")
                continue

            try:
                run_etl(
                    tenant=tenant,
                    secondary_csv=str(csv_file) if sec else None,
                    primary_csv=str(csv_file) if pri else None,
                )
                dest = processed / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{csv_file.name}"
                csv_file.rename(dest)
                log.info(f"Moved to processed: {dest.name}")
            except Exception as e:
                log.error(f"Failed to process {csv_file.name}: {e}")

        time.sleep(poll_seconds)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CPG Sales ETL — CSV → Postgres")
    parser.add_argument("--tenant",    required=True, help="Tenant name e.g. nestle, itc, unilever")
    parser.add_argument("--secondary", help="Path to secondary sales CSV file")
    parser.add_argument("--primary",   help="Path to primary sales CSV file")
    parser.add_argument("--watch",     help="Drop-zone folder to watch continuously")
    parser.add_argument("--poll",      type=int, default=30, help="Watch poll interval in seconds (default 30)")
    args = parser.parse_args()

    if args.watch:
        watch_folder(args.tenant, args.watch, args.poll)
    elif args.secondary or args.primary:
        run_etl(args.tenant, args.secondary, args.primary)
    else:
        parser.error("Provide --secondary, --primary, or --watch")


if __name__ == "__main__":
    main()
