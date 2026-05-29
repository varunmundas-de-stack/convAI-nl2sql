"""
Standalone role-aware insight generator — direct Postgres, no Cube, no NL pipeline.
Imported by both main.py and metadata_store.py (no circular dependency).
"""
from __future__ import annotations
import logging, os, uuid
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def _fmt(n: float) -> str:
    n = float(n or 0)
    if n >= 1e7: return f"\u20b9{n/1e7:.1f}Cr"
    if n >= 1e5: return f"\u20b9{n/1e5:.1f}L"
    if n >= 1e3: return f"\u20b9{n/1e3:.0f}K"
    return f"\u20b9{n:.0f}"


def generate_insights(schema: str, role: str, user: Any) -> list[dict]:
    try:
        import psycopg2, psycopg2.extras
    except ImportError:
        logger.error("[Insights] psycopg2 not available")
        return []

    today = date.today()
    d7    = (today - timedelta(days=7)).isoformat()
    d14   = (today - timedelta(days=14)).isoformat()
    d30   = (today - timedelta(days=30)).isoformat()
    d60   = (today - timedelta(days=60)).isoformat()
    tod   = today.isoformat()

    dsn = {
        "host":     os.getenv("DB_HOST",     os.getenv("POSTGRES_HOST",     "postgres")),
        "port":     int(os.getenv("DB_PORT", os.getenv("POSTGRES_PORT",     "5432"))),
        "dbname":   os.getenv("DB_NAME",     os.getenv("POSTGRES_DB",       "sales_analytics")),
        "user":     os.getenv("DB_USER",     os.getenv("POSTGRES_USER",     "postgres")),
        "password": os.getenv("DB_PASS",     os.getenv("POSTGRES_PASSWORD", "postgres")),
    }

    role_upper = (role or "").upper()
    role_filter = ""
    if role_upper == "SO" and getattr(user, "salesrep_code", None):
        role_filter = f"AND salesrep_code = {repr(user.salesrep_code)}"
    elif role_upper == "ASM" and getattr(user, "asm_code", None):
        role_filter = f"AND asm_code = {repr(user.asm_code)}"
    elif role_upper == "ZSM" and getattr(user, "zsm_code", None):
        role_filter = f"AND zsm_code = {repr(user.zsm_code)}"

    insights: list[dict] = []

    try:
        conn = psycopg2.connect(**dsn)
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1 — SKU Concentration Risk
        cur.execute(f"""
            WITH s AS (
                SELECT sku_code, brand, SUM(net_value) AS v,
                       SUM(SUM(net_value)) OVER () AS tot
                FROM {schema}.fact_secondary_sales
                WHERE invoice_date BETWEEN %s AND %s {role_filter}
                GROUP BY sku_code, brand
            )
            SELECT sku_code, brand, v, ROUND((v/NULLIF(tot,0)*100)::numeric,1) AS pct
            FROM s ORDER BY v DESC LIMIT 5
        """, (d30, tod))
        rows = cur.fetchall()
        if rows:
            top3 = sum(float(r["pct"] or 0) for r in rows[:3])
            if top3 > 25:
                t = rows[0]
                insights.append(dict(
                    insight_id=str(uuid.uuid4()), is_read=False, data_json=None,
                    metric_change_pct=None, detection_method="sku_concentration",
                    insight_type="concentration_risk",
                    priority="high" if top3 > 45 else "medium",
                    title=f"SKU Concentration Risk — Top 3 SKUs drive {top3:.0f}% of revenue",
                    description=(f"{t['brand']} ({t['sku_code']}) alone is {float(t['pct']):.1f}% "
                                 f"({_fmt(t['v'])}) of 30-day secondary sales. Top 3 SKUs = {top3:.0f}% — "
                                 f"any supply disruption hits your total immediately."),
                    suggested_action=f"Activate 2-3 adjacent SKUs to reduce dependency on {t['brand']}.",
                ))

        # 2 — Zone Velocity Divergence
        cur.execute(f"""
            WITH z AS (
                SELECT zone,
                    SUM(CASE WHEN invoice_date BETWEEN %s AND %s THEN net_value ELSE 0 END) AS cur,
                    SUM(CASE WHEN invoice_date BETWEEN %s AND %s THEN net_value ELSE 0 END) AS prev
                FROM {schema}.fact_secondary_sales
                WHERE invoice_date BETWEEN %s AND %s {role_filter}
                GROUP BY zone
            )
            SELECT zone, cur, prev,
                   ROUND(((cur-prev)/NULLIF(prev,0)*100)::numeric,1) AS chg
            FROM z WHERE prev > 0 ORDER BY chg DESC
        """, (d14, tod, d30, d14, d30, tod))
        rows = cur.fetchall()
        if len(rows) >= 2:
            best, worst = rows[0], rows[-1]
            spread = float(best["chg"] or 0) - float(worst["chg"] or 0)
            if spread > 10:
                insights.append(dict(
                    insight_id=str(uuid.uuid4()), is_read=False, data_json=None,
                    detection_method="velocity_divergence", insight_type="zone_divergence",
                    priority="high" if spread > 20 else "medium",
                    metric_change_pct=round(float(worst["chg"] or 0), 1),
                    title=f"Zone Gap — {best['zone']} +{float(best['chg']):.1f}% while {worst['zone']} {float(worst['chg']):.1f}%",
                    description=(f"{best['zone']} accelerating (+{float(best['chg']):.1f}%, {_fmt(best['cur'])}) "
                                 f"while {worst['zone']} declining ({float(worst['chg']):.1f}%, {_fmt(worst['cur'])}). "
                                 f"{spread:.0f}pp spread signals execution gap, not market difference."),
                    suggested_action=f"Pull distributor call reports for {worst['zone']} — benchmark vs {best['zone']}.",
                ))

        # 3 — Dormant High-Value Brand
        cur.execute(f"""
            WITH b AS (
                SELECT brand,
                    SUM(CASE WHEN invoice_date BETWEEN %s AND %s THEN net_value ELSE 0 END) AS cur,
                    SUM(CASE WHEN invoice_date BETWEEN %s AND %s THEN net_value ELSE 0 END) AS prev
                FROM {schema}.fact_secondary_sales
                WHERE invoice_date BETWEEN %s AND %s {role_filter}
                GROUP BY brand
            ),
            r AS (SELECT *, RANK() OVER (ORDER BY prev DESC) AS rnk FROM b)
            SELECT brand, cur, prev,
                   ROUND(((cur-prev)/NULLIF(prev,0)*100)::numeric,1) AS chg
            FROM r WHERE rnk <= 5 AND cur < prev * 0.85 ORDER BY prev DESC LIMIT 1
        """, (d14, tod, d30, d14, d30, tod))
        row = cur.fetchone()
        if row:
            insights.append(dict(
                insight_id=str(uuid.uuid4()), is_read=False, data_json=None,
                detection_method="brand_rank_drop", insight_type="brand_dormancy",
                priority="critical" if float(row["chg"] or 0) < -30 else "high",
                metric_change_pct=round(float(row["chg"] or 0), 1),
                title=f"{row['brand']} — Was Top-5, Now Down {abs(float(row['chg'])):.0f}%",
                description=(f"{row['brand']} was top-5 ({_fmt(row['prev'])}) last period but "
                             f"only {_fmt(row['cur'])} this period. "
                             f"Masked by other brands in zone totals — investigate immediately."),
                suggested_action=f"Check distributor stock + retailer shelf for {row['brand']} in last 7 days.",
            ))

        # 4 — Weekday vs Weekend Pattern
        cur.execute(f"""
            SELECT
                ROUND(AVG(CASE WHEN EXTRACT(DOW FROM d) IN (0,6) THEN s END)::numeric,0) AS we,
                ROUND(AVG(CASE WHEN EXTRACT(DOW FROM d) NOT IN (0,6) THEN s END)::numeric,0) AS wd
            FROM (
                SELECT invoice_date::date AS d, SUM(net_value) AS s
                FROM {schema}.fact_secondary_sales
                WHERE invoice_date BETWEEN %s AND %s {role_filter}
                GROUP BY invoice_date::date
            ) x
        """, (d30, tod))
        row = cur.fetchone()
        if row and row["wd"] and row["we"]:
            wd, we = float(row["wd"]), float(row["we"])
            ratio = wd / we if we > 0 else 0
            if ratio > 1.5:
                insights.append(dict(
                    insight_id=str(uuid.uuid4()), is_read=False, data_json=None,
                    detection_method="weekday_weekend_ratio", insight_type="sales_pattern",
                    priority="medium", metric_change_pct=round((ratio-1)*100, 1),
                    title=f"Push-Model Signal — Weekday sales {ratio:.1f}x higher than weekends",
                    description=(f"Weekday avg {_fmt(wd)}/day vs weekend {_fmt(we)}/day. "
                                 f"Field-rep activity is driving orders, not consumer pull. "
                                 f"Outlet sell-through may lag behind fill rates."),
                    suggested_action="Cross-check primary sales (offtake) vs secondary — divergence = pipeline loading.",
                ))

        # 5 — Emerging SKU
        cur.execute(f"""
            WITH s AS (
                SELECT sku_code, brand,
                    SUM(CASE WHEN invoice_date BETWEEN %s AND %s THEN net_value ELSE 0 END) AS cur,
                    SUM(CASE WHEN invoice_date BETWEEN %s AND %s THEN net_value ELSE 0 END) AS prev,
                    SUM(SUM(CASE WHEN invoice_date BETWEEN %s AND %s THEN net_value ELSE 0 END)) OVER () AS tot
                FROM {schema}.fact_secondary_sales
                WHERE invoice_date BETWEEN %s AND %s {role_filter}
                GROUP BY sku_code, brand
            )
            SELECT sku_code, brand, cur, prev,
                   ROUND(((cur-prev)/NULLIF(prev,0)*100)::numeric,1) AS chg,
                   ROUND((prev/NULLIF(tot,0)*100)::numeric,1) AS share
            FROM s WHERE prev > 0 AND prev/NULLIF(tot,0) < 0.20
              AND (cur-prev)/NULLIF(prev,0) > 0.20
            ORDER BY chg DESC LIMIT 1
        """, (d14, tod, d30, d14, d30, d14, d30, tod))
        row = cur.fetchone()
        if row:
            insights.append(dict(
                insight_id=str(uuid.uuid4()), is_read=False, data_json=None,
                detection_method="momentum_detection", insight_type="emerging_sku",
                priority="medium", metric_change_pct=round(float(row["chg"] or 0), 1),
                title=f"Emerging SKU — {row['brand']} ({row['sku_code']}) up {float(row['chg']):.0f}%",
                description=(f"{row['sku_code']} had only {float(row['share']):.1f}% share but "
                             f"grew {float(row['chg']):.0f}% ({_fmt(row['prev'])} → {_fmt(row['cur'])}). "
                             f"Small-base high-growth = early breakout signal."),
                suggested_action=f"Push {row['sku_code']} distribution now — before competition notices.",
            ))

        # 6 — EOM Channel Stuffing
        cur.execute(f"""
            WITH m AS (
                SELECT DATE_TRUNC('month', invoice_date) AS mo,
                       SUM(net_value) AS tot,
                       SUM(CASE WHEN EXTRACT(DAY FROM invoice_date) >= 28 THEN net_value ELSE 0 END) AS last3
                FROM {schema}.fact_secondary_sales
                WHERE invoice_date BETWEEN %s AND %s {role_filter}
                GROUP BY DATE_TRUNC('month', invoice_date)
            )
            SELECT mo, tot, last3, ROUND((last3/NULLIF(tot,0)*100)::numeric,1) AS pct
            FROM m WHERE tot > 0 ORDER BY mo DESC LIMIT 3
        """, (d60, tod))
        rows = cur.fetchall()
        spikes = [r for r in rows if float(r["pct"] or 0) > 30]
        if len(spikes) >= 2:
            avg = sum(float(r["pct"]) for r in spikes) / len(spikes)
            insights.append(dict(
                insight_id=str(uuid.uuid4()), is_read=False, data_json=None,
                detection_method="eom_spike", insight_type="channel_stuffing",
                priority="high", metric_change_pct=round(avg, 1),
                title=f"Channel Stuffing — Last 3 days of month = {avg:.0f}% of sales",
                description=(f"Across {len(spikes)} months, last-3-days consistently "
                             f"= {avg:.0f}% of secondary sales. "
                             f"Classic end-of-month push to hit targets — not consumer demand."),
                suggested_action="Compare primary vs secondary invoicing same months — divergence confirms pipeline loading.",
            ))

        # 7 — Distributor Dependency
        cur.execute(f"""
            WITH d AS (
                SELECT distributor_name, zone, SUM(net_value) AS v,
                       SUM(SUM(net_value)) OVER (PARTITION BY zone) AS zt
                FROM {schema}.fact_secondary_sales
                WHERE invoice_date BETWEEN %s AND %s {role_filter}
                GROUP BY distributor_name, zone
            )
            SELECT distributor_name, zone, v,
                   ROUND((v/NULLIF(zt,0)*100)::numeric,1) AS pct
            FROM d WHERE v/NULLIF(zt,0) > 0.25
            ORDER BY pct DESC LIMIT 1
        """, (d30, tod))
        row = cur.fetchone()
        if row:
            insights.append(dict(
                insight_id=str(uuid.uuid4()), is_read=False, data_json=None,
                detection_method="concentration_probe", insight_type="distributor_dependency",
                priority="high" if float(row["pct"]) > 40 else "medium",
                metric_change_pct=None,
                title=f"Distributor Risk — {row['distributor_name']} = {float(row['pct']):.0f}% of {row['zone']}",
                description=(f"{row['distributor_name']} handles {float(row['pct']):.0f}% ({_fmt(row['v'])}) "
                             f"of {row['zone']} zone. Any credit block or dispute = immediate zone impact."),
                suggested_action=f"Appoint secondary distributor in {row['zone']} to reduce {row['distributor_name']} exposure.",
            ))

        # 8 — Pack Mix Shift
        cur.execute(f"""
            WITH p AS (
                SELECT pack_size,
                    SUM(CASE WHEN invoice_date BETWEEN %s AND %s THEN net_value ELSE 0 END) AS cur,
                    SUM(CASE WHEN invoice_date BETWEEN %s AND %s THEN net_value ELSE 0 END) AS prev
                FROM {schema}.fact_secondary_sales
                WHERE invoice_date BETWEEN %s AND %s {role_filter}
                  AND pack_size IS NOT NULL
                GROUP BY pack_size
            )
            SELECT pack_size, cur, prev,
                   ROUND(((cur-prev)/NULLIF(prev,0)*100)::numeric,1) AS chg
            FROM p WHERE prev > 0 ORDER BY chg ASC LIMIT 1
        """, (d14, tod, d30, d14, d30, tod))
        row = cur.fetchone()
        if row and float(row["chg"] or 0) < -5:
            insights.append(dict(
                insight_id=str(uuid.uuid4()), is_read=False, data_json=None,
                detection_method="mix_shift_probe", insight_type="pack_mix_shift",
                priority="medium", metric_change_pct=round(float(row["chg"] or 0), 1),
                title=f"Pack Mix Shift — {row['pack_size']} declining {abs(float(row['chg'])):.0f}%",
                description=(f"{row['pack_size']} pack down {abs(float(row['chg'])):.0f}% "
                             f"({_fmt(row['prev'])} → {_fmt(row['cur'])}). "
                             f"Pack size migration = affordability pressure or competitor pricing — "
                             f"invisible at brand-level totals."),
                suggested_action=f"Check if smaller packs gaining share — trading-down signal.",
            ))

        cur.close()
        conn.close()

    except Exception as e:
        logger.error(f"[Insights] DB probe failed: {e}", exc_info=True)

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    insights.sort(key=lambda x: priority_order.get(str(x.get("priority", "low")), 9))
    return insights
