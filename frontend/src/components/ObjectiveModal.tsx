"use client";

import { useEffect, useState } from "react";
import { Target, X, ChevronRight, Check } from "lucide-react";
import {
    getObjectiveTemplates, getObjectiveTemplate, saveObjective,
    ObjectiveTemplate,
} from "@/services/api";

type Props = {
    onClose: () => void;
    onSaved: (result: { session_id: string; title: string; answers: Record<string, string> }) => void;
};

export default function ObjectiveModal({ onClose, onSaved }: Props) {
    const [templates, setTemplates] = useState<ObjectiveTemplate[]>([]);
    const [activeTemplate, setActiveTemplate] = useState<ObjectiveTemplate | null>(null);
    const [answers, setAnswers] = useState<Record<string, string>>({});
    const [step, setStep] = useState(0);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [summary, setSummary] = useState<{ session_id: string; title: string; answers: Record<string, string> } | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        getObjectiveTemplates()
            .then((d) => setTemplates(d.templates || []))
            .catch(() => setError("Could not load objectives"))
            .finally(() => setLoading(false));
    }, []);

    async function pickTemplate(templateId: string) {
        setLoading(true);
        try {
            const full = await getObjectiveTemplate(templateId);
            setActiveTemplate(full);
            setStep(0);
            setAnswers({});
        } catch {
            setError("Could not load that objective");
        } finally {
            setLoading(false);
        }
    }

    function selectAnswer(questionId: string, value: string) {
        setAnswers((prev) => ({ ...prev, [questionId]: value }));
    }

    async function handleNext() {
        if (!activeTemplate?.questions) return;
        if (step < activeTemplate.questions.length - 1) {
            setStep(step + 1);
            return;
        }
        setSaving(true);
        setError(null);
        try {
            const result = await saveObjective({
                template_id: activeTemplate.template_id,
                answers,
                title: activeTemplate.title,
            });
            setSummary({ session_id: result.session_id, title: activeTemplate.title, answers });
        } catch {
            setError("Could not save objective. Try again.");
        } finally {
            setSaving(false);
        }
    }

    const question = activeTemplate?.questions?.[step];

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm px-4">
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden">
                <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
                    <div className="flex items-center gap-2">
                        <Target size={18} className="text-indigo-500" />
                        <span className="font-semibold text-gray-900 text-sm">
                            {summary ? "Objective set" : "Set your objective"}
                        </span>
                    </div>
                    <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 text-gray-400">
                        <X size={16} />
                    </button>
                </div>

                <div className="p-5 min-h-[180px]">
                    {error && <p className="text-xs text-red-500 mb-3">{error}</p>}

                    {summary ? (
                        <div className="flex flex-col items-center text-center gap-3 py-4">
                            <div className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center">
                                <Check size={18} className="text-emerald-600" />
                            </div>
                            <p className="text-sm text-gray-700">
                                <span className="font-semibold">{summary.title}</span> is ready.
                            </p>
                            <button
                                onClick={() => onSaved(summary)}
                                className="mt-2 px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors"
                            >
                                Start chatting
                            </button>
                        </div>
                    ) : loading ? (
                        <p className="text-xs text-gray-400">Loading…</p>
                    ) : !activeTemplate ? (
                        <div className="flex flex-col gap-2">
                            {templates.length === 0 && (
                                <p className="text-xs text-gray-400">No objectives available for your role yet.</p>
                            )}
                            {templates.map((t) => (
                                <button
                                    key={t.template_id}
                                    onClick={() => pickTemplate(t.template_id)}
                                    className="flex items-center justify-between text-left px-3 py-2.5 rounded-lg border border-gray-200 hover:border-indigo-300 hover:bg-indigo-50 transition-colors"
                                >
                                    <div>
                                        <div className="text-sm font-medium text-gray-900">{t.title}</div>
                                        {t.description && (
                                            <div className="text-xs text-gray-500 mt-0.5">{t.description}</div>
                                        )}
                                    </div>
                                    <ChevronRight size={14} className="text-gray-400 shrink-0" />
                                </button>
                            ))}
                        </div>
                    ) : question ? (
                        <div className="flex flex-col gap-3">
                            <div className="text-xs text-gray-400">
                                Step {step + 1} of {activeTemplate.questions!.length}
                            </div>
                            <p className="text-sm font-medium text-gray-900">{question.question_text}</p>
                            <div className="flex flex-col gap-2">
                                {question.options.map((opt) => (
                                    <button
                                        key={opt.option_id}
                                        onClick={() => selectAnswer(question.question_id, opt.value)}
                                        className="text-left px-3 py-2 rounded-lg border text-sm transition-colors"
                                        style={
                                            answers[question.question_id] === opt.value
                                                ? { borderColor: "#6366F1", backgroundColor: "#EEF2FF", color: "#3730A3" }
                                                : { borderColor: "#E5E7EB", color: "#374151" }
                                        }
                                    >
                                        {opt.label}
                                    </button>
                                ))}
                            </div>
                            <button
                                onClick={handleNext}
                                disabled={!answers[question.question_id] || saving}
                                className="mt-2 self-end px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium disabled:opacity-40 hover:bg-indigo-700 transition-colors"
                            >
                                {saving ? "Saving…" : step < activeTemplate.questions!.length - 1 ? "Next" : "Save"}
                            </button>
                        </div>
                    ) : null}
                </div>
            </div>
        </div>
    );
}
