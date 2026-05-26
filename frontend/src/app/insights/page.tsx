"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
    ArrowLeft, TrendingDown, TrendingUp, AlertTriangle, Activity,
    Clock, Zap, Bookmark, BookmarkCheck, ThumbsDown, MessageSquare,
    RefreshCw, Sparkles, Bell, Filter, Layers, CheckCheck, BarChart2,
    Target, Flame, Shield, Users, Package, Map, ArrowUpRight,
    ArrowDownRight, ChevronRight, Star, Eye, EyeOff, Lightbulb,
} from "lucide-react";
import { getInsights, markInsightRead, postInsightFeedback, triggerIntelRun, getAccessToken, getMe } from "@/services/api";

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

const ROLE_NUDGES: Record<string, { label: string; query: string; icon: any; iconBg: string; iconColor: string }[]> = {
    admin: [
        { label: "Full P&L by Zone",    query: "Show net sales and gross margin by zone this month",           icon: BarChart2,    iconBg: "bg-indigo-50",  iconColor: "text-indigo-600" },
        { label: "Bottom 5 SKUs",       query: "Which 5 SKUs had lowest sales last 30 days",                   icon: TrendingDown, iconBg: "bg-rose-50",    iconColor: "text-rose-500"   },
        { label: "Target Gap Analysis", query: "Show zones below sales target this month with gap percentage",  icon: Target,       iconBg: "bg-amber-50",   iconColor: "text-amber-600"  },
        { label: "Distributor Review",  query: "Top 10 distributors by secondary sales last 30 days",          icon: Users,        iconBg: "bg-sky-50",     iconColor: "text-sky-600"    },
        { label: "Brand Performance",   query: "Net sales by brand for current month vs last month",           icon: Star,         iconBg: "bg-emerald-50", iconColor: "text-emerald-600"},
        { label: "Inactive Outlets",    query: "Show retailers with zero purchases in last 14 days",           icon: Clock,        iconBg: "bg-orange-50",  iconColor: "text-orange-500" },
    ],
    analytics: [
        { label: "Zone Heatmap",      query: "Show net sales by zone for last 30 days",           icon: Map,       iconBg: "bg-indigo-50",  iconColor: "text-indigo-600" },
        { label: "Category Split",    query: "Sales breakdown by product category this month",    icon: Layers,    iconBg: "bg-sky-50",     iconColor: "text-sky-600"    },
        { label: "Monthly Trend",     query: "Show monthly sales trend for last 6 months",        icon: TrendingUp,iconBg: "bg-emerald-50", iconColor: "text-emerald-600"},
        { label: "Pack Size Analysis",query: "Sales volume by pack size this quarter",            icon: Package,   iconBg: "bg-amber-50",   iconColor: "text-amber-600"  },
    ],
    asm: [
        { label: "My Territory Sales", query: "Show net sales for my ASM territory last 30 days",      icon: Map,       iconBg: "bg-indigo-50",  iconColor: "text-indigo-600"},
        { label: "SO Performance",     query: "Top performing sales officers in my territory",          icon: Users,     iconBg: "bg-sky-50",     iconColor: "text-sky-600"   },
        { label: "Beat Efficiency",    query: "Which routes have lowest coverage in my area",           icon: Activity,  iconBg: "bg-rose-50",    iconColor: "text-rose-500"  },
        { label: "Strike Rate",        query: "Productive calls vs total calls by salesrep this week", icon: Target,    iconBg: "bg-amber-50",   iconColor: "text-amber-600" },
    ],
    salesrep: [
        { label: "My Route Sales",    query: "Show my sales for this month",                               icon: TrendingUp,    iconBg: "bg-emerald-50", iconColor: "text-emerald-600"},
        { label: "Inactive Retailers",query: "Which retailers on my route haven't purchased in 7 days",   icon: AlertTriangle, iconBg: "bg-rose-50",    iconColor: "text-rose-500"  },
        { label: "Top SKUs",          query: "Top selling products on my route this month",               icon: Package,       iconBg: "bg-amber-50",   iconColor: "text-amber-600" },
    ],
};

const DET: Record<string, { icon: any; iconBg: string; iconColor: string; label: string; borderColor: string }> = {
    anomaly:    { icon: AlertTriangle, iconBg: "bg-amber-50",   iconColor: "text-amber-600",  label: "Anomaly",    borderColor: "border-l-amber-400"  },
    trend:      { icon: TrendingDown,  iconBg: "bg-rose-50",    iconColor: "text-rose-500",   label: "Trend",      borderColor: "border-l-rose-400"   },
    target_gap: { icon: Target,        iconBg: "bg-orange-50",  iconColor: "text-orange-500", label: "Target Gap", borderColor: "border-l-orange-400" },
    inactivity: { icon: Clock,         iconBg: "bg-gray-100",   iconColor: "text-gray-500",   label: "Inactivity", borderColor: "border-l-gray-400"   },
    default:    { icon: Sparkles,      iconBg: "bg-indigo-50",  iconColor: "text-indigo-600", label: "Insight",    borderColor: "border-l-indigo-400" },
};

const PRI_CONFIG: Record<string, { label: string; bg: string; text: string; border: string; dot: string }> = {
    critical: { label: "CRITICAL", bg: "bg-rose-50",   text: "text-rose-600",   border: "border-rose-200",   dot: "bg-rose-500"   },
    high:     { label: "HIGH",     bg: "bg-amber-50",  text: "text-amber-700",  border: "border-amber-200",  dot: "bg-amber-500"  },
    medium:   { label: "MEDIUM",   bg: "bg-sky-50",    text: "text-sky-700",    border: "border-sky-200",    dot: "bg-sky-500"    },
    low:      { label: "LOW",      bg: "bg-gray-100",  text: "text-gray-500",   border: "border-gray-200",   dot: "bg-gray-400"   },
};

const fmt = (n: number) =>
    n >= 1_000_000 ? `₹${(n / 1_000_000).toFixed(1)}M`
    : n >= 1_000   ? `₹${(n / 1_000).toFixed(0)}K`
    : `₹${n.toFixed(0)}`;

const timeAgo = (s: string) => {
    const m = Math.floor((Date.now() - new Date(s).getTime()) / 60000);
    return m < 60 ? `${m}m ago` : m < 1440 ? `${Math.floor(m / 60)}h ago` : `${Math.floor(m / 1440)}d ago`;
};

function Sparkline({ data, positive }: { data: number[]; positive: boolean }) {
    if (data.length < 2) return null;
    const max = Math.max(...data), min = Math.min(...data), range = max - min || 1;
    const W = 90, H = 32;
    const pts = data.map((v, i) => `${(i / (data.length - 1)) * W},${H - ((v - min) / range) * H}`).join(" ");
    const lastX = W, lastY = H - ((data[data.length - 1] - min) / range) * H;
    return (
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="overflow-visible">
            <polyline points={pts} fill="none" stroke={positive ? "#10b981" : "#f43f5e"} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
            <circle cx={lastX} cy={lastY} r="2.5" fill={positive ? "#10b981" : "#f43f5e"} />
        </svg>
    );
}

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
        <article className={`card overflow-hidden border-l-4 ${meta.borderColor} transition-all duration-200
            ${insight._pinned ? "ring-2 ring-indigo-200 ring-offset-1" : ""}
            ${!insight.is_read ? "bg-blue-50/30" : ""}
        `}>
            {!insight.is_read && (
                <div className="absolute top-4 right-4 w-2 h-2 rounded-full bg-sky-500 ring-2 ring-sky-200" />
            )}
            <div className="p-5 relative">
                <div className="flex items-start gap-3 mb-3">
                    <div className={`shrink-0 w-10 h-10 rounded-xl ${meta.iconBg} flex items-center justify-center`}>
                        <Icon size={17} className={meta.iconColor} />
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap mb-1.5">
                            <span className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border ${pri.bg} ${pri.text} ${pri.border}`}>
                                <span className={`w-1.5 h-1.5 rounded-full ${pri.dot}`} />
                                {pri.label}
                            </span>
                            <span className="text-[10px] text-gray-400 uppercase tracking-wider">{meta.label}</span>
                            {dimLabels && <span className="text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded font-mono">{dimLabels}</span>}
                        </div>
                        <h3 className="text-sm font-semibold text-gray-900 leading-snug cursor-pointer hover:text-indigo-600 transition-colors"
                            onClick={() => onDrillDown(insight)}>{insight.title}</h3>
                    </div>
                    {sparkline.length > 1 && (
                        <div className="shrink-0 flex flex-col items-end gap-1">
                            <Sparkline data={sparkline} positive={!isDown} />
                            {insight.metric_change_pct != null && (
                                <span className={`text-[11px] font-bold flex items-center gap-0.5 ${isDown ? "text-rose-600" : "text-emerald-600"}`}>
                                    {isDown ? <ArrowDownRight size={11} /> : <ArrowUpRight size={11} />}
                                    {insight.metric_change_pct > 0 ? "+" : ""}{insight.metric_change_pct.toFixed(1)}%
                                </span>
                            )}
                        </div>
                    )}
                </div>

                <p className="text-sm text-gray-600 leading-relaxed mb-3">{insight.description}</p>

                {(insight.metric_value || sig.z_score != null || sig.gap_pct != null || sig.days_inactive != null) && (
                    <div className="flex flex-wrap gap-2 mb-3">
                        {insight.metric_value != null && insight.metric_value !== 0 && (
                            <span className="text-xs bg-gray-100 border border-gray-200 rounded-lg px-2.5 py-1 text-gray-600">
                                Value: <span className="text-gray-900 font-semibold">{fmt(insight.metric_value)}</span>
                            </span>
                        )}
                        {insight.metric_change_pct != null && (
                            <span className={`text-xs border rounded-lg px-2.5 py-1 font-semibold ${isDown ? "bg-rose-50 border-rose-200 text-rose-600" : "bg-emerald-50 border-emerald-200 text-emerald-600"}`}>
                                {insight.metric_change_pct > 0 ? "+" : ""}{insight.metric_change_pct.toFixed(1)}% change
                            </span>
                        )}
                        {sig.z_score != null && (
                            <span className="text-xs bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1 text-amber-700">Z: {sig.z_score.toFixed(1)}σ</span>
                        )}
                        {sig.gap_pct != null && (
                            <span className="text-xs bg-orange-50 border border-orange-200 rounded-lg px-2.5 py-1 text-orange-700">Gap: {sig.gap_pct.toFixed(1)}%</span>
                        )}
                        {sig.days_inactive != null && (
                            <span className="text-xs bg-gray-100 border border-gray-200 rounded-lg px-2.5 py-1 text-gray-600">Inactive: {sig.days_inactive}d</span>
                        )}
                        {insight.period_start && (
                            <span className="text-xs bg-gray-50 border border-gray-200 rounded-lg px-2.5 py-1 text-gray-400 font-mono">
                                {insight.period_start} → {insight.period_end ?? "now"}
                            </span>
                        )}
                    </div>
                )}

                {insight.suggested_action && (
                    <div className="flex items-start gap-2.5 bg-amber-50 border border-amber-200 rounded-xl px-3.5 py-3 mb-3">
                        <Zap size={13} className="text-amber-500 mt-0.5 shrink-0" />
                        <p className="text-xs text-amber-800 leading-relaxed font-medium">{insight.suggested_action}</p>
                    </div>
                )}

                <div className="flex items-center justify-between pt-1">
                    <div className="flex items-center gap-1.5">
                        <button onClick={() => onDrillDown(insight)}
                            className="btn-indigo flex items-center gap-1.5 text-xs py-1.5 px-3">
                            <ChevronRight size={12} /> Drill Down
                        </button>
                        <button onClick={() => onAskInChat(insight)}
                            className="flex items-center gap-1.5 text-xs font-semibold text-sky-600 bg-sky-50 hover:bg-sky-100 border border-sky-200 px-3 py-1.5 rounded-lg transition-colors">
                            <MessageSquare size={12} /> Explore
                        </button>
                        <button onClick={() => onAction(insight.insight_id, "pinned")}
                            className={`p-1.5 rounded-lg transition-all ${insight._pinned ? "text-indigo-600 bg-indigo-50 border border-indigo-200" : "text-gray-400 hover:text-indigo-600 hover:bg-indigo-50"}`}>
                            {insight._pinned ? <BookmarkCheck size={14} /> : <Bookmark size={14} />}
                        </button>
                        <button onClick={() => onAction(insight.insight_id, "dismissed")}
                            className="p-1.5 rounded-lg text-gray-300 hover:text-rose-500 hover:bg-rose-50 transition-all">
                            <ThumbsDown size={14} />
                        </button>
                        <button onClick={() => setExpanded(!expanded)}
                            className="p-1.5 rounded-lg text-gray-300 hover:text-gray-600 hover:bg-gray-100 transition-all">
                            {expanded ? <EyeOff size={14} /> : <Eye size={14} />}
                        </button>
                    </div>
                    <span className="text-[10px] text-gray-400">{timeAgo(insight.created_at)}</span>
                </div>

                {expanded && (
                    <div className="mt-4 pt-4 border-t border-gray-100 space-y-3">
                        {(sig.r_squared != null || sig.normalized_slope != null || sig.target != null) && (
                            <div className="grid grid-cols-3 gap-2">
                                {sig.r_squared != null && (
                                    <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-center">
                                        <p className="text-[10px] text-gray-400 mb-0.5">R² Fit</p>
                                        <p className="text-sm font-bold text-gray-800">{sig.r_squared.toFixed(2)}</p>
                                    </div>
                                )}
                                {sig.normalized_slope != null && (
                                    <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-center">
                                        <p className="text-[10px] text-gray-400 mb-0.5">Slope /wk</p>
                                        <p className="text-sm font-bold text-gray-800">{sig.normalized_slope.toFixed(1)}%</p>
                                    </div>
                                )}
                                {sig.target != null && (
                                    <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-center">
                                        <p className="text-[10px] text-gray-400 mb-0.5">Target</p>
                                        <p className="text-sm font-bold text-gray-800">{fmt(sig.target)}</p>
                                    </div>
                                )}
                            </div>
                        )}
                        {insight.suggested_query && (
                            <div className="bg-sky-50 border border-sky-200 rounded-xl px-3.5 py-3">
                                <p className="text-[10px] text-sky-500 uppercase tracking-wider mb-1.5 font-semibold">Suggested Query</p>
                                <p className="text-xs text-sky-800 font-mono leading-relaxed">{insight.suggested_query}</p>
                                <button onClick={() => onAskInChat(insight)}
                                    className="mt-2 flex items-center gap-1.5 text-xs text-sky-600 hover:text-sky-800 transition-colors font-medium">
                                    <MessageSquare size={11} /> Run in Chat <ChevronRight size={11} />
                                </button>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </article>
    );
}

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

    const onNudge = (query: string) => { sessionStorage.setItem("suggested_query", query); router.push("/"); };

    const onDrillDown = (i: Insight) => {
        markInsightRead(i.insight_id).catch(() => null);
        const params = new URLSearchParams({
            title: i.title, type: i.detection_method ?? i.insight_type ?? "general",
            body: i.description, id: i.insight_id, priority: i.priority,
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
        { key: "all",    label: "All",           count: insights.filter(i => !i._dismissed).length },
        { key: "unread", label: "Unread",         count: unreadCount },
        { key: "high",   label: "High Priority",  count: insights.filter(i => (i.priority === "high" || i.priority === "critical") && !i._dismissed).length },
        { key: "pinned", label: "Pinned",          count: insights.filter(i => i._pinned).length },
    ];

    return (
        <div className="min-h-screen" style={{ backgroundColor: "#0F2044", backgroundImage: "radial-gradient(circle, rgba(255,255,255,0.06) 1px, transparent 1px)", backgroundSize: "28px 28px" }}>

            {/* Header */}
            <header className="bg-white border-b border-gray-200 sticky top-0 z-20">
                <div className="max-w-5xl mx-auto px-5 py-4 flex items-center justify-between gap-4">
                    <div className="flex items-center gap-3">
                        <button onClick={() => router.push("/")} className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-all">
                            <ArrowLeft size={17} />
                        </button>
                        <div className="w-px h-5 bg-gray-200" />
                        <div className="flex items-center gap-2.5">
                            <div className="w-9 h-9 rounded-xl gradient-mesh flex items-center justify-center">
                                <Sparkles size={15} className="text-white" />
                            </div>
                            <div>
                                <h1 className="text-sm font-bold text-gray-900">Intel Insights</h1>
                                <p className="text-[10px] text-gray-400">{clientName || "Proactive alerts from your data"}</p>
                            </div>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        {unreadCount > 0 && (
                            <span className="flex items-center gap-1.5 bg-sky-50 border border-sky-200 text-sky-600 text-xs font-bold px-2.5 py-1 rounded-full">
                                <Bell size={10} /> {unreadCount} new
                            </span>
                        )}
                        {criticalCount > 0 && (
                            <span className="flex items-center gap-1.5 bg-rose-50 border border-rose-200 text-rose-600 text-xs font-bold px-2.5 py-1 rounded-full">
                                <Flame size={10} /> {criticalCount} critical
                            </span>
                        )}
                        <button onClick={handleGenerate} disabled={generating || loading} className="btn-primary flex items-center gap-1.5 text-xs py-2 px-3 disabled:opacity-40 disabled:transform-none disabled:shadow-none">
                            <Zap size={12} className={generating ? "animate-pulse" : ""} />
                            {generating ? "Generating..." : "Generate"}
                        </button>
                        <button onClick={refresh} disabled={refreshing || generating}
                            className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 border border-gray-200 rounded-lg transition-all disabled:opacity-40">
                            <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
                        </button>
                    </div>
                </div>
            </header>

            <main className="max-w-5xl w-full mx-auto px-5 py-6 space-y-6">

                {/* Stats row */}
                <div className="grid grid-cols-4 gap-3">
                    {[
                        { label: "Total",    value: insights.filter(i => !i._dismissed).length,                                        color: "text-gray-900",   bg: "bg-white",       border: "border-gray-200" },
                        { label: "Unread",   value: unreadCount,                                                                        color: "text-sky-600",    bg: "bg-sky-50",      border: "border-sky-200"  },
                        { label: "Critical", value: criticalCount,                                                                      color: "text-rose-600",   bg: "bg-rose-50",     border: "border-rose-200" },
                        { label: "High",     value: insights.filter(i => i.priority === "high" && !i._dismissed).length,               color: "text-amber-700",  bg: "bg-amber-50",    border: "border-amber-200"},
                    ].map(({ label, value, color, bg, border }) => (
                        <div key={label} className={`${bg} border ${border} rounded-xl px-4 py-3 text-center`}>
                            <p className={`text-2xl font-bold ${color}`}>{value}</p>
                            <p className="text-[11px] text-gray-400 mt-0.5 uppercase tracking-wider">{label}</p>
                        </div>
                    ))}
                </div>

                {/* Role nudges */}
                <div className="card overflow-hidden">
                    <div className="px-5 py-3.5 border-b border-gray-100 flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <Shield size={14} className="text-indigo-500" />
                            <span className="text-xs font-bold text-gray-600 uppercase tracking-widest">
                                {userName ? `${userName}'s` : "Your"} Action Items
                            </span>
                            <span className="text-[10px] bg-indigo-50 border border-indigo-200 text-indigo-600 px-2 py-0.5 rounded-full uppercase font-semibold">{userRole}</span>
                        </div>
                        <span className="text-[10px] text-gray-400">Click any to query instantly</span>
                    </div>
                    <div className="p-4 grid grid-cols-2 sm:grid-cols-3 gap-2.5">
                        {nudges.map((n) => {
                            const Icon = n.icon;
                            return (
                                <button key={n.label} onClick={() => onNudge(n.query)}
                                    className="group flex items-center gap-2.5 bg-gray-50 hover:bg-gray-100 border border-gray-200 rounded-xl px-3.5 py-2.5 transition-colors text-left">
                                    <div className={`w-7 h-7 rounded-lg ${n.iconBg} flex items-center justify-center shrink-0`}>
                                        <Icon size={14} className={n.iconColor} />
                                    </div>
                                    <span className="text-xs font-semibold text-gray-700 leading-tight">{n.label}</span>
                                    <ChevronRight size={11} className="ml-auto text-gray-300 group-hover:text-orange-400 transition-colors" />
                                </button>
                            );
                        })}
                    </div>
                </div>

                {/* Controls */}
                <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-1 bg-white border border-gray-200 rounded-xl p-1">
                        <Filter size={11} className="text-gray-400 ml-1.5" />
                        {FILTERS.map(({ key, label, count }) => (
                            <button key={key} onClick={() => setFilter(key)}
                                className={`text-xs px-3 py-1.5 rounded-lg transition-all font-semibold flex items-center gap-1.5
                                    ${filter === key ? "bg-indigo-600 text-white shadow-sm" : "text-gray-500 hover:text-gray-800 hover:bg-gray-100"}`}>
                                {label}
                                {count !== undefined && count > 0 && (
                                    <span className={`text-[9px] px-1.5 py-0.5 rounded-full ${filter === key ? "bg-white/20 text-white" : "bg-gray-200 text-gray-500"}`}>{count}</span>
                                )}
                            </button>
                        ))}
                    </div>
                    <div className="flex items-center gap-1 bg-white border border-gray-200 rounded-xl p-1">
                        <Layers size={11} className="text-gray-400 ml-1.5" />
                        {(["priority", "newest", "change"] as SortKey[]).map(s => (
                            <button key={s} onClick={() => setSort(s)}
                                className={`text-xs px-3 py-1.5 rounded-lg transition-all capitalize font-semibold
                                    ${sort === s ? "bg-gray-900 text-white shadow-sm" : "text-gray-500 hover:text-gray-800 hover:bg-gray-100"}`}>
                                {s}
                            </button>
                        ))}
                    </div>
                </div>

                {unreadCount > 0 && (
                    <button onClick={markAllRead} className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-sky-400 transition-colors font-medium">
                        <CheckCheck size={13} /> Mark all as read
                    </button>
                )}

                {/* Cards */}
                {loading ? (
                    <div className="flex flex-col items-center justify-center h-60 gap-4">
                        <div className="w-10 h-10 border-2 border-indigo-200 border-t-indigo-600 rounded-full animate-spin" />
                        <p className="text-sm text-slate-300">Loading intelligence…</p>
                    </div>
                ) : visible.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-52 gap-3">
                        <div className="w-16 h-16 rounded-2xl flex items-center justify-center" style={{ backgroundColor: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.12)" }}>
                            <Lightbulb size={26} className="text-slate-400" />
                        </div>
                        <p className="text-sm text-slate-300">No insights for this filter.</p>
                        <button onClick={handleGenerate} disabled={generating}
                            className="text-xs text-orange-500 hover:text-orange-600 flex items-center gap-1 font-medium transition-colors">
                            <Zap size={11} /> Generate new insights
                        </button>
                    </div>
                ) : (
                    <div className="grid gap-3">
                        {pinned.length > 0 && (
                            <p className="text-[10px] text-indigo-600 uppercase tracking-widest font-bold flex items-center gap-1.5">
                                <BookmarkCheck size={11} /> Pinned
                            </p>
                        )}
                        {pinned.map(i => <InsightCard key={i.insight_id} insight={i} onAction={onAction} onAskInChat={onAskInChat} onDrillDown={onDrillDown} />)}
                        {pinned.length > 0 && rest.length > 0 && (
                            <p className="text-[10px] text-slate-400 uppercase tracking-widest font-bold mt-1 flex items-center gap-1.5">
                                <Activity size={11} /> Active
                            </p>
                        )}
                        {rest.map(i => <InsightCard key={i.insight_id} insight={i} onAction={onAction} onAskInChat={onAskInChat} onDrillDown={onDrillDown} />)}
                    </div>
                )}

                <div className="flex items-center justify-between text-[11px] text-slate-400 pt-2 border-t border-white/10">
                    <span>{visible.length} insight{visible.length !== 1 ? "s" : ""} shown</span>
                    {insights[0]?.created_at && <span>Last updated {timeAgo(insights[0].created_at)}</span>}
                </div>
            </main>
        </div>
    );
}
