#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@Time    : 2026-05-11
@Author  : Levi Fang 000592
@File    : wechat_article_client.py
@Desc    : WeChat Official Account article search client via wechat-article-exporter API
"""
import traceback
from typing import Dict, List, Any, Optional

import requests

from utils.klogger_util import logger


class WechatArticleClient:
    """Client for wechat-article-exporter API (https://down.mptext.top)"""

    def __init__(self, api_base_url: str, api_key: str, timeout: int = 15) -> None:
        """
        Initialize WeChat Article client.

        :param api_base_url: Base URL of the exporter API
        :param api_key: X-Auth-Key for authentication
        :param timeout: Request timeout in seconds
        """
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.headers = {"X-Auth-Key": api_key}

        logger.info(f"WechatArticleClient initialized, base_url={self.api_base_url}")

    def verify_key(self) -> bool:
        """Verify if the API key is still valid."""
        try:
            resp = requests.get(
                f"{self.api_base_url}/api/public/v1/authkey",
                headers=self.headers,
                timeout=self.timeout
            )
            data = resp.json()
            return data.get("code") == 0
        except Exception:
            return False

    def search_accounts(self, keyword: str) -> List[Dict[str, Any]]:
        """
        Search WeChat official accounts by keyword.

        :param keyword: Account name keyword
        :return: List of account dicts with fakeid, nickname, alias, signature, etc.
        """
        try:
            resp = requests.get(
                f"{self.api_base_url}/api/public/v1/account",
                params={"keyword": keyword},
                headers=self.headers,
                timeout=self.timeout
            )
            data = resp.json()

            if data.get("base_resp", {}).get("ret") != 0:
                logger.warning(
                    f"WeChat account search failed, keyword={keyword}, "
                    f"resp={data}"
                )
                return []

            accounts = data.get("list", [])
            logger.info(
                f"WeChat account search completed, keyword={keyword}, "
                f"returned={len(accounts)}"
            )
            return accounts

        except Exception:
            logger.error(
                f"WeChat account search error, keyword={keyword}, "
                f"error: {traceback.format_exc()}"
            )
            return []

    def get_articles(
        self,
        fakeid: str,
        begin: int = 0,
        size: int = 20,
        keyword: str = ""
    ) -> Dict[str, Any]:
        """
        Get article list for a specific official account.

        :param fakeid: Account's fakeid from search results
        :param begin: Pagination offset
        :param size: Page size (max 20)
        :param keyword: Optional title keyword filter
        :return: Dict with articles list and pagination info
        """
        try:
            params = {
                "fakeid": fakeid,
                "begin": begin,
                "size": min(size, 20),
            }
            if keyword:
                params["keyword"] = keyword

            resp = requests.get(
                f"{self.api_base_url}/api/public/v1/article",
                params=params,
                headers=self.headers,
                timeout=self.timeout
            )
            data = resp.json()

            if data.get("base_resp", {}).get("ret") != 0:
                logger.warning(
                    f"WeChat article list failed, fakeid={fakeid}, "
                    f"resp={data}"
                )
                return {"articles": [], "total": 0}

            articles = data.get("articles", []) or data.get("list", [])
            total = data.get("total", len(articles))

            logger.info(
                f"WeChat article list completed, fakeid={fakeid}, "
                f"begin={begin}, returned={len(articles)}, total={total}"
            )
            return {"articles": articles, "total": total}

        except Exception:
            logger.error(
                f"WeChat article list error, fakeid={fakeid}, "
                f"error: {traceback.format_exc()}"
            )
            return {"articles": [], "total": 0}

    def get_article_content(
        self,
        url: str,
        format: str = "markdown"
    ) -> Optional[str]:
        """
        Download article content by URL.

        :param url: WeChat article URL
        :param format: Output format: html / markdown / text / json
        :return: Article content string or None
        """
        try:
            resp = requests.get(
                f"{self.api_base_url}/api/public/v1/download",
                params={"url": url, "format": format},
                headers=self.headers,
                timeout=30  # Article download may take longer
            )

            if resp.status_code == 200:
                return resp.text
            else:
                logger.warning(
                    f"WeChat article download failed, url={url[:80]}, "
                    f"status={resp.status_code}"
                )
                return None

        except Exception:
            logger.error(
                f"WeChat article download error, url={url[:80]}, "
                f"error: {traceback.format_exc()}"
            )
            return None
