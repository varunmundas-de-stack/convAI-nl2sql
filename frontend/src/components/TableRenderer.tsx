"use client";

import { useState, useMemo, useCallback, useRef, useEffect } from "react";
import { FixedSizeList as List } from "react-window";
import { TableResponse } from "@/types/chat";
import { LayoutGrid, Table2, ChevronDown } from "lucide-react";

interface TableRendererProps {
    data: TableResponse;
}

// ─── Utilities ────────────────────────────────────────────────────────────────

function cleanColumnName(col: string): string {
    if (!col) return "Value";
    let cleaned = col;
    const prefixes = [
        "fact_secondary_sales.", "fact_primary_sales.",
        "fact secondary sales.", "fact primary sales.",
        "dim_product.", "dim_region.", "dim_time.", "fact_", "dim_",
    ];
    for (const prefix of prefixes) {
        if (cleaned.toLowerCase().startsWith(prefix.toLowerCase())) {
            cleaned = cleaned.substring(prefix.length);
            break;
        }
    }
    if (cleaned.includes(".")) cleaned = cleaned.split(".").pop()!;
    return cleaned.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function formatCellValue(value: any, isPrice: boolean = false): string {
    if (value === null || value === undefined || value === "") return "–";
    if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(value)) {
        try {
            return new Date(value).toLocaleDateString("en-GB", {
                day: "2-digit", month: "short", year: "numeric",
            });
        } catch { return String(value); }
    }
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

function isNumericColumn(rows: any[], col: string): boolean {
    const samples = rows.slice(0, 5).map(r => r[col]).filter(v => v != null);
    return samples.length > 0 && samples.some(v => typeof v === "number" || (typeof v === "string" && !isNaN(Number(v)) && v.trim() !== ""));
}

function isPriceColumn(col: string): boolean {
    if (!col) return false;
    const lower = col.toLowerCase();
    if (lower.includes("qty") || lower.includes("quantity") || lower.includes("volume") || lower.includes("count")) {
        return false;
    }
    return lower.includes("sales") || lower.includes("value") || lower.includes("revenue") || lower.includes("amount") || lower.includes("price") || lower.includes("cost") || lower.includes("margin");
}

// ─── Column deduplication ─────────────────────────────────────────────────────
const TIME_GRANULARITIES = new Set(["day", "week", "month", "quarter", "year"]);

function deduplicateTimeColumns(columns: string[]): string[] {
    const shadowed = new Set<string>();
    for (const col of columns) {
        const lastDot = col.lastIndexOf(".");
        if (lastDot === -1) continue;
        const suffix = col.substring(lastDot + 1);
        if (TIME_GRANULARITIES.has(suffix)) {
            const base = col.substring(0, lastDot);
            shadowed.add(base);
        }
    }
    if (shadowed.size === 0) return columns;
    return columns.filter(col => !shadowed.has(col));
}

// ─── Virtualised flat table ───────────────────────────────────────────────────
// Uses react-window FixedSizeList for large datasets (>100 rows).
// For small datasets (<= 100 rows) falls back to the original DOM table
// to preserve natural table behaviour (borders, hover, selection).

const ROW_HEIGHT = 44;       // px — matches py-3 + border
const HEADER_HEIGHT = 44;    // px
const MAX_VISIBLE_ROWS = 12; // rows shown before virtualising scroll

function FlatTable({ columns, rows }: { columns: string[]; rows: any[] }) {
    const numericColumns = useMemo(
        () => new Set(columns.filter(c => isNumericColumn(rows, c))),
        [columns, rows]
    );

    const containerRef = useRef<HTMLDivElement>(null);
    const [containerWidth, setContainerWidth] = useState(800);

    useEffect(() => {
        if (!containerRef.current) return;
        const ro = new ResizeObserver(([entry]) => {
            setContainerWidth(entry.contentRect.width);
        });
        ro.observe(containerRef.current);
        return () => ro.disconnect();
    }, []);

    // For small datasets use the original table — no virtualisation overhead
    if (rows.length <= 100) {
        return (
            <div className="overflow-x-auto rounded-xl border border-gray-200 shadow-sm bg-white">
                <div className="max-h-[560px] overflow-y-auto">
                    <table className="min-w-full divide-y divide-gray-100 text-sm">
                        <thead className="bg-gray-50 sticky top-0 z-10">
                            <tr>
                                {columns.map((col, i) => (
                                    <th
                                        key={i}
                                        className={`px-5 py-3 text-xs font-semibold tracking-wider text-gray-500 uppercase border-b border-gray-200 ${numericColumns.has(col) ? "text-right" : "text-left"}`}
                                    >
                                        {cleanColumnName(col)}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-50">
                            {rows.length === 0 ? (
                                <tr>
                                    <td colSpan={columns.length} className="px-5 py-10 text-center text-gray-400 italic">
                                        No data
                                    </td>
                                </tr>
                            ) : (
                                rows.map((row, ri) => (
                                    <tr
                                        key={ri}
                                        className={`transition-colors duration-100 ${ri % 2 === 0 ? "bg-white" : "bg-gray-50/50"} hover:bg-blue-50/40`}
                                    >
                                        {columns.map((col, ci) => (
                                            <td
                                                key={ci}
                                                className={`px-5 py-3 text-gray-800 ${numericColumns.has(col) ? "text-right font-mono tabular-nums whitespace-nowrap" : "text-left"}`}
                                            >
                                                {formatCellValue(row[col], isPriceColumn(col))}
                                            </td>
                                        ))}
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        );
    }

    // Large dataset — virtualised rendering
    const listHeight = Math.min(rows.length, MAX_VISIBLE_ROWS) * ROW_HEIGHT;

    const Row = useCallback(({ index, style }: { index: number; style: React.CSSProperties }) => {
        const row = rows[index];
        return (
            <div
                style={style}
                className={`flex border-b border-gray-100 transition-colors ${index % 2 === 0 ? "bg-white" : "bg-gray-50/50"} hover:bg-blue-50/40`}
            >
                {columns.map((col, ci) => (
                    <div
                        key={ci}
                        className={`flex-1 px-5 flex items-center text-sm text-gray-800 min-w-[120px] ${numericColumns.has(col) ? "justify-end font-mono tabular-nums whitespace-nowrap" : "justify-start"}`}
                    >
                        {formatCellValue(row[col], isPriceColumn(col))}
                    </div>
                ))}
            </div>
        );
    }, [rows, columns, numericColumns]);

    return (
        <div ref={containerRef} className="rounded-xl border border-gray-200 shadow-sm bg-white overflow-hidden">
            {/* Sticky header */}
            <div className="bg-gray-50 border-b border-gray-200 flex sticky top-0 z-10">
                {columns.map((col, i) => (
                    <div
                        key={i}
                        className={`flex-1 px-5 py-3 text-xs font-semibold tracking-wider text-gray-500 uppercase min-w-[120px] ${numericColumns.has(col) ? "text-right" : "text-left"}`}
                    >
                        {cleanColumnName(col)}
                    </div>
                ))}
            </div>

            {/* Virtualised rows */}
            <List
                height={listHeight}
                itemCount={rows.length}
                itemSize={ROW_HEIGHT}
                width="100%"
            >
                {Row}
            </List>

            {/* Row count footer */}
            <div className="px-5 py-2 text-xs text-gray-400 border-t border-gray-100 bg-gray-50">
                Showing all {rows.length.toLocaleString()} rows — scrolling virtualised
            </div>
        </div>
    );
}

// ─── Pivot selector ───────────────────────────────────────────────────────────

function Select({
    label, value, options, onChange,
}: { label: string; value: string; options: string[]; onChange: (v: string) => void }) {
    return (
        <div className="flex flex-col gap-1">
            <label className="text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                {label}
            </label>
            <div className="relative">
                <select
                    value={value}
                    onChange={e => onChange(e.target.value)}
                    className="appearance-none w-40 pl-3 pr-8 py-1.5 text-sm bg-white border border-gray-200 rounded-lg shadow-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-300 cursor-pointer"
                >
                    {options.map(o => (
                        <option key={o} value={o}>{cleanColumnName(o)}</option>
                    ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400" />
            </div>
        </div>
    );
}

// ─── Pivot table ──────────────────────────────────────────────────────────────
// Unchanged from original — pivot builds a computed matrix, not a raw row list,
// so react-window virtualisation does not apply here.

function PivotTable({
    columns, rows,
}: { columns: string[]; rows: any[] }) {
    const numericCols = useMemo(() => columns.filter(c => isNumericColumn(rows, c)), [columns, rows]);
    const categoricalCols = useMemo(() => columns.filter(c => !isNumericColumn(rows, c)), [columns, rows]);

    const defaultRow = categoricalCols[0] ?? columns[0] ?? "";
    const defaultCol = categoricalCols[1] ?? categoricalCols[0] ?? columns[0] ?? "";
    const defaultVal = numericCols[0] ?? columns[columns.length - 1] ?? "";

    const [rowDim, setRowDim] = useState(defaultRow);
    const [colDim, setColDim] = useState(defaultCol);
    const [valMetric, setValMetric] = useState(defaultVal);

    const { rowKeys, colKeys, matrix } = useMemo(() => {
        const rowKeySet = new Set<string>();
        const colKeySet = new Set<string>();
        const cells: Record<string, Record<string, number[]>> = {};

        for (const row of rows) {
            const rk = String(row[rowDim] ?? "–");
            const ck = String(row[colDim] ?? "–");
            const v = row[valMetric];
            const num = typeof v === "number" ? v : parseFloat(v);
            rowKeySet.add(rk);
            colKeySet.add(ck);
            if (!cells[rk]) cells[rk] = {};
            if (!cells[rk][ck]) cells[rk][ck] = [];
            if (!isNaN(num)) cells[rk][ck].push(num);
        }

        const rowKeys = Array.from(rowKeySet).sort();
        const colKeys = Array.from(colKeySet).sort();

        const matrix: Record<string, Record<string, number | null>> = {};
        for (const rk of rowKeys) {
            matrix[rk] = {};
            for (const ck of colKeys) {
                const vals = cells[rk]?.[ck];
                matrix[rk][ck] = vals && vals.length > 0
                    ? vals.reduce((a, b) => a + b, 0)
                    : null;
            }
        }

        return { rowKeys, colKeys, matrix };
    }, [rows, rowDim, colDim, valMetric]);

    const rowTotals = useMemo(
        () => rowKeys.map(rk => colKeys.reduce((s, ck) => s + (matrix[rk][ck] ?? 0), 0)),
        [rowKeys, colKeys, matrix],
    );
    const colTotals = useMemo(
        () => colKeys.map(ck => rowKeys.reduce((s, rk) => s + (matrix[rk][ck] ?? 0), 0)),
        [rowKeys, colKeys, matrix],
    );
    const grandTotal = rowTotals.reduce((a, b) => a + b, 0);

    const maxVal = Math.max(...rowTotals, 1);
    function heatColor(val: number | null): string {
        if (val === null || val === 0) return "";
        const intensity = Math.round((val / maxVal) * 100);
        if (intensity > 80) return "bg-blue-100 text-blue-900";
        if (intensity > 50) return "bg-blue-50 text-blue-800";
        if (intensity > 20) return "bg-sky-50 text-sky-700";
        return "";
    }

    const allCols = columns;
    const isPrice = isPriceColumn(valMetric);

    return (
        <div className="space-y-3">
            <div className="flex flex-wrap items-end gap-4 px-1">
                <Select label="Rows" value={rowDim} options={allCols} onChange={setRowDim} />
                <Select label="Columns" value={colDim} options={allCols} onChange={setColDim} />
                <Select label="Values (sum)" value={valMetric} options={allCols} onChange={setValMetric} />
            </div>

            {rowDim === colDim ? (
                <p className="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                    Row and column dimensions are the same — choose different fields for a meaningful pivot.
                </p>
            ) : (
                <div className="overflow-x-auto rounded-xl border border-gray-200 shadow-sm bg-white">
                    <div className="max-h-[560px] overflow-y-auto">
                        <table className="min-w-full text-sm border-collapse">
                            <thead className="sticky top-0 z-10">
                                <tr className="bg-gray-50 border-b border-gray-200">
                                    <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500 border-r border-gray-200 min-w-[140px]">
                                        {cleanColumnName(rowDim)}
                                        <span className="mx-1 text-gray-300">/</span>
                                        {cleanColumnName(colDim)}
                                    </th>
                                    {colKeys.map(ck => (
                                        <th
                                            key={ck}
                                            className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500 whitespace-nowrap"
                                        >
                                            {formatCellValue(ck)}
                                        </th>
                                    ))}
                                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-700 bg-gray-100 border-l border-gray-200">
                                        Total
                                    </th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                                {rowKeys.map((rk, ri) => (
                                    <tr
                                        key={rk}
                                        className={`transition-colors hover:bg-blue-50/30 ${ri % 2 === 0 ? "bg-white" : "bg-gray-50/40"}`}
                                    >
                                        <td className="px-5 py-3 text-left font-medium text-gray-700 border-r border-gray-100 whitespace-nowrap">
                                            {formatCellValue(rk)}
                                        </td>
                                        {colKeys.map(ck => {
                                            const val = matrix[rk][ck];
                                            return (
                                                <td
                                                    key={ck}
                                                    className={`px-4 py-3 text-right tabular-nums font-mono whitespace-nowrap ${heatColor(val)}`}
                                                >
                                                    {val !== null ? formatCellValue(val, isPrice) : "–"}
                                                </td>
                                            );
                                        })}
                                        <td className="px-4 py-3 text-right tabular-nums font-mono font-semibold text-gray-800 bg-gray-50 border-l border-gray-200 whitespace-nowrap">
                                            {formatCellValue(rowTotals[ri], isPrice)}
                                        </td>
                                    </tr>
                                ))}
                                <tr className="bg-gray-100 border-t-2 border-gray-300 font-semibold text-gray-800">
                                    <td className="px-5 py-3 text-left text-xs uppercase tracking-wider border-r border-gray-200">
                                        Total
                                    </td>
                                    {colTotals.map((t, i) => (
                                        <td key={i} className="px-4 py-3 text-right tabular-nums font-mono whitespace-nowrap">
                                            {formatCellValue(t, isPrice)}
                                        </td>
                                    ))}
                                    <td className="px-4 py-3 text-right tabular-nums font-mono text-blue-700 bg-blue-50 border-l border-gray-200 whitespace-nowrap">
                                        {formatCellValue(grandTotal, isPrice)}
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            <p className="text-[10px] text-gray-400 px-1">
                {rowKeys.length} rows × {colKeys.length} columns · values summed
            </p>
        </div>
    );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function TableRenderer({ data }: TableRendererProps) {
    const { columns: rawColumns, rows, explanation } = data;
    const columns = useMemo(() => deduplicateTimeColumns(rawColumns), [rawColumns]);
    const [view, setView] = useState<"flat" | "pivot">("flat");

    return (
        <div className="space-y-3">
            {explanation && (
                <p className="text-sm text-gray-700 italic bg-blue-50 border border-blue-200 rounded-lg px-4 py-2">
                    {explanation}
                </p>
            )}

            <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">
                    {rows.length} {rows.length === 1 ? "row" : "rows"}
                    {rows.length > 100 && (
                        <span className="ml-2 text-amber-500 font-medium">· large dataset</span>
                    )}
                </span>

                <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
                    <button
                        id="table-view-flat"
                        onClick={() => setView("flat")}
                        title="Flat table view"
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-150 ${view === "flat"
                            ? "bg-white text-gray-800 shadow-sm"
                            : "text-gray-500 hover:text-gray-700"
                            }`}
                    >
                        <Table2 className="h-3.5 w-3.5" />
                        Flat
                    </button>
                    {columns.length > 2 && (
                        <button
                            id="table-view-pivot"
                            onClick={() => setView("pivot")}
                            title="Pivot table view"
                            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-150 ${view === "pivot"
                                ? "bg-white text-gray-800 shadow-sm"
                                : "text-gray-500 hover:text-gray-700"
                                }`}
                        >
                            <LayoutGrid className="h-3.5 w-3.5" />
                            Pivot
                        </button>
                    )}
                </div>
            </div>

            {view === "flat" ? (
                <FlatTable columns={columns} rows={rows} />
            ) : (
                <PivotTable columns={columns} rows={rows} />
            )}
        </div>
    );
}
