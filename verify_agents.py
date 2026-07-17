"""
TEAP Agent Verification Script — ADK 2.0
==========================================
Tests the declarative skill loading and root orchestrator.
"""

import asyncio
import os
import sys
import traceback

# Ensure the project root is in the python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agents.agent import root_agent


def run_test():
    print("=" * 50)
    print("TEST: Root Orchestrator — Curriculum Builder Skill")
    print("=" * 50)

    prompt = "Create a learning path for 'Vertex AI Fundamentals'. Identify the key concepts needed."
    print(f"Sending prompt: {prompt}")

    try:
        for chunk in root_agent.run(prompt):
            if hasattr(chunk, 'text'):
                print(chunk.text, end="", flush=True)
            elif hasattr(chunk, 'content'):
                print(chunk.content, end="", flush=True)
            elif isinstance(chunk, str):
                print(chunk, end="", flush=True)
            else:
                print(chunk, end="", flush=True)
        print("\n")
    except Exception as e:
        print(f"\nError testing root_agent: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    run_test()
