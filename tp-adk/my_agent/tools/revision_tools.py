from google.adk.tools import FunctionTool


def generate_question(topic: str, question_number: int = 1) -> dict:
    """Génère une question QCM de révision sur un sujet donné.

    Args:
        topic: Le sujet sur lequel générer la question.
        question_number: Numéro de la question (1, 2, 3) pour varier le type.

    Returns:
        Un dictionnaire avec la question et les choix possibles.
    """
    if not topic or not topic.strip():
        return {"error": "Le sujet ne peut pas être vide.", "status": "error"}

    # Types de questions variés selon le numéro
    question_types = {
        1: "définition",
        2: "exemple ou application",
        3: "comparaison ou différence",
    }
    q_type = question_types.get(question_number, "définition")

    return {
        "topic": topic,
        "question_type": q_type,
        "question_number": question_number,
        "instruction": f"Génère une question QCM de type '{q_type}' sur le sujet '{topic}'",
        "status": "success",
    }


def check_answer(question: str, user_answer: str, correct_answer: str) -> dict:
    """Vérifie la réponse de l'utilisateur à une question de quiz.

    Args:
        question: La question posée.
        user_answer: La réponse fournie par l'utilisateur (A, B, C ou D).
        correct_answer: La bonne réponse (A, B, C ou D).

    Returns:
        Un dictionnaire avec le résultat de la correction et un feedback.
    """
    if not user_answer or not user_answer.strip():
        return {"error": "La réponse ne peut pas être vide.", "status": "error"}

    user_answer = user_answer.strip().upper()
    correct_answer = correct_answer.strip().upper()

    if user_answer not in ("A", "B", "C", "D"):
        return {"error": "La réponse doit être A, B, C ou D.", "status": "error"}

    is_correct = user_answer == correct_answer
    return {
        "question": question,
        "user_answer": user_answer,
        "correct_answer": correct_answer,
        "is_correct": is_correct,
        "feedback": "✅ Bonne réponse !" if is_correct else f"❌ Mauvaise réponse. La bonne réponse était {correct_answer}.",
        "status": "success",
    }


def generate_summary(topic: str, level: str = "intermédiaire") -> dict:
    """Génère une fiche de révision structurée sur un sujet.

    Args:
        topic: Le sujet à résumer.
        level: Le niveau ('débutant', 'intermédiaire', 'avancé').

    Returns:
        Un dictionnaire avec les métadonnées pour générer la fiche.
    """
    if not topic or not topic.strip():
        return {"error": "Le sujet ne peut pas être vide.", "status": "error"}

    valid_levels = ("débutant", "intermédiaire", "avancé")
    if level not in valid_levels:
        level = "intermédiaire"

    return {
        "topic": topic,
        "level": level,
        "status": "success",
    }


def track_progress(user_id: str, topic: str, score: int, total: int) -> dict:
    """Enregistre et retourne la progression de l'étudiant.

    Args:
        user_id: Identifiant de l'étudiant.
        topic: Le sujet évalué.
        score: Nombre de bonnes réponses.
        total: Nombre total de questions.

    Returns:
        Un dictionnaire avec le pourcentage de réussite et un message.
    """
    if total <= 0:
        return {"percentage": 0, "message": "Aucune question répondue.", "status": "success"}

    score = max(0, min(score, total))
    percentage = round((score / total) * 100, 1)

    if percentage >= 80:
        message = "🌟 Excellent ! Tu maîtrises ce sujet."
    elif percentage >= 60:
        message = "👍 Bien ! Encore quelques révisions."
    else:
        message = "📚 Continue, ne te décourage pas !"

    return {
        "user_id": user_id,
        "topic": topic,
        "score": score,
        "total": total,
        "percentage": percentage,
        "message": message,
        "status": "success",
    }


generate_question_tool = FunctionTool(generate_question)
check_answer_tool = FunctionTool(check_answer)
generate_summary_tool = FunctionTool(generate_summary)
track_progress_tool = FunctionTool(track_progress)