"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import {
    TrendingUp, TrendingDown, Package, Target, Map, BarChart2,
    Lightbulb, ArrowLeft, Zap, Activity, ShoppingCart, Users,
    ArrowUpRight, ArrowDownRight, ChevronRight, Star, Award, Flame
} from "lucide-react";

const KPI_CARDS = [
    {
        label: "Total Net Sales",
        value: "₹24.5M",
        sub: "+8.2% vs last month",
        positive: true,
        icon: TrendingUp,
        gradient: "from-violet-600 to-indigo-600",
        glow: "shadow-violet-500/25",
        sparkline: [60, 72, 65, 80, 75, 90, 88, 95, 100],
        drillQuery: "Show net sales by zone and category for last 30 days",
        drillLabel: "Sales breakdown by zone & category",
    },
    {
        label: "Active Zones",
        value: "12",
        sub: "All Regions Active",
        positive: true,
        icon: Map,
        gradient: "from-emerald-500 to-teal-600",
        glow: "shadow-emerald-500/25",
        sparkline: [10, 10, 11, 11, 12, 12, 12, 12, 12],
        drillQuery: "Show active retailers and sales volume by zone this month",
        drillLabel: "Active zones — retailer coverage detail",
    },
    {
        label: "Top SKU Revenue",
        value: "₹3.2M",
        sub: "+12.4% growth",
        positive: true,
        icon: Package,
        gradient: "from-amber-500 to-orange-600",
        glow: "shadow-amber-500/25",
        sparkline: [50, 55, 60, 58, 70, 68, 75, 80, 85],
        drillQuery: "Top 10 products by net sales this month with growth vs last month",
        drillLabel: "Top SKUs — revenue drill-down",
    },
    {
        label: "Target Achievement",
        value: "87%",
        sub: "-3% below target",
        positive: false,
        icon: Target,
        gradient: "from-rose-500 to-pink-600",
        glow: "shadow-rose-500/25",
        sparkline: [95, 92, 90, 88, 87, 87, 86, 87, 87],
        drillQuery: "Show zones below sales target this month with gap percentage",
        drillLabel: "Target gap — zone & rep detail",
    },
];

const QUICK_ACTIONS = [
    {
        label: "Zone-wise Sales",
        desc: "Sales by geography",
        icon: Map,
        query: "Show net sales by zone for last 30 days",
        color: "from-violet-500/20 to-indigo-500/20",
        border: "border-violet-500/30",
        iconColor: "text-violet-400",
        hover: "hover:from-violet-500/30 hover:to-indigo-500/30",
    },
    {
        label: "Top Products",
        desc: "Best performing SKUs",
        icon: Award,
        query: "Top 10 products by net sales this month",
        color: "from-amber-500/20 to-orange-500/20",
        border: "border-amber-500/30",
        iconColor: "text-amber-400",
        hover: "hover:from-amber-500/30 hover:to-orange-500/30",
    },
    {
        label: "Sales vs Target",
        desc: "Achievement analysis",
        icon: Target,
        query: "Compare actual sales vs target by zone",
        color: "from-rose-500/20 to-pink-500/20",
        border: "border-rose-500/30",
        iconColor: "text-rose-400",
        hover: "hover:from-rose-500/30 hover:to-pink-500/30",
    },
    {
        label: "Monthly Trend",
        desc: "6-month performance",
        icon: TrendingUp,
        query: "Show monthly sales trend for last 6 months",
        color: "from-emerald-500/20 to-teal-500/20",
        border: "border-emerald-500/30",
        iconColor: "text-emerald-400",
        hover: "hover:from-emerald-500/30 hover:to-teal-500/30",
    },
    {
        label: "Regional Breakdown",
        desc: "Region & zone split",
        icon: BarChart2,
        query: "Net sales breakdown by region and zone",
        color: "from-sky-500/20 to-blue-500/20",
        border: "border-sky-500/30",
        iconColor: "text-sky-400",
        hover: "hover:from-sky-500/30 hover:to-blue-500/30",
    },
    {
        label: "View Insights",
        desc: "AI-powered alerts",
        icon: Lightbulb,
        query: null,
        route: "/insights",
        color: "from-fuchsia-500/20 to-purple-500/20",
        border: "border-fuchsia-500/30",
        iconColor: "text-fuchsia-400",
        hover: "hover:from-fuchsia-500/30 hover:to-purple-500/30",
    },
];

const RECENT_ACTIVITY = [
    { text: "North Zone exceeded target by 12%", time: "2h ago", icon: Flame, color: "text-emerald-400" },
    { text: "SKU #A204 flagged low stock alert", time: "4h ago", icon: Activity, color: "text-amber-400" },
    { text: "South Zone below target — 78%", time: "6h ago", icon: TrendingDown, color: "text-rose-400" },
    { text: "New monthly record: West Zone", time: "1d ago", icon: Star, color: "text-violet-400" },
    { text: "Q2 report generated successfully", time: "2d ago", icon: BarChart2, color: "text-sky-400" },
];

function MiniSparkline({ data, positive }: { data: number[]; positive: boolean }) {
    const max = Math.max(...data), min = Math.min(...data), range = max - min || 1;
    const W = 80, H = 28;
    const pts = data.map((v, i) => {
        const x = (i / (data.length - 1)) * W;
        const y = H - ((v - min) / range) * H;
        return `${x},${y}`;
    }).join(" ");
    const color = positive ? "#34d399" : "#f87171";
    return (
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
            <polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        </svg>
    );
}

export default function DashboardPage() {
    const router = useRouter();
    const [activeAction, setActiveAction] = useState<string | null>(null);

    const handleAction = (label: string, route: string = "/", query: string | null = null) => {
        setActiveAction(label);
        if (query) sessionStorage.setItem("suggested_query", query);
        setTimeout(() => router.push(route), 150);
    };

    return (
        <div className="min-h-screen text-white" style={{
            background: "linear-gradient(135deg, #0a0f1e 0%, #0d1530 40%, #0f1a3d 70%, #0a0f1e 100%)",
            fontFamily: '"Courier New", Courier, monospace'
        }}>
            {/* Ambient glow blobs */}
            <div className="fixed inset-0 overflow-hidden pointer-events-none">
                <div className="absolute top-0 left-1/4 w-96 h-96 bg-violet-600/10 rounded-full blur-3xl" />
                <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-indigo-600/10 rounded-full blur-3xl" />
                <div className="absolute top-1/2 left-0 w-64 h-64 bg-emerald-600/8 rounded-full blur-3xl" />
            </div>

            {/* Header */}
            <header className="relative z-10 border-b border-white/8 backdrop-blur-sm bg-black/20">
                <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        <Link href="/" className="flex items-center gap-2 text-white/50 hover:text-white transition-colors group">
                            <ArrowLeft size={16} className="group-hover:-translate-x-0.5 transition-transform" />
                            <span className="text-sm">Back</span>
                        </Link>
                        <div className="w-px h-5 bg-white/10" />
                        <div className="flex items-center gap-2.5">
                            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-violet-500/30">
                                <BarChart2 size={15} className="text-white" />
                            </div>
                            <div>
                                <h1 className="text-base font-bold text-white tracking-tight">Analytics Dashboard</h1>
                                <p className="text-[10px] text-white/35">Real-time FMCG Intelligence</p>
                            </div>
                        </div>
                    </div>
                    <div className="flex items-center gap-3">
                        <span className="flex items-center gap-1.5 text-[11px] text-emerald-400 bg-emerald-400/10 border border-emerald-400/20 px-3 py-1.5 rounded-full">
                            <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
                            Live Data
                        </span>
                        <Link href="/insights" className="flex items-center gap-1.5 text-[11px] text-violet-300 bg-violet-500/15 border border-violet-500/30 px-3 py-1.5 rounded-lg hover:bg-violet-500/25 transition-all">
                            <Lightbulb size={12} /> Insights
                        </Link>
                    </div>
                </div>
            </header>

            <div className="relative z-10 max-w-7xl mx-auto px-6 py-8 space-y-8">

                {/* KPI Cards */}
                <div>
                    <div className="flex items-center gap-2 mb-4">
                        <Zap size={14} className="text-violet-400" />
                        <span className="text-xs font-semibold text-white/40 uppercase tracking-widest">Key Metrics</span>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                        {KPI_CARDS.map((card) => {
                            const Icon = card.icon;
                            return (
                                <div key={card.label}
                                    onClick={() => handleAction(card.label, "/", card.drillQuery)}
                                    title={card.drillLabel}
                                    className={`relative rounded-2xl border border-white/8 bg-white/4 backdrop-blur-sm overflow-hidden p-5 hover:bg-white/8 hover:border-white/16 hover:scale-[1.02] transition-all duration-300 cursor-pointer shadow-xl ${card.glow} group`}>
                                    {/* Gradient top accent */}
                                    <div className={`absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r ${card.gradient}`} />
                                    <div className="flex items-start justify-between mb-4">
                                        <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${card.gradient} flex items-center justify-center shadow-lg`}>
                                            <Icon size={18} className="text-white" />
                                        </div>
                                        <MiniSparkline data={card.sparkline} positive={card.positive} />
                                    </div>
                                    <p className="text-[11px] text-white/40 uppercase tracking-wider mb-1">{card.label}</p>
                                    <p className="text-2xl font-bold text-white mb-2">{card.value}</p>
                                    <div className={`flex items-center gap-1 text-[11px] font-semibold ${card.positive ? "text-emerald-400" : "text-rose-400"}`}>
                                        {card.positive ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                                        {card.sub}
                                    </div>
                                    <div className="absolute bottom-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity">
                                        <ChevronRight size={14} className="text-white/40" />
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>

                {/* Quick Actions + Recent Activity */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

                    {/* Quick Actions - 2/3 width */}
                    <div className="lg:col-span-2">
                        <div className="flex items-center gap-2 mb-4">
                            <ShoppingCart size={14} className="text-amber-400" />
                            <span className="text-xs font-semibold text-white/40 uppercase tracking-widest">Quick Actions</span>
                        </div>
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                            {QUICK_ACTIONS.map((action) => {
                                const Icon = action.icon;
                                const isActive = activeAction === action.label;
                                return (
                                    <button key={action.label}
                                        onClick={() => handleAction(action.label, action.route ?? "/", action.query)}
                                        className={`relative group rounded-2xl border ${action.border} bg-gradient-to-br ${action.color} ${action.hover} p-4 text-left transition-all duration-200 cursor-pointer
                                            ${isActive ? "scale-95 opacity-70" : "hover:scale-[1.02] hover:shadow-lg"}`}>
                                        <div className={`w-9 h-9 rounded-xl bg-white/8 flex items-center justify-center mb-3 group-hover:scale-110 transition-transform`}>
                                            <Icon size={18} className={action.iconColor} />
                                        </div>
                                        <p className="text-sm font-semibold text-white/90 leading-tight mb-1">{action.label}</p>
                                        <p className="text-[10px] text-white/40 leading-tight">{action.desc}</p>
                                        <ChevronRight size={12} className="absolute bottom-4 right-4 text-white/20 group-hover:text-white/50 group-hover:translate-x-0.5 transition-all" />
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {/* Recent Activity - 1/3 width */}
                    <div>
                        <div className="flex items-center gap-2 mb-4">
                            <Activity size={14} className="text-sky-400" />
                            <span className="text-xs font-semibold text-white/40 uppercase tracking-widest">Recent Activity</span>
                        </div>
                        <div className="rounded-2xl border border-white/8 bg-white/4 backdrop-blur-sm overflow-hidden">
                            {RECENT_ACTIVITY.map((item, i) => {
                                const Icon = item.icon;
                                return (
                                    <div key={i} className={`flex items-start gap-3 p-4 hover:bg-white/4 transition-colors cursor-default ${i < RECENT_ACTIVITY.length - 1 ? "border-b border-white/5" : ""}`}>
                                        <div className="w-7 h-7 rounded-lg bg-white/6 flex items-center justify-center shrink-0 mt-0.5">
                                            <Icon size={13} className={item.color} />
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <p className="text-[12px] text-white/75 leading-snug">{item.text}</p>
                                            <p className="text-[10px] text-white/25 mt-1">{item.time}</p>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                </div>

                {/* Performance Bar */}
                <div className="rounded-2xl border border-white/8 bg-white/4 backdrop-blur-sm p-5">
                    <div className="flex items-center justify-between mb-4">
                        <div className="flex items-center gap-2">
                            <Users size={14} className="text-sky-400" />
                            <span className="text-xs font-semibold text-white/40 uppercase tracking-widest">Zone Performance</span>
                        </div>
                        <button onClick={() => handleAction("Zone Performance", "/", "Show net sales by zone for last 30 days")}
                            className="text-[11px] text-violet-400 hover:text-violet-300 flex items-center gap-1 transition-colors">
                            View All <ChevronRight size={11} />
                        </button>
                    </div>
                    <div className="space-y-3">
                        {[
                            { zone: "North Zone", pct: 94, val: "₹6.8M", color: "from-violet-500 to-indigo-500", queryZone: "North-1" },
                            { zone: "South Zone", pct: 78, val: "₹5.2M", color: "from-rose-500 to-pink-500",   queryZone: "South-1" },
                            { zone: "East Zone",  pct: 87, val: "₹4.9M", color: "from-amber-500 to-orange-500", queryZone: "East" },
                            { zone: "West Zone",  pct: 102, val: "₹7.6M", color: "from-emerald-500 to-teal-500", queryZone: "Central" },
                        ].map((z) => (
                            <div key={z.zone}
                                onClick={() => handleAction(z.zone, "/", `Show net sales, top SKUs, and active retailers for ${z.queryZone} zone this month`)}
                                className="cursor-pointer group rounded-lg px-2 -mx-2 py-1 hover:bg-white/4 transition-all"
                                title={`Drill into ${z.zone} details`}>
                                <div className="flex items-center justify-between mb-1.5">
                                    <span className="text-[12px] text-white/70 group-hover:text-white/90 transition-colors flex items-center gap-1.5">
                                        {z.zone}
                                        <ChevronRight size={10} className="text-white/20 group-hover:text-white/50 transition-colors" />
                                    </span>
                                    <div className="flex items-center gap-2">
                                        <span className="text-[11px] text-white/40">{z.val}</span>
                                        <span className={`text-[11px] font-bold ${z.pct >= 100 ? "text-emerald-400" : z.pct >= 85 ? "text-amber-400" : "text-rose-400"}`}>{z.pct}%</span>
                                    </div>
                                </div>
                                <div className="h-1.5 bg-white/8 rounded-full overflow-hidden">
                                    <div className={`h-full bg-gradient-to-r ${z.color} rounded-full transition-all duration-700`}
                                        style={{ width: `${Math.min(z.pct, 100)}%` }} />
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
}
