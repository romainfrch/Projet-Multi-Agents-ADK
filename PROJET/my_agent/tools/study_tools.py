"""Outils utilises par l'agent quiz/fiche."""

from __future__ import annotations

import re


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
