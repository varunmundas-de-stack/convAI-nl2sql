"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Target, ChevronRight, ArrowLeft, CheckCircle, Loader2, MessageSquare, Zap } from "lucide-react";
import Link from "next/link";
import {
    getMe, getAccessToken,
    listObjectives, getObjective, saveObjectiveResponse,
    PersonaObjectiveSummary, PersonaObjectiveFull,
} from "@/services/api";

type Phase = "list" | "questions" | "done";

export default function ObjectivesPage() {
    const router = useRouter();
    const [user, setUser] = useState<any>(null);
    const [authReady, setAuthReady] = useState(false);

    const [phase, setPhase] = useState<Phase>("list");
    const [objectives, setObjectives] = useState<PersonaObjectiveSummary[]>([]);
    const [selected, setSelected] = useState<PersonaObjectiveFull | null>(null);
    const [answers, setAnswers] = useState<Record<string, string>>({});
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [savedTitle, setSavedTitle] = useState("");
    const [sessionId, setSessionId] = useState("");

    useEffect(() => {
        const tok = getAccessToken();
        if (!tok) { setAuthReady(true); return; }
        getMe().then(d => setUser(d.user)).catch(() => {}).finally(() => setAuthReady(true));
        listObjectives()
            .then(d => setObjectives(d.objectives))
            .catch(() => {})
            .finally(() => setLoading(false));
    }, []);

    if (!authReady) return null;
    if (!user) return (
        <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: "#0F2044" }}>
            <Link href="/" className="px-6 py-2 text-sm bg-orange-500 text-white rounded-xl">Go to Chat</Link>
        </div>
    );

    async function selectObjective(id: string) {
        setLoading(true);
        try {
            const obj = await getObjective(id);
            setSelected(obj);
            const defaults: Record<string, string> = {};
            obj.questions.forEach(q => { if (q.options[0]) defaults[q.id] = q.options[0].value; });
            setAnswers(defaults);
            setPhase("questions");
        } catch {}
        finally { setLoading(false); }
    }

    async function saveObjective() {
        if (!selected) return;
        setSaving(true);
        try {
            const r = await saveObjectiveResponse(selected.id, answers);
            setSavedTitle(r.title);
            setSessionId(r.session_id);
            setPhase("done");
        } catch {}
        finally { setSaving(false); }
    }

    function startChat() {
        sessionStorage.setItem("suggested_query", `I have set my objective: ${savedTitle}. Based on my choices, what should I focus on first?`);
        router.push("/");
    }

    return (
        <div className="min-h-screen" style={{ backgroundColor: "#0F2044", backgroundImage: "radial-gradient(circle, rgba(255,255,255,0.06) 1px, transparent 1px)", backgroundSize: "28px 28px" }}>
            <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
                <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        <div className="flex items-center gap-2.5">
                            <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: "linear-gradient(135deg,#6366f1,#f97316)" }}>
                                <Target size={14} className="text-white" />
                            </div>
                            <div>
                                <h1 className="text-sm font-bold text-gray-900">Objectives</h1>
                                <p className="text-[10px] text-gray-400">Set your focus for this session</p>
                            </div>
                        </div>
                        <nav className="flex items-center gap-1 bg-gray-100 rounded-xl p-1 ml-2">
                            <Link href="/" className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-500 hover:text-gray-900 hover:bg-white/60 transition-colors">Chat</Link>
                            <Link href="/dashboard" className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-500 hover:text-gray-900 hover:bg-white/60 transition-colors">Dashboard</Link>
                            <Link href="/insights" className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-500 hover:text-gray-900 hover:bg-white/60 transition-colors">Insights</Link>
                            <Link href="/actions" className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-500 hover:text-gray-900 hover:bg-white/60 transition-colors">Actions</Link>
                            <span className="px-3 py-1.5 rounded-lg text-sm font-medium bg-white text-gray-900 shadow-sm">Objectives</span>
                        </nav>
                    </div>
                </div>
            </header>

            <div className="max-w-4xl mx-auto px-6 py-10">
                {/* List phase */}
                {phase === "list" && (
                    <>
                        <p className="text-sm text-white/50 mb-6">Choose an objective for this session. Your answers will shape every response CPG-Analyst gives you.</p>
                        {loading ? (
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                {[0,1,2,3].map(i => <div key={i} className="bg-white/5 rounded-2xl p-5 animate-pulse h-28" />)}
                            </div>
                        ) : (
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                {objectives.map(o => (
                                    <button key={o.id} onClick={() => selectObjective(o.id)}
                                        className="text-left bg-white rounded-2xl p-5 shadow hover:shadow-md border border-gray-100 hover:border-indigo-200 transition-all group">
                                        <div className="flex items-start gap-3">
                                            <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0" style={{ background: "linear-gradient(135deg,#6366f1,#f97316)" }}>
                                                <Target size={15} className="text-white" />
                                            </div>
                                            <div className="flex-1">
                                                <h3 className="text-sm font-semibold text-gray-900">{o.title}</h3>
                                                <p className="text-xs text-gray-400 mt-0.5">{o.description}</p>
                                                <p className="text-[10px] text-indigo-400 mt-2">{o.question_count} questions to define your strategy</p>
                                            </div>
                                            <ChevronRight size={14} className="text-gray-300 group-hover:text-indigo-500 mt-1 transition-colors" />
                                        </div>
                                    </button>
                                ))}
                            </div>
                        )}
                    </>
                )}

                {/* Questions phase */}
                {phase === "questions" && selected && (
                    <div className="max-w-lg mx-auto">
                        <button onClick={() => setPhase("list")} className="flex items-center gap-1.5 text-white/40 hover:text-white/70 text-sm mb-6 transition-colors">
                            <ArrowLeft size={14} /> Back to objectives
                        </button>
                        <div className="bg-white rounded-2xl shadow-xl p-6">
                            <div className="flex items-center gap-3 mb-5">
                                <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: "linear-gradient(135deg,#6366f1,#f97316)" }}>
                                    <Target size={16} className="text-white" />
                                </div>
                                <div>
                                    <h2 className="text-base font-bold text-gray-900">{selected.title}</h2>
                                    <p className="text-xs text-gray-400">{selected.description}</p>
                                </div>
                            </div>

                            <div className="space-y-6">
                                {selected.questions.map((q, qi) => (
                                    <div key={q.id}>
                                        <p className="text-sm font-semibold text-gray-700 mb-2">{qi + 1}. {q.text}</p>
                                        <div className="grid grid-cols-1 gap-2">
                                            {q.options.map(opt => (
                                                <button key={opt.value}
                                                    onClick={() => setAnswers(a => ({ ...a, [q.id]: opt.value }))}
                                                    className={`px-4 py-2.5 rounded-lg text-sm text-left border transition-all ${answers[q.id] === opt.value ? "bg-indigo-50 border-indigo-400 text-indigo-800 font-medium" : "border-gray-200 text-gray-600 hover:border-indigo-200"}`}>
                                                    {answers[q.id] === opt.value && <CheckCircle size={12} className="inline mr-2 text-indigo-500" />}
                                                    {opt.label}
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                ))}
                            </div>

                            <button onClick={saveObjective} disabled={saving}
                                className="w-full mt-6 flex items-center justify-center gap-2 py-3 px-4 rounded-xl text-sm font-semibold text-white transition-all disabled:opacity-60"
                                style={{ background: "linear-gradient(135deg,#6366f1,#f97316)" }}>
                                {saving ? <><Loader2 size={14} className="animate-spin" /> Saving...</> : <>Set Objective <ChevronRight size={14} /></>}
                            </button>
                        </div>
                    </div>
                )}

                {/* Done phase */}
                {phase === "done" && (
                    <div className="max-w-lg mx-auto">
                        <div className="bg-white rounded-2xl shadow-xl p-8 text-center">
                            <CheckCircle size={48} className="text-emerald-500 mx-auto mb-4" />
                            <h2 className="text-xl font-bold text-gray-900 mb-2">Objective Set!</h2>
                            <p className="text-sm text-gray-500 mb-2">
                                <span className="font-semibold text-indigo-600">{savedTitle}</span> is now active.
                            </p>
                            <p className="text-xs text-gray-400 mb-6">CPG-Analyst will use this objective to give you focused, relevant responses. You can change it anytime.</p>
                            <div className="space-y-3">
                                <button onClick={startChat}
                                    className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl text-sm font-semibold text-white"
                                    style={{ background: "linear-gradient(135deg,#6366f1,#f97316)" }}>
                                    <MessageSquare size={14} /> Start Chat with this Objective
                                </button>
                                <button onClick={() => setPhase("list")}
                                    className="w-full py-2.5 px-4 rounded-xl text-sm font-medium text-gray-500 hover:bg-gray-50 border border-gray-200">
                                    Choose a Different Objective
                                </button>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
