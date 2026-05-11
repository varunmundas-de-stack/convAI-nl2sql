"use client";

import { useState, useEffect, useRef, KeyboardEvent } from "react";
import { ArrowUp, LogOut, Plus, PanelLeftClose, PanelLeft, Trash2, Lightbulb, BarChart2 } from "lucide-react";
import Link from "next/link";
import {
    sendQuery,
    clarify,
    healthCheck,
    getCurrentSessionId,
    setSessionId as setApiSessionId,
    resetSession,
    retryQuery,
    login,
    logout,
    getAccessToken,
    getMe,
    getChatSessions,
    deleteChatSession,
    getChatMessages,
    transformBackendResponse,
} from "@/services/api";
import { useConversation } from "@/state/conversation";
import MessageBubble from "./MessageBubble";
import { parseClarificationAnswers } from "@/utils/clarificationParser";

export default function ChatWindow() {
    const [input, setInput] = useState("");
    const [isBackendAvailable, setIsBackendAvailable] = useState(true);
    const [isLoading, setIsLoading] = useState(false);
    const [sessionId, setSessionId] = useState<string | null>(null);
    const [retryingMessageId, setRetryingMessageId] = useState<string | null>(null);
    const [user, setUser] = useState<any>(null);
    const [loginError, setLoginError] = useState<string | null>(null);
    const [loginForm, setLoginForm] = useState({ username: "nestle_admin", password: "admin123" });
    const [sessions, setSessions] = useState<any[]>([]);
    const [isSidebarOpen, setIsSidebarOpen] = useState(true);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const {
        messages,
        pendingClarification,
        backendResponse,
        compoundState,
        addUserMessage,
        handleResponse,
        clearMessages,
        replaceMessages,
    } = useConversation();

    async function refreshUserData() {
        try {
            const data = await getChatSessions();
            setSessions(data.sessions || []);
        } catch {
            setSessions([]);
        }
    }

    useEffect(() => {
        if (!getAccessToken()) return;
        getMe()
            .then((data) => {
                setUser(data.user);
                refreshUserData();
            })
            .catch(() => logout());
    }, []);

    // Clear session token when the browser tab/window is closed
    useEffect(() => {
        const handleBeforeUnload = () => {
            localStorage.removeItem("nl2sql_access_token");
        };
        window.addEventListener("beforeunload", handleBeforeUnload);
        return () => window.removeEventListener("beforeunload", handleBeforeUnload);
    }, []);

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

    // Prepopulate input if navigating from Insights page
    useEffect(() => {
        const storedQuery = sessionStorage.getItem("suggested_query");
        if (storedQuery) {
            setInput(storedQuery);
            sessionStorage.removeItem("suggested_query");
        }
    }, []);

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
        if (!input.trim() || isLoading || !isBackendAvailable || !user) return;

        const userInput = input.trim();
        addUserMessage(userInput);
        setInput("");
        setIsLoading(true);

        try {
            let result;

            if (pendingClarification) {
                // Handle compound clarifications
                if (pendingClarification.type === "compound_clarification_required" && compoundState) {
                    result = await clarify({
                        compound_state: compoundState,
                        clarification_answer: userInput,
                    });
                } else if (backendResponse) {
                    // Regular clarifications
                    const missingFields = backendResponse.missing_fields || [];
                    const answers = parseClarificationAnswers(userInput, missingFields);

                    result = await clarify({
                        request_id: backendResponse.request_id,
                        answers: answers,
                    });
                } else {
                    throw new Error("Missing backend response for clarification");
                }
            } else {
                // Regular query
                result = await sendQuery(userInput);
                // Update session ID from response
                if (result.sessionId) {
                    setSessionId(result.sessionId);
                }
            }

            handleResponse(result.response, result.raw);
            refreshUserData();
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
        if (isLoading || !isBackendAvailable || !pendingClarification || !user) return;

        // Show friendly message to user
        const displayValue = answerValue.replace(/_/g, " ");
        addUserMessage(displayValue);

        setIsLoading(true);

        try {
            let result;

            // Handle compound clarifications
            if (pendingClarification.type === "compound_clarification_required" && compoundState) {
                result = await clarify({
                    compound_state: compoundState,
                    clarification_answer: answerValue,
                });
            } else {
                // Regular clarification handling
                if (!backendResponse) {
                    throw new Error("Missing backend response for clarification");
                }

                const missingFields = backendResponse.missing_fields || [];
                const answers = parseClarificationAnswers(answerValue, missingFields);

                result = await clarify({
                    request_id: backendResponse.request_id,
                    answers: answers,
                });
            }

            handleResponse(result.response, result.raw);
            refreshUserData();
        } catch (error) {
            handleResponse({
                type: "error",
                message: error instanceof Error ? error.message : "Unknown error occurred",
            });
        } finally {
            setIsLoading(false);
        }
    }

    async function handleRetry(modifiedQuery: string, originalMessage: any) {
        if (isLoading || !isBackendAvailable || !sessionId || !user) return;

        // Use the original_query from the backend response (not effective_query)
        // The original_query is what we want for RLHF logging
        const originalQuery = originalMessage.rawBackendData?.original_query ||
            originalMessage.rawBackendData?.query ||
            modifiedQuery;

        setRetryingMessageId(originalMessage.id);
        setIsLoading(true);

        try {
            const result = await retryQuery(
                originalMessage.rawBackendData?.request_id,
                modifiedQuery,
                sessionId,
                originalQuery
            );

            // Update session ID from response
            if (result.sessionId) {
                setSessionId(result.sessionId);
            }

            // Add user message with the modified query
            addUserMessage(modifiedQuery);

            // Handle the response
            handleResponse(result.response, result.raw);
            refreshUserData();
        } catch (error) {
            handleResponse({
                type: "error",
                message: error instanceof Error ? error.message : "Retry failed",
            });
        } finally {
            setIsLoading(false);
            setRetryingMessageId(null);
        }
    }

    function handleNewConversation() {
        if (true) {
            resetSession();
            setSessionId(null);
            clearMessages();
        }
    }

    async function handleDeleteSession(sessionIdToDelete: string) {
        if (!confirm("Are you sure you want to delete this conversation?")) return;
        try {
            await deleteChatSession(sessionIdToDelete);
            if (sessionId === sessionIdToDelete) {
                resetSession();
                setSessionId(null);
                clearMessages();
            }
            await refreshUserData();
        } catch (error) {
            console.error("Failed to delete session", error);
        }
    }

    async function handleLogin() {
        setLoginError(null);
        try {
            const nextUser = await login(loginForm.username, loginForm.password);
            setUser(nextUser);
            await refreshUserData();
        } catch (error) {
            setLoginError(error instanceof Error ? error.message : "Login failed");
        }
    }

    async function handleLogout() {
        await logout();
        setUser(null);
        setSessionId(null);
        setSessions([]);
        clearMessages();
    }

    async function loadSession(sessionIdToLoad: string) {
        const data = await getChatMessages(sessionIdToLoad);
        setSessionId(sessionIdToLoad);
        setApiSessionId(sessionIdToLoad);

        let restoredPendingClarification = null;
        let restoredBackendResponse = null;
        let restoredCompoundState = null;

        const transformedMessages = (data.messages || []).map((m: any, index: number) => {
            let responseData;
            if (m.raw_data) {
                responseData = transformBackendResponse(m.raw_data);
                if (m.raw_data.stage === "CLARIFICATION_REQUESTED" && index === (data.messages || []).length - 1) {
                    restoredPendingClarification = responseData;
                    restoredBackendResponse = m.raw_data;
                    restoredCompoundState = m.raw_data.compound_state || null;
                }
            }
            return {
                id: m.message_id,
                role: m.role,
                content: m.content,
                rawBackendData: m.raw_data || undefined,
                responseData: responseData,
            };
        });

        replaceMessages(
            transformedMessages,
            restoredPendingClarification,
            restoredBackendResponse,
            restoredCompoundState
        );
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

    if (!user) {
        return (
            <div className="flex min-h-screen items-center justify-center bg-[#1a3a6b] px-4">
                <div className="w-full max-w-sm bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
                    <h1 className="text-xl font-semibold text-gray-900 mb-5">Sign in</h1>
                    <div className="space-y-3">
                        <input
                            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                            value={loginForm.username}
                            onChange={(e) => setLoginForm((f) => ({ ...f, username: e.target.value }))}
                            placeholder="Username"
                        />
                        <input
                            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                            type="password"
                            value={loginForm.password}
                            onChange={(e) => setLoginForm((f) => ({ ...f, password: e.target.value }))}
                            placeholder="Password"
                            onKeyDown={(e) => {
                                if (e.key === "Enter") handleLogin();
                            }}
                        />
                        {loginError && <div className="text-sm text-red-600">{loginError}</div>}
                        <button
                            onClick={handleLogin}
                            className="w-full bg-gray-900 text-white rounded-md py-2 text-sm hover:bg-gray-800"
                        >
                            Sign in
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="flex flex-col h-screen bg-[#1a3a6b]">
            {/* Header */}
            <div className="bg-[#1a3a6b] border-b border-[#2a4a8b] px-6 py-4 shadow-sm z-10">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <button
                            onClick={() => setIsSidebarOpen(!isSidebarOpen)}
                            className="p-1.5 text-blue-200 hover:bg-[#2a4a8b] rounded-md transition-colors hidden lg:block"
                            title="Toggle Sidebar"
                        >
                            {isSidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeft size={18} />}
                        </button>
                        <h1 className="text-xl font-semibold text-white">NL2SQL Chat</h1>
                    </div>
                    <div className="flex items-center gap-4">
                        <Link
                            href="/dashboard"
                            className="flex items-center gap-1.5 text-xs bg-blue-50 text-blue-700 border border-blue-200 px-3 py-1.5 rounded-lg hover:bg-blue-100 transition-colors"
                            title="View Dashboard"
                        >
                            <BarChart2 size={14} /> Dashboard
                        </Link>
                        <Link
                            href="/insights"
                            className="flex items-center gap-1.5 text-xs bg-yellow-50 text-yellow-700 border border-yellow-200 px-3 py-1.5 rounded-lg hover:bg-yellow-100 transition-colors"
                            title="View Business Insights"
                        >
                            <Lightbulb size={14} />
                            Insights
                        </Link>
                        <button
                            onClick={handleNewConversation}
                            className="flex items-center gap-1.5 text-xs bg-[#2a4a8b] text-white px-3 py-1.5 rounded-lg hover:bg-[#3a5a9b] transition-colors"
                            title="Start a new conversation"
                        >
                            <Plus size={14} />
                            New Chat
                        </button>

                        {/* Session Indicator */}
                        {/* {sessionId && (
                            <div className="flex items-center gap-2 text-xs">
                                <span className="text-gray-500">Session:</span>
                                <code className="bg-gray-100 px-2 py-1 rounded text-gray-700 font-mono">
                                    {sessionId}
                                </code>
                            </div>
                        )} */}
                        <div className="text-xs text-blue-200">
                            {user.full_name} · {user.client_name}
                        </div>
                        <button
                            onClick={handleLogout}
                            className="p-1.5 rounded-md border border-[#2a4a8b] text-blue-200 hover:bg-[#2a4a8b]"
                            title="Sign out"
                        >
                            <LogOut size={14} />
                        </button>
                        {/* Backend Status */}
                        <div className="flex items-center gap-2 ml-2">
                            <div
                                className={`w-2 h-2 rounded-full ${isBackendAvailable ? "bg-green-500" : "bg-red-500"
                                    }`}
                            />
                            {/* <span className="text-sm text-gray-600">
                                {isBackendAvailable ? "Connected" : "Disconnected"}
                            </span> */}
                        </div>
                    </div>
                </div>
            </div>

            <div className="flex-1 min-h-0 flex relative">
                {isSidebarOpen && (
                    <aside className="hidden lg:block w-72 border-r border-[#2a4a8b] overflow-y-auto p-3 shrink-0 bg-[#1a3a6b]">
                        <div className="text-xs font-semibold text-blue-200 uppercase mb-2">Recent Chats</div>
                        <div className="space-y-1 mb-5">
                            {sessions.map((s) => (
                                <div key={s.session_id} className="flex items-center gap-1 w-full group">
                                    <button
                                        onClick={() => loadSession(s.session_id)}
                                        className={`flex-1 text-left text-sm px-2 py-2 rounded-md truncate transition-colors ${sessionId === s.session_id ? "bg-[#2a4a8b] text-white font-medium" : "text-blue-100 hover:bg-[#2a4a8b]"}`}
                                    >
                                        {s.title || "New conversation"}
                                    </button>
                                    <button
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            handleDeleteSession(s.session_id);
                                        }}
                                        className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-md opacity-0 group-hover:opacity-100 transition-all shrink-0"
                                        title="Delete conversation"
                                    >
                                        <Trash2 size={14} />
                                    </button>
                                </div>
                            ))}
                        </div>
                    </aside>
                )}

                {/* Main Chat Area */}
                <div className="flex-1 flex flex-col relative min-w-0 bg-[#1a3a6b]">
                    {/* Messages */}
                    <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6 flex flex-col items-center">
                        <div className="w-full max-w-5xl flex flex-col h-full">
                            {messages.length === 0 && (
                                <div className="flex flex-col items-center justify-center h-full">
                                    <h2 className="text-4xl font-semibold text-white mb-8 tracking-tight">What do you want to know?</h2>
                                    <div className="flex flex-wrap gap-3 justify-center max-w-2xl">
                                        {[
                                            "Show net sales by zone for last 30 days",
                                            "Top 5 products by revenue this month",
                                            "Sales performance by region vs target",
                                            "Which SKUs had the highest growth last quarter?",
                                        ].map((suggestion) => (
                                            <button
                                                key={suggestion}
                                                onClick={() => setInput(suggestion)}
                                                className="bg-[#2a4a8b] text-white text-sm px-4 py-2 rounded-full hover:bg-[#3a5a9b] cursor-pointer transition-colors"
                                            >
                                                {suggestion}
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {messages.map((msg, index) => {
                                // Determine the query to show in retry modal
                                // Use effective_query (original + clarifications) for display
                                let originalQuery = "";
                                if (msg.role === "assistant" && msg.rawBackendData?.effective_query) {
                                    // Use the effective query (original + clarifications)
                                    originalQuery = msg.rawBackendData.effective_query;
                                } else if (msg.role === "assistant" && msg.rawBackendData?.original_query) {
                                    // Fall back to original query from backend
                                    originalQuery = msg.rawBackendData.original_query;
                                } else if (index > 0 && messages[index - 1].role === "user") {
                                    // Final fallback to previous user message
                                    originalQuery = messages[index - 1].content;
                                }

                                return (
                                    <MessageBubble
                                        key={msg.id}
                                        message={msg}
                                        responseData={msg.responseData}
                                        rawBackendData={msg.rawBackendData}
                                        onClarify={submitClarification}
                                        isActiveClarification={pendingClarification === msg.responseData}
                                        onRetry={msg.role === "assistant" && msg.rawBackendData?.request_id
                                            ? (modifiedQuery) => handleRetry(modifiedQuery, msg)
                                            : undefined}
                                        originalQuery={originalQuery}
                                    />
                                );
                            })}

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

                            <div className="h-24 shrink-0 w-full" />
                            <div ref={messagesEndRef} />
                        </div>
                    </div>

                    {/* Floating Input */}
                    <div
                        className={`
                    absolute bottom-6 left-1/2 -translate-x-1/2
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
            </div>
        </div>
    );
}
