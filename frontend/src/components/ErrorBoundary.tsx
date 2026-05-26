"use client";

import { Component, ReactNode } from "react";

interface Props { children: ReactNode; }
interface State { hasError: boolean; }

export default class ErrorBoundary extends Component<Props, State> {
    state: State = { hasError: false };

    static getDerivedStateFromError(): State {
        return { hasError: true };
    }

    render() {
        if (this.state.hasError) {
            return (
                <div className="flex items-center justify-center h-full w-full p-8">
                    <div className="card text-center max-w-sm p-8">
                        <div className="text-4xl mb-4">⚠️</div>
                        <h2 className="text-lg font-semibold text-gray-900 mb-2">Something went wrong</h2>
                        <p className="text-sm text-gray-500 mb-4">An unexpected error occurred. Please try again.</p>
                        <button
                            onClick={() => this.setState({ hasError: false })}
                            className="btn-primary px-4 py-2 rounded-xl text-sm text-white"
                        >
                            Try again
                        </button>
                    </div>
                </div>
            );
        }
        return this.props.children;
    }
}
