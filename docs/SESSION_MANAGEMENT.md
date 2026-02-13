# Session Management Implementation

## Summary

Implemented session tracking for conversational context in the NL2SQL chat application.

## How It Works

### Backend (Already Implemented)
1. **First Query**: Backend generates a unique `session_id` (e.g., `sess_abc123456`) when it receives a query without a `session_id`
2. **Returns session_id**: Backend includes the `session_id` in every response
3. **Follow-up Queries**: Backend uses the `session_id` to maintain conversational context via QCO (Query Context Object)

### Frontend (Newly Implemented)

#### Session Lifecycle
```
User sends first query
  ↓
Backend generates session_id
  ↓
Frontend receives & stores session_id 
  ↓
User sends follow-up query
  ↓
Frontend includes stored session_id in request
  ↓
Backend uses QCO to resolve context
```

#### API Service (`frontend/src/services/api.ts`)

**Session State Management:**
```typescript
// Module-level variable (persists for tab lifetime)
let currentSessionId: string | null = null;

export function getCurrentSessionId(): string | null
export function setSessionId(sessionId: string): void
export function resetSession(): void
```

**sendQuery() Flow:**
1. Check if `currentSessionId` exists
2. If yes: Include `session_id` in request body
3. If no: Send without `session_id` (backend will generate one)
4. Extract `session_id`from backend response
5. Store it using `setSessionId()`
6. Return it to caller

#### ChatWindow Component (`frontend/src/components/ChatWindow.tsx`)

**Features Added:**
1. **Session Display**: Shows current `session_id` in header
2. **New Conversation Button**: Resets session and clears messages
3. **Session Sync**: Periodically syncs session state from API

**UI Changes:**
```tsx
{sessionId && (
    <div>
        Session: <code>{sessionId}</code>
        <button onClick={handleNewConversation}>New</button>
    </div>
)}
```

## Example Usage

### First Query
```
POST /query
{
    "query": "Show me sales by region"
    // No session_id sent
}

Response:
{
    "success": true,
    "session_id": "sess_b72b140bcfa3",  ← Backend generated this
    "data": [...],
    ...
}
```

Frontend:
- Receives `sess_b72b140bcfa3`
- Stores it in `currentSessionId`
- Displays it in header

### Follow-up Query
```
POST /query
{
    "query": "What about for Mumbai only?",
    "session_id": "sess_b72b140bcfa3"  ← Frontend sends stored ID
}

Response:
{
    "success": true,
    "session_id": "sess_b72b140bcfa3",  ← Same session
    "data": [...],  ← Context-aware: knows we're talking about sales by region
    ...
}
```

Backend:
- Looks up QCO for `sess_b72b140bcfa3`
- Finds previous query context (sales metrics, region dimension)
- Resolves "Mumbai only" → adds filter to existing query

### New Conversation
```
User clicks "New" button
  ↓
Frontend calls resetSession()
  ↓
currentSessionId = null
  ↓
Messages cleared
  ↓
Next query starts fresh (no session_id sent)
  ↓
Backend generates new session_id
```

## Implementation Details

### Why Module-Level State?
- Persists across component renders
- Survives React re-renders
- Lost only on tab close/refresh (intentional - fresh start)

### Why Not in URL/LocalStorage?
- **URL**: Would clutter URL, hard to share
- **LocalStorage**: Would persist across tab closes (we want fresh sessions)
- **Memory**: Perfect for tab-scoped session management

### Clarification Endpoint
**Note:** `/clarify` endpoint does NOT need `session_id`
- The `request_id` already ties to the original session
- Backend tracks session via the request_id mapping

## Files Modified

1. **`frontend/src/services/api.ts`**
   - Added: `getCurrentSessionId()`, `setSessionId()`, `resetSession()`
   - Updated: `sendQuery()` to send/receive `session_id`
   - Updated: Return type to include `sessionId: string`

2. **`frontend/src/components/ChatWindow.tsx`**
   - Added: Session ID display in header
   - Added: "New" button to reset conversation
   - Added: Session sync logic
   - Added: `handleNewConversation()` function

3. **`frontend/src/state/conversation.ts`**
   - Added: `clearMessages()` function

## Testing

### Manual Test
1. Open chat
2. Send query: "Show me sales by region"
3. Check header - should see session ID (e.g.,  `sess_abc123`)
4. Send follow-up: "What about Mumbai only?"
5. Backend should understand context
6. Click "New" button
7. Session ID should disappear
8. Send new query
9. New session ID should appear

### Console Logs
Watch for these messages:
```
[Session] Sending first query - backend will generate session_id
[Session] Session ID updated: sess_b72b140bcfa3
[Session] Sending query with existing session_id: sess_b72b140bcfa3
[Session] Session reset - new conversation started
```

## Benefits

1. **Contextual Follow-ups**: "Show it for Mumbai" works without repeating full query
2. **Visual Feedback**: User sees they're in a continuous conversation
3. **Easy Reset**: One click to start fresh
4. **No Server State**: Sessions are lightweight, just IDs linking to QCOs
5. **Tab-Scoped**: Each tab has independent conversation

## Known Limitations

1. **No Persistence**: Closing tab loses session (by design)
2. **No Multi-Tab Sync**: Each tab has separate session
3. **No Session History**: Can't go back to previous sessions
4. **No Session Naming**: Sessions only have auto-generated IDs

## Future Enhancements

- Add session naming/titling
- Persist sessions to localStorage (optional)
- Session history/sidebar
- Multi-turn conversation summary
- Export conversation as PDF/text
