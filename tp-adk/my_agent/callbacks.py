"""
Callbacks ADK pour le système de révision.
- before_model_callback  : journalise chaque appel LLM et peut bloquer les requêtes hors-sujet.
- after_tool_callback    : enrichit le state avec les résultats des outils.
"""

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from typing import Optional
import datetime


BLOCKED_KEYWORDS = ["jeu vidéo", "politique", "paris sportif", "crypto"]


# ─── Callback 1 : before_model_callback ───────────────────────────────────────
def before_model_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """Journalise l'appel LLM et bloque les sujets non scolaires."""

    agent_name = callback_context.agent_name
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")

    last_user_text = ""
    if llm_request.contents:
        for content in reversed(llm_request.contents):
            if content.role == "user" and content.parts:
                last_user_text = content.parts[0].text or ""
                break

    for keyword in BLOCKED_KEYWORDS:
        if keyword.lower() in last_user_text.lower():
            print(f"[{timestamp}] 🚫 Sujet bloqué : '{keyword}' détecté.")
            from google.genai.types import Content, Part
            return LlmResponse(
                content=Content(
                    role="model",
                    parts=[Part(text=(
                        f"❌ Je suis un assistant de révision scolaire. "
                        f"Le sujet '{keyword}' est hors de mon périmètre."
                    ))],
                )
            )

    return None


# ─── Callback 2 : after_tool_callback ─────────────────────────────────────────
def after_tool_callback(
    tool: BaseTool,
    args: dict,
    tool_context: ToolContext,
    tool_response: dict,
) -> Optional[dict]:
    """Enregistre le résultat de l'outil dans le state partagé."""

    tool_name = tool.name
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")

    # Sécurité : tool_response peut être None ou non-dict selon la version ADK
    if not isinstance(tool_response, dict):
        print(f"[{timestamp}] ⚠️  {tool_name} — réponse ignorée (type: {type(tool_response).__name__})")
        return None

    status = tool_response.get("status", "unknown")
    print(f"[{timestamp}] 🔧 Outil exécuté : {tool_name} — status: {status}")

    if tool_name == "generate_question" and status == "success":
        tool_context.state["last_question"] = tool_response.get("question", "")
        tool_context.state["last_correct_answer"] = tool_response.get("correct", "")
        tool_context.state["last_topic"] = tool_response.get("topic", "")
        print(f"[{timestamp}] 💾 State mis à jour : last_question, last_correct_answer, last_topic")

    elif tool_name == "check_answer" and status == "success":
        is_correct = tool_response.get("is_correct", False)
        tool_context.state["last_result"] = "correct" if is_correct else "incorrect"
        score = tool_context.state.get("score", 0)
        total = tool_context.state.get("total_questions", 0)
        if is_correct:
            tool_context.state["score"] = score + 1
        tool_context.state["total_questions"] = total + 1
        print(f"[{timestamp}] 💾 State mis à jour : score={tool_context.state['score']}/{tool_context.state['total_questions']}")

    elif tool_name == "generate_summary" and status == "success":
        tool_context.state["last_summary_topic"] = tool_response.get("topic", "")
        print(f"[{timestamp}] 💾 State mis à jour : last_summary_topic")

    elif tool_name == "track_progress" and status == "success":
        tool_context.state["last_percentage"] = tool_response.get("percentage", 0)
        print(f"[{timestamp}] 💾 State mis à jour : last_percentage")

    return None