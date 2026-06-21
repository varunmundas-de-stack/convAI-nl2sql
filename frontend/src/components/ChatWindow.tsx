"use client";

import { useState, useEffect, useRef, KeyboardEvent } from "react";
import {
    ArrowUp, LogOut, Plus, PanelLeftClose, PanelLeft, Trash2,
    Lightbulb, BarChart2, TrendingUp, Package, Target, Settings,
    ChevronDown, Zap, MapPin, X
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
    const [loginForm, setLoginForm] = useState({ username: "", password: "" });
    const [sessions, setSessions] = useState<any[]>([]);
    const [isSidebarOpen, setIsSidebarOpen] = useState(true);
    const [scopeZone, setScopeZone] = useState<string | null>(null);
    const [scopeCity, setScopeCity] = useState<string | null>(null);
    const [lastSalesScope, setLastSalesScope] = useState<"PRIMARY" | "SECONDARY" | null>(null);
    const [zoneInput, setZoneInput] = useState("");
    const [cityInput, setCityInput] = useState("");
    const [editingScope, setEditingScope] = useState<"zone" | "city" | null>(null);
    const [suggestions, setSuggestions] = useState<{ label: string; question: string; category: string }[]>([]);
    const [suggestionsLoading, setSuggestionsLoading] = useState(true);
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const zoneInputRef = useRef<HTMLInputElement>(null);
    const cityInputRef = useRef<HTMLInputElement>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const {
        messages, pendingClarification, backendResponse, compoundState,
        addUserMessage, handleResponse, clearMessages, replaceMessages,
    } = useConversation();

    // Track sales scope from last successful backend response
    useEffect(() => {
        if (backendResponse?.raw_intent?.sales_scope) {
            setLastSalesScope(backendResponse.raw_intent.sales_scope as "PRIMARY" | "SECONDARY");
        } else if (backendResponse?.merged_intent?.sales_scope) {
            setLastSalesScope(backendResponse.merged_intent.sales_scope as "PRIMARY" | "SECONDARY");
        }
    }, [backendResponse]);

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
        const API_BASE = process.env.NEXT_PUBLIC_API_BASE;
        fetch(`${API_BASE}/api/questions?category=all&limit=4`)
            .then((r) => r.json())
            .then((d) => { if (d.questions?.length) setSuggestions(d.questions); })
            .catch(() => {})
            .finally(() => setSuggestionsLoading(false));
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

    useEffect(() => {
        if (editingScope === "zone") zoneInputRef.current?.focus();
        if (editingScope === "city") cityInputRef.current?.focus();
    }, [editingScope]);

    function commitZone() {
        const v = zoneInput.trim();
        if (v) { setScopeZone(v); setScopeCity(null); setCityInput(""); }
        setEditingScope(null);
        setZoneInput("");
    }

    function commitCity() {
        const v = cityInput.trim();
        if (v) setScopeCity(v);
        setEditingScope(null);
        setCityInput("");
    }

    function resetToNational() {
        setScopeZone(null); setScopeCity(null);
        setZoneInput(""); setCityInput(""); setEditingScope(null);
    }

    function buildScopePrefix(): string {
        if (!scopeZone && !scopeCity) return "";
        const parts: string[] = [];
        if (scopeZone) parts.push(`Zone: ${scopeZone}`);
        if (scopeCity) parts.push(`City: ${scopeCity}`);
        return `Filter results for: ${parts.join(", ")}.`;
    }

    function onSendDebounced() {
        if (debounceRef.current) return; // already pending
        debounceRef.current = setTimeout(() => { debounceRef.current = null; }, 300);
        onSend();
    }

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
                const prefix = buildScopePrefix();
                const queryWithScope = prefix ? `${prefix} ${userInput}` : userInput;
                result = await sendQuery(queryWithScope);
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
            onSendDebounced();
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
                {/* Left: editorial magazine panel */}
                <div className="hidden lg:flex lg:w-1/2 flex-col justify-between p-14 relative overflow-hidden"
                    style={{ backgroundColor: "#0A1628" }}>

                    {/* Geometric SVG accent — top right */}
                    <svg className="absolute top-0 right-0 w-72 h-72 opacity-20" viewBox="0 0 288 288" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <circle cx="240" cy="48" r="120" stroke="white" strokeWidth="1"/>
                        <circle cx="240" cy="48" r="80" stroke="#F97316" strokeWidth="0.8"/>
                        <circle cx="240" cy="48" r="40" stroke="white" strokeWidth="0.6"/>
                        <line x1="120" y1="0" x2="288" y2="168" stroke="white" strokeWidth="0.5"/>
                        <line x1="160" y1="0" x2="288" y2="128" stroke="#F97316" strokeWidth="0.4"/>
                        <line x1="200" y1="0" x2="288" y2="88" stroke="white" strokeWidth="0.3"/>
                    </svg>

                    {/* Top label */}
                    <div className="relative z-10">
                        <span className="text-xs font-bold tracking-[0.2em] uppercase" style={{ color: "#F97316" }}>
                            Enterprise CPG Intelligence
                        </span>
                    </div>

                    {/* Center: massive headline */}
                    <div className="relative z-10 flex-1 flex flex-col justify-center">
                        <h1 className="font-black text-white leading-[0.9] mb-6"
                            style={{ fontSize: "clamp(64px, 7vw, 88px)", fontWeight: 900, letterSpacing: "-0.03em" }}>
                            CPG<br />Analytics
                        </h1>
                        <p className="text-xl font-semibold mb-2" style={{ color: "#F97316" }}>
                            Ask your data anything.
                        </p>
                        <p className="text-sm" style={{ color: "#94A3B8" }}>
                            Instant SQL insights for sales, SKUs,<br />zones &amp; targets — no code required.
                        </p>
                    </div>

                    {/* Bottom: feature pills */}
                    <div className="relative z-10 flex flex-wrap gap-2">
                        {["Net Sales", "SKU Trends", "Zone Drill-down", "AI Insights"].map((label) => (
                            <span key={label}
                                className="text-xs font-semibold text-white px-4 py-2 rounded-full border"
                                style={{ backgroundColor: "rgba(255,255,255,0.08)", borderColor: "rgba(255,255,255,0.15)" }}>
                                {label}
                            </span>
                        ))}
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
        <div className="flex h-screen overflow-hidden" style={{ backgroundColor: "#0F2044", backgroundImage: "radial-gradient(circle, rgba(255,255,255,0.06) 1px, transparent 1px)", backgroundSize: "28px 28px" }}>

            {/* ── SIDEBAR ─────────────────────────────────────────────────────── */}
            {isSidebarOpen && (
                <aside className="hidden lg:flex flex-col w-72 shrink-0 transition-all duration-200" style={{ backgroundColor: "#0F2044", borderRight: "1px solid rgba(255,255,255,0.1)" }}>
                    {/* Logo row */}
                    <div className="px-5 py-5 flex items-center justify-between" style={{ borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
                        <div className="flex items-center gap-2.5">
                            <div className="w-8 h-8 gradient-mesh rounded-lg flex items-center justify-center">
                                <Zap size={15} className="text-white" />
                            </div>
                            <div>
                                <div className="text-sm font-bold text-white leading-none">CPG Analytics</div>
                                <div className="text-[10px] mt-0.5" style={{ color: "#94A3B8" }}>NL2SQL Workspace</div>
                            </div>
                        </div>
                        <button onClick={() => setIsSidebarOpen(false)} className="p-1 rounded transition-colors" style={{ color: "#94A3B8" }}>
                            <PanelLeftClose size={16} />
                        </button>
                    </div>

                    {/* Tenant pill */}
                    <div className="px-4 py-3" style={{ borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
                        <button className="w-full flex items-center justify-between rounded-lg px-3 py-2 text-sm font-medium text-white transition-colors" style={{ backgroundColor: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)" }}>
                            <span className="truncate">{user.client_name || "Organisation"}</span>
                            <ChevronDown size={14} className="shrink-0 ml-1" style={{ color: "#94A3B8" }} />
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
                        <div className="text-[10px] font-semibold uppercase tracking-wider px-2 mb-2" style={{ color: "#64748B" }}>Conversations</div>
                        {Object.entries(groupedSessions).map(([group, groupSessions]) => (
                            <div key={group} className="mb-4">
                                <div className="text-[10px] font-semibold uppercase tracking-wider px-2 mb-1" style={{ color: "#64748B" }}>{group}</div>
                                <div className="space-y-0.5">
                                    {groupSessions.map((s) => (
                                        <div key={s.session_id} className="flex items-center gap-1 group">
                                            <button
                                                onClick={() => loadSession(s.session_id)}
                                                className="flex-1 text-left text-sm px-3 py-2 rounded-lg truncate transition-colors"
                                                style={sessionId === s.session_id
                                                    ? { backgroundColor: "#1E3A5F", color: "#ffffff", borderLeft: "3px solid #F97316", paddingLeft: "9px" }
                                                    : { color: "#CBD5E1" }
                                                }
                                                onMouseEnter={(e) => { if (sessionId !== s.session_id) (e.currentTarget as HTMLElement).style.backgroundColor = "#1E3A5F"; }}
                                                onMouseLeave={(e) => { if (sessionId !== s.session_id) (e.currentTarget as HTMLElement).style.backgroundColor = "transparent"; }}
                                            >
                                                {s.title || "New conversation"}
                                            </button>
                                            <button
                                                onClick={(e) => { e.stopPropagation(); handleDeleteSession(s.session_id); }}
                                                className="p-1.5 rounded opacity-0 group-hover:opacity-100 transition-all shrink-0"
                                                style={{ color: "#64748B" }}
                                                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = "#f87171"; }}
                                                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = "#64748B"; }}
                                            >
                                                <Trash2 size={13} />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        ))}
                        {sessions.length === 0 && (
                            <p className="text-xs px-2 py-2" style={{ color: "#64748B" }}>No conversations yet.</p>
                        )}
                    </div>

                    {/* User footer */}
                    <div className="px-4 py-3 flex items-center gap-3" style={{ borderTop: "1px solid rgba(255,255,255,0.08)" }}>
                        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-orange-400 to-indigo-500 flex items-center justify-center text-white text-xs font-bold shrink-0">
                            {(user.full_name || user.username || "U")[0].toUpperCase()}
                        </div>
                        <div className="flex-1 min-w-0">
                            <div className="text-sm font-semibold text-white truncate">{user.full_name || user.username}</div>
                            <div className="text-[11px] truncate" style={{ color: "#94A3B8" }}>{user.role}</div>
                        </div>
                        <button onClick={handleLogout} className="p-1.5 rounded transition-colors" style={{ color: "#94A3B8" }} title="Sign out">
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
                <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6 flex flex-col items-center" style={{ backgroundColor: "transparent" }}>
                    <div className="w-full max-w-4xl flex flex-col h-full">

                        {/* Empty state hero */}
                        {messages.length === 0 && (
                            <div className="flex flex-col items-center justify-center h-full rounded-3xl py-16 px-6 relative"
                                style={{ backgroundColor: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}>
                                <div className="relative z-10 text-center mb-10">
                                    <h2 className="text-4xl font-extrabold tracking-tight mb-3" style={{ color: "#ffffff" }}>
                                        What do you want to know?
                                    </h2>
                                    <p className="text-lg" style={{ color: "#94A3B8" }}>
                                        Ask anything about your CPG sales, SKUs, zones, and targets
                                    </p>
                                </div>
                                {/* Suggestion cards 2x2 */}
                                <div className="relative z-10 grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-2xl">
                                    {suggestionsLoading ? (
                                        [0, 1, 2, 3].map((i) => (
                                            <div key={i} className="card p-4 flex gap-3 items-start animate-pulse">
                                                <div className="shrink-0 w-9 h-9 bg-gray-200 rounded-xl" />
                                                <div className="flex-1 space-y-2 py-1">
                                                    <div className="h-3 bg-gray-200 rounded w-2/3" />
                                                    <div className="h-3 bg-gray-200 rounded w-full" />
                                                    <div className="h-3 bg-gray-200 rounded w-4/5" />
                                                </div>
                                            </div>
                                        ))
                                    ) : (suggestions.length > 0 ? suggestions : [
                                        { label: "Net Sales by Zone", question: "Show net sales breakdown for last 30 days", category: "sales_performance" },
                                        { label: "Top SKU Revenue", question: "Top 5 products by revenue this month", category: "sku_product" },
                                        { label: "SKU Growth", question: "Which SKUs had the highest growth last quarter?", category: "sku_product" },
                                        { label: "Target vs Actual", question: "Sales performance by region vs target", category: "target_vs_actual" },
                                    ]).map((s) => {
                                        const iconMap: Record<string, React.ReactNode> = {
                                            sales_performance: <BarChart2 size={20} className="text-orange-500" />,
                                            sku_product: <Package size={20} className="text-emerald-500" />,
                                            regional_zone: <MapPin size={20} className="text-indigo-500" />,
                                            target_vs_actual: <Target size={20} className="text-rose-500" />,
                                            risk_anomaly: <TrendingUp size={20} className="text-amber-500" />,
                                        };
                                        return (
                                            <button
                                                key={s.label}
                                                onClick={() => setInput(s.question)}
                                                className="card card-hover text-left p-4 flex gap-3 items-start hover:border-orange-200 group"
                                            >
                                                <div className="shrink-0 w-9 h-9 bg-gray-50 rounded-xl flex items-center justify-center group-hover:bg-orange-50 transition-colors">
                                                    {iconMap[s.category] ?? <BarChart2 size={20} className="text-orange-500" />}
                                                </div>
                                                <div>
                                                    <div className="font-semibold text-gray-900 text-sm">{s.label}</div>
                                                    <div className="text-xs text-gray-500 mt-0.5">{s.question}</div>
                                                </div>
                                            </button>
                                        );
                                    })}
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
                            <div className="flex justify-start mb-6">
                                <div className="w-full max-w-2xl bg-gray-50 border border-gray-200 rounded-xl px-6 py-5 shadow-sm space-y-3 animate-pulse">
                                    {/* Pulsing dots + status line */}
                                    <div className="flex items-center gap-3">
                                        <div className="flex gap-1">
                                            <span className="w-2 h-2 rounded-full bg-orange-300 animate-bounce [animation-delay:0ms]" />
                                            <span className="w-2 h-2 rounded-full bg-orange-300 animate-bounce [animation-delay:150ms]" />
                                            <span className="w-2 h-2 rounded-full bg-orange-300 animate-bounce [animation-delay:300ms]" />
                                        </div>
                                        <div className="h-3 bg-gray-200 rounded w-36" />
                                    </div>
                                    {/* Skeleton content lines */}
                                    <div className="space-y-2 pt-1">
                                        <div className="h-3 bg-gray-200 rounded w-3/4" />
                                        <div className="h-3 bg-gray-200 rounded w-1/2" />
                                    </div>
                                    {/* Skeleton metric card */}
                                    <div className="flex gap-3 pt-1">
                                        <div className="h-8 bg-gray-200 rounded w-24" />
                                        <div className="h-8 bg-gray-200 rounded w-24" />
                                        <div className="h-8 bg-gray-200 rounded w-24" />
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

                    {/* Scope-aware dimension chips */}
                    {lastSalesScope && (
                        <div className="flex flex-wrap gap-1.5 mb-2 px-1">
                            <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-bold border ${
                                lastSalesScope === "PRIMARY"
                                    ? "bg-indigo-50 text-indigo-700 border-indigo-200"
                                    : "bg-orange-50 text-orange-700 border-orange-200"
                            }`}>
                                {lastSalesScope === "PRIMARY" ? "Primary Sales" : "Secondary Sales"}
                            </span>
                            {/* Common dimensions — always visible */}
                            {["zone","state","brand","category","sku","distributor","asm","zsm"].map((d) => (
                                <button key={d} onClick={() => setInput((prev) => prev ? `${prev} by ${d}` : `Show by ${d}`)}
                                    className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 text-gray-600 border border-gray-200 hover:bg-gray-200 transition-colors">
                                    {d}
                                </button>
                            ))}
                            {/* Secondary-only dimensions — hidden for PRIMARY */}
                            {lastSalesScope === "SECONDARY" && ["retailer","route","salesrep"].map((d) => (
                                <button key={d} onClick={() => setInput((prev) => prev ? `${prev} by ${d}` : `Show by ${d}`)}
                                    className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-orange-50 text-orange-600 border border-orange-200 hover:bg-orange-100 transition-colors">
                                    {d}
                                </button>
                            ))}
                        </div>
                    )}

                    <div className={`flex items-end gap-2 bg-white border rounded-2xl px-4 py-2.5 shadow-2xl transition-all duration-150 ${
                        !isBackendAvailable ? "border-red-200" : "border-white/20 focus-within:border-orange-300 focus-within:shadow-[0_0_0_3px_rgba(249,115,22,0.15)]"
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
                            onClick={() => { onSendDebounced(); const ta = document.querySelector("textarea"); if (ta) ta.style.height = "auto"; }}
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
