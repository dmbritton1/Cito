"""Single source of truth for the model integration.

Swapping models/providers must be a one-line edit here — the model id and
endpoint appear nowhere else.
"""

GEMMA_MODEL = "gemma-4-26b-a4b-it"
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
