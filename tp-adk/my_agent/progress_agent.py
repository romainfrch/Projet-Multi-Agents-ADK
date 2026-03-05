from google.adk.agents import LlmAgent
from .model import MODEL
from .tools.revision_tools import track_progress_tool
from .callbacks import before_model_callback, after_tool_callback

progress_agent = LlmAgent(
    name="progress_agent",
    model=MODEL,
    description="Suit la progression de l'étudiant et donne des conseils personnalisés.",
    instruction="""Tu es un coach scolaire qui suit la progression des étudiants.

Quand l'utilisateur demande son bilan ou sa progression :
1. Utilise l'outil track_progress UNE SEULE FOIS avec les données fournies
2. Présente un bilan motivant avec le pourcentage de réussite
3. STOP. N'appelle plus track_progress.

Sois motivant, bienveillant et donne des conseils concrets.
""",
    tools=[track_progress_tool],
    output_key="progress_output",
    before_model_callback=before_model_callback,
    after_tool_callback=after_tool_callback,
)