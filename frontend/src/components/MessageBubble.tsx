"use client";

import { ChatMessage, ChatResponse } from "@/types/chat";
import TableRenderer from "./TableRenderer";
import ChartRenderer from "./ChartRenderer";
import ClarificationPrompt from "./ClarificationPrompt";
import FeedbackBar from "./FeedbackBar";

interface MessageBubbleProps {
    message: ChatMessage;
    responseData?: ChatResponse;
    rawBackendData?: any;
    onClarify?: (value: string) => void;
    isActiveClarification?: boolean;
}

export default function MessageBubble({ message, responseData, rawBackendData, onClarify, isActiveClarification }: MessageBubbleProps) {
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

    const shouldRenderResponseData = !isUser && responseData && (
        responseData.type === "table" ||
        responseData.type === "chart" ||
        (responseData.type === "clarification_required" && isActiveClarification) ||
        responseData.type === "error"
    );

    // Show feedback bar for assistant messages that are NOT errors or clarifications
    const showFeedback = !isUser && !isSystem && responseData &&
        responseData.type !== "error" &&
        responseData.type !== "clarification_required" &&
        rawBackendData?.request_id;

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
                {shouldRenderResponseData && (
                    <div className="mt-8 space-y-8"> {/* Ample vertical spacing */}
                        {responseData.type === "table" && <TableRenderer data={responseData} />}
                        {responseData.type === "chart" && (
                            <ChartRenderer
                                visual_spec={responseData.data?.visual_spec}
                                refined_insights={responseData.data?.refined_insights}
                            />
                        )}
                        {responseData.type === "clarification_required" && isActiveClarification && (
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

                {/* Feedback bar */}
                {showFeedback && (
                    <FeedbackBar
                        requestId={rawBackendData.request_id}
                        query={rawBackendData.query || ""}
                        promptVersion={rawBackendData.prompt_version}
                        abGroup={rawBackendData.ab_group}
                        responseSummary={
                            rawBackendData.refined_insights?.executive_summary ||
                            rawBackendData.refined_insights?.primary_insight?.headline ||
                            message.content || ""
                        }
                        fullResponse={
                            rawBackendData.refined_insights
                                ? JSON.stringify(rawBackendData.refined_insights)
                                : undefined
                        }
                        sqlQuery={
                            rawBackendData.cube_query
                                ? JSON.stringify(rawBackendData.cube_query)
                                : undefined
                        }
                    />
                )}
            </div>
        </div>
    );
}
