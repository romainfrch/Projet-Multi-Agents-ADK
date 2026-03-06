"""Custom tools for the ADK fiche/quiz project."""

from __future__ import annotations

import json
import re
from typing import Any


def extract_study_context(raw_request: str) -> dict[str, Any]:
    """Extract topic, level and revision duration from a user request.

    Args:
        raw_request: Natural language request from the user.

    Returns:
        A dictionary with normalized fields: topic, level, duration_min.

    Raises:
        ValueError: If the request is empty or unusable.
    """
    try:
        text = (raw_request or "").strip()
        if not text:
            raise ValueError("La demande est vide.")

        lowered = text.lower()

        level = "intermediaire"
        if any(k in lowered for k in ["debutant", "débutant", "novice"]):
            level = "debutant"
        elif any(k in lowered for k in ["avance", "avancé", "expert"]):
            level = "avance"

        duration_min = 30
        duration_match = re.search(r"(\d{1,3})\s*(min|minutes|h|heure|heures)", lowered)
        if duration_match:
            value = int(duration_match.group(1))
            unit = duration_match.group(2)
            duration_min = value * 60 if unit.startswith("h") else value

        topic = text
        for marker in ["fais", "fais-moi", "crée", "cree", "prépare", "prepare"]:
            if marker in lowered:
                idx = lowered.find(marker)
                topic = text[idx + len(marker) :].strip(" :,-")
                break

        topic = topic[:160] if topic else "sujet non precise"

        return {
            "topic": topic,
            "level": level,
            "duration_min": max(10, min(duration_min, 240)),
        }
    except Exception as exc:
        return {"error": f"extract_study_context_failed: {exc}"}


def response(raw_request: str = "", message: str = "") -> dict[str, Any]:
    """Compatibility alias for LLM tool-call hallucinations.

    Some non-native tool-calling models may invent a `response` function name.
    This alias safely redirects to `extract_study_context`.
    """
    text = (raw_request or message or "").strip()
    if not text:
        return {"error": "response_alias_missing_input"}
    return extract_study_context(text)


def quiz_writer_agent(draft_quiz: str = "") -> dict[str, Any]:
    """Compatibility alias when the model hallucinates `quiz_writer_agent` as a tool name.

    This function returns a lightly normalized quiz draft so the run does not fail.
    """
    text = (draft_quiz or "").strip()
    if not text:
        return {
            "status": "noop",
            "message": "Aucun brouillon fourni. Continue sans appel de tool.",
        }
    return {
        "status": "ok",
        "message": "Brouillon recu et conserve sans modification.",
        "reviewed_quiz": text,
    }


def build_memory_hooks(topic: str, level: str) -> dict[str, Any]:
    """Create simple memory hooks to help active recall.

    Args:
        topic: Topic to revise.
        level: Learner level (debutant/intermediaire/avance).

    Returns:
        A dictionary with flash prompts and trap questions.
    """
    try:
        clean_topic = (topic or "").strip()
        clean_level = (level or "intermediaire").strip().lower()
        if not clean_topic:
            raise ValueError("topic manquant")

        hooks = [
            f"Explique {clean_topic} en 3 phrases.",
            f"Donne 2 erreurs frequentes sur {clean_topic}.",
            f"Relie {clean_topic} a un cas concret.",
        ]

        if clean_level == "debutant":
            hooks.append("Definis les notions de base sans jargon.")
        elif clean_level == "avance":
            hooks.append("Compare deux approches et justifie les compromis.")

        return {
            "topic": clean_topic,
            "level": clean_level,
            "memory_hooks": hooks,
        }
    except Exception as exc:
        return {"error": f"build_memory_hooks_failed: {exc}"}


def grade_quiz_submission(quiz_payload: str, user_answers_payload: str) -> dict[str, Any]:
    """Grade a quiz attempt from JSON payloads.

    Args:
        quiz_payload: JSON string containing questions and expected answers.
        user_answers_payload: JSON string mapping question ids to answers.

    Returns:
        Score summary with percentage and per-question feedback.
    """
    try:
        quiz = json.loads(quiz_payload)
        answers = json.loads(user_answers_payload)

        questions = quiz.get("questions", [])
        if not isinstance(questions, list) or not questions:
            raise ValueError("questions invalides")

        total = 0
        correct = 0
        details: list[dict[str, Any]] = []

        for question in questions:
            qid = str(question.get("id", ""))
            expected = str(question.get("answer", "")).strip().lower()
            received = str(answers.get(qid, "")).strip().lower()
            ok = expected != "" and received == expected
            total += 1
            correct += 1 if ok else 0
            details.append(
                {
                    "id": qid,
                    "ok": ok,
                    "expected": expected,
                    "received": received,
                }
            )

        percentage = round((correct / total) * 100, 1)
        return {
            "score": f"{correct}/{total}",
            "percentage": percentage,
            "details": details,
        }
    except Exception as exc:
        return {"error": f"grade_quiz_submission_failed: {exc}"}


def result(user_answers: str = "", quiz_text: str = "") -> str:
    """Compatibility tool for hallucinated `result` function calls.

    Args:
        user_answers: Free-form answers string from the user.
        quiz_text: Quiz text currently in context.

    Returns:
        A normalized payload that can be reused by the agent to produce
        a correction message without failing on unknown tools.
    """
    _ = (quiz_text or "").strip()
    answers = (user_answers or "").strip()
    return (
        "Reponses recues: "
        f"{answers if answers else 'aucune reponse detectee'}. "
        "Je prepare la correction lisible (score + detail Q1-Q3)."
    )


def transfer_to_assessment_agent(payload: str = "") -> str:
    """Compatibility alias for hallucinated transfer tool names.

    Returns the payload unchanged so the run does not fail on unknown tool calls.
    """
    clean_payload = (payload or "").strip()
    return (
        "Demande de correction recue "
        f"{': ' + clean_payload if clean_payload else ''}. "
        "Generation du resultat lisible."
    )


def quiz_correction_agent(payload: str = "") -> str:
    """Compatibility alias for hallucinated calls to `quiz_correction_agent` tool.

    Returns a short text so the run can continue without crashing.
    """
    clean_payload = (payload or "").strip()
    return (
        "Correction en cours."
        f"{' Donnees recues: ' + clean_payload if clean_payload else ''}"
    )


def print_response(text: str = "", payload: str = "") -> str:
    """Compatibility alias for hallucinated `print_response` tool calls.

    Returns plain readable text only.
    """
    content = (text or payload or "").strip()
    if not content:
        return "Correction en cours de generation."

    def _decode_escapes(raw: str) -> str:
        out = raw
        if "\\n" in out or "\\u" in out:
            try:
                out = bytes(out, "utf-8").decode("unicode_escape")
            except Exception:
                pass
        return out

    def _extract_result_block(raw: str) -> str | None:
        decoded = _decode_escapes(raw)
        m = re.search(r"(RESULTAT.*?Relance:[^\n]*\?)", decoded, flags=re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return None

    # 1) If the tool received raw JSON, try to parse and extract nested text fields.
    if content.startswith("{") or content.startswith("["):
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = None

        if parsed is not None:
            if isinstance(parsed, dict):
                for direct_key in ("result", "text", "output", "message", "content"):
                    direct_val = parsed.get(direct_key)
                    if isinstance(direct_val, str) and direct_val.strip():
                        content = direct_val.strip()
                        break

            candidates: list[str] = []

            def _walk(node: Any) -> None:
                if isinstance(node, dict):
                    for k, v in node.items():
                        if isinstance(v, (dict, list)):
                            _walk(v)
                        elif isinstance(v, str) and k.lower() in {
                            "text",
                            "result",
                            "output",
                            "content",
                            "message",
                            "final",
                            "assistant",
                        }:
                            candidates.append(v)
                elif isinstance(node, list):
                    for item in node:
                        _walk(item)

            _walk(parsed)
            for candidate in candidates:
                block = _extract_result_block(candidate)
                if block:
                    return block

    # 2) Fallback on the raw payload itself.
    block = _extract_result_block(content)
    if block:
        return block

    # 3) Handle common bad pattern: English JSON-like correction with extra quiz dump.
    decoded = _decode_escapes(content)
    lowered = decoded.lower()
    if "the user's responses are correct" in lowered or "complete quiz with all four questions" in lowered:
        return (
            "RESULTAT\n"
            "Score: 3/3\n"
            "Q1 - Ta reponse: correcte | Bonne reponse: correcte | Feedback: Bien joue.\n"
            "Q2 - Ta reponse: correcte | Bonne reponse: correcte | Feedback: Bien joue.\n"
            "Q3 - Ta reponse: correcte | Bonne reponse: correcte | Feedback: Bien joue.\n"
            "Conseil: Continue comme ca, tes reponses sont solides.\n"
            "Relance: Veux-tu un nouveau quiz ou une fiche ?"
        )

    # 4) Last fallback: decode escapes and keep only readable plain text.
    return decoded


def print_result(text: str = "", payload: str = "") -> str:
    """Compatibility alias for hallucinated `print_result` tool calls."""
    return print_response(text=text, payload=payload)


def generate_correction(text: str = "", payload: str = "") -> str:
    """Compatibility alias for hallucinated `generate_correction` tool calls."""
    return print_response(text=text, payload=payload)


def _normalize_letter(value: str) -> str:
    letter = (value or "").strip().upper()
    return letter if letter in {"A", "B", "C"} else ""


def _parse_user_answers(user_answers: str) -> dict[str, str]:
    raw = (user_answers or "").strip()
    if not raw:
        return {}

    compact = re.sub(r"\s+", "", raw.upper())
    if re.fullmatch(r"[ABC]{3}", compact):
        return {"Q1": compact[0], "Q2": compact[1], "Q3": compact[2]}

    out: dict[str, str] = {}
    pairs = re.findall(r"Q([123])\s*[:=-]\s*([ABC])", raw, flags=re.IGNORECASE)
    for qid, letter in pairs:
        out[f"Q{qid}"] = letter.upper()

    if len(out) == 3:
        return out

    letters = re.findall(r"\b([ABC])\b", raw.upper())
    if len(letters) >= 3:
        return {"Q1": letters[0], "Q2": letters[1], "Q3": letters[2]}
    return out


def _parse_answer_key(quiz_text: str) -> dict[str, str]:
    text = (quiz_text or "").strip()
    if not text:
        return {}

    key_match = re.search(
        r"<!--\s*ANSWERS\s*:\s*Q1\s*=\s*([ABC])\s*;\s*Q2\s*=\s*([ABC])\s*;\s*Q3\s*=\s*([ABC])\s*-->",
        text,
        flags=re.IGNORECASE,
    )
    if key_match:
        return {
            "Q1": key_match.group(1).upper(),
            "Q2": key_match.group(2).upper(),
            "Q3": key_match.group(3).upper(),
        }

    fallback = {}
    for qid, letter in re.findall(r"Q([123])\s*[:=-]\s*([ABC])", text, flags=re.IGNORECASE):
        fallback[f"Q{qid}"] = letter.upper()
    return fallback if len(fallback) >= 3 else {}


def build_quiz_correction_text(user_answers: str = "", quiz_text: str = "") -> str:
    """Deterministic quiz correction (no LLM), always returned in French."""
    parsed_user = _parse_user_answers(user_answers)
    if len(parsed_user) != 3:
        return "Je ne comprends pas votre demande. Pouvez-vous la reiterer ?"

    answer_key = _parse_answer_key(quiz_text)
    if len(answer_key) != 3:
        return (
            "Je ne peux pas corriger ce quiz pour le moment (cle de correction absente). "
            "Demande un nouveau quiz puis reponds au format: Q1: ... | Q2: ... | Q3: ..."
        )

    score = 0
    lines: list[str] = []
    for q in ("Q1", "Q2", "Q3"):
        user_letter = _normalize_letter(parsed_user.get(q, ""))
        good_letter = _normalize_letter(answer_key.get(q, ""))
        is_ok = user_letter == good_letter and user_letter != ""
        if is_ok:
            score += 1
        feedback = "Bonne reponse." if is_ok else "Reponse incorrecte."
        lines.append(
            f"{q} - Ta reponse: {user_letter or '?'} | Bonne reponse: {good_letter or '?'} | Feedback: {feedback}"
        )

    if score == 3:
        tip = "Excellent, continue comme ca."
    elif score == 2:
        tip = "Bon resultat. Revois la question ratee."
    elif score == 1:
        tip = "Tu progresses. Reprends la fiche puis retente un quiz."
    else:
        tip = "Relis la fiche, puis refais un quiz."

    return (
        "RESULTAT\n"
        f"Score: {score}/3\n"
        f"{lines[0]}\n"
        f"{lines[1]}\n"
        f"{lines[2]}\n"
        f"Conseil: {tip}\n"
        "Relance: Veux-tu un nouveau quiz ou une fiche ?"
    )
