from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent

from ..tools import prepare_turn_context, retrieve_scene, plan_storyline, review_storyline, refine_storyline, exit_loop


MODEL_NAME = "gemini-2.0-flash"


WEBTOON_GOAL = """
Goal: collaboratively create a Korean-style vertical-scroll webtoon (doom-scroll friendly)
about two masc lesbians. Produce a clear storyline with vertically-stacked panels per scene.

Hard requirements:
- Exactly 2 main characters (both masc lesbians), each with name, description, visual_description.
- Story is structured as episodes/scenes with multiple vertical panels.
- Each panel MUST have dialogue. Dialogue can be:
  * Spoken dialogue: "Character name: [what they say]"
  * Internal monologue: "(Internal monologue) [thought]"
  * Action/narration: "(Narration) [description]"
  * Empty string ONLY for truly silent moments (use sparingly, max 1-2 panels per scene).
- Keep it grounded, emotionally coherent, and scene-to-scene progression makes sense.
- Ideas can be inspired by the current conversation + any retrieved context (subtitles/frames).
"""


def create_storyline_planner() -> LlmAgent:
    """Creates the initial storyline draft (JSON) and stores it via plan_storyline tool."""
    return LlmAgent(
        name="StorylinePlanner",
        model=MODEL_NAME,
        description="Generates an initial webtoon storyline draft as JSON and stores it.",
        instruction=f"""
You are a story planner for a Korean-style vertical-scroll webtoon.

{WEBTOON_GOAL}

Inputs available:
- Latest user message: {{new_message}}
- Recent conversation summary: {{history_summary}}

Workflow:
1) Call prepare_turn_context(query) to pull any relevant inspiration from RAG or show context.
   Use a query like: "masc lesbian webtoon plot beats, relationship tension, scenes, dialogue".
2) Then CALL plan_storyline(storyline_json=...) exactly once, where storyline_json is a STRICT JSON string.

JSON schema to output (STRICT JSON, no markdown, no comments):
{{
  "title": "...",
  "characters": [
    {{"name":"...","description":"...","visual_description":"..."}},
    {{"name":"...","description":"...","visual_description":"..."}}
  ],
  "scenes": [
    {{
      "episode": 1,
      "scene_number": 1,
      "summary": "...",
      "panels": [
        {{"panel_number": 1, "visual_description": "...", "dialogue": "...", "mood": "..." }},
        {{"panel_number": 2, "visual_description": "...", "dialogue": "...", "mood": "..." }},
        {{"panel_number": 3, "visual_description": "...", "dialogue": "...", "mood": "..." }}
      ]
    }}
  ],
  "overall_theme": "...",
  "target_audience": "Korean webtoon readers"
}}

Make at least 3 scenes, each with at least 3 panels (vertical scroll feel).

CRITICAL: Every panel MUST have dialogue. Use formats like:
- "Hana: [spoken line]"
- "Soo-jin: [spoken line]"
- "(Internal monologue) [thought]"
- "(Narration) [description]"
Only use empty string "" for truly silent moments (max 1-2 per scene).

After calling plan_storyline, do NOT output anything else.
""",
        tools=[prepare_turn_context, retrieve_scene, plan_storyline],
    )


def create_storyline_reviewer() -> LlmAgent:
    """Reviews storyline quality and exits loop when it passes."""
    return LlmAgent(
        name="StorylineReviewer",
        model=MODEL_NAME,
        description="Reviews the current storyline JSON for structural quality; exits loop when ready.",
        instruction=f"""
You are a webtoon storyline quality reviewer.

{WEBTOON_GOAL}

You must:
1) Call review_storyline(storyline_json=...) using the current storyline JSON from state:
   Use {{current_storyline_json}} as the argument.
2) If the tool result is pass: call exit_loop() and respond with:
   "Storyline meets all requirements. Exiting the refinement loop."
3) If fail: output concise actionable feedback (1-6 bullet points) about what to fix next.

IMPORTANT: Check that most panels have dialogue. If too many panels have empty dialogue, provide feedback to add dialogue (spoken lines, internal monologue, or narration).

Do not add extra prose. Either call exit_loop and return the completion message OR provide feedback.
""",
        tools=[review_storyline, exit_loop],
        output_key="review_feedback",
    )


def create_storyline_refiner() -> LlmAgent:
    """Refines storyline JSON based on review feedback."""
    return LlmAgent(
        name="StorylineRefiner",
        model=MODEL_NAME,
        description="Refines the current storyline JSON based on review feedback.",
        instruction=f"""
You refine a webtoon storyline JSON.

{WEBTOON_GOAL}

Inputs:
- Current storyline JSON: {{current_storyline_json}}
- Review feedback: {{review_feedback}}

Task:
- Apply the feedback and improve the storyline.
- Keep it STRICT JSON matching the schema.
- Maintain exactly 2 main characters.
- Ensure scenes/panels are webtoon-friendly (vertical stacking).
- CRITICAL: Ensure every panel has dialogue. Use formats like "Character: [line]", "(Internal monologue) [thought]", or "(Narration) [text]". Only use "" for truly silent moments (max 1-2 per scene).

Output instructions:
1) Produce STRICT JSON string only.
2) Then call refine_storyline(storyline_json=...) exactly once.
3) Do not output anything else.
""",
        tools=[refine_storyline],
    )


def create_storyline_planning_loop() -> LoopAgent:
    """Loop: reviewer -> refiner until reviewer calls exit_loop."""
    return LoopAgent(
        name="StorylinePlanningLoop",
        max_iterations=5,  # Reduced from 10 to speed up execution
        sub_agents=[create_storyline_reviewer(), create_storyline_refiner()],
        description="Iteratively reviews and refines the webtoon storyline until quality requirements are met.",
    )


def create_storyline_pipeline() -> SequentialAgent:
    """Planner first, then refinement loop."""
    return SequentialAgent(
        name="WebtoonStorylinePipeline",
        sub_agents=[create_storyline_planner(), create_storyline_planning_loop()],
        description="Generates and refines a webtoon storyline through an iterative review process.",
    )


