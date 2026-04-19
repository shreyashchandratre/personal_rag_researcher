import os
from dotenv import load_dotenv
load_dotenv()
from langchain_cerebras import ChatCerebras
from langchain_core.tools import tool
@tool
def adder(a: int) -> int:
    """Adds 1 to a number."""
    return a + 1
llm = ChatCerebras(model='llama-3.3-70b', api_key=os.environ.get('CEREBRAS_API_KEY'))
llm_with_tools = llm.bind_tools([adder])
print("Invoking Cerebras with tools...")
try:
    r = llm_with_tools.invoke("add 1 to 5")
    print("Result:", r)
except Exception as e:
    print("Cerebras Exception:", e)

from langchain_ollama import ChatOllama
o = ChatOllama(model='mistral', temperature=0, num_ctx=8192)
o_with_tools = o.bind_tools([adder])
print("Invoking Ollama Mistral with tools...")
try:
    r2 = o_with_tools.invoke("add 1 to 5")
    print("Ollama Result:", r2)
except Exception as e:
    print("Ollama Exception:", e)
