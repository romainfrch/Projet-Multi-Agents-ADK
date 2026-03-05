import asyncio
import json
import random
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from my_agent.model import MODEL
from my_agent.tools.revision_tools import check_answer, generate_summary, track_progress
from my_agent.callbacks import before_model_callback
from google.adk.agents import LlmAgent

APP_NAME = "revision_app"
USER_ID = "student_1"

state = {
    "score": 0,
    "total_questions": 0,
    "last_topic": "",
    "quiz_batch": [],
    "quiz_index": 0,
    "quiz_active": False,
    "batch_score": 0,
}

# Historique des questions récentes pour éviter répétitions
_recent_questions: list = []

GREETINGS = {
    "slt", "salut", "bonjour", "bonsoir", "hello", "hi", "hey",
    "cc", "coucou", "yo", "wesh", "wsh", "ola", "hola",
    "ca va", "ça va", "tu vas bien", "comment tu vas", "quoi de neuf"
}

BLOCKED = {
    "scatophilie", "pornographie", "porno", "erotique",
    "pedophilie", "inceste", "cocaine", "heroine",
}

# 3 agents séparés avec instructions distinctes
quiz_agent = LlmAgent(
    name="quiz_generator",
    model=MODEL,
    instruction=(
        "Tu dois répondre UNIQUEMENT en FRANÇAIS.\n"
        "Tu dois répondre UNIQUEMENT en JSON valide.\n"
        "Aucun texte avant/après. Aucun markdown.\n"
        "N'utilise jamais d'anglais (même dans les noms de sections)."
    ),
    before_model_callback=before_model_callback,
)

fiche_agent = LlmAgent(
    name="fiche_generator",
    model=MODEL,
    instruction=(
        "Tu dois répondre UNIQUEMENT en FRANÇAIS.\n"
        "Tu dois répondre UNIQUEMENT en JSON valide.\n"
        "Aucun texte avant/après. Aucun markdown.\n"
        "Max 5 points clés. Ne te répète jamais.\n"
        "N'utilise jamais d'anglais."
    ),
    before_model_callback=before_model_callback,
)

intent_agent = LlmAgent(
    name="intent_analyzer",
    model=MODEL,
    instruction=(
        "Tu dois répondre UNIQUEMENT en FRANÇAIS.\n"
        "Tu dois répondre UNIQUEMENT en JSON valide.\n"
        "Aucun texte avant/après. Aucun markdown.\n"
        "Ne mets pas de mots anglais."
    ),
    before_model_callback=before_model_callback,
)


async def call_agent(agent, session_service, prompt: str) -> str:
    """Appelle un agent avec une session fraîche à chaque fois."""
    sid = f"s_{random.randint(1, 99999999)}"
    try:
        await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=sid)
    except Exception:
        pass
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)
    msg = Content(role="user", parts=[Part(text=prompt)])
    async for event in runner.run_async(user_id=USER_ID, session_id=sid, new_message=msg):
        if event.is_final_response() and event.content and event.content.parts:
            return (event.content.parts[0].text or "").strip()
    return ""


def extract_first_object(raw: str) -> dict | None:
    """Extrait le premier objet JSON { } valide du texte brut."""
    depth = 0
    start = None
    for i, c in enumerate(raw):
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(raw[start:i+1])
                except Exception:
                    pass
                start = None
    return None


def extract_all_objects(raw: str) -> list:
    """Extrait tous les objets JSON du texte, gère aussi les tableaux."""
    # Nettoyage markdown
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else parts[0]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    # Essai direct
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return [r for r in result if isinstance(r, dict)]
        if isinstance(result, dict):
            # Cherche une liste imbriquée (ex: {"qcm": [...]})
            for v in result.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    return v
            return [result]
    except Exception:
        pass

    # Extraction objet par objet
    objects = []
    depth = 0
    start = None
    for i, c in enumerate(raw):
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    obj = json.loads(raw[start:i+1])
                    if isinstance(obj, dict):
                        objects.append(obj)
                except Exception:
                    pass
                start = None
    return objects

import re

def is_gibberish_topic(topic: str) -> bool:
    """
    Heuristique:
    - trop court (<3)
    - pas de voyelle (souvent du charabia)
    - trop de consonnes d'affilée
    - répète beaucoup les mêmes lettres
    """
    if not topic:
        return True

    t = topic.strip().lower()

    # longueur
    if len(t) < 3:
        return True

    # si c'est juste des caractères non alphabétiques
    if not re.search(r"[a-zà-öø-ÿ]", t):
        return True

    # pas de voyelles = souvent charabia (ex: zqddz)
    if not re.search(r"[aeiouyàâäéèêëîïôöùûüÿ]", t):
        return True

    # 4 consonnes d'affilée (approx)
    if re.search(r"[bcdfghjklmnpqrstvwxz]{4,}", t):
        return True

    # répétition forte (ex: aaaaa, zzzzz)
    if re.search(r"(.)\1\1\1", t):
        return True

    return False

def extract_topic_from_command(text: str) -> str:
    """
    Extrait le sujet d'une commande du type:
    - quiz pogba
    - fiche mbappe
    """

    m = re.match(r"^(quiz|fiche)\s+(.+)$", text.strip(), re.IGNORECASE)

    if not m:
        return ""

    topic = m.group(2).strip()

    # nettoyage ponctuation
    topic = topic.strip(" \t\r\n-:;,.!?\"'")

    # protection contre sujet idiot
    if topic.lower() in {"quiz", "fiche", "question"}:
        return ""

    return topic

async def analyze_intent(session_service, text: str) -> dict:
    t = text.lower().strip()

    # Intent par mots-clés rapides
    if any(w in t for w in ["quiz", "question", "qcm", "teste", "interroge"]):
        intent_guess = "quiz"
    elif any(w in t for w in ["fiche", "resume", "explique", "revision", "resumer"]):
        intent_guess = "fiche"
    elif any(w in t for w in ["score", "bilan", "progression", "resultat"]):
        return {"intent": "score", "topic": ""}
    else:
        intent_guess = "unknown"

    # -----------------------------
    # 1️⃣ Parsing Python si commande claire
    # -----------------------------
    topic = extract_topic_from_command(text)

    if topic:
        return {"intent": intent_guess, "topic": topic}

    # -----------------------------
    # 2️⃣ Sinon on demande au LLM
    # -----------------------------
    prompt = f"""
Analyse ce message.

Retourne STRICTEMENT ce JSON :

{{
 "intent": "quiz ou fiche",
 "topic": "sujet principal"
}}

Message :
{text}
"""

    raw = await call_agent(intent_agent, session_service, prompt)

    obj = extract_first_object(raw)

    if obj:
        intent = obj.get("intent", intent_guess)
        topic = obj.get("topic", "").strip()

        # protection contre sujet débile
        if topic.lower() in {"quiz", "fiche", "question"}:
            topic = ""

        return {
            "intent": intent,
            "topic": topic,
        }

    return {"intent": "inconnu", "topic": ""}

async def generate_quiz(session_service, topic: str) -> list:
    global _recent_questions

    types = ["definition", "date ou chiffre", "comparaison", "exemple concret", "cause ou consequence", "caracteristique"]
    q_types = random.sample(types, 3)

    avoid = ""
    if _recent_questions:
        avoid = f"\nNE pose PAS ces questions: {'; '.join(_recent_questions[-6:])}\n"

    prompt = (
        f'Tu dois creer 3 QCM sur le SUJET EXACT: "{topic}".\n'
        "Règles STRICTES:\n"
        "- FRANÇAIS UNIQUEMENT.\n"
        "- Si le sujet est inconnu, ambigu, ou ressemble à du charabia, tu DOIS répondre EXACTEMENT: []\n"
        "- Interdiction d’inventer des liens avec des personnes (ex: Pogba) si ce n’est pas le sujet.\n"
        "- Interdiction d’inventer des faits.\n"
        "- Réponds UNIQUEMENT en JSON (pas de texte, pas de markdown).\n"
        "Format attendu (sinon []):\n"
        '[{"question":"...?","choices":{"A":"...","B":"...","C":"...","D":"..."},"correct":"A","explication":"..."},'
        '{"question":"...?","choices":{"A":"...","B":"...","C":"...","D":"..."},"correct":"B","explication":"..."},'
        '{"question":"...?","choices":{"A":"...","B":"...","C":"...","D":"..."},"correct":"C","explication":"..."}]'
    )

    raw = await call_agent(quiz_agent, session_service, prompt)
    objects = extract_all_objects(raw)

    fixed = []
    for q in objects:
        choices = q.get("choices", {})
        if isinstance(choices, list):
            choices_dict = {}
            for item in choices:
                if isinstance(item, dict):
                    for k, v in item.items():
                        if k in ("A", "B", "C", "D"):
                            choices_dict[k] = v
                        elif k in ("correct", "explication"):
                            q[k] = v
            q["choices"] = choices_dict
            choices = choices_dict
        for key in ("correct", "explication"):
            if key in choices:
                q[key] = choices.pop(key)
        if q.get("question") and len(q.get("choices", {})) == 4 and q.get("correct"):
            fixed.append(q)
        if len(fixed) == 3:
            break

    if fixed:
        _recent_questions.extend([q["question"] for q in fixed])
        _recent_questions = _recent_questions[-9:]

    return fixed


async def generate_fiche(session_service, topic: str) -> str:
    generate_summary(topic)
    prompt = (
        f'Fiche de revision sur "{topic}". JSON uniquement:\n'
        '{"titre":"...","definition":"2 phrases concretes.","points_cles":["fait 1","fait 2","fait 3"],"exemple":"...","a_retenir":"..."}'
    )
    raw = await call_agent(fiche_agent, session_service, prompt)

    # Cherche le JSON peu importe le texte autour
    obj = extract_first_object(raw)
    if not obj:
        objects = extract_all_objects(raw)
        obj = next((o for o in objects if "titre" in o or "definition" in o or "points_cles" in o), None)

    if not obj:
        return f"\n📖 Fiche : {topic.upper()}\n   {raw[:400]}\n"

    out = f"\n📖 Fiche : {obj.get('titre', topic).upper()}\n"
    if obj.get("definition"):
        out += f"   Definition : {obj['definition']}\n"
    out += "   Points cles :\n"
    seen = set()
    for pt in obj.get("points_cles", [])[:5]:
        p = str(pt).strip()
        if p and p not in seen:
            seen.add(p)
            out += f"     - {p}\n"
    if obj.get("exemple"):
        out += f"   Exemple : {obj['exemple']}\n"
    if obj.get("a_retenir"):
        out += f"   A retenir : {obj['a_retenir']}\n"
    return out


def display_question():
    idx = state["quiz_index"]
    q = state["quiz_batch"][idx]
    num = idx + 1
    print(f"\nAgent > \033[1mQuestion {num}\033[0m")
    print(f"         {q['question']}")
    for letter in ["A", "B", "C", "D"]:
        print(f"         {letter}) {q['choices'].get(letter, '?')}")
    print("         -> Reponds par A, B, C ou D\n")


async def main():
    session_service = InMemorySessionService()

    print("=" * 60)
    print("🎓  Assistant de Revision Multi-Agents (ADK)")
    print("=" * 60)
    print("  'quiz <sujet>'           -> questions sur un sujet")
    print("  'fiche <sujet>'          -> fiche de revision")
    print("  'A/B/C/D'                -> repondre a une question")
    print("  'stop'                   -> abandonner le quiz")
    print("  'score'                  -> ta progression")
    print("  'exit'                   -> quitter")
    print("=" * 60)
    print()

    while True:
        try:
            text = input("Vous > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAu revoir !")
            break

        if not text:
            continue
        if text.lower() in {"exit", "quit", "q"}:
            print("Bonne revision !")
            break

        t = text.lower().strip().rstrip("?!.,;:")

        # Sujets bloqués
        if any(w in t for w in BLOCKED):
            print("\nAgent > 🚫 Sujet non approprie pour la revision scolaire.\n")
            continue

        # Salutations
        if t in GREETINGS or any(t.startswith(g + " ") for g in GREETINGS):
            print("\nAgent > Salut ! Je suis ton assistant de revision 🎓")
            print("         Ex: 'quiz photosynthese', 'fiche Napoleon', 'score'\n")
            continue

        # Réponse A/B/C/D
        if t in {"a", "b", "c", "d"}:
            if not state["quiz_active"]:
                print("\nAgent > Aucun quiz en cours. Tape 'quiz <sujet>' d'abord !\n")
                continue
            answer = t.upper()
            idx_q = state["quiz_index"]
            q = state["quiz_batch"][idx_q]
            result = check_answer(q["question"], answer, q["correct"])
            state["total_questions"] += 1
            if result["is_correct"]:
                state["score"] += 1
                state["batch_score"] += 1
            print(f"\nAgent > {result['feedback']}")
            if not result["is_correct"] and q.get("explication"):
                print(f"         💡 {q['explication']}")
            if idx_q + 1 < len(state["quiz_batch"]):
                state["quiz_index"] += 1
                display_question()
            else:
                state["quiz_active"] = False
                nb = len(state["quiz_batch"])
                pct = round(state["batch_score"] / nb * 100)
                emoji = "🌟" if pct >= 80 else "👍" if pct >= 50 else "📚"
                print(f"\nAgent > {emoji} Fin du lot ! Score : {state['batch_score']}/{nb} ({pct}%)")
                print(f"         Tape 'quiz {state['last_topic']}' pour un nouveau lot !\n")
            continue

        # Stop
        if t == "stop":
            if state["quiz_active"]:
                state["quiz_active"] = False
                print("\nAgent > Quiz abandonne.\n")
            else:
                print("\nAgent > Aucun quiz en cours.\n")
            continue

        # Bloquer si quiz en cours
        if state["quiz_active"]:
            print(f"\nAgent > Quiz en cours ! Question {state['quiz_index']+1}/{len(state['quiz_batch'])}.")
            print("         Reponds par A, B, C ou D — ou tape 'stop'.\n")
            continue

        # Analyse LLM
        parsed = await analyze_intent(session_service, text)
        intent = parsed["intent"]
        topic = parsed["topic"]

        try:
            if intent == "quiz":
                if is_gibberish_topic(topic):
                    print("\nAgent > 🚫 Sujet non reconnu (ça ressemble à du texte aléatoire).")
                    print("         Essaie un vrai thème: 'quiz mbappe', 'quiz photosynthese', 'quiz réseau', etc.\n")
                    continue
                if not topic:
                    print("\nAgent > Sur quel sujet veux-tu un quiz ?\n")
                    continue
                batch = await generate_quiz(session_service, topic)
                if not batch:
                    print(f"Agent > Impossible de generer des questions sur '{topic}'.\n")
                    continue
                state["quiz_batch"] = batch
                state["quiz_index"] = 0
                state["quiz_active"] = True
                state["last_topic"] = topic
                state["batch_score"] = 0
                display_question()

            elif intent == "fiche":
                if is_gibberish_topic(topic):
                    print("\nAgent > 🚫 Sujet non reconnu (texte aléatoire).")
                    print("         Donne un vrai sujet pour une fiche.\n")
                    continue
                if not topic:
                    print("\nAgent > Sur quel sujet veux-tu une fiche ?\n")
                    continue
                fiche = await generate_fiche(session_service, topic)
                print(f"Agent > {fiche}")

            elif intent == "score":
                result = track_progress("student_1", state["last_topic"],
                                        state["score"], max(state["total_questions"], 1))
                print(f"\nAgent > 📊 Bilan :")
                print(f"         Score : {state['score']}/{state['total_questions']} ({result.get('percentage',0)}%)")
                print(f"         {result.get('message','')}")
                if state["last_topic"]:
                    print(f"         Dernier sujet : {state['last_topic']}")
                print()

            elif intent == "hors_sujet":
                print("\nAgent > 🚫 Sujet non reconnu. Choisis un sujet valide !\n")

            else:
                print("\nAgent > Je n'ai pas compris. Essaie 'quiz <sujet>' ou 'fiche <sujet>' !\n")

        except Exception as e:
            print(f"Erreur : {e}\n")


if __name__ == "__main__":
    asyncio.run(main())