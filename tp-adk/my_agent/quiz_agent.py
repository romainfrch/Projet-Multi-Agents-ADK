from google.adk.agents import LlmAgent
from .model import MODEL
from .tools.revision_tools import generate_question_tool
from .callbacks import before_model_callback, after_tool_callback

quiz_agent = LlmAgent(
    name="quiz_agent",
    model=MODEL,
    description="Génère des questions QCM de révision sur un sujet donné.",
    instruction="""Tu es un générateur de quiz scolaire.

Quand tu reçois un sujet :
1. Appelle generate_question UNE SEULE FOIS avec le sujet
2. Présente la question et les choix A, B, C, D
3. STOP. N'appelle plus generate_question. Attends la réponse de l'utilisateur.

IMPORTANT : Tu ne dois appeler generate_question qu'une seule fois par message.
""",
    tools=[generate_question_tool],
    output_key="quiz_output",
    before_model_callback=before_model_callback,
    after_tool_callback=after_tool_callback,
)