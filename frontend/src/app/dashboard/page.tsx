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
        label: "Total Net Sales", value: "₹24.5M", sub: "+8.2% vs last month", positive: true,
        icon: TrendingUp, iconBg: "bg-indigo-50", iconColor: "text-indigo-600",
        trend: "text-emerald-600", trendBg: "bg-emerald-50",
        sparkline: [60, 72, 65, 80, 75, 90, 88, 95, 100],
        drillQuery: "Show net sales by zone and category for last 30 days",
        drillLabel: "Sales breakdown by zone & category",
    },
    {
        label: "Active Zones", value: "12", sub: "All Regions Active", positive: true,
        icon: Map, iconBg: "bg-emerald-50", iconColor: "text-emerald-600",
        trend: "text-emerald-600", trendBg: "bg-emerald-50",
        sparkline: [10, 10, 11, 11, 12, 12, 12, 12, 12],
        drillQuery: "Show active retailers and sales volume by zone this month",
        drillLabel: "Active zones — retailer coverage detail",
    },
    {
        label: "Top SKU Revenue", value: "₹3.2M", sub: "+12.4% growth", positive: true,
        icon: Package, iconBg: "bg-orange-50", iconColor: "text-orange-500",
        trend: "text-emerald-600", trendBg: "bg-emerald-50",
        sparkline: [50, 55, 60, 58, 70, 68, 75, 80, 85],
        drillQuery: "Top 10 products by net sales this month with growth vs last month",
        drillLabel: "Top SKUs — revenue drill-down",
    },
    {
        label: "Target Achievement", value: "87%", sub: "-3% below target", positive: false,
        icon: Target, iconBg: "bg-rose-50", iconColor: "text-rose-500",
        trend: "text-rose-600", trendBg: "bg-rose-50",
        sparkline: [95, 92, 90, 88, 87, 87, 86, 87, 87],
        drillQuery: "Show zones below sales target this month with gap percentage",
        drillLabel: "Target gap — zone & rep detail",
    },
];

const QUICK_ACTIONS = [
    { label: "Zone-wise Sales",   desc: "Sales by geography",    icon: Map,       query: "Show net sales by zone for last 30 days",         iconBg: "bg-indigo-50",  iconColor: "text-indigo-600" },
    { label: "Top Products",      desc: "Best performing SKUs",  icon: Award,     query: "Top 10 products by net sales this month",          iconBg: "bg-amber-50",   iconColor: "text-amber-600" },
    { label: "Sales vs Target",   desc: "Achievement analysis",  icon: Target,    query: "Compare actual sales vs target by zone",           iconBg: "bg-rose-50",    iconColor: "text-rose-500"  },
    { label: "Monthly Trend",     desc: "6-month performance",   icon: TrendingUp,query: "Show monthly sales trend for last 6 months",       iconBg: "bg-emerald-50", iconColor: "text-emerald-600" },
    { label: "Regional Breakdown",desc: "Region & zone split",   icon: BarChart2, query: "Net sales breakdown by region and zone",           iconBg: "bg-sky-50",     iconColor: "text-sky-600"   },
    { label: "View Insights",     desc: "AI-powered alerts",     icon: Lightbulb, query: null, route: "/insights",                           iconBg: "bg-purple-50",  iconColor: "text-purple-600"},
];

const RECENT_ACTIVITY = [
    { text: "North Zone exceeded target by 12%",    time: "2h ago",  icon: Flame,       color: "text-emerald-500" },
    { text: "SKU #A204 flagged low stock alert",     time: "4h ago",  icon: Activity,    color: "text-amber-500"   },
    { text: "South Zone below target — 78%",        time: "6h ago",  icon: TrendingDown,color: "text-rose-500"    },
    { text: "New monthly record: West Zone",         time: "1d ago",  icon: Star,        color: "text-indigo-500"  },
    { text: "Q2 report generated successfully",      time: "2d ago",  icon: BarChart2,   color: "text-sky-500"     },
];

function MiniSparkline({ data, positive }: { data: number[]; positive: boolean }) {
    const max = Math.max(...data), min = Math.min(...data), range = max - min || 1;
    const W = 72, H = 24;
    const pts = data.map((v, i) => `${(i / (data.length - 1)) * W},${H - ((v - min) / range) * H}`).join(" ");
    return (
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
            <polyline points={pts} fill="none" stroke={positive ? "#10b981" : "#f43f5e"} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        </svg>
    );
}

export default function DashboardPage() {
    const router = useRouter();
    const [activeAction, setActiveAction] = useState<string | null>(null);

    const handleAction = (label: string, route = "/", query: string | null = null) => {
        setActiveAction(label);
        if (query) sessionStorage.setItem("suggested_query", query);
        setTimeout(() => router.push(route), 150);
    };

    return (
        <div className="min-h-screen bg-gray-50">

            {/* Header */}
            <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
                <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        <Link href="/" className="flex items-center gap-2 text-gray-500 hover:text-gray-800 transition-colors group text-sm">
                            <ArrowLeft size={15} className="group-hover:-translate-x-0.5 transition-transform" /> Back
                        </Link>
                        <div className="w-px h-5 bg-gray-200" />
                        <div className="flex items-center gap-2.5">
                            <div className="w-8 h-8 gradient-mesh rounded-lg flex items-center justify-center">
                                <BarChart2 size={14} className="text-white" />
                            </div>
                            <div>
                                <h1 className="text-sm font-bold text-gray-900">Analytics Dashboard</h1>
                                <p className="text-[10px] text-gray-400">Real-time CPG Intelligence</p>
                            </div>
                        </div>
                    </div>
                    <div className="flex items-center gap-3">
                        <span className="flex items-center gap-1.5 text-xs text-emerald-600 bg-emerald-50 border border-emerald-200 px-3 py-1.5 rounded-full font-medium">
                            <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" /> Live Data
                        </span>
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
                        <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">Key Metrics</span>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                        {KPI_CARDS.map((card) => {
                            const Icon = card.icon;
                            return (
                                <div key={card.label}
                                    onClick={() => handleAction(card.label, "/", card.drillQuery)}
                                    title={card.drillLabel}
                                    className="card card-hover p-5 cursor-pointer group">
                                    <div className="flex items-start justify-between mb-4">
                                        <div className={`w-10 h-10 rounded-xl ${card.iconBg} flex items-center justify-center`}>
                                            <Icon size={18} className={card.iconColor} />
                                        </div>
                                        <MiniSparkline data={card.sparkline} positive={card.positive} />
                                    </div>
                                    <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{card.label}</p>
                                    <p className="text-2xl font-bold text-gray-900 mb-2">{card.value}</p>
                                    <div className="flex items-center justify-between">
                                        <span className={`text-xs font-semibold flex items-center gap-0.5 px-2 py-0.5 rounded-full ${card.trendBg} ${card.trend}`}>
                                            {card.positive ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
                                            {card.sub}
                                        </span>
                                        <ChevronRight size={14} className="text-gray-300 group-hover:text-orange-400 transition-colors" />
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>

                {/* Quick Actions + Recent Activity */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

                    <div className="lg:col-span-2">
                        <div className="flex items-center gap-2 mb-4">
                            <ShoppingCart size={14} className="text-orange-500" />
                            <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">Quick Actions</span>
                        </div>
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                            {QUICK_ACTIONS.map((action) => {
                                const Icon = action.icon;
                                const isActive = activeAction === action.label;
                                return (
                                    <button key={action.label}
                                        onClick={() => handleAction(action.label, action.route ?? "/", action.query)}
                                        className={`card card-hover text-left p-4 group transition-all ${isActive ? "opacity-60 scale-95" : ""}`}>
                                        <div className={`w-9 h-9 rounded-xl ${action.iconBg} flex items-center justify-center mb-3`}>
                                            <Icon size={17} className={action.iconColor} />
                                        </div>
                                        <p className="text-sm font-semibold text-gray-900 leading-tight mb-1">{action.label}</p>
                                        <p className="text-xs text-gray-400">{action.desc}</p>
                                        <ChevronRight size={12} className="mt-2 text-gray-300 group-hover:text-orange-400 transition-colors" />
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    <div>
                        <div className="flex items-center gap-2 mb-4">
                            <Activity size={14} className="text-indigo-500" />
                            <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">Recent Activity</span>
                        </div>
                        <div className="card overflow-hidden">
                            {RECENT_ACTIVITY.map((item, i) => {
                                const Icon = item.icon;
                                return (
                                    <div key={i} className={`flex items-start gap-3 p-4 hover:bg-gray-50 transition-colors ${i < RECENT_ACTIVITY.length - 1 ? "border-b border-gray-100" : ""}`}>
                                        <div className="w-7 h-7 rounded-lg bg-gray-50 border border-gray-100 flex items-center justify-center shrink-0 mt-0.5">
                                            <Icon size={13} className={item.color} />
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <p className="text-xs text-gray-700 leading-snug">{item.text}</p>
                                            <p className="text-[10px] text-gray-400 mt-1">{item.time}</p>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                </div>

                {/* Zone Performance */}
                <div className="card p-6">
                    <div className="flex items-center justify-between mb-5">
                        <div className="flex items-center gap-2">
                            <Users size={14} className="text-indigo-500" />
                            <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">Zone Performance</span>
                        </div>
                        <button onClick={() => handleAction("Zone Performance", "/", "Show net sales by zone for last 30 days")}
                            className="text-xs text-orange-500 hover:text-orange-600 flex items-center gap-1 font-medium transition-colors">
                            View All <ChevronRight size={12} />
                        </button>
                    </div>
                    <div className="space-y-4">
                        {[
                            { zone: "North Zone", pct: 94,  val: "₹6.8M", color: "bg-indigo-500",  queryZone: "North-1" },
                            { zone: "South Zone", pct: 78,  val: "₹5.2M", color: "bg-rose-500",    queryZone: "South-1" },
                            { zone: "East Zone",  pct: 87,  val: "₹4.9M", color: "bg-amber-500",   queryZone: "East"    },
                            { zone: "West Zone",  pct: 102, val: "₹7.6M", color: "bg-emerald-500", queryZone: "Central" },
                        ].map((z) => (
                            <div key={z.zone}
                                onClick={() => handleAction(z.zone, "/", `Show net sales, top SKUs, and active retailers for ${z.queryZone} zone this month`)}
                                className="cursor-pointer group">
                                <div className="flex items-center justify-between mb-1.5">
                                    <span className="text-sm text-gray-700 font-medium group-hover:text-gray-900 flex items-center gap-1">
                                        {z.zone} <ChevronRight size={12} className="text-gray-300 group-hover:text-orange-400 transition-colors" />
                                    </span>
                                    <div className="flex items-center gap-3">
                                        <span className="text-xs text-gray-400">{z.val}</span>
                                        <span className={`text-xs font-bold ${z.pct >= 100 ? "text-emerald-600" : z.pct >= 85 ? "text-amber-600" : "text-rose-600"}`}>{z.pct}%</span>
                                    </div>
                                </div>
                                <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                                    <div className={`h-full ${z.color} rounded-full transition-all duration-700`}
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
