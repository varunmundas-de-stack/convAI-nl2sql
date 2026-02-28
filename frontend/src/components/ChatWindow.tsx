"use client";

import { useState, useEffect, useRef, KeyboardEvent } from "react";
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

        addUserMessage(answerValue);
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
        }
    }

    // console.log("backendResponse in render:", backendResponse);

    return (
        <div className="flex flex-col h-screen bg-gray-50">
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

            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-6 py-4">
                {messages.length === 0 && (
                    <div className="flex items-center justify-center h-full">
                        <div className="text-center text-gray-500">
                            <p className="text-lg font-medium">Welcome to NL2SQL</p>
                            <p className="text-sm mt-2">
                                Ask questions about your data in natural language
                            </p>
                        </div>
                    </div>
                )}

                {messages.map((msg) => (
                    <MessageBubble key={msg.id} message={msg} responseData={msg.responseData} onClarify={submitClarification} />
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

            {/* Input */}
            <div className="bg-white border-t border-gray-200 px-6 py-4">
                {!isBackendAvailable && (
                    <div className="mb-3 bg-red-50 border border-red-200 text-red-700 px-4 py-2 rounded-lg text-sm">
                        Backend is unavailable. Please check your connection.
                    </div>
                )}



                <div className="flex gap-3">
                    <textarea
                        className="flex-1 border border-gray-300 text-black rounded-lg px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none disabled:bg-gray-100 disabled:cursor-not-allowed"
                        rows={2}
                        placeholder={
                            isBackendAvailable
                                ? "Type your question... (Enter to send, Shift+Enter for new line)"
                                : "Backend unavailable..."
                        }
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={handleKeyDown}
                        disabled={!isBackendAvailable || isLoading}
                    />
                    <button
                        onClick={onSend}
                        disabled={!isBackendAvailable || isLoading || !input.trim()}
                        className="bg-blue-600 text-white px-6 py-3 rounded-lg font-medium hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                    >
                        Send
                    </button>
                </div>
            </div>
        </div>
    );
}
