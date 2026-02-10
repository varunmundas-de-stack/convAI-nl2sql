import { ChatResponse } from "@/types/chat";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

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
        };
    }

    // Handle error
    if (backendResponse.success === false || backendResponse.error) {
        return {
            type: "error",
            message: backendResponse.error || "An error occurred",
        };
    }

    // Handle successful data response
    if (backendResponse.success && backendResponse.data) {
        const data = backendResponse.data;

        // Check if visualization exists
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
}> {
    const res = await fetch(`${API_BASE}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
    });

    const backendResponse = await res.json();

    // Transform the backend response to frontend format
    return {
        response: transformBackendResponse(backendResponse),
        raw: backendResponse,
    };
}

export async function clarify(payload: {
    request_id: string;
    answers: Record<string, any>;
}): Promise<{
    response: ChatResponse;
    raw: any;
}> {
    const res = await fetch(`${API_BASE}/clarify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });

    const backendResponse = await res.json();

    // Transform the backend response to frontend format
    return {
        response: transformBackendResponse(backendResponse),
        raw: backendResponse,
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
