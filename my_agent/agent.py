"""Minimal stable ADK app: quiz + fiche + readable correction."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.agents.context import Context
from google.adk.tools import AgentTool
from google.genai import types as genai_types
from my_agent.tools.study_tools import build_quiz_correction_text

load_dotenv(Path(__file__).resolve().parent / ".env")
# Provider local: on force Ollama pour eviter Gemini/API key.
os.environ.setdefault("ADK_MODEL_PROVIDER", "ollama")
# Modele local demande: Mistral via Ollama.
os.environ.setdefault("ADK_MODEL_NAME", "ollama/mistral")
# Nom de modele centralise pour tous les agents LLM ci-dessous.
MODEL_NAME = os.getenv("ADK_MODEL_NAME", "ollama/mistral")


# Callback "after": memorise quel agent a parle en dernier + timestamp.
# Utile pour debug et traces ADK dans la session.
def after_agent_stamp(
    context: Context | None = None,
    callback_context: Context | None = None,
    **_: Any,
):
    # ADK peut passer context OU callback_context selon le hook/version.
    ctx = callback_context or context
    if ctx is None:
        return None
    # On stocke l'agent courant dans l'etat de session.
    ctx.state["last_agent"] = ctx.agent_name
    # Timestamp UTC standard pour suivre l'ordre des evenements.
    ctx.state["last_agent_at"] = datetime.utcnow().isoformat()
    return None


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

    # ID d'invocation courant (une execution utilisateur).
    invocation_id = getattr(ctx, "invocation_id", None) or "unknown"
    # Si nouvelle invocation, reset du compteur.
    if ctx.state.get("_guard_invocation_id") != invocation_id:
        ctx.state["_guard_invocation_id"] = invocation_id
        ctx.state["_guard_step_count"] = 0

    # Compteur de "pas" total de la chaine d'agents.
    step_count = int(ctx.state.get("_guard_step_count", 0)) + 1
    ctx.state["_guard_step_count"] = step_count

    # Garde-fou uniquement en dernier recours (seuil tres eleve).
    if step_count > 120:
        return genai_types.Content(
            role="assistant",
            parts=[
                genai_types.Part(
                    text="Je ne comprends pas votre demande. Pouvez-vous la reiterer ?"
                )
            ],
        )
    return None


def _read_user_text(ctx: Context) -> str:
    """Extract plain user text from ADK user_content."""
    user_text = ""
    user_content = getattr(ctx, "user_content", None)
    if user_content and getattr(user_content, "parts", None):
        for part in user_content.parts:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str) and part_text.strip():
                user_text += (" " + part_text.strip())
    return user_text.strip()


def _looks_like_quiz_answers(user_text: str) -> bool:
    """Detect answer-only turns (must keep previous quiz in memory)."""
    txt = (user_text or "").strip().upper()
    if not txt:
        return False
    if txt in {"ABC", "A B C", "A,B,C", "A|B|C", "A / B / C"}:
        return True
    if "Q1" in txt and "Q2" in txt and "Q3" in txt:
        return True
    return False


def _infer_topic_from_user_text(user_text: str) -> str:
    """Extract topic from the current user turn only (no history)."""
    txt = (user_text or "").strip()
    if not txt:
        return ""

    # Remove common command words to keep only the subject.
    lowered = txt.lower()
    for token in [
        "fais moi",
        "fais-moi",
        "donne moi",
        "donne-moi",
        "creer",
        "créer",
        "cree",
        "crée",
        "quiz",
        "fiche",
        "sur",
        "de",
        ":",
    ]:
        lowered = lowered.replace(token, " ")

    cleaned = " ".join(lowered.split()).strip(" -_|")
    if not cleaned:
        return ""

    # Re-capitalize lightly for display in generated content.
    return cleaned[:1].upper() + cleaned[1:]


def reset_state_on_new_request_before_agent(
    context: Context | None = None,
    callback_context: Context | None = None,
    **_: Any,
):
    """Reset sticky topic/quiz state when user starts a new request."""
    ctx = callback_context or context
    if ctx is None:
        return None

    user_text = _read_user_text(ctx)
    lowered = user_text.lower()
    asks_quiz_or_sheet = any(k in lowered for k in ["quiz", "fiche", "sheet"])

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
    """Root callback: reset stale state + keep loop guard."""
    ctx = callback_context or context
    if ctx is not None:
        user_text = _read_user_text(ctx)
        # Deterministic shortcut: if user sends answers, correct immediately.
        # This avoids accidental rerouting to quiz generation and wrong scoring.
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

    reset_state_on_new_request_before_agent(
        context=context, callback_context=callback_context, **kwargs
    )
    return loop_guard_before_agent(
        context=context, callback_context=callback_context, **kwargs
    )


def deterministic_quiz_correction_before_agent(
    context: Context | None = None,
    callback_context: Context | None = None,
    **_: Any,
):
    """Compute quiz correction in pure Python to avoid LLM drift/hallucinations."""
    ctx = callback_context or context
    if ctx is None:
        return None

    user_text = _read_user_text(ctx)

    quiz_text = str(ctx.state.get("quiz_content", "") or "")
    correction = build_quiz_correction_text(user_answers=user_text, quiz_text=quiz_text)
    ctx.state["quiz_correction"] = correction
    return genai_types.Content(
        role="assistant",
        parts=[genai_types.Part(text=correction)],
    )


# Parser agents: extraient un topic propre depuis la demande utilisateur.
# Important ADK: un meme objet agent ne peut pas avoir plusieurs parents.
# Donc on duplique parser_both/parser_fiche/parser_quiz.
parser_both = LlmAgent(
    name="parser_both",
    model=MODEL_NAME,
    instruction=(
        "Extrait un sujet precis de la demande utilisateur. "
        "Retourne uniquement un JSON valide avec la cle 'topic'. "
        "Si la demande est 'quiz pogba', topic='Pogba' (pas 'quiz')."
    ),
    output_key="study_context",
    before_agent_callback=loop_guard_before_agent,
    after_agent_callback=after_agent_stamp,
)

parser_fiche = LlmAgent(
    name="parser_fiche",
    model=MODEL_NAME,
    instruction=(
        "Extrait un sujet precis de la demande utilisateur. "
        "Retourne uniquement un JSON valide avec la cle 'topic'."
    ),
    output_key="study_context",
    before_agent_callback=loop_guard_before_agent,
    after_agent_callback=after_agent_stamp,
)

parser_quiz = LlmAgent(
    name="parser_quiz",
    model=MODEL_NAME,
    instruction=(
        "Extrait un sujet precis de la demande utilisateur. "
        "Retourne uniquement un JSON valide avec la cle 'topic'."
    ),
    output_key="study_context",
    before_agent_callback=loop_guard_before_agent,
    after_agent_callback=after_agent_stamp,
)


# Agents "fiche": produisent une fiche de revision lisible.
# On impose des sections fixes pour garder un format stable.
fiche_both = LlmAgent(
    name="fiche_both",
    model=MODEL_NAME,
    instruction=(
        "Utilise {study_context}. Redige une fiche claire en francais avec EXACTEMENT ces sections:\n"
        "1) Infos cles\n2) Definitions importantes\n3) Anecdotes utiles\n"
        "4) Chiffres/Dates reperes\n5) Pieges frequents\n6) Resume en 5 lignes\n"
        "Pas de JSON."
    ),
    output_key="study_sheet",
    before_agent_callback=loop_guard_before_agent,
    after_agent_callback=after_agent_stamp,
)

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
    after_agent_callback=after_agent_stamp,
)


# Agents "quiz": produisent exactement 3 questions (Q1/Q2/Q3).
# quiz_only = questions uniquement; la correction se fait apres reponses utilisateur.
quiz_both = LlmAgent(
    name="quiz_both",
    model=MODEL_NAME,
    instruction=(
        "Tu dois repondre uniquement en francais. "
        "Utilise {study_context}. Cree un quiz de 3 questions (Q1,Q2,Q3) avec choix A/B/C. "
        "Ajoute ensuite une section Corrections. Pas de JSON."
    ),
    output_key="quiz_content",
    before_agent_callback=loop_guard_before_agent,
    after_agent_callback=after_agent_stamp,
)

quiz_only = LlmAgent(
    name="quiz_only",
    model=MODEL_NAME,
    instruction=(
        "Tu dois repondre uniquement en francais. "
        "Utilise {study_context}. Cree un quiz de 3 questions (Q1,Q2,Q3) avec choix A/B/C. "
        "Ne donne pas les corrections maintenant. "
        "Finis par: 'Envoie tes reponses au format: Q1: ... | Q2: ... | Q3: ...'. "
        "Ajoute a la fin un commentaire HTML cache EXACT au format: "
        "<!--ANSWERS:Q1=A;Q2=B;Q3=C--> "
        "(remplace A/B/C par les bonnes lettres). "
        "Pas de JSON."
    ),
    output_key="quiz_content",
    before_agent_callback=loop_guard_before_agent,
    after_agent_callback=after_agent_stamp,
)

# Agent de correction: transforme les reponses user en resultat lisible.
# Ici on interdit JSON/tool dump et on force un template texte stable.
quiz_correction_agent = LlmAgent(
    name="quiz_correction_agent",
    model=MODEL_NAME,
    instruction=(
        "Tu dois repondre uniquement en francais. "
        "Cet agent utilise une correction deterministe Python via callback. "
        "Ne rien ajouter."
    ),
    output_key="quiz_correction",
    before_agent_callback=deterministic_quiz_correction_before_agent,
    after_agent_callback=after_agent_stamp,
)


# Workflows:
# - both_workflow: parser puis fiche+quiz en parallele
# - fiche_workflow: parser puis fiche uniquement
# - quiz_workflow: parser puis quiz uniquement
parallel_both = ParallelAgent(
    name="parallel_both",
    description="Generate fiche and quiz in parallel.",
    sub_agents=[fiche_both, quiz_both],
)

both_workflow = SequentialAgent(
    name="both_workflow",
    description="Generate fiche+quiz from the current state topic.",
    sub_agents=[parallel_both],
)

fiche_workflow = SequentialAgent(
    name="fiche_workflow",
    description="Generate fiche only from the current state topic.",
    sub_agents=[fiche_only],
)

quiz_workflow = SequentialAgent(
    name="quiz_workflow",
    description="Generate quiz only from the current state topic.",
    sub_agents=[quiz_only],
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
        "Routage strict:\n"
        "- quiz seul -> transfer_to_agent quiz_workflow\n"
        "- fiche seule -> transfer_to_agent fiche_workflow\n"
        "- fiche+quiz ou ambigu -> transfer_to_agent both_workflow\n"
        "- si un quiz existe deja et l'utilisateur envoie des reponses (Q1/Q2/Q3 ou A/B/C) -> "
        "transfer_to_agent quiz_correction_agent\n"
        "Ne jamais afficher de JSON ou Tool Calls."
    ),
    sub_agents=[both_workflow, fiche_workflow, quiz_workflow, quiz_correction_agent],
    # Fallback: si le modele hallucine un appel tool au lieu d'un transfer propre.
    tools=[AgentTool(quiz_correction_agent)],
    before_agent_callback=root_before_agent,
    after_agent_callback=after_agent_stamp,
)
