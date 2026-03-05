from google.adk.agents import LlmAgent
from google.adk.tools import AgentTool
from .model import MODEL
from .quiz_agent import quiz_agent
from .summary_agent import summary_agent
from .corrector_agent import corrector_agent
from .progress_agent import progress_agent
from .quiz_workflow import quiz_workflow
from .callbacks import before_model_callback

# Mécanisme 1 : AgentTool (invocation comme outil)
progress_agent_tool = AgentTool(agent=progress_agent)
quiz_workflow_tool = AgentTool(agent=quiz_workflow)

# Mécanisme 2 : sub_agents (transfer_to_agent / délégation complète)
router_agent = LlmAgent(
    name="router_agent",
    model=MODEL,
    description="Agent principal qui route les demandes vers les agents spécialisés.",
    instruction="""Tu es le coordinateur principal d'un assistant de révision scolaire.

Tu disposes de deux types d'agents :

DELEGATION COMPLETE (transfer_to_agent) :
- quiz_agent      : si l'utilisateur demande un quiz ou des questions
- summary_agent   : si l'utilisateur demande une fiche ou un résumé
- corrector_agent : si l'utilisateur donne une réponse A, B, C ou D

INVOCATION COMME OUTIL (AgentTool) :
- progress_agent_tool : si l'utilisateur demande son score ou bilan
- quiz_workflow_tool  : si l'utilisateur demande un quiz complet

RÈGLES :
- Bonjour/salut/conversation -> réponds toi-même sans déléguer
- Demande ambiguë -> demande des précisions
- Ne délègue QUE si la demande correspond à un cas ci-dessus
""",
    tools=[progress_agent_tool, quiz_workflow_tool],
    sub_agents=[quiz_agent, summary_agent, corrector_agent],
    before_model_callback=before_model_callback,
)