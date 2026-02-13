"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronUp, TrendingUp, TrendingDown, Minus } from "lucide-react";

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
}

interface Axis {
    label: string;
    values?: any[];
    format?: string;
    axis_type?: "time" | "categorical" | "linear";
}

interface DataSeries {
    label: string;
    values: any[];
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
}

interface ChartRendererProps {
    visual_spec?: VisualSpec;
    refined_insights?: RefinedInsights;
}

export default function ChartRenderer({ visual_spec, refined_insights }: ChartRendererProps) {
    const [showInsights, setShowInsights] = useState(true);
    const [isClient, setIsClient] = useState(false);

    useEffect(() => {
        setIsClient(true);
    }, []);

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

            {/* Executive Summary (collapsible) */}
            {refined_insights?.executive_summary && (
                <div className="bg-blue-50 border border-blue-200 rounded-lg overflow-hidden">
                    <button
                        onClick={() => setShowInsights(!showInsights)}
                        className="w-full px-4 py-3 flex items-center justify-between hover:bg-blue-100 transition-colors"
                    >
                        <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-blue-900">Executive Summary</span>
                        </div>
                        {showInsights ? (
                            <ChevronUp className="h-4 w-4 text-blue-700" />
                        ) : (
                            <ChevronDown className="h-4 w-4 text-blue-700" />
                        )}
                    </button>
                    {showInsights && (
                        <div className="px-4 py-3 border-t border-blue-200">
                            <p className="text-sm text-blue-900">{refined_insights.executive_summary}</p>
                        </div>
                    )}
                </div>
            )}

            {/* Primary/Secondary Values for Number Cards and Snapshots */}
            {chart_type === "number_card" && primary_value && (
                <div className="bg-gradient-to-br from-blue-50 to-indigo-50 p-6 rounded-lg border border-blue-200">
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
                                        {direction === "up" && <TrendingUp className="h-4 w-4" />}
                                        {direction === "down" && <TrendingDown className="h-4 w-4" />}
                                        {direction === "flat" && <Minus className="h-4 w-4" />}
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
                <TableRenderer columns={visual_spec.columns} rows={visual_spec.rows} />
            ) : chart_type === "bar" || chart_type === "horizontal_bar" || chart_type === "stacked_bar" ? (
                <BarChartRenderer spec={visual_spec} />
            ) : chart_type === "line" ? (
                <LineChartRenderer spec={visual_spec} />
            ) : chart_type === "pie" ? (
                <PieChartRenderer spec={visual_spec} />
            ) : chart_type !== "number_card" ? (
                <div className="bg-white p-6 rounded-lg border border-gray-200">
                    <p className="text-gray-500">Unsupported chart type: {chart_type}</p>
                </div>
            ) : null}

            {/* Annotations */}
            {visual_spec.annotations && visual_spec.annotations.length > 0 && (
                <div className="space-y-2">
                    {visual_spec.annotations
                        .filter(a => a.position === "header" || a.position === "footer")
                        .map((annotation, idx) => (
                            <div
                                key={idx}
                                className={`px-4 py-3 rounded-lg border ${getSeverityStyles(annotation.severity)}`}
                            >
                                <div className="flex items-start gap-2">
                                    {annotation.direction && annotation.direction !== "unknown" && (
                                        <div className="mt-0.5">
                                            {annotation.direction === "up" && <TrendingUp className="h-4 w-4" />}
                                            {annotation.direction === "down" && <TrendingDown className="h-4 w-4" />}
                                            {annotation.direction === "flat" && <Minus className="h-4 w-4" />}
                                        </div>
                                    )}
                                    <p className="text-sm flex-1">{annotation.text}</p>
                                </div>
                            </div>
                        ))}
                </div>
            )}
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

// Table Renderer
function TableRenderer({ columns, rows }: { columns: string[]; rows: any[] }) {
    return (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                        <tr>
                            {columns.map((col, idx) => (
                                <th
                                    key={idx}
                                    className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                                >
                                    {col}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                        {rows.map((row, rowIdx) => (
                            <tr key={rowIdx} className="hover:bg-gray-50">
                                {columns.map((col, colIdx) => (
                                    <td key={colIdx} className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                        {row[col] !== undefined ? String(row[col]) : "-"}
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

// Bar Chart Renderer (Simple SVG implementation)
function BarChartRenderer({ spec }: { spec: VisualSpec }) {
    const series = spec.series?.[0];
    const xValues = spec.x_axis?.values || [];
    const yValues = series?.values || [];
    const pointColors = series?.point_colors || [];
    const pointEmphasis = series?.point_emphasis || [];

    if (yValues.length === 0) return null;

    const maxValue = Math.max(...yValues.map(v => typeof v === 'number' ? v : 0));
    const chartHeight = 300;
    const barWidth = Math.min(60, (600 / yValues.length) * 0.8);

    return (
        <div className="bg-white p-6 rounded-lg border border-gray-200">
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
                    <span className="text-gray-400">Max: {maxValue.toLocaleString()}</span>
                </div>
                <svg width="100%" height={chartHeight + 40} viewBox={`0 0 ${xValues.length * (barWidth + 10)} ${chartHeight + 40}`}>
                    {/* Bars */}
                    {yValues.map((value, idx) => {
                        const height = (value / maxValue) * chartHeight;
                        const x = idx * (barWidth + 10) + 5;
                        const y = chartHeight - height;

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
                                />
                                <text
                                    x={x + barWidth / 2}
                                    y={y - 5}
                                    textAnchor="middle"
                                    className="text-xs fill-gray-600"
                                >
                                    {value.toLocaleString()}
                                </text>
                                <text
                                    x={x + barWidth / 2}
                                    y={chartHeight + 20}
                                    textAnchor="middle"
                                    className="text-xs fill-gray-500"
                                >
                                    {String(xValues[idx] || idx).substring(0, 10)}
                                </text>
                            </g>
                        );
                    })}

                    {/* Threshold markers */}
                    {spec.markers?.filter(m => m.marker_type === "threshold").map((marker, idx) => {
                        const y = chartHeight - ((marker.value || 0) / maxValue) * chartHeight;
                        return (
                            <g key={`threshold-${idx}`}>
                                <line
                                    x1={0}
                                    y1={y}
                                    x2={xValues.length * (barWidth + 10)}
                                    y2={y}
                                    stroke="#94a3b8"
                                    strokeWidth={2}
                                    strokeDasharray="4 4"
                                />
                                <text
                                    x={5}
                                    y={y - 5}
                                    className="text-xs fill-gray-500"
                                >
                                    {marker.label}
                                </text>
                            </g>
                        );
                    })}
                </svg>
            </div>
        </div>
    );
}

// Line Chart Renderer (Simple SVG implementation)
function LineChartRenderer({ spec }: { spec: VisualSpec }) {
    const series = spec.series?.[0];
    const xValues = spec.x_axis?.values || [];
    const yValues = series?.values || [];

    if (yValues.length === 0) return null;

    const maxValue = Math.max(...yValues.map(v => typeof v === 'number' ? v : 0));
    const minValue = Math.min(...yValues.map(v => typeof v === 'number' ? v : 0));
    const chartHeight = 300;
    const chartWidth = 600;
    const pointSpacing = chartWidth / (yValues.length - 1 || 1);

    // Generate path
    const pathData = yValues
        .map((value, idx) => {
            const x = idx * pointSpacing;
            const y = chartHeight - ((value - minValue) / (maxValue - minValue)) * chartHeight;
            return `${idx === 0 ? 'M' : 'L'} ${x} ${y}`;
        })
        .join(' ');

    const lineColor = series?.color_hint === "positive" ? "#10b981" :
        series?.color_hint === "negative" ? "#ef4444" : "#3b82f6";

    return (
        <div className="bg-white p-6 rounded-lg border border-gray-200">
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
                            {spec.trend_slope > 0 && <TrendingUp className="h-4 w-4" />}
                            {spec.trend_slope < 0 && <TrendingDown className="h-4 w-4" />}
                            {spec.trend_slope === 0 && <Minus className="h-4 w-4" />}
                            <span>{Math.abs(spec.trend_slope).toFixed(1)}%</span>
                        </div>
                    )}
                </div>
            )}
            <div className="space-y-4">
                <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-600">{spec.y_axis?.label || "Value"}</span>
                </div>
                <svg width="100%" height={chartHeight + 40} viewBox={`0 0 ${chartWidth} ${chartHeight + 40}`}>
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
                        const x = idx * pointSpacing;
                        const y = chartHeight - ((value - minValue) / (maxValue - minValue)) * chartHeight;

                        return (
                            <circle
                                key={idx}
                                cx={x}
                                cy={y}
                                r={4}
                                fill={lineColor}
                                className="hover:r-6 transition-all"
                            />
                        );
                    })}

                    {/* X-axis labels */}
                    {xValues.map((label, idx) => {
                        const x = idx * pointSpacing;
                        return (
                            <text
                                key={idx}
                                x={x}
                                y={chartHeight + 20}
                                textAnchor="middle"
                                className="text-xs fill-gray-500"
                            >
                                {String(label).substring(0, 10)}
                            </text>
                        );
                    })}
                </svg>
            </div>
        </div>
    );
}

// Pie Chart Renderer (Simple SVG implementation)
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
        <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex flex-col md:flex-row gap-6">
                <div className="flex-1">
                    <svg width="300" height="300" viewBox="-150 -150 300 300">
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
                                />
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
