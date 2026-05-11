"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import {
    ArrowLeft, MessageSquare, Download, ChevronRight, AlertTriangle,
    TrendingDown, Target, Clock, Sparkles, BarChart2, Map, Users,
    Package, Zap, Activity
} from "lucide-react";

// ─── Drill-down question sets per insight type ────────────────────────────────
const DRILL_DOWN_QUESTIONS: Record<string, { label: string; query: string; icon: any }[]> = {
    anomaly: [
        { label: "7-day failure trend", query: "Show failure rate trend over the last 7 days", icon: Activity },
        { label: "Top failed queries", query: "Which users have the most failed queries?", icon: Users },
        { label: "Failures by hour", query: "What time of day do most failures occur?", icon: Clock },
        { label: "Error breakdown", query: "Show all failed queries with their error types", icon: AlertTriangle },
    ],
    trend: [
        { label: "Zone breakdown", query: "Show this trend broken down by zone", icon: Map },
        { label: "YoY comparison", query: "Compare this trend with the same period last year", icon: TrendingDown },
        { label: "Monthly split", query: "Show monthly breakdown of this trend for last 6 months", icon: BarChart2 },
        { label: "Top contributors", query: "What are the top contributing SKUs to this trend?", icon: Package },
    ],
    target_gap: [
        { label: "Zone gap detail", query: "Show zones below sales target this month with gap percentage", icon: Target },
        { label: "Rep performance", query: "Which salesreps are furthest from target this month?", icon: Users },
        { label: "SKU-level gap", query: "Show SKUs contributing most to target shortfall", icon: Package },
        { label: "Trend to target", query: "Show daily sales pace vs target for current month", icon: Activity },
    ],
    inactivity: [
        { label: "Inactive retailers", query: "Show retailers with zero purchases in last 14 days", icon: Clock },
        { label: "Zone inactivity", query: "Which zones have the most inactive retailers?", icon: Map },
        { label: "Last purchase dates", query: "Show last purchase date for all inactive retailers", icon: BarChart2 },
        { label: "Recovery potential", query: "Inactive retailers sorted by historical purchase value", icon: Zap },
    ],
    opportunity: [
        { label: "Revenue by zone", query: "Show revenue opportunity by zone last 30 days", icon: Map },
        { label: "High-potential SKUs", query: "Which SKUs have the highest growth potential this quarter?", icon: Package },
        { label: "Channel split", query: "Revenue opportunity breakdown by retailer channel", icon: BarChart2 },
        { label: "Top accounts", query: "Top 10 accounts by untapped revenue potential", icon: Users },
    ],
    default: [
        { label: "Full P&L by zone", query: "Show net sales and gross margin by zone this month", icon: BarChart2 },
        { label: "Category split", query: "Sales breakdown by product category this month", icon: Package },
        { label: "Monthly trend", query: "Show monthly sales trend for last 6 months", icon: Activity },
        { label: "Distributor leaderboard", query: "Top 10 distributors by secondary sales last 30 days", icon: Users },
    ],
};

const PRI_CONFIG: Record<string, { label: string; bg: string; text: string; border: string }> = {
    critical: { label: "CRITICAL", bg: "bg-rose-500/20",   text: "text-rose-300",   border: "border-rose-500/40" },
    high:     { label: "HIGH",     bg: "bg-amber-500/20",  text: "text-amber-300",  border: "border-amber-500/40" },
    medium:   { label: "MEDIUM",   bg: "bg-sky-500/20",    text: "text-sky-300",    border: "border-sky-500/40" },
    low:      { label: "LOW",      bg: "bg-slate-500/20",  text: "text-slate-400",  border: "border-slate-500/40" },
};

const TYPE_META: Record<string, { icon: any; gradient: string; label: string }> = {
    anomaly:    { icon: AlertTriangle, gradient: "from-amber-500 to-orange-600",   label: "Anomaly" },
    trend:      { icon: TrendingDown,  gradient: "from-rose-500 to-pink-600",      label: "Trend" },
    target_gap: { icon: Target,        gradient: "from-orange-500 to-red-600",     label: "Target Gap" },
    inactivity: { icon: Clock,         gradient: "from-slate-500 to-slate-600",    label: "Inactivity" },
    opportunity:{ icon: Zap,           gradient: "from-emerald-500 to-teal-600",   label: "Opportunity" },
    default:    { icon: Sparkles,      gradient: "from-violet-500 to-fuchsia-600", label: "Insight" },
};

function InsightDetailContent() {
    const router = useRouter();
    const params = useSearchParams();

    const title    = params.get("title")    || "Insight Detail";
    const type     = (params.get("type")    || "default").toLowerCase();
    const body     = params.get("body")     || "";
    const priority = (params.get("priority") || "medium").toLowerCase();
    const sugQuery = params.get("query")    || "";

    const drillQuestions = DRILL_DOWN_QUESTIONS[type] ?? DRILL_DOWN_QUESTIONS.default;
    const meta = TYPE_META[type] ?? TYPE_META.default;
    const MetaIcon = meta.icon;
    const pri = PRI_CONFIG[priority] ?? PRI_CONFIG.medium;

    function goToChat(query: string) {
        sessionStorage.setItem("suggested_query", query);
        router.push("/");
    }

    function handleExport() {
        const content = [
            `Insight: ${title}`,
            `Type: ${type}`,
            `Priority: ${priority}`,
            ``,
            body,
            sugQuery ? `\nSuggested Query: ${sugQuery}` : "",
            `\nDrill-down questions:`,
            ...drillQuestions.map((q, i) => `${i + 1}. ${q.query}`),
        ].join("\n");
        const blob = new Blob([content], { type: "text/plain" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `insight-${type}-${Date.now()}.txt`;
        a.click();
        URL.revokeObjectURL(url);
    }

    return (
        <div className="min-h-screen text-white" style={{
            background: "linear-gradient(135deg, #080b18 0%, #0d1028 40%, #100c22 70%, #080b18 100%)",
            fontFamily: '"Courier New", Courier, monospace'
        }}>
            {/* Ambient blobs */}
            <div className="fixed inset-0 overflow-hidden pointer-events-none">
                <div className="absolute top-0 right-1/3 w-80 h-80 bg-violet-600/12 rounded-full blur-3xl" />
                <div className="absolute bottom-1/3 left-1/4 w-64 h-64 bg-indigo-600/10 rounded-full blur-3xl" />
            </div>

            {/* Header */}
            <header className="sticky top-0 z-20 border-b border-white/8 backdrop-blur-xl bg-black/40">
                <div className="max-w-4xl mx-auto px-5 py-3.5 flex items-center justify-between gap-4">
                    <div className="flex items-center gap-3">
                        <button onClick={() => router.push("/insights")}
                            className="p-1.5 text-white/40 hover:text-white hover:bg-white/8 rounded-lg transition-all group">
                            <ArrowLeft size={17} className="group-hover:-translate-x-0.5 transition-transform" />
                        </button>
                        <div className="w-px h-5 bg-white/10" />
                        <div className="flex items-center gap-2.5">
                            <div className={`w-9 h-9 rounded-xl bg-gradient-to-br ${meta.gradient} flex items-center justify-center shadow-lg`}>
                                <MetaIcon size={16} className="text-white" />
                            </div>
                            <div>
                                <h1 className="text-sm font-bold text-white/90">Insight Detail</h1>
                                <p className="text-[10px] text-white/35">{meta.label} · Drill-down view</p>
                            </div>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className={`inline-flex items-center gap-1 text-[10px] font-bold px-2.5 py-1 rounded-full border ${pri.bg} ${pri.text} ${pri.border}`}>
                            {pri.label}
                        </span>
                        <button onClick={handleExport}
                            className="flex items-center gap-1.5 text-[11px] text-white/50 hover:text-white bg-white/5 hover:bg-white/10 border border-white/10 px-3 py-1.5 rounded-lg transition-all">
                            <Download size={12} /> Export
                        </button>
                    </div>
                </div>
            </header>

            <main className="relative z-10 max-w-4xl mx-auto px-5 py-8 space-y-6">

                {/* Insight summary card */}
                <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-sm overflow-hidden">
                    <div className={`h-1 bg-gradient-to-r ${meta.gradient}`} />
                    <div className="p-6">
                        <div className="flex items-start gap-4">
                            <div className={`shrink-0 w-12 h-12 rounded-xl bg-gradient-to-br ${meta.gradient} flex items-center justify-center shadow-lg`}>
                                <MetaIcon size={20} className="text-white" />
                            </div>
                            <div className="flex-1">
                                <h2 className="text-xl font-bold text-white/95 mb-2 leading-snug">{title}</h2>
                                <p className="text-sm text-white/60 leading-relaxed">{body || "No additional description available."}</p>
                            </div>
                        </div>

                        {/* Suggested query */}
                        {sugQuery && (
                            <div className="mt-5 bg-sky-500/8 border border-sky-500/20 rounded-xl px-4 py-3.5">
                                <p className="text-[10px] text-sky-400/60 uppercase tracking-wider mb-1.5">Suggested Query</p>
                                <p className="text-[13px] text-sky-200/80 font-mono leading-relaxed">{sugQuery}</p>
                                <button onClick={() => goToChat(sugQuery)}
                                    className="mt-2.5 flex items-center gap-1.5 text-[11px] font-semibold text-sky-400 hover:text-sky-300 transition-colors">
                                    <MessageSquare size={11} /> Run in Chat <ChevronRight size={11} />
                                </button>
                            </div>
                        )}

                        {/* Action buttons */}
                        <div className="flex items-center gap-3 mt-5">
                            <button onClick={() => goToChat(sugQuery || title)}
                                className="flex items-center gap-2 text-[12px] font-semibold text-white bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 px-4 py-2 rounded-lg transition-all shadow-lg shadow-sky-500/20">
                                <MessageSquare size={13} /> Ask in Chat
                            </button>
                            <button onClick={() => router.push("/insights")}
                                className="flex items-center gap-2 text-[12px] text-white/50 hover:text-white bg-white/5 hover:bg-white/10 border border-white/10 px-4 py-2 rounded-lg transition-all">
                                <ArrowLeft size={13} /> Back to Insights
                            </button>
                        </div>
                    </div>
                </div>

                {/* Drill-down panel */}
                <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-sm overflow-hidden">
                    <div className="px-5 py-4 border-b border-white/8 flex items-center gap-2">
                        <BarChart2 size={14} className="text-violet-400" />
                        <span className="text-xs font-bold text-white/60 uppercase tracking-widest">Drill Down — Explore Further</span>
                        <span className="text-[10px] bg-violet-500/20 border border-violet-500/30 text-violet-300 px-2 py-0.5 rounded-full ml-auto">{drillQuestions.length} actions</span>
                    </div>
                    <div className="p-4 space-y-2.5">
                        {drillQuestions.map((q, i) => {
                            const QIcon = q.icon;
                            return (
                                <button key={i} onClick={() => goToChat(q.query)}
                                    className="w-full flex items-center gap-3 bg-white/4 hover:bg-white/8 border border-white/8 hover:border-white/16 rounded-xl px-4 py-3.5 text-left transition-all group">
                                    <div className="w-8 h-8 rounded-lg bg-white/6 flex items-center justify-center shrink-0">
                                        <QIcon size={15} className="text-violet-400 group-hover:text-violet-300 transition-colors" />
                                    </div>
                                    <span className="flex-1 text-[13px] text-white/70 group-hover:text-white/90 font-medium transition-colors">{q.query}</span>
                                    <ChevronRight size={14} className="text-white/20 group-hover:text-violet-400 group-hover:translate-x-0.5 transition-all shrink-0" />
                                </button>
                            );
                        })}
                    </div>
                </div>

                {/* Related actions */}
                <div className="grid grid-cols-2 gap-3">
                    <button onClick={() => goToChat("Show net sales by zone for last 30 days")}
                        className="flex items-center gap-3 bg-violet-500/10 hover:bg-violet-500/18 border border-violet-500/25 rounded-xl px-4 py-3.5 transition-all group text-left">
                        <Map size={16} className="text-violet-400 shrink-0" />
                        <div>
                            <p className="text-[12px] font-semibold text-violet-300">Zone Heatmap</p>
                            <p className="text-[10px] text-white/35">Sales by geography</p>
                        </div>
                        <ChevronRight size={12} className="ml-auto text-white/20 group-hover:text-violet-400 transition-colors" />
                    </button>
                    <button onClick={() => goToChat("Top 10 products by net sales this month")}
                        className="flex items-center gap-3 bg-amber-500/10 hover:bg-amber-500/18 border border-amber-500/25 rounded-xl px-4 py-3.5 transition-all group text-left">
                        <Package size={16} className="text-amber-400 shrink-0" />
                        <div>
                            <p className="text-[12px] font-semibold text-amber-300">Top SKUs</p>
                            <p className="text-[10px] text-white/35">Best performing products</p>
                        </div>
                        <ChevronRight size={12} className="ml-auto text-white/20 group-hover:text-amber-400 transition-colors" />
                    </button>
                </div>

            </main>
        </div>
    );
}

export default function InsightDetailPage() {
    return (
        <Suspense fallback={
            <div className="min-h-screen flex items-center justify-center" style={{
                background: "linear-gradient(135deg, #080b18, #0d1028)",
                fontFamily: '"Courier New", Courier, monospace'
            }}>
                <div className="w-10 h-10 border-2 border-violet-500/40 border-t-violet-400 rounded-full animate-spin" />
            </div>
        }>
            <InsightDetailContent />
        </Suspense>
    );
}
