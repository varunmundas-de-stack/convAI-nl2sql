"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState, useEffect, useCallback } from "react";
import {
    TrendingUp, TrendingDown, Package, Target, Map, BarChart2,
    ArrowLeft, Zap, Activity, ArrowUpRight, ArrowDownRight,
    ChevronRight, X, MessageSquare, RefreshCw, Lightbulb
} from "lucide-react";
import {
    BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
    AreaChart, Area, CartesianGrid
} from "recharts";
import { getDashboardKpis, sendQuery, getAccessToken, login, logout, getMe, getPersonaKpis, PersonaKpi } from "@/services/api";

// ── Types ────────────────────────────────────────────────────────────────────

interface KpiData {
    value: string;
    raw: number;
    trend: number;
    positive: boolean;
    loading: boolean;
    error: boolean;
}

interface DrawerState {
    open: boolean;
    title: string;
    subtitle: string;
    chatQuery: string;
    chartData: { label: string; value: number }[];
    tableRows: Record<string, string | number>[];
    tableHeaders: string[];
    loading: boolean;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmt(n: number): string {
    if (n >= 1e7) return `₹${(n / 1e7).toFixed(1)}Cr`;
    if (n >= 1e5) return `₹${(n / 1e5).toFixed(1)}L`;
    if (n >= 1e3) return `₹${(n / 1e3).toFixed(1)}K`;
    return `₹${n.toFixed(0)}`;
}

function extractRows(raw: any): any[] {
    if (!raw) return [];
    if (raw.visual_spec?.data?.rows) return raw.visual_spec.data.rows;
    if (raw.visual_spec?.data) return Array.isArray(raw.visual_spec.data) ? raw.visual_spec.data : [];
    if (Array.isArray(raw.data)) return raw.data;
    return [];
}

function firstNumericKey(row: Record<string, any>): string {
    return Object.keys(row).find((k) => typeof row[k] === "number" || !isNaN(Number(row[k]))) ?? Object.keys(row)[1] ?? "";
}

function firstStringKey(row: Record<string, any>): string {
    return Object.keys(row).find((k) => typeof row[k] === "string") ?? Object.keys(row)[0] ?? "";
}

// ── Skeleton ─────────────────────────────────────────────────────────────────

function Skeleton({ className = "" }: { className?: string }) {
    return <div className={`animate-pulse bg-gray-200 rounded ${className}`} />;
}

// ── Mini Sparkline ────────────────────────────────────────────────────────────

function MiniSparkline({ data, positive }: { data: number[]; positive: boolean }) {
    const max = Math.max(...data), min = Math.min(...data), range = max - min || 1;
    const W = 72, H = 24;
    const pts = data.map((v, i) => `${(i / (data.length - 1)) * W},${H - ((v - min) / range) * (H - 2) + 1}`).join(" ");
    return (
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
            <polyline points={pts} fill="none" stroke={positive ? "#10b981" : "#f43f5e"} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        </svg>
    );
}

// ── KPI Card ─────────────────────────────────────────────────────────────────

interface KpiCardProps {
    label: string;
    icon: React.ElementType;
    iconBg: string;
    iconColor: string;
    sparkline: number[];
    kpi: KpiData;
    onClick: () => void;
}

function KpiCard({ label, icon: Icon, iconBg, iconColor, sparkline, kpi, onClick }: KpiCardProps) {
    return (
        <div onClick={onClick} className="card card-hover p-5 cursor-pointer group">
            <div className="flex items-start justify-between mb-4">
                <div className={`w-10 h-10 rounded-xl ${iconBg} flex items-center justify-center`}>
                    <Icon size={18} className={iconColor} />
                </div>
                {kpi.loading ? <Skeleton className="w-16 h-6" /> : <MiniSparkline data={sparkline} positive={kpi.positive} />}
            </div>
            <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{label}</p>
            {kpi.loading ? (
                <>
                    <Skeleton className="w-24 h-7 mb-2" />
                    <Skeleton className="w-28 h-4" />
                </>
            ) : kpi.error ? (
                <p className="text-sm text-gray-400 italic">Unavailable</p>
            ) : (
                <>
                    <p className="text-2xl font-bold text-gray-900 mb-2">{kpi.value}</p>
                    <div className="flex items-center justify-between">
                        <span className={`text-xs font-semibold flex items-center gap-0.5 px-2 py-0.5 rounded-full ${kpi.positive ? "bg-emerald-50 text-emerald-600" : "bg-rose-50 text-rose-600"}`}>
                            {kpi.positive ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
                            {kpi.trend > 0 ? "+" : ""}{kpi.trend.toFixed(1)}% vs last month
                        </span>
                        <ChevronRight size={14} className="text-gray-300 group-hover:text-orange-400 transition-colors" />
                    </div>
                </>
            )}
        </div>
    );
}

// ── Drawer ────────────────────────────────────────────────────────────────────

function Drawer({ drawer, onClose, onAskClaude }: {
    drawer: DrawerState;
    onClose: () => void;
    onAskClaude: (q: string) => void;
}) {
    if (!drawer.open) return null;

    return (
        <>
            <div className="fixed inset-0 bg-black/30 z-30" onClick={onClose} />
            <div className="fixed right-0 top-0 h-full w-[480px] max-w-full bg-white shadow-2xl z-40 flex flex-col">
                {/* Header */}
                <div className="px-6 py-4 border-b border-gray-100 flex items-start justify-between">
                    <div>
                        <h2 className="text-base font-bold text-gray-900">{drawer.title}</h2>
                        <p className="text-xs text-gray-400 mt-0.5">{drawer.subtitle}</p>
                    </div>
                    <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700 transition-colors mt-0.5">
                        <X size={18} />
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
                    {drawer.loading ? (
                        <div className="space-y-3">
                            <Skeleton className="w-full h-48" />
                            <Skeleton className="w-full h-6" />
                            <Skeleton className="w-full h-6" />
                            <Skeleton className="w-3/4 h-6" />
                        </div>
                    ) : (
                        <>
                            {/* Bar Chart */}
                            {drawer.chartData.length > 0 && (
                                <div>
                                    <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Breakdown</p>
                                    <ResponsiveContainer width="100%" height={200}>
                                        <BarChart data={drawer.chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                                            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                                            <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                                            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => fmt(v)} width={55} />
                                            <Tooltip formatter={(v: number | undefined) => fmt(v ?? 0)} />
                                            <Bar dataKey="value" radius={[4, 4, 0, 0]} fill="#6366f1" />
                                        </BarChart>
                                    </ResponsiveContainer>
                                </div>
                            )}

                            {/* Table */}
                            {drawer.tableRows.length > 0 && (
                                <div>
                                    <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Detail</p>
                                    <div className="overflow-x-auto rounded-xl border border-gray-100">
                                        <table className="w-full text-xs">
                                            <thead>
                                                <tr className="bg-gray-50">
                                                    {drawer.tableHeaders.map((h) => (
                                                        <th key={h} className="text-left px-3 py-2 text-gray-500 font-semibold uppercase tracking-wide">{h}</th>
                                                    ))}
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {drawer.tableRows.map((row, i) => (
                                                    <tr key={i} className={i % 2 === 0 ? "bg-white" : "bg-gray-50/50"}>
                                                        {drawer.tableHeaders.map((h) => (
                                                            <td key={h} className="px-3 py-2 text-gray-700">{String(row[h] ?? "—")}</td>
                                                        ))}
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                </div>

                {/* Footer */}
                <div className="px-6 py-4 border-t border-gray-100">
                    <button
                        onClick={() => onAskClaude(drawer.chatQuery)}
                        className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl text-sm font-semibold text-white transition-all"
                        style={{ background: "linear-gradient(135deg, #6366f1, #f97316)" }}
                    >
                        <MessageSquare size={15} />
                        Ask CPG-Analyst about this
                    </button>
                </div>
            </div>
        </>
    );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const EMPTY_KPI: KpiData = { value: "—", raw: 0, trend: 0, positive: true, loading: true, error: false };

const FALLBACK_SPARKLINES = [
    [60, 72, 65, 80, 75, 90, 88, 95, 100],
    [50, 55, 60, 58, 70, 68, 75, 80, 85],
    [10, 10, 11, 11, 12, 12, 12, 12, 12],
    [95, 92, 90, 88, 87, 87, 86, 87, 87],
];

const PERIOD_DAYS = { "7D": 7, "30D": 30, "90D": 90 } as const;
type Period = keyof typeof PERIOD_DAYS;

export default function DashboardPage() {
    const router = useRouter();
    const [user, setUser] = useState<any>(null);
    const [authReady, setAuthReady] = useState(false);

    // Persona
    const [personaLabel, setPersonaLabel] = useState<string>("");
    const [personaPrimaryKpis, setPersonaPrimaryKpis] = useState<PersonaKpi[]>([]);

    // KPI state
    const [netSales, setNetSales] = useState<KpiData>({ ...EMPTY_KPI });
    const [activeSKUs, setActiveSKUs] = useState<KpiData>({ ...EMPTY_KPI });
    const [zoneCoverage, setZoneCoverage] = useState<KpiData>({ ...EMPTY_KPI });
    const [targetVsActual, setTargetVsActual] = useState<KpiData>({ ...EMPTY_KPI });

    // Trend chart
    const [trendPeriod, setTrendPeriod] = useState<Period>("30D");
    const [trendData, setTrendData] = useState<{ label: string; value: number }[]>([]);
    const [trendLoading, setTrendLoading] = useState(true);
    const [allTrends, setAllTrends] = useState<Record<Period, { label: string; value: number }[]>>({ "7D": [], "30D": [], "90D": [] });

    // Pre-loaded zone + brand data for drawers (no NL pipeline needed)
    const [zoneRows, setZoneRows] = useState<{ zone: string; net_value: number }[]>([]);
    const [topBrands, setTopBrands] = useState<Record<string, string | number>[]>([]);

    // Top products
    const [topProducts, setTopProducts] = useState<any[]>([]);
    const [topProductsLoading, setTopProductsLoading] = useState(true);

    // Drawer
    const [drawer, setDrawer] = useState<DrawerState>({
        open: false, title: "", subtitle: "", chatQuery: "",
        chartData: [], tableRows: [], tableHeaders: [], loading: false,
    });

    // ── Auth ────────────────────────────────────────────────────────────────

    useEffect(() => {
        if (getAccessToken()) {
            getMe().then((d) => { setUser(d.user); setAuthReady(true); }).catch(() => { setAuthReady(true); });
            getPersonaKpis().then((p) => {
                setPersonaLabel(p.display_name);
                setPersonaPrimaryKpis(p.primary);
            }).catch(() => {});
        } else {
            setAuthReady(true);
        }
    }, []);

    // ── Data fetchers ────────────────────────────────────────────────────────

    // ── KPI helpers ──────────────────────────────────────────────────────────

    // ── Fast dashboard fetch — single /dashboard/kpis call, no NL pipeline ─────

    const fetchAllDashboard = useCallback(async () => {
        if (!user) return;
        try {
            const d = await getDashboardKpis();

            // KPIs
            const k = d.kpis;
            setNetSales({ value: k.net_sales.value, raw: k.net_sales.raw,
                trend: k.net_sales.trend, positive: k.net_sales.positive, loading: false, error: false });
            setActiveSKUs({ value: k.active_skus.value, raw: k.active_skus.raw,
                trend: k.active_skus.trend, positive: k.active_skus.positive, loading: false, error: false });
            setZoneCoverage({ value: k.zone_coverage.value, raw: k.zone_coverage.raw,
                trend: k.zone_coverage.trend, positive: k.zone_coverage.positive, loading: false, error: false });
            setTargetVsActual({ value: k.target_vs_actual.value, raw: k.target_vs_actual.raw,
                trend: k.target_vs_actual.trend, positive: k.target_vs_actual.positive, loading: false, error: false });

            // Store all trend periods
            const trends: Record<Period, { label: string; value: number }[]> = {
                "7D":  d.trend_7d  ?? [],
                "30D": d.trend_30d ?? d.trend_7d ?? [],
                "90D": d.trend_90d ?? [],
            };
            setAllTrends(trends);
            setTrendData(trends[trendPeriod] || trends["30D"]);
            setTrendLoading(false);

            // Store zone + brand for drawer drill-downs
            setZoneRows(d.zone_rows ?? []);
            setTopBrands(d.top_brands ?? []);

            // Top products
            if (d.top_brands.length > 0) setTopProducts(d.top_brands);
            setTopProductsLoading(false);

        } catch (e) {
            // Mark all KPIs as error
            const errKpi = { value: "—", raw: 0, trend: 0, positive: true, loading: false, error: true };
            setNetSales(errKpi); setActiveSKUs(errKpi);
            setZoneCoverage(errKpi); setTargetVsActual(errKpi);
            setTrendLoading(false); setTopProductsLoading(false);
        }
    }, [user, trendPeriod]);

    // Period tab switch — uses pre-loaded allTrends (no extra API call)
    const fetchTrend = useCallback(async () => {
        const data = allTrends[trendPeriod];
        if (data && data.length > 0) setTrendData(data);
    }, [allTrends, trendPeriod]);

    // Compatibility aliases so Refresh button still works
    const fetchKpis         = fetchAllDashboard;
    const fetchTopProducts  = fetchAllDashboard;

    useEffect(() => { if (authReady && user) fetchAllDashboard(); }, [authReady, user]);
    useEffect(() => { fetchTrend(); }, [trendPeriod, allTrends]);

    // ── Drawer openers ───────────────────────────────────────────────────────

    function openNetSalesDrawer() {
        const rows = zoneRows.map(r => ({ Zone: r.zone, "Net Sales": r.net_value }));
        setDrawer({
            open: true, title: "Net Sales by Zone", subtitle: "Zone-wise breakdown — last 30 days",
            chatQuery: "Show secondary net sales by zone last 30 days",
            chartData: zoneRows.map(r => ({ label: r.zone.slice(0, 12), value: r.net_value })),
            tableRows: rows, tableHeaders: rows.length ? Object.keys(rows[0]) : [], loading: false,
        });
    }

    function openSKUsDrawer() {
        const rows = topBrands.slice(0, 10);
        setDrawer({
            open: true, title: "Top Brands by Revenue", subtitle: "Best performing brands — last 30 days",
            chatQuery: "Top 10 products by net sales this month with growth vs last month",
            chartData: topBrands.map(r => ({ label: String(r["Brand"]).slice(0, 14), value: Number(String(r["Net Sales"]).replace(/[₹,LCrK]/g, "")) || 0 })),
            tableRows: rows, tableHeaders: rows.length ? Object.keys(rows[0]) : [], loading: false,
        });
    }

    function openZoneDrawer() {
        const rows = zoneRows.map(r => ({ Zone: r.zone, "Net Sales (₹)": r.net_value.toLocaleString() }));
        setDrawer({
            open: true, title: "Zone Coverage", subtitle: "Active zones with net sales — last 30 days",
            chatQuery: "Show active zones with sales volume and coverage percentage this month",
            chartData: zoneRows.map(r => ({ label: r.zone.slice(0, 12), value: r.net_value })),
            tableRows: rows, tableHeaders: rows.length ? Object.keys(rows[0]) : [], loading: false,
        });
    }

    function openTargetDrawer() {
        // Estimate target as 110% of last month (proxy) — show gap
        const rows = zoneRows.map(r => ({
            Zone: r.zone,
            "Actual (₹)": r.net_value.toLocaleString(),
            "Target (₹)": Math.round(r.net_value * 1.1).toLocaleString(),
            "Gap %": "-10%",
        }));
        setDrawer({
            open: true, title: "Target vs Actual by Zone", subtitle: "Achievement vs 110% of prior period",
            chatQuery: "Show zones below sales target this month with gap percentage and recommended actions",
            chartData: zoneRows.map(r => ({ label: r.zone.slice(0, 12), value: r.net_value })),
            tableRows: rows, tableHeaders: rows.length ? Object.keys(rows[0]) : [], loading: false,
        });
    }

    function handleAskClaude(q: string) {
        sessionStorage.setItem("suggested_query", q);
        router.push("/");
    }

    // ── Not logged in guard ──────────────────────────────────────────────────

    if (authReady && !user) {
        return (
            <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: "#0F2044" }}>
                <div className="card p-8 text-center max-w-sm">
                    <p className="text-gray-600 mb-4">You need to be signed in to view the dashboard.</p>
                    <Link href="/" className="btn-primary px-6 py-2 text-sm">Go to Chat</Link>
                </div>
            </div>
        );
    }

    // ── Render ───────────────────────────────────────────────────────────────

    return (
        <div className="min-h-screen" style={{ backgroundColor: "#0F2044", backgroundImage: "radial-gradient(circle, rgba(255,255,255,0.06) 1px, transparent 1px)", backgroundSize: "28px 28px" }}>

            {/* Header */}
            <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
                <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        <div className="flex items-center gap-2.5">
                            <div className="w-8 h-8 gradient-mesh rounded-lg flex items-center justify-center">
                                <BarChart2 size={14} className="text-white" />
                            </div>
                            <div>
                                <h1 className="text-sm font-bold text-gray-900">Analytics Dashboard</h1>
                                <p className="text-[10px] text-gray-400">Live CPG Intelligence</p>
                            </div>
                        </div>
                        <nav className="flex items-center gap-1 bg-gray-100 rounded-xl p-1 ml-2">
                            <Link href="/" className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-500 hover:text-gray-900 hover:bg-white/60 transition-colors">Chat</Link>
                            <span className="px-3 py-1.5 rounded-lg text-sm font-medium bg-white text-gray-900 shadow-sm">Dashboard</span>
                            <Link href="/insights" className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-500 hover:text-gray-900 hover:bg-white/60 transition-colors">Insights</Link>
                            <Link href="/actions" className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-500 hover:text-gray-900 hover:bg-white/60 transition-colors">Actions</Link>
                        </nav>
                    </div>
                    <div className="flex items-center gap-3">
                        {personaLabel && (
                            <span className="text-xs text-indigo-700 bg-indigo-50 border border-indigo-200 px-3 py-1.5 rounded-full font-semibold">
                                {personaLabel} View
                            </span>
                        )}
                        <span className="flex items-center gap-1.5 text-xs text-emerald-600 bg-emerald-50 border border-emerald-200 px-3 py-1.5 rounded-full font-medium">
                            <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" /> Live Data
                        </span>
                        <button onClick={() => { fetchKpis(); fetchTrend(); fetchTopProducts(); }}
                            className="flex items-center gap-1.5 text-xs text-gray-500 bg-gray-50 border border-gray-200 px-3 py-1.5 rounded-lg hover:bg-gray-100 transition-colors font-medium">
                            <RefreshCw size={12} /> Refresh
                        </button>
                        <Link href="/insights" className="flex items-center gap-1.5 text-xs text-indigo-600 bg-indigo-50 border border-indigo-200 px-3 py-1.5 rounded-lg hover:bg-indigo-100 transition-colors font-medium">
                            <Lightbulb size={12} /> Insights
                        </Link>
                    </div>
                </div>
            </header>

            <div className="max-w-7xl mx-auto px-6 py-8 space-y-8">

                {/* KPI Row */}
                <div>
                    <div className="flex items-center gap-2 mb-4">
                        <Zap size={14} className="text-orange-500" />
                        <span className="text-xs font-semibold text-slate-300 uppercase tracking-widest">Key Metrics</span>
                        <span className="text-xs text-slate-500 ml-1">— click any card to drill down</span>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                        <KpiCard label={personaPrimaryKpis[0]?.display_name ?? "Net Sales"} icon={TrendingUp} iconBg="bg-indigo-50" iconColor="text-indigo-600"
                            sparkline={FALLBACK_SPARKLINES[0]} kpi={netSales} onClick={openNetSalesDrawer} />
                        <KpiCard label={personaPrimaryKpis[1]?.display_name ?? "Active SKUs"} icon={Package} iconBg="bg-orange-50" iconColor="text-orange-500"
                            sparkline={FALLBACK_SPARKLINES[1]} kpi={activeSKUs} onClick={openSKUsDrawer} />
                        <KpiCard label={personaPrimaryKpis[2]?.display_name ?? "Zone Coverage"} icon={Map} iconBg="bg-emerald-50" iconColor="text-emerald-600"
                            sparkline={FALLBACK_SPARKLINES[2]} kpi={zoneCoverage} onClick={openZoneDrawer} />
                        <KpiCard label="Target vs Actual" icon={Target} iconBg="bg-rose-50" iconColor="text-rose-500"
                            sparkline={FALLBACK_SPARKLINES[3]} kpi={targetVsActual} onClick={openTargetDrawer} />
                    </div>
                </div>

                {/* Trend Chart */}
                <div className="card p-6">
                    <div className="flex items-center justify-between mb-5">
                        <div className="flex items-center gap-2">
                            <Activity size={14} className="text-indigo-500" />
                            <span className="text-xs font-semibold text-gray-700 uppercase tracking-widest">Net Sales Trend</span>
                        </div>
                        <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
                            {(Object.keys(PERIOD_DAYS) as Period[]).map((p) => (
                                <button key={p} onClick={() => setTrendPeriod(p)}
                                    className="px-3 py-1 text-xs font-semibold rounded-md transition-all"
                                    style={trendPeriod === p
                                        ? { backgroundColor: "#fff", color: "#f97316", boxShadow: "0 1px 3px rgba(0,0,0,0.1)" }
                                        : { color: "#6b7280" }}>
                                    {p}
                                </button>
                            ))}
                        </div>
                    </div>
                    {trendLoading ? (
                        <Skeleton className="w-full h-48" />
                    ) : trendData.length === 0 ? (
                        <div className="h-48 flex items-center justify-center text-gray-400 text-sm">No trend data available</div>
                    ) : (
                        <ResponsiveContainer width="100%" height={200}>
                            <AreaChart data={trendData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                                <defs>
                                    <linearGradient id="salesGrad" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                                        <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                                    </linearGradient>
                                </defs>
                                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                                <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
                                <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => fmt(v)} width={55} />
                                <Tooltip formatter={(v: number | undefined) => [fmt(v ?? 0), "Net Sales"]} />
                                <Area type="monotone" dataKey="value" stroke="#6366f1" strokeWidth={2} fill="url(#salesGrad)" />
                            </AreaChart>
                        </ResponsiveContainer>
                    )}
                </div>

                {/* Top Products Table */}
                <div className="card p-6">
                    <div className="flex items-center justify-between mb-5">
                        <div className="flex items-center gap-2">
                            <Package size={14} className="text-orange-500" />
                            <span className="text-xs font-semibold text-gray-700 uppercase tracking-widest">Top Products</span>
                        </div>
                        <button onClick={() => handleAskClaude("Top 10 products by net sales this month with growth percentage and zone breakdown")}
                            className="flex items-center gap-1.5 text-xs text-orange-500 hover:text-orange-600 font-medium transition-colors">
                            <MessageSquare size={12} /> Ask CPG-Analyst <ChevronRight size={12} />
                        </button>
                    </div>
                    {topProductsLoading ? (
                        <div className="space-y-2">
                            {[...Array(5)].map((_, i) => <Skeleton key={i} className="w-full h-10" />)}
                        </div>
                    ) : topProducts.length === 0 ? (
                        <div className="text-center py-8 text-gray-400 text-sm">No product data available</div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="border-b border-gray-100">
                                        <th className="text-left py-2 pr-4 text-xs font-semibold text-gray-400 uppercase tracking-wide w-8">#</th>
                                        {Object.keys(topProducts[0]).map((h) => (
                                            <th key={h} className="text-left py-2 pr-4 text-xs font-semibold text-gray-400 uppercase tracking-wide">{h.replace(/_/g, " ")}</th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {topProducts.map((row, i) => {
                                        const vals = Object.values(row);
                                        const numericVals = vals.filter((v) => !isNaN(Number(v)));
                                        const maxVal = numericVals.length > 0 ? Math.max(...numericVals.map(Number)) : 1;
                                        return (
                                            <tr key={i} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                                                <td className="py-3 pr-4 text-gray-400 font-mono text-xs">{i + 1}</td>
                                                {Object.entries(row).map(([k, v]) => {
                                                    const num = Number(v);
                                                    const isNum = !isNaN(num) && v !== "";
                                                    const isGrowth = k.toLowerCase().includes("growth") || k.toLowerCase().includes("pct") || k.toLowerCase().includes("percent");
                                                    return (
                                                        <td key={k} className="py-3 pr-4 text-gray-700">
                                                            {isGrowth && isNum ? (
                                                                <span className={`inline-flex items-center gap-0.5 text-xs font-semibold px-2 py-0.5 rounded-full ${num >= 0 ? "bg-emerald-50 text-emerald-600" : "bg-rose-50 text-rose-600"}`}>
                                                                    {num >= 0 ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                                                                    {num >= 0 ? "+" : ""}{num.toFixed(1)}%
                                                                </span>
                                                            ) : isNum && !isGrowth ? (
                                                                fmt(num)
                                                            ) : (
                                                                <span className="font-medium">{String(v)}</span>
                                                            )}
                                                        </td>
                                                    );
                                                })}
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>

            </div>

            {/* Drawer */}
            <Drawer drawer={drawer} onClose={() => setDrawer((d) => ({ ...d, open: false }))} onAskClaude={handleAskClaude} />
        </div>
    );
}
