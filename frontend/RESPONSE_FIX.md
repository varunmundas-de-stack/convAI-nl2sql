# Frontend Response Rendering Fix

## Problem
The `/query` endpoint response wasn't being rendered in the frontend.

## Root Cause
The backend returns a different response structure than what the frontend expected:

**Backend Response:**
```json
{
  "query": "...",
  "success": true/false,
  "stage": "...",
  "clarification": true/false,
  "clarification_message": ["question1", "question2"],
  "missing_fields": ["time_dimension", "time_range"],
  "request_id": "...",
  "data": [...],
  "visualization": {...}
}
```

**Frontend Expected:**
```json
{
  "type": "text" | "table" | "chart" | "clarification_required" | "error",
  "content": "...",
  "columns": [...],
  "rows": [...],
  ...
}
```

## Solution

### 1. Added Transformation Layer (`api.ts`)
Created `transformBackendResponse()` function to convert backend response format to frontend `ChatResponse` format:

- Maps `clarification: true` → `type: "clarification_required"`
- Maps `success: false` → `type: "error"`
- Maps `data` + `visualization` → `type: "chart"` or `type: "table"`
- Extracts chart type from `visualization.chart_type`

### 2. Updated API Functions
Modified `sendQuery()` and `clarify()` to return both:
- `response`: Transformed ChatResponse
- `raw`: Original backend response (needed for `request_id` and `missing_fields`)

### 3. Fixed Conversation State (`conversation.ts`)
- Added `backendResponse` state to store raw backend response
- Updated `handleResponse()` to accept both transformed and raw responses
- Properly reset clarification state after successful answers

### 4. Fixed ChatWindow (`ChatWindow.tsx`)
- Destructured `backendResponse` from `useConversation()`
- Updated `onSend()` to:
  - Extract `missing_fields` from backend response
  - Build `answers` object keyed by field names (not generic IDs)
  - Support comma-separated answers for multiple fields
  - Pass both `result.response` and `result.raw` to `handleResponse()`
- Improved clarification mode indicator to show:
  - Which fields need answers
  - Helpful tip about comma-separated input

### 5. Clarification Flow
**Before:**
```typescript
clarify({ answer: userInput })  // ❌ Wrong format
```

**After:**
```typescript
clarify({
  request_id: backendResponse.request_id,
  answers: {
    time_dimension: "day",
    time_range: "last 30 days"
  }
})  // ✅ Correct format
```

## Files Changed
1. `src/services/api.ts` - Added transformation layer
2. `src/state/conversation.ts` - Store raw backend response
3. `src/components/ChatWindow.tsx` - Fixed clarification handling
4. `src/components/ClarificationPrompt.tsx` - Already correct
5. `src/components/TableRenderer.tsx` - Already correct
6. `src/components/ChartRenderer.tsx` - Already correct

## Testing
To test the complete flow:

1. **Query**: "What are the top 5 zones by total quantity?"
2. **Backend Response**: Clarification needed for time_dimension and time_range
3. **User Input**: "day, last 30 days"
4. **Backend receives**:
   ```json
   {
     "request_id": "...",
     "answers": {
       "time_dimension": "day",
       "time_range": "last 30 days"
     }
   }
   ```
5. **Result**: Table or chart rendered with data

## Key Improvements
✅ Backend response properly transformed to frontend format
✅ Clarification flow works with correct payload structure
✅ Tables and charts render correctly
✅ Error handling improved
✅ Better UX with helpful clarification instructions
