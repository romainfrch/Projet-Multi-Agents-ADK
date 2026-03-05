from google.adk.models.lite_llm import LiteLlm

MODEL = LiteLlm(
    model="ollama/mistral:latest",
    max_tokens=2048,
)