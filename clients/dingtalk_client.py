#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@Time    : 2026-03-19
@Author  : Levi Fang 000592
@File    : dingtalk_client.py
@Desc    : DingTalk API client with signature authentication for webhook delivery
"""
import os
import sys
import time
import hmac
import hashlib
import base64
import urllib.parse
import traceback
import requests
from typing import Dict, Any, Optional

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.klogger_util import logger
from utils.retry_util import retry_webhook_call
from config.config import CONFIG


class DingTalkClient:
    """Client for DingTalk robot webhook with signature authentication"""
    
    def __init__(
        self,
        webhook_url: Optional[str] = None,
        secret: Optional[str] = None,
        timeout: int = 10
    ) -> None:
        """
        Initialize DingTalk webhook client
        
        :param webhook_url: DingTalk robot webhook URL (defaults to config)
        :param secret: DingTalk robot secret for signature (defaults to config)
        :param timeout: Request timeout in seconds
        """
        self.webhook_url = webhook_url or CONFIG.DINGTALK_CONFIG.webhook_url
        self.secret = secret or CONFIG.DINGTALK_CONFIG.secret
        self.timeout = timeout or CONFIG.DINGTALK_CONFIG.timeout
        
        if not self.webhook_url:
            raise ValueError("DingTalk webhook URL is required")
        
        if not self.secret:
            raise ValueError("DingTalk secret is required for signature authentication")
        
        logger.info(
            f"DingTalkClient initialized with "
            f"webhook_url={self._mask_webhook_url(self.webhook_url)}, "
            f"timeout={self.timeout}s"
        )
    
    def _generate_signed_url(self) -> str:
        """
        Generate signed webhook URL with timestamp and signature
        
        DingTalk requires HMAC-SHA256 signature for security:
        1. Get current timestamp (milliseconds)
        2. Create sign string: timestamp + "\n" + secret
        3. Calculate HMAC-SHA256 signature
        4. Base64 encode the signature
        5. URL encode the result
        6. Append timestamp and sign to webhook URL
        
        :return: Signed webhook URL
        """
        try:
            # Step 1: Get current timestamp in milliseconds
            timestamp = str(round(time.time() * 1000))
            
            # Step 2: Create string to sign
            string_to_sign = f'{timestamp}\n{self.secret}'
            
            # Step 3: Calculate HMAC-SHA256 signature
            secret_enc = self.secret.encode('utf-8')
            string_to_sign_enc = string_to_sign.encode('utf-8')
            hmac_code = hmac.new(
                secret_enc,
                string_to_sign_enc,
                digestmod=hashlib.sha256
            ).digest()
            
            # Step 4 & 5: Base64 encode and URL encode
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            
            # Step 6: Build final URL with signature
            final_url = f"{self.webhook_url}&timestamp={timestamp}&sign={sign}"
            
            logger.debug(
                f"Generated signed URL, timestamp={timestamp}, "
                f"sign={sign[:20]}..."
            )
            
            return final_url
            
        except Exception as e:
            logger.error(
                f"Failed to generate signed URL, "
                f"error: {traceback.format_exc()}"
            )
            raise
    
    @retry_webhook_call(max_retries=3, backoff_factor=2.0, initial_delay=2.0, max_delay=60.0)
    def send_markdown(
        self,
        title: str,
        content: str,
        at_mobiles: Optional[list] = None,
        at_all: bool = False
    ) -> bool:
        """
        Send markdown message to DingTalk group with signature authentication
        
        Sends a markdown-formatted message via DingTalk robot webhook
        with HMAC-SHA256 signature for security verification.
        
        :param title: Message title
        :param content: Markdown content
        :param at_mobiles: List of mobile numbers to @mention
        :param at_all: Whether to @all members
        :return: True if successful, False otherwise
        """
        try:
            # Generate signed URL with timestamp and signature
            signed_url = self._generate_signed_url()
            
            # Build request payload
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": content
                }
            }
            
            # Add @mentions if specified
            if at_mobiles or at_all:
                payload["at"] = {
                    "atMobiles": at_mobiles or [],
                    "isAtAll": at_all
                }
            
            headers = {
                "Content-Type": "application/json"
            }
            
            logger.info(
                f"Sending DingTalk message, "
                f"title={title}, "
                f"content_length={len(content)}, "
                f"at_mobiles={at_mobiles}, "
                f"at_all={at_all}"
            )
            
            # Make webhook request with signed URL
            response = requests.post(
                signed_url,
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            
            # Check response status
            response.raise_for_status()
            
            # Parse response
            response_data = response.json()
            
            # Check DingTalk API response
            if response_data.get('errcode') != 0:
                error_msg = response_data.get('errmsg', 'Unknown error')
                logger.error(
                    f"DingTalk API error, "
                    f"errcode={response_data.get('errcode')}, "
                    f"errmsg={error_msg}, "
                    f"title={title}"
                )
                raise DingTalkAPIException(
                    f"DingTalk API error: {error_msg} (code: {response_data.get('errcode')})"
                )
            
            logger.info(
                f"DingTalk message sent successfully, "
                f"title={title}, "
                f"content_length={len(content)}"
            )
            
            return True
            
        except requests.exceptions.Timeout as e:
            logger.error(
                f"DingTalk webhook timeout, "
                f"timeout={self.timeout}s, "
                f"title={title}, "
                f"error: {traceback.format_exc()}"
            )
            raise
            
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else None
            logger.error(
                f"DingTalk webhook HTTP error, "
                f"status_code={status_code}, "
                f"title={title}, "
                f"error: {traceback.format_exc()}"
            )
            raise
            
        except requests.exceptions.RequestException as e:
            logger.error(
                f"DingTalk webhook request failed, "
                f"title={title}, "
                f"error: {traceback.format_exc()}"
            )
            raise
            
        except DingTalkAPIException:
            # Re-raise DingTalk API exceptions without additional logging
            raise
            
        except Exception as e:
            logger.error(
                f"DingTalk message send failed unexpectedly, "
                f"title={title}, "
                f"error: {traceback.format_exc()}"
            )
            raise
    
    def _mask_webhook_url(self, url: str) -> str:
        """
        Mask webhook URL for logging security
        
        :param url: Original webhook URL
        :return: Masked URL
        """
        if not url:
            return ""
        
        # Mask access token in URL
        if "access_token=" in url:
            parts = url.split("access_token=")
            if len(parts) == 2:
                token = parts[1].split("&")[0]
                masked_token = token[:8] + "****" + token[-4:] if len(token) > 12 else "****"
                return url.replace(token, masked_token)
        
        return url


class DingTalkAPIException(Exception):
    """Exception raised for DingTalk API errors"""
    pass
