from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re
from typing import Any

from dotenv import load_dotenv
from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.agents.context import Context
from google.genai import types as genai_types
from my_agent.tools.study_tools import build_quiz_correction_text

load_dotenv(Path(__file__).resolve().parent / ".env")
os.environ.setdefault("ADK_MODEL_PROVIDER", "ollama")
# Modele local demande: Mistral via Ollama.
os.environ.setdefault("ADK_MODEL_NAME", "ollama/mistral")
# Nom de modele centralise pour tous les agents LLM ci-dessous.
MODEL_NAME = os.getenv("ADK_MODEL_NAME", "ollama/mistral")
UNIVERSAL_FALLBACK = "Je ne comprends pas votre demande. Pouvez-vous la reiterer ?"
WELCOME_MESSAGE = (
    "👋 Bienvenue !\n\n"
    "Je peux t'aider à :\n\n"
    "• 🧠 Créer un quiz (3 questions)\n\n"
    "\tExemple : 'Fais un quiz sur le football'\n\n"
    "• 📚 Créer une fiche de révision\n\n"
    "\tExemple : 'Créer une fiche sur Intel'"
)


# Callback "before": garde-fou anti-boucle/infinite loop.
# Si trop d'iterations dans la meme invocation, on coupe proprement.
def loop_guard_before_agent(
    context: Context | None = None,
    callback_context: Context | None = None,
    **_: Any,
):
    ctx = callback_context or context
    if ctx is None:
        return None

    # ID d'invocation courant
    invocation_id = getattr(ctx, "invocation_id", None) or "unknown"
    # Si nouvelle invocation, reset du compteur.
    if ctx.state.get("_guard_invocation_id") != invocation_id:
        ctx.state["_guard_invocation_id"] = invocation_id
        ctx.state["_guard_step_count"] = 0

    # Compteur de "pas" total de la chaine d'agents.
    step_count = int(ctx.state.get("_guard_step_count", 0)) + 1
    ctx.state["_guard_step_count"] = step_count

    # Garde-fou uniquement en dernier recours
    if step_count > 120:
        return genai_types.Content(
            role="assistant",
            parts=[
                genai_types.Part(
                    text=UNIVERSAL_FALLBACK
                )
            ],
        )
    return None


def _read_user_text(ctx: Context) -> str:
    user_text = ""
    user_content = getattr(ctx, "user_content", None)
    if user_content and getattr(user_content, "parts", None):
        for part in user_content.parts:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str) and part_text.strip():
                user_text += (" " + part_text.strip())
    return user_text.strip()


def _looks_like_quiz_answers(user_text: str) -> bool:
    txt = (user_text or "").strip().upper()
    if not txt:
        return False

    # Acceptes les combinaisons de reponses 
    letters = re.findall(r"[ABC]", txt)
    if len(letters) == 3:
        leftover = re.sub(r"[ABC\s,;|/\-._:]+", "", txt)
        if leftover == "":
            return True

    if "Q1" in txt and "Q2" in txt and "Q3" in txt:
        return True
    return False


def _classify_user_intent(user_text: str) -> str:
    txt = (user_text or "").lower()
    if not txt:
        return "unknown"

    quiz_keywords = {
        "quiz","quizz","question","questions",
    }
    fiche_keywords = {
        "fiche","resume","résumé","explication","explications","expliquer","cours",
    }

    if any(k in txt for k in quiz_keywords):
        return "quiz"
    if any(k in txt for k in fiche_keywords):
        return "fiche"
    return "unknown"


def _infer_topic_from_user_text(user_text: str) -> str:
    txt = (user_text or "").strip()
    if not txt:
        return ""
    
    lowered = txt.lower()
    for token in [
        "fais","fais moi","fais-moi",
        "donne moi","donne-moi","donne",
        "creer","créer","cree","crée",
        "quiz","fiche",
        "sur","de",":",
    ]:
        lowered = lowered.replace(token, " ")

    cleaned = " ".join(lowered.split()).strip(" -_|")
    if not cleaned:
        return ""

    return cleaned[:1].upper() + cleaned[1:]


def reset_state_on_new_request_before_agent(
    context: Context | None = None,
    callback_context: Context | None = None,
    **_: Any,
):
    ctx = callback_context or context
    if ctx is None:
        return None

    user_text = _read_user_text(ctx)
    intent = _classify_user_intent(user_text)
    asks_quiz_or_sheet = intent in {"quiz", "fiche"}

    # New task request: clear prior derived state so previous topic is not reused.
    if asks_quiz_or_sheet and not _looks_like_quiz_answers(user_text):
        for key in ("study_context", "quiz_content", "quiz_correction", "study_sheet"):
            # ADK State n'expose pas pop/del: on ecrase la valeur pour eviter l'etat "colle".
            ctx.state[key] = ""
        topic = _infer_topic_from_user_text(user_text)
        if topic:
            # Keep a deterministic, current-turn topic in state.
            ctx.state["study_context"] = f'{{"topic":"{topic}"}}'

    return None


def root_before_agent(
    context: Context | None = None,
    callback_context: Context | None = None,
    **kwargs: Any,
):
    ctx = callback_context or context
    if ctx is not None:
        user_text = _read_user_text(ctx)
        intent = _classify_user_intent(user_text)
        ctx.state["forced_intent"] = intent
        if str(ctx.state.get("welcome_shown", "")) != "1" and intent == "unknown":
            ctx.state["welcome_shown"] = "1"
            return genai_types.Content(
                role="assistant",
                parts=[genai_types.Part(text=WELCOME_MESSAGE)],
            )
        if _looks_like_quiz_answers(user_text):
            quiz_text = str(ctx.state.get("quiz_content", "") or "")
            correction = build_quiz_correction_text(
                user_answers=user_text, quiz_text=quiz_text
            )
            ctx.state["quiz_correction"] = correction
            return genai_types.Content(
                role="assistant",
                parts=[genai_types.Part(text=correction)],
            )
        # Universal fallback
        if intent == "unknown":
            return genai_types.Content(
                role="assistant",
                parts=[genai_types.Part(text=UNIVERSAL_FALLBACK)],
            )

    reset_state_on_new_request_before_agent(
        context=context, callback_context=callback_context, **kwargs
    )
    return loop_guard_before_agent(
        context=context, callback_context=callback_context, **kwargs
    )


# Agents "fiche": produisent une fiche de revision lisible.
# On impose des sections fixes pour garder un format stable.
fiche_only = LlmAgent(
    name="fiche_only",
    model=MODEL_NAME,
    instruction=(
        "Utilise {study_context}. Redige une fiche claire en francais avec EXACTEMENT ces sections:\n"
        "1) Infos cles\n2) Definitions importantes\n3) Anecdotes utiles\n"
        "4) Chiffres/Dates reperes\n5) Pieges frequents\n6) Resume en 5 lignes\n"
        "Pas de JSON."
    ),
    output_key="study_sheet",
    before_agent_callback=loop_guard_before_agent,
)

# Agents "quiz": produisent exactement 3 questions (Q1/Q2/Q3).
# quiz_only = questions uniquement; la correction se fait apres reponses utilisateur.
quiz_only = LlmAgent(
    name="quiz_only_writer",
    model=MODEL_NAME,
    instruction=(
        "Tu dois repondre uniquement en francais. "
        "Utilise {study_context}. Cree un quiz de 3 questions (Q1,Q2,Q3) avec choix A/B/C. "
        "Ne donne pas les corrections maintenant. "
        "Finis par: 'Envoie-moi tes reponses"
        "Ajoute a la fin un commentaire HTML cache EXACT au format: "
        "<!--ANSWERS:Q1=A;Q2=B;Q3=C--> "
        "(remplace A/B/C par les bonnes lettres). "
        "Pas de JSON."
    ),
    output_key="quiz_content",
    before_agent_callback=loop_guard_before_agent,
)

# Workflow Loop minimal pour le quiz (1 iteration) expose directement au routeur.
quiz_only = LoopAgent(
    name="quiz_only",
    description="Boucle quiz (1 iteration) pour conformite workflow.",
    sub_agents=[quiz_only],
    max_iterations=1,
)

# Workflows:
# - fiche_workflow: fiche uniquement
# - quiz_workflow: quiz uniquement
fiche_workflow = SequentialAgent(
    name="fiche_workflow",
    description="Generate fiche only from the current state topic.",
    sub_agents=[fiche_only],
)

# Root router:
# C'est l'unique point d'entree qui decide vers quel workflow transferer.
# Il gere aussi le cas "l'utilisateur envoie A/B/C" -> correction quiz.
root_agent = LlmAgent(
    name="revision_coach_root",
    model=MODEL_NAME,
    instruction=(
        "Tu es un coach de revision en francais. "
        "Tu dois repondre uniquement en francais. "
        "Si la demande est incomprehensible, reponds exactement: "
        "'Je ne comprends pas votre demande. Pouvez-vous la reiterer ?'. "
        "Intent detecte par regles: {forced_intent}. "
        "Routage strict:\n"
        "- si forced_intent=quiz -> transfer_to_agent quiz_only\n"
        "- si forced_intent=fiche -> transfer_to_agent fiche_workflow\n"
        "- ne jamais produire quiz+fiche dans la meme reponse\n"
        "- si l'utilisateur envoie des reponses quiz (Q1/Q2/Q3 ou A/B/C), la correction est geree par callback Python\n"
        "Ne jamais afficher de JSON ou Tool Calls."
    ),
    sub_agents=[fiche_workflow, quiz_only],
    before_agent_callback=root_before_agent,
)
