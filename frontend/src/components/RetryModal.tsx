"use client";

import { useState } from "react";
import { X, RotateCcw } from "lucide-react";

interface RetryModalProps {
    isOpen: boolean;
    originalQuery: string;
    onSubmit: (modifiedQuery: string) => void;
    onCancel: () => void;
}

export default function RetryModal({
    isOpen,
    originalQuery,
    onSubmit,
    onCancel,
}: RetryModalProps) {
    const [modifiedQuery, setModifiedQuery] = useState(originalQuery);
    const maxLength = 1000;

    if (!isOpen) return null;

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (modifiedQuery.trim()) {
            onSubmit(modifiedQuery.trim());
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Escape") {
            onCancel();
        }
    };

    const isQueryChanged = modifiedQuery.trim() !== originalQuery.trim();
    const isValid = modifiedQuery.trim().length > 0 && modifiedQuery.trim().length <= maxLength;

    return (
        <div
            className="fixed inset-0 flex items-center justify-center z-50 p-4"
            onKeyDown={handleKeyDown}
            tabIndex={-1}
        >
            <div className="bg-white rounded-lg shadow-lg max-w-2xl w-full max-h-[90vh] overflow-hidden">
                {/* Header */}
                <div className="flex items-center justify-between p-4 border-b border-gray-200">
                    <div className="flex items-center gap-2">
                        <RotateCcw size={18} className="text-blue-600" />
                        <h2 className="text-lg font-semibold text-gray-900">Retry Query</h2>
                    </div>
                    <button
                        onClick={onCancel}
                        className="p-1 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
                        title="Close"
                    >
                        <X size={18} />
                    </button>
                </div>

                <form onSubmit={handleSubmit} className="flex flex-col h-full">
                    {/* Content */}
                    <div className="p-4 space-y-4 flex-1 overflow-y-auto">
                        {/* Original Query Reference */}
                        <div className="space-y-2">
                            <label className="block text-sm font-medium text-gray-700">
                                Original Query
                            </label>
                            <div className="bg-gray-50 border border-gray-200 rounded-md p-3 text-sm text-gray-600">
                                {originalQuery}
                            </div>
                        </div>

                        {/* Modified Query Input */}
                        <div className="space-y-2">
                            <label
                                htmlFor="modified-query"
                                className="block text-sm font-medium text-gray-700"
                            >
                                Modified Query *
                            </label>
                            <textarea
                                id="modified-query"
                                value={modifiedQuery}
                                onChange={(e) => setModifiedQuery(e.target.value)}
                                className="w-full border border-gray-300 rounded-md p-3 text-sm focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 resize-none"
                                rows={4}
                                maxLength={maxLength}
                                placeholder="Enter your modified query here..."
                                autoFocus
                            />
                            <div className="flex justify-between items-center text-xs">
                                <span className={`${!isValid && modifiedQuery.length > maxLength ? 'text-red-500' : 'text-gray-500'}`}>
                                    {modifiedQuery.length}/{maxLength} characters
                                </span>
                                {isQueryChanged && (
                                    <span className="text-blue-600 font-medium">Query modified</span>
                                )}
                            </div>
                        </div>

                        {!isValid && modifiedQuery.length > 0 && (
                            <div className="text-sm text-red-600">
                                {modifiedQuery.length > maxLength
                                    ? `Query is too long (maximum ${maxLength} characters)`
                                    : "Query cannot be empty"
                                }
                            </div>
                        )}
                    </div>

                    {/* Footer */}
                    <div className="flex items-center justify-end gap-3 p-4 border-t border-gray-200">
                        <button
                            type="button"
                            onClick={onCancel}
                            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={!isValid}
                            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                        >
                            Retry Query
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}