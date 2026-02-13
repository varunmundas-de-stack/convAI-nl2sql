# NL2SQL Frontend

A Next.js-based chat interface for natural language to SQL queries.

## Tech Stack

- **Framework**: Next.js 16 (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS v4
- **State Management**: React hooks only
- **Charts**: Recharts

## Project Structure

```
frontend/src/
├── app/
│   ├── page.tsx          # Main entry point
│   ├── layout.tsx        # Root layout
│   └── globals.css       # Global styles
├── components/
│   ├── ChatWindow.tsx           # Main chat interface
│   ├── MessageBubble.tsx        # Message rendering
│   ├── ClarificationPrompt.tsx  # Clarification UI
│   ├── TableRenderer.tsx        # Table visualization
│   └── ChartRenderer.tsx        # Chart visualization
├── services/
│   └── api.ts            # Backend API client
├── state/
│   └── conversation.ts   # Conversation state management
└── types/
    └── chat.ts           # TypeScript types
```

## Backend Endpoints

The frontend connects to these backend endpoints:

- `GET /health` - Health check
- `POST /query` - Send user query
- `POST /clarify` - Send clarification response
- `GET /catalog/metrics` - Get available metrics
- `GET /catalog/dimensions` - Get available dimensions
- `GET /catalog/time-windows` - Get available time windows

## Features

### Core Chat Behavior

- ✅ Textarea input with auto-resize
- ✅ Send on `Enter`, newline on `Shift+Enter`
- ✅ Disable input when backend unavailable
- ✅ Auto-scroll to latest message
- ✅ Loading indicator during API calls
- ✅ Backend health check with visual status indicator

### Conversation Logic

1. All user messages go to `/query`
2. If response type is `clarification_required`, switch to clarification mode
3. In clarification mode, send user reply to `/clarify`
4. Reset clarification mode after successful answer

### Response Types

The backend returns one of these response types:

```typescript
type ChatResponse =
  | { type: "text"; content: string }
  | { type: "table"; columns: string[]; rows: any[]; explanation?: string }
  | { type: "chart"; chartType: "bar" | "line" | "pie"; data: any; explanation?: string }
  | { type: "clarification_required"; question: string }
  | { type: "error"; message: string };
```

### UI Rendering

- **User messages**: Blue background, right-aligned
- **Assistant messages**: Gray background, left-aligned
- **Clarification prompts**: Amber background with warning icon
- **Tables**: Styled table with headers and hover effects
- **Charts**: Rendered using Recharts (bar, line, pie)
- **Errors**: Red background with error message

## Environment Variables

Create a `.env.local` file:

```env
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

## Development

```bash
# Install dependencies
npm install

# Run development server
npm run dev

# Build for production
npm run build

# Start production server
npm start
```

The app will be available at `http://localhost:3000`.

## Non-Goals

This implementation explicitly does NOT include:

- ❌ Authentication
- ❌ Database
- ❌ Design system library
- ❌ Markdown editor
- ❌ Redux / Zustand

## Component Details

### ChatWindow

Main chat interface with:
- Message list with auto-scroll
- Input textarea with keyboard shortcuts
- Backend health monitoring
- Loading states
- Clarification mode indicator

### MessageBubble

Renders individual messages with:
- Role-based styling (user/assistant/system)
- Response data rendering (table/chart/clarification/error)
- Proper text wrapping

### TableRenderer

Displays tabular data with:
- Column headers
- Row hover effects
- Optional explanation text
- Responsive overflow handling

### ChartRenderer

Visualizes data using Recharts:
- Bar charts
- Line charts
- Pie charts with percentage labels
- Optional explanation text
- Responsive container

### ClarificationPrompt

Distinctive UI for clarification requests:
- Amber color scheme
- Warning icon
- Clear messaging

## API Client

The `api.ts` service provides typed functions for all backend endpoints:

```typescript
healthCheck()              // GET /health
sendQuery(message, context?) // POST /query
clarify(payload)           // POST /clarify
getCatalogMetrics()        // GET /catalog/metrics
getCatalogDimensions()     // GET /catalog/dimensions
getCatalogTimeWindows()    // GET /catalog/time-windows
```

## State Management

The `useConversation` hook manages:
- Message history
- Pending clarification state
- Response handling
- Message addition

## Type Safety

All API responses and component props are fully typed using TypeScript interfaces defined in `types/chat.ts`.
