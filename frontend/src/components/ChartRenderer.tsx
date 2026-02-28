"use client";

import { useEffect, useState, useMemo } from "react";
import { ChevronDown, ChevronUp, TrendingUp, TrendingDown, Minus, BarChart2, Table2, LayoutGrid } from "lucide-react";
import TableRenderer from "./TableRenderer";

// Types matching backend VisualSpec
interface VisualSpec {
    chart_type: string;
    title?: string;
    subtitle?: string;
    x_axis?: Axis;
    y_axis?: Axis;
    series?: DataSeries[];
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
    granularity?: string; // "day" | "week" | "month" | "quarter" | "year"
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
    key_risks?: string[];
    possible_drivers?: string[];
    recommendations?: string[];
}

interface ChartRendererProps {
    visual_spec?: VisualSpec;
    refined_insights?: RefinedInsights;
}

export default function ChartRenderer({ visual_spec, refined_insights }: ChartRendererProps) {
    const [showContextNotes, setShowContextNotes] = useState(false);
    const [isClient, setIsClient] = useState(false);
    const [viewMode, setViewMode] = useState<"chart" | "table">("chart");
    const [pivotMode, setPivotMode] = useState(false);

    useEffect(() => {
        setIsClient(true);
    }, []);

    // Build a flat column/row dataset from the visual_spec for the table view
    const tableData = useMemo(() => {
        if (!visual_spec) return { columns: [], rows: [] };

        // For native table specs, use stored rows/columns directly
        if (visual_spec.chart_type === "table" && visual_spec.columns && visual_spec.rows) {
            return { columns: visual_spec.columns, rows: visual_spec.rows };
        }

        // For charts, reconstruct a table from x_axis labels + series values
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

    const canPivot = tableData.columns.length > 2;

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

    return (
        <div className="space-y-4">

            {/* Title Section */}
            {title && (
                <div className="space-y-1">
                    <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
                    {subtitle && <p className="text-sm text-gray-600">{subtitle}</p>}
                </div>
            )}

            {/* Executive Summary (Always Visible) */}
            {refined_insights?.executive_summary && (
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                    <h4 className="text-xs font-bold text-blue-900 mb-2 uppercase tracking-wide">Executive Summary</h4>
                    <p className="text-sm text-blue-800 leading-relaxed font-medium">{refined_insights.executive_summary}</p>
                </div>
            )}

            {/* Narrative Panels: Key Risks / Possible Drivers / Recommendations */}
            {((refined_insights?.key_risks?.length ?? 0) > 0 ||
                (refined_insights?.possible_drivers?.length ?? 0) > 0 ||
                (refined_insights?.recommendations?.length ?? 0) > 0) && (
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">

                        {/* Key Risks */}
                        {refined_insights?.key_risks && refined_insights.key_risks.length > 0 && (
                            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                                <h4 className="text-xs font-bold text-red-800 mb-3 uppercase tracking-wide flex items-center gap-1.5">
                                    <span aria-hidden="true">⚠️</span> Key Risks
                                </h4>
                                <ul className="space-y-2">
                                    {refined_insights.key_risks.map((risk, idx) => (
                                        <li key={idx} className="flex items-start gap-2">
                                            <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-red-400 flex-shrink-0" aria-hidden="true" />
                                            <span className="text-sm text-red-900 leading-snug">{risk}</span>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        )}

                        {/* Possible Drivers */}
                        {refined_insights?.possible_drivers && refined_insights.possible_drivers.length > 0 && (
                            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
                                <h4 className="text-xs font-bold text-amber-800 mb-3 uppercase tracking-wide flex items-center gap-1.5">
                                    <span aria-hidden="true">🔍</span> Possible Drivers
                                </h4>
                                <ul className="space-y-2">
                                    {refined_insights.possible_drivers.map((driver, idx) => (
                                        <li key={idx} className="flex items-start gap-2">
                                            <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0" aria-hidden="true" />
                                            <span className="text-sm text-amber-900 leading-snug">{driver}</span>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        )}

                        {/* Recommendations */}
                        {refined_insights?.recommendations && refined_insights.recommendations.length > 0 && (
                            <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                                <h4 className="text-xs font-bold text-green-800 mb-3 uppercase tracking-wide flex items-center gap-1.5">
                                    <span aria-hidden="true">✅</span> Recommendations
                                </h4>
                                <ul className="space-y-2">
                                    {refined_insights.recommendations.map((rec, idx) => (
                                        <li key={idx} className="flex items-start gap-2">
                                            <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-green-500 flex-shrink-0" aria-hidden="true" />
                                            <span className="text-sm text-green-900 leading-snug">{rec}</span>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        )}
                    </div>
                )}

            {/* Context Notes (Collapsible via Dropdown) */}
            {refined_insights?.insights && refined_insights.insights.length > 0 && (
                <div className="bg-white border border-gray-200 rounded-lg overflow-hidden shadow-sm">
                    <button
                        onClick={() => setShowContextNotes(!showContextNotes)}
                        className="w-full px-4 py-3 flex items-center justify-between bg-gray-50 hover:bg-gray-100 transition-colors"
                        aria-expanded={showContextNotes}
                    >
                        <div className="flex items-center gap-3">
                            <span className="text-sm font-semibold text-gray-700">Detailed Insights</span>
                            <span className="bg-blue-100 text-blue-700 text-xs font-bold px-2 py-0.5 rounded-full">
                                {refined_insights.insights.length}
                            </span>
                        </div>
                        {showContextNotes ? (
                            <ChevronUp className="h-4 w-4 text-gray-500" aria-hidden="true" />
                        ) : (
                            <ChevronDown className="h-4 w-4 text-gray-500" aria-hidden="true" />
                        )}
                    </button>
                    {showContextNotes && (
                        <div className="divide-y divide-gray-100">
                            {refined_insights.insights.map((insight: any, idx: number) => (
                                <div key={idx} className="p-4 hover:bg-gray-50 transition-colors">
                                    <div className="flex items-start gap-3">
                                        <div className={`mt-1.5 w-2 h-2 rounded-full flex-shrink-0 ${insight.severity === 'critical' ? 'bg-red-500 shadow-sm ring-1 ring-red-200' :
                                            insight.severity === 'high' ? 'bg-orange-500 shadow-sm ring-1 ring-orange-200' :
                                                insight.severity === 'medium' ? 'bg-yellow-500 shadow-sm ring-1 ring-yellow-200' :
                                                    'bg-blue-400 shadow-sm ring-1 ring-blue-200'
                                            }`} />
                                        <div className="space-y-1">
                                            <p className="text-sm text-gray-700 font-medium leading-normal">{insight.headline}</p>
                                            {insight.context_note && (
                                                <p className="text-sm text-gray-600 mt-1">{insight.context_note}</p>
                                            )}
                                            {insight.label && (
                                                <p className="text-xs text-gray-400 uppercase tracking-tighter">{insight.label.replace(/_/g, " ")}</p>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            ))}
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
                            onClick={() => { setViewMode("chart"); setPivotMode(false); }}
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

                    {/* Pivot toggle — only in table mode with >2 columns */}
                    {viewMode === "table" && canPivot && (
                        <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
                            <button
                                id="view-toggle-flat"
                                onClick={() => setPivotMode(false)}
                                title="Flat table"
                                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-150 ${!pivotMode
                                    ? "bg-white text-gray-800 shadow-sm"
                                    : "text-gray-500 hover:text-gray-700"
                                    }`}
                            >
                                <Table2 className="h-3.5 w-3.5" />
                                Flat
                            </button>
                            <button
                                id="view-toggle-pivot"
                                onClick={() => setPivotMode(true)}
                                title="Pivot table"
                                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-150 ${pivotMode
                                    ? "bg-white text-gray-800 shadow-sm"
                                    : "text-gray-500 hover:text-gray-700"
                                    }`}
                            >
                                <LayoutGrid className="h-3.5 w-3.5" />
                                Pivot
                            </button>
                        </div>
                    )}
                </div>
            )}

            {viewMode === "table" && isChartType ? (
                tableData.rows.length > 0 ? (
                    pivotMode && canPivot ? (
                        <PivotTableInline columns={tableData.columns} rows={tableData.rows} />
                    ) : (
                        <FlatTableInline columns={tableData.columns} rows={tableData.rows} />
                    )
                ) : (
                    <div className="bg-white p-4 rounded-lg border border-gray-200 text-center text-gray-500 text-sm">
                        No tabular data available for this chart.
                    </div>
                )
            ) : (
                <>
                    {/* Primary/Secondary Values for Number Cards and Snapshots */}
                    {chart_type === "number_card" && primary_value && (
                        <div className="bg-gradient-to-br from-blue-50 to-indigo-50 rounded-lg border border-blue-200">
                            <div className="space-y-4">
                                <div>
                                    <p className="text-sm text-gray-600 mb-1">{primary_label || "Value"}</p>
                                    <div className="flex items-baseline gap-3">
                                        <p className="text-4xl font-bold text-gray-900">{primary_value}</p>
                                        {direction && direction !== "unknown" && trend_slope !== undefined && (
                                            <div className={`flex items-center gap-1 px-2 py-1 rounded text-sm font-medium ${direction === "up" ? "bg-green-100 text-green-700" :
                                                direction === "down" ? "bg-red-100 text-red-700" :
                                                    "bg-gray-100 text-gray-700"
                                                }`}>
                                                {direction === "up" && <TrendingUp className="h-4 w-4" aria-hidden="true" />}
                                                {direction === "down" && <TrendingDown className="h-4 w-4" aria-hidden="true" />}
                                                {direction === "flat" && <Minus className="h-4 w-4" aria-hidden="true" />}
                                                <span>{Math.abs(trend_slope).toFixed(1)}%</span>
                                            </div>
                                        )}
                                    </div>
                                </div>
                                {secondary_value && (
                                    <div className="pt-4 border-t border-blue-200">
                                        <p className="text-xs text-gray-500">{secondary_label || "Secondary"}</p>
                                        <p className="text-lg font-semibold text-gray-700">{secondary_value}</p>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    {/* Chart Rendering */}
                    {chart_type === "table" && visual_spec.columns && visual_spec.rows ? (
                        <TableRenderer data={{ type: "table", columns: visual_spec.columns, rows: visual_spec.rows }} />
                    ) : chart_type === "bar" || chart_type === "horizontal_bar" || chart_type === "stacked_bar" ? (
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

function _formatCell(value: any): string {
    if (value === null || value === undefined || value === "") return "–";
    if (typeof value === "number") {
        if (Number.isInteger(value) || Math.abs(value) > 100)
            return value.toLocaleString("en-IN", { maximumFractionDigits: 0 });
        return value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    return String(value);
}

function _isNumeric(rows: any[], col: string): boolean {
    return rows.slice(0, 5).map(r => r[col]).filter(v => v != null).some(v => typeof v === "number");
}

function FlatTableInline({ columns, rows }: { columns: string[]; rows: any[] }) {
    const numericCols = new Set(columns.filter(c => _isNumeric(rows, c)));
    return (
        <div className="overflow-x-auto rounded-xl border border-gray-200 shadow-sm bg-white">
            <div className="max-h-[560px] overflow-y-auto">
                <table className="min-w-full divide-y divide-gray-100 text-sm">
                    <thead className="bg-gray-50 sticky top-0 z-10">
                        <tr>
                            {columns.map((col, i) => (
                                <th key={i} className={`px-5 py-3 text-xs font-semibold tracking-wider text-gray-500 uppercase border-b border-gray-200 ${numericCols.has(col) ? "text-right" : "text-left"}`}>
                                    {col.replace(/_/g, " ")}
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
                                        {_formatCell(row[col])}
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

function PivotTableInline({ columns, rows }: { columns: string[]; rows: any[] }) {
    const { useState: _useState, useMemo: _useMemo } = { useState, useMemo };
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
                {opts.map(o => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
            </select>
        </div>
    );

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
                                        {rowDim.replace(/_/g, " ")} / {colDim.replace(/_/g, " ")}
                                    </th>
                                    {colKeys.map(ck => <th key={ck} className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500 whitespace-nowrap">{ck}</th>)}
                                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-700 bg-gray-100 border-l border-gray-200">Total</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                                {rowKeys.map((rk, ri) => (
                                    <tr key={rk} className={`transition-colors hover:bg-blue-50/30 ${ri % 2 === 0 ? "bg-white" : "bg-gray-50/40"}`}>
                                        <td className="px-5 py-3 text-left font-medium text-gray-700 border-r border-gray-100 whitespace-nowrap">{rk}</td>
                                        {colKeys.map(ck => { const v = matrix[rk][ck]; return <td key={ck} className={`px-4 py-3 text-right tabular-nums font-mono ${heat(v)}`}>{v !== null ? _formatCell(v) : "–"}</td>; })}
                                        <td className="px-4 py-3 text-right tabular-nums font-mono font-semibold text-gray-800 bg-gray-50 border-l border-gray-200">{_formatCell(rowTotals[ri])}</td>
                                    </tr>
                                ))}
                                <tr className="bg-gray-100 border-t-2 border-gray-300 font-semibold text-gray-800">
                                    <td className="px-5 py-3 text-left text-xs uppercase tracking-wider border-r border-gray-200">Total</td>
                                    {colTotals.map((t, i) => <td key={i} className="px-4 py-3 text-right tabular-nums font-mono">{_formatCell(t)}</td>)}
                                    <td className="px-4 py-3 text-right tabular-nums font-mono text-blue-700 bg-blue-50 border-l border-gray-200">{_formatCell(grandTotal)}</td>
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
    if (value >= 1_000_000_000) {
        return `${(value / 1_000_000_000).toFixed(1)}B`;
    } else if (value >= 1_000_000) {
        return `${(value / 1_000_000).toFixed(1)}M`;
    } else if (value >= 1_000) {
        return `${(value / 1_000).toFixed(1)}K`;
    } else if (value % 1 !== 0) {
        return value.toFixed(2);
    } else {
        return value.toString();
    }
}

// ─── Date label formatter for line-chart x-axis ──────────────────────────────
// Formats an ISO date string (e.g. "2025-02-15T00:00:00.000Z") or plain date
// according to the time granularity used in the query.
function formatDateLabel(raw: any, granularity?: string): string {
    if (raw === null || raw === undefined) return "";
    const s = String(raw);
    // Try to parse as a date
    const d = new Date(s);
    if (isNaN(d.getTime())) return s; // Not a date — return as-is

    const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const m = MONTHS[d.getUTCMonth()];
    const yr2 = String(d.getUTCFullYear()).slice(-2);
    const yr4 = d.getUTCFullYear();

    switch (granularity) {
        case "day": {
            // dd-Mon-'yy  →  15-Feb-'25
            const dd = String(d.getUTCDate()).padStart(2, "0");
            return `${dd}-${m}-'${yr2}`;
        }
        case "week": {
            // Wk{n} - Mon  →  Wk8 - Feb
            // ISO week number
            const jan1 = new Date(Date.UTC(yr4, 0, 1));
            const weekNum = Math.ceil(((d.getTime() - jan1.getTime()) / 86400000 + jan1.getUTCDay() + 1) / 7);
            return `Wk${weekNum} - ${m}`;
        }
        case "month": {
            // Mon 'yy  →  Feb '25
            return `${m} '${yr2}`;
        }
        case "quarter": {
            // Q{n} 'yy  →  Q1 '25
            const q = Math.floor(d.getUTCMonth() / 3) + 1;
            return `Q${q} '${yr2}`;
        }
        case "year": {
            return `${yr4}`;
        }
        default:
            // Fallback: try to detect from the string itself
            if (/^\d{4}-\d{2}-\d{2}/.test(s)) {
                const dd = String(d.getUTCDate()).padStart(2, "0");
                return `${dd}-${m}-'${yr2}`;
            }
            return s;
    }
}

// Clean up column label for display (remove table prefixes, format nicely)
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
function isNumericColumn(rows: any[], columnName: string): boolean {
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

// Bar Chart Renderer (SVG implementation)
function BarChartRenderer({ spec }: { spec: VisualSpec }) {
    const series = spec.series?.[0];
    const xLabels = spec.x_axis?.values || [];  // Category labels
    const yValues = series?.values || [];       // Actual data values
    const yAxisTicks = spec.y_axis?.values || [];  // Y-axis tick positions
    const pointColors = series?.point_colors || [];
    const pointEmphasis = series?.point_emphasis || [];

    if (yValues.length === 0) return null;

    const maxValue = Math.max(...yValues.map(v => typeof v === 'number' ? v : 0));
    const chartHeight = 300;
    const topPadding = 40;
    const bottomPadding = 100;
    const leftPadding = 60;  // Space for Y-axis labels
    const rightPadding = 20;
    const totalHeight = chartHeight + topPadding + bottomPadding;
    const chartWidth = Math.max(600, xLabels.length * 70);
    const totalWidth = chartWidth + leftPadding + rightPadding;
    const barWidth = Math.min(60, (chartWidth / yValues.length) * 0.8);

    // Use backend tick values if available, otherwise compute
    const tickValues = yAxisTicks.length > 0
        ? yAxisTicks
        : [0, maxValue * 0.25, maxValue * 0.5, maxValue * 0.75, maxValue];

    const maxTickValue = Math.max(...tickValues.map(v => typeof v === 'number' ? v : 0));

    return (
        <div className="bg-white p-8 rounded-lg border border-gray-200">
            {spec.primary_value && (
                <div className="mb-4 flex items-baseline gap-4">
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
            <div className="space-y-4">
                <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-600">{spec.y_axis?.label || "Value"}</span>
                </div>
                <div className="overflow-x-auto">
                    <svg
                        width={totalWidth}
                        height={totalHeight}
                        viewBox={`0 0 ${totalWidth} ${totalHeight}`}
                        role="img"
                        aria-label={`Bar chart showing ${spec.y_axis?.label || "values"}`}
                    >
                        <title>{spec.title || `Bar chart of ${spec.y_axis?.label}`}</title>

                        {/* Y-axis ticks and labels */}
                        {tickValues.map((tickValue, idx) => {
                            const y = topPadding + chartHeight - ((tickValue as number) / maxTickValue) * chartHeight;
                            return (
                                <g key={`y-tick-${idx}`}>
                                    {/* Grid line */}
                                    <line
                                        x1={leftPadding}
                                        y1={y}
                                        x2={leftPadding + chartWidth}
                                        y2={y}
                                        stroke="#e5e7eb"
                                        strokeWidth={1}
                                        aria-hidden="true"
                                    />
                                    {/* Tick mark */}
                                    <line
                                        x1={leftPadding - 5}
                                        y1={y}
                                        x2={leftPadding}
                                        y2={y}
                                        stroke="#9ca3af"
                                        strokeWidth={1}
                                        aria-hidden="true"
                                    />
                                    {/* Y-axis label */}
                                    <text
                                        x={leftPadding - 10}
                                        y={y}
                                        textAnchor="end"
                                        dominantBaseline="middle"
                                        className="text-xs fill-gray-600"
                                    >
                                        {formatNumber(tickValue as number)}
                                    </text>
                                </g>
                            );
                        })}

                        {/* Y-axis line */}
                        <line
                            x1={leftPadding}
                            y1={topPadding}
                            x2={leftPadding}
                            y2={topPadding + chartHeight}
                            stroke="#9ca3af"
                            strokeWidth={2}
                            aria-hidden="true"
                        />

                        {/* X-axis line */}
                        <line
                            x1={leftPadding}
                            y1={topPadding + chartHeight}
                            x2={leftPadding + chartWidth}
                            y2={topPadding + chartHeight}
                            stroke="#9ca3af"
                            strokeWidth={2}
                            aria-hidden="true"
                        />

                        {/* Bars */}
                        {yValues.map((value, idx) => {
                            const height = maxTickValue > 0 ? (value / maxTickValue) * chartHeight : 0;
                            const x = leftPadding + idx * (chartWidth / yValues.length) + (chartWidth / yValues.length - barWidth) / 2;
                            const y = topPadding + (chartHeight - height);

                            // Determine color
                            let fillColor = pointColors[idx] || "#3b82f6"; // Default blue
                            const emphasis = pointEmphasis[idx];

                            // Adjust opacity based on emphasis
                            const opacity = emphasis === "strong" || emphasis === "critical" ? 1 :
                                emphasis === "subtle" ? 0.8 : 0.7;

                            return (
                                <g key={idx}>
                                    <rect
                                        x={x}
                                        y={y}
                                        width={barWidth}
                                        height={height}
                                        fill={fillColor}
                                        opacity={opacity}
                                        rx={4}
                                        className="transition-all hover:opacity-100"
                                        aria-label={`${xLabels[idx]}: ${formatNumber(value)}`}
                                    >
                                        <title>{`${xLabels[idx]}: ${formatNumber(value)}`}</title>
                                    </rect>
                                    {/* Value label on top of bar */}
                                    <text
                                        x={x + barWidth / 2}
                                        y={y - 5}
                                        textAnchor="middle"
                                        className="text-xs fill-gray-700 font-medium"
                                    >
                                        {formatNumber(value)}
                                    </text>
                                    {/* X-axis label */}
                                    <text
                                        x={x + barWidth / 2}
                                        y={topPadding + chartHeight + 12}
                                        textAnchor="end"
                                        transform={`rotate(-45, ${x + barWidth / 2}, ${topPadding + chartHeight + 12})`}
                                        className="text-xs fill-gray-600"
                                    >
                                        {String(xLabels[idx] || idx)}
                                    </text>
                                </g>
                            );
                        })}

                        {/* Threshold markers */}
                        {spec.markers?.filter(m => m.marker_type === "threshold").map((marker, idx) => {
                            const markerValue = marker.value || 0;
                            const y = topPadding + (chartHeight - (markerValue / maxTickValue) * chartHeight);
                            return (
                                <g key={`threshold-${idx}`}>
                                    <line
                                        x1={leftPadding}
                                        y1={y}
                                        x2={leftPadding + chartWidth}
                                        y2={y}
                                        stroke="#ef4444"
                                        strokeWidth={2}
                                        strokeDasharray="4 4"
                                        aria-hidden="true"
                                    />
                                    <text
                                        x={leftPadding + 5}
                                        y={y - 5}
                                        className="text-xs fill-red-600 font-medium"
                                    >
                                        {marker.label}
                                    </text>
                                </g>
                            );
                        })}
                    </svg>
                </div>
            </div>
        </div>
    );
}

// Line Chart Renderer (SVG implementation)
function LineChartRenderer({ spec }: { spec: VisualSpec }) {
    const series = spec.series?.[0];
    const xLabels = spec.x_axis?.values || [];  // Time/category labels
    const yValues = series?.values || [];       // Actual data values
    const yAxisTicks = spec.y_axis?.values || [];  // Y-axis tick positions

    if (yValues.length === 0) return null;

    const maxValue = Math.max(...yValues.map(v => typeof v === 'number' ? v : 0));
    const minValue = Math.min(...yValues.map(v => typeof v === 'number' ? v : 0));
    const chartHeight = 300;
    const topPadding = 40;
    const bottomPadding = 100;
    const leftPadding = 60;
    const rightPadding = 20;
    const totalHeight = chartHeight + topPadding + bottomPadding;
    const chartWidth = 600;
    const totalWidth = chartWidth + leftPadding + rightPadding;
    const pointSpacing = chartWidth / (yValues.length - 1 || 1);

    // Use backend tick values if available, otherwise compute
    const tickValues = yAxisTicks.length > 0
        ? yAxisTicks
        : [minValue, minValue + (maxValue - minValue) * 0.25, minValue + (maxValue - minValue) * 0.5,
            minValue + (maxValue - minValue) * 0.75, maxValue];

    const minTickValue = Math.min(...tickValues.map(v => typeof v === 'number' ? v : 0));
    const maxTickValue = Math.max(...tickValues.map(v => typeof v === 'number' ? v : 0));
    const range = maxTickValue - minTickValue || 1;

    // Generate path
    const pathData = yValues
        .map((value, idx) => {
            const x = leftPadding + idx * pointSpacing;
            const y = topPadding + (chartHeight - ((value - minTickValue) / range) * chartHeight);
            return `${idx === 0 ? 'M' : 'L'} ${x} ${y}`;
        })
        .join(' ');

    const lineColor = series?.color_hint === "positive" ? "#10b981" :
        series?.color_hint === "negative" ? "#ef4444" : "#3b82f6";

    return (
        <div className="bg-white p-8 rounded-lg border border-gray-200">
            {spec.primary_value && (
                <div className="mb-4 flex items-baseline gap-4">
                    <div>
                        <p className="text-xs text-gray-500">{spec.primary_label}</p>
                        <p className="text-2xl font-bold text-gray-900">{spec.primary_value}</p>
                    </div>
                    {spec.trend_slope !== undefined && (
                        <div className={`flex items-center gap-1 px-2 py-1 rounded text-sm font-medium ${spec.trend_slope > 0 ? "bg-green-100 text-green-700" :
                            spec.trend_slope < 0 ? "bg-red-100 text-red-700" :
                                "bg-gray-100 text-gray-700"
                            }`}>
                            {spec.trend_slope > 0 && <TrendingUp className="h-4 w-4" aria-hidden="true" />}
                            {spec.trend_slope < 0 && <TrendingDown className="h-4 w-4" aria-hidden="true" />}
                            {spec.trend_slope === 0 && <Minus className="h-4 w-4" aria-hidden="true" />}
                            <span>{Math.abs(spec.trend_slope).toFixed(1)}%</span>
                        </div>
                    )}
                </div>
            )}
            <div className="space-y-4">
                <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-600">{spec.y_axis?.label || "Value"}</span>
                </div>
                <svg
                    width={totalWidth}
                    height={totalHeight}
                    viewBox={`0 0 ${totalWidth} ${totalHeight}`}
                    role="img"
                    aria-label={`Line chart showing ${spec.y_axis?.label || "trend"}`}
                >
                    <title>{spec.title || `Line chart of ${spec.y_axis?.label}`}</title>

                    {/* Y-axis ticks and labels */}
                    {tickValues.map((tickValue, idx) => {
                        const y = topPadding + chartHeight - ((tickValue as number - minTickValue) / range) * chartHeight;
                        return (
                            <g key={`y-tick-${idx}`}>
                                {/* Grid line */}
                                <line
                                    x1={leftPadding}
                                    y1={y}
                                    x2={leftPadding + chartWidth}
                                    y2={y}
                                    stroke="#e5e7eb"
                                    strokeWidth={1}
                                    aria-hidden="true"
                                />
                                {/* Tick mark */}
                                <line
                                    x1={leftPadding - 5}
                                    y1={y}
                                    x2={leftPadding}
                                    y2={y}
                                    stroke="#9ca3af"
                                    strokeWidth={1}
                                    aria-hidden="true"
                                />
                                {/* Y-axis label */}
                                <text
                                    x={leftPadding - 10}
                                    y={y}
                                    textAnchor="end"
                                    dominantBaseline="middle"
                                    className="text-xs fill-gray-600"
                                >
                                    {formatNumber(tickValue as number)}
                                </text>
                            </g>
                        );
                    })}

                    {/* Y-axis line */}
                    <line
                        x1={leftPadding}
                        y1={topPadding}
                        x2={leftPadding}
                        y2={topPadding + chartHeight}
                        stroke="#9ca3af"
                        strokeWidth={2}
                        aria-hidden="true"
                    />

                    {/* X-axis line */}
                    <line
                        x1={leftPadding}
                        y1={topPadding + chartHeight}
                        x2={leftPadding + chartWidth}
                        y2={topPadding + chartHeight}
                        stroke="#9ca3af"
                        strokeWidth={2}
                        aria-hidden="true"
                    />

                    {/* Line path */}
                    <path
                        d={pathData}
                        fill="none"
                        stroke={lineColor}
                        strokeWidth={3}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                    />

                    {/* Points */}
                    {yValues.map((value, idx) => {
                        const x = leftPadding + idx * pointSpacing;
                        const y = topPadding + (chartHeight - ((value - minTickValue) / range) * chartHeight);
                        const formattedLabel = formatDateLabel(xLabels[idx], spec.granularity);

                        return (
                            <circle
                                key={idx}
                                cx={x}
                                cy={y}
                                r={4}
                                fill={lineColor}
                                className="hover:r-6 transition-all"
                                aria-label={`${formattedLabel}: ${formatNumber(value)}`}
                            >
                                <title>{`${formattedLabel}: ${formatNumber(value)}`}</title>
                            </circle>
                        );
                    })}

                    {/* X-axis labels */}
                    {xLabels.map((label, idx) => {
                        const x = leftPadding + idx * pointSpacing;
                        const formatted = formatDateLabel(label, spec.granularity);
                        return (
                            <text
                                key={idx}
                                x={x}
                                y={topPadding + chartHeight + 12}
                                textAnchor="end"
                                transform={`rotate(-45, ${x}, ${topPadding + chartHeight + 12})`}
                                className="text-xs fill-gray-600"
                            >
                                {formatted}
                            </text>
                        );
                    })}
                </svg>
            </div>
        </div>
    );
}

// Pie Chart Renderer (SVG implementation)
function PieChartRenderer({ spec }: { spec: VisualSpec }) {
    const series = spec.series?.[0];
    const labels = spec.x_axis?.values || [];
    const values = series?.values || [];

    if (values.length === 0) return null;

    const total = values.reduce((sum, v) => sum + (typeof v === 'number' ? v : 0), 0);
    const colors = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"];

    let currentAngle = -90; // Start from top
    const slices = values.map((value, idx) => {
        const percentage = (value / total) * 100;
        const angle = (value / total) * 360;
        const startAngle = currentAngle;
        const endAngle = currentAngle + angle;
        currentAngle = endAngle;

        return {
            value,
            percentage,
            startAngle,
            endAngle,
            color: colors[idx % colors.length],
            label: labels[idx],
        };
    });

    return (
        <div className="bg-white p-8 rounded-lg border border-gray-200">
            <div className="flex flex-col md:flex-row gap-6">
                <div className="flex-1">
                    <svg
                        width="300"
                        height="300"
                        viewBox="-150 -150 300 300"
                        role="img"
                        aria-label={`Pie chart showing distribution of ${spec.y_axis?.label || "values"}`}
                    >
                        <title>{spec.title || `Pie chart of ${spec.y_axis?.label}`}</title>
                        {slices.map((slice, idx) => {
                            const radius = 120;
                            const startRad = (slice.startAngle * Math.PI) / 180;
                            const endRad = (slice.endAngle * Math.PI) / 180;
                            const x1 = radius * Math.cos(startRad);
                            const y1 = radius * Math.sin(startRad);
                            const x2 = radius * Math.cos(endRad);
                            const y2 = radius * Math.sin(endRad);
                            const largeArc = slice.percentage > 50 ? 1 : 0;

                            return (
                                <path
                                    key={idx}
                                    d={`M 0 0 L ${x1} ${y1} A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2} Z`}
                                    fill={slice.color}
                                    opacity={0.9}
                                    className="hover:opacity-100 transition-opacity"
                                    aria-label={`${slice.label}: ${slice.percentage.toFixed(1)}%`}
                                >
                                    <title>{`${slice.label}: ${slice.value.toLocaleString()} (${slice.percentage.toFixed(1)}%)`}</title>
                                </path>
                            );
                        })}
                    </svg>
                </div>
                <div className="flex-1 space-y-2">
                    {slices.map((slice, idx) => (
                        <div key={idx} className="flex items-center gap-3">
                            <div
                                className="w-4 h-4 rounded"
                                style={{ backgroundColor: slice.color }}
                                aria-hidden="true"
                            />
                            <div className="flex-1">
                                <p className="text-sm font-medium text-gray-900">{slice.label}</p>
                                <p className="text-xs text-gray-500">
                                    {slice.value.toLocaleString()} ({slice.percentage.toFixed(1)}%)
                                </p>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
