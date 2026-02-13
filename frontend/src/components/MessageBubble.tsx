"use client";

import { ChatMessage, ChatResponse } from "@/types/chat";
import TableRenderer from "./TableRenderer";
import ChartRenderer from "./ChartRenderer";
import ClarificationPrompt from "./ClarificationPrompt";

interface MessageBubbleProps {
    message: ChatMessage;
    responseData?: ChatResponse;
}

export default function MessageBubble({ message, responseData }: MessageBubbleProps) {
    const isUser = message.role === "user";

    return (
        <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}>
            <div
                className={`max-w-[80%] rounded-lg px-4 py-3 ${isUser
                    ? "bg-blue-600 text-white"
                    : message.role === "system"
                        ? "bg-yellow-100 text-yellow-900 border border-yellow-300"
                        : "bg-gray-100 text-gray-900"
                    }`}
            >
                {/* Text content */}
                {message.content && (
                    <div className="whitespace-pre-wrap break-words">{message.content}</div>
                )}

                {/* Response data rendering */}
                {!isUser && responseData && (
                    <div className="mt-3">
                        {responseData.type === "table" && <TableRenderer data={responseData} />}
                        {responseData.type === "chart" && (
                            <ChartRenderer
                                visual_spec={responseData.data?.visual_spec}
                                refined_insights={responseData.data?.refined_insights}
                            />
                        )}
                        {responseData.type === "clarification_required" && (
                            <ClarificationPrompt question={responseData.question} />
                        )}
                        {responseData.type === "error" && (
                            <div className="bg-red-100 text-red-800 p-3 rounded border border-red-300">
                                <strong>Error:</strong> {responseData.message}
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
