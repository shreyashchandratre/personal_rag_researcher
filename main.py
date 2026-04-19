"""
Personal RAG Document Researcher: CLI entry point.
"""

from __future__ import annotations

import sys

from langchain_core.messages import AIMessage, HumanMessage

from agent_service import (
    build_agent,
    ensure_env_loaded,
    last_assistant_text,
    load_vectorstore,
)


def main() -> None:
    ensure_env_loaded()

    try:
        load_vectorstore()
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    agent = build_agent()

    print("Personal RAG Researcher — type 'quit' or 'exit' to stop.\n")
    messages: list = []

    while True:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        if user.lower() in {"quit", "exit", "q"}:
            break

        messages.append(HumanMessage(content=user))
        try:
            result = agent.invoke({"messages": messages})
        except Exception as e:
            print(f"Agent error: {e}", file=sys.stderr)
            messages.pop()
            continue

        messages = list(result.get("messages", messages))
        text = last_assistant_text(messages)
        if text:
            print(f"Agent: {text}\n")


if __name__ == "__main__":
    main()
