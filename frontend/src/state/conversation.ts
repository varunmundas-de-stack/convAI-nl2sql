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
    const [compoundState, setCompoundState] = useState<any>(null);

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
        // ADD DEBUG LINE
        console.log("💬 Conversation handling response:", response.type, response);

        // Store the raw backend response for clarification
        if (rawBackendResponse) {
            setBackendResponse(rawBackendResponse);
        }

        // Handle compound clarifications
        if (response.type === "compound_clarification_required") {
            setPendingClarification(response);
            setCompoundState(response.compound_state);

            const clarificationText = `For "${response.pending_clarification.subquery_text}": ${response.pending_clarification.clarification.question}`;
            addAssistantMessage(clarificationText, response, rawBackendResponse);
            return;
        }

        // Handle regular clarifications
        if (response.type === "clarification_required") {
            setPendingClarification(response);
            addAssistantMessage(response.question, response, rawBackendResponse);
            return;
        }

        // Handle compound partial results
        if (response.type === "compound_partial_results") {
            // Don't reset clarification state for partial results - more may be coming
            const completedCount = response.completed_subqueries.length;
            const totalCount = response.compound_metadata.total_subqueries;
            const pendingCount = response.pending_subqueries.length;

            let content = `Showing partial results (${completedCount}/${totalCount} sections completed)`;
            if (pendingCount > 0) {
                content += `. ${pendingCount} section${pendingCount !== 1 ? 's' : ''} still processing...`;
            }

            addAssistantMessage(content, response, rawBackendResponse);
            return;
        }

        // Reset clarification mode after successful answer
        setPendingClarification(null);
        setBackendResponse(null);
        setCompoundState(null);

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
        setCompoundState(null);
    }

    function replaceMessages(
        nextMessages: ConversationMessage[],
        restoredPendingClarification: any = null,
        restoredBackendResponse: any = null,
        restoredCompoundState: any = null
    ) {
        setMessages(nextMessages);
        setPendingClarification(restoredPendingClarification);
        setBackendResponse(restoredBackendResponse);
        setCompoundState(restoredCompoundState);
    }

    return {
        messages,
        pendingClarification,
        backendResponse,
        compoundState,
        addUserMessage,
        handleResponse,
        clearMessages,
        replaceMessages,
    };
}

