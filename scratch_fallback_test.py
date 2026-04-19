from agent_service import build_agent
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

load_dotenv()
agent = build_agent()
try:
    print("Invoking agent...")
    res = agent.invoke({"messages": [HumanMessage(content="how many times can you say meow?")]})
    print("Agent Result:", res)
except Exception as e:
    print("Ex:", e)
