"""Programmatic runner for the ADK multi-agent project."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from my_agent.agent import root_agent


def run_once(prompt: str, user_id: str = "student") -> None:
    """Run one prompt through ADK Runner with an in-memory session."""
    project_root = Path(__file__).resolve().parent
    load_dotenv(project_root / "my_agent" / ".env")

    session_service = InMemorySessionService()
    app_name = "revision_quiz_app"
    session = session_service.create_session_sync(app_name=app_name, user_id=user_id)

    runner = Runner(agent=root_agent, app_name=app_name, session_service=session_service)
    message = types.Content(role="user", parts=[types.Part(text=prompt)])

    for event in runner.run(user_id=user_id, session_id=session.id, new_message=message):
        if not event.content or not event.content.parts:
            continue
        text_parts = [part.text for part in event.content.parts if getattr(part, "text", None)]
        if text_parts:
            print("\n".join(text_parts))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ADK fiche/quiz agent.")
    parser.add_argument(
        "prompt",
        nargs="?",
        default="Fais-moi une fiche et un quiz sur les probabilites pour un niveau debutant en 30 minutes.",
    )
    args = parser.parse_args()

    os.environ.setdefault("PYTHONUTF8", "1")
    run_once(args.prompt)


if __name__ == "__main__":
    main()
