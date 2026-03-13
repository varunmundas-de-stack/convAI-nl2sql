import { ChatResponse } from "@/types/chat";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE;

// Store session ID in memory for the current conversation
let currentSessionId: string | null = null;

/**
 * Get the current session ID (if any)
 */
export function getCurrentSessionId(): string | null {
    return currentSessionId;
}

/**
 * Store the session ID received from backend
 */
export function setSessionId(sessionId: string): void {
    if (sessionId && sessionId !== currentSessionId) {
        currentSessionId = sessionId;
        console.log(`[Session] Session ID updated: ${sessionId}`);
    }
}

/**
 * Clear the current session (start a new conversation)
 */
export function resetSession(): void {
    currentSessionId = null;
    console.log("[Session] Session reset - new conversation started");
}

export async function healthCheck() {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) throw new Error("Backend unavailable");
    return res.json();
}

/**
 * Transform backend response to frontend ChatResponse format
 */
function transformBackendResponse(backendResponse: any): ChatResponse {
    // Handle clarification request
    if (backendResponse.clarification === true) {
        const questions = Array.isArray(backendResponse.clarification_message)
            ? backendResponse.clarification_message.join("\n\n")
            : backendResponse.clarification_message;

        return {
            type: "clarification_required",
            question: questions,
            allowed_values: backendResponse.allowed_values,
            missing_fields: backendResponse.missing_fields,
        };
    }

    // Handle error
    if (backendResponse.success === false || backendResponse.error) {
        return {
            type: "error",
            message: backendResponse.error || "An error occurred",
        };
    }

    // Handle successful data response with NEW visual_spec format
    if (backendResponse.success && backendResponse.visual_spec) {
        return {
            type: "chart",
            chartType: backendResponse.visual_spec.chart_type || "bar",
            data: {
                visual_spec: backendResponse.visual_spec,
                refined_insights: backendResponse.refined_insights || null,
            },
        };
    }

    // Handle successful data response with LEGACY visualization format
    if (backendResponse.success && backendResponse.data) {
        const data = backendResponse.data;

        // Check if visualization exists (legacy)
        if (backendResponse.visualization) {
            const viz = backendResponse.visualization;

            // Handle number_card and table separately (they might use different rendering)
            if (viz.visualization_type === "number_card" || viz.visualization_type === "table") {
                return {
                    type: "chart",
                    chartType: "bar", // Placeholder, not used for number_card
                    data: viz, // Pass the full visualization object
                    explanation: viz.description || viz.title,
                };
            }

            // Determine chart type from visualization_type
            let chartType: "bar" | "line" | "pie" = "bar";
            if (viz.visualization_type === "line_chart") chartType = "line";
            else if (viz.visualization_type === "pie_chart") chartType = "pie";
            else if (viz.visualization_type === "bar_chart") chartType = "bar";

            return {
                type: "chart",
                chartType,
                data: viz, // Pass the full visualization object
                explanation: viz.description || viz.title,
            };
        }

        // If no visualization but has data, return as table
        if (Array.isArray(data) && data.length > 0) {
            const columns = Object.keys(data[0]);
            return {
                type: "table",
                columns,
                rows: data,
                explanation: backendResponse.raw_intent?.intent_type
                    ? `Showing ${backendResponse.raw_intent.intent_type} results`
                    : undefined,
            };
        }

        // Data exists but empty
        return {
            type: "text",
            content: "No data found for your query.",
        };
    }

    // Fallback to text response
    return {
        type: "text",
        content: backendResponse.message || "Query processed successfully.",
    };
}

export async function sendQuery(query: string): Promise<{
    response: ChatResponse;
    raw: any;
    sessionId: string;
}> {
    const requestBody: any = { query };

    // Include session_id if we have one (for follow-up queries)
    if (currentSessionId) {
        requestBody.session_id = currentSessionId;
        console.log(`[Session] Sending query with existing session_id: ${currentSessionId}`);
    } else {
        console.log(`[Session] Sending first query - backend will generate session_id`);
    }

    const res = await fetch(`${API_BASE}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
    });

    const backendResponse = await res.json();

    // Extract and store session_id from backend response
    if (backendResponse.session_id) {
        setSessionId(backendResponse.session_id);
    }

    // Transform the backend response to frontend format
    return {
        response: transformBackendResponse(backendResponse),
        raw: backendResponse,
        sessionId: backendResponse.session_id || currentSessionId || "unknown",
    };
}

export async function clarify(payload: {
    request_id: string;
    answers: Record<string, any>;
}): Promise<{
    response: ChatResponse;
    raw: any;
    sessionId: string;
}> {
    console.log(`[Session] Sending clarification for request_id: ${payload.request_id}`);

    const res = await fetch(`${API_BASE}/clarify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            request_id: payload.request_id,
            answers: payload.answers,
            // Note: session_id is NOT needed here - it's tracked via request_id
        }),
    });

    const backendResponse = await res.json();

    // Extract and store session_id from backend response if present
    if (backendResponse.session_id) {
        setSessionId(backendResponse.session_id);
    }

    // Transform the backend response to frontend format
    return {
        response: transformBackendResponse(backendResponse),
        raw: backendResponse,
        sessionId: backendResponse.session_id || currentSessionId || "unknown",
    };
}

export async function getCatalogMetrics() {
    return fetch(`${API_BASE}/catalog/metrics`).then((r) => r.json());
}

export async function getCatalogDimensions() {
    return fetch(`${API_BASE}/catalog/dimensions`).then((r) => r.json());
}

export async function getCatalogTimeWindows() {
    return fetch(`${API_BASE}/catalog/time-windows`).then((r) => r.json());
}

export async function submitFeedback(payload: {
    request_id: string;
    query: string;
    response_summary: string;
    prompt_version: string;
    rating: number;
    ab_group?: string | null;
    correction?: string | null;
    full_response?: string | null;
    sql_query?: string | null;
}): Promise<void> {
    const res = await fetch(`${API_BASE}/rlhf/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        throw new Error(`Feedback submission failed: ${res.status}`);
    }
}
