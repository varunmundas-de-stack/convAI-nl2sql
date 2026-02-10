"use client";

import { ChartResponse } from "@/types/chat";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

// Dynamically import Plotly to avoid SSR issues
const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

interface ChartRendererProps {
    data: ChartResponse;
}

export default function ChartRenderer({ data }: ChartRendererProps) {
    const { chartType, data: chartData, explanation } = data;
    const [plotlyData, setPlotlyData] = useState<any>(null);
    const [isClient, setIsClient] = useState(false);

    useEffect(() => {
        setIsClient(true);
    }, []);

    useEffect(() => {
        // Check if chartData is a visualization object with Plotly JSON
        if (
            chartData &&
            typeof chartData === "object" &&
            "output_format" in chartData &&
            chartData.output_format === "plotly_json"
        ) {
            try {
                // Parse the Plotly JSON content
                const plotlySpec =
                    typeof chartData.content === "string"
                        ? JSON.parse(chartData.content)
                        : chartData.content;
                setPlotlyData(plotlySpec);
            } catch (error) {
                console.error("Failed to parse Plotly JSON:", error);
                setPlotlyData(null);
            }
        } else {
            setPlotlyData(null);
        }
    }, [chartData]);

    // Don't render on server
    if (!isClient) {
        return (
            <div className="space-y-3">
                {explanation && (
                    <p className="text-sm text-gray-700 italic">{explanation}</p>
                )}
                <div className="bg-white p-4 rounded-lg border border-gray-200 h-[300px] flex items-center justify-center">
                    <p className="text-gray-500">Loading chart...</p>
                </div>
            </div>
        );
    }

    // Render Plotly chart if we have Plotly data
    if (plotlyData) {
        // Determine height based on chart type
        const isIndicator = plotlyData.data?.[0]?.type === "indicator";
        const chartHeight = isIndicator ? "200px" : "400px";

        return (
            <div className="space-y-3">
                {explanation && (
                    <p className="text-sm text-gray-700 italic">{explanation}</p>
                )}
                <div className="bg-white p-4 rounded-lg border border-gray-200">
                    <Plot
                        data={plotlyData.data || []}
                        layout={{
                            ...plotlyData.layout,
                            autosize: true,
                            margin: { l: 50, r: 50, t: 50, b: 50 },
                        }}
                        config={{
                            ...plotlyData.config,
                            responsive: true,
                            displayModeBar: !isIndicator, // Hide toolbar for indicators
                            displaylogo: false,
                        }}
                        style={{ width: "100%", height: chartHeight }}
                        useResizeHandler={true}
                    />
                </div>
            </div>
        );
    }

    // Fallback: Render HTML if available
    if (
        chartData &&
        typeof chartData === "object" &&
        "output_format" in chartData &&
        chartData.output_format === "html"
    ) {
        return (
            <div className="space-y-3">
                {explanation && (
                    <p className="text-sm text-gray-700 italic">{explanation}</p>
                )}
                <div
                    className="bg-white p-4 rounded-lg border border-gray-200"
                    dangerouslySetInnerHTML={{ __html: chartData.content }}
                />
            </div>
        );
    }

    // Fallback: Show error message
    return (
        <div className="space-y-3">
            {explanation && (
                <p className="text-sm text-gray-700 italic">{explanation}</p>
            )}
            <div className="bg-white p-4 rounded-lg border border-gray-200">
                <p className="text-gray-500">
                    Unable to render chart. Unsupported format.
                </p>
                <pre className="text-xs text-gray-400 mt-2 overflow-auto">
                    {JSON.stringify(chartData, null, 2)}
                </pre>
            </div>
        </div>
    );
}
