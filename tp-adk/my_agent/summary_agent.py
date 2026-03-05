from google.adk.agents import LlmAgent
from .model import MODEL
from .tools.revision_tools import generate_summary_tool
from .callbacks import before_model_callback, after_tool_callback

summary_agent = LlmAgent(
    name="summary_agent",
    model=MODEL,
    description="Crée des fiches de révision structurées sur un sujet académique.",
    instruction="""Tu es un expert en création de fiches de révision pédagogiques.

Quand l'utilisateur demande une fiche de révision sur un sujet :
1. Utilise l'outil generate_summary UNE SEULE FOIS avec le sujet
2. Présente la fiche de façon claire et structurée avec des titres
3. STOP. N'appelle plus generate_summary.

Structure ta présentation avec :
- Définition
- Points clés
- Exemple concret
- A retenir

Sois précis, concis et pédagogique.
""",
    tools=[generate_summary_tool],
    output_key="summary_output",
    before_model_callback=before_model_callback,
    after_tool_callback=after_tool_callback,
)