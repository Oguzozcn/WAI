import asyncio
import os
import sys
import traceback

# Ensure the project root is in the python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from WAI_agent.sub_agents.curriculum_builder.agent import curriculum_builder_agent
from WAI_agent.sub_agents.knowledge_coach.agent import knowledge_coach_agent

def run_test():
    print("=" * 50)
    print("TEST 1: Curriculum Builder (Gap ID & Learning Path)")
    print("=" * 50)
    
    prompt_1 = "Create a learning path for 'Vertex AI Fundamentals'. Identify the key concepts needed."
    print(f"Sending prompt: {prompt_1}")
    
    try:
        # Try synchronous run
        for chunk in curriculum_builder_agent.run(prompt_1):
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
        print(f"\nError testing curriculum_builder: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    run_test()
