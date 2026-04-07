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
    allowed_values?: string[];
    missing_fields?: string[];
};

export type ErrorResponse = {
    type: "error";
    message: string;
};

export type CompoundPartialResultsResponse = {
    type: "compound_partial_results";
    original_query: string;
    completed_subqueries: Array<{
        index: number;
        query: string;
        result: any;
        status: "completed";
    }>;
    pending_subqueries: Array<{
        index: number;
        query: string;
        status: "pending_dependencies" | "error" | "clarifying";
        reason?: string;
        blocked_by?: number[];
        error?: {
            type: string;
            message: string;
        };
    }>;
    visual_spec: {
        chart_type: "compound_sections_partial";
        sections: Array<{
            subquery_index: number;
            subquery_text: string;
            visual_spec: any;
            status: "completed" | "pending_dependencies" | "error" | "clarifying";
            reason?: string;
            blocked_by?: number[];
        }>;
        total_sections: number;
        completed_sections: number;
        pending_sections: number;
        is_partial: true;
    };
    compound_metadata: {
        total_subqueries: number;
        completed_count: number;
        pending_count: number;
    };
};

export type CompoundCompleteResultsResponse = {
    type: "compound_complete_results";
    original_query: string;
    completed_subqueries: Array<{
        index: number;
        query: string;
        result: any;
    }>;
    visual_spec: {
        chart_type: "compound_sections";
        sections: Array<{
            subquery_index: number;
            subquery_text: string;
            visual_spec: any;
            status: "completed";
        }>;
        total_sections: number;
        completed_sections: number;
        pending_sections: 0;
        is_partial: false;
    };
    compound_metadata: {
        total_subqueries: number;
        completed_count: number;
        pending_count: 0;
    };
};

export type CompoundClarificationRequiredResponse = {
    type: "compound_clarification_required";
    original_query: string;
    completed_subqueries: Array<{
        index: number;
        query: string;
        result: any;
    }>;
    pending_clarification: {
        subquery_index: number;
        subquery_text: string;
        clarification: {
            request_id: string;
            field: string;
            question: string;
            options: string[];
            multi_select: boolean;
            context?: string;
        };
    };
    compound_state: {
        request_id: string;
        session_id: string;
        total_subqueries: number;
        completed_count: number;
        dependencies: Record<number, number[]>;
    };
};

export type ChatResponse =
    | TextResponse
    | TableResponse
    | ChartResponse
    | ClarificationResponse
    | CompoundPartialResultsResponse
    | CompoundCompleteResultsResponse
    | CompoundClarificationRequiredResponse
    | ErrorResponse;
