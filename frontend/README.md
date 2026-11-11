# AnatomyRAG frontend

Next.js chat UI for AnatomyRAG. See the [main README](../README.md) for the full project.

```bash
npm install
cp .env.example .env.local   # NEXT_PUBLIC_API_URL points at the backend
npm run dev                  # http://localhost:3000
```

- `components/Chat.tsx`: conversation state, streaming, follow-up history
- `components/Answer.tsx`: renders streamed text segments with citation chips
- `components/SourcePanel.tsx`: the cited passage, with the cited sentences highlighted
- `lib/api.ts`: SSE client for `POST /api/chat`
