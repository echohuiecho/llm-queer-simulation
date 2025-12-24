from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from config import config

from ..tools import prepare_turn_context, retrieve_scene, plan_storyline, review_storyline, refine_storyline, exit_loop


MODEL_NAME = "gemini-2.0-flash"


def get_webtoon_goal(lang: str = None) -> str:
    """Get webtoon goal text in the specified language."""
    if lang is None:
        lang = config.get("language", "en").replace("-", "_")

    goals = {
        "en": """
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
""",
        "zh_Hans": """
目标：协作创作一个韩国风格的垂直滚动网络漫画（适合无限滚动）
关于两个男性化女同性恋者。为每个场景生成清晰的故事情节，包含垂直堆叠的面板。

硬性要求：
- 恰好2个主要角色（都是男性化女同性恋者），每个都有姓名、描述、视觉描述。
- 故事结构为剧集/场景，每个场景有多个垂直面板。
- 每个面板必须有对话。对话可以是：
  * 口语对话："角色名：[他们说的话]"
  * 内心独白："（内心独白）[想法]"
  * 动作/叙述："（叙述）[描述]"
  * 空字符串仅用于真正沉默的时刻（谨慎使用，每个场景最多1-2个面板）。
- 保持接地气、情感连贯，场景之间的进展合理。
- 想法可以受到当前对话+任何检索到的上下文（字幕/帧）的启发。
""",
        "zh_Hant": """
目標：協作創作一個韓國風格的垂直滾動網絡漫畫（適合無限滾動）
關於兩個男性化女同性戀者。為每個場景生成清晰的故事情節，包含垂直堆疊的面板。

硬性要求：
- 恰好2個主要角色（都是男性化女同性戀者），每個都有姓名、描述、視覺描述。
- 故事結構為劇集/場景，每個場景有多個垂直面板。
- 每個面板必須有對話。對話可以是：
  * 口語對話："角色名：[他們說的話]"
  * 內心獨白："（內心獨白）[想法]"
  * 動作/敘述："（敘述）[描述]"
  * 空字符串僅用於真正沉默的時刻（謹慎使用，每個場景最多1-2個面板）。
- 保持接地氣、情感連貫，場景之間的進展合理。
- 想法可以受到當前對話+任何檢索到的上下文（字幕/幀）的啟發。
"""
    }

    return goals.get(lang, goals["en"])


def create_storyline_planner() -> LlmAgent:
    """Creates the initial storyline draft (JSON) and stores it via plan_storyline tool."""
    lang = config.get("language", "en").replace("-", "_")
    webtoon_goal = get_webtoon_goal(lang)

    if lang == "zh_Hans":
        instruction = f"""
你是一个韩国风格垂直滚动网络漫画的故事规划师。

{webtoon_goal}

可用输入：
- 最新用户消息：{{new_message}}
- 最近对话摘要：{{history_summary}}

工作流程：
1) 调用 prepare_turn_context(query) 从RAG或节目上下文中提取任何相关灵感。
   使用类似这样的查询："男性化女同性恋网络漫画情节节拍、关系紧张、场景、对话"。
2) 然后调用 plan_storyline(storyline_json=...) 恰好一次，其中 storyline_json 是严格的JSON字符串。

要输出的JSON模式（严格JSON，无markdown，无注释）：
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
  "target_audience": "韩国网络漫画读者"
}}

至少制作3个场景，每个场景至少3个面板（垂直滚动感觉）。

关键：每个面板必须有对话。使用格式如：
- "Hana: [口语台词]"
- "Soo-jin: [口语台词]"
- "（内心独白）[想法]"
- "（叙述）[描述]"
仅对真正沉默的时刻使用空字符串 ""（每个场景最多1-2个面板）。

调用 plan_storyline 后，不要输出任何其他内容。
"""
    elif lang == "zh_Hant":
        instruction = f"""
你是一個韓國風格垂直滾動網絡漫畫的故事規劃師。

{webtoon_goal}

可用輸入：
- 最新用戶消息：{{new_message}}
- 最近對話摘要：{{history_summary}}

工作流程：
1) 調用 prepare_turn_context(query) 從RAG或節目上下文中提取任何相關靈感。
   使用類似這樣的查詢："男性化女同性戀網絡漫畫情節節拍、關係緊張、場景、對話"。
2) 然後調用 plan_storyline(storyline_json=...) 恰好一次，其中 storyline_json 是嚴格的JSON字符串。

要輸出的JSON模式（嚴格JSON，無markdown，無註釋）：
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
  "target_audience": "韓國網絡漫畫讀者"
}}

至少製作3個場景，每個場景至少3個面板（垂直滾動感覺）。

關鍵：每個面板必須有對話。使用格式如：
- "Hana: [口語台詞]"
- "Soo-jin: [口語台詞]"
- "（內心獨白）[想法]"
- "（敘述）[描述]"
僅對真正沉默的時刻使用空字符串 ""（每個場景最多1-2個面板）。

調用 plan_storyline 後，不要輸出任何其他內容。
"""
    else:  # English
        instruction = f"""
You are a story planner for a Korean-style vertical-scroll webtoon.

{webtoon_goal}

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
"""

    return LlmAgent(
        name="StorylinePlanner",
        model=MODEL_NAME,
        description="Generates an initial webtoon storyline draft as JSON and stores it.",
        instruction=instruction,
        tools=[prepare_turn_context, retrieve_scene, plan_storyline],
    )


def create_storyline_reviewer() -> LlmAgent:
    """Reviews storyline quality and exits loop when it passes."""
    lang = config.get("language", "en").replace("-", "_")
    webtoon_goal = get_webtoon_goal(lang)

    if lang == "zh_Hans":
        instruction = f"""
你是一个网络漫画故事情节质量审查员。

{webtoon_goal}

你必须：
1) 调用 review_storyline(storyline_json=...) 使用状态中的当前故事情节JSON：
   使用 {{current_storyline_json}} 作为参数。
2) 如果工具结果是通过：调用 exit_loop() 并回复：
   "故事情节满足所有要求。退出细化循环。"
3) 如果失败：输出简洁的可操作反馈（1-6个要点）关于下一步要修复的内容。

重要：检查大多数面板是否有对话。如果太多面板有空对话，提供反馈以添加对话（口语台词、内心独白或叙述）。

不要添加额外的散文。要么调用 exit_loop 并返回完成消息，要么提供反馈。
"""
    elif lang == "zh_Hant":
        instruction = f"""
你是一個網絡漫畫故事情節質量審查員。

{webtoon_goal}

你必須：
1) 調用 review_storyline(storyline_json=...) 使用狀態中的當前故事情節JSON：
   使用 {{current_storyline_json}} 作為參數。
2) 如果工具結果是通過：調用 exit_loop() 並回復：
   "故事情節滿足所有要求。退出細化循環。"
3) 如果失敗：輸出簡潔的可操作反饋（1-6個要點）關於下一步要修復的內容。

重要：檢查大多數面板是否有對話。如果太多面板有空對話，提供反饋以添加對話（口語台詞、內心獨白或敘述）。

不要添加額外的散文。要麼調用 exit_loop 並返回完成消息，要麼提供反饋。
"""
    else:  # English
        instruction = f"""
You are a webtoon storyline quality reviewer.

{webtoon_goal}

You must:
1) Call review_storyline(storyline_json=...) using the current storyline JSON from state:
   Use {{current_storyline_json}} as the argument.
2) If the tool result is pass: call exit_loop() and respond with:
   "Storyline meets all requirements. Exiting the refinement loop."
3) If fail: output concise actionable feedback (1-6 bullet points) about what to fix next.

IMPORTANT: Check that most panels have dialogue. If too many panels have empty dialogue, provide feedback to add dialogue (spoken lines, internal monologue, or narration).

Do not add extra prose. Either call exit_loop and return the completion message OR provide feedback.
"""

    return LlmAgent(
        name="StorylineReviewer",
        model=MODEL_NAME,
        description="Reviews the current storyline JSON for structural quality; exits loop when ready.",
        instruction=instruction,
        tools=[review_storyline, exit_loop],
        output_key="review_feedback",
    )


def create_storyline_refiner() -> LlmAgent:
    """Refines storyline JSON based on review feedback."""
    lang = config.get("language", "en").replace("-", "_")
    webtoon_goal = get_webtoon_goal(lang)

    if lang == "zh_Hans":
        instruction = f"""
你细化一个网络漫画故事情节JSON。

{webtoon_goal}

输入：
- 当前故事情节JSON：{{current_storyline_json}}
- 审查反馈：{{review_feedback}}
- 剧集进度摘要：{{episode_progress}}

任务：
- 应用反馈并改进故事情节。
- 保持严格的JSON匹配模式。
- 保持恰好2个主要角色。
- 确保场景/面板适合网络漫画（垂直堆叠）。
- 关键：确保每个面板都有对话。使用格式如"角色：[台词]"、"（内心独白）[想法]"或"（叙述）[文本]"。仅对真正沉默的时刻使用""（每个场景最多1-2个）。
- 关键：细化时，你必须在JSON输出中包含所有剧集的所有现有场景。不要删除已完成剧集或当前剧集的场景。系统会保留它们，但你应该包含它们以保持故事连续性。
- 关键：如果当前剧集有≥3个场景且面板质量良好，考虑提议完成该剧集并开始下一剧集。

输出说明：
1) 仅生成严格的JSON字符串。
2) 然后恰好调用一次 refine_storyline(storyline_json=...)。
3) 不要输出任何其他内容。
"""
    elif lang == "zh_Hant":
        instruction = f"""
你細化一個網絡漫畫故事情節JSON。

{webtoon_goal}

輸入：
- 當前故事情節JSON：{{current_storyline_json}}
- 審查反饋：{{review_feedback}}
- 劇集進度摘要：{{episode_progress}}

任務：
- 應用反饋並改進故事情節。
- 保持嚴格的JSON匹配模式。
- 保持恰好2個主要角色。
- 確保場景/面板適合網絡漫畫（垂直堆疊）。
- 關鍵：確保每個面板都有對話。使用格式如"角色：[台詞]"、"（內心獨白）[想法]"或"（敘述）[文本]"。僅對真正沉默的時刻使用""（每個場景最多1-2個）。
- 關鍵：細化時，你必須在JSON輸出中包含所有劇集的所有現有場景。不要刪除已完成劇集或當前劇集的場景。系統會保留它們，但你應該包含它們以保持故事連續性。
- 關鍵：如果當前劇集有≥3個場景且面板質量良好，考慮提議完成該劇集並開始下一劇集。

輸出說明：
1) 僅生成嚴格的JSON字符串。
2) 然後恰好調用一次 refine_storyline(storyline_json=...)。
3) 不要輸出任何其他內容。
"""
    else:  # English
        instruction = f"""
You refine a webtoon storyline JSON.

{webtoon_goal}

Inputs:
- Current storyline JSON: {{current_storyline_json}}
- Review feedback: {{review_feedback}}
- Episode progress summary: {{episode_progress}}

Task:
- Apply the feedback and improve the storyline.
- Keep it STRICT JSON matching the schema.
- Maintain exactly 2 main characters.
- Ensure scenes/panels are webtoon-friendly (vertical stacking).
- CRITICAL: Ensure every panel has dialogue. Use formats like "Character: [line]", "(Internal monologue) [thought]", or "(Narration) [text]". Only use "" for truly silent moments (max 1-2 per scene).
- CRITICAL: When refining, you MUST include ALL existing scenes from ALL episodes in your JSON output. Do NOT remove scenes from completed episodes or the current episode. The system will preserve them, but you should include them to maintain story continuity.
- CRITICAL: If the current episode has ≥3 scenes with good panels, consider proposing it complete and starting the next episode.

Output instructions:
1) Produce STRICT JSON string only.
2) Then call refine_storyline(storyline_json=...) exactly once.
3) Do not output anything else.
"""

    return LlmAgent(
        name="StorylineRefiner",
        model=MODEL_NAME,
        description="Refines the current storyline JSON based on review feedback.",
        instruction=instruction,
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


def create_storyline_plan_only_pipeline() -> SequentialAgent:
    """Planner only (no reviewer/refiner loop). Used to reliably create v1 quickly."""
    return SequentialAgent(
        name="WebtoonStorylinePlanOnly",
        sub_agents=[create_storyline_planner()],
        description="Creates an initial webtoon storyline draft (planner only).",
    )


