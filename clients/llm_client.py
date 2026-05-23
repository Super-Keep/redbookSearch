#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@Time    : 2026-03-19
@Author  : Levi Fang 000592
@File    : llm_client.py
@Desc    : LLM API client with retry logic for intelligence briefing generation
"""
import os
import sys
import traceback
from typing import Dict, Any, Optional

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from utils.klogger_util import logger
from utils.retry_util import retry_api_call
from config.config import CONFIG


class LLMClient:
    """Client for LLM API with retry logic"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = None,
        max_tokens: int = None
    ) -> None:
        """
        Initialize LLM API client
        
        :param api_key: LLM API key (defaults to config)
        :param api_url: LLM API endpoint URL (defaults to config)
        :param model: LLM model name (defaults to config)
        :param timeout: Request timeout in seconds
        :param max_tokens: Maximum tokens in response
        """
        self.model = model
        self.timeout = timeout or int(getattr(CONFIG.LLM_CONFIG, 'TIMEOUT', 300))
        self.max_tokens = max_tokens or int(getattr(CONFIG.LLM_CONFIG, 'MAX_TOKEN', 16000))
        self.llm = self.llm_init()
        
        logger.info(
            f"LLMClient initialized with model={self.model}, "
            f"timeout={self.timeout}s, max_tokens={self.max_tokens}"
        )
    
    def llm_init(self) -> ChatOpenAI:
        """
        Initialize ChatOpenAI instance
        
        :return: ChatOpenAI instance
        """
        llm = ChatOpenAI(
            model=CONFIG.LLM_CONFIG.MODEL,
            temperature=0,
            streaming=False,
            max_tokens=self.max_tokens,
            timeout=self.timeout
        )
        return llm
    
    def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7
    ) -> str:
        """
        Generate completion using LLM
        
        :param prompt: User prompt
        :param system_prompt: System prompt (optional)
        :param temperature: Temperature for generation (0.0-1.0)
        :return: Generated text
        """
        try:
            # Create messages
            messages = []
            
            if system_prompt:
                messages.append(SystemMessage(content=system_prompt))
            
            messages.append(HumanMessage(content=prompt))
            
            # Update temperature for this call
            self.llm.temperature = temperature
            
            # Invoke LLM
            logger.info(
                f"Calling LLM with prompt_length={len(prompt)}, "
                f"temperature={temperature}"
            )
            
            response = self.llm.invoke(messages)
            
            # Extract content from response
            result = response.content if hasattr(response, 'content') else str(response)
            
            logger.info(
                f"LLM response received, "
                f"response_length={len(result)}"
            )
            
            return result
            
        except Exception as e:
            logger.error(
                f"LLM completion failed, "
                f"prompt_length={len(prompt) if prompt else 0}, "
                f"error: {traceback.format_exc()}"
            )
            raise
 