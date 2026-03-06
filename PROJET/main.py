"""Programmatic runner for the ADK multi-agent project."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from my_agent.agent import root_agent


async def _send_turn_async(
    runner: Runner,
    session_id: str,
    user_id: str,
    prompt: str,
) -> None:
    """Send one user turn and print assistant text outputs."""
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=message,
    ):
        if not event.content or not event.content.parts:
            continue
        text_parts = [part.text for part in event.content.parts if getattr(part, "text", None)]
        if text_parts:
            print("\n".join(text_parts))


async def run_chat_async(initial_prompt: str | None = None, user_id: str = "student") -> None:
    """Run an interactive ADK chat with a persistent in-memory session."""
    project_root = Path(__file__).resolve().parent
    load_dotenv(project_root / "my_agent" / ".env")

    session_service = InMemorySessionService()
    app_name = "revision_quiz_app"
    session = await session_service.create_session(app_name=app_name, user_id=user_id)
    runner = Runner(agent=root_agent, app_name=app_name, session_service=session_service)

    print("Mode interactif ADK. Tape 'exit' pour quitter.")

    if initial_prompt:
        await _send_turn_async(runner, session.id, user_id, initial_prompt)

    while True:
        user_text = input("\nyou> ").strip()
        if not user_text:
            continue
        if user_text.lower() in {"exit", "quit", "q"}:
            print("Fin de session.")
            break
        await _send_turn_async(runner, session.id, user_id, user_text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ADK fiche/quiz agent.")
    parser.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="Optional first prompt before entering interactive mode.",
    )
    args = parser.parse_args()

    os.environ.setdefault("PYTHONUTF8", "1")
    asyncio.run(run_chat_async(initial_prompt=args.prompt))


if __name__ == "__main__":
    main()
