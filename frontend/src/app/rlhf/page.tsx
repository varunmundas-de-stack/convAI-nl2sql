"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
    ArrowLeft,
    RefreshCw,
    Zap,
    GitBranch,
    Star,
    TrendingUp,
    CheckCircle,
    XCircle,
    AlertTriangle,
    ChevronDown,
    ChevronUp,
    Play,
    RotateCcw,
    ArrowUpCircle,
    FlaskConical,
    StopCircle,
    Info,
    BarChart3,
    Layers,
    Cpu,
    MessageSquare,
} from "lucide-react";
import {
    getPromptVersions,
    getAbStatus,
    createAbTest,
    stopAbTest,
    triggerRefinement,
    runRefinementCycle,
    promoteVersion,
    rollbackVersion,
    compareVersions,
    getPreferencePairs,
} from "@/services/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface VersionStat {
    version_tag: string;
    filename: string;
    few_shot_count: number;
    is_active: boolean;
    parent_version: string | null;
    created_at: string | null;
    avg_rating: number;
    feedback_count: number;
    distribution: Record<string, number>;
}

interface Toast {
    id: number;
    type: "success" | "error" | "info";
    message: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function StarBar({ rating, max = 5 }: { rating: number; max?: number }) {
    return (
        <div className="flex items-center gap-1">
            {Array.from({ length: max }).map((_, i) => (
                <Star
                    key={i}
                    size={12}
                    className={
                        i < Math.round(rating)
                            ? "fill-amber-400 text-amber-400"
                            : "text-gray-200 fill-gray-200"
                    }
                />
            ))}
            <span className="ml-1 text-xs font-mono text-gray-600">
                {rating > 0 ? rating.toFixed(2) : "—"}
            </span>
        </div>
    );
}

function Badge({ active }: { active: boolean }) {
    return active ? (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-100 text-emerald-700">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            Active
        </span>
    ) : (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-gray-100 text-gray-500">
            Inactive
        </span>
    );
}

function StatusChip({ status }: { status: string }) {
    const map: Record<string, string> = {
        refined: "bg-emerald-100 text-emerald-700",
        skipped: "bg-amber-100 text-amber-700",
        error: "bg-red-100 text-red-700",
        success: "bg-blue-100 text-blue-700",
    };
    return (
        <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${map[status] ?? "bg-gray-100 text-gray-600"}`}>
            {status}
        </span>
    );
}

function RatingDistBar({ dist }: { dist: Record<string, number> }) {
    const total = Object.values(dist).reduce((a, b) => a + b, 0);
    if (total === 0) return <p className="text-xs text-gray-400">No ratings yet</p>;
    return (
        <div className="space-y-1 mt-1">
            {[5, 4, 3, 2, 1].map((r) => {
                const count = dist[String(r)] ?? 0;
                const pct = total > 0 ? (count / total) * 100 : 0;
                return (
                    <div key={r} className="flex items-center gap-2 text-xs">
                        <span className="w-3 text-gray-500 font-mono">{r}</span>
                        <div className="flex-1 bg-gray-100 rounded-full h-1.5">
                            <div
                                className="h-1.5 rounded-full bg-amber-400 transition-all duration-500"
                                style={{ width: `${pct}%` }}
                            />
                        </div>
                        <span className="w-6 text-right text-gray-500">{count}</span>
                    </div>
                );
            })}
        </div>
    );
}

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------
function Toasts({ toasts, remove }: { toasts: Toast[]; remove: (id: number) => void }) {
    return (
        <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
            {toasts.map((t) => (
                <div
                    key={t.id}
                    className={`pointer-events-auto flex items-start gap-2.5 px-4 py-3 rounded-xl shadow-lg text-sm font-medium border transition-all
                        ${t.type === "success" ? "bg-emerald-50 border-emerald-200 text-emerald-800" :
                          t.type === "error" ? "bg-red-50 border-red-200 text-red-800" :
                          "bg-blue-50 border-blue-200 text-blue-800"}`}
                >
                    {t.type === "success" && <CheckCircle size={16} className="mt-0.5 shrink-0 text-emerald-600" />}
                    {t.type === "error" && <XCircle size={16} className="mt-0.5 shrink-0 text-red-500" />}
                    {t.type === "info" && <Info size={16} className="mt-0.5 shrink-0 text-blue-500" />}
                    <span className="flex-1">{t.message}</span>
                    <button onClick={() => remove(t.id)} className="text-current opacity-50 hover:opacity-100 ml-1">×</button>
                </div>
            ))}
        </div>
    );
}

// ---------------------------------------------------------------------------
// Section card wrapper
// ---------------------------------------------------------------------------
function Card({ title, icon, children, className = "" }: {
    title: string;
    icon: React.ReactNode;
    children: React.ReactNode;
    className?: string;
}) {
    return (
        <div className={`bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden ${className}`}>
            <div className="flex items-center gap-3 px-6 py-4 border-b border-gray-100 bg-gray-50">
                <span className="text-gray-500">{icon}</span>
                <h2 className="text-sm font-semibold text-gray-800 tracking-tight">{title}</h2>
            </div>
            <div className="p-6">{children}</div>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------
export default function RLHFDashboard() {
    // Data state
    const [versions, setVersions] = useState<VersionStat[]>([]);
    const [abStatus, setAbStatus] = useState<any>(null);
    const [comparison, setComparison] = useState<any>(null);
    const [pairs, setPairs] = useState<any>(null);
    const [cycleResult, setCycleResult] = useState<any>(null);
    const [refineResult, setRefineResult] = useState<any>(null);

    // Loading flags
    const [loadingMain, setLoadingMain] = useState(true);
    const [loadingAction, setLoadingAction] = useState<string | null>(null);

    // UI state
    const [expandedVersion, setExpandedVersion] = useState<string | null>(null);
    const [abForm, setAbForm] = useState({ version_a: "", version_b: "", traffic_split: 0.5 });
    const [cycleVersion, setCycleVersion] = useState("");
    const [cycleMinRatings, setCycleMinRatings] = useState(50);
    const [refineVersion, setRefineVersion] = useState("");
    const [compareA, setCompareA] = useState("");
    const [compareB, setCompareB] = useState("");
    const [pairsVersion, setPairsVersion] = useState("");

    // Toasts
    const [toasts, setToasts] = useState<Toast[]>([]);
    const toastId = { current: 0 };

    function toast(type: Toast["type"], message: string) {
        const id = ++toastId.current;
        setToasts((prev) => [...prev, { id, type, message }]);
        setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 5000);
    }

    function removeToast(id: number) {
        setToasts((prev) => prev.filter((t) => t.id !== id));
    }

    // Load main data
    const loadData = useCallback(async () => {
        setLoadingMain(true);
        try {
            const [vData, abData] = await Promise.all([getPromptVersions(), getAbStatus()]);
            setVersions(vData.versions ?? []);
            setAbStatus(abData);
            // Pre-fill forms with sensible defaults
            const activeTag = vData.versions?.find((v: VersionStat) => v.is_active)?.version_tag ?? "";
            setCycleVersion(activeTag);
            setRefineVersion(activeTag);
        } catch (e: any) {
            toast("error", `Failed to load data: ${e.message}`);
        } finally {
            setLoadingMain(false);
        }
    }, []);

    useEffect(() => { loadData(); }, [loadData]);

    // ----------- Actions -----------

    async function handlePromote(version: string) {
        setLoadingAction(`promote-${version}`);
        try {
            await promoteVersion(version);
            toast("success", `Version ${version} promoted to active.`);
            await loadData();
        } catch (e: any) {
            toast("error", e.message);
        } finally {
            setLoadingAction(null);
        }
    }

    async function handleRollback(version: string) {
        if (!confirm(`Rollback from ${version} to its parent?`)) return;
        setLoadingAction(`rollback-${version}`);
        try {
            const res = await rollbackVersion(version);
            toast("success", `Rolled back to ${res.active_version}.`);
            await loadData();
        } catch (e: any) {
            toast("error", e.message);
        } finally {
            setLoadingAction(null);
        }
    }

    async function handleCreateAb() {
        if (!abForm.version_a || !abForm.version_b) {
            toast("error", "Both version A and B are required.");
            return;
        }
        setLoadingAction("create-ab");
        try {
            await createAbTest(abForm);
            toast("success", `A/B test started: ${abForm.version_a} vs ${abForm.version_b}`);
            await loadData();
        } catch (e: any) {
            toast("error", e.message);
        } finally {
            setLoadingAction(null);
        }
    }

    async function handleStopAb() {
        if (!confirm("Stop the current A/B test?")) return;
        setLoadingAction("stop-ab");
        try {
            await stopAbTest();
            toast("success", "A/B test stopped.");
            await loadData();
        } catch (e: any) {
            toast("error", e.message);
        } finally {
            setLoadingAction(null);
        }
    }

    async function handleRunCycle() {
        if (!cycleVersion) { toast("error", "Select a version first."); return; }
        setLoadingAction("run-cycle");
        setCycleResult(null);
        try {
            const res = await runRefinementCycle(cycleVersion, cycleMinRatings);
            setCycleResult(res);
            if (res.status === "refined") {
                toast("success", `New version ${res.details?.new_version} created!`);
                await loadData();
            } else {
                toast("info", `Cycle ${res.status}: ${res.reason}`);
            }
        } catch (e: any) {
            toast("error", e.message);
        } finally {
            setLoadingAction(null);
        }
    }

    async function handleRefine() {
        if (!refineVersion) { toast("error", "Select a version first."); return; }
        if (!confirm(`Force-run Claude refinement on ${refineVersion}? This bypasses guardrails and costs API tokens.`)) return;
        setLoadingAction("refine");
        setRefineResult(null);
        try {
            const res = await triggerRefinement(refineVersion);
            setRefineResult(res);
            if (res.status === "success") {
                toast("success", `New version ${res.new_version} created from ${refineVersion}!`);
                await loadData();
            } else {
                toast("info", `Refinement: ${res.reason ?? res.status}`);
            }
        } catch (e: any) {
            toast("error", e.message);
        } finally {
            setLoadingAction(null);
        }
    }

    async function handleCompare() {
        if (!compareA || !compareB) { toast("error", "Select both versions to compare."); return; }
        setLoadingAction("compare");
        try {
            const res = await compareVersions(compareA, compareB);
            setComparison(res);
        } catch (e: any) {
            toast("error", e.message);
        } finally {
            setLoadingAction(null);
        }
    }

    async function handleFetchPairs() {
        if (!pairsVersion) { toast("error", "Select a version."); return; }
        setLoadingAction("pairs");
        try {
            const res = await getPreferencePairs(pairsVersion);
            setPairs(res);
        } catch (e: any) {
            toast("error", e.message);
        } finally {
            setLoadingAction(null);
        }
    }

    // ----------- Rendering -----------

    const versionTags = versions.map((v) => v.version_tag);

    return (
        <div className="min-h-screen bg-gray-50 text-gray-900">
            <Toasts toasts={toasts} remove={removeToast} />

            {/* Top Nav */}
            <header className="bg-white border-b border-gray-200 sticky top-0 z-30">
                <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        <Link href="/" className="flex items-center gap-2 text-gray-500 hover:text-gray-800 transition-colors text-sm">
                            <ArrowLeft size={16} />
                            Chat
                        </Link>
                        <div className="w-px h-5 bg-gray-200" />
                        <div className="flex items-center gap-2">
                            <div className="w-7 h-7 rounded-lg bg-gray-900 flex items-center justify-center">
                                <Cpu size={14} className="text-white" />
                            </div>
                            <div>
                                <h1 className="text-sm font-semibold text-gray-900">RLHF Dashboard</h1>
                                <p className="text-[11px] text-gray-400">Prompt management & feedback loop</p>
                            </div>
                        </div>
                    </div>
                    <button
                        onClick={loadData}
                        disabled={loadingMain}
                        className="flex items-center gap-2 text-xs text-gray-600 hover:text-gray-900 border border-gray-200 px-3 py-1.5 rounded-lg hover:border-gray-400 transition-all disabled:opacity-50"
                    >
                        <RefreshCw size={13} className={loadingMain ? "animate-spin" : ""} />
                        Refresh
                    </button>
                </div>
            </header>

            <main className="max-w-7xl mx-auto px-6 py-8 space-y-6">

                {/* Summary stats strip */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {[
                        {
                            label: "Total Versions",
                            value: loadingMain ? "—" : versions.length,
                            icon: <Layers size={18} className="text-indigo-500" />,
                            bg: "bg-indigo-50",
                        },
                        {
                            label: "Active Version",
                            value: loadingMain ? "—" : (versions.find(v => v.is_active)?.version_tag ?? "none"),
                            icon: <CheckCircle size={18} className="text-emerald-500" />,
                            bg: "bg-emerald-50",
                        },
                        {
                            label: "Total Feedback",
                            value: loadingMain ? "—" : versions.reduce((s, v) => s + v.feedback_count, 0),
                            icon: <MessageSquare size={18} className="text-blue-500" />,
                            bg: "bg-blue-50",
                        },
                        {
                            label: "A/B Test",
                            value: loadingMain ? "—" : (abStatus?.active ? "Running" : "Off"),
                            icon: <FlaskConical size={18} className="text-purple-500" />,
                            bg: "bg-purple-50",
                        },
                    ].map((s) => (
                        <div key={s.label} className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm flex items-center gap-3">
                            <div className={`w-9 h-9 rounded-lg ${s.bg} flex items-center justify-center shrink-0`}>
                                {s.icon}
                            </div>
                            <div>
                                <p className="text-xs text-gray-500">{s.label}</p>
                                <p className="text-lg font-bold text-gray-900 leading-tight">{s.value}</p>
                            </div>
                        </div>
                    ))}
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

                    {/* ── Prompt Versions ── */}
                    <Card title="Prompt Versions" icon={<GitBranch size={16} />} className="lg:col-span-2">
                        {loadingMain ? (
                            <div className="space-y-3">
                                {[1, 2, 3].map((i) => (
                                    <div key={i} className="h-16 bg-gray-100 rounded-xl animate-pulse" />
                                ))}
                            </div>
                        ) : versions.length === 0 ? (
                            <p className="text-sm text-gray-400 text-center py-6">No versions found. Backend may need to be started.</p>
                        ) : (
                            <div className="space-y-2">
                                {versions.map((v) => (
                                    <div
                                        key={v.version_tag}
                                        className={`rounded-xl border transition-all ${v.is_active ? "border-emerald-200 bg-emerald-50/40" : "border-gray-200 bg-white hover:border-gray-300"}`}
                                    >
                                        {/* Header row */}
                                        <div
                                            className="flex items-center gap-3 px-4 py-3 cursor-pointer"
                                            onClick={() =>
                                                setExpandedVersion(expandedVersion === v.version_tag ? null : v.version_tag)
                                            }
                                        >
                                            <span className="font-mono font-bold text-sm text-gray-900 w-8">{v.version_tag}</span>
                                            <Badge active={v.is_active} />
                                            {v.parent_version && (
                                                <span className="text-[11px] text-gray-400">← {v.parent_version}</span>
                                            )}
                                            <div className="ml-auto flex items-center gap-4">
                                                <StarBar rating={v.avg_rating} />
                                                <span className="text-xs text-gray-400">{v.feedback_count} ratings</span>
                                                {expandedVersion === v.version_tag ? (
                                                    <ChevronUp size={14} className="text-gray-400" />
                                                ) : (
                                                    <ChevronDown size={14} className="text-gray-400" />
                                                )}
                                            </div>
                                        </div>

                                        {/* Expanded details */}
                                        {expandedVersion === v.version_tag && (
                                            <div className="px-4 pb-4 border-t border-gray-100 mt-1 pt-3 space-y-3">
                                                <div className="grid grid-cols-2 gap-4 text-xs text-gray-600">
                                                    <div>
                                                        <p className="text-gray-400 uppercase tracking-wider text-[10px] mb-1">File</p>
                                                        <code className="text-gray-700">{v.filename}</code>
                                                    </div>
                                                    <div>
                                                        <p className="text-gray-400 uppercase tracking-wider text-[10px] mb-1">Few-shots</p>
                                                        <p>{v.few_shot_count}</p>
                                                    </div>
                                                    <div>
                                                        <p className="text-gray-400 uppercase tracking-wider text-[10px] mb-1">Created</p>
                                                        <p>{v.created_at ? new Date(v.created_at).toLocaleString() : "—"}</p>
                                                    </div>
                                                    <div>
                                                        <p className="text-gray-400 uppercase tracking-wider text-[10px] mb-1">Parent</p>
                                                        <p>{v.parent_version ?? "baseline"}</p>
                                                    </div>
                                                </div>
                                                <div>
                                                    <p className="text-gray-400 uppercase tracking-wider text-[10px] mb-1">Rating Distribution</p>
                                                    <RatingDistBar dist={v.distribution} />
                                                </div>
                                                <div className="flex items-center gap-2 pt-1">
                                                    {!v.is_active && (
                                                        <button
                                                            onClick={() => handlePromote(v.version_tag)}
                                                            disabled={loadingAction === `promote-${v.version_tag}`}
                                                            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 transition-colors"
                                                        >
                                                            <ArrowUpCircle size={12} />
                                                            {loadingAction === `promote-${v.version_tag}` ? "Promoting..." : "Promote"}
                                                        </button>
                                                    )}
                                                    {v.parent_version && (
                                                        <button
                                                            onClick={() => handleRollback(v.version_tag)}
                                                            disabled={loadingAction === `rollback-${v.version_tag}`}
                                                            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-gray-100 text-gray-700 hover:bg-gray-200 disabled:opacity-50 transition-colors"
                                                        >
                                                            <RotateCcw size={12} />
                                                            {loadingAction === `rollback-${v.version_tag}` ? "Rolling back..." : "Rollback"}
                                                        </button>
                                                    )}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </Card>

                    {/* ── A/B Testing ── */}
                    <Card title="A/B Testing" icon={<FlaskConical size={16} />}>
                        {/* Current status */}
                        <div className="mb-5">
                            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Current Status</p>
                            {loadingMain ? (
                                <div className="h-10 bg-gray-100 rounded-lg animate-pulse" />
                            ) : abStatus?.active ? (
                                <div className="bg-purple-50 border border-purple-200 rounded-xl p-4">
                                    <div className="flex items-center justify-between mb-3">
                                        <span className="text-sm font-semibold text-purple-800">
                                            {abStatus.config.version_a} <span className="text-purple-400 mx-1">vs</span> {abStatus.config.version_b}
                                        </span>
                                        <span className="text-xs text-purple-600 font-mono">
                                            {Math.round(abStatus.config.traffic_split * 100)}% → A
                                        </span>
                                    </div>
                                    <div className="grid grid-cols-2 gap-3 text-xs mb-3">
                                        {["a", "b"].map((g) => {
                                            const stats = abStatus.stats?.[`version_${g}`];
                                            return (
                                                <div key={g} className="bg-white rounded-lg p-2.5 border border-purple-100">
                                                    <p className="font-mono font-bold text-gray-700 mb-1">
                                                        Group {g.toUpperCase()} — {g === "a" ? abStatus.config.version_a : abStatus.config.version_b}
                                                    </p>
                                                    <StarBar rating={stats?.avg_rating ?? 0} />
                                                    <p className="text-gray-400 mt-1">{stats?.count ?? 0} ratings</p>
                                                </div>
                                            );
                                        })}
                                    </div>
                                    <button
                                        onClick={handleStopAb}
                                        disabled={loadingAction === "stop-ab"}
                                        className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-red-100 text-red-700 hover:bg-red-200 disabled:opacity-50 transition-colors"
                                    >
                                        <StopCircle size={12} />
                                        {loadingAction === "stop-ab" ? "Stopping..." : "Stop Test"}
                                    </button>
                                </div>
                            ) : (
                                <p className="text-sm text-gray-400 bg-gray-50 rounded-xl px-4 py-3 border border-gray-200">
                                    No A/B test running.
                                </p>
                            )}
                        </div>

                        {/* Create new test */}
                        <div>
                            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Start New Test</p>
                            <div className="space-y-2">
                                <div className="grid grid-cols-2 gap-2">
                                    <div>
                                        <label className="block text-[11px] text-gray-500 mb-1">Version A</label>
                                        <select
                                            value={abForm.version_a}
                                            onChange={(e) => setAbForm({ ...abForm, version_a: e.target.value })}
                                            className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-gray-400 bg-white"
                                        >
                                            <option value="">Select...</option>
                                            {versionTags.map((t) => <option key={t} value={t}>{t}</option>)}
                                        </select>
                                    </div>
                                    <div>
                                        <label className="block text-[11px] text-gray-500 mb-1">Version B</label>
                                        <select
                                            value={abForm.version_b}
                                            onChange={(e) => setAbForm({ ...abForm, version_b: e.target.value })}
                                            className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-gray-400 bg-white"
                                        >
                                            <option value="">Select...</option>
                                            {versionTags.map((t) => <option key={t} value={t}>{t}</option>)}
                                        </select>
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-[11px] text-gray-500 mb-1">
                                        Traffic to A — {Math.round(abForm.traffic_split * 100)}%
                                    </label>
                                    <input
                                        type="range"
                                        min={0} max={1} step={0.05}
                                        value={abForm.traffic_split}
                                        onChange={(e) => setAbForm({ ...abForm, traffic_split: parseFloat(e.target.value) })}
                                        className="w-full accent-purple-600"
                                    />
                                </div>
                                <button
                                    onClick={handleCreateAb}
                                    disabled={loadingAction === "create-ab"}
                                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50 transition-colors"
                                >
                                    <Play size={12} />
                                    {loadingAction === "create-ab" ? "Creating..." : "Start A/B Test"}
                                </button>
                            </div>
                        </div>
                    </Card>

                    {/* ── Refinement ── */}
                    <Card title="Refinement Engine" icon={<Zap size={16} />}>
                        {/* Guided cycle */}
                        <div className="mb-6">
                            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Run Cycle (with guardrails)</p>
                            <div className="space-y-2">
                                <div className="grid grid-cols-2 gap-2">
                                    <div>
                                        <label className="block text-[11px] text-gray-500 mb-1">Base Version</label>
                                        <select
                                            value={cycleVersion}
                                            onChange={(e) => setCycleVersion(e.target.value)}
                                            className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-gray-400 bg-white"
                                        >
                                            <option value="">Select...</option>
                                            {versionTags.map((t) => <option key={t} value={t}>{t}</option>)}
                                        </select>
                                    </div>
                                    <div>
                                        <label className="block text-[11px] text-gray-500 mb-1">Min Ratings</label>
                                        <input
                                            type="number"
                                            min={1}
                                            value={cycleMinRatings}
                                            onChange={(e) => setCycleMinRatings(Number(e.target.value))}
                                            className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-gray-400"
                                        />
                                    </div>
                                </div>
                                <button
                                    onClick={handleRunCycle}
                                    disabled={!!loadingAction}
                                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-gray-900 text-white hover:bg-gray-700 disabled:opacity-50 transition-colors"
                                >
                                    <TrendingUp size={12} />
                                    {loadingAction === "run-cycle" ? "Running..." : "Run Cycle"}
                                </button>
                                {cycleResult && (
                                    <div className="rounded-xl border border-gray-200 bg-gray-50 p-3 text-xs space-y-1">
                                        <div className="flex items-center gap-2">
                                            <StatusChip status={cycleResult.status} />
                                            <span className="text-gray-600">{cycleResult.reason}</span>
                                        </div>
                                        {cycleResult.details && (
                                            <pre className="text-[10px] text-gray-400 overflow-auto max-h-32 mt-1 bg-white rounded-lg p-2 border border-gray-100">
                                                {JSON.stringify(cycleResult.details, null, 2)}
                                            </pre>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* Force refine */}
                        <div>
                            <div className="flex items-center gap-2 mb-2">
                                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Force Refine</p>
                                <span className="text-[10px] text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded font-semibold">Bypasses guardrails</span>
                            </div>
                            <div className="space-y-2">
                                <div>
                                    <label className="block text-[11px] text-gray-500 mb-1">Base Version</label>
                                    <select
                                        value={refineVersion}
                                        onChange={(e) => setRefineVersion(e.target.value)}
                                        className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-gray-400 bg-white"
                                    >
                                        <option value="">Select...</option>
                                        {versionTags.map((t) => <option key={t} value={t}>{t}</option>)}
                                    </select>
                                </div>
                                <button
                                    onClick={handleRefine}
                                    disabled={!!loadingAction}
                                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50 transition-colors"
                                >
                                    <AlertTriangle size={12} />
                                    {loadingAction === "refine" ? "Refining..." : "Force Refine"}
                                </button>
                                {refineResult && (
                                    <div className="rounded-xl border border-gray-200 bg-gray-50 p-3 text-xs space-y-2">
                                        <div className="flex items-center gap-2">
                                            <StatusChip status={refineResult.status} />
                                            {refineResult.new_version && (
                                                <span className="text-gray-600">Created <code className="font-mono">{refineResult.new_version}</code></span>
                                            )}
                                        </div>
                                        {refineResult.analysis && (
                                            <div>
                                                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-1">Claude's Analysis</p>
                                                <p className="text-gray-700">{refineResult.analysis}</p>
                                            </div>
                                        )}
                                        {refineResult.edits?.length > 0 && (
                                            <div>
                                                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-1">Edits ({refineResult.edits.length})</p>
                                                <div className="space-y-1 max-h-40 overflow-y-auto">
                                                    {refineResult.edits.map((e: any, i: number) => (
                                                        <div key={i} className="bg-white border border-gray-100 rounded-lg p-2">
                                                            <p className="font-semibold text-gray-700">{e.section}</p>
                                                            <p className="text-gray-500 mt-0.5">{e.rationale}</p>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>
                    </Card>

                    {/* ── Version Comparison ── */}
                    <Card title="Version Comparison" icon={<BarChart3 size={16} />}>
                        <div className="space-y-3">
                            <div className="grid grid-cols-2 gap-2">
                                <div>
                                    <label className="block text-[11px] text-gray-500 mb-1">Version A</label>
                                    <select
                                        value={compareA}
                                        onChange={(e) => setCompareA(e.target.value)}
                                        className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-gray-400 bg-white"
                                    >
                                        <option value="">Select...</option>
                                        {versionTags.map((t) => <option key={t} value={t}>{t}</option>)}
                                    </select>
                                </div>
                                <div>
                                    <label className="block text-[11px] text-gray-500 mb-1">Version B</label>
                                    <select
                                        value={compareB}
                                        onChange={(e) => setCompareB(e.target.value)}
                                        className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-gray-400 bg-white"
                                    >
                                        <option value="">Select...</option>
                                        {versionTags.map((t) => <option key={t} value={t}>{t}</option>)}
                                    </select>
                                </div>
                            </div>
                            <button
                                onClick={handleCompare}
                                disabled={loadingAction === "compare"}
                                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
                            >
                                <BarChart3 size={12} />
                                {loadingAction === "compare" ? "Comparing..." : "Compare"}
                            </button>

                            {comparison && (
                                <div className="space-y-3 mt-1">
                                    <div className="grid grid-cols-2 gap-2">
                                        {["version_a", "version_b"].map((key) => {
                                            const s = comparison[key];
                                            return (
                                                <div key={key} className="bg-gray-50 border border-gray-200 rounded-xl p-3">
                                                    <p className="text-xs font-bold text-gray-700 mb-2">{s.version}</p>
                                                    <StarBar rating={s.avg_rating} />
                                                    <p className="text-xs text-gray-400 mt-1">{s.count} ratings</p>
                                                    <RatingDistBar dist={s.distribution} />
                                                </div>
                                            );
                                        })}
                                    </div>
                                    <div className={`rounded-xl px-4 py-3 text-sm font-semibold flex items-center gap-2
                                        ${comparison.improvement > 0 ? "bg-emerald-50 text-emerald-800 border border-emerald-200" :
                                          comparison.improvement < 0 ? "bg-red-50 text-red-800 border border-red-200" :
                                          "bg-gray-50 text-gray-700 border border-gray-200"}`}
                                    >
                                        <TrendingUp size={14} />
                                        Winner: <code className="font-mono">{comparison.winner}</code>
                                        <span className="font-normal text-xs ml-auto">
                                            Δ {comparison.improvement > 0 ? "+" : ""}{comparison.improvement.toFixed(3)} avg rating
                                        </span>
                                    </div>
                                </div>
                            )}
                        </div>
                    </Card>

                    {/* ── Preference Pairs ── */}
                    <Card title="Preference Pairs" icon={<MessageSquare size={16} />}>
                        <div className="space-y-3">
                            <div>
                                <label className="block text-[11px] text-gray-500 mb-1">Version</label>
                                <select
                                    value={pairsVersion}
                                    onChange={(e) => setPairsVersion(e.target.value)}
                                    className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-gray-400 bg-white"
                                >
                                    <option value="">Select...</option>
                                    {versionTags.map((t) => <option key={t} value={t}>{t}</option>)}
                                </select>
                            </div>
                            <button
                                onClick={handleFetchPairs}
                                disabled={loadingAction === "pairs"}
                                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-gray-800 text-white hover:bg-gray-700 disabled:opacity-50 transition-colors"
                            >
                                <MessageSquare size={12} />
                                {loadingAction === "pairs" ? "Loading..." : "Load Pairs"}
                            </button>

                            {pairs && (
                                <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
                                    {pairs.count === 0 ? (
                                        <p className="text-xs text-gray-400 bg-gray-50 rounded-xl px-4 py-3 border border-gray-200">
                                            No preference pairs found. Collect more feedback with rating gaps ≥ 2.
                                        </p>
                                    ) : (
                                        <>
                                            <p className="text-xs text-gray-500">{pairs.count} pairs found</p>
                                            {pairs.pairs.map((p: any, i: number) => (
                                                <div key={i} className="border border-gray-200 rounded-xl overflow-hidden text-xs">
                                                    <div className="bg-gray-50 px-3 py-2 font-medium text-gray-700 border-b border-gray-200">
                                                        {p.query}
                                                    </div>
                                                    <div className="grid grid-cols-2 divide-x divide-gray-200">
                                                        <div className="p-3 bg-emerald-50">
                                                            <p className="font-semibold text-emerald-700 mb-1">✓ Chosen ({p.chosen.rating}★)</p>
                                                            <p className="text-gray-600 line-clamp-3">{p.chosen.response_summary}</p>
                                                            {p.chosen.correction && (
                                                                <p className="text-emerald-600 mt-1 italic">"{p.chosen.correction}"</p>
                                                            )}
                                                        </div>
                                                        <div className="p-3 bg-red-50">
                                                            <p className="font-semibold text-red-600 mb-1">✗ Rejected ({p.rejected.rating}★)</p>
                                                            <p className="text-gray-600 line-clamp-3">{p.rejected.response_summary}</p>
                                                        </div>
                                                    </div>
                                                </div>
                                            ))}
                                        </>
                                    )}
                                </div>
                            )}
                        </div>
                    </Card>

                </div>
            </main>
        </div>
    );
}
