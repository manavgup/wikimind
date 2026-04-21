# Q&A Agent

WikiMind's Q&A agent answers questions against your compiled wiki, citing specific articles and suggesting follow-up questions.

## Asking Questions

### Simple question

```bash
curl -X POST http://localhost:7842/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the main arguments for and against microservices?"}'
```

The response includes:

```json
{
  "query": {
    "id": "...",
    "question": "What are the main arguments...",
    "answer": "Based on your wiki articles...",
    "confidence": "high",
    "source_article_ids": ["Article Title 1", "Article Title 2"],
    "conversation_id": "..."
  },
  "conversation": {
    "id": "...",
    "title": "What are the main arguments..."
  }
}
```

### Follow-up questions

Continue a conversation by passing the `conversation_id`:

```bash
curl -X POST http://localhost:7842/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How does that compare to the monolith approach?",
    "conversation_id": "CONVERSATION_ID"
  }'
```

The agent uses prior turns as context to disambiguate references like "it" or "that approach". Up to 5 prior turns are included (configurable via `WIKIMIND_QA__MAX_PRIOR_TURNS_IN_CONTEXT`).

### Streaming answers

For token-by-token streaming via Server-Sent Events:

```bash
curl -N http://localhost:7842/query/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "Summarize my notes on distributed systems"}'
```

SSE events:

| Event | Description |
|---|---|
| `chunk` | Text delta (partial answer) |
| `done` | Final response with full answer, sources, and metadata |
| `error` | Error occurred during streaming |

## File-Back

When an answer has high or medium confidence, you can file it back to the wiki. This creates a new article from the conversation, making the wiki smarter over time.

### Auto file-back

Set `file_back: true` in the request to automatically file high/medium confidence answers:

```bash
curl -X POST http://localhost:7842/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is the current state of quantum computing?",
    "file_back": true
  }'
```

### Manual file-back

File an entire conversation back to the wiki:

```bash
curl -X POST http://localhost:7842/query/conversations/{conversation_id}/file-back
```

Or file selected turns from one or more conversations:

```bash
curl -X POST http://localhost:7842/query/conversations/file-back \
  -H "Content-Type: application/json" \
  -d '{
    "selections": [
      {"conversation_id": "...", "turn_indices": [0, 1, 2]}
    ]
  }'
```

## Conversations

### List conversations

```bash
curl http://localhost:7842/query/conversations
```

Returns conversations ordered by most recently updated first.

### Get conversation detail

```bash
curl http://localhost:7842/query/conversations/{conversation_id}
```

Returns the conversation with all its turns (questions and answers).

### Export as markdown

```bash
curl http://localhost:7842/query/conversations/{conversation_id}/export
```

Returns a standalone markdown document of the conversation.

### Fork a conversation

Branch a conversation at a specific turn to explore a different line of reasoning:

```bash
curl -X POST http://localhost:7842/query/conversations/{conversation_id}/fork \
  -H "Content-Type: application/json" \
  -d '{
    "turn_index": 2,
    "question": "What if we approached it differently?"
  }'
```

This creates a new conversation that shares turns 0 through `turn_index - 1` with the parent. The original branch is preserved immutably.

## How Context Retrieval Works

When you ask a question, the Q&A agent:

1. Extracts key terms from your question
2. Scores all wiki articles by term overlap
3. Selects the top 5 most relevant articles
4. Truncates each to 3,000 characters to fit the context window
5. Includes prior conversation turns (up to 5) for multi-turn context
6. Sends everything to the LLM with a structured prompt

The LLM responds with JSON containing the answer, confidence level, cited sources, related articles, and follow-up questions.

!!! note "Semantic search coming soon"
    The current retrieval uses simple term overlap. Semantic search via ChromaDB embeddings is planned, which will significantly improve answer quality for conceptual questions.
