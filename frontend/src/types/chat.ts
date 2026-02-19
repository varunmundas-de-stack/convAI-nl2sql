export type ChatRole = "user" | "assistant" | "system";

export type ChatMessage = {
    id: string;
    role: ChatRole;
    content: string;
};

export type TableResponse = {
    type: "table";
    columns: string[];
    rows: Array<Record<string, string | number>>;
    explanation?: string;
};

export type ChartResponse = {
    type: "chart";
    chartType: "bar" | "line" | "pie";
    data: any;
    explanation?: string;
};

export type TextResponse = {
    type: "text";
    content: string;
};

export type ClarificationResponse = {
    type: "clarification_required";
    question: string;
};

export type ErrorResponse = {
    type: "error";
    message: string;
};

export type ChatResponse =
    | TextResponse
    | TableResponse
    | ChartResponse
    | ClarificationResponse
    | ErrorResponse;
