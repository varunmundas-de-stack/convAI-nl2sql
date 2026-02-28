/**
 * Parse user clarification answers into structured format expected by backend
 */
export function parseClarificationAnswers(
    userInput: string,
    missingFields: string[]
): Record<string, any> {
    const answers: Record<string, any> = {};

    // Split by comma if multiple answers
    const userAnswers = userInput.includes(",")
        ? userInput.split(",").map((a) => a.trim())
        : [userInput.trim()];

    missingFields.forEach((field, idx) => {
        const answer = userAnswers[idx];
        if (!answer) return; // Only process answers that were actually provided

        if (field === "time_dimension") {
            // Parse time dimension: expect "granularity" or "dimension, granularity"
            // Examples: "day", "month", "invoice_date, day"
            const parts = answer.includes(",")
                ? answer.split(",").map(p => p.trim())
                : [answer.trim()];

            if (parts.length === 1) {
                // Only granularity provided, use default dimension
                answers[field] = {
                    dimension: "invoice_date", // default
                    granularity: parts[0].toLowerCase()
                };
            } else {
                // Both dimension and granularity provided
                answers[field] = {
                    dimension: parts[0],
                    granularity: parts[1].toLowerCase()
                };
            }
        } else if (field === "time_range") {
            // Parse time range: expect window name
            // Examples: "last_30_days", "last 30 days", "month_to_date", "MTD"
            const normalized = answer
                .toLowerCase()
                .replace(/\s+/g, "_") // "last 30 days" -> "last_30_days"
                .replace(/[^a-z0-9_]/g, ""); // remove special chars

            answers[field] = {
                window: normalized
            };
        } else {
            // For other fields, use the answer as-is
            answers[field] = answer;
        }
    });

    return answers;
}
