export interface ActionStep {
    id: string;
    title: string;
    description: string;
    query?: string;
    inputLabel?: string;
    inputType?: "select" | "text" | "none";
    options?: { value: string; label: string }[];
}

export interface ActionPipeline {
    id: string;
    label: string;
    icon: string;
    description: string;
    steps: ActionStep[];
}

export const ACTION_PIPELINES: ActionPipeline[] = [
    {
        id: "zone-coverage-review",
        label: "Zone Coverage Review",
        icon: "Map",
        description: "Identify underperforming zones and recommend field actions",
        steps: [
            { id: "select-zone", title: "Select Zone", description: "Which zone do you want to review?", inputType: "select", inputLabel: "Zone", options: [{ value: "all", label: "All Zones" }, { value: "north", label: "North" }, { value: "south", label: "South" }, { value: "east", label: "East" }, { value: "west", label: "West" }] },
            { id: "fetch-coverage", title: "Fetch Coverage Data", description: "Loading zone sales vs target breakdown", query: "Show secondary net sales by zone last 30 days with target achievement", inputType: "none" },
            { id: "identify-gaps", title: "Identify Gaps", description: "Highlight zones below 80% target achievement", query: "Show zones below 80% of sales target this month with gap percentage", inputType: "none" },
            { id: "action-plan", title: "Generate Action Plan", description: "Recommend distributor push and field rep targets", query: "For underperforming zones suggest field actions and distributor targets", inputType: "none" },
        ],
    },
    {
        id: "sku-recovery-plan",
        label: "SKU Recovery Plan",
        icon: "Package",
        description: "Identify declining SKUs and build a recovery strategy",
        steps: [
            { id: "select-category", title: "Select Category", description: "Filter by product category", inputType: "select", inputLabel: "Category", options: [{ value: "all", label: "All Categories" }, { value: "chocolate", label: "Chocolate" }, { value: "beverage", label: "Beverage" }, { value: "dairy", label: "Dairy" }, { value: "snacks", label: "Snacks" }] },
            { id: "identify-declining", title: "Identify Declining SKUs", description: "Finding SKUs with negative growth trend", query: "Show SKUs with declining sales trend last 30 days vs previous 30 days", inputType: "none" },
            { id: "root-cause", title: "Root Cause Analysis", description: "Checking distributor coverage and stockouts", query: "Which declining SKUs have low distributor coverage or stockout signals?", inputType: "none" },
            { id: "recovery-actions", title: "Recovery Actions", description: "Push lists and promotional recommendations", query: "Recommend recovery actions for top 5 declining SKUs including distributor push", inputType: "none" },
        ],
    },
    {
        id: "distributor-push-list",
        label: "Distributor Push List",
        icon: "Users",
        description: "Rank distributors by performance and create push priority list",
        steps: [
            { id: "select-period", title: "Select Period", description: "Which period to evaluate?", inputType: "select", inputLabel: "Period", options: [{ value: "7d", label: "Last 7 Days" }, { value: "30d", label: "Last 30 Days" }, { value: "qtd", label: "Quarter to Date" }] },
            { id: "rank-distributors", title: "Rank Distributors", description: "Loading distributor performance data", query: "Show top and bottom 10 distributors by secondary sales last 30 days", inputType: "none" },
            { id: "identify-underperformers", title: "Flag Underperformers", description: "Distributors below 70% of their target", query: "Show distributors below 70% target achievement this month", inputType: "none" },
            { id: "push-priorities", title: "Create Push List", description: "Prioritized push list with contact and SKU recommendations", query: "Generate prioritized distributor push list with recommended SKUs for each", inputType: "none" },
        ],
    },
    {
        id: "trend-acceleration",
        label: "Trend Acceleration",
        icon: "TrendingUp",
        description: "Find fast-growing signals and amplify momentum",
        steps: [
            { id: "select-metric", title: "Select Metric", description: "What metric to track?", inputType: "select", inputLabel: "Metric", options: [{ value: "net_sales", label: "Net Sales" }, { value: "volume", label: "Volume" }, { value: "sku_count", label: "Active SKUs" }] },
            { id: "find-accelerators", title: "Find Accelerators", description: "Identifying fast-growing SKUs and zones", query: "Show SKUs and zones with fastest growth rate last 14 days", inputType: "none" },
            { id: "validate-trend", title: "Validate Trend", description: "Check consistency across distributors", query: "Validate growth trend by distributor for top growing SKUs last 30 days", inputType: "none" },
            { id: "amplify-plan", title: "Amplify Plan", description: "Actions to accelerate momentum further", query: "Recommend actions to accelerate growth for fast-trending SKUs and zones", inputType: "none" },
        ],
    },
];

export type ActiveAction = {
    pipelineId: string;
    currentStep: number;
    stepData: Record<string, string>;
    startedAt: number;
};

export const ACTIVE_ACTION_KEY = "nl2sql_active_action";

export function getActiveAction(): ActiveAction | null {
    if (typeof window === "undefined") return null;
    try {
        const raw = localStorage.getItem(ACTIVE_ACTION_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch { return null; }
}

export function saveActiveAction(action: ActiveAction): void {
    if (typeof window !== "undefined")
        localStorage.setItem(ACTIVE_ACTION_KEY, JSON.stringify(action));
}

export function clearActiveAction(): void {
    if (typeof window !== "undefined")
        localStorage.removeItem(ACTIVE_ACTION_KEY);
}

export function getPipeline(id: string): ActionPipeline | undefined {
    return ACTION_PIPELINES.find(p => p.id === id);
}

export function serializeActionContext(action: ActiveAction): string {
    const pipeline = getPipeline(action.pipelineId);
    if (!pipeline) return "";
    const completedSteps = pipeline.steps.slice(0, action.currentStep);
    const lines = [
        `[Active Action: ${pipeline.label}]`,
        `Progress: Step ${action.currentStep}/${pipeline.steps.length}`,
        ...Object.entries(action.stepData).map(([k, v]) => `- ${k}: ${v}`),
        `Completed steps: ${completedSteps.map(s => s.title).join(" → ")}`,
    ];
    return lines.join("\n");
}
