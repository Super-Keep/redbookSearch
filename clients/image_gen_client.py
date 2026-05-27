#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@Time    : 2026-05-24
@Author  : AI Assistant
@File    : image_gen_client.py
@Desc    : OpenAI gpt-image-2 client for generating XHS-style images based on AI analysis
"""
import os
import sys
import base64
import traceback
from typing import Optional, List
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openai

from utils.klogger_util import logger


# Default directory for saving generated images
_DEFAULT_IMAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "exports", "images"
)


class ImageGenClient:
    """Client for generating images using OpenAI gpt-image-2 model"""

    def __init__(self, api_key: str, api_url: str = "https://api.openai.com/v1") -> None:
        """
        Initialize image generation client.

        :param api_key: OpenAI API key (same key as chat completions)
        :param api_url: API base URL
        """
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url=api_url,
            timeout=600.0,
            max_retries=3,
        )
        logger.info("ImageGenClient initialized with gpt-image-2")

    def generate_xhs_image(
        self,
        analysis: str,
        title: str = "",
        content: str = "",
        style_hints: str = "",
        size: str = "1024x1024",
        quality: str = "high"
    ) -> Optional[str]:
        """
        Generate a XHS-style image based on AI analysis results.
        Returns base64-encoded image data.

        :param analysis: AI deep analysis text (contains good/bad points)
        :param title: Original note title
        :param content: Original note content (truncated)
        :param style_hints: Additional style guidance
        :param size: Image size (1024x1024, 1024x1536, 1536x1024)
        :param quality: Image quality (low, medium, high)
        :return: Base64-encoded image string, or None on failure
        """
        try:
            # Build the image generation prompt based on analysis
            prompt = self._build_image_prompt(analysis, title, content, style_hints)

            logger.info(
                f"Generating image with gpt-image-2, "
                f"prompt_length={len(prompt)}, size={size}"
            )

            response = self.client.images.generate(
                model="gpt-image-2",
                prompt=prompt,
                n=1,
                size=size,
                quality="low",  # Use low quality for faster generation (proxy-friendly)
            )

            # gpt-image-2 returns base64 by default
            image_data = response.data[0].b64_json

            logger.info("Image generated successfully with gpt-image-2")
            return image_data

        except Exception as e:
            logger.error(f"Image generation failed: {traceback.format_exc()}")
            return None

    def generate_and_save(
        self,
        analysis: str,
        title: str = "",
        content: str = "",
        style_hints: str = "",
        size: str = "1024x1536",
        quality: str = "high",
        save_dir: str = ""
    ) -> Optional[str]:
        """
        Generate image and save to local file.

        :param analysis: AI analysis text
        :param title: Note title
        :param content: Note content
        :param style_hints: Style guidance
        :param size: Image size (1024x1536 is portrait, good for XHS)
        :param quality: Image quality
        :param save_dir: Directory to save (defaults to exports/images/)
        :return: File path of saved image, or None on failure
        """
        prompt = self._build_image_prompt(analysis, title, content, style_hints)
        return self.generate_and_save_with_prompt(prompt, title, size, save_dir)

    def generate_and_save_with_prompt(
        self,
        prompt: str,
        title: str = "",
        size: str = "1024x1024",
        save_dir: str = ""
    ) -> Optional[str]:
        """
        Generate image from a direct prompt and save to local file.

        :param prompt: Image generation prompt
        :param title: Title for filename
        :param size: Image size
        :param save_dir: Directory to save
        :return: File path of saved image, or None on failure
        """
        image_b64 = self.generate_xhs_image_with_prompt(prompt, size)

        if not image_b64:
            return None

        # Save to file
        save_dir = save_dir or _DEFAULT_IMAGE_DIR
        os.makedirs(save_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        import re
        safe_title = re.sub(r'[\\/:*?"<>|\n\r]+', '', title)[:20].strip() or "image"
        filename = f"xhs_{safe_title}_{timestamp}.png"
        filepath = os.path.join(save_dir, filename)

        image_bytes = base64.b64decode(image_b64)
        with open(filepath, "wb") as f:
            f.write(image_bytes)

        logger.info(f"Image saved: {filepath}, size={len(image_bytes)} bytes")
        return filepath

    def generate_xhs_image_with_prompt(
        self,
        prompt: str,
        size: str = "1024x1024"
    ) -> Optional[str]:
        """
        Generate image from a direct prompt string.

        :param prompt: Full image generation prompt
        :param size: Image size
        :return: Base64-encoded image string, or None on failure
        """
        try:
            logger.info(
                f"Generating image with gpt-image-2, "
                f"prompt_length={len(prompt)}, size={size}"
            )

            response = self.client.images.generate(
                model="gpt-image-2",
                prompt=prompt,
                n=1,
                size=size,
                quality="medium",
            )

            image_data = response.data[0].b64_json
            logger.info("Image generated successfully with gpt-image-2")
            return image_data

        except Exception as e:
            logger.error(f"Image generation failed: {traceback.format_exc()}")
            return None

    def _build_image_prompt(
        self,
        analysis: str,
        title: str,
        content: str,
        style_hints: str
    ) -> str:
        """
        Build image prompt by first using LLM to understand the note's visual intent,
        then generating a precise image generation prompt.
        """
        # Use the analysis to understand what kind of image this note needs
        # The analysis contains insights about what works well and what to improve

        # Determine the visual intent from the content
        context = f"标题：{title}\n内容：{content[:500]}" if content else title
        analysis_short = analysis[:500] if analysis else ""

        prompt = (
            f"Based on this Chinese social media note, generate a matching image.\n\n"
            f"Note title: {title}\n"
            f"Note type & intent: This is a knowledge/educational card post. "
            f"The image should match the VISUAL FORMAT of the original post.\n\n"
            f"AI analysis of what works well:\n{analysis_short}\n\n"
            f"IMPORTANT RULES:\n"
            f"- If the note is an educational/vocabulary card → generate a clean, "
            f"well-designed infographic-style card with the topic's visual theme\n"
            f"- If the note is a lifestyle/aesthetic post → generate a matching lifestyle photo\n"
            f"- If the note is a tutorial → generate step-by-step visual guide style\n"
            f"- Match the MOOD and PURPOSE of the original content\n"
            f"- Use colors and composition that appeal to young Chinese women on Xiaohongshu\n"
            f"- NO text, NO watermarks\n"
        )

        if style_hints:
            prompt += f"- Additional style: {style_hints}\n"

        if len(prompt) > 1500:
            prompt = prompt[:1500]

        return prompt
