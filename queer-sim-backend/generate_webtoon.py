#!/usr/bin/env python3
"""
Webtoon Image Generation Script

Generates images for webtoon episodes in vertical webtoon format.
Each panel is generated separately and then combined vertically.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from io import BytesIO
import asyncio

try:
    from google import genai
    from google.genai import types
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    print(f"Missing required package: {e}")
    print("Please install: pip install google-genai pillow")
    sys.exit(1)

from config import config


class WebtoonImageGenerator:
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the image generator with Gemini API."""
        self.api_key = api_key or config.get("google_api_key")

        if not self.api_key:
            raise ValueError("Google API key is required. Set it in config.json or GOOGLE_API_KEY env var.")

        self.client = genai.Client(api_key=self.api_key)
        self.output_dir = Path("webtoon_output")
        self.output_dir.mkdir(exist_ok=True)

    def build_panel_prompt(self, panel: Dict[str, Any], characters: List[Dict[str, Any]]) -> str:
        """Build a detailed prompt for image generation from panel data."""
        visual_desc = panel.get("visual_description", "")
        mood = panel.get("mood", "")
        dialogue = panel.get("dialogue", "")

        # Build character descriptions
        char_descriptions = []
        for char in characters:
            name = char.get("name", "")
            desc = char.get("visual_description", "")
            if name and desc:
                char_descriptions.append(f"{name}: {desc}")

        char_context = "\n".join(char_descriptions) if char_descriptions else ""

        # Build the prompt
        prompt_parts = [
            "A webtoon panel in Korean webtoon style,",
            "vertical format, high quality, detailed illustration.",
        ]

        if char_context:
            prompt_parts.append(f"\nCharacter descriptions:\n{char_context}")

        prompt_parts.append(f"\nVisual description: {visual_desc}")

        if mood:
            prompt_parts.append(f"\nMood: {mood}")

        if dialogue:
            # Note: We'll add dialogue as text overlay later, but mention it in the prompt
            prompt_parts.append(f"\nNote: Dialogue will be added as text overlay: {dialogue}")

        prompt_parts.append("\nStyle: Korean webtoon, clean lines, expressive characters, cinematic composition.")

        return " ".join(prompt_parts)

    async def generate_panel_image(self, panel: Dict[str, Any], characters: List[Dict[str, Any]],
                                   episode_num: int, scene_num: int, panel_num: int) -> Image.Image:
        """Generate a single panel image using Gemini."""
        prompt = self.build_panel_prompt(panel, characters)

        print(f"Generating panel {episode_num}-{scene_num}-{panel_num}...")
        print(f"Prompt: {prompt[:200]}...")

        try:
            # Use Gemini 3 Pro Image Preview for image generation
            parts = [types.Part.from_text(text=prompt)]
            contents = [
                types.Content(
                    role="user",
                    parts=parts,
                ),
            ]

            generate_content_config = types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                temperature=0.8,
            )

            image_bytes = None
            chunk_count = 0
            print("Processing Gemini response stream...")

            # Generate image using streaming API
            for chunk in self.client.models.generate_content_stream(
                model="gemini-3-pro-image-preview",
                contents=contents,
                config=generate_content_config,
            ):
                chunk_count += 1
                if hasattr(chunk, 'candidates') and chunk.candidates:
                    for candidate in chunk.candidates:
                        if hasattr(candidate, 'content') and candidate.content:
                            for part in candidate.content.parts:
                                if hasattr(part, 'inline_data') and part.inline_data:
                                    image_bytes = part.inline_data.data
                                    print(f"Found image data in chunk {chunk_count} (size: {len(image_bytes)} bytes)")
                                    break
                        if image_bytes:
                            break
                if image_bytes:
                    break

            if not image_bytes:
                raise ValueError("No image data received from Gemini")

            # Convert bytes to PIL Image
            image = Image.open(BytesIO(image_bytes))

            # Convert to RGB if needed
            if image.mode != "RGB":
                image = image.convert("RGB")

            return image

        except Exception as e:
            print(f"Error generating image: {e}")
            import traceback
            traceback.print_exc()
            # Return a placeholder image
            placeholder = Image.new("RGB", (1024, 1024), color=(240, 240, 240))
            draw = ImageDraw.Draw(placeholder)
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 40)
            except:
                font = ImageFont.load_default()
            draw.text((512, 512), f"Error: {str(e)[:50]}", fill=(100, 100, 100), anchor="mm", font=font)
            return placeholder

    def add_dialogue_to_panel(self, image: Image.Image, dialogue: str) -> Image.Image:
        """Add dialogue text to a panel image."""
        if not dialogue or dialogue.strip() == "":
            return image

        # Create a copy to avoid modifying the original
        img = image.copy()
        draw = ImageDraw.Draw(img)

        # Try to load a nice font, fallback to default
        try:
            # Try different font paths
            font_paths = [
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
            font = None
            for path in font_paths:
                if os.path.exists(path):
                    font = ImageFont.truetype(path, 32)
                    break
            if font is None:
                font = ImageFont.load_default()
        except:
            font = ImageFont.load_default()

        # Calculate text size and position
        # For webtoon, dialogue is usually at the bottom or in a speech bubble area
        width, height = img.size

        # Create a semi-transparent background for text
        text_padding = 20
        text_height = 80

        # Draw text background
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle(
            [(0, height - text_height - text_padding), (width, height)],
            fill=(0, 0, 0, 200)
        )
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

        # Draw text
        text_y = height - text_height // 2 - text_padding // 2
        draw.text(
            (width // 2, text_y),
            dialogue,
            fill=(255, 255, 255),
            anchor="mm",
            font=font,
            align="center"
        )

        return img

    def resize_panel_for_webtoon(self, image: Image.Image, target_width: int = 800) -> Image.Image:
        """Resize panel to webtoon format (vertical, consistent width)."""
        width, height = image.size

        # Calculate new dimensions maintaining aspect ratio
        aspect_ratio = height / width
        new_width = target_width
        new_height = int(target_width * aspect_ratio)

        # Resize with high quality
        resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        return resized

    async def generate_episode(self, episode_data: Dict[str, Any], output_filename: Optional[str] = None):
        """Generate all panels for an episode and combine them vertically."""
        title = episode_data.get("title", "Untitled")
        characters = episode_data.get("characters", [])
        scenes = episode_data.get("scenes", [])
        episode_num = scenes[0].get("episode", 1) if scenes else 1

        print(f"\n{'='*60}")
        print(f"Generating Episode {episode_num}: {title}")
        print(f"{'='*60}\n")

        all_panels = []

        # Generate all panels
        for scene in scenes:
            scene_num = scene.get("scene_number", 1)
            panels = scene.get("panels", [])

            print(f"\nScene {scene_num}: {scene.get('summary', '')}")

            for panel in panels:
                panel_num = panel.get("panel_number", 1)

                # Generate panel image
                panel_image = await self.generate_panel_image(
                    panel, characters, episode_num, scene_num, panel_num
                )

                # Add dialogue if present
                dialogue = panel.get("dialogue", "")
                if dialogue:
                    panel_image = self.add_dialogue_to_panel(panel_image, dialogue)

                # Resize for webtoon format
                panel_image = self.resize_panel_for_webtoon(panel_image, target_width=800)

                # Save individual panel
                panel_filename = self.output_dir / f"ep{episode_num}_scene{scene_num}_panel{panel_num}.png"
                panel_image.save(panel_filename, "PNG", quality=95)
                print(f"Saved: {panel_filename}")

                all_panels.append(panel_image)

        # Combine all panels vertically
        if all_panels:
            print(f"\nCombining {len(all_panels)} panels vertically...")

            # Calculate total height
            total_height = sum(panel.size[1] for panel in all_panels)
            target_width = 800

            # Create combined image
            combined = Image.new("RGB", (target_width, total_height), color=(255, 255, 255))

            # Paste panels
            y_offset = 0
            for panel in all_panels:
                combined.paste(panel, (0, y_offset))
                y_offset += panel.size[1]

            # Save combined webtoon
            if output_filename is None:
                output_filename = f"episode_{episode_num}_{title.replace(' ', '_')}.png"

            output_path = self.output_dir / output_filename
            combined.save(output_path, "PNG", quality=95)
            print(f"\n✓ Saved combined webtoon: {output_path}")
            print(f"  Dimensions: {target_width}x{total_height}")

            return output_path

        return None


async def main():
    """Main function to generate webtoon images."""
    # Episode 1 data
    episode_1 = {
        "title": "String of Pearls",
        "characters": [
            {
                "name": "Hana",
                "description": "A slightly anxious, introverted masc lesbian struggling with feelings of unworthiness.",
                "visual_description": "Short, choppy dark hair, often wears practical clothing like jeans and t-shirts. Has a small scar above her left eyebrow. Tends to have a furrowed brow and avoid direct eye contact."
            },
            {
                "name": "Soo-jin",
                "description": "A gentle, confident, and affectionate masc lesbian. Patient and understanding, but also observant.",
                "visual_description": "Longer, shaggy dark hair, often tied back loosely. Favors oversized sweaters and comfortable pants. Has a warm, comforting smile and kind eyes."
            }
        ],
        "scenes": [
            {
                "episode": 1,
                "scene_number": 1,
                "summary": "Hana is carefully misting her String of Pearls, lost in thought and self-doubt.",
                "panels": [
                    {
                        "panel_number": 1,
                        "visual_description": "Close-up of Hana's hands carefully misting a String of Pearls plant. Tiny water droplets cling to the pearls. Soft sunlight filters through the window.",
                        "dialogue": "",
                        "mood": "calm, focused"
                    },
                    {
                        "panel_number": 2,
                        "visual_description": "The camera pans up to Hana's face. She has a furrowed brow and a worried expression. Her eyes are unfocused.",
                        "dialogue": "(Internal monologue) Do I even deserve this?",
                        "mood": "anxious, vulnerable"
                    },
                    {
                        "panel_number": 3,
                        "visual_description": "Soo-jin approaches Hana from behind and gently wraps her arms around her in a back hug. Hana flinches slightly.",
                        "dialogue": "",
                        "mood": "tender, surprising"
                    }
                ]
            },
            {
                "episode": 1,
                "scene_number": 2,
                "summary": "Soo-jin comforts Hana after noticing her distress.",
                "panels": [
                    {
                        "panel_number": 1,
                        "visual_description": "Close-up of Soo-jin's arms wrapped around Hana. Soo-jin is wearing a soft, oversized sweater. Her messy hair falls slightly over Hana's shoulder. A small, comforting smile is on her face.",
                        "dialogue": "",
                        "mood": "warm, comforting"
                    },
                    {
                        "panel_number": 2,
                        "visual_description": "Hana turns her head slightly to look at Soo-jin, her expression still uncertain.",
                        "dialogue": "Hana: (softly) Soo-jin...",
                        "mood": "hesitant, questioning"
                    },
                    {
                        "panel_number": 3,
                        "visual_description": "Soo-jin nuzzles her face into Hana's neck. Her eyes are closed, and she looks peaceful. The String of Pearls hangs in the background, slightly out of focus.",
                        "dialogue": "Soo-jin: Just breathe, baby. I'm here.",
                        "mood": "reassuring, loving"
                    }
                ]
            },
            {
                "episode": 1,
                "scene_number": 3,
                "summary": "Hana and Soo-jin sit together, finding solace in each other's presence.",
                "panels": [
                    {
                        "panel_number": 1,
                        "visual_description": "Hana and Soo-jin are sitting on the couch, Soo-jin still holding Hana. The apartment is filled with soft sunlight and various plants. The color palette is muted and calming.",
                        "dialogue": "",
                        "mood": "peaceful, domestic"
                    },
                    {
                        "panel_number": 2,
                        "visual_description": "Close-up of Hana's hand resting on Soo-jin's arm. Her expression is starting to soften. She takes a deep breath.",
                        "dialogue": "(Internal monologue) Maybe... maybe I do.",
                        "mood": "hopeful, introspective"
                    },
                    {
                        "panel_number": 3,
                        "visual_description": "Wide shot of Hana and Soo-jin sitting together, framed by the plants. They are silhouetted against the window. The String of Pearls is prominently displayed.",
                        "dialogue": "",
                        "mood": "content, connected"
                    }
                ]
            }
        ],
        "overall_theme": "Overcoming self-doubt and finding love and acceptance in a relationship between two masc lesbians.",
        "target_audience": "Korean webtoon readers",
        "meta": {
            "version": 4,
            "updated_ts": 1766333561.1992462
        }
    }

    try:
        generator = WebtoonImageGenerator()
        output_path = await generator.generate_episode(episode_1)

        if output_path:
            print(f"\n{'='*60}")
            print("✓ Webtoon generation complete!")
            print(f"  Output directory: {generator.output_dir.absolute()}")
            print(f"  Main file: {output_path}")
            print(f"{'='*60}\n")
        else:
            print("Error: No panels were generated.")

    except ValueError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error generating webtoon: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

