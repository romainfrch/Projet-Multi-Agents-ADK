from google.adk.agents import SequentialAgent, LlmAgent
from .model import MODEL
from .tools.revision_tools import generate_question_tool, check_answer_tool
from .callbacks import before_model_callback, after_tool_callback

# Instances séparées pour le workflow
# (un agent ne peut pas avoir deux parents différents dans ADK)
_quiz_agent_wf = LlmAgent(
    name="quiz_agent_workflow",
    model=MODEL,
    description="Génère des questions QCM de révision sur un sujet donné.",
    instruction="""Tu es un générateur de quiz scolaire.
Génère 3 questions QCM sur le sujet demandé en utilisant generate_question.
Sujet actuel : {last_topic}
""",
    tools=[generate_question_tool],
    output_key="quiz_output",
    before_model_callback=before_model_callback,
    after_tool_callback=after_tool_callback,
)

_corrector_agent_wf = LlmAgent(
    name="corrector_agent_workflow",
    model=MODEL,
    description="Corrige les réponses de l'utilisateur au quiz.",
    instruction="""Tu es un correcteur pédagogique.
Dernière question : {last_question}
Bonne réponse : {last_correct_answer}
Utilise check_answer pour corriger la réponse de l'utilisateur.
""",
    tools=[check_answer_tool],
    output_key="correction_output",
    before_model_callback=before_model_callback,
    after_tool_callback=after_tool_callback,
)

# Workflow séquentiel : génère d'abord le quiz, puis corrige automatiquement
quiz_workflow = SequentialAgent(
    name="quiz_workflow",
    description="Workflow complet : génère un quiz puis corrige les réponses dans l'ordre.",
    sub_agents=[_quiz_agent_wf, _corrector_agent_wf],
)