"use client";

import { TableResponse } from "@/types/chat";

interface TableRendererProps {
    data: TableResponse;
}

// Clean column name for display (remove table prefixes, format nicely)
function cleanColumnName(col: string): string {
    if (!col) return "Value";
    
    // Remove table prefixes like "fact_secondary_sales.", "dim_product.", etc.
    let cleaned = col;
    
    // Strip common table prefixes
    const prefixes = [
        "fact_secondary_sales.",
        "fact_primary_sales.",
        "fact secondary sales.",
        "fact primary sales.",
        "dim_product.",
        "dim_region.",
        "dim_time.",
        "fact_",
        "dim_",
    ];
    
    for (const prefix of prefixes) {
        if (cleaned.toLowerCase().startsWith(prefix.toLowerCase())) {
            cleaned = cleaned.substring(prefix.length);
            break;
        }
    }
    
    // Remove any remaining dots by taking the last segment
    if (cleaned.includes(".")) {
        const parts = cleaned.split(".");
        cleaned = parts[parts.length - 1];
    }
    
    // Replace underscores with spaces and title case
    return cleaned.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

// Format cell values with proper number and date formatting
function formatCellValue(value: any): string {
    if (value === null || value === undefined || value === "") {
        return "-";
    }
    
    // Handle date strings (ISO 8601 format)
    if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(value)) {
        try {
            const date = new Date(value);
            // Format as: DD MMM YYYY (e.g., "01 Oct 2025")
            return date.toLocaleDateString('en-GB', { 
                day: '2-digit', 
                month: 'short', 
                year: 'numeric' 
            });
        } catch {
            return String(value);
        }
    }
    
    // Handle numbers - add comma separators for large numbers
    if (typeof value === "number") {
        // For integers or numbers with less than 2 decimal places, show as integer
        if (Number.isInteger(value) || Math.abs(value) > 100) {
            return value.toLocaleString('en-IN', { maximumFractionDigits: 0 });
        }
        // For small decimal numbers, show 2 decimal places
        return value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    
    return String(value);
}

// Detect if a column contains numeric data (for right alignment)
function isNumericColumn(rows: Array<Record<string, string | number>>, columnName: string): boolean {
    if (rows.length === 0) return false;
    
    // Check first 5 non-null values
    const samples = rows
        .slice(0, 5)
        .map(row => row[columnName])
        .filter(val => val !== null && val !== undefined);
    
    if (samples.length === 0) return false;
    
    // If any sample is a number, consider it numeric
    return samples.some(val => typeof val === "number");
}

export default function TableRenderer({ data }: TableRendererProps) {
    const { columns, rows, explanation } = data;
    
    // Determine which columns are numeric for alignment
    const numericColumns = new Set(
        columns.filter(col => isNumericColumn(rows, col))
    );

    return (
        <div className="space-y-3">
            {explanation && (
                <p className="text-sm text-gray-700 italic bg-blue-50 border border-blue-200 rounded-lg px-4 py-2">
                    {explanation}
                </p>
            )}
            
            {/* Row count indicator */}
            <div className="flex items-center justify-between text-xs text-gray-500">
                <span>{rows.length} {rows.length === 1 ? 'row' : 'rows'}</span>
                {rows.length > 100 && (
                    <span className="text-amber-600 font-medium">
                        Large dataset - scroll to view all
                    </span>
                )}
            </div>
            
            <div className="overflow-x-auto rounded-lg border border-gray-200 shadow-sm bg-white">
                <div className="max-h-[600px] overflow-y-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                        <thead className="bg-gray-50 sticky top-0 z-10">
                            <tr>
                                {columns.map((col, idx) => (
                                    <th
                                        key={idx}
                                        className={`px-6 py-3 text-xs font-semibold text-gray-700 uppercase tracking-wider border-b-2 border-gray-200 ${
                                            numericColumns.has(col) ? 'text-right' : 'text-left'
                                        }`}
                                    >
                                        {cleanColumnName(col)}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody className="bg-white divide-y divide-gray-200">
                            {rows.length === 0 ? (
                                <tr>
                                    <td 
                                        colSpan={columns.length} 
                                        className="px-6 py-8 text-center text-sm text-gray-500"
                                    >
                                        No data available
                                    </td>
                                </tr>
                            ) : (
                                rows.map((row, rowIdx) => (
                                    <tr 
                                        key={rowIdx} 
                                        className="hover:bg-gray-50 transition-colors duration-150"
                                    >
                                        {columns.map((col, colIdx) => {
                                            const value = row[col];
                                            const isNumeric = numericColumns.has(col);
                                            
                                            return (
                                                <td
                                                    key={colIdx}
                                                    className={`px-6 py-4 text-sm text-gray-900 ${
                                                        isNumeric 
                                                            ? 'text-right font-mono' 
                                                            : 'text-left'
                                                    }`}
                                                >
                                                    {formatCellValue(value)}
                                                </td>
                                            );
                                        })}
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}
