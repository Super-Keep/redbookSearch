#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@Time    : 2026-05-25
@Author  : AI Assistant
@File    : cookie_fetcher.py
@Desc    : Auto-fetch XHS cookies by opening a browser for user login
"""
import os
import sys
import json
import traceback
from typing import Optional

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.klogger_util import logger

# Local settings path
_LOCAL_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'config', 'local_settings.json'
)


def fetch_xhs_cookie_via_browser(headless: bool = False, timeout: int = 120) -> Optional[str]:
    """
    Open a browser window for user to login to Xiaohongshu,
    then automatically extract cookies after login.

    :param headless: Whether to run headless (False = show browser window)
    :param timeout: Max seconds to wait for login (default 120s)
    :return: Cookie string or None if failed/timeout
    """
    try:
        from playwright.sync_api import sync_playwright

        logger.info("Starting browser for XHS cookie fetch...")

        with sync_playwright() as p:
            # Launch visible browser for user to login
            browser = p.chromium.launch(
                headless=headless,
                args=['--disable-blink-features=AutomationControlled']
            )

            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/121.0.0.0 Safari/537.36"
                )
            )

            page = context.new_page()

            # Navigate to XHS login page
            page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded")

            logger.info("Browser opened, waiting for user to login...")

            # Poll for web_session cookie (httpOnly cookies can't be read by JS)
            import time
            start_time = time.time()
            logged_in = False

            while time.time() - start_time < timeout:
                cookies = context.cookies("https://www.xiaohongshu.com")
                cookie_names = [c['name'] for c in cookies]
                if 'web_session' in cookie_names:
                    logged_in = True
                    time.sleep(2)  # Wait a moment for all cookies to settle
                    break
                time.sleep(2)  # Check every 2 seconds

            if not logged_in:
                logger.warning("Login timeout - web_session not found")

            # Extract all cookies
            cookies = context.cookies("https://www.xiaohongshu.com")

            if not cookies:
                logger.warning("No cookies found after login attempt")
                browser.close()
                return None

            # Format cookies as string
            cookie_str = "; ".join(
                f"{c['name']}={c['value']}" for c in cookies
            )

            # Verify we got the essential cookies
            essential_cookies = ['a1', 'web_session', 'webId']
            found = [name for name in essential_cookies if name + "=" in cookie_str]

            if 'web_session' not in found:
                logger.warning(
                    f"Cookie incomplete - missing web_session. "
                    f"Found: {found}. User may not have logged in."
                )
                browser.close()
                return None

            browser.close()

            logger.info(
                f"XHS cookies fetched successfully, "
                f"length={len(cookie_str)}, essential_found={found}"
            )
            return cookie_str

    except ImportError:
        logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
        return None
    except Exception:
        logger.error(f"Cookie fetch failed: {traceback.format_exc()}")
        return None


def fetch_and_save_xhs_cookie(headless: bool = False, timeout: int = 120) -> dict:
    """
    Fetch XHS cookie via browser and save to local_settings.json.

    :param headless: Whether to run headless
    :param timeout: Max seconds to wait
    :return: Dict with success status and message
    """
    cookie_str = fetch_xhs_cookie_via_browser(headless=headless, timeout=timeout)

    if not cookie_str:
        return {
            "success": False,
            "message": "获取Cookie失败，请确保已完成登录"
        }

    # Save to local_settings.json
    try:
        settings = {}
        if os.path.exists(_LOCAL_SETTINGS_PATH):
            with open(_LOCAL_SETTINGS_PATH, 'r', encoding='utf-8') as f:
                settings = json.load(f)

        settings["xhs_cookies"] = cookie_str

        os.makedirs(os.path.dirname(_LOCAL_SETTINGS_PATH), exist_ok=True)
        with open(_LOCAL_SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)

        logger.info("XHS cookie saved to local_settings.json")
        return {
            "success": True,
            "message": f"Cookie获取成功（长度: {len(cookie_str)}）",
            "cookie_length": len(cookie_str)
        }

    except Exception:
        logger.error(f"Save cookie failed: {traceback.format_exc()}")
        return {
            "success": False,
            "message": "Cookie获取成功但保存失败"
        }
