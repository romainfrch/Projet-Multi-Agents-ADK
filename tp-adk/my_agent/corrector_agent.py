from google.adk.agents import LlmAgent
from .model import MODEL
from .tools.revision_tools import check_answer_tool
from .callbacks import before_model_callback, after_tool_callback

corrector_agent = LlmAgent(
    name="corrector_agent",
    model=MODEL,
    description="Corrige les réponses de l'utilisateur au quiz et donne un feedback pédagogique.",
    instruction="""Tu es un correcteur pédagogique bienveillant.

Quand l'utilisateur donne une réponse (A, B, C ou D) :
1. Utilise l'outil check_answer pour vérifier la réponse
2. Donne un feedback clair et encourageant
3. Si la réponse est fausse, explique brièvement pourquoi la bonne réponse est correcte

Sois toujours positif et encourage l'étudiant à continuer.
""",
    tools=[check_answer_tool],
    output_key="correction_output",
    before_model_callback=before_model_callback,
    after_tool_callback=after_tool_callback,
)