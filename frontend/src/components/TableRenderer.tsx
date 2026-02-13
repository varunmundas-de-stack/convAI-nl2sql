"use client";

import { TableResponse } from "@/types/chat";

interface TableRendererProps {
    data: TableResponse;
}

export default function TableRenderer({ data }: TableRendererProps) {
    const { columns, rows, explanation } = data;

    return (
        <div className="space-y-3">
            {explanation && (
                <p className="text-sm text-gray-700 italic">{explanation}</p>
            )}
            <div className="overflow-x-auto rounded-lg border border-gray-200 shadow-sm">
                <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                        <tr>
                            {columns.map((col, idx) => (
                                <th
                                    key={idx}
                                    className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider"
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
                                    <td
                                        key={colIdx}
                                        className="px-4 py-3 text-sm text-gray-900 whitespace-nowrap"
                                    >
                                        {row[col] !== null && row[col] !== undefined
                                            ? String(row[col])
                                            : "-"}
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
