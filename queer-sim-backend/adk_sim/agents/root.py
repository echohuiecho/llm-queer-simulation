import random
from google.adk.agents import LlmAgent, SequentialAgent
from .personas import create_persona_agent
from config import config
from ..tools import dispatch_persona_replies
from .storyline import create_storyline_pipeline

def create_dispatch_agent() -> LlmAgent:
    """Create a fresh dispatch agent instance to avoid parent agent conflicts."""
    return LlmAgent(
        name="DispatchAgent",
        model="gemini-2.0-flash",
        instruction="""
You are a dispatcher.
Call the dispatch_persona_replies tool exactly once to publish persona replies into the chat.
Do not write anything else.
""",
        tools=[dispatch_persona_replies],
    )


def create_root_agent_with_shuffled_order(*, enable_storyline: bool = False) -> SequentialAgent:
    """
    Create a root SequentialAgent with persona agents in a random order.
    This ensures each agent sees state updates in a different order each turn.

    Note: We create fresh agent instances each time because ADK agents can only
    have one parent. Reusing the same instances would cause a validation error.

    Returns:
        A SequentialAgent with shuffled persona agents + dispatch agent,
        optionally extended with a LoopAgent storyline refinement pipeline.
    """
    # Create fresh agent instances to avoid "agent already has a parent" error
    profiles = config.get("agent_profiles", {})
    fresh_agents = {
        aid: create_persona_agent(aid, profile)
        for aid, profile in profiles.items()
    }

    # Get all persona agents in a list
    agents_list = [fresh_agents["a1"], fresh_agents["a2"], fresh_agents["a3"]]

    # Shuffle the order
    shuffled = agents_list.copy()
    random.shuffle(shuffled)

    # Log the order for debugging
    order = [agent.name for agent in shuffled]
    print(f"[ROOT] Creating SequentialDeciders with shuffled order: {order}")

    # Create SequentialAgent with shuffled persona agents
    sequential_deciders = SequentialAgent(
        name="SequentialDeciders",
        sub_agents=shuffled,
        description="Persona agents running sequentially in shuffled order"
    )

    # Create a fresh dispatch agent to avoid parent conflicts
    fresh_dispatch_agent = create_dispatch_agent()

    sub_agents = [sequential_deciders, fresh_dispatch_agent]

    # Optional extension: webtoon storyline planning + iterative refinement loop.
    if enable_storyline:
        sub_agents.append(create_storyline_pipeline())

    # Create root agent with sequential deciders + dispatch (+ optional storyline pipeline)
    root = SequentialAgent(
        name="QueerSimRoot",
        sub_agents=sub_agents,
        description=(
            "Sequential persona agents (with shuffled order each turn) + deterministic dispatch"
            + (" + webtoon storyline planning loop" if enable_storyline else "")
        ),
    )

    return root


# Create initial root agent (will be recreated with new order each turn)
root_agent = create_root_agent_with_shuffled_order(enable_storyline=False)
