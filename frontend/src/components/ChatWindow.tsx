"use client";

import { useState, useEffect, useRef, KeyboardEvent } from "react";
import { ArrowUp } from "lucide-react";
import { sendQuery, clarify, healthCheck, getCurrentSessionId, resetSession } from "@/services/api";
import { useConversation } from "@/state/conversation";
import MessageBubble from "./MessageBubble";
import { parseClarificationAnswers } from "@/utils/clarificationParser";

export default function ChatWindow() {
    const [input, setInput] = useState("");
    const [isBackendAvailable, setIsBackendAvailable] = useState(true);
    const [isLoading, setIsLoading] = useState(false);
    const [sessionId, setSessionId] = useState<string | null>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const {
        messages,
        pendingClarification,
        backendResponse,
        addUserMessage,
        handleResponse,
        clearMessages,
    } = useConversation();

    // Check backend health on mount
    useEffect(() => {
        const checkHealth = async () => {
            try {
                await healthCheck();
                setIsBackendAvailable(true);
            } catch (error) {
                setIsBackendAvailable(false);
            }
        };

        checkHealth();
        // Check health every 30 seconds
        const interval = setInterval(checkHealth, 30000);
        return () => clearInterval(interval);
    }, []);

    // Auto-scroll to latest message
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    // Sync session ID from API
    useEffect(() => {
        const interval = setInterval(() => {
            const currentSession = getCurrentSessionId();
            if (currentSession !== sessionId) {
                setSessionId(currentSession);
            }
        }, 500);
        return () => clearInterval(interval);
    }, [sessionId]);

    async function onSend() {
        if (!input.trim() || isLoading || !isBackendAvailable) return;

        const userInput = input.trim();
        addUserMessage(userInput);
        setInput("");
        setIsLoading(true);

        try {
            let result;

            if (pendingClarification && backendResponse) {
                // In clarification mode - parse user input into structured format
                const missingFields = backendResponse.missing_fields || [];
                const answers = parseClarificationAnswers(userInput, missingFields);

                result = await clarify({
                    request_id: backendResponse.request_id,
                    answers: answers,
                });
            } else {
                result = await sendQuery(userInput);
                // Update session ID from response
                if (result.sessionId) {
                    setSessionId(result.sessionId);
                }
            }

            handleResponse(result.response, result.raw);
        } catch (error) {
            handleResponse({
                type: "error",
                message:
                    error instanceof Error ? error.message : "Unknown error occurred",
            });
        } finally {
            setIsLoading(false);
        }
    }

    async function submitClarification(answerValue: string) {
        if (isLoading || !isBackendAvailable || !pendingClarification || !backendResponse) return;

        // Show friendly message to user
        const displayValue = answerValue.replace(/_/g, " ");
        addUserMessage(displayValue);

        setIsLoading(true);

        try {
            const missingFields = backendResponse.missing_fields || [];
            const answers = parseClarificationAnswers(answerValue, missingFields);

            const result = await clarify({
                request_id: backendResponse.request_id,
                answers: answers,
            });

            handleResponse(result.response, result.raw);
        } catch (error) {
            handleResponse({
                type: "error",
                message: error instanceof Error ? error.message : "Unknown error occurred",
            });
        } finally {
            setIsLoading(false);
        }
    }

    function handleNewConversation() {
        if (confirm("Start a new conversation? This will clear the current chat history.")) {
            resetSession();
            setSessionId(null);
            clearMessages();
        }
    }

    function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
        // Send on Enter, newline on Shift+Enter
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSend();
            // reset height on send
            requestAnimationFrame(() => {
                if (e.target instanceof HTMLTextAreaElement) {
                    e.target.style.height = 'auto';
                }
            });
        }
    }

    // console.log("backendResponse in render:", backendResponse);

    const isClarificationWithButtons = Boolean(
        pendingClarification &&
        pendingClarification.allowed_values &&
        pendingClarification.allowed_values.length > 0
    );

    return (
        <div className="flex flex-col h-screen bg-white">
            {/* Header */}
            <div className="bg-white border-b border-gray-200 px-6 py-4 shadow-sm">
                <div className="flex items-center justify-between">
                    <h1 className="text-xl font-semibold text-gray-900">NL2SQL Chat</h1>
                    <div className="flex items-center gap-4">
                        {/* Session Indicator */}
                        {sessionId && (
                            <div className="flex items-center gap-2 text-xs">
                                <span className="text-gray-500">Session:</span>
                                <code className="bg-gray-100 px-2 py-1 rounded text-gray-700 font-mono">
                                    {sessionId}
                                </code>
                                <button
                                    onClick={handleNewConversation}
                                    className="text-blue-600 hover:text-blue-700 underline"
                                    title="Start a new conversation"
                                >
                                    New
                                </button>
                            </div>
                        )}
                        {/* Backend Status */}
                        <div className="flex items-center gap-2">
                            <div
                                className={`w-2 h-2 rounded-full ${isBackendAvailable ? "bg-green-500" : "bg-red-500"
                                    }`}
                            />
                            <span className="text-sm text-gray-600">
                                {isBackendAvailable ? "Connected" : "Disconnected"}
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            {/* Messages — extra bottom padding so content clears the floating bar */}
            <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6 pb-44 flex flex-col items-center">
                <div className="w-full max-w-5xl flex flex-col h-full">
                    {messages.length === 0 && (
                        <div className="flex flex-col items-center justify-center h-full">
                            <h2 className="text-4xl font-semibold text-gray-800 mb-8 tracking-tight">What do you want to know?</h2>
                        </div>
                    )}

                    {messages.map((msg) => (
                        <MessageBubble
                            key={msg.id}
                            message={msg}
                            responseData={msg.responseData}
                            onClarify={submitClarification}
                            isActiveClarification={pendingClarification === msg.responseData}
                        />
                    ))}

                    {isLoading && (
                        <div className="flex justify-start mb-4">
                            <div className="bg-gray-100 rounded-lg px-4 py-3">
                                <div className="flex items-center gap-2">
                                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-100" />
                                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-200" />
                                </div>
                            </div>
                        </div>
                    )}

                    <div ref={messagesEndRef} />
                </div>
            </div>

            {/* Floating Input */}
            <div
                className={`
                    fixed bottom-6 left-1/2 -translate-x-1/2
                    flex items-end gap-2
                    w-[calc(100%-2rem)] max-w-3xl
                    bg-white border rounded-2xl px-4 py-2.5
                    shadow-[0_2px_12px_rgba(0,0,0,0.08)]
                    transition-all duration-150
                    ${!isBackendAvailable
                        ? 'border-red-200'
                        : isClarificationWithButtons || isLoading
                            ? 'border-gray-200'
                            : 'border-gray-300 focus-within:border-gray-400 focus-within:shadow-[0_2px_16px_rgba(0,0,0,0.12)]'
                    }
                `}
            >
                <textarea
                    className="flex-1 max-h-[160px] outline-none border-none resize-none bg-transparent text-gray-900 text-sm leading-relaxed placeholder:text-gray-400 disabled:opacity-40 disabled:cursor-not-allowed overflow-y-auto"
                    rows={1}
                    style={{ minHeight: '24px' }}
                    placeholder={
                        !isBackendAvailable
                            ? "Backend unavailable..."
                            : isClarificationWithButtons
                                ? "Select an option above..."
                                : "Ask anything..."
                    }
                    value={input}
                    onChange={(e) => {
                        setInput(e.target.value);
                        e.target.style.height = 'auto';
                        e.target.style.height = e.target.scrollHeight + 'px';
                    }}
                    onKeyDown={handleKeyDown}
                    disabled={!isBackendAvailable || isLoading || isClarificationWithButtons}
                />
                <button
                    onClick={() => {
                        onSend();
                        const ta = document.querySelector('textarea');
                        if (ta) ta.style.height = 'auto';
                    }}
                    disabled={!isBackendAvailable || isLoading || isClarificationWithButtons || !input.trim()}
                    className="shrink-0 p-1.5 rounded-full flex items-center justify-center text-white bg-black hover:bg-gray-800 disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed transition-colors"
                >
                    <ArrowUp size={15} strokeWidth={2.5} />
                </button>
            </div>
        </div>
    );
}