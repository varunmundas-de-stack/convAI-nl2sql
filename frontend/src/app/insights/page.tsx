"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
    ArrowLeft, TrendingDown, TrendingUp, AlertTriangle, Activity,
    Clock, Zap, Bookmark, BookmarkCheck, ThumbsDown, MessageSquare,
    RefreshCw, ChevronRight, Sparkles, Bell, Filter, Layers,
    CheckCheck, BarChart2, Target
} from "lucide-react";
import { getInsights, markInsightRead, postInsightFeedback, triggerIntelRun, getAccessToken } from "@/services/api";

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

// ─── Constants ────────────────────────────────────────────────────────────────
const DET: Record<string, { icon: React.ElementType; color: string; bg: string; label: string }> = {
    anomaly:    { icon: AlertTriangle, color: "text-amber-400",  bg: "bg-amber-400/10",  label: "Anomaly"    },
    trend:      { icon: TrendingDown,  color: "text-rose-400",   bg: "bg-rose-400/10",   label: "Trend"      },
    target_gap: { icon: Target,        color: "text-orange-400", bg: "bg-orange-400/10", label: "Target Gap" },
    inactivity: { icon: Clock,         color: "text-slate-400",  bg: "bg-slate-400/10",  label: "Inactivity" },
    default:    { icon: Sparkles,      color: "text-violet-400", bg: "bg-violet-400/10", label: "Insight"    },
};

const PRI: Record<string, string> = {
    critical: "bg-rose-500/15 text-rose-300 border border-rose-500/30",
    high:     "bg-amber-500/15 text-amber-300 border border-amber-500/30",
    medium:   "bg-sky-500/15 text-sky-300 border border-sky-500/30",
    low:      "bg-slate-500/15 text-slate-400 border border-slate-500/30",
};

// ─── Helpers ──────────────────────────────────────────────────────────────────
const fmt = (n: number) =>
    n >= 1_000_000 ? `₹${(n / 1_000_000).toFixed(1)}M`
    : n >= 1_000   ? `₹${(n / 1_000).toFixed(0)}K`
    : `₹${n.toFixed(0)}`;

const timeAgo = (s: string) => {
    const m = Math.floor((Date.now() - new Date(s).getTime()) / 60000);
    return m < 60 ? `${m}m ago` : m < 1440 ? `${Math.floor(m / 60)}h ago` : `${Math.floor(m / 1440)}d ago`;
};

// ─── Inline Sparkline ─────────────────────────────────────────────────────────
function Sparkline({ data, color }: { data: number[]; color: string }) {
    if (!data.length) return null;
    const max = Math.max(...data);
    const min = Math.min(...data);
    const range = max - min || 1;
    const W = 120, H = 32, pts = data.map((v, i) => {
        const x = (i / (data.length - 1)) * W;
        const y = H - ((v - min) / range) * H;
        return `${x},${y}`;
    }).join(" ");

    return (
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="overflow-visible">
            <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
            {data.map((v, i) => {
                if (i !== data.length - 1) return null;
                const x = (i / (data.length - 1)) * W;
                const y = H - ((v - min) / range) * H;
                return <circle key={i} cx={x} cy={y} r="2.5" fill={color} />;
            })}
        </svg>
    );
}

// ─── Stats Strip ─────────────────────────────────────────────────────────────
function StatsStrip({ insight }: { insight: Insight }) {
    const sig = insight.data_json?.signal ?? {} as SparklineSignal;
    const items: { label: string; value: string; sub?: string }[] = [];

    if (insight.metric_value != null && insight.metric_value !== 0)
        items.push({ label: "Current Value", value: fmt(insight.metric_value) });

    if (insight.metric_change_pct != null)
        items.push({ label: "Change", value: `${insight.metric_change_pct > 0 ? "+" : ""}${insight.metric_change_pct.toFixed(1)}%` });

    if (sig.z_score != null)
        items.push({ label: "Z-Score", value: `${sig.z_score.toFixed(1)}σ`, sub: "vs 30d mean" });

    if (sig.r_squared != null)
        items.push({ label: "R²", value: sig.r_squared.toFixed(2), sub: "trend fit" });

    if (sig.normalized_slope != null)
        items.push({ label: "Slope", value: `${sig.normalized_slope.toFixed(1)}%/wk` });

    if (sig.days_inactive != null)
        items.push({ label: "Inactive", value: `${sig.days_inactive} days` });

    if (sig.target != null)
        items.push({ label: "Target", value: fmt(sig.target) });

    if (sig.gap_pct != null)
        items.push({ label: "Gap", value: `${sig.gap_pct.toFixed(1)}%` });

    if (insight.period_start)
        items.push({ label: "Period", value: `${insight.period_start} → ${insight.period_end ?? "now"}` });

    if (!items.length) return null;

    return (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-3">
            {items.map(({ label, value, sub }) => (
                <div key={label} className="bg-white/4 border border-white/8 rounded-xl px-3 py-2">
                    <p className="text-[10px] text-white/35 mb-0.5">{label}</p>
                    <p className="text-sm font-bold text-white/85">{value}</p>
                    {sub && <p className="text-[10px] text-white/25">{sub}</p>}
                </div>
            ))}
        </div>
    );
}

// ─── Insight Card ─────────────────────────────────────────────────────────────
function InsightCard({ insight, onAction, onAskInChat }: {
    insight: Insight;
    onAction: (id: string, a: "pinned" | "dismissed") => void;
    onAskInChat: (i: Insight) => void;
}) {
    const key = insight.detection_method ?? insight.insight_type ?? "default";
    const meta = DET[key] ?? DET.default;
    const Icon = meta.icon;
    const sig = insight.data_json?.signal ?? {} as SparklineSignal;
    const sparkline = sig.sparkline ?? [];
    const isDown = (insight.metric_change_pct ?? 0) < 0;
    const sparkColor = key === "anomaly" ? "#f59e0b" : isDown ? "#f87171" : "#34d399";
    const dimLabels = sig.dimension_filters
        ? Object.entries(sig.dimension_filters).map(([k, v]) => `${k}: ${v}`).join(" · ")
        : null;

    if (insight._dismissed) return null;

    return (
        <article className={`relative rounded-2xl border overflow-hidden transition-all duration-300
            ${insight._pinned ? "border-violet-500/40 bg-gradient-to-br from-[#1a1230] to-[#13111f]" : "border-white/8 bg-white/4 hover:border-white/14 hover:bg-white/6"}
            ${!insight.is_read ? "ring-1 ring-sky-500/20" : ""}`}>

            {/* Unread dot */}
            {!insight.is_read && <span className="absolute top-4 right-4 w-2 h-2 rounded-full bg-sky-400 ring-2 ring-sky-400/30 z-10" />}
            {insight._pinned && <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-gradient-to-b from-violet-500 to-fuchsia-500" />}

            <div className="p-5">
                {/* Header */}
                <div className="flex items-start gap-3 mb-3">
                    <div className={`shrink-0 w-10 h-10 rounded-xl flex items-center justify-center ${meta.bg}`}>
                        <Icon size={18} className={meta.color} />
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap mb-1">
                            <span className={`text-[10px] font-semibold uppercase tracking-widest px-2 py-0.5 rounded-full ${PRI[insight.priority] ?? PRI.medium}`}>
                                {insight.priority}
                            </span>
                            <span className="text-[10px] text-white/30">{meta.label}</span>
                            {dimLabels && <span className="text-[10px] text-white/20 font-mono">{dimLabels}</span>}
                        </div>
                        <h3 className="text-sm font-semibold text-white/90 leading-snug">{insight.title}</h3>
                    </div>

                    {/* Sparkline */}
                    {sparkline.length > 1 && (
                        <div className="shrink-0 flex flex-col items-end gap-1">
                            <Sparkline data={sparkline} color={sparkColor} />
                            {insight.metric_change_pct != null && (
                                <span className={`text-[11px] font-bold flex items-center gap-0.5
                                    ${isDown ? "text-rose-400" : "text-emerald-400"}`}>
                                    {isDown ? <TrendingDown size={10} /> : <TrendingUp size={10} />}
                                    {insight.metric_change_pct > 0 ? "+" : ""}{insight.metric_change_pct.toFixed(1)}%
                                </span>
                            )}
                        </div>
                    )}
                </div>

                {/* Narrative */}
                <p className="text-[13px] text-white/60 leading-relaxed mb-3">{insight.description}</p>

                {/* Stats strip */}
                <StatsStrip insight={insight} />

                {/* Suggested Action */}
                {insight.suggested_action && (
                    <div className="flex items-start gap-2 bg-amber-400/8 border border-amber-400/20 rounded-xl px-3 py-2.5 mt-3">
                        <Zap size={13} className="text-amber-400 mt-0.5 shrink-0" />
                        <p className="text-[12px] text-amber-200/80 leading-relaxed">{insight.suggested_action}</p>
                    </div>
                )}

                {/* Footer */}
                <div className="flex items-center justify-between mt-4">
                    <div className="flex items-center gap-1.5">
                        <button id={`ask-${insight.insight_id}`} onClick={() => onAskInChat(insight)}
                            className="flex items-center gap-1.5 text-[11px] text-sky-400 hover:text-sky-300 bg-sky-500/10 hover:bg-sky-500/18 px-2.5 py-1.5 rounded-lg transition-all">
                            <MessageSquare size={12} /> Explore in Chat
                        </button>
                        <button id={`pin-${insight.insight_id}`} onClick={() => onAction(insight.insight_id, "pinned")}
                            className={`p-1.5 rounded-lg transition-all ${insight._pinned ? "text-violet-400 bg-violet-500/15" : "text-white/25 hover:text-violet-400 hover:bg-violet-500/10"}`}>
                            {insight._pinned ? <BookmarkCheck size={13} /> : <Bookmark size={13} />}
                        </button>
                        <button id={`dismiss-${insight.insight_id}`} onClick={() => onAction(insight.insight_id, "dismissed")}
                            className="p-1.5 rounded-lg text-white/20 hover:text-rose-400 hover:bg-rose-500/10 transition-all">
                            <ThumbsDown size={13} />
                        </button>
                    </div>
                    <span className="text-[10px] text-white/20">{timeAgo(insight.created_at)}</span>
                </div>
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

    useEffect(() => { if (!getAccessToken()) router.push("/"); }, [router]);

    const fetch = useCallback(async () => {
        try {
            const d = await getInsights();
            setInsights((d.insights || []).map((i: Insight) => ({ ...i, _pinned: false, _dismissed: false })));
        } catch { setInsights([]); }
        finally { setLoading(false); setRefreshing(false); }
    }, []);

    useEffect(() => { fetch(); }, [fetch]);

    const refresh = () => { setRefreshing(true); fetch(); };

    const handleGenerate = async () => {
        setGenerating(true);
        try {
            await triggerIntelRun();
            await fetch(); // Refresh immediately after it finishes
        } catch (e) {
            console.error("Failed to generate insights", e);
        } finally {
            setGenerating(false);
        }
    };

    const onAskInChat = (i: Insight) => {
        markInsightRead(i.insight_id).catch(() => null);
        postInsightFeedback(i.insight_id, "clicked_followup").catch(() => null);
        sessionStorage.setItem("suggested_query", i.suggested_query || i.title);
        router.push("/");
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

    const FILTERS: { key: FilterKey; label: string }[] = [
        { key: "all", label: "All" }, { key: "unread", label: "Unread" },
        { key: "high", label: "High Priority" }, { key: "pinned", label: "Pinned" },
    ];

    return (
        <div className="flex flex-col min-h-screen" style={{ background: "linear-gradient(135deg,#0d0d14 0%,#0f0d1a 60%,#120d1f 100%)" }}>

            {/* Header */}
            <header className="sticky top-0 z-20 border-b border-white/8 backdrop-blur-xl bg-black/30">
                <div className="max-w-4xl mx-auto px-5 py-3.5 flex items-center justify-between gap-4">
                    <div className="flex items-center gap-3">
                        <button id="back-btn" onClick={() => router.push("/")}
                            className="p-1.5 text-white/40 hover:text-white/80 hover:bg-white/8 rounded-lg transition-all">
                            <ArrowLeft size={18} />
                        </button>
                        <div className="flex items-center gap-2">
                            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-500 flex items-center justify-center">
                                <Sparkles size={15} className="text-white" />
                            </div>
                            <div>
                                <h1 className="text-sm font-semibold text-white/90">Intel Insights</h1>
                                <p className="text-[10px] text-white/35">Proactive alerts from your data</p>
                            </div>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        {unreadCount > 0 && (
                            <span className="flex items-center gap-1 bg-sky-500/15 border border-sky-500/30 text-sky-300 text-[11px] font-semibold px-2.5 py-1 rounded-full">
                                <Bell size={10} /> {unreadCount} new
                            </span>
                        )}
                        <button id="generate-btn" onClick={handleGenerate} disabled={generating || loading}
                            className="flex items-center gap-1.5 text-[11px] text-violet-300 hover:text-violet-200 bg-violet-500/15 hover:bg-violet-500/25 border border-violet-500/30 px-3 py-1.5 rounded-lg transition-all disabled:opacity-40">
                            <Zap size={13} className={generating ? "animate-pulse" : ""} /> {generating ? "Generating..." : "Generate"}
                        </button>
                        <button id="refresh-btn" onClick={refresh} disabled={refreshing || generating}
                            className="flex items-center gap-1.5 text-[11px] text-white/50 hover:text-white/80 bg-white/5 hover:bg-white/10 px-3 py-1.5 rounded-lg transition-all disabled:opacity-40">
                            <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} /> Refresh
                        </button>
                    </div>
                </div>
            </header>

            <main className="flex-1 max-w-4xl w-full mx-auto px-5 py-6">
                {loading ? (
                    <div className="flex flex-col items-center justify-center h-60 gap-4">
                        <div className="w-8 h-8 border-2 border-violet-500/40 border-t-violet-400 rounded-full animate-spin" />
                        <p className="text-xs text-white/30">Loading your insights…</p>
                    </div>
                ) : (
                    <>
                        {/* Stats bar */}
                        <div className="grid grid-cols-4 gap-3 mb-6">
                            {[
                                { label: "Total", value: insights.filter(i => !i._dismissed).length, color: "text-white/70" },
                                { label: "Unread", value: unreadCount, color: "text-sky-400" },
                                { label: "Critical", value: insights.filter(i => i.priority === "critical" && !i._dismissed).length, color: "text-rose-400" },
                                { label: "High", value: insights.filter(i => i.priority === "high" && !i._dismissed).length, color: "text-amber-400" },
                            ].map(({ label, value, color }) => (
                                <div key={label} className="bg-white/4 border border-white/8 rounded-xl px-4 py-3 text-center">
                                    <p className={`text-xl font-bold ${color}`}>{value}</p>
                                    <p className="text-[11px] text-white/35 mt-0.5">{label}</p>
                                </div>
                            ))}
                        </div>

                        {/* Controls */}
                        <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
                            <div className="flex items-center gap-1.5 bg-white/4 border border-white/8 rounded-xl p-1">
                                <Filter size={12} className="text-white/30 ml-1" />
                                {FILTERS.map(({ key, label }) => (
                                    <button key={key} id={`filter-${key}`} onClick={() => setFilter(key)}
                                        className={`text-[11px] px-3 py-1.5 rounded-lg transition-all font-medium ${filter === key ? "bg-violet-500/20 text-violet-300 border border-violet-500/30" : "text-white/40 hover:text-white/70"}`}>
                                        {label}
                                    </button>
                                ))}
                            </div>
                            <div className="flex items-center gap-1.5 bg-white/4 border border-white/8 rounded-xl p-1">
                                <Layers size={12} className="text-white/30 ml-1" />
                                {(["priority", "newest", "change"] as SortKey[]).map(s => (
                                    <button key={s} id={`sort-${s}`} onClick={() => setSort(s)}
                                        className={`text-[11px] px-3 py-1.5 rounded-lg transition-all capitalize font-medium ${sort === s ? "bg-white/10 text-white/80" : "text-white/40 hover:text-white/60"}`}>
                                        {s}
                                    </button>
                                ))}
                            </div>
                        </div>

                        {unreadCount > 0 && (
                            <button id="mark-all-read" onClick={markAllRead}
                                className="flex items-center gap-1.5 text-[11px] text-white/40 hover:text-sky-400 mb-4 transition-colors">
                                <CheckCheck size={13} /> Mark all as read
                            </button>
                        )}

                        {visible.length === 0 ? (
                            <div className="flex flex-col items-center justify-center h-52 gap-3">
                                <div className="w-14 h-14 rounded-2xl bg-white/4 border border-white/8 flex items-center justify-center">
                                    <BarChart2 size={24} className="text-white/20" />
                                </div>
                                <p className="text-sm text-white/30">No insights for this filter.</p>
                            </div>
                        ) : (
                            <div className="grid gap-4">
                                {pinned.length > 0 && (
                                    <p className="text-[10px] text-violet-400/60 uppercase tracking-widest font-semibold flex items-center gap-1.5">
                                        <BookmarkCheck size={11} /> Pinned
                                    </p>
                                )}
                                {pinned.map(i => <InsightCard key={i.insight_id} insight={i} onAction={onAction} onAskInChat={onAskInChat} />)}
                                {pinned.length > 0 && rest.length > 0 && (
                                    <p className="text-[10px] text-white/20 uppercase tracking-widest font-semibold mt-1 flex items-center gap-1.5">
                                        <Activity size={11} /> Active Insights
                                    </p>
                                )}
                                {rest.map(i => <InsightCard key={i.insight_id} insight={i} onAction={onAction} onAskInChat={onAskInChat} />)}
                            </div>
                        )}

                        <div className="mt-8 flex items-center justify-between text-[11px] text-white/20">
                            <span>{visible.length} insight{visible.length !== 1 ? "s" : ""} shown</span>
                            {insights[0]?.created_at && <span>Last updated {timeAgo(insights[0].created_at)}</span>}
                        </div>
                    </>
                )}
            </main>
        </div>
    );
}
