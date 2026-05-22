"use client";

import { useState, useEffect, useRef, KeyboardEvent } from "react";
import {
    ArrowUp, LogOut, Plus, PanelLeftClose, PanelLeft, Trash2,
    Lightbulb, BarChart2, TrendingUp, Package, Target, Settings,
    ChevronDown, Zap
} from "lucide-react";
import Link from "next/link";
import {
    sendQuery, clarify, healthCheck, getCurrentSessionId,
    setSessionId as setApiSessionId, resetSession, retryQuery,
    login, logout, getAccessToken, getMe, getChatSessions,
    deleteChatSession, getChatMessages, transformBackendResponse,
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
        messages, pendingClarification, backendResponse, compoundState,
        addUserMessage, handleResponse, clearMessages, replaceMessages,
    } = useConversation();

    async function refreshUserData() {
        try {
            const data = await getChatSessions();
            setSessions(data.sessions || []);
        } catch { setSessions([]); }
    }

    useEffect(() => {
        if (!getAccessToken()) return;
        getMe().then((data) => { setUser(data.user); refreshUserData(); }).catch(() => logout());
    }, []);

    useEffect(() => {
        const handleBeforeUnload = () => localStorage.removeItem("nl2sql_access_token");
        window.addEventListener("beforeunload", handleBeforeUnload);
        return () => window.removeEventListener("beforeunload", handleBeforeUnload);
    }, []);

    useEffect(() => {
        const checkHealth = async () => {
            try { await healthCheck(); setIsBackendAvailable(true); }
            catch { setIsBackendAvailable(false); }
        };
        checkHealth();
        const interval = setInterval(checkHealth, 30000);
        return () => clearInterval(interval);
    }, []);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    useEffect(() => {
        const storedQuery = sessionStorage.getItem("suggested_query");
        if (storedQuery) { setInput(storedQuery); sessionStorage.removeItem("suggested_query"); }
    }, []);

    useEffect(() => {
        const interval = setInterval(() => {
            const currentSession = getCurrentSessionId();
            if (currentSession !== sessionId) setSessionId(currentSession);
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
                if (pendingClarification.type === "compound_clarification_required" && compoundState) {
                    result = await clarify({ compound_state: compoundState, clarification_answer: userInput });
                } else if (backendResponse) {
                    const answers = parseClarificationAnswers(userInput, backendResponse.missing_fields || []);
                    result = await clarify({ request_id: backendResponse.request_id, answers });
                } else throw new Error("Missing backend response for clarification");
            } else {
                result = await sendQuery(userInput);
                if (result.sessionId) setSessionId(result.sessionId);
            }
            handleResponse(result.response, result.raw);
            refreshUserData();
        } catch (error) {
            handleResponse({ type: "error", message: error instanceof Error ? error.message : "Unknown error occurred" });
        } finally { setIsLoading(false); }
    }

    async function submitClarification(answerValue: string) {
        if (isLoading || !isBackendAvailable || !pendingClarification || !user) return;
        addUserMessage(answerValue.replace(/_/g, " "));
        setIsLoading(true);
        try {
            let result;
            if (pendingClarification.type === "compound_clarification_required" && compoundState) {
                result = await clarify({ compound_state: compoundState, clarification_answer: answerValue });
            } else {
                if (!backendResponse) throw new Error("Missing backend response for clarification");
                const answers = parseClarificationAnswers(answerValue, backendResponse.missing_fields || []);
                result = await clarify({ request_id: backendResponse.request_id, answers });
            }
            handleResponse(result.response, result.raw);
            refreshUserData();
        } catch (error) {
            handleResponse({ type: "error", message: error instanceof Error ? error.message : "Unknown error occurred" });
        } finally { setIsLoading(false); }
    }

    async function handleRetry(modifiedQuery: string, originalMessage: any) {
        if (isLoading || !isBackendAvailable || !sessionId || !user) return;
        const originalQuery = originalMessage.rawBackendData?.original_query || originalMessage.rawBackendData?.query || modifiedQuery;
        setRetryingMessageId(originalMessage.id);
        setIsLoading(true);
        try {
            const result = await retryQuery(originalMessage.rawBackendData?.request_id, modifiedQuery, sessionId, originalQuery);
            if (result.sessionId) setSessionId(result.sessionId);
            addUserMessage(modifiedQuery);
            handleResponse(result.response, result.raw);
            refreshUserData();
        } catch (error) {
            handleResponse({ type: "error", message: error instanceof Error ? error.message : "Retry failed" });
        } finally { setIsLoading(false); setRetryingMessageId(null); }
    }

    function handleNewConversation() {
        resetSession(); setSessionId(null); clearMessages();
    }

    async function handleDeleteSession(sessionIdToDelete: string) {
        if (!confirm("Delete this conversation?")) return;
        try {
            await deleteChatSession(sessionIdToDelete);
            if (sessionId === sessionIdToDelete) { resetSession(); setSessionId(null); clearMessages(); }
            await refreshUserData();
        } catch (error) { console.error("Failed to delete session", error); }
    }

    async function handleLogin() {
        setLoginError(null);
        try {
            const nextUser = await login(loginForm.username, loginForm.password);
            setUser(nextUser);
            await refreshUserData();
        } catch (error) { setLoginError(error instanceof Error ? error.message : "Login failed"); }
    }

    async function handleLogout() {
        await logout(); setUser(null); setSessionId(null); setSessions([]); clearMessages();
    }

    async function loadSession(sessionIdToLoad: string) {
        const data = await getChatMessages(sessionIdToLoad);
        setSessionId(sessionIdToLoad);
        setApiSessionId(sessionIdToLoad);
        let restoredPendingClarification = null, restoredBackendResponse = null, restoredCompoundState = null;
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
            return { id: m.message_id, role: m.role, content: m.content, rawBackendData: m.raw_data || undefined, responseData };
        });
        replaceMessages(transformedMessages, restoredPendingClarification, restoredBackendResponse, restoredCompoundState);
    }

    function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSend();
            requestAnimationFrame(() => { if (e.target instanceof HTMLTextAreaElement) e.target.style.height = "auto"; });
        }
    }

    const isClarificationWithButtons = Boolean(
        pendingClarification?.allowed_values?.length > 0
    );

    // ── LOGIN PAGE ──────────────────────────────────────────────────────────────
    if (!user) {
        return (
            <div className="flex min-h-screen">
                {/* Left: animated gradient mesh */}
                <div className="hidden lg:flex lg:w-1/2 gradient-mesh flex-col items-center justify-center p-12 relative overflow-hidden">
                    {/* Subtle grid overlay */}
                    <div className="absolute inset-0 opacity-10"
                        style={{ backgroundImage: "radial-gradient(circle, rgba(255,255,255,0.4) 1px, transparent 1px)", backgroundSize: "32px 32px" }} />
                    <div className="relative z-10 text-center text-white">
                        <div className="flex items-center justify-center gap-2 mb-6">
                            <div className="w-10 h-10 bg-white/20 backdrop-blur rounded-xl flex items-center justify-center">
                                <Zap size={20} className="text-white" />
                            </div>
                            <span className="text-2xl font-bold tracking-tight">CPG Analytics</span>
                        </div>
                        <h2 className="text-4xl font-extrabold leading-tight mb-4">
                            Ask your data<br />anything.
                        </h2>
                        <p className="text-white/80 text-lg max-w-xs mx-auto">
                            Instant SQL insights for sales, SKUs, zones &amp; targets — no code required.
                        </p>
                        <div className="mt-10 grid grid-cols-2 gap-3 max-w-sm mx-auto text-sm">
                            {["Net Sales by Zone", "Top SKU Revenue", "Target vs Actual", "Region Trends"].map((label) => (
                                <div key={label} className="bg-white/15 backdrop-blur-sm rounded-xl px-4 py-3 text-left font-medium border border-white/20">
                                    {label}
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

                {/* Right: login card */}
                <div className="flex-1 flex flex-col items-center justify-center bg-gray-50 px-6 py-12">
                    <div className="w-full max-w-sm">
                        {/* Mobile logo */}
                        <div className="flex items-center gap-2 mb-8 lg:hidden">
                            <div className="w-8 h-8 gradient-mesh rounded-lg flex items-center justify-center">
                                <Zap size={16} className="text-white" />
                            </div>
                            <span className="font-bold text-gray-900">CPG Analytics</span>
                        </div>

                        <h1 className="text-2xl font-bold text-gray-900 mb-1">Welcome back</h1>
                        <p className="text-gray-500 text-sm mb-8">Sign in to your analytics workspace</p>

                        <div className="space-y-4">
                            <div>
                                <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1.5">Username</label>
                                <input
                                    className="input-field"
                                    value={loginForm.username}
                                    onChange={(e) => setLoginForm((f) => ({ ...f, username: e.target.value }))}
                                    placeholder="Enter username"
                                />
                            </div>
                            <div>
                                <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1.5">Password</label>
                                <input
                                    className="input-field"
                                    type="password"
                                    value={loginForm.password}
                                    onChange={(e) => setLoginForm((f) => ({ ...f, password: e.target.value }))}
                                    placeholder="Enter password"
                                    onKeyDown={(e) => { if (e.key === "Enter") handleLogin(); }}
                                />
                            </div>
                            {loginError && (
                                <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-lg">{loginError}</div>
                            )}
                            <button onClick={handleLogin} className="btn-primary w-full py-3 text-base">
                                Sign in
                            </button>
                        </div>

                        <div className="mt-8 flex items-center justify-center gap-2">
                            <div className="w-5 h-5 bg-gray-200 rounded-full flex items-center justify-center">
                                <Zap size={11} className="text-gray-500" />
                            </div>
                            <span className="text-xs text-gray-400">Powered by Claude Sonnet 4.6</span>
                        </div>
                    </div>
                </div>
            </div>
        );
    }

    // ── MAIN APP ────────────────────────────────────────────────────────────────
    const groupedSessions = sessions.reduce((acc: Record<string, any[]>, s) => {
        const date = s.updated_at ? new Date(s.updated_at) : new Date();
        const now = new Date();
        const diffDays = Math.floor((now.getTime() - date.getTime()) / 86400000);
        const group = diffDays === 0 ? "Today" : diffDays === 1 ? "Yesterday" : diffDays <= 7 ? "This Week" : "Older";
        if (!acc[group]) acc[group] = [];
        acc[group].push(s);
        return acc;
    }, {});

    return (
        <div className="flex h-screen bg-gray-50 overflow-hidden">

            {/* ── SIDEBAR ─────────────────────────────────────────────────────── */}
            {isSidebarOpen && (
                <aside className="hidden lg:flex flex-col w-72 bg-white border-r border-gray-200 shrink-0 transition-all duration-200">
                    {/* Logo row */}
                    <div className="px-5 py-5 flex items-center justify-between border-b border-gray-100">
                        <div className="flex items-center gap-2.5">
                            <div className="w-8 h-8 gradient-mesh rounded-lg flex items-center justify-center">
                                <Zap size={15} className="text-white" />
                            </div>
                            <div>
                                <div className="text-sm font-bold text-gray-900 leading-none">CPG Analytics</div>
                                <div className="text-[10px] text-gray-400 mt-0.5">NL2SQL Workspace</div>
                            </div>
                        </div>
                        <button onClick={() => setIsSidebarOpen(false)} className="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded">
                            <PanelLeftClose size={16} />
                        </button>
                    </div>

                    {/* Tenant pill */}
                    <div className="px-4 py-3 border-b border-gray-100">
                        <button className="w-full flex items-center justify-between bg-gray-50 hover:bg-gray-100 border border-gray-200 rounded-lg px-3 py-2 text-sm font-medium text-gray-700 transition-colors">
                            <span className="truncate">{user.client_name || "Organisation"}</span>
                            <ChevronDown size={14} className="text-gray-400 shrink-0 ml-1" />
                        </button>
                    </div>

                    {/* New chat */}
                    <div className="px-4 py-3">
                        <button onClick={handleNewConversation} className="btn-primary w-full flex items-center justify-center gap-1.5 text-sm py-2">
                            <Plus size={14} /> New Chat
                        </button>
                    </div>

                    {/* Conversations */}
                    <div className="flex-1 overflow-y-auto px-3 pb-4">
                        <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider px-2 mb-2">Conversations</div>
                        {Object.entries(groupedSessions).map(([group, groupSessions]) => (
                            <div key={group} className="mb-4">
                                <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider px-2 mb-1">{group}</div>
                                <div className="space-y-0.5">
                                    {groupSessions.map((s) => (
                                        <div key={s.session_id} className="flex items-center gap-1 group">
                                            <button
                                                onClick={() => loadSession(s.session_id)}
                                                className={`flex-1 text-left text-sm px-3 py-2 rounded-lg truncate transition-colors ${
                                                    sessionId === s.session_id
                                                        ? "nav-active rounded-lg"
                                                        : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                                                }`}
                                            >
                                                {s.title || "New conversation"}
                                            </button>
                                            <button
                                                onClick={(e) => { e.stopPropagation(); handleDeleteSession(s.session_id); }}
                                                className="p-1.5 text-gray-300 hover:text-red-500 hover:bg-red-50 rounded opacity-0 group-hover:opacity-100 transition-all shrink-0"
                                            >
                                                <Trash2 size={13} />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        ))}
                        {sessions.length === 0 && (
                            <p className="text-xs text-gray-400 px-2 py-2">No conversations yet.</p>
                        )}
                    </div>

                    {/* User footer */}
                    <div className="border-t border-gray-100 px-4 py-3 flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-orange-400 to-indigo-500 flex items-center justify-center text-white text-xs font-bold shrink-0">
                            {(user.full_name || user.username || "U")[0].toUpperCase()}
                        </div>
                        <div className="flex-1 min-w-0">
                            <div className="text-sm font-semibold text-gray-900 truncate">{user.full_name || user.username}</div>
                            <div className="text-[11px] text-gray-400 truncate">{user.role}</div>
                        </div>
                        <button onClick={handleLogout} className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded transition-colors" title="Sign out">
                            <LogOut size={15} />
                        </button>
                    </div>
                </aside>
            )}

            {/* ── MAIN AREA ────────────────────────────────────────────────────── */}
            <div className="flex-1 flex flex-col min-w-0">

                {/* Topbar */}
                <header className="bg-white/80 backdrop-blur-md border-b border-gray-200 px-5 py-3 flex items-center justify-between gap-4 z-10 sticky top-0">
                    <div className="flex items-center gap-3">
                        {!isSidebarOpen && (
                            <button onClick={() => setIsSidebarOpen(true)} className="p-1.5 text-gray-500 hover:bg-gray-100 rounded-lg transition-colors">
                                <PanelLeft size={18} />
                            </button>
                        )}
                        {!isSidebarOpen && (
                            <div className="flex items-center gap-2">
                                <div className="w-7 h-7 gradient-mesh rounded-lg flex items-center justify-center">
                                    <Zap size={13} className="text-white" />
                                </div>
                                <span className="font-bold text-gray-900 text-sm">CPG Analytics</span>
                            </div>
                        )}
                    </div>

                    {/* Center tabs */}
                    <nav className="flex items-center gap-1 bg-gray-100 rounded-xl p-1">
                        <Link href="/" className="px-4 py-1.5 rounded-lg text-sm font-medium bg-white text-gray-900 shadow-sm">Chat</Link>
                        <Link href="/dashboard" className="px-4 py-1.5 rounded-lg text-sm font-medium text-gray-500 hover:text-gray-900 transition-colors">Dashboard</Link>
                        <Link href="/insights" className="px-4 py-1.5 rounded-lg text-sm font-medium text-gray-500 hover:text-gray-900 transition-colors">Insights</Link>
                    </nav>

                    {/* Right: status + actions */}
                    <div className="flex items-center gap-3">
                        <div className={`w-2 h-2 rounded-full shrink-0 ${isBackendAvailable ? "bg-emerald-500" : "bg-red-500"}`} title={isBackendAvailable ? "Backend connected" : "Backend unavailable"} />
                        <button onClick={handleNewConversation} className="btn-primary flex items-center gap-1.5 text-sm py-2 px-3">
                            <Plus size={14} /> New Chat
                        </button>
                    </div>
                </header>

                {/* Messages */}
                <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6 flex flex-col items-center">
                    <div className="w-full max-w-4xl flex flex-col h-full">

                        {/* Empty state hero */}
                        {messages.length === 0 && (
                            <div className="flex flex-col items-center justify-center h-full dot-grid rounded-3xl py-16 px-6 relative">
                                <div className="absolute inset-0 rounded-3xl bg-gradient-to-b from-white/60 to-white/90" />
                                <div className="relative z-10 text-center mb-10">
                                    <h2 className="text-4xl font-extrabold text-gray-900 tracking-tight mb-3">
                                        What do you want to know?
                                    </h2>
                                    <p className="text-gray-500 text-lg">
                                        Ask anything about your CPG sales, SKUs, zones, and targets
                                    </p>
                                </div>
                                {/* Suggestion cards 2x2 */}
                                <div className="relative z-10 grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-2xl">
                                    {[
                                        { icon: <BarChart2 size={20} className="text-orange-500" />, label: "Net Sales by Zone", desc: "Show net sales breakdown for last 30 days" },
                                        { icon: <TrendingUp size={20} className="text-indigo-500" />, label: "Top SKU Revenue", desc: "Top 5 products by revenue this month" },
                                        { icon: <Package size={20} className="text-emerald-500" />, label: "SKU Growth", desc: "Which SKUs had the highest growth last quarter?" },
                                        { icon: <Target size={20} className="text-rose-500" />, label: "Target vs Actual", desc: "Sales performance by region vs target" },
                                    ].map((s) => (
                                        <button
                                            key={s.label}
                                            onClick={() => setInput(s.desc)}
                                            className="card card-hover text-left p-4 flex gap-3 items-start hover:border-orange-200 group"
                                        >
                                            <div className="shrink-0 w-9 h-9 bg-gray-50 rounded-xl flex items-center justify-center group-hover:bg-orange-50 transition-colors">
                                                {s.icon}
                                            </div>
                                            <div>
                                                <div className="font-semibold text-gray-900 text-sm">{s.label}</div>
                                                <div className="text-xs text-gray-500 mt-0.5">{s.desc}</div>
                                            </div>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}

                        {messages.map((msg, index) => {
                            let originalQuery = "";
                            if (msg.role === "assistant" && msg.rawBackendData?.effective_query) {
                                originalQuery = msg.rawBackendData.effective_query;
                            } else if (msg.role === "assistant" && msg.rawBackendData?.original_query) {
                                originalQuery = msg.rawBackendData.original_query;
                            } else if (index > 0 && messages[index - 1].role === "user") {
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
                                <div className="card px-5 py-3">
                                    <div className="flex items-center gap-1.5">
                                        {[0, 1, 2].map((i) => (
                                            <div key={i} className={`w-2 h-2 bg-orange-400 rounded-full animate-bounce delay-${i * 100}`} />
                                        ))}
                                    </div>
                                </div>
                            </div>
                        )}

                        <div className="h-28 shrink-0 w-full" />
                        <div ref={messagesEndRef} />
                    </div>
                </div>

                {/* Floating input */}
                <div className="absolute bottom-6 left-1/2 -translate-x-1/2 w-[calc(100%-2rem)] max-w-3xl"
                    style={{ left: isSidebarOpen ? "calc(50% + 144px)" : "50%" }}>
                    <div className={`flex items-end gap-2 bg-white border rounded-2xl px-4 py-2.5 shadow-lg transition-all duration-150 ${
                        !isBackendAvailable ? "border-red-200" : "border-gray-200 focus-within:border-orange-300 focus-within:shadow-[0_0_0_3px_rgba(249,115,22,0.1)]"
                    }`}>
                        <textarea
                            className="flex-1 max-h-40 outline-none border-none resize-none bg-transparent text-gray-900 text-sm leading-relaxed placeholder:text-gray-400 disabled:opacity-40 disabled:cursor-not-allowed overflow-y-auto"
                            rows={1}
                            style={{ minHeight: "24px" }}
                            placeholder={
                                !isBackendAvailable ? "Backend unavailable..."
                                    : isClarificationWithButtons ? "Select an option above..."
                                    : "Ask anything about your CPG data..."
                            }
                            value={input}
                            onChange={(e) => {
                                setInput(e.target.value);
                                e.target.style.height = "auto";
                                e.target.style.height = e.target.scrollHeight + "px";
                            }}
                            onKeyDown={handleKeyDown}
                            disabled={!isBackendAvailable || isLoading || isClarificationWithButtons}
                        />
                        <button
                            onClick={() => { onSend(); const ta = document.querySelector("textarea"); if (ta) ta.style.height = "auto"; }}
                            disabled={!isBackendAvailable || isLoading || isClarificationWithButtons || !input.trim()}
                            className="shrink-0 p-2 rounded-xl flex items-center justify-center text-white btn-primary disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed disabled:shadow-none disabled:transform-none"
                        >
                            <ArrowUp size={16} strokeWidth={2.5} />
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
