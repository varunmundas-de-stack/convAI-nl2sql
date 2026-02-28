"use client";

import { ChatMessage, ChatResponse } from "@/types/chat";
import TableRenderer from "./TableRenderer";
import ChartRenderer from "./ChartRenderer";
import ClarificationPrompt from "./ClarificationPrompt";

interface MessageBubbleProps {
    message: ChatMessage;
    responseData?: ChatResponse;
    onClarify?: (value: string) => void;
}

export default function MessageBubble({ message, responseData, onClarify }: MessageBubbleProps) {
    const isUser = message.role === "user";
    const isSystem = message.role === "system";

    // Determine container classes based on role
    // User: standard bubble, right aligned
    // System: warning/notice style
    // Assistant: full width, card style, ample padding
    const containerClasses = isUser
        ? "max-w-[80%] bg-blue-600 text-white rounded-2xl rounded-tr-none px-5 py-4 shadow-sm"
        : isSystem
            ? "max-w-[90%] bg-yellow-50 text-yellow-900 border border-yellow-200 rounded-lg px-4 py-3"
            : "w-full bg-gray-50 text-gray-900 border border-gray-200 rounded-xl px-8 py-8 shadow-sm"; // Full width, gray canvas for contrast

    const alignClasses = isUser ? "justify-end" : "justify-start";

    return (
        <div className={`flex ${alignClasses} mb-6`}>
            <div className={containerClasses}>
                {/* Text content */}
                {message.content && (
                    <div className={`whitespace-pre-wrap break-words ${!isUser ? "text-lg leading-relaxed text-gray-800" : ""}`}>
                        {message.content}
                    </div>
                )}

                {/* Response data rendering */}
                {!isUser && responseData && (
                    <div className="mt-8 space-y-8"> {/* Ample vertical spacing */}
                        {responseData.type === "table" && <TableRenderer data={responseData} />}
                        {responseData.type === "chart" && (
                            <ChartRenderer
                                visual_spec={responseData.data?.visual_spec}
                                refined_insights={responseData.data?.refined_insights}
                            />
                        )}
                        {responseData.type === "clarification_required" && (
                            <ClarificationPrompt
                                question={responseData.question}
                                allowed_values={responseData.allowed_values}
                                missing_fields={responseData.missing_fields}
                                onClarify={onClarify}
                            />
                        )}
                        {responseData.type === "error" && (
                            <div className="bg-red-50 text-red-800 p-4 rounded-lg border border-red-200">
                                <div className="font-semibold mb-1">Error</div>
                                {responseData.message}
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
