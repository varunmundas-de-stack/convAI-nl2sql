"use client";

interface ClarificationPromptProps {
    question: string;
    allowed_values?: string[];
    missing_fields?: string[];
    onClarify?: (value: string) => void;
}

export default function ClarificationPrompt({
    question,
    allowed_values,
    missing_fields,
    onClarify,
}: ClarificationPromptProps) {
    return (
        <div className="rounded-xl border border-blue-100 bg-blue-50/60 px-5 py-4 space-y-3">

            {/* Question */}
            <p className="text-sm font-semibold text-gray-800 leading-snug">
                {question || "Could you clarify a few details?"}
            </p>

            {/* Chip buttons when allowed_values provided */}
            {allowed_values && allowed_values.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                    {allowed_values.map((val: string) => (
                        <button
                            key={val}
                            onClick={() => onClarify && onClarify(val)}
                            className="px-4 py-1.5 rounded-full text-xs font-semibold border border-blue-300 bg-white text-blue-700 hover:bg-blue-600 hover:text-white hover:border-blue-600 shadow-sm transition-all duration-150"
                        >
                            {val.replace(/_/g, " ")}
                        </button>
                    ))}
                </div>
            ) : (
                /* Fallback hint when no allowed_values */
                !question && (
                    <div className="text-xs text-gray-500 space-y-0.5">
                        <div>• For <strong>time_dimension</strong>: Enter granularity (e.g., "day", "month", "year")</div>
                        <div>• For <strong>time_range</strong>: Enter window (e.g., "last 30 days", "last 1 year")</div>
                        <div>• For multiple fields: Separate with commas (e.g., "month, last 30 days")</div>
                    </div>
                )
            )}

            {/* Missing fields hint — subtle, only when no chips */}
            {(!allowed_values || allowed_values.length === 0) && missing_fields && missing_fields.length > 0 && (
                <p className="text-xs text-gray-400">
                    Missing: {missing_fields.join(", ")}
                </p>
            )}
        </div>
    );
}
