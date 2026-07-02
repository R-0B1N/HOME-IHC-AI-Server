import sys
import asyncio
from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig
from google.antigravity.hooks import policy

async def main():
    if len(sys.argv) < 2:
        print("Please provide a prompt.")
        sys.exit(1)
        
    prompt = sys.argv[1]
    
    # Configure the agent
    # We use policy.allow_all() to fully automate execution (YOLO mode)
    config = LocalAgentConfig(
        system_instructions="You are an autonomous AI orchestrator. Use the tools available to you to gather context, write code, run commands, and make progress on the project.",
        capabilities=CapabilitiesConfig(),
        policies=[policy.allow_all()],
    )
    
    async with Agent(config) as agent:
        print("Agent is thinking...", flush=True)
        response = await agent.chat(prompt)
        
        # Stream the response back to the console
        async for chunk in response:
            print(chunk, end="", flush=True)
        print()

if __name__ == "__main__":
    # We use asyncio to run the async main function
    asyncio.run(main())
