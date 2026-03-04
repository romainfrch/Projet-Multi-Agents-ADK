import asyncio
import json
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from my_agent.model import MODEL
from my_agent.tools.revision_tools import check_answer, generate_summary, track_progress
from my_agent.callbacks import before_model_callback
from google.adk.agents import LlmAgent

APP_NAME = "revision_app"
USER_ID = "student_1"
SESSION_ID = "session_1"

state = {
    "score": 0,
    "total_questions": 0,
    "last_topic": "",
    "quiz_batch": [],     # [{"question": ..., "choices": {...}, "correct": ...}, ...]
    "quiz_index": 0,
    "quiz_active": False,
    "batch_score": 0,
}

# Agent LLM utilisé pour générer les vraies questions et fiches
llm_agent = LlmAgent(
    name="quiz_generator",
    model=MODEL,
    description="Génère des questions de quiz et des fiches de révision.",
    instruction="""Tu es un assistant pédagogique expert. 
Réponds UNIQUEMENT en JSON valide, sans texte avant ni après, sans balises markdown.
""",
    before_model_callback=before_model_callback,
)


async def ask_llm_raw(session_service, prompt: str) -> str:
    """Appelle le LLM et retourne le texte brut."""
    runner = Runner(agent=llm_agent, app_name=APP_NAME, session_service=session_service)
    msg = Content(role="user", parts=[Part(text=prompt)])
    final = None
    async for event in runner.run_async(user_id=USER_ID, session_id=SESSION_ID, new_message=msg):
        if event.is_final_response() and event.content and event.content.parts:
            final = event.content.parts[0].text
    return final or ""


async def generate_quiz_batch(session_service, topic: str) -> list:
    """Demande au LLM de générer 3 vraies questions QCM sur le sujet."""
    prompt = f"""Génère 3 questions QCM différentes sur le sujet : "{topic}"

Réponds UNIQUEMENT avec ce JSON (rien d'autre, pas de markdown) :
[
  {{
    "question": "Question 1 ?",
    "choices": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
    "correct": "A",
    "explication": "Pourquoi cette réponse est correcte."
  }},
  {{
    "question": "Question 2 ?",
    "choices": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
    "correct": "B",
    "explication": "..."
  }},
  {{
    "question": "Question 3 ?",
    "choices": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
    "correct": "C",
    "explication": "..."
  }}
]

Les questions doivent être variées : définition, exemple, comparaison.
Chaque bonne réponse doit être différente (pas toujours la même lettre)."""

    raw = await ask_llm_raw(session_service, prompt)

    # Nettoie et parse le JSON
    raw = raw.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        batch = json.loads(raw)
        if isinstance(batch, list) and len(batch) >= 3:
            return batch[:3]
    except Exception:
        pass

    # Fallback si le JSON est invalide
    print("   (Le modèle n'a pas pu générer du JSON propre, questions de secours utilisées)")
    return [
        {"question": f"Qu'est-ce que '{topic}' ?", "choices": {"A": f"Définition de {topic}", "B": "Autre chose", "C": "Rien", "D": "Inconnu"}, "correct": "A", "explication": f"{topic} est défini par A."},
        {"question": f"Quel est l'usage principal de '{topic}' ?", "choices": {"A": "Aucun", "B": f"Utiliser {topic} correctement", "C": "Ignorer {topic}", "D": "Autre"}, "correct": "B", "explication": "L'usage principal est B."},
        {"question": f"Quelle propriété est associée à '{topic}' ?", "choices": {"A": "Rien", "B": "Autre", "C": f"La propriété centrale de {topic}", "D": "Inconnu"}, "correct": "C", "explication": "La propriété centrale est C."},
    ]


async def generate_summary_llm(session_service, topic: str) -> str:
    """Demande au LLM de générer une vraie fiche de révision."""
    # On appelle l'outil pour logger l'action dans ADK
    generate_summary(topic)

    prompt = f"""Génère une fiche de révision sur : "{topic}"

Réponds UNIQUEMENT avec ce JSON :
{{
  "titre": "{topic}",
  "definition": "Définition claire en 2 phrases.",
  "points_cles": ["point 1", "point 2", "point 3"],
  "exemple": "Un exemple concret.",
  "a_retenir": "La chose la plus importante à retenir."
}}"""

    raw = await ask_llm_raw(session_service, prompt)
    raw = raw.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        data = json.loads(raw)
        # Accepte aussi un tableau JSON [{ ... }]
        if isinstance(data, list):
            data = data[0]
        result = f"\n📖 Fiche : {data.get('titre', topic).upper()}\n"
        result += f"   Définition : {data.get('definition', '')}\n"
        result += f"   Points clés :\n"
        for pt in data.get('points_cles', []):
            result += f"     • {pt}\n"
        result += f"   Exemple : {data.get('exemple', '')}\n"
        result += f"   ✅ À retenir : {data.get('a_retenir', '')}\n"
        return result
    except Exception:
        return f"\n📖 Fiche sur '{topic}' générée. (Reformatage échoué — réponse brute :)\n{raw}\n"


def route(text: str) -> str:
    t = text.lower().strip()
    if t in {"a", "b", "c", "d"}:
        return "answer"
    if any(w in t for w in ["score", "bilan", "progression", "résultat"]):
        return "score"
    if any(w in t for w in ["fiche", "résumé", "resume", "explique", "synthèse"]):
        return "summary"
    if any(w in t for w in ["quiz", "question", "interroge", "teste", "qcm"]):
        return "quiz"
    return "unknown"


def extract_topic(text: str, keywords: list) -> str:
    """Extrait le sujet en supprimant les mots-clés de commande en début de phrase."""
    t = text.strip()
    # Supprime uniquement les mots-clés en début, pas partout (évite de couper les mots)
    words_to_remove = keywords + ["sur", "stp", "svp", "moi"]
    parts = t.split()
    filtered = [w for w in parts if w.lower() not in words_to_remove]
    result = " ".join(filtered).strip()
    return result or t


def display_question():
    idx = state["quiz_index"]
    total = len(state["quiz_batch"])
    q = state["quiz_batch"][idx]
    print(f"\nAgent > ❓ Question {idx + 1}/{total} — sujet : '{state['last_topic']}'")
    print(f"         {q['question']}")
    print(f"         A) {q['choices']['A']}")
    print(f"         B) {q['choices']['B']}")
    print(f"         C) {q['choices']['C']}")
    print(f"         D) {q['choices']['D']}")
    print(f"         → Réponds par A, B, C ou D\n")


async def main():
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID
    )

    print("=" * 60)
    print("🎓  Assistant de Révision Multi-Agents (ADK)")
    print("=" * 60)
    print("  • 'quiz <sujet>'   → lot de 3 questions QCM")
    print("  • 'fiche <sujet>'  → fiche de révision")
    print("  • 'A/B/C/D'        → répondre à une question")
    print("  • 'score'          → ta progression")
    print("  • 'exit'           → quitter")
    print("=" * 60)
    print()

    GREETINGS = {"slt", "salut", "bonjour", "hello", "hi", "hey", "cc", "coucou"}

    while True:
        try:
            text = input("Vous > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Au revoir !")
            break

        if not text:
            continue
        if text.lower() in {"exit", "quit", "q"}:
            print("👋 Bonne révision !")
            break
        if text.lower() in GREETINGS:
            print("\nAgent > Bonjour ! Dis-moi 'quiz <sujet>' ou 'fiche <sujet>' pour commencer 🎓\n")
            continue

        intent = route(text)

        # Si un quiz est en cours, bloquer tout sauf les réponses A/B/C/D
        if state["quiz_active"] and intent != "answer":
            idx = state["quiz_index"]
            total = len(state["quiz_batch"])
            if text.lower() == "stop":
                state["quiz_active"] = False
                print("\nAgent > Quiz abandonné. Tu peux relancer avec \'quiz <sujet>\'!\n")
            else:
                print(f"\nAgent > ⚠️  Quiz en cours ! Question {idx + 1}/{total}.")
                print(f"         Réponds par A, B, C ou D — ou tape \'stop\' pour abandonner.\n")
            continue

        try:
            if intent == "quiz":
                topic = extract_topic(text, ["quiz", "question", "interroge", "teste", "qcm"])
                print(f"\nAgent > 🎯 Je génère 3 questions sur '{topic}' (quelques secondes)...\n")
                batch = await generate_quiz_batch(session_service, topic)
                state["quiz_batch"] = batch
                state["quiz_index"] = 0
                state["quiz_active"] = True
                state["last_topic"] = topic
                state["batch_score"] = 0
                display_question()

            elif intent == "answer":
                if not state["quiz_active"]:
                    print("\nAgent > Aucun quiz en cours. Tape 'quiz <sujet>' d'abord !\n")
                    continue

                answer = text.strip().upper()
                idx = state["quiz_index"]
                q = state["quiz_batch"][idx]
                result = check_answer(q["question"], answer, q["correct"])

                state["total_questions"] += 1
                if result["is_correct"]:
                    state["score"] += 1
                    state["batch_score"] += 1

                print(f"\nAgent > {result['feedback']}")
                if not result["is_correct"] and "explication" in q:
                    print(f"         💡 {q['explication']}")

                next_idx = idx + 1
                if next_idx < len(state["quiz_batch"]):
                    state["quiz_index"] = next_idx
                    display_question()
                else:
                    state["quiz_active"] = False
                    pct = round(state["batch_score"] / 3 * 100)
                    emoji = "🌟" if pct >= 80 else "👍" if pct >= 50 else "📚"
                    print(f"\nAgent > {emoji} Fin du lot ! Score : {state['batch_score']}/3 ({pct}%)")
                    print(f"         Tape 'quiz {state['last_topic']}' pour un nouveau lot !\n")

            elif intent == "summary":
                topic = extract_topic(text, ["fiche", "résumé", "resume", "explique", "synthèse"])
                print(f"\nAgent > ✍️  Je génère la fiche sur '{topic}' (quelques secondes)...\n")
                fiche = await generate_summary_llm(session_service, topic)
                print(f"Agent > {fiche}")

            elif intent == "score":
                result = track_progress("student_1", state["last_topic"], state["score"], max(state["total_questions"], 1))
                print(f"\nAgent > 📊 Bilan :")
                print(f"         Score total : {state['score']}/{state['total_questions']} ({result.get('percentage', 0)}%)")
                print(f"         {result.get('message', '')}")
                if state["last_topic"]:
                    print(f"         Dernier sujet : {state['last_topic']}")
                print()

            else:
                print("\nAgent > Je suis un assistant de révision. Essaie 'quiz <sujet>' ou 'fiche <sujet>' !\n")

        except Exception as e:
            print(f"❌ Erreur : {e}\n")


if __name__ == "__main__":
    asyncio.run(main())