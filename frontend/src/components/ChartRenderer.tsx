"use client";

import { useEffect, useState, useMemo } from "react";
import { TrendingUp, TrendingDown, Minus, BarChart2, Table2, LayoutGrid } from "lucide-react";
import { BarChart, Bar, LineChart, Line, PieChart, Pie, Cell, ReferenceLine, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend, ResponsiveContainer } from "recharts";
import TableRenderer from "./TableRenderer";

// Types matching backend VisualSpec
interface VisualSpec {
    chart_type: string;
    title?: string;
    subtitle?: string;
    x_axis?: Axis;
    y_axis?: Axis;
    series?: any[];
    annotations?: InsightAnnotation[];
    markers?: Marker[];
    primary_value?: string;
    primary_label?: string;
    secondary_value?: string;
    secondary_label?: string;
    direction?: "up" | "down" | "flat" | "unknown";
    trend_slope?: number;
    columns?: string[];
    rows?: any[];
    empty?: boolean;
    pivot_config?: {
        index_dimension: string;
        stack_dimension: string;
        stack_keys: string[];
    };
    data?: any[];
    x_axis_key?: string;
}

interface Axis {
    label: string;
    values?: any[];  // For categorical/time: labels; For linear: tick positions
    format?: string;
    axis_type?: "time" | "categorical" | "linear";
}

interface DataSeries {
    label: string;
    values: any[];  // Actual data values
    emphasis?: string;
    color_hint?: string;
    point_emphasis?: string[];
    point_colors?: (string | null)[];
}

interface InsightAnnotation {
    text: string;
    severity: "low" | "medium" | "high" | "critical";
    direction?: "up" | "down" | "flat" | "unknown";
    position?: string;
}

interface Marker {
    marker_type: "outlier" | "trend_line" | "threshold" | "annotation" | "peak" | "trough";
    label: string;
    position?: any;
    value?: number;
    emphasis?: string;
}

interface RefinedInsights {
    insights?: any[];
    executive_summary?: string;
    key_risks?: Record<string, string>;
    possible_drivers?: Record<string, string>;
    recommendations?: Record<string, string>;
}

interface ChartRendererProps {
    visual_spec?: VisualSpec;
    refined_insights?: RefinedInsights;
}

export default function ChartRenderer({ visual_spec, refined_insights }: ChartRendererProps) {
    const [isClient, setIsClient] = useState(false);
    const [viewMode, setViewMode] = useState<"chart" | "table">("chart");

    useEffect(() => {
        setIsClient(true);
    }, []);

    // Build a flat column/row dataset from the visual_spec for the table view
    const tableData = useMemo(() => {
        if (!visual_spec) return { columns: [], rows: [] };

        // Prefer the raw columns/rows the backend attaches to every spec.
        // This gives all DB columns (all group_by dims + metric), not just
        // the x-axis dim + series that the chart builder picks.
        if (visual_spec.columns && visual_spec.rows && visual_spec.rows.length > 0) {
            return { columns: visual_spec.columns, rows: visual_spec.rows };
        }

        // Fallback: for native table specs with rows but no chart axes
        if (visual_spec.chart_type === "table" && visual_spec.columns && visual_spec.rows) {
            return { columns: visual_spec.columns, rows: visual_spec.rows };
        }

        // Legacy fallback: reconstruct from x_axis labels + series values
        const xLabels: any[] = visual_spec.x_axis?.values ?? [];
        const series = visual_spec.series ?? [];
        if (xLabels.length === 0 && series.length === 0) return { columns: [], rows: [] };

        const columns: string[] = [
            visual_spec.x_axis?.label || "Category",
            ...series.map(s => s.label || "Value"),
        ];

        const rows = xLabels.map((label, i) => {
            const row: Record<string, any> = { [columns[0]]: label };
            series.forEach((s, si) => {
                row[columns[si + 1]] = s.values?.[i] ?? null;
            });
            return row;
        });

        // For number_card / specs with no x labels, collapse series into single rows
        if (xLabels.length === 0 && series.length > 0) {
            const row: Record<string, any> = {};
            series.forEach(s => { row[s.label || "Value"] = s.values?.[0] ?? null; });
            return { columns: series.map(s => s.label || "Value"), rows: [row] };
        }

        return { columns, rows };
    }, [visual_spec]);

    if (!isClient) {
        return (
            <div className="bg-white p-6 rounded-lg border border-gray-200 h-[400px] flex items-center justify-center">
                <p className="text-gray-500">Loading chart...</p>
            </div>
        );
    }

    if (!visual_spec) {
        return (
            <div className="bg-white p-6 rounded-lg border border-gray-200">
                <p className="text-gray-500">No visualization data available</p>
            </div>
        );
    }

    if (visual_spec.empty) {
        return (
            <div className="bg-white p-6 rounded-lg border border-gray-200">
                <p className="text-gray-500">No data returned for this query</p>
            </div>
        );
    }

    const isChartType = visual_spec.chart_type !== "number_card" && visual_spec.chart_type !== "table";
    const { chart_type, title, subtitle, primary_value, primary_label, secondary_value, secondary_label, direction, trend_slope } = visual_spec;

    const keyRisksEntries = Object.entries(refined_insights?.key_risks || {});
    const possibleDriversEntries = Object.entries(refined_insights?.possible_drivers || {});
    const recommendationsEntries = Object.entries(refined_insights?.recommendations || {});

    return (
        <div className="space-y-4">

            {/* Title Section
            {title && (
                <div className="space-y-1">
                    <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
                    {subtitle && <p className="text-sm text-gray-600">{subtitle}</p>}
                </div>
            )} */}

            {/* Executive Summary (Always Visible) */}
            {refined_insights?.executive_summary && (
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                    <h4 className="text-xs font-bold text-blue-900 mb-2 uppercase tracking-wide">Executive Summary</h4>
                    <p className="text-sm text-blue-800 leading-relaxed font-medium">{refined_insights.executive_summary}</p>
                </div>
            )}

            {/* Narrative Panels: Key Risks / Possible Drivers / Recommendations */}
            {(keyRisksEntries.length > 0 || possibleDriversEntries.length > 0 || recommendationsEntries.length > 0) && (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">

                    {/* Key Risks */}
                    {keyRisksEntries.length > 0 && (
                        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                            <h4 className="text-xs font-bold text-red-800 mb-3 uppercase tracking-wide flex items-center gap-1.5">
                                <span aria-hidden="true">⚠️</span> Key Risks
                            </h4>
                            <ul className="space-y-2">
                                {keyRisksEntries.map(([key, risk]) => (
                                    <li key={key} className="flex items-start gap-2">
                                        <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-red-400 flex-shrink-0" aria-hidden="true" />
                                        <span className="text-sm text-red-900 leading-snug">{risk}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}

                    {/* Possible Drivers */}
                    {possibleDriversEntries.length > 0 && (
                        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
                            <h4 className="text-xs font-bold text-amber-800 mb-3 uppercase tracking-wide flex items-center gap-1.5">
                                <span aria-hidden="true">🔍</span> Possible Drivers
                            </h4>
                            <ul className="space-y-2">
                                {possibleDriversEntries.map(([key, driver]) => (
                                    <li key={key} className="flex items-start gap-2">
                                        <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0" aria-hidden="true" />
                                        <span className="text-sm text-amber-900 leading-snug">{driver}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}

                    {/* Recommendations */}
                    {recommendationsEntries.length > 0 && (
                        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                            <h4 className="text-xs font-bold text-green-800 mb-3 uppercase tracking-wide flex items-center gap-1.5">
                                <span aria-hidden="true">✅</span> Recommendations
                            </h4>
                            <ul className="space-y-2">
                                {recommendationsEntries.map(([key, rec]) => (
                                    <li key={key} className="flex items-start gap-2">
                                        <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-green-500 flex-shrink-0" aria-hidden="true" />
                                        <span className="text-sm text-green-900 leading-snug">{rec}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                </div>
            )}


            {/* ── View toggle bar (below insights, above chart) ──────── */}
            {isChartType && (
                <div className="flex items-center justify-end gap-2">
                    {/* Chart / Table toggle */}
                    <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
                        <button
                            id="view-toggle-chart"
                            onClick={() => setViewMode("chart")}
                            title="Chart view"
                            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-150 ${viewMode === "chart"
                                ? "bg-white text-gray-800 shadow-sm"
                                : "text-gray-500 hover:text-gray-700"
                                }`}
                        >
                            <BarChart2 className="h-3.5 w-3.5" />
                            Chart
                        </button>
                        <button
                            id="view-toggle-table"
                            onClick={() => setViewMode("table")}
                            title="Table view"
                            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-150 ${viewMode === "table"
                                ? "bg-white text-gray-800 shadow-sm"
                                : "text-gray-500 hover:text-gray-700"
                                }`}
                        >
                            <Table2 className="h-3.5 w-3.5" />
                            Table
                        </button>
                    </div>

                </div>
            )}

            {viewMode === "table" && isChartType ? (
                tableData.rows.length > 0 ? (
                    <TableRenderer data={{ type: "table", columns: tableData.columns, rows: tableData.rows }} />
                ) : (
                    <div className="bg-white p-4 rounded-lg border border-gray-200 text-center text-gray-500 text-sm">
                        No tabular data available for this chart.
                    </div>
                )
            ) : (
                <>
                    {/* Primary/Secondary Values for Number Cards and Snapshots */}
                    {chart_type === "number_card" && primary_value && (
                        <div className="relative bg-gradient-to-br from-blue-50 to-indigo-50/80 rounded-2xl border border-blue-100 shadow-sm p-6 overflow-hidden">
                            {/* Decorative Background Element */}
                            <div className="absolute -top-6 -right-6 text-blue-600/5 pointer-events-none">
                                {direction === "up" ? (
                                    <TrendingUp className="w-40 h-40" />
                                ) : direction === "down" ? (
                                    <TrendingDown className="w-40 h-40" />
                                ) : (
                                    <BarChart2 className="w-40 h-40" />
                                )}
                            </div>

                            <div className="relative z-10 flex flex-col gap-6">
                                {/* Primary Metric */}
                                <div className="space-y-2">
                                    <p className="text-sm font-semibold text-blue-700/80 uppercase tracking-wider">{primary_label || "Value"}</p>
                                    <div className="flex flex-wrap items-baseline gap-4">
                                        <p className="text-5xl font-extrabold text-blue-950 tracking-tight">{primary_value}</p>

                                        {/* Trend Badge */}
                                        {direction && direction !== "unknown" && trend_slope !== undefined && (
                                            <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-bold shadow-sm border ${direction === "up" ? "bg-emerald-50 text-emerald-700 border-emerald-200" :
                                                direction === "down" ? "bg-rose-50 text-rose-700 border-rose-200" :
                                                    "bg-gray-50 text-gray-700 border-gray-200"
                                                }`}>
                                                {direction === "up" && <TrendingUp className="h-4 w-4 stroke-[2.5]" aria-hidden="true" />}
                                                {direction === "down" && <TrendingDown className="h-4 w-4 stroke-[2.5]" aria-hidden="true" />}
                                                {direction === "flat" && <Minus className="h-4 w-4 stroke-[2.5]" aria-hidden="true" />}
                                                <span>{Math.abs(trend_slope).toFixed(1)}%</span>
                                            </div>
                                        )}
                                    </div>
                                </div>

                                {/* Secondary Metric (if present) */}
                                {secondary_value && (
                                    <div className="pt-5 border-t border-blue-200/50 flex flex-col gap-1">
                                        <p className="text-xs font-semibold text-blue-800/60 uppercase tracking-widest">{secondary_label || "Secondary"}</p>
                                        <p className="text-2xl font-bold text-blue-900">{secondary_value}</p>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    {/* Chart Rendering */}
                    {chart_type === "table" && visual_spec.columns && visual_spec.rows ? (
                        <TableRenderer data={{ type: "table", columns: visual_spec.columns, rows: visual_spec.rows }} />
                    ) : chart_type === "grouped_bar" || chart_type === "stacked_bar" || chart_type === "multi_line" ? (
                        <RechartsRenderer spec={visual_spec} />
                    ) : chart_type === "bar" || chart_type === "horizontal_bar" ? (
                        <BarChartRenderer spec={visual_spec} />
                    ) : chart_type === "line" ? (
                        <LineChartRenderer spec={visual_spec} />
                    ) : chart_type === "pie" ? (
                        <PieChartRenderer spec={visual_spec} />
                    ) : chart_type !== "number_card" ? (
                        <div className="bg-white p-2 rounded-lg border border-gray-200">
                            <p className="text-gray-500">Unsupported chart type: {chart_type}</p>
                        </div>
                    ) : null}
                </>
            )}
        </div>
    );
}

// ─── Inline table helpers for chart → table view ─────────────────────────────

function _formatCell(value: any, isPrice: boolean = false): string {
    if (value === null || value === undefined || value === "") return "–";
    if (typeof value === "string" && !isNaN(Number(value)) && value.trim() !== "") {
        value = Number(value);
    }
    if (typeof value === "number") {
        const prefix = isPrice ? "₹ " : "";
        if (Number.isInteger(value) || Math.abs(value) > 100)
            return prefix + value.toLocaleString("en-IN", { maximumFractionDigits: 0 });
        return prefix + value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    return String(value);
}

function _isPriceColumn(col: string): boolean {
    if (!col) return false;
    const lower = col.toLowerCase();

    if (lower.includes("qty") || lower.includes("quantity") || lower.includes("volume") || lower.includes("count")) {
        return false;
    }

    return lower.includes("sales") || lower.includes("value") || lower.includes("revenue") || lower.includes("amount") || lower.includes("price") || lower.includes("cost") || lower.includes("margin");
}

function _isNumeric(rows: any[], col: string): boolean {
    return rows.slice(0, 5).map(r => r[col]).filter(v => v != null).some(v => typeof v === "number" || (typeof v === "string" && !isNaN(Number(v)) && v.trim() !== ""));
}

const _TIME_GRANULARITIES = new Set(["day", "week", "month", "quarter", "year"]);

function _deduplicateTimeColumns(columns: string[]): string[] {
    const shadowed = new Set<string>();
    for (const col of columns) {
        const lastDot = col.lastIndexOf(".");
        if (lastDot === -1) continue;
        const suffix = col.substring(lastDot + 1);
        if (_TIME_GRANULARITIES.has(suffix)) {
            shadowed.add(col.substring(0, lastDot));
        }
    }
    if (shadowed.size === 0) return columns;
    return columns.filter(col => !shadowed.has(col));
}

function FlatTableInline({ columns: rawColumns, rows }: { columns: string[]; rows: any[] }) {
    const columns = _deduplicateTimeColumns(rawColumns);
    const numericCols = new Set(columns.filter(c => _isNumeric(rows, c)));

    return (
        <div className="overflow-x-auto rounded-xl border border-gray-200 shadow-sm bg-white">
            <div className="max-h-[560px] overflow-y-auto">
                <table className="min-w-full divide-y divide-gray-100 text-sm">
                    <thead className="bg-gray-50 sticky top-0 z-10">
                        <tr>
                            {columns.map((col, i) => (
                                <th key={i} className={`px-5 py-3 text-xs font-semibold tracking-wider text-gray-500 uppercase border-b border-gray-200 ${numericCols.has(col) ? "text-right" : "text-left"}`}>
                                    {cleanColumnName(col)}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                        {rows.length === 0 ? (
                            <tr><td colSpan={columns.length} className="px-5 py-10 text-center text-gray-400 italic">No data</td></tr>
                        ) : rows.map((row, ri) => (
                            <tr key={ri} className={`transition-colors duration-100 ${ri % 2 === 0 ? "bg-white" : "bg-gray-50/50"} hover:bg-blue-50/40`}>
                                {columns.map((col, ci) => (
                                    <td key={ci} className={`px-5 py-3 text-gray-800 ${numericCols.has(col) ? "text-right font-mono tabular-nums" : "text-left"}`}>
                                        {_formatCell(row[col], _isPriceColumn(col))}
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

function PivotTableInline({ columns: rawColumns, rows }: { columns: string[]; rows: any[] }) {
    const { useState: _useState, useMemo: _useMemo } = { useState, useMemo };
    const columns = _deduplicateTimeColumns(rawColumns);
    const numericCols = columns.filter(c => _isNumeric(rows, c));
    const categoricalCols = columns.filter(c => !_isNumeric(rows, c));

    const [rowDim, setRowDim] = _useState(categoricalCols[0] ?? columns[0] ?? "");
    const [colDim, setColDim] = _useState(categoricalCols[1] ?? categoricalCols[0] ?? columns[0] ?? "");
    const [valMetric, setValMetric] = _useState(numericCols[0] ?? columns[columns.length - 1] ?? "");


    const { rowKeys, colKeys, matrix } = _useMemo(() => {
        const rkSet = new Set<string>(); const ckSet = new Set<string>();
        const cells: Record<string, Record<string, number[]>> = {};
        for (const row of rows) {
            const rk = String(row[rowDim] ?? "–"); const ck = String(row[colDim] ?? "–");
            const num = parseFloat(row[valMetric]);
            rkSet.add(rk); ckSet.add(ck);
            if (!cells[rk]) cells[rk] = {};
            if (!cells[rk][ck]) cells[rk][ck] = [];
            if (!isNaN(num)) cells[rk][ck].push(num);
        }
        const rowKeys = Array.from(rkSet).sort(); const colKeys = Array.from(ckSet).sort();
        const matrix: Record<string, Record<string, number | null>> = {};
        for (const rk of rowKeys) { matrix[rk] = {}; for (const ck of colKeys) { const v = cells[rk]?.[ck]; matrix[rk][ck] = v?.length ? v.reduce((a, b) => a + b, 0) : null; } }
        return { rowKeys, colKeys, matrix };
    }, [rows, rowDim, colDim, valMetric]);

    const rowTotals = rowKeys.map(rk => colKeys.reduce((s, ck) => s + (matrix[rk][ck] ?? 0), 0));
    const colTotals = colKeys.map(ck => rowKeys.reduce((s, rk) => s + (matrix[rk][ck] ?? 0), 0));
    const grandTotal = rowTotals.reduce((a, b) => a + b, 0);
    const maxVal = Math.max(...rowTotals, 1);
    const heat = (v: number | null) => {
        if (!v) return ""; const p = (v / maxVal) * 100;
        return p > 80 ? "bg-blue-100 text-blue-900" : p > 50 ? "bg-blue-50 text-blue-800" : p > 20 ? "bg-sky-50 text-sky-700" : "";
    };

    const Sel = ({ label, value, opts, set }: { label: string; value: string; opts: string[]; set: (v: string) => void }) => (
        <div className="flex flex-col gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-gray-400">{label}</span>
            <select value={value} onChange={e => set(e.target.value)} className="appearance-none w-36 pl-3 pr-6 py-1.5 text-sm bg-white border border-gray-200 rounded-lg shadow-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-300 cursor-pointer">
                {opts.map(o => <option key={o} value={o}>{cleanColumnName(o)}</option>)}
            </select>
        </div>
    );

    const isPrice = _isPriceColumn(valMetric);

    return (
        <div className="space-y-3">
            <div className="flex flex-wrap items-end gap-4 px-1">
                <Sel label="Rows" value={rowDim} opts={columns} set={setRowDim} />
                <Sel label="Columns" value={colDim} opts={columns} set={setColDim} />
                <Sel label="Values" value={valMetric} opts={columns} set={setValMetric} />
            </div>
            {rowDim === colDim ? (
                <p className="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">Row and column dimensions must be different.</p>
            ) : (
                <div className="overflow-x-auto rounded-xl border border-gray-200 shadow-sm bg-white">
                    <div className="max-h-[560px] overflow-y-auto">
                        <table className="min-w-full text-sm border-collapse">
                            <thead className="sticky top-0 z-10">
                                <tr className="bg-gray-50 border-b border-gray-200">
                                    <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500 border-r border-gray-200 min-w-[140px]">
                                        {cleanColumnName(rowDim)} / {cleanColumnName(colDim)}
                                    </th>
                                    {colKeys.map(ck => <th key={ck} className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500 whitespace-nowrap">{ck}</th>)}
                                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-700 bg-gray-100 border-l border-gray-200">Total</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                                {rowKeys.map((rk, ri) => (
                                    <tr key={rk} className={`transition-colors hover:bg-blue-50/30 ${ri % 2 === 0 ? "bg-white" : "bg-gray-50/40"}`}>
                                        <td className="px-5 py-3 text-left font-medium text-gray-700 border-r border-gray-100 whitespace-nowrap">{rk}</td>
                                        {colKeys.map(ck => { const v = matrix[rk][ck]; return <td key={ck} className={`px-4 py-3 text-right tabular-nums font-mono ${heat(v)}`}>{v !== null ? _formatCell(v, isPrice) : "–"}</td>; })}
                                        <td className="px-4 py-3 text-right tabular-nums font-mono font-semibold text-gray-800 bg-gray-50 border-l border-gray-200">{_formatCell(rowTotals[ri], isPrice)}</td>
                                    </tr>
                                ))}
                                <tr className="bg-gray-100 border-t-2 border-gray-300 font-semibold text-gray-800">
                                    <td className="px-5 py-3 text-left text-xs uppercase tracking-wider border-r border-gray-200">Total</td>
                                    {colTotals.map((t, i) => <td key={i} className="px-4 py-3 text-right tabular-nums font-mono">{_formatCell(t, isPrice)}</td>)}
                                    <td className="px-4 py-3 text-right tabular-nums font-mono text-blue-700 bg-blue-50 border-l border-gray-200">{_formatCell(grandTotal, isPrice)}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
            <p className="text-[10px] text-gray-400 px-1">{rowKeys.length} rows × {colKeys.length} columns · values summed</p>
        </div>
    );
}

// Helper function for severity styles
function getSeverityStyles(severity: string): string {
    switch (severity) {
        case "critical":
            return "bg-red-50 border-red-300 text-red-900";
        case "high":
            return "bg-orange-50 border-orange-300 text-orange-900";
        case "medium":
            return "bg-yellow-50 border-yellow-300 text-yellow-900";
        case "low":
        default:
            return "bg-gray-50 border-gray-300 text-gray-700";
    }
}

// Helper to format numbers consistently
function formatNumber(value: number): string {
    if (value >= 1_00_00_000) { // 1 crore
        return `${(value / 1_00_00_000).toFixed(1)}Cr`;
    } else if (value >= 1_00_000) { // 1 lakh
        return `${(value / 1_00_000).toFixed(1)}L`;
    } else if (value >= 1_000) {
        return `${(value / 1_000).toFixed(1)}K`;
    } else if (value % 1 !== 0) {
        return value.toFixed(2);
    } else {
        return value.toString();
    }
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
function formatCellValue(value: any, isPrice: boolean = false): string {
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

    if (typeof value === "string" && !isNaN(Number(value)) && value.trim() !== "") {
        value = Number(value);
    }

    // Handle numbers - add comma separators for large numbers
    if (typeof value === "number") {
        const prefix = isPrice ? "₹ " : "";
        // For integers or numbers with less than 2 decimal places, show as integer
        if (Number.isInteger(value) || Math.abs(value) > 100) {
            return prefix + value.toLocaleString('en-IN', { maximumFractionDigits: 0 });
        }
        // For small decimal numbers, show 2 decimal places
        return prefix + value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    return String(value);
}

// Detect if a column contains numeric data (for right alignment)
function isNumericColumn(rows: any[], columnName: string): boolean {
    if (rows.length === 0) return false;

    // Check first 5 non-null rows
    const samples = rows.map(r => r[columnName]).filter(v => v != null).slice(0, 5);
    if (samples.length === 0) return false;

    return samples.some(v => typeof v === "number" || (typeof v === "string" && !isNaN(Number(v)) && v.trim() !== ""));
}

function BarChartRenderer({ spec }: { spec: VisualSpec }) {
    const series = spec.series?.[0];
    const xLabels = spec.x_axis?.values || [];
    const yValues = series?.values || [];
    const pointColors = series?.point_colors || [];

    if (yValues.length === 0) return null;

    // Build data array for recharts
    const data = yValues.map((value: any, idx: number) => ({
        name: xLabels[idx] || String(idx),
        value: typeof value === 'number' ? value : 0,
        color: pointColors[idx] || "#3b82f6"
    }));

    return (
        <div className="rounded-xl border border-gray-200 bg-white p-4 w-full">
            {spec.primary_value && (
                <div className="mb-2 flex items-baseline gap-4">
                    <div>
                        <p className="text-xs text-gray-500">{spec.primary_label}</p>
                        <p className="text-2xl font-bold text-gray-900">{spec.primary_value}</p>
                    </div>
                    {spec.secondary_value && (
                        <div>
                            <p className="text-xs text-gray-500">{spec.secondary_label}</p>
                            <p className="text-lg font-semibold text-gray-700">{spec.secondary_value}</p>
                        </div>
                    )}
                </div>
            )}
            <div className="h-[380px] w-full mt-4">
                <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data} margin={{ top: 32, right: 24, left: 0, bottom: 40 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f3f4f6" />
                        <XAxis
                            dataKey="name"
                            tick={{ fontSize: 11, fill: '#9ca3af' }}
                            tickMargin={8}
                            angle={-40}
                            textAnchor="end"
                            height={40}
                            interval={0}
                        />
                        <YAxis
                            tick={{ fontSize: 11, fill: '#9ca3af' }}
                            tickFormatter={(val) => formatNumber(val as number)}
                            width={80}
                            axisLine={false}
                            tickLine={false}
                        />
                        <RechartsTooltip
                            formatter={(value: any) => [formatNumber(Number(value)), spec.y_axis?.label || 'Value']}
                            cursor={{ fill: 'rgba(59,130,246,0.05)' }}
                            labelStyle={{ color: '#111827', fontWeight: 600, marginBottom: 2 }}
                            contentStyle={{ borderRadius: '10px', border: '1px solid #e5e7eb', boxShadow: '0 4px 16px rgba(0,0,0,0.08)', fontSize: '13px' }}
                        />
                        <Bar dataKey="value" radius={[6, 6, 0, 0]} maxBarSize={64}>
                            {data.map((entry: any, index: number) => (
                                <Cell key={`cell-${index}`} fill={entry.color} />
                            ))}
                        </Bar>
                        {spec.markers?.filter(m => m.marker_type === "threshold").map((marker, idx: number) => (
                            <ReferenceLine key={idx} y={marker.value} stroke="#ef4444" strokeDasharray="5 3"
                                label={{ position: 'insideTopLeft', value: marker.label, fill: '#ef4444', fontSize: 11 }} />
                        ))}
                    </BarChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
}

function LineChartRenderer({ spec }: { spec: VisualSpec }) {
    const series = spec.series?.[0];
    const xLabels = spec.x_axis?.values || [];
    const yValues = series?.values || [];

    if (yValues.length === 0) return null;

    const lineColor = series?.color_hint === "positive" ? "#10b981" :
        series?.color_hint === "negative" ? "#ef4444" : "#3b82f6";

    const data = yValues.map((value: any, idx: number) => ({
        name: xLabels[idx] || String(idx),
        value: typeof value === 'number' ? value : 0
    }));

    return (
        <div className="rounded-xl border border-gray-200 bg-white p-4 w-full">
            {spec.primary_value && (
                <div className="mb-2 flex items-baseline gap-4">
                    <div>
                        <p className="text-xs text-gray-500">{spec.primary_label}</p>
                        <p className="text-2xl font-bold text-gray-900">{spec.primary_value}</p>
                    </div>
                </div>
            )}
            <div className="h-[380px] w-full mt-4">
                <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={data} margin={{ top: 32, right: 24, left: 0, bottom: 40 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f3f4f6" />
                        <XAxis
                            dataKey="name"
                            tick={{ fontSize: 11, fill: '#9ca3af' }}
                            tickMargin={8}
                            angle={-40}
                            textAnchor="end"
                            height={40}
                            interval={0}
                        />
                        <YAxis
                            tick={{ fontSize: 11, fill: '#9ca3af' }}
                            tickFormatter={(val) => formatNumber(val as number)}
                            width={80}
                            axisLine={false}
                            tickLine={false}
                        />
                        <RechartsTooltip
                            formatter={(value: any) => [formatNumber(Number(value)), spec.y_axis?.label || 'Value']}
                            labelStyle={{ color: '#111827', fontWeight: 600, marginBottom: 2 }}
                            contentStyle={{ borderRadius: '10px', border: '1px solid #e5e7eb', boxShadow: '0 4px 16px rgba(0,0,0,0.08)', fontSize: '13px' }}
                        />
                        <Line
                            type="monotone"
                            dataKey="value"
                            stroke={lineColor}
                            strokeWidth={2.5}
                            dot={false}
                            activeDot={{ r: 5, strokeWidth: 0, fill: lineColor }}
                        />
                        {spec.markers?.filter(m => m.marker_type === "threshold").map((marker, idx) => (
                            <ReferenceLine key={idx} y={marker.value} stroke="#ef4444" strokeDasharray="5 3"
                                label={{ position: 'insideTopLeft', value: marker.label, fill: '#ef4444', fontSize: 11 }} />
                        ))}
                    </LineChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
}

function PieChartRenderer({ spec }: { spec: VisualSpec }) {
    const series = spec.series?.[0];
    const labels = spec.x_axis?.values || [];
    const values = series?.values || [];

    if (values.length === 0) return null;

    const colors = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4"];

    const data = values.map((value: any, idx: number) => ({
        name: labels[idx] || `Segment ${idx + 1}`,
        value: typeof value === 'number' ? value : 0,
        color: colors[idx % colors.length]
    }));

    return (
        <div className="rounded-xl border border-gray-200 bg-white p-4 w-full">
            <div className="flex flex-col md:flex-row gap-6 items-center">
                <div className="h-[320px] w-full md:w-[320px] flex-shrink-0">
                    <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                            <RechartsTooltip
                                formatter={(value: any) => [formatNumber(Number(value)), '']}
                                contentStyle={{ borderRadius: '10px', border: '1px solid #e5e7eb', boxShadow: '0 4px 16px rgba(0,0,0,0.08)', fontSize: '13px' }}
                            />
                            <Pie
                                data={data}
                                cx="50%"
                                cy="50%"
                                labelLine={false}
                                outerRadius="80%"
                                innerRadius="45%"
                                dataKey="value"
                                paddingAngle={2}
                            >
                                {data.map((entry: any, idx: number) => (
                                    <Cell key={`cell-${idx}`} fill={entry.color} stroke="none" />
                                ))}
                            </Pie>
                        </PieChart>
                    </ResponsiveContainer>
                </div>
                <div className="flex-1 space-y-2.5 min-w-0">
                    {data.map((slice: any, idx: number) => (
                        <div key={idx} className="flex items-center gap-3">
                            <div className="w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: slice.color }} />
                            <div className="flex-1 min-w-0">
                                <p className="text-sm font-medium text-gray-800 truncate">{slice.name}</p>
                            </div>
                            <p className="text-sm font-mono text-gray-500 flex-shrink-0">{formatNumber(slice.value as number)}</p>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

// Recharts implementation for advanced multi-dimensional charts
function RechartsRenderer({ spec }: { spec: VisualSpec }) {
    if (!spec.data || spec.data.length === 0) return null;

    const data = spec.data;
    const xAxisKey = spec.x_axis_key || "label";
    const colors = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4"];

    const commonMargin = { top: 32, right: 24, left: 0, bottom: 48 };
    const commonXAxis = (
        <XAxis
            dataKey={xAxisKey}
            tick={{ fontSize: 11, fill: '#9ca3af' }}
            tickMargin={8}
            angle={-40}
            textAnchor="end"
            height={48}
            interval={0}
        />
    );
    const commonYAxis = (
        <YAxis
            tick={{ fontSize: 11, fill: '#9ca3af' }}
            tickFormatter={(val) => formatCellValue(val, false)}
            width={80}
            axisLine={false}
            tickLine={false}
        />
    );
    const commonTooltip = (
        <RechartsTooltip
            formatter={(value: any) => formatCellValue(Number(value), false)}
            labelStyle={{ color: '#111827', fontWeight: 600, marginBottom: 2 }}
            contentStyle={{ borderRadius: '10px', border: '1px solid #e5e7eb', boxShadow: '0 4px 16px rgba(0,0,0,0.08)', fontSize: '13px' }}
        />
    );

    return (
        <div className="rounded-xl border border-gray-200 bg-white p-4 w-full">
            {spec.primary_value && (
                <div className="mb-3 flex items-baseline gap-4">
                    <div>
                        <p className="text-xs text-gray-400 uppercase tracking-wide">{spec.primary_label || 'Total'}</p>
                        <p className="text-2xl font-bold text-gray-900">{spec.primary_value}</p>
                    </div>
                </div>
            )}
            <div className="h-[380px] w-full mt-4">
                <ResponsiveContainer width="100%" height="100%">
                    {spec.chart_type === "multi_line" ? (
                        <LineChart data={data} margin={commonMargin}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f3f4f6" />
                            {commonXAxis}
                            {commonYAxis}
                            {commonTooltip}
                            <Legend iconType="circle" iconSize={8}
                                wrapperStyle={{ paddingTop: '12px', fontSize: '12px', color: '#6b7280' }} />
                            {spec.pivot_config?.stack_keys?.map((key, i) => (
                                <Line
                                    key={key}
                                    type="monotone"
                                    dataKey={key}
                                    name={cleanColumnName(key)}
                                    stroke={colors[i % colors.length]}
                                    strokeWidth={2.5}
                                    dot={false}
                                    activeDot={{ r: 5, strokeWidth: 0 }}
                                />
                            ))}
                        </LineChart>
                    ) : (
                        <BarChart data={data} margin={commonMargin}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f3f4f6" />
                            {commonXAxis}
                            {commonYAxis}
                            {commonTooltip}
                            <Legend iconType="square" iconSize={10}
                                wrapperStyle={{ paddingTop: '12px', fontSize: '12px', color: '#6b7280' }} />
                            {spec.chart_type === "stacked_bar" && spec.pivot_config?.stack_keys?.map((key, i) => (
                                <Bar
                                    key={key}
                                    dataKey={key}
                                    name={cleanColumnName(key)}
                                    stackId="a"
                                    fill={colors[i % colors.length]}
                                    maxBarSize={56}
                                    radius={[i === spec.pivot_config!.stack_keys.length - 1 ? 6 : 0,
                                    i === spec.pivot_config!.stack_keys.length - 1 ? 6 : 0, 0, 0]}
                                />
                            ))}
                            {spec.chart_type === "grouped_bar" && spec.series?.map((s, i) => (
                                <Bar
                                    key={s.key}
                                    dataKey={s.key}
                                    name={s.label}
                                    fill={colors[i % colors.length]}
                                    maxBarSize={40}
                                    radius={[4, 4, 0, 0]}
                                />
                            ))}
                        </BarChart>
                    )}
                </ResponsiveContainer>
            </div>
        </div>
    );
}

