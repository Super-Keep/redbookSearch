#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@Time    : 2026-05-08
@Author  : Levi Fang 000592
@File    : xhs_client.py
@Desc    : Xiaohongshu (RED) search client based on Spider_XHS sign algorithm
"""
import os
import sys
import json
import time
import subprocess
import traceback
from typing import Dict, List, Any, Optional
from urllib.parse import urlencode

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from utils.klogger_util import logger
from config.config import CONFIG


# Sort mode mapping
SORT_MAP = {
    "general": "general",
    "hot": "popularity_descending",
    "latest": "time_descending",
}

# XHS search API endpoint
XHS_SEARCH_API = "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes"

# Base project path for locating JS sign files
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse_count(value: Any) -> int:
    """Parse count value that may be int, str like '123', or '1.7万'"""
    if isinstance(value, int):
        return value
    if not value:
        return 0
    s = str(value).strip()
    try:
        if "万" in s:
            return int(float(s.replace("万", "")) * 10000)
        return int(s)
    except (ValueError, TypeError):
        return 0


class XhsClient:
    """Xiaohongshu search client with sign algorithm integration"""

    def __init__(
        self,
        cookies: str,
        node_path: str = "node",
        timeout: int = 30
    ) -> None:
        """
        Initialize XHS client

        :param cookies: Login cookie string from browser
        :param node_path: Path to Node.js executable
        :param timeout: HTTP request timeout in seconds
        """
        self.cookies = cookies
        self.node_path = node_path
        self.timeout = timeout
        self.session = requests.Session()
        self._setup_session()

        logger.info("XhsClient initialized")

    def _setup_session(self) -> None:
        """Configure session with default headers matching XHS browser fingerprint"""
        self.session.headers.update({
            "authority": "edith.xiaohongshu.com",
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "cache-control": "no-cache",
            "content-type": "application/json;charset=UTF-8",
            "origin": "https://www.xiaohongshu.com",
            "pragma": "no-cache",
            "referer": "https://www.xiaohongshu.com/",
            "sec-ch-ua": '"Not A(Brand";v="99", "Microsoft Edge";v="121", "Chromium";v="121"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0"
            ),
            "x-b3-traceid": self._generate_trace_id(),
            "x-mns": "unload",
            "Cookie": self.cookies,
        })

    def search(
        self,
        keyword: str,
        num: int = 20,
        sort: str = "general"
    ) -> List[Dict[str, Any]]:
        """
        Search Xiaohongshu notes by keyword

        :param keyword: Search keyword
        :param num: Number of results to return (1-50)
        :param sort: Sort mode: general / hot / latest
        :return: List of note dicts with title, content, note_url, author, likes, published_at
        """
        num = max(1, min(num, 50))
        sort_value = SORT_MAP.get(sort, "general")
        all_notes: List[Dict[str, Any]] = []
        page = 1
        page_size = 20

        try:
            while len(all_notes) < num:
                notes = self._search_page(keyword, page, page_size, sort_value)
                if not notes:
                    break
                all_notes.extend(notes)
                page += 1
                # Rate limiting between pages
                time.sleep(1)

            result = all_notes[:num]
            logger.info(
                f"XHS search completed, keyword={keyword}, "
                f"requested={num}, returned={len(result)}"
            )
            return result

        except Exception:
            logger.error(
                f"XHS search failed, keyword={keyword}, "
                f"error: {traceback.format_exc()}"
            )
            raise

    def _search_page(
        self,
        keyword: str,
        page: int,
        page_size: int,
        sort_value: str
    ) -> List[Dict[str, Any]]:
        """
        Search a single page of results

        :param keyword: Search keyword
        :param page: Page number (1-based)
        :param page_size: Results per page
        :param sort_value: Sort parameter value
        :return: List of parsed note dicts
        """
        payload = {
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
            "search_id": self._generate_search_id(),
            "sort": sort_value,
            "note_type": 0,  # 0=all, 1=image, 2=video
        }

        # Generate sign parameters
        sign_params = self._generate_sign("/api/sns/web/v1/search/notes", payload)
        if not sign_params:
            logger.error("Failed to generate XHS sign parameters")
            return []

        # Update headers with sign
        headers = {**self.session.headers, **sign_params}

        try:
            response = self.session.post(
                XHS_SEARCH_API,
                json=payload,
                headers=headers,
                timeout=self.timeout
            )

            if response.status_code == 461:
                raise XhsCookieExpiredError("XHS cookie expired, need to refresh")

            if response.status_code != 200:
                logger.warning(
                    f"XHS search API returned status={response.status_code}, "
                    f"body={response.text[:200]}"
                )
                return []

            data = response.json()
            return self._parse_search_response(data)

        except XhsCookieExpiredError:
            raise
        except requests.Timeout:
            logger.error(f"XHS search request timeout, page={page}")
            return []
        except Exception:
            logger.error(
                f"XHS search page request failed, page={page}, "
                f"error: {traceback.format_exc()}"
            )
            return []

    def _generate_sign(
        self,
        api_path: str,
        payload: Dict[str, Any]
    ) -> Optional[Dict[str, str]]:
        """
        Generate x-s, x-t sign parameters by calling Node.js script

        :param api_path: API path string
        :param payload: Request payload dict
        :return: Dict with sign headers or None on failure
        """
        try:
            sign_script = os.path.join(BASE_DIR, "static", "xhs_sign.js")
            if not os.path.exists(sign_script):
                logger.error(f"XHS sign script not found: {sign_script}")
                return None

            input_data = json.dumps({
                "path": api_path,
                "payload": json.dumps(payload),
                "cookie": self.cookies,
            })

            result = subprocess.run(
                [self.node_path, sign_script],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=os.path.join(BASE_DIR, "static")
            )

            if result.returncode != 0:
                logger.error(
                    f"XHS sign script failed, "
                    f"stderr={result.stderr[:200]}"
                )
                return None

            # Parse last line of stdout (sign JS may output debug info before JSON)
            stdout_lines = result.stdout.strip().split('\n')
            sign_result = json.loads(stdout_lines[-1])
            return {
                "x-s": sign_result.get("x-s", ""),
                "x-t": sign_result.get("x-t", ""),
                "x-s-common": sign_result.get("x-s-common", ""),
            }

        except subprocess.TimeoutExpired:
            logger.error("XHS sign script execution timeout")
            return None
        except Exception:
            logger.error(
                f"XHS sign generation failed, "
                f"error: {traceback.format_exc()}"
            )
            return None

    def _parse_search_response(
        self,
        data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Parse raw XHS search API response into standardized note list

        :param data: Raw API response dict
        :return: List of parsed note dicts
        """
        notes = []
        try:
            items = data.get("data", {}).get("items", [])
            for item in items:
                note_card = item.get("note_card", {})
                if not note_card:
                    continue

                user = note_card.get("user", {})
                interact_info = note_card.get("interact_info", {})
                note_id = item.get("id", "")

                # Build URL with xsec_token for valid access
                xsec_token = item.get("xsec_token", "")
                xsec_source = item.get("xsec_source", "pc_search")
                if xsec_token:
                    note_url = (
                        f"https://www.xiaohongshu.com/explore/{note_id}"
                        f"?xsec_token={xsec_token}"
                        f"&xsec_source={xsec_source}"
                    )
                else:
                    note_url = f"https://www.xiaohongshu.com/explore/{note_id}"

                notes.append({
                    "title": note_card.get("display_title", ""),
                    "content": note_card.get("desc", ""),
                    "note_url": note_url,
                    "note_id": note_id,
                    "xsec_token": xsec_token,
                    "xsec_source": xsec_source,
                    "author": user.get("nickname", ""),
                    "author_avatar": user.get("avatar", ""),
                    "likes": _parse_count(interact_info.get("liked_count", "0")),
                    "collected": _parse_count(interact_info.get("collected_count", "0")),
                    "comments": _parse_count(interact_info.get("comment_count", "0")),
                    "cover_image": note_card.get("cover", {}).get("url_default", ""),
                    "note_type": note_card.get("type", ""),
                })

        except Exception:
            logger.error(
                f"Failed to parse XHS search response, "
                f"error: {traceback.format_exc()}"
            )

        return notes

    def get_note_detail(self, note_id: str, xsec_token: str = "", xsec_source: str = "pc_search") -> Optional[Dict[str, Any]]:
        """
        Get full note detail (content, images, video) via feed API.

        :param note_id: Note ID
        :param xsec_token: xsec_token from search result
        :param xsec_source: xsec_source, default pc_search
        :return: Dict with full note content or None on failure
        """
        try:
            api = "/api/sns/web/v1/feed"
            payload = {
                "source_note_id": note_id,
                "image_formats": ["jpg", "webp", "avif"],
                "extra": {"need_body_topic": "1"},
                "xsec_source": xsec_source,
                "xsec_token": xsec_token,
            }

            # Generate sign parameters
            sign_params = self._generate_sign(api, payload)
            if not sign_params:
                logger.error(f"Failed to generate sign for note detail, note_id={note_id}")
                return None

            headers = {**self.session.headers, **sign_params}

            response = self.session.post(
                f"https://edith.xiaohongshu.com{api}",
                json=payload,
                headers=headers,
                timeout=self.timeout
            )

            if response.status_code == 461:
                raise XhsCookieExpiredError("XHS cookie expired")

            if response.status_code != 200:
                logger.warning(
                    f"Note detail API returned status={response.status_code}, "
                    f"note_id={note_id}"
                )
                return None

            res_json = response.json()
            if not res_json.get("success"):
                logger.warning(
                    f"Note detail API failed, note_id={note_id}, "
                    f"msg={res_json.get('msg', '')}"
                )
                return None

            # Parse note detail from feed response
            items = res_json.get("data", {}).get("items", [])
            if not items:
                return None

            note_item = items[0].get("note_card", {})

            # Extract image list (full resolution URLs)
            image_list = []
            for img in note_item.get("image_list", []):
                info_list = img.get("info_list", [])
                if len(info_list) > 1:
                    image_list.append(info_list[1].get("url", ""))
                elif len(info_list) > 0:
                    image_list.append(info_list[0].get("url", ""))

            # Extract video URL (for video notes)
            video_url = ""
            video_info = note_item.get("video", {})
            if video_info:
                streams = video_info.get("media", {}).get("stream", {}).get("h264", [])
                if streams:
                    video_url = streams[0].get("master_url") or streams[0].get("url", "")
                if not video_url:
                    # Fallback: consumer.origin_video_key
                    origin_key = video_info.get("consumer", {}).get("origin_video_key", "")
                    if origin_key:
                        video_url = f"https://sns-video-bd.xhscdn.com/{origin_key}"

            return {
                "title": note_item.get("title", ""),
                "content": note_item.get("desc", ""),
                "tags": [tag.get("name", "") for tag in note_item.get("tag_list", [])],
                "time": note_item.get("time", ""),
                "last_update_time": note_item.get("last_update_time", ""),
                "ip_location": note_item.get("ip_location", ""),
                "image_list": image_list,
                "video_url": video_url,
            }

        except XhsCookieExpiredError:
            raise
        except Exception:
            logger.error(
                f"Get note detail failed, note_id={note_id}, "
                f"error: {traceback.format_exc()}"
            )
            return None

    def _generate_x_rap_param(
        self,
        api_path: str,
        data: Any
    ) -> Optional[str]:
        """
        Generate x-rap-param header by calling xhs_rap.js

        :param api_path: API path (with query string for GET)
        :param data: Request body (empty string for GET)
        :return: x-rap-param string or None
        """
        try:
            rap_script = os.path.join(BASE_DIR, "static", "xhs_rap.js")
            if not os.path.exists(rap_script):
                logger.warning("XHS rap script not found, skipping x-rap-param")
                return None

            # Build a small wrapper script that calls generate_x_rap_param
            wrapper = (
                f'const fs = require("fs");\n'
                f'require("./xhs_rap.js");\n'
                f'try {{\n'
                f'  const result = generate_x_rap_param("{api_path}", {json.dumps(data if data else "")});\n'
                f'  process.stdout.write(result);\n'
                f'}} catch(e) {{\n'
                f'  process.stderr.write(e.message);\n'
                f'  process.exit(1);\n'
                f'}}\n'
            )

            result = subprocess.run(
                [self.node_path, "-e", wrapper],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=os.path.join(BASE_DIR, "static")
            )

            if result.returncode != 0:
                logger.warning(
                    f"XHS rap script failed, stderr={result.stderr[:200]}"
                )
                return None

            rap_param = result.stdout.strip()
            if rap_param:
                logger.debug(f"Generated x-rap-param: {rap_param[:50]}...")
                return rap_param
            return None

        except subprocess.TimeoutExpired:
            logger.warning("XHS rap script timeout")
            return None
        except Exception:
            logger.warning(
                f"XHS rap generation failed, error: {traceback.format_exc()}"
            )
            return None

    def _generate_sign_for_get(
        self,
        api_path: str
    ) -> Optional[Dict[str, str]]:
        """
        Generate sign parameters for GET requests.
        For GET requests, the payload in sign generation should be empty.

        :param api_path: Full API path with query string
        :return: Dict with sign headers or None on failure
        """
        try:
            sign_script = os.path.join(BASE_DIR, "static", "xhs_sign.js")
            if not os.path.exists(sign_script):
                logger.error(f"XHS sign script not found: {sign_script}")
                return None

            input_data = json.dumps({
                "path": api_path,
                "payload": "",
                "cookie": self.cookies,
            })

            result = subprocess.run(
                [self.node_path, sign_script],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=os.path.join(BASE_DIR, "static")
            )

            if result.returncode != 0:
                logger.error(
                    f"XHS sign script failed for GET, "
                    f"stderr={result.stderr[:200]}"
                )
                return None

            stdout_lines = result.stdout.strip().split('\n')
            sign_result = json.loads(stdout_lines[-1])
            return {
                "x-s": sign_result.get("x-s", ""),
                "x-t": sign_result.get("x-t", ""),
                "x-s-common": sign_result.get("x-s-common", ""),
            }

        except subprocess.TimeoutExpired:
            logger.error("XHS sign script execution timeout (GET)")
            return None
        except Exception:
            logger.error(
                f"XHS sign generation failed (GET), "
                f"error: {traceback.format_exc()}"
            )
            return None

    def search_users(
        self,
        keyword: str,
        num: int = 15
    ) -> List[Dict[str, Any]]:
        """
        Search Xiaohongshu users by keyword

        :param keyword: Search keyword (username, nickname, etc.)
        :param num: Number of results to return (1-30)
        :return: List of user dicts with user_id, nickname, avatar, fans, desc, etc.
        """
        num = max(1, min(num, 30))
        all_users: List[Dict[str, Any]] = []
        page = 1
        page_size = 15

        try:
            while len(all_users) < num:
                users = self._search_users_page(keyword, page, page_size)
                if not users:
                    break
                all_users.extend(users)
                page += 1
                time.sleep(1)

            result = all_users[:num]
            logger.info(
                f"XHS user search completed, keyword={keyword}, "
                f"requested={num}, returned={len(result)}"
            )
            return result

        except Exception:
            logger.error(
                f"XHS user search failed, keyword={keyword}, "
                f"error: {traceback.format_exc()}"
            )
            raise

    def _search_users_page(
        self,
        keyword: str,
        page: int,
        page_size: int
    ) -> List[Dict[str, Any]]:
        """
        Search a single page of user results

        :param keyword: Search keyword
        :param page: Page number (1-based)
        :param page_size: Results per page
        :return: List of parsed user dicts
        """
        api = "/api/sns/web/v1/search/usersearch"
        payload = {
            "search_user_request": {
                "keyword": keyword,
                "search_id": self._generate_search_id(),
                "page": page,
                "page_size": page_size,
                "biz_type": "web_search_user",
                "request_id": self._generate_search_id(),
            }
        }

        sign_params = self._generate_sign(api, payload)
        if not sign_params:
            logger.error("Failed to generate sign for user search")
            return []

        headers = {**self.session.headers, **sign_params}

        try:
            response = self.session.post(
                f"https://edith.xiaohongshu.com{api}",
                json=payload,
                headers=headers,
                timeout=self.timeout
            )

            if response.status_code == 461:
                raise XhsCookieExpiredError("XHS cookie expired, need to refresh")

            if response.status_code != 200:
                logger.warning(
                    f"XHS user search API returned status={response.status_code}, "
                    f"body={response.text[:200]}"
                )
                return []

            res_json = response.json()
            if not res_json.get("success"):
                logger.warning(
                    f"XHS user search failed, msg={res_json.get('msg', '')}"
                )
                return []

            logger.debug(
                f"XHS user search raw response keys: "
                f"{list(res_json.get('data', {}).keys())}"
            )

            return self._parse_user_search_response(res_json)

        except XhsCookieExpiredError:
            raise
        except requests.Timeout:
            logger.error(f"XHS user search request timeout, page={page}")
            return []
        except Exception:
            logger.error(
                f"XHS user search page request failed, page={page}, "
                f"error: {traceback.format_exc()}"
            )
            return []

    def _parse_user_search_response(
        self,
        data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Parse raw XHS user search API response into standardized user list.

        Actual API response structure (each item):
        {
            "id": "5a16b266e8ac2b1a571e74ee",
            "name": "吃鸡蛋不吃蛋黄",
            "image": "https://sns-avatar-qc.xhscdn.com/...",
            "red_id": "943414783",
            "fans": "85",
            "note_count": 3,
            "sub_title": "小红书号：943414783",
            "xsec_token": "ABYq...",
            ...
        }
        """
        users = []
        try:
            user_items = data.get("data", {}).get("users", [])
            for item in user_items:
                # Parse fans - could be string like "85" or "1.2万"
                fans_raw = item.get("fans", "0")
                try:
                    if isinstance(fans_raw, str) and "万" in fans_raw:
                        fans = int(float(fans_raw.replace("万", "")) * 10000)
                    else:
                        fans = int(fans_raw)
                except (ValueError, TypeError):
                    fans = 0

                users.append({
                    "user_id": item.get("id", ""),
                    "nickname": item.get("name", ""),
                    "avatar": item.get("image", ""),
                    "red_id": item.get("red_id", ""),
                    "desc": item.get("sub_title", ""),
                    "fans": fans,
                    "note_count": item.get("note_count", 0),
                    "xsec_token": item.get("xsec_token", ""),
                    "xsec_source": "pc_search",
                })
        except Exception:
            logger.error(
                f"Failed to parse XHS user search response, "
                f"error: {traceback.format_exc()}"
            )
        return users

    def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user profile information by user_id

        :param user_id: Target user ID
        :return: User info dict or None on failure
        """
        try:
            api = "/api/sns/web/v1/user/otherinfo"
            params = f"?target_user_id={user_id}"
            full_api = api + params

            sign_params = self._generate_sign_for_get(full_api)
            if not sign_params:
                logger.error(f"Failed to generate sign for user info, user_id={user_id}")
                return None

            headers = {**self.session.headers, **sign_params}

            response = self.session.get(
                f"https://edith.xiaohongshu.com{full_api}",
                headers=headers,
                timeout=self.timeout
            )

            if response.status_code == 461:
                raise XhsCookieExpiredError("XHS cookie expired")

            if response.status_code != 200:
                logger.warning(
                    f"User info API returned status={response.status_code}, "
                    f"user_id={user_id}, body={response.text[:200]}"
                )
                return None

            res_json = response.json()
            if not res_json.get("success"):
                logger.warning(
                    f"User info API failed, user_id={user_id}, "
                    f"msg={res_json.get('msg', '')}"
                )
                return None

            logger.info(
                f"User info raw response data keys: "
                f"{list(res_json.get('data', {}).keys())}, "
                f"basic_info: {json.dumps(res_json.get('data', {}).get('basic_info', {}), ensure_ascii=False)[:300]}"
            )

            basic_info = res_json.get("data", {}).get("basic_info", {})
            interactions = res_json.get("data", {}).get("interactions", [])

            fans = 0
            for interaction in interactions:
                if interaction.get("type") == "fans":
                    fans = interaction.get("count", 0)
                    break
            # Fallback: fans is typically the second item
            if fans == 0 and len(interactions) > 1:
                fans = interactions[1].get("count", 0)

            return {
                "user_id": user_id,
                "nickname": basic_info.get("nickname", ""),
                "avatar": basic_info.get("imageb", "") or basic_info.get("image", ""),
                "red_id": basic_info.get("red_id", ""),
                "desc": basic_info.get("desc", ""),
                "fans": fans,
                "gender": basic_info.get("gender", -1),
                "ip_location": basic_info.get("ip_location", ""),
                "xsec_token": "",
                "xsec_source": "pc_user",
            }

        except XhsCookieExpiredError:
            raise
        except Exception:
            logger.error(
                f"Get user info failed, user_id={user_id}, "
                f"error: {traceback.format_exc()}"
            )
            return None

    def get_user_notes(
        self,
        user_id: str,
        xsec_token: str = "",
        xsec_source: str = "pc_search",
        num: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Get notes published by a specific user (paginated).
        Tries with xsec_token first, falls back to without if data is null.

        :param user_id: Target user ID
        :param xsec_token: xsec_token for access
        :param xsec_source: xsec_source, default pc_search
        :param num: Max number of notes to return (1-50)
        :return: List of note dicts (same format as search results)
        """
        num = max(1, min(num, 50))
        all_notes: List[Dict[str, Any]] = []
        cursor = ""

        logger.info(
            f"XHS get_user_notes starting, user_id={user_id}, "
            f"xsec_token={xsec_token[:20] if xsec_token else 'EMPTY'}, num={num}"
        )

        # Try with token first, then without if empty result
        token_options = [(xsec_token, xsec_source)]
        if xsec_token:
            token_options.append(("", ""))

        for try_token, try_source in token_options:
            all_notes = []
            cursor = ""
            try:
                while len(all_notes) < num:
                    notes, new_cursor, has_more = self._get_user_notes_page(
                        user_id, cursor, try_token, try_source
                    )
                    if not notes:
                        break
                    all_notes.extend(notes)
                    if not has_more or not new_cursor:
                        break
                    cursor = new_cursor
                    time.sleep(1)

                if all_notes:
                    break  # Got results, no need to try next option

            except Exception:
                logger.error(
                    f"XHS get user notes failed, user_id={user_id}, "
                    f"error: {traceback.format_exc()}"
                )
                if try_token == token_options[-1][0]:
                    raise
                continue

        result = all_notes[:num]
        logger.info(
            f"XHS get user notes completed, user_id={user_id}, "
            f"requested={num}, returned={len(result)}"
        )
        return result

    def _get_user_notes_page(
        self,
        user_id: str,
        cursor: str,
        xsec_token: str,
        xsec_source: str
    ) -> tuple:
        """
        Get a single page of user's notes

        :param user_id: Target user ID
        :param cursor: Pagination cursor
        :param xsec_token: xsec_token
        :param xsec_source: xsec_source
        :return: (notes_list, next_cursor, has_more)
        """
        api = "/api/sns/web/v1/user_posted"
        params_parts = [
            f"num=30",
            f"cursor={cursor}",
            f"user_id={user_id}",
            f"image_formats=jpg,webp,avif",
        ]
        # Only include xsec params if token is provided
        if xsec_token:
            params_parts.append(f"xsec_token={xsec_token}")
            params_parts.append(f"xsec_source={xsec_source}")
        query_string = "&".join(params_parts)
        full_api = f"{api}?{query_string}"

        logger.info(f"User notes request path: {full_api[:200]}")

        sign_params = self._generate_sign_for_get(full_api)
        if not sign_params:
            logger.error(f"Failed to generate sign for user notes, user_id={user_id}")
            return [], "", False

        # Generate x-rap-param for user_posted API
        rap_param = self._generate_x_rap_param(full_api, "")
        headers = {**self.session.headers, **sign_params}
        if rap_param:
            headers["x-rap-param"] = rap_param

        try:
            response = self.session.get(
                f"https://edith.xiaohongshu.com{full_api}",
                headers=headers,
                timeout=self.timeout
            )

            if response.status_code == 461:
                raise XhsCookieExpiredError("XHS cookie expired")

            if response.status_code != 200:
                logger.warning(
                    f"User notes API returned status={response.status_code}, "
                    f"user_id={user_id}"
                )
                return [], "", False

            res_json = response.json()
            if not res_json.get("success"):
                logger.warning(
                    f"User notes API failed, user_id={user_id}, "
                    f"msg={res_json.get('msg', '')}, "
                    f"response_keys={list(res_json.keys())}"
                )
                return [], "", False

            data = res_json.get("data") or {}
            if not data:
                logger.warning(
                    f"User notes API returned empty data, user_id={user_id}, "
                    f"full_response={json.dumps(res_json, ensure_ascii=False)[:500]}"
                )
                return [], "", False
            has_more = data.get("has_more", False)
            new_cursor = str(data.get("cursor", ""))
            raw_notes = data.get("notes", [])

            # Parse notes into standard format
            notes = []
            for note in raw_notes:
                interact_info = note.get("interact_info", {})
                user_info = note.get("user", {})
                note_id = note.get("note_id", "")
                note_xsec_token = note.get("xsec_token", xsec_token)

                note_url = (
                    f"https://www.xiaohongshu.com/explore/{note_id}"
                    f"?xsec_token={note_xsec_token}"
                    f"&xsec_source={xsec_source}"
                )

                notes.append({
                    "title": note.get("display_title", ""),
                    "content": note.get("desc", ""),
                    "note_url": note_url,
                    "note_id": note_id,
                    "xsec_token": note_xsec_token,
                    "xsec_source": xsec_source,
                    "author": user_info.get("nickname", ""),
                    "author_avatar": user_info.get("avatar", ""),
                    "likes": _parse_count(interact_info.get("liked_count", "0")),
                    "collected": _parse_count(interact_info.get("collected_count", "0")),
                    "comments": _parse_count(interact_info.get("comment_count", "0")),
                    "cover_image": note.get("cover", {}).get("url_default", ""),
                    "note_type": note.get("type", ""),
                })

            return notes, new_cursor, has_more

        except XhsCookieExpiredError:
            raise
        except requests.Timeout:
            logger.error(f"User notes request timeout, user_id={user_id}")
            return [], "", False
        except Exception:
            logger.error(
                f"User notes page request failed, user_id={user_id}, "
                f"error: {traceback.format_exc()}"
            )
            return [], "", False

    def _generate_search_id(self) -> str:
        """
        Generate a unique search_id for the request

        :return: Search ID string
        """
        import hashlib
        raw = f"{time.time()}{os.getpid()}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _generate_trace_id(self, length: int = 16) -> str:
        """
        Generate x-b3-traceid header value

        :param length: Length of trace ID string
        :return: Hex trace ID
        """
        import random
        chars = "abcdef0123456789"
        return "".join(random.choice(chars) for _ in range(length))


class XhsCookieExpiredError(Exception):
    """Raised when XHS cookie is expired and needs refresh"""
    pass
