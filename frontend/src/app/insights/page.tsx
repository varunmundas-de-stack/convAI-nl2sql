"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
    ArrowLeft, TrendingDown, TrendingUp, AlertTriangle, Activity,
    Clock, Zap, Bookmark, BookmarkCheck, ThumbsDown, MessageSquare,
    RefreshCw, Sparkles, Bell, Filter, Layers, CheckCheck, BarChart2,
    Target, Flame, Shield, Users, Package, Map, ArrowUpRight,
    ArrowDownRight, ChevronRight, Star, Eye, EyeOff, Lightbulb,
    TrendingUp as TrendUp
} from "lucide-react";
import { getInsights, markInsightRead, postInsightFeedback, triggerIntelRun, getAccessToken, getMe } from "@/services/api";

// ─── Types ───────────────────────────────────────────────────────────────────
interface SparklineSignal {
    sparkline?: number[];
    z_score?: number;
    r_squared?: number;
    normalized_slope?: number;
    days_inactive?: number;
    target?: number;
    gap_pct?: number;
    dimension_filters?: Record<string, string>;
}

interface Insight {
    insight_id: string;
    title: string;
    description: string;
    insight_type: string;
    detection_method?: string;
    priority: "low" | "medium" | "high" | "critical";
    metric_value?: number | null;
    metric_change_pct?: number | null;
    suggested_action?: string | null;
    suggested_query?: string | null;
    period_start?: string | null;
    period_end?: string | null;
    expires_at?: string | null;
    is_read: boolean;
    created_at: string;
    data_json?: { signal?: SparklineSignal } | null;
    _pinned?: boolean;
    _dismissed?: boolean;
}

// ─── Role-based Nudges ───────────────────────────────────────────────────────
const ROLE_NUDGES: Record<string, { label: string; query: string; icon: any; color: string; bg: string; border: string }[]> = {
    admin: [
        { label: "Full P&L by Zone", query: "Show net sales and gross margin by zone this month", icon: BarChart2, color: "text-violet-300", bg: "bg-violet-500/15", border: "border-violet-500/30" },
        { label: "Bottom 5 SKUs", query: "Which 5 SKUs had lowest sales last 30 days", icon: TrendingDown, color: "text-rose-300", bg: "bg-rose-500/15", border: "border-rose-500/30" },
        { label: "Target Gap Analysis", query: "Show zones below sales target this month with gap percentage", icon: Target, color: "text-amber-300", bg: "bg-amber-500/15", border: "border-amber-500/30" },
        { label: "Distributor Review", query: "Top 10 distributors by secondary sales last 30 days", icon: Users, color: "text-sky-300", bg: "bg-sky-500/15", border: "border-sky-500/30" },
        { label: "Brand Performance", query: "Net sales by brand for current month vs last month", icon: Star, color: "text-emerald-300", bg: "bg-emerald-500/15", border: "border-emerald-500/30" },
        { label: "Inactive Outlets", query: "Show retailers with zero purchases in last 14 days", icon: Clock, color: "text-orange-300", bg: "bg-orange-500/15", border: "border-orange-500/30" },
    ],
    analytics: [
        { label: "Zone Heatmap", query: "Show net sales by zone for last 30 days", icon: Map, color: "text-violet-300", bg: "bg-violet-500/15", border: "border-violet-500/30" },
        { label: "Category Split", query: "Sales breakdown by product category this month", icon: Layers, color: "text-sky-300", bg: "bg-sky-500/15", border: "border-sky-500/30" },
        { label: "Monthly Trend", query: "Show monthly sales trend for last 6 months", icon: TrendingUp, color: "text-emerald-300", bg: "bg-emerald-500/15", border: "border-emerald-500/30" },
        { label: "Pack Size Analysis", query: "Sales volume by pack size this quarter", icon: Package, color: "text-amber-300", bg: "bg-amber-500/15", border: "border-amber-500/30" },
    ],
    asm: [
        { label: "My Territory Sales", query: "Show net sales for my ASM territory last 30 days", icon: Map, color: "text-violet-300", bg: "bg-violet-500/15", border: "border-violet-500/30" },
        { label: "SO Performance", query: "Top performing sales officers in my territory", icon: Users, color: "text-sky-300", bg: "bg-sky-500/15", border: "border-sky-500/30" },
        { label: "Beat Efficiency", query: "Which routes have lowest coverage in my area", icon: Activity, color: "text-rose-300", bg: "bg-rose-500/15", border: "border-rose-500/30" },
        { label: "Strike Rate", query: "Productive calls vs total calls by salesrep this week", icon: Target, color: "text-amber-300", bg: "bg-amber-500/15", border: "border-amber-500/30" },
    ],
    salesrep: [
        { label: "My Route Sales", query: "Show my sales for this month", icon: TrendingUp, color: "text-emerald-300", bg: "bg-emerald-500/15", border: "border-emerald-500/30" },
        { label: "Inactive Retailers", query: "Which retailers on my route haven't purchased in 7 days", icon: AlertTriangle, color: "text-rose-300", bg: "bg-rose-500/15", border: "border-rose-500/30" },
        { label: "Top SKUs", query: "Top selling products on my route this month", icon: Package, color: "text-amber-300", bg: "bg-amber-500/15", border: "border-amber-500/30" },
    ],
};

// ─── Constants ────────────────────────────────────────────────────────────────
const DET: Record<string, { icon: any; gradient: string; label: string; accent: string }> = {
    anomaly:    { icon: AlertTriangle, gradient: "from-amber-500 to-orange-600",   label: "Anomaly",    accent: "#f59e0b" },
    trend:      { icon: TrendingDown,  gradient: "from-rose-500 to-pink-600",      label: "Trend",      accent: "#f87171" },
    target_gap: { icon: Target,        gradient: "from-orange-500 to-red-600",     label: "Target Gap", accent: "#fb923c" },
    inactivity: { icon: Clock,         gradient: "from-slate-500 to-slate-600",    label: "Inactivity", accent: "#94a3b8" },
    default:    { icon: Sparkles,      gradient: "from-violet-500 to-fuchsia-600", label: "Insight",    accent: "#a78bfa" },
};

const PRI_CONFIG: Record<string, { label: string; bg: string; text: string; border: string; dot: string }> = {
    critical: { label: "CRITICAL", bg: "bg-rose-500/20",   text: "text-rose-300",   border: "border-rose-500/40",   dot: "bg-rose-400" },
    high:     { label: "HIGH",     bg: "bg-amber-500/20",  text: "text-amber-300",  border: "border-amber-500/40",  dot: "bg-amber-400" },
    medium:   { label: "MEDIUM",   bg: "bg-sky-500/20",    text: "text-sky-300",    border: "border-sky-500/40",    dot: "bg-sky-400" },
    low:      { label: "LOW",      bg: "bg-slate-500/20",  text: "text-slate-400",  border: "border-slate-500/40",  dot: "bg-slate-400" },
};

const fmt = (n: number) =>
    n >= 1_000_000 ? `₹${(n / 1_000_000).toFixed(1)}M`
    : n >= 1_000   ? `₹${(n / 1_000).toFixed(0)}K`
    : `₹${n.toFixed(0)}`;

const timeAgo = (s: string) => {
    const m = Math.floor((Date.now() - new Date(s).getTime()) / 60000);
    return m < 60 ? `${m}m ago` : m < 1440 ? `${Math.floor(m / 60)}h ago` : `${Math.floor(m / 1440)}d ago`;
};

// ─── Sparkline ────────────────────────────────────────────────────────────────
function Sparkline({ data, accent }: { data: number[]; accent: string }) {
    if (data.length < 2) return null;
    const max = Math.max(...data), min = Math.min(...data), range = max - min || 1;
    const W = 100, H = 36;
    const pts = data.map((v, i) => `${(i / (data.length - 1)) * W},${H - ((v - min) / range) * H}`).join(" ");
    const lastX = W, lastY = H - ((data[data.length - 1] - min) / range) * H;
    return (
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="overflow-visible">
            <defs>
                <linearGradient id={`sg-${accent.replace('#','')}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={accent} stopOpacity="0.3" />
                    <stop offset="100%" stopColor={accent} stopOpacity="0" />
                </linearGradient>
            </defs>
            <polyline points={pts} fill="none" stroke={accent} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
            <circle cx={lastX} cy={lastY} r="3" fill={accent} />
        </svg>
    );
}

// ─── Insight Card ─────────────────────────────────────────────────────────────
function InsightCard({ insight, onAction, onAskInChat, onDrillDown }: {
    insight: Insight;
    onAction: (id: string, a: "pinned" | "dismissed") => void;
    onAskInChat: (i: Insight) => void;
    onDrillDown: (i: Insight) => void;
}) {
    const [expanded, setExpanded] = useState(false);
    const key = insight.detection_method ?? insight.insight_type ?? "default";
    const meta = DET[key] ?? DET.default;
    const Icon = meta.icon;
    const pri = PRI_CONFIG[insight.priority] ?? PRI_CONFIG.medium;
    const sig = insight.data_json?.signal ?? {} as SparklineSignal;
    const sparkline = sig.sparkline ?? [];
    const isDown = (insight.metric_change_pct ?? 0) < 0;
    const dimLabels = sig.dimension_filters
        ? Object.entries(sig.dimension_filters).map(([k, v]) => `${k}: ${v}`).join(" · ")
        : null;

    if (insight._dismissed) return null;

    return (
        <article className={`relative rounded-2xl border overflow-hidden transition-all duration-300 group
            ${insight._pinned
                ? "border-violet-500/50 bg-gradient-to-br from-[#1a1040]/80 to-[#0d0820]/80"
                : "border-white/10 bg-white/5 hover:bg-white/8 hover:border-white/18"}
            ${!insight.is_read ? "ring-1 ring-sky-500/25" : ""}`}>

            {/* Priority accent line */}
            <div className={`absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r ${meta.gradient}`} />
            {insight._pinned && <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-gradient-to-b from-violet-500 to-fuchsia-500" />}

            {/* Unread dot */}
            {!insight.is_read && (
                <span className="absolute top-4 right-4 w-2 h-2 rounded-full bg-sky-400 ring-2 ring-sky-400/30 z-10 animate-pulse" />
            )}

            <div className="p-5">
                {/* Header row */}
                <div className="flex items-start gap-3 mb-3">
                    <div className={`shrink-0 w-11 h-11 rounded-xl bg-gradient-to-br ${meta.gradient} flex items-center justify-center shadow-lg`}>
                        <Icon size={18} className="text-white" />
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap mb-1.5">
                            <span className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border ${pri.bg} ${pri.text} ${pri.border}`}>
                                <span className={`w-1 h-1 rounded-full ${pri.dot}`} />
                                {pri.label}
                            </span>
                            <span className="text-[10px] text-white/30 uppercase tracking-wider">{meta.label}</span>
                            {dimLabels && <span className="text-[10px] text-white/20 font-mono bg-white/5 px-1.5 py-0.5 rounded">{dimLabels}</span>}
                        </div>
                        <h3
                            className="text-sm font-semibold text-white/90 leading-snug pr-6 cursor-pointer hover:text-violet-300 transition-colors"
                            onClick={() => onDrillDown(insight)}
                            title="Click to drill down"
                        >{insight.title}</h3>
                    </div>
                    {sparkline.length > 1 && (
                        <div className="shrink-0 flex flex-col items-end gap-1">
                            <Sparkline data={sparkline} accent={meta.accent} />
                            {insight.metric_change_pct != null && (
                                <span className={`text-[11px] font-bold flex items-center gap-0.5 ${isDown ? "text-rose-400" : "text-emerald-400"}`}>
                                    {isDown ? <ArrowDownRight size={11} /> : <ArrowUpRight size={11} />}
                                    {insight.metric_change_pct > 0 ? "+" : ""}{insight.metric_change_pct.toFixed(1)}%
                                </span>
                            )}
                        </div>
                    )}
                </div>

                {/* Description */}
                <p className="text-[13px] text-white/60 leading-relaxed mb-3">{insight.description}</p>

                {/* Metrics chips */}
                {(insight.metric_value || sig.z_score != null || sig.gap_pct != null || sig.days_inactive != null) && (
                    <div className="flex flex-wrap gap-2 mb-3">
                        {insight.metric_value != null && insight.metric_value !== 0 && (
                            <span className="text-[11px] bg-white/6 border border-white/10 rounded-lg px-2.5 py-1 text-white/70">
                                Value: <span className="text-white font-semibold">{fmt(insight.metric_value)}</span>
                            </span>
                        )}
                        {insight.metric_change_pct != null && (
                            <span className={`text-[11px] border rounded-lg px-2.5 py-1 font-semibold ${isDown ? "bg-rose-500/10 border-rose-500/20 text-rose-300" : "bg-emerald-500/10 border-emerald-500/20 text-emerald-300"}`}>
                                {insight.metric_change_pct > 0 ? "+" : ""}{insight.metric_change_pct.toFixed(1)}% change
                            </span>
                        )}
                        {sig.z_score != null && (
                            <span className="text-[11px] bg-amber-500/10 border border-amber-500/20 rounded-lg px-2.5 py-1 text-amber-300">
                                Z-Score: {sig.z_score.toFixed(1)}σ
                            </span>
                        )}
                        {sig.gap_pct != null && (
                            <span className="text-[11px] bg-orange-500/10 border border-orange-500/20 rounded-lg px-2.5 py-1 text-orange-300">
                                Gap: {sig.gap_pct.toFixed(1)}%
                            </span>
                        )}
                        {sig.days_inactive != null && (
                            <span className="text-[11px] bg-slate-500/10 border border-slate-500/20 rounded-lg px-2.5 py-1 text-slate-300">
                                Inactive: {sig.days_inactive}d
                            </span>
                        )}
                        {insight.period_start && (
                            <span className="text-[11px] bg-white/5 border border-white/8 rounded-lg px-2.5 py-1 text-white/40 font-mono">
                                {insight.period_start} → {insight.period_end ?? "now"}
                            </span>
                        )}
                    </div>
                )}

                {/* Suggested Action - highlighted */}
                {insight.suggested_action && (
                    <div className="flex items-start gap-2.5 bg-gradient-to-r from-amber-500/12 to-orange-500/8 border border-amber-400/25 rounded-xl px-3.5 py-3 mb-3">
                        <Zap size={14} className="text-amber-400 mt-0.5 shrink-0" />
                        <p className="text-[12px] text-amber-200/85 leading-relaxed font-medium">{insight.suggested_action}</p>
                    </div>
                )}

                {/* Footer actions */}
                <div className="flex items-center justify-between pt-1">
                    <div className="flex items-center gap-1.5">
                        <button onClick={() => onDrillDown(insight)}
                            className="flex items-center gap-1.5 text-[11px] font-semibold text-white bg-gradient-to-r from-violet-600 to-fuchsia-600 hover:from-violet-500 hover:to-fuchsia-500 px-3 py-1.5 rounded-lg transition-all shadow-lg shadow-violet-500/20 hover:shadow-violet-500/30">
                            <ChevronRight size={12} /> Drill Down
                        </button>
                        <button onClick={() => onAskInChat(insight)}
                            className="flex items-center gap-1.5 text-[11px] font-semibold text-white bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 px-3 py-1.5 rounded-lg transition-all shadow-lg shadow-sky-500/20 hover:shadow-sky-500/30">
                            <MessageSquare size={12} /> Explore in Chat
                        </button>
                        <button onClick={() => onAction(insight.insight_id, "pinned")}
                            className={`p-1.5 rounded-lg transition-all ${insight._pinned ? "text-violet-400 bg-violet-500/20 border border-violet-500/30" : "text-white/25 hover:text-violet-400 hover:bg-violet-500/12"}`}>
                            {insight._pinned ? <BookmarkCheck size={14} /> : <Bookmark size={14} />}
                        </button>
                        <button onClick={() => onAction(insight.insight_id, "dismissed")}
                            className="p-1.5 rounded-lg text-white/20 hover:text-rose-400 hover:bg-rose-500/12 transition-all">
                            <ThumbsDown size={14} />
                        </button>
                        <button onClick={() => setExpanded(!expanded)}
                            className="p-1.5 rounded-lg text-white/20 hover:text-white/60 hover:bg-white/8 transition-all">
                            {expanded ? <EyeOff size={14} /> : <Eye size={14} />}
                        </button>
                    </div>
                    <span className="text-[10px] text-white/20 font-mono">{timeAgo(insight.created_at)}</span>
                </div>

                {/* Expanded detail */}
                {expanded && (
                    <div className="mt-3 pt-3 border-t border-white/8 space-y-3">
                        {/* Stats grid */}
                        {(sig.r_squared != null || sig.normalized_slope != null || sig.target != null) && (
                            <div className="grid grid-cols-3 gap-2">
                                {sig.r_squared != null && (
                                    <div className="bg-white/4 rounded-lg px-3 py-2 text-center">
                                        <p className="text-[10px] text-white/30 mb-0.5">R² Fit</p>
                                        <p className="text-sm font-bold text-white/80">{sig.r_squared.toFixed(2)}</p>
                                    </div>
                                )}
                                {sig.normalized_slope != null && (
                                    <div className="bg-white/4 rounded-lg px-3 py-2 text-center">
                                        <p className="text-[10px] text-white/30 mb-0.5">Slope /wk</p>
                                        <p className="text-sm font-bold text-white/80">{sig.normalized_slope.toFixed(1)}%</p>
                                    </div>
                                )}
                                {sig.target != null && (
                                    <div className="bg-white/4 rounded-lg px-3 py-2 text-center">
                                        <p className="text-[10px] text-white/30 mb-0.5">Target</p>
                                        <p className="text-sm font-bold text-white/80">{fmt(sig.target)}</p>
                                    </div>
                                )}
                            </div>
                        )}
                        {/* Suggested query preview */}
                        {insight.suggested_query && (
                            <div className="bg-sky-500/8 border border-sky-500/20 rounded-xl px-3.5 py-3">
                                <p className="text-[10px] text-sky-400/60 uppercase tracking-wider mb-1.5">Suggested Query</p>
                                <p className="text-[12px] text-sky-200/80 font-mono leading-relaxed">{insight.suggested_query}</p>
                                <button onClick={() => onAskInChat(insight)}
                                    className="mt-2 flex items-center gap-1.5 text-[11px] text-sky-400 hover:text-sky-300 transition-colors">
                                    <MessageSquare size={11} /> Run this query in Chat <ChevronRight size={11} />
                                </button>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </article>
    );
}

// ─── Page ─────────────────────────────────────────────────────────────────────
type FilterKey = "all" | "high" | "unread" | "pinned";
type SortKey = "priority" | "newest" | "change";

export default function InsightsPage() {
    const router = useRouter();
    const [insights, setInsights] = useState<Insight[]>([]);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [filter, setFilter] = useState<FilterKey>("all");
    const [sort, setSort] = useState<SortKey>("priority");
    const [generating, setGenerating] = useState(false);
    const [userRole, setUserRole] = useState<string>("admin");
    const [userName, setUserName] = useState<string>("");
    const [clientName, setClientName] = useState<string>("");

    useEffect(() => {
        if (!getAccessToken()) { router.push("/"); return; }
        getMe().then((d) => {
            setUserRole(d.user?.role ?? "admin");
            setUserName(d.user?.full_name ?? "");
            setClientName(d.user?.client_name ?? "");
        }).catch(() => {});
    }, [router]);

    const fetchInsights = useCallback(async () => {
        try {
            const d = await getInsights();
            setInsights((d.insights || []).map((i: Insight) => ({ ...i, _pinned: false, _dismissed: false })));
        } catch { setInsights([]); }
        finally { setLoading(false); setRefreshing(false); }
    }, []);

    useEffect(() => { fetchInsights(); }, [fetchInsights]);

    const refresh = () => { setRefreshing(true); fetchInsights(); };

    const handleGenerate = async () => {
        setGenerating(true);
        try { await triggerIntelRun(); await fetchInsights(); }
        catch (e) { console.error(e); }
        finally { setGenerating(false); }
    };

    const onAskInChat = (i: Insight) => {
        markInsightRead(i.insight_id).catch(() => null);
        postInsightFeedback(i.insight_id, "clicked_followup").catch(() => null);
        sessionStorage.setItem("suggested_query", i.suggested_query || i.title);
        router.push("/");
    };

    const onNudge = (query: string) => {
        sessionStorage.setItem("suggested_query", query);
        router.push("/");
    };

    const onDrillDown = (i: Insight) => {
        markInsightRead(i.insight_id).catch(() => null);
        const params = new URLSearchParams({
            title: i.title,
            type: i.detection_method ?? i.insight_type ?? "general",
            body: i.description,
            id: i.insight_id,
            priority: i.priority,
            ...(i.suggested_query ? { query: i.suggested_query } : {}),
        });
        router.push(`/insights/${i.insight_id}?${params.toString()}`);
    };

    const onAction = (id: string, action: "pinned" | "dismissed") => {
        postInsightFeedback(id, action).catch(() => null);
        setInsights(p => p.map(i => i.insight_id !== id ? i : action === "pinned" ? { ...i, _pinned: !i._pinned } : { ...i, _dismissed: true }));
    };

    const markAllRead = () => {
        insights.filter(i => !i.is_read).forEach(i => markInsightRead(i.insight_id).catch(() => null));
        setInsights(p => p.map(i => ({ ...i, is_read: true })));
    };

    const PRIO = { critical: 0, high: 1, medium: 2, low: 3 } as Record<string, number>;
    const visible = insights
        .filter(i => {
            if (i._dismissed) return false;
            if (filter === "unread") return !i.is_read;
            if (filter === "high") return i.priority === "high" || i.priority === "critical";
            if (filter === "pinned") return i._pinned;
            return true;
        })
        .sort((a, b) => {
            if (sort === "priority") return (PRIO[a.priority] ?? 4) - (PRIO[b.priority] ?? 4);
            if (sort === "change") return Math.abs(b.metric_change_pct ?? 0) - Math.abs(a.metric_change_pct ?? 0);
            return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
        });

    const pinned = visible.filter(i => i._pinned);
    const rest = visible.filter(i => !i._pinned);
    const unreadCount = insights.filter(i => !i.is_read && !i._dismissed).length;
    const criticalCount = insights.filter(i => i.priority === "critical" && !i._dismissed).length;
    const nudges = ROLE_NUDGES[userRole] ?? ROLE_NUDGES.admin;

    const FILTERS: { key: FilterKey; label: string; count?: number }[] = [
        { key: "all", label: "All", count: insights.filter(i => !i._dismissed).length },
        { key: "unread", label: "Unread", count: unreadCount },
        { key: "high", label: "High Priority", count: insights.filter(i => (i.priority === "high" || i.priority === "critical") && !i._dismissed).length },
        { key: "pinned", label: "Pinned", count: insights.filter(i => i._pinned).length },
    ];

    return (
        <div className="min-h-screen text-white" style={{
            background: "linear-gradient(135deg, #080b18 0%, #0d1028 40%, #100c22 70%, #080b18 100%)",
            fontFamily: '"Courier New", Courier, monospace'
        }}>
            {/* Ambient blobs */}
            <div className="fixed inset-0 overflow-hidden pointer-events-none">
                <div className="absolute top-0 right-1/3 w-80 h-80 bg-violet-600/12 rounded-full blur-3xl" />
                <div className="absolute bottom-1/3 left-1/4 w-64 h-64 bg-indigo-600/10 rounded-full blur-3xl" />
                {criticalCount > 0 && <div className="absolute top-1/3 right-0 w-48 h-48 bg-rose-600/8 rounded-full blur-3xl" />}
            </div>

            {/* Header */}
            <header className="sticky top-0 z-20 border-b border-white/8 backdrop-blur-xl bg-black/40">
                <div className="max-w-5xl mx-auto px-5 py-3.5 flex items-center justify-between gap-4">
                    <div className="flex items-center gap-3">
                        <button onClick={() => router.push("/")}
                            className="p-1.5 text-white/40 hover:text-white hover:bg-white/8 rounded-lg transition-all group">
                            <ArrowLeft size={17} className="group-hover:-translate-x-0.5 transition-transform" />
                        </button>
                        <div className="w-px h-5 bg-white/10" />
                        <div className="flex items-center gap-2.5">
                            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-600 flex items-center justify-center shadow-lg shadow-violet-500/30">
                                <Sparkles size={16} className="text-white" />
                            </div>
                            <div>
                                <h1 className="text-sm font-bold text-white/90">Intel Insights</h1>
                                <p className="text-[10px] text-white/35">{clientName || "Proactive alerts from your data"}</p>
                            </div>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        {unreadCount > 0 && (
                            <span className="flex items-center gap-1.5 bg-sky-500/15 border border-sky-500/30 text-sky-300 text-[11px] font-bold px-2.5 py-1 rounded-full animate-pulse">
                                <Bell size={10} /> {unreadCount} new
                            </span>
                        )}
                        {criticalCount > 0 && (
                            <span className="flex items-center gap-1.5 bg-rose-500/15 border border-rose-500/30 text-rose-300 text-[11px] font-bold px-2.5 py-1 rounded-full">
                                <Flame size={10} /> {criticalCount} critical
                            </span>
                        )}
                        <button onClick={handleGenerate} disabled={generating || loading}
                            className="flex items-center gap-1.5 text-[11px] font-semibold text-white bg-gradient-to-r from-violet-600 to-fuchsia-600 hover:from-violet-500 hover:to-fuchsia-500 px-3.5 py-1.5 rounded-lg transition-all shadow-lg shadow-violet-500/25 disabled:opacity-40">
                            <Zap size={12} className={generating ? "animate-pulse" : ""} />
                            {generating ? "Generating..." : "Generate"}
                        </button>
                        <button onClick={refresh} disabled={refreshing || generating}
                            className="flex items-center gap-1.5 text-[11px] text-white/50 hover:text-white bg-white/5 hover:bg-white/10 border border-white/10 px-3 py-1.5 rounded-lg transition-all disabled:opacity-40">
                            <RefreshCw size={12} className={refreshing ? "animate-spin" : ""} />
                        </button>
                    </div>
                </div>
            </header>

            <main className="relative z-10 max-w-5xl w-full mx-auto px-5 py-6 space-y-6">

                {/* Role-based Nudges */}
                <div className="rounded-2xl border border-white/10 bg-white/4 backdrop-blur-sm overflow-hidden">
                    <div className="px-5 py-3.5 border-b border-white/8 flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <Shield size={14} className="text-violet-400" />
                            <span className="text-xs font-bold text-white/60 uppercase tracking-widest">
                                {userName ? `${userName}'s` : "Your"} Action Items
                            </span>
                            <span className="text-[10px] bg-violet-500/20 border border-violet-500/30 text-violet-300 px-2 py-0.5 rounded-full uppercase">{userRole}</span>
                        </div>
                        <span className="text-[10px] text-white/25">Click any to query instantly</span>
                    </div>
                    <div className="p-4 grid grid-cols-2 sm:grid-cols-3 gap-2.5">
                        {nudges.map((n) => {
                            const Icon = n.icon;
                            return (
                                <button key={n.label} onClick={() => onNudge(n.query)}
                                    className={`group flex items-center gap-2.5 ${n.bg} border ${n.border} rounded-xl px-3.5 py-2.5 hover:brightness-125 transition-all cursor-pointer text-left`}>
                                    <Icon size={15} className={`${n.color} shrink-0`} />
                                    <span className={`text-[12px] font-semibold ${n.color} leading-tight`}>{n.label}</span>
                                    <ChevronRight size={11} className="ml-auto text-white/15 group-hover:text-white/40 group-hover:translate-x-0.5 transition-all" />
                                </button>
                            );
                        })}
                    </div>
                </div>

                {/* Stats bar */}
                <div className="grid grid-cols-4 gap-3">
                    {[
                        { label: "Total", value: insights.filter(i => !i._dismissed).length, color: "text-white/80", bg: "from-white/8 to-white/4", border: "border-white/10" },
                        { label: "Unread", value: unreadCount, color: "text-sky-400", bg: "from-sky-500/15 to-sky-500/5", border: "border-sky-500/20" },
                        { label: "Critical", value: criticalCount, color: "text-rose-400", bg: "from-rose-500/15 to-rose-500/5", border: "border-rose-500/20" },
                        { label: "High", value: insights.filter(i => i.priority === "high" && !i._dismissed).length, color: "text-amber-400", bg: "from-amber-500/15 to-amber-500/5", border: "border-amber-500/20" },
                    ].map(({ label, value, color, bg, border }) => (
                        <div key={label} className={`bg-gradient-to-br ${bg} border ${border} rounded-xl px-4 py-3 text-center backdrop-blur-sm`}>
                            <p className={`text-2xl font-bold ${color}`}>{value}</p>
                            <p className="text-[11px] text-white/30 mt-0.5 uppercase tracking-wider">{label}</p>
                        </div>
                    ))}
                </div>

                {/* Controls */}
                <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-1 bg-white/5 border border-white/10 rounded-xl p-1">
                        <Filter size={11} className="text-white/25 ml-1.5" />
                        {FILTERS.map(({ key, label, count }) => (
                            <button key={key} onClick={() => setFilter(key)}
                                className={`text-[11px] px-3 py-1.5 rounded-lg transition-all font-semibold flex items-center gap-1.5
                                    ${filter === key ? "bg-gradient-to-r from-violet-500/30 to-fuchsia-500/20 text-violet-300 border border-violet-500/30" : "text-white/35 hover:text-white/65"}`}>
                                {label}
                                {count !== undefined && count > 0 && (
                                    <span className={`text-[9px] px-1 rounded-full ${filter === key ? "bg-violet-400/30 text-violet-200" : "bg-white/10 text-white/30"}`}>{count}</span>
                                )}
                            </button>
                        ))}
                    </div>
                    <div className="flex items-center gap-1 bg-white/5 border border-white/10 rounded-xl p-1">
                        <Layers size={11} className="text-white/25 ml-1.5" />
                        {(["priority", "newest", "change"] as SortKey[]).map(s => (
                            <button key={s} onClick={() => setSort(s)}
                                className={`text-[11px] px-3 py-1.5 rounded-lg transition-all capitalize font-semibold
                                    ${sort === s ? "bg-white/12 text-white/85" : "text-white/35 hover:text-white/60"}`}>
                                {s}
                            </button>
                        ))}
                    </div>
                </div>

                {unreadCount > 0 && (
                    <button onClick={markAllRead}
                        className="flex items-center gap-1.5 text-[11px] text-white/35 hover:text-sky-400 transition-colors">
                        <CheckCheck size={13} /> Mark all as read
                    </button>
                )}

                {/* Insight Cards */}
                {loading ? (
                    <div className="flex flex-col items-center justify-center h-60 gap-4">
                        <div className="w-10 h-10 border-2 border-violet-500/40 border-t-violet-400 rounded-full animate-spin" />
                        <p className="text-xs text-white/30">Loading intelligence…</p>
                    </div>
                ) : visible.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-52 gap-3">
                        <div className="w-16 h-16 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center">
                            <Lightbulb size={26} className="text-white/15" />
                        </div>
                        <p className="text-sm text-white/30">No insights for this filter.</p>
                        <button onClick={handleGenerate} disabled={generating}
                            className="text-[11px] text-violet-400 hover:text-violet-300 flex items-center gap-1 mt-1 transition-colors">
                            <Zap size={11} /> Generate new insights
                        </button>
                    </div>
                ) : (
                    <div className="grid gap-3">
                        {pinned.length > 0 && (
                            <p className="text-[10px] text-violet-400/70 uppercase tracking-widest font-bold flex items-center gap-1.5">
                                <BookmarkCheck size={11} /> Pinned
                            </p>
                        )}
                        {pinned.map(i => <InsightCard key={i.insight_id} insight={i} onAction={onAction} onAskInChat={onAskInChat} onDrillDown={onDrillDown} />)}
                        {pinned.length > 0 && rest.length > 0 && (
                            <p className="text-[10px] text-white/20 uppercase tracking-widest font-bold mt-1 flex items-center gap-1.5">
                                <Activity size={11} /> Active
                            </p>
                        )}
                        {rest.map(i => <InsightCard key={i.insight_id} insight={i} onAction={onAction} onAskInChat={onAskInChat} onDrillDown={onDrillDown} />)}
                    </div>
                )}

                <div className="flex items-center justify-between text-[11px] text-white/18 pt-2 border-t border-white/5">
                    <span>{visible.length} insight{visible.length !== 1 ? "s" : ""} shown</span>
                    {insights[0]?.created_at && <span>Last updated {timeAgo(insights[0].created_at)}</span>}
                </div>
            </main>
        </div>
    );
}
