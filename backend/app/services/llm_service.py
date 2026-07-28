"""
Gemini-powered LLM service.

Drop-in replacement for the old Ollama / Wikipedia+DDG service.
Same public interface — generate_response() and generate_response_stream() —
so chat.py needs zero changes.

How it works:
  1. Builds a system prompt with the chatbot's persona
  2. Injects RAG context (if relevant) + conversation history
  3. Sends the full prompt to Gemini for generation
  4. Returns natural language (blocking) or streams tokens (SSE)

Requires: GEMINI_API_KEY environment variable.
"""

import os
import asyncio
from typing import List, Optional, AsyncGenerator

import google.generativeai as genai
from dotenv import load_dotenv


# ── Configuration ────────────────────────────────────────────────────

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    print(f"[Gemini] Configured with model: {GEMINI_MODEL}")
else:
    print("[Gemini] WARNING: GEMINI_API_KEY not set — calls will fail!")


# ── System prompt ────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are TenantIQ, a helpful and intelligent AI helpdesk assistant.

Your behavior:
- Give clear, accurate, and concise answers.
- When knowledge-base context is provided, use it to answer. Cite it naturally.
- When no relevant context is provided, answer from your own knowledge.
- Be friendly, professional, and conversational.
- If you don't know something, say so honestly.
- Keep responses well-structured but not overly long.
"""


class LLMService:
    """
    Gemini-powered LLM service with RAG context injection
    and multi-turn conversation history support.
    """

    def __init__(self):
        self.model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT,
        )

    # ── Prompt builder ───────────────────────────────────────────────

    def _build_prompt(
        self,
        query: str,
        intent: Optional[str],
        confidence: float,
        entities: Optional[list],
        context_strings: Optional[List[str]],
        rag_is_relevant: bool,
        conversation_history: str,
    ) -> str:
        """
        Build the user-turn prompt that gets sent to Gemini.
        Includes RAG context + conversation history + the actual question.
        """
        parts: list[str] = []

        # ── Conversation history ──
        if conversation_history:
            parts.append("## Previous conversation")
            parts.append(conversation_history)
            parts.append("")

        # ── RAG context ──
        if rag_is_relevant and context_strings:
            parts.append("## Relevant knowledge base context")
            for i, ctx in enumerate(context_strings, 1):
                parts.append(f"{i}. {ctx.strip()[:800]}")
            parts.append("")
            parts.append(
                "Use the above context to answer the question. "
                "If the context is insufficient, supplement with your own knowledge."
            )
        else:
            parts.append(
                "No relevant knowledge base context was found. "
                "Answer the question using your own knowledge."
            )

        parts.append("")

        # ── Intent hint (optional, helps Gemini understand the domain) ──
        if intent and confidence > 0.3:
            parts.append(f"[Detected intent: {intent} ({confidence:.0%} confidence)]")

        # ── The actual question ──
        parts.append(f"## User question\n{query}")

        return "\n".join(parts)

    # ── Public: blocking response ────────────────────────────────────

    def generate_response(
        self,
        query: str,
        intent: Optional[str] = None,
        confidence: float = 0.0,
        entities: Optional[list] = None,
        context_strings: Optional[List[str]] = None,
        rag_is_relevant: bool = True,
        conversation_history: str = "",
    ) -> str:
        """
        Send the prompt to Gemini and return the full response text.
        Used by the /chat endpoint.
        """
        prompt = self._build_prompt(
            query=query,
            intent=intent,
            confidence=confidence,
            entities=entities,
            context_strings=context_strings,
            rag_is_relevant=rag_is_relevant,
            conversation_history=conversation_history,
        )

        try:
            response = self.model.generate_content(prompt)
            answer = response.text.strip()
            print(f"[Gemini] Response generated ({len(answer)} chars)")
            return answer

        except Exception as e:
            print(f"[Gemini] Error: {type(e).__name__}: {e}")
            return (
                "I'm sorry, I encountered an error while generating a response. "
                "Please try again in a moment."
            )

    # ── Public: streaming response ───────────────────────────────────

    async def generate_response_stream(
        self,
        query: str,
        context_strings: Optional[List[str]] = None,
        rag_is_relevant: bool = True,
        conversation_history: str = "",
    ) -> AsyncGenerator[str, None]:
        """
        Stream tokens from Gemini via its native streaming API.
        Used by the /chat/stream SSE endpoint.
        """
        prompt = self._build_prompt(
            query=query,
            intent=None,
            confidence=0.0,
            entities=None,
            context_strings=context_strings,
            rag_is_relevant=rag_is_relevant,
            conversation_history=conversation_history,
        )

        try:
            # Gemini's stream=True returns chunks as they're generated
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.model.generate_content(prompt, stream=True),
            )

            for chunk in response:
                if chunk.text:
                    yield chunk.text
                    await asyncio.sleep(0.01)  # small yield for SSE backpressure

        except Exception as e:
            print(f"[Gemini] Stream error: {type(e).__name__}: {e}")
            yield "I'm sorry, I encountered an error. Please try again."


# Singleton — same pattern as before
llm_service = LLMService()