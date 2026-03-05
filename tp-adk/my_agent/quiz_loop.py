from google.adk.agents import LoopAgent, LlmAgent
from .model import MODEL
from .tools.revision_tools import generate_question_tool
from .callbacks import before_model_callback, after_tool_callback

# Instance séparée pour la boucle
# (un agent ne peut pas avoir deux parents différents dans ADK)
_quiz_agent_loop = LlmAgent(
    name="quiz_agent_loop",
    model=MODEL,
    description="Génère des questions QCM en boucle.",
    instruction="""Tu es un générateur de quiz scolaire.
Génère une question QCM sur le sujet : {last_topic}
""",
    tools=[generate_question_tool],
    output_key="quiz_output",
    before_model_callback=before_model_callback,
    after_tool_callback=after_tool_callback,
)

# Boucle de génération : répète la génération de questions jusqu'à 3 fois
quiz_loop = LoopAgent(
    name="quiz_loop",
    description="Génère plusieurs séries de questions en boucle (max 3 itérations).",
    sub_agents=[_quiz_agent_loop],
    max_iterations=3,
)