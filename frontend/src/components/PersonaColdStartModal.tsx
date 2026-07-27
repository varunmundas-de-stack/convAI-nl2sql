"use client";

import { useEffect, useState } from "react";
import { Sliders, ChevronRight, Check } from "lucide-react";
import { getPersonaColdStart, savePersonaPreferences, PersonaColdStartQuestion } from "@/services/api";

type Props = {
    username: string;
    onDone: (answers: Record<string, string>) => void;
};

const STORAGE_KEY = (u: string) => `cold_start_done_${u}`;

export function isColdStartDone(username: string): boolean {
    if (typeof window === "undefined") return true;
    return !!localStorage.getItem(STORAGE_KEY(username));
}

export default function PersonaColdStartModal({ username, onDone }: Props) {
    const [questions, setQuestions] = useState<PersonaColdStartQuestion[]>([]);
    const [step, setStep] = useState(0);
    const [answers, setAnswers] = useState<Record<string, string>>({});
    const [loading, setLoading] = useState(true);
    const [done, setDone] = useState(false);

    useEffect(() => {
        getPersonaColdStart()
            .then((d) => {
                setQuestions(d.questions);
                const defaults: Record<string, string> = {};
                d.questions.forEach((q) => { if (q.default) defaults[q.preference_id] = q.default; });
                setAnswers(defaults);
            })
            .catch(() => {
                // API failed — call onDone without writing localStorage so it retries next session
                onDone({});
            })
            .finally(() => setLoading(false));
    }, []);

    function markDone(finalAnswers: Record<string, string>) {
        localStorage.setItem(STORAGE_KEY(username), JSON.stringify(finalAnswers));
        savePersonaPreferences(finalAnswers).catch(() => {}); // fire-and-forget
        onDone(finalAnswers);
    }

    function handleSelect(prefId: string, value: string) {
        setAnswers((prev) => ({ ...prev, [prefId]: value }));
    }

    function handleNext() {
        if (step < questions.length - 1) {
            setStep(step + 1);
        } else {
            setDone(true);
            setTimeout(() => markDone(answers), 800);
        }
    }

    if (loading) return null;
    if (questions.length === 0) return null;

    const q = questions[step];

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm px-4">
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden">
                <div className="px-5 py-4 border-b border-gray-100 flex items-center gap-2">
                    <Sliders size={16} className="text-indigo-500" />
                    <span className="text-sm font-semibold text-gray-900">Quick setup</span>
                    <span className="ml-auto text-xs text-gray-400">{step + 1} / {questions.length}</span>
                </div>

                <div className="p-5 min-h-[180px]">
                    {done ? (
                        <div className="flex flex-col items-center gap-3 py-6 text-center">
                            <div className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center">
                                <Check size={18} className="text-emerald-600" />
                            </div>
                            <p className="text-sm text-gray-700 font-medium">Preferences saved!</p>
                        </div>
                    ) : (
                        <div className="flex flex-col gap-3">
                            <p className="text-sm font-medium text-gray-900">{q.question_text}</p>
                            <div className="flex flex-col gap-2">
                                {q.options.map((opt) => (
                                    <button
                                        key={opt.value}
                                        onClick={() => handleSelect(q.preference_id, opt.value)}
                                        className="text-left px-3 py-2.5 rounded-lg border text-sm transition-colors"
                                        style={
                                            answers[q.preference_id] === opt.value
                                                ? { borderColor: "#6366F1", backgroundColor: "#EEF2FF", color: "#3730A3" }
                                                : { borderColor: "#E5E7EB", color: "#374151" }
                                        }
                                    >
                                        {opt.label}
                                    </button>
                                ))}
                            </div>
                            <div className="flex items-center justify-between mt-2">
                                <button
                                    onClick={() => markDone(answers)}
                                    className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
                                >
                                    Skip for now
                                </button>
                                <button
                                    onClick={handleNext}
                                    disabled={!answers[q.preference_id]}
                                    className="flex items-center gap-1 px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium disabled:opacity-40 hover:bg-indigo-700 transition-colors"
                                >
                                    {step < questions.length - 1 ? (
                                        <><span>Next</span><ChevronRight size={14} /></>
                                    ) : (
                                        <><span>Done</span><Check size={14} /></>
                                    )}
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
