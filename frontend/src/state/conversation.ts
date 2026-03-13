import { useState } from "react";
import { ChatMessage, ChatResponse } from "@/types/chat";

export interface ConversationMessage extends ChatMessage {
    responseData?: ChatResponse;
    rawBackendData?: any;  // Raw backend response for RLHF feedback (request_id, prompt_version, etc.)
}

export function useConversation() {
    const [messages, setMessages] = useState<ConversationMessage[]>([]);
    const [pendingClarification, setPendingClarification] = useState<any>(null);
    const [backendResponse, setBackendResponse] = useState<any>(null);

    function addUserMessage(content: string) {
        setMessages((m) => [
            ...m,
            { id: crypto.randomUUID(), role: "user", content },
        ]);
    }

    function addAssistantMessage(content: string, responseData?: ChatResponse, rawBackendData?: any) {
        setMessages((m) => [
            ...m,
            { id: crypto.randomUUID(), role: "assistant", content, responseData, rawBackendData },
        ]);
    }

    function handleResponse(response: ChatResponse, rawBackendResponse?: any) {
        // Store the raw backend response for clarification
        if (rawBackendResponse) {
            setBackendResponse(rawBackendResponse);
        }

        if (response.type === "clarification_required") {
            setPendingClarification(response);
            addAssistantMessage(response.question, response, rawBackendResponse);
            return;
        }

        // Reset clarification mode after successful answer
        setPendingClarification(null);
        setBackendResponse(null);

        if (response.type === "text") {
            addAssistantMessage(response.content, response, rawBackendResponse);
        } else if (response.type === "table") {
            const content = response.explanation || "";
            addAssistantMessage(content, response, rawBackendResponse);
        } else if (response.type === "chart") {
            const content = response.explanation || "";
            addAssistantMessage(content, response, rawBackendResponse);
        } else if (response.type === "error") {
            addAssistantMessage(`Error: ${response.message}`, response, rawBackendResponse);
        }
    }

    function clearMessages() {
        setMessages([]);
        setPendingClarification(null);
        setBackendResponse(null);
    }

    return {
        messages,
        pendingClarification,
        backendResponse,
        addUserMessage,
        handleResponse,
        clearMessages,
    };
}

