import uuid
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from app.services.rasa_service import rasa_service
from app.services.rag_service import rag_service
from app.services.llm_service import llm_service
from app.services.log_service import log_interaction
from app.services.memory_service import memory_service
from app.services.preprocessing_service import preprocessing_service
from app.database.connection import get_db

router = APIRouter()

#  Confidence thresholds
RASA_HIGH_CONFIDENCE = 0.80   # above this → Rasa handles directly
RASA_MEDIUM_CONFIDENCE = 0.40  # above this → use Rasa intent as hint + LLM

# Intents that Rasa can answer by itself (have static utter_ responses)
RASA_DIRECT_INTENTS = {
    "greet", "goodbye", "affirm", "deny", "bot_challenge",
    "thank_you", "ask_capabilities", "out_of_scope",
}

# Static responses matching domain.yml — used when Rasa handles directly
RASA_STATIC_RESPONSES = {
    "greet": "Hello! I'm your assistant. How can I help you today?",
    "goodbye": "Goodbye! Have a great day.",
    "bot_challenge": (
        "I'm a bot built with Rasa NLU. I use a DIET classifier to "
        "understand your messages and a custom action layer to answer "
        "questions from a knowledge base."
    ),
    "thank_you": "You're welcome! Anything else I can help with?",
    "ask_capabilities": (
        "I can answer questions on many topics — general knowledge, places, "
        "India, technology, and more. I also handle FAQs and can look things "
        "up from my knowledge base. Try asking me anything!"
    ),
    "out_of_scope": (
        "That's outside what I can help with right now, but feel free "
        "to ask me something else."
    ),
    "affirm": "Great!",
    "deny": "No problem. Let me know if you need anything else.",
}


#  Request / Response models 
class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None  # for conversation memory

class ChatResponse(BaseModel):
    query: str
    intent: Optional[str] = None
    confidence: float = 0.0
    entities: List[Dict[str, Any]] = []
    context: List[str] = []
    rag_relevant: bool = False
    route: str = "llm"                # "rasa" or "llm"
    final_answer: str
    session_id: str


# ── Main chat endpoint 
@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, db: Session = Depends(get_db)):
    """
    Smart chat endpoint with confidence-based routing:

    1. Preprocess the query
    2. Send to Rasa for intent + entities
    3. HIGH confidence + known intent  → Rasa answers directly (fast)
    4. Otherwise                       → RAG retrieval + LLM generation
       - If RAG chunks are relevant   → LLM uses them as context
       - If RAG chunks are weak       → LLM answers from own knowledge
    5. Log everything to MySQL
    6. Store conversation turn in memory
    """
    raw_query = request.query.strip()
    if not raw_query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    session_id = request.session_id or str(uuid.uuid4())

    #  Step 1: Preprocess 
    cleaned_query = preprocessing_service.clean(raw_query)
    normalized_query = preprocessing_service.normalize(raw_query)

    # Step 2: Rasa NLU 
    nlu_result = await rasa_service.get_intent_and_entities(cleaned_query)
    intent = nlu_result.get("intent")
    confidence = nlu_result.get("confidence", 0.0)
    entities = nlu_result.get("entities", [])

    #  Step 3: Route decision 
    route = "llm"
    final_answer = ""
    context_strings = []
    rag_relevant = False

    if (
        confidence >= RASA_HIGH_CONFIDENCE
        and intent in RASA_DIRECT_INTENTS
    ):
        # --- RASA DIRECT PATH ---
        route = "rasa"
        final_answer = RASA_STATIC_RESPONSES.get(
            intent, "I'm not sure how to respond to that."
        )
    else:
        # --- LLM PATH (with optional RAG context) ---

        # Retrieve conversation history
        conversation_history = memory_service.get_history_as_text(session_id)

        # RAG retrieval with relevance scoring
        rag_result = rag_service.retrieve_relevant_context(
            normalized_query, top_k=3
        )
        context_strings = rag_result["context_strings"]
        rag_relevant = rag_result["is_relevant"]

        # Generate LLM response
        final_answer = llm_service.generate_response(
            query=raw_query,
            intent=intent,
            confidence=confidence,
            entities=entities,
            context_strings=context_strings,
            rag_is_relevant=rag_relevant,
            conversation_history=conversation_history,
        )

    #  Step 4: Memory 
    memory_service.add_turn(session_id, "user", raw_query)
    memory_service.add_turn(session_id, "assistant", final_answer)

    #  Step 5: Log to DB 
    log_interaction(
        db=db,
        query=raw_query,
        intent=intent or "Unknown",
        confidence=confidence,
        entities=entities,
        response=final_answer,
        route=route,
        session_id=session_id,
    )

    return ChatResponse(
        query=raw_query,
        intent=intent,
        confidence=confidence,
        entities=entities,
        context=context_strings if route == "llm" else [],
        rag_relevant=rag_relevant,
        route=route,
        final_answer=final_answer,
        session_id=session_id,
    )


#  Item 7: Streaming chat endpoint 
class StreamChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None

@router.post("/chat/stream")
async def chat_stream_endpoint(request: StreamChatRequest):
    """
    Streaming version of the chat endpoint.
    Returns an SSE stream of tokens as the LLM generates them.

    NOTE: Streaming skips Rasa routing — always goes through RAG + LLM.
    Use the regular /chat endpoint for fast Rasa-handled intents.
    """
    raw_query = request.query.strip()
    if not raw_query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    session_id = request.session_id or str(uuid.uuid4())
    normalized_query = preprocessing_service.normalize(raw_query)

    # Conversation history
    conversation_history = memory_service.get_history_as_text(session_id)

    # RAG retrieval
    rag_result = rag_service.retrieve_relevant_context(normalized_query, top_k=3)

    # Store user turn now (assistant turn stored after streaming is harder,
    # but we add a placeholder — the client gets the full text anyway)
    memory_service.add_turn(session_id, "user", raw_query)

    async def event_generator():
        full_response = []
        async for token in llm_service.generate_response_stream(
            query=raw_query,
            context_strings=rag_result["context_strings"],
            rag_is_relevant=rag_result["is_relevant"],
            conversation_history=conversation_history,
        ):
            full_response.append(token)
            # SSE format
            yield f"data: {token}\n\n"

        # Store the complete response in memory
        complete = "".join(full_response)
        memory_service.add_turn(session_id, "assistant", complete)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-Id": session_id,
        },
    )