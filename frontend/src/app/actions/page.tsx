"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Zap, ArrowRight, Map, Package, Users, TrendingUp, ChevronRight, CheckCircle, Circle, Loader2, MessageSquare, X } from "lucide-react";
import Link from "next/link";
import { getMe, getAccessToken, sendQuery } from "@/services/api";
import {
    ACTION_PIPELINES, ActionPipeline, ActiveAction,
    getActiveAction, saveActiveAction, clearActiveAction, serializeActionContext,
} from "@/lib/actionPipelines";

const ICON_MAP: Record<string, React.ElementType> = {
    Map, Package, Users, TrendingUp, Zap,
};

export default function ActionsPage() {
    const router = useRouter();
    const [user, setUser] = useState<any>(null);
    const [authReady, setAuthReady] = useState(false);
    const [activeAction, setActiveAction] = useState<ActiveAction | null>(null);
    const [stepLoading, setStepLoading] = useState(false);
    const [stepResult, setStepResult] = useState<string | null>(null);
    const [stepError, setStepError] = useState(false);
    const [selectValues, setSelectValues] = useState<Record<string, string>>({});

    useEffect(() => {
        const tok = getAccessToken();
        if (!tok) { setAuthReady(true); return; }
        getMe().then(d => setUser(d.user)).catch(() => {}).finally(() => setAuthReady(true));
        setActiveAction(getActiveAction());
    }, []);

    if (!authReady) return null;
    if (!user) return (
        <div className="min-h-screen flex flex-col items-center justify-center gap-4" style={{ backgroundColor: "#0F2044" }}>
            <p className="text-white">You need to be signed in.</p>
            <Link href="/" className="px-6 py-2 text-sm bg-orange-500 text-white rounded-xl">Go to Chat</Link>
        </div>
    );

    const pipeline = activeAction ? ACTION_PIPELINES.find(p => p.id === activeAction.pipelineId) : null;
    const currentStep = pipeline ? pipeline.steps[activeAction!.currentStep] : null;

    function startAction(p: ActionPipeline) {
        const a: ActiveAction = { pipelineId: p.id, currentStep: 0, stepData: {}, startedAt: Date.now() };
        saveActiveAction(a);
        setActiveAction(a);
        setStepResult(null);
    }

    function cancelAction() {
        clearActiveAction();
        setActiveAction(null);
        setStepResult(null);
    }

    async function runStep() {
        if (!activeAction || !pipeline || !currentStep) return;
        setStepLoading(true);
        setStepError(false);
        setStepResult(null);

        // If this step has a select input, save its value
        const updatedData = { ...activeAction.stepData };
        if (currentStep.inputType === "select") {
            const val = selectValues[currentStep.id] || currentStep.options?.[0]?.value || "";
            updatedData[currentStep.inputLabel || currentStep.id] = val;
        }

        if (currentStep.inputType === "none" && currentStep.query) {
            try {
                const r = await sendQuery(currentStep.query);
                const narrative: string = (r?.raw as any)?.narrative || "";
                const rows: any[] = (r?.raw as any)?.visual_spec?.data?.rows || (r?.raw as any)?.visual_spec?.data || [];
                if (narrative) {
                    setStepResult(narrative);
                } else if (rows.length > 0) {
                    setStepResult(`Found ${rows.length} records. Key data: ` + rows.slice(0, 3).map(row => Object.values(row).slice(0, 2).join(": ")).join(" | "));
                } else {
                    setStepResult("Analysis complete — no critical issues detected for this period.");
                }
            } catch {
                setStepError(true);
                setStepResult("Unable to fetch live data. You can still proceed.");
            }
        } else {
            setStepResult(`Selection saved: ${Object.values(updatedData).join(", ")}`);
        }

        const newStep = activeAction.currentStep + 1;
        const updated: ActiveAction = { ...activeAction, currentStep: newStep, stepData: updatedData };
        saveActiveAction(updated);
        setActiveAction(updated);
        setStepLoading(false);
    }

    function finishAction() {
        if (!activeAction || !pipeline) return;
        const context = serializeActionContext(activeAction);
        sessionStorage.setItem("suggested_query", `[Action complete: ${pipeline.label}]\n${context}\n\nPlease summarize findings and next steps.`);
        clearActiveAction();
        router.push("/");
    }

    const isDone = activeAction && pipeline && activeAction.currentStep >= pipeline.steps.length;

    return (
        <div className="min-h-screen" style={{ backgroundColor: "#0F2044", backgroundImage: "radial-gradient(circle, rgba(255,255,255,0.06) 1px, transparent 1px)", backgroundSize: "28px 28px" }}>
            <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
                <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        <div className="flex items-center gap-2.5">
                            <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: "linear-gradient(135deg,#6366f1,#f97316)" }}>
                                <Zap size={14} className="text-white" />
                            </div>
                            <div>
                                <h1 className="text-sm font-bold text-gray-900">Recommended Actions</h1>
                                <p className="text-[10px] text-gray-400">{activeAction ? `Running: ${pipeline?.label}` : "Choose an action to run"}</p>
                            </div>
                        </div>
                        <nav className="flex items-center gap-1 bg-gray-100 rounded-xl p-1 ml-2">
                            <Link href="/" className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-500 hover:text-gray-900 hover:bg-white/60 transition-colors">Chat</Link>
                            <Link href="/dashboard" className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-500 hover:text-gray-900 hover:bg-white/60 transition-colors">Dashboard</Link>
                            <Link href="/insights" className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-500 hover:text-gray-900 hover:bg-white/60 transition-colors">Insights</Link>
                            <span className="px-3 py-1.5 rounded-lg text-sm font-medium bg-white text-gray-900 shadow-sm">Actions</span>
                        </nav>
                    </div>
                </div>
            </header>

            <div className="max-w-5xl mx-auto px-6 py-10">
                {/* Action picker */}
                {!activeAction && (
                    <>
                        <p className="text-sm text-white/50 mb-6">Select an action pipeline to run a guided analysis. Results feed directly into Chat.</p>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                            {ACTION_PIPELINES.map(p => {
                                const Icon = ICON_MAP[p.icon] ?? Zap;
                                return (
                                    <button key={p.id} onClick={() => startAction(p)}
                                        className="text-left bg-white rounded-2xl p-5 shadow hover:shadow-md transition-all group border border-gray-100 hover:border-indigo-200">
                                        <div className="flex items-start gap-3">
                                            <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0" style={{ background: "linear-gradient(135deg,#6366f1,#f97316)" }}>
                                                <Icon size={15} className="text-white" />
                                            </div>
                                            <div className="flex-1">
                                                <h3 className="text-sm font-semibold text-gray-900">{p.label}</h3>
                                                <p className="text-xs text-gray-400 mt-0.5">{p.description}</p>
                                                <p className="text-[10px] text-indigo-400 mt-2">{p.steps.length} steps</p>
                                            </div>
                                            <ArrowRight size={14} className="text-gray-300 group-hover:text-indigo-500 mt-1 transition-colors" />
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                    </>
                )}

                {/* Active pipeline workspace */}
                {activeAction && pipeline && (
                    <div className="max-w-2xl mx-auto">
                        {/* Progress bar */}
                        <div className="mb-6">
                            <div className="flex items-center justify-between mb-2">
                                <span className="text-white/70 text-sm font-semibold">{pipeline.label}</span>
                                <button onClick={cancelAction} className="text-white/30 hover:text-white/60 text-xs flex items-center gap-1"><X size={12} /> Cancel</button>
                            </div>
                            <div className="flex items-center gap-2">
                                {pipeline.steps.map((s, i) => (
                                    <div key={s.id} className="flex items-center gap-2 flex-1">
                                        <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 text-xs font-bold ${i < activeAction.currentStep ? "bg-emerald-500 text-white" : i === activeAction.currentStep ? "bg-indigo-500 text-white" : "bg-white/10 text-white/30"}`}>
                                            {i < activeAction.currentStep ? <CheckCircle size={14} /> : i + 1}
                                        </div>
                                        {i < pipeline.steps.length - 1 && <div className={`h-0.5 flex-1 rounded ${i < activeAction.currentStep ? "bg-emerald-500" : "bg-white/10"}`} />}
                                    </div>
                                ))}
                            </div>
                            <div className="flex justify-between mt-1">
                                {pipeline.steps.map((s, i) => (
                                    <span key={s.id} className={`text-[10px] ${i === activeAction.currentStep ? "text-white/70" : "text-white/25"}`}>{s.title}</span>
                                ))}
                            </div>
                        </div>

                        {/* Done state */}
                        {isDone ? (
                            <div className="bg-white rounded-2xl p-6 text-center shadow-xl">
                                <CheckCircle size={40} className="text-emerald-500 mx-auto mb-3" />
                                <h2 className="text-lg font-bold text-gray-900 mb-2">{pipeline.label} Complete</h2>
                                <p className="text-sm text-gray-500 mb-5">All {pipeline.steps.length} steps finished. Take the findings to Chat for a full summary.</p>
                                <button onClick={finishAction}
                                    className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl text-sm font-semibold text-white transition-all"
                                    style={{ background: "linear-gradient(135deg, #6366f1, #f97316)" }}>
                                    <MessageSquare size={15} />
                                    Send to Chat for Summary
                                </button>
                            </div>
                        ) : currentStep && (
                            <div className="bg-white rounded-2xl p-6 shadow-xl">
                                <p className="text-xs text-indigo-500 font-semibold uppercase tracking-widest mb-1">Step {activeAction.currentStep + 1} of {pipeline.steps.length}</p>
                                <h2 className="text-lg font-bold text-gray-900 mb-1">{currentStep.title}</h2>
                                <p className="text-sm text-gray-500 mb-5">{currentStep.description}</p>

                                {/* Select input */}
                                {currentStep.inputType === "select" && currentStep.options && (
                                    <div className="mb-5">
                                        <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">{currentStep.inputLabel}</label>
                                        <div className="grid grid-cols-2 gap-2">
                                            {currentStep.options.map(opt => (
                                                <button key={opt.value}
                                                    onClick={() => setSelectValues(v => ({ ...v, [currentStep.id]: opt.value }))}
                                                    className={`px-3 py-2 rounded-lg text-sm font-medium border transition-all text-left ${(selectValues[currentStep.id] || currentStep.options![0].value) === opt.value ? "bg-indigo-50 border-indigo-300 text-indigo-700" : "border-gray-200 text-gray-600 hover:border-indigo-200"}`}>
                                                    {opt.label}
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {/* Result */}
                                {stepResult && (
                                    <div className={`rounded-xl p-4 mb-5 text-sm ${stepError ? "bg-rose-50 text-rose-700 border border-rose-200" : "bg-emerald-50 text-emerald-800 border border-emerald-200"}`}>
                                        <p className="font-semibold text-xs uppercase tracking-wide mb-1">{stepError ? "Warning" : "Result"}</p>
                                        {stepResult}
                                    </div>
                                )}

                                <button onClick={runStep} disabled={stepLoading}
                                    className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl text-sm font-semibold text-white transition-all disabled:opacity-60"
                                    style={{ background: "linear-gradient(135deg, #6366f1, #f97316)" }}>
                                    {stepLoading ? <><Loader2 size={15} className="animate-spin" /> Running...</> : <>{stepResult ? "Next Step" : currentStep.inputType === "none" ? "Run Analysis" : "Confirm & Continue"} <ChevronRight size={15} /></>}
                                </button>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
