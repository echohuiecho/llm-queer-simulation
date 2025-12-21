from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from .personas import persona_agents
from ..tools import dispatch_persona_replies

# 1) Parallel persona decisions (each persona can use tools and writes final message to {aid}_reply via output_key)
parallel_deciders = ParallelAgent(
    name="ParallelDeciders",
    sub_agents=[persona_agents["a1"], persona_agents["a2"], persona_agents["a3"]],
)

# 2) Deterministic dispatch step: publish a1_reply/a2_reply/a3_reply to chat/outbox
dispatch_agent = LlmAgent(
    name="DispatchAgent",
    model="gemini-2.0-flash",
    instruction="""
You are a dispatcher.
Call the dispatch_persona_replies tool exactly once to publish persona replies into the chat.
Do not write anything else.
""",
    tools=[dispatch_persona_replies],
)

# Root: no shared ContextPrepAgent; personas prepare their own context if needed
root_agent = SequentialAgent(
    name="QueerSimRoot",
    sub_agents=[parallel_deciders, dispatch_agent],
    description="Parallel persona agents (with tools) + deterministic dispatch"
)
