"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Lightbulb } from "lucide-react";
import { getInsights, markInsightRead, getAccessToken } from "@/services/api";

export default function InsightsPage() {
    const [insights, setInsights] = useState<any[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const router = useRouter();

    useEffect(() => {
        if (!getAccessToken()) {
            router.push("/");
            return;
        }

        getInsights()
            .then((data) => setInsights(data.insights || []))
            .catch(() => setInsights([]))
            .finally(() => setIsLoading(false));
    }, [router]);

    const handleInsightClick = (insight: any) => {
        if (insight.insight_id) {
            markInsightRead(insight.insight_id).catch(() => null);
        }
        if (insight.suggested_query) {
            sessionStorage.setItem("suggested_query", insight.suggested_query);
        }
        router.push("/");
    };

    return (
        <div className="flex flex-col min-h-screen bg-gray-50">
            <div className="bg-white border-b border-gray-200 px-6 py-4 shadow-sm z-10 flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <button
                        onClick={() => router.push("/")}
                        className="p-2 text-gray-500 hover:bg-gray-100 rounded-md transition-colors"
                        title="Back to Chat"
                    >
                        <ArrowLeft size={20} />
                    </button>
                    <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
                        <Lightbulb size={20} className="text-yellow-500" />
                        Business Insights
                    </h1>
                </div>
            </div>

            <div className="flex-1 max-w-4xl w-full mx-auto p-6 md:p-8">
                {isLoading ? (
                    <div className="flex justify-center items-center h-40">
                        <div className="w-6 h-6 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
                    </div>
                ) : insights.length === 0 ? (
                    <div className="text-center text-gray-500 mt-20">
                        <Lightbulb size={48} className="mx-auto text-gray-300 mb-4" />
                        <p className="text-lg">No insights available right now.</p>
                    </div>
                ) : (
                    <div className="grid gap-4">
                        {insights.map((insight) => (
                            <button
                                key={insight.insight_id}
                                onClick={() => handleInsightClick(insight)}
                                className="w-full text-left bg-white border border-gray-200 rounded-xl p-5 shadow-sm hover:shadow-md hover:border-blue-200 transition-all group"
                            >
                                <div className="flex justify-between items-start mb-2">
                                    <h3 className="text-lg font-medium text-gray-900 group-hover:text-blue-700 transition-colors">
                                        {insight.title}
                                    </h3>
                                    {!insight.is_read && (
                                        <span className="bg-blue-100 text-blue-800 text-xs font-semibold px-2.5 py-0.5 rounded-full whitespace-nowrap">
                                            New
                                        </span>
                                    )}
                                </div>
                                <p className="text-gray-600 mb-4">{insight.description}</p>
                                {insight.suggested_query && (
                                    <div className="bg-gray-50 p-3 rounded-lg text-sm text-gray-700 border border-gray-100 flex items-center gap-2">
                                        <span className="font-semibold text-gray-500">Ask:</span>
                                        <code className="text-blue-600 font-mono text-xs">{insight.suggested_query}</code>
                                    </div>
                                )}
                            </button>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
