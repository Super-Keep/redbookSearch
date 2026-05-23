#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@Time    : 2026-05-08
@Author  : Levi Fang 000592
@File    : xhs_search_service.py
@Desc    : Xiaohongshu search orchestration service: search -> AI analyze -> HTML -> S3
"""
import csv
import io
import os
import re
import sys
import traceback
from datetime import datetime
from typing import Dict, Any, List, Optional

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.klogger_util import logger
from clients.xhs_client import XhsClient, XhsCookieExpiredError
from clients.llm_client import LLMClient
from utils.s3_util import S3Util


# Sort display names for HTML
SORT_DISPLAY = {
    "general": "综合排序",
    "hot": "热门排序",
    "latest": "最新排序",
}


class XhsSearchService:
    """Xiaohongshu search and analysis orchestration service"""

    # Class-level search cache: key -> (timestamp, result)
    _search_cache: Dict[str, Any] = {}
    _CACHE_TTL = 3600  # 1 hour in seconds

    def __init__(
        self,
        xhs_client: XhsClient,
        llm_client: LLMClient,
        s3_util: S3Util
    ) -> None:
        """
        Initialize XHS search service

        :param xhs_client: XHS search client
        :param llm_client: LLM client for content analysis
        :param s3_util: S3 utility for HTML upload
        """
        self.xhs_client = xhs_client
        self.llm_client = llm_client
        self.s3_util = s3_util

        logger.info("XhsSearchService initialized")

    def _get_cache_key(self, keyword: str, num: int, sort: str) -> str:
        """Generate cache key from search parameters."""
        return f"{keyword}|{num}|{sort}"

    def _get_cached_result(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        Get cached search result if still valid (within TTL).

        :param cache_key: Cache key
        :return: Cached result dict or None if expired/missing
        """
        import time as _time
        if cache_key in self._search_cache:
            cached_time, cached_result = self._search_cache[cache_key]
            if _time.time() - cached_time < self._CACHE_TTL:
                logger.info(f"Cache hit for key={cache_key}")
                return cached_result
            else:
                # Expired, remove
                del self._search_cache[cache_key]
                logger.info(f"Cache expired for key={cache_key}")
        return None

    def _set_cache(self, cache_key: str, result: Dict[str, Any]) -> None:
        """Store search result in cache."""
        import time as _time
        self._search_cache[cache_key] = (_time.time(), result)
        logger.info(f"Cache stored for key={cache_key}")

    def search_and_analyze_json(
        self,
        keyword: str,
        num: int = 20,
        sort: str = "general"
    ) -> Dict[str, Any]:
        """
        Search XHS notes and return structured data (no HTML/S3).

        :param keyword: Search keyword
        :param num: Number of results (1-50)
        :param sort: Sort mode: general / hot / latest
        :return: Dict with ai_summary, notes array, keyword, sort, note_count
        :raises XhsCookieExpiredError: When cookie is expired
        """
        # Check cache first
        cache_key = self._get_cache_key(keyword, num, sort)
        cached = self._get_cached_result(cache_key)
        if cached:
            return cached

        logger.info(
            f"XHS search_and_analyze_json started, "
            f"keyword={keyword}, num={num}, sort={sort}"
        )

        # Step 1: Search XHS
        notes = self.xhs_client.search(keyword, num, sort)
        note_count = len(notes)
        logger.info(f"XHS search returned {note_count} notes")

        # Step 2: Fetch full content for each note
        self._enrich_notes_content(notes)

        # Step 3: AI analysis (non-blocking on failure)
        ai_summary = self._analyze_notes(keyword, notes)

        # Step 4: Build structured response (skip HTML rendering and S3 upload)
        structured_notes = []
        for note in notes:
            structured_notes.append({
                "title": note.get("title", ""),
                "content": note.get("content", ""),
                "author": note.get("author", ""),
                "likes": note.get("likes", 0),
                "collected": note.get("collected", 0),
                "comments": note.get("comments", 0),
                "note_url": note.get("note_url", ""),
                "cover_image": note.get("cover_image", ""),
                "image_list": note.get("image_list", []),
                "video_url": note.get("video_url", ""),
                "tags": note.get("tags", []),
            })

        logger.info(
            f"XHS search_and_analyze_json completed, "
            f"keyword={keyword}, notes={note_count}"
        )

        result = {
            "ai_summary": ai_summary,
            "notes": structured_notes,
            "keyword": keyword,
            "sort": sort,
            "note_count": note_count,
        }

        # Store in cache
        self._set_cache(cache_key, result)

        return result

    def search_and_analyze_stream(
        self,
        keyword: str,
        num: int = 20,
        sort: str = "general"
    ):
        """
        Generator that yields SSE progress events during search + analyze.

        Yields dicts like:
            {"stage": "searching", "message": "..."}
            {"stage": "enriching", "current": 3, "total": 20, "message": "..."}
            {"stage": "analyzing", "message": "..."}
            {"stage": "done", "data": {...}}
            {"stage": "error", "message": "..."}
        """
        import json as _json
        import time as _time

        # Check cache first
        cache_key = self._get_cache_key(keyword, num, sort)
        cached = self._get_cached_result(cache_key)
        if cached:
            yield {"stage": "searching", "message": "命中缓存，直接返回结果..."}
            yield {"stage": "done", "data": cached}
            return

        try:
            # Stage 1: Search
            yield {"stage": "searching", "message": f"正在搜索「{keyword}」相关笔记..."}

            notes = self.xhs_client.search(keyword, num, sort)
            note_count = len(notes)

            if not notes:
                yield {"stage": "done", "data": {
                    "ai_summary": "未找到相关笔记。",
                    "notes": [], "keyword": keyword, "sort": sort, "note_count": 0
                }}
                return

            yield {"stage": "searching", "message": f"找到 {note_count} 篇笔记，开始获取详情..."}

            # Stage 2: Enrich (with per-note progress)
            enriched = 0
            for i, note in enumerate(notes, 1):
                note_id = note.get("note_id", "")
                xsec_token = note.get("xsec_token", "")
                xsec_source = note.get("xsec_source", "pc_search")

                if note_id:
                    try:
                        detail = self.xhs_client.get_note_detail(
                            note_id, xsec_token, xsec_source
                        )
                        if detail and detail.get("content"):
                            note["content"] = detail["content"]
                            if detail.get("tags"):
                                note["tags"] = detail["tags"]
                            if detail.get("ip_location"):
                                note["ip_location"] = detail["ip_location"]
                            if detail.get("image_list"):
                                note["image_list"] = detail["image_list"]
                            if detail.get("video_url"):
                                note["video_url"] = detail["video_url"]
                            enriched += 1
                        _time.sleep(0.5)
                    except XhsCookieExpiredError:
                        raise
                    except Exception:
                        pass

                yield {
                    "stage": "enriching",
                    "current": i,
                    "total": note_count,
                    "message": f"获取笔记详情 {i}/{note_count}"
                }

            # Stage 3: AI Analysis
            yield {"stage": "analyzing", "message": "AI 正在分析总结..."}

            ai_summary = self._analyze_notes(keyword, notes)

            # Stage 4: Build result
            structured_notes = []
            for note in notes:
                structured_notes.append({
                    "title": note.get("title", ""),
                    "content": note.get("content", ""),
                    "author": note.get("author", ""),
                    "likes": note.get("likes", 0),
                    "collected": note.get("collected", 0),
                    "comments": note.get("comments", 0),
                    "note_url": note.get("note_url", ""),
                    "cover_image": note.get("cover_image", ""),
                    "image_list": note.get("image_list", []),
                    "video_url": note.get("video_url", ""),
                    "tags": note.get("tags", []),
                })

            stream_result = {
                "ai_summary": ai_summary,
                "notes": structured_notes,
                "keyword": keyword,
                "sort": sort,
                "note_count": note_count,
            }

            # Store in cache
            self._set_cache(cache_key, stream_result)

            yield {"stage": "done", "data": stream_result}

        except XhsCookieExpiredError:
            yield {"stage": "error", "message": "小红书Cookie已过期，请更新XHS_COOKIES环境变量"}
        except Exception as e:
            logger.error(f"Stream search failed: {traceback.format_exc()}")
            yield {"stage": "error", "message": "搜索服务异常，请稍后重试"}

    def search_and_analyze(
        self,
        keyword: str,
        num: int = 20,
        sort: str = "general"
    ) -> Dict[str, Any]:
        """
        Full pipeline: search XHS -> AI summarize -> generate HTML -> upload S3

        :param keyword: Search keyword
        :param num: Number of results (1-50)
        :param sort: Sort mode: general / hot / latest
        :return: Dict with html_url, keyword, note_count, search_time
        :raises XhsCookieExpiredError: When cookie is expired
        """
        logger.info(
            f"XHS search_and_analyze started, "
            f"keyword={keyword}, num={num}, sort={sort}"
        )
        start_time = datetime.now()

        # Step 1: Search XHS
        notes = self.xhs_client.search(keyword, num, sort)
        note_count = len(notes)
        logger.info(f"XHS search returned {note_count} notes")

        # Step 2: Fetch full content for each note
        self._enrich_notes_content(notes)

        # Step 3: AI analysis (non-blocking on failure)
        ai_summary = self._analyze_notes(keyword, notes)

        # Step 4: Generate HTML
        html_content = self._render_html(keyword, sort, notes, ai_summary)

        # Step 5: Upload to S3
        html_url = self._upload_to_s3(keyword, html_content)

        search_time = start_time.strftime("%Y-%m-%d %H:%M:%S")
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"XHS search_and_analyze completed, "
            f"keyword={keyword}, notes={note_count}, "
            f"duration={duration:.2f}s"
        )

        return {
            "html_url": html_url,
            "keyword": keyword,
            "note_count": note_count,
            "search_time": search_time,
        }

    def search_users(
        self,
        keyword: str,
        num: int = 15
    ) -> Dict[str, Any]:
        """
        Smart user search: auto-detect user_id vs keyword.

        If keyword looks like a user_id, try direct lookup first.
        If that fails or keyword is not a user_id, fall back to keyword search.

        :param keyword: User name, keyword, or user_id
        :param num: Number of results (1-30)
        :return: Dict with users list, keyword, user_count, match_type
        """
        logger.info(f"XHS search_users started, keyword={keyword}, num={num}")

        # Try direct user_id lookup first
        if self._looks_like_user_id(keyword):
            try:
                user_info = self.xhs_client.get_user_info(keyword)
                if user_info and user_info.get("nickname"):
                    logger.info(
                        f"XHS user found by ID, user_id={keyword}, "
                        f"nickname={user_info.get('nickname', '')}"
                    )
                    return {
                        "users": [user_info],
                        "keyword": keyword,
                        "user_count": 1,
                        "match_type": "id",
                    }
                elif user_info:
                    logger.warning(
                        f"XHS user found by ID but nickname is empty, "
                        f"falling back to keyword search, user_id={keyword}"
                    )
            except Exception:
                logger.warning(
                    f"Direct user_id lookup failed, falling back to keyword search, "
                    f"user_id={keyword}"
                )

        # Keyword search
        try:
            users = self.xhs_client.search_users(keyword, num)
            logger.info(
                f"XHS user search completed, keyword={keyword}, "
                f"returned={len(users)}"
            )
            return {
                "users": users,
                "keyword": keyword,
                "user_count": len(users),
                "match_type": "keyword",
            }
        except Exception:
            logger.error(
                f"XHS user search failed, keyword={keyword}, "
                f"error: {traceback.format_exc()}"
            )
            raise

    def get_user_notes_and_analyze(
        self,
        user_id: str,
        xsec_token: str = "",
        num: int = 30
    ) -> Dict[str, Any]:
        """
        Get user's notes and analyze with AI.

        :param user_id: Target user ID
        :param xsec_token: xsec_token for access
        :param num: Max number of notes (1-50)
        :return: Dict with ai_summary, notes, user_id, note_count
        """
        logger.info(
            f"XHS get_user_notes_and_analyze started, "
            f"user_id={user_id}, num={num}"
        )

        # Step 1: Get user notes
        notes = self.xhs_client.get_user_notes(
            user_id=user_id,
            xsec_token=xsec_token,
            num=num
        )
        note_count = len(notes)
        logger.info(f"XHS user notes returned {note_count} notes")

        # Step 2: Enrich notes with full content
        self._enrich_notes_content(notes)

        # Step 3: AI analysis
        # Use user_id as context keyword for AI prompt
        nickname = notes[0].get("author", user_id) if notes else user_id
        ai_summary = self._analyze_notes(f"用户「{nickname}」的笔记", notes)

        # Step 4: Build structured response
        structured_notes = []
        for note in notes:
            structured_notes.append({
                "title": note.get("title", ""),
                "content": note.get("content", ""),
                "author": note.get("author", ""),
                "likes": note.get("likes", 0),
                "collected": note.get("collected", 0),
                "comments": note.get("comments", 0),
                "note_url": note.get("note_url", ""),
                "cover_image": note.get("cover_image", ""),
                "image_list": note.get("image_list", []),
                "video_url": note.get("video_url", ""),
                "tags": note.get("tags", []),
            })

        logger.info(
            f"XHS get_user_notes_and_analyze completed, "
            f"user_id={user_id}, notes={note_count}"
        )

        return {
            "ai_summary": ai_summary,
            "notes": structured_notes,
            "user_id": user_id,
            "note_count": note_count,
        }

    def get_user_notes_stream(
        self,
        user_id: str,
        xsec_token: str = "",
        num: int = 20
    ):
        """
        Generator that yields SSE progress events during user notes fetch + analyze.

        Yields dicts like:
            {"stage": "fetching", "message": "..."}
            {"stage": "enriching", "current": 3, "total": 20, "message": "..."}
            {"stage": "analyzing", "message": "..."}
            {"stage": "done", "data": {...}}
            {"stage": "error", "message": "..."}
        """
        import time as _time

        try:
            # Stage 1: Fetch user notes
            yield {"stage": "fetching", "message": f"正在获取用户笔记列表..."}

            notes = self.xhs_client.get_user_notes(
                user_id=user_id,
                xsec_token=xsec_token,
                num=num
            )
            note_count = len(notes)

            if not notes:
                yield {"stage": "done", "data": {
                    "ai_summary": "未找到该用户的笔记。",
                    "notes": [], "user_id": user_id, "note_count": 0
                }}
                return

            yield {"stage": "fetching", "message": f"找到 {note_count} 篇笔记，开始获取详情..."}

            # Stage 2: Enrich (with per-note progress)
            enriched = 0
            for i, note in enumerate(notes, 1):
                note_id = note.get("note_id", "")
                note_xsec_token = note.get("xsec_token", "")
                xsec_source = note.get("xsec_source", "pc_search")

                if note_id:
                    try:
                        detail = self.xhs_client.get_note_detail(
                            note_id, note_xsec_token, xsec_source
                        )
                        if detail:
                            if detail.get("content"):
                                note["content"] = detail["content"]
                            if detail.get("tags"):
                                note["tags"] = detail["tags"]
                            if detail.get("ip_location"):
                                note["ip_location"] = detail["ip_location"]
                            if detail.get("image_list"):
                                note["image_list"] = detail["image_list"]
                            if detail.get("video_url"):
                                note["video_url"] = detail["video_url"]
                            enriched += 1
                        _time.sleep(0.5)
                    except XhsCookieExpiredError:
                        raise
                    except Exception:
                        pass

                yield {
                    "stage": "enriching",
                    "current": i,
                    "total": note_count,
                    "message": f"获取笔记详情 {i}/{note_count}"
                }

            # Stage 3: AI Analysis
            yield {"stage": "analyzing", "message": "AI 正在分析总结..."}

            nickname = notes[0].get("author", user_id) if notes else user_id
            ai_summary = self._analyze_notes(f"用户「{nickname}」的笔记", notes)

            # Stage 4: Build result
            structured_notes = []
            for note in notes:
                structured_notes.append({
                    "title": note.get("title", ""),
                    "content": note.get("content", ""),
                    "author": note.get("author", ""),
                    "likes": note.get("likes", 0),
                    "collected": note.get("collected", 0),
                    "comments": note.get("comments", 0),
                    "note_url": note.get("note_url", ""),
                    "cover_image": note.get("cover_image", ""),
                    "image_list": note.get("image_list", []),
                    "video_url": note.get("video_url", ""),
                    "tags": note.get("tags", []),
                })

            yield {"stage": "done", "data": {
                "ai_summary": ai_summary,
                "notes": structured_notes,
                "user_id": user_id,
                "note_count": note_count,
            }}

        except XhsCookieExpiredError:
            yield {"stage": "error", "message": "小红书Cookie已过期，请更新XHS_COOKIES环境变量"}
        except Exception:
            logger.error(f"User notes stream failed: {traceback.format_exc()}")
            yield {"stage": "error", "message": "获取用户笔记失败，请稍后重试"}

    def export_zip(self, notes: List[Dict[str, Any]], name_prefix: str = "xhs") -> bytes:
        """
        Export notes as a ZIP archive with per-note folders and a summary CSV.
        Uses concurrent downloads for speed.

        :param notes: List of note dicts
        :param name_prefix: Prefix for naming
        :return: ZIP file bytes
        """
        import zipfile
        import json as _json
        import requests as _requests
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def download_media(url: str, timeout: int = 15) -> Optional[bytes]:
            """Download a single media file, return bytes or None."""
            if not url:
                return None
            try:
                resp = _requests.get(
                    url,
                    timeout=timeout,
                    headers={
                        "Referer": "https://www.xiaohongshu.com/",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    }
                )
                if resp.status_code == 200 and len(resp.content) > 100:
                    return resp.content
            except Exception:
                pass
            return None

        # Collect all download tasks
        download_tasks = []  # (folder_name, filename, url, timeout)
        note_folders = []

        for idx, note in enumerate(notes, 1):
            title = note.get("title", "无标题")
            safe_title = re.sub(r'[\\/:*?"<>|\n\r]+', '', title)[:20].strip()
            note_id = note.get("note_url", "").split("/")[-1].split("?")[0] or f"note_{idx}"
            folder_name = f"{idx:02d}_{safe_title}_{note_id}"
            note_folders.append((folder_name, note))

            # Images
            image_list = note.get("image_list", [])
            cover_url = note.get("cover_image", "")
            urls = image_list if image_list else ([cover_url] if cover_url else [])
            for img_idx, img_url in enumerate(urls):
                if img_url:
                    download_tasks.append((folder_name, f"image_{img_idx}", img_url, 15))

            # Video
            video_url = note.get("video_url", "")
            if video_url:
                download_tasks.append((folder_name, "video", video_url, 60))

        # Concurrent download all media
        downloaded = {}  # key: (folder_name, filename) -> bytes
        logger.info(f"ZIP export starting concurrent download, tasks={len(download_tasks)}")

        with ThreadPoolExecutor(max_workers=10) as executor:
            future_map = {}
            for folder, filename, url, timeout in download_tasks:
                future = executor.submit(download_media, url, timeout)
                future_map[future] = (folder, filename, url)

            for future in as_completed(future_map):
                folder, filename, url = future_map[future]
                data = future.result()
                if data:
                    downloaded[(folder, filename)] = data

        logger.info(f"Download completed, success={len(downloaded)}/{len(download_tasks)}")

        # Build ZIP
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Summary CSV
            csv_content = self.export_csv(notes)
            zf.writestr("summary.csv", csv_content.encode('utf-8-sig'))

            # Per-note folders
            for folder_name, note in note_folders:
                # info.json
                info = {
                    "title": note.get("title", ""),
                    "content": note.get("content", ""),
                    "author": note.get("author", ""),
                    "likes": note.get("likes", 0),
                    "collected": note.get("collected", 0),
                    "comments": note.get("comments", 0),
                    "note_url": note.get("note_url", ""),
                    "cover_image": note.get("cover_image", ""),
                    "image_list": note.get("image_list", []),
                    "video_url": note.get("video_url", ""),
                    "tags": note.get("tags", []),
                }
                info_json = _json.dumps(info, ensure_ascii=False, indent=2)
                zf.writestr(f"{folder_name}/info.json", info_json.encode('utf-8'))

                # Add downloaded media files
                for (f, filename), data in downloaded.items():
                    if f == folder_name:
                        if filename == "video":
                            zf.writestr(f"{folder_name}/{filename}.mp4", data)
                        else:
                            # Detect extension from first bytes
                            ext = "jpg"
                            if data[:4] == b'\x89PNG':
                                ext = "png"
                            elif data[:4] == b'RIFF':
                                ext = "webp"
                            zf.writestr(f"{folder_name}/{filename}.{ext}", data)

        zip_buffer.seek(0)
        logger.info(f"ZIP export completed, notes={len(notes)}, size={zip_buffer.getbuffer().nbytes} bytes")
        return zip_buffer.getvalue()

    def export_csv(self, notes: List[Dict[str, Any]]) -> str:
        """
        Convert notes list to CSV string (UTF-8 with BOM for Excel compatibility).

        :param notes: List of note dicts
        :return: CSV formatted string
        """
        output = io.StringIO()
        # Write BOM for Excel to recognize UTF-8
        output.write('\ufeff')

        writer = csv.writer(output)
        # Header row
        writer.writerow([
            "标题", "内容摘要", "作者", "点赞", "收藏", "评论", "链接", "标签"
        ])

        for note in notes:
            content = note.get("content", "")
            if len(content) > 200:
                content = content[:200] + "..."

            tags = note.get("tags", [])
            tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags)

            writer.writerow([
                note.get("title", ""),
                content,
                note.get("author", ""),
                note.get("likes", 0),
                note.get("collected", 0),
                note.get("comments", 0),
                note.get("note_url", ""),
                tags_str,
            ])

        return output.getvalue()

    def _looks_like_user_id(self, input_str: str) -> bool:
        """
        Determine if input looks like a XHS user_id.

        XHS user_id formats:
        - Pure digits, 9-12 characters (e.g. 943414783)
        - 24-character hex string (e.g. 64c3f392000000002b009e45)

        :param input_str: Input string to check
        :return: True if it looks like a user_id
        """
        if not input_str:
            return False

        # Pure digits, 9-12 chars
        if re.match(r'^\d{9,12}$', input_str):
            return True

        # 24-char hex string
        if re.match(r'^[0-9a-fA-F]{24}$', input_str):
            return True

        return False

    def _enrich_notes_content(self, notes: List[Dict[str, Any]]) -> None:
        """
        Fetch full note content via feed API for each note.
        Updates notes in-place with full content.

        :param notes: List of note dicts from search results
        """
        import time as _time

        enriched = 0
        for note in notes:
            note_id = note.get("note_id", "")
            xsec_token = note.get("xsec_token", "")
            xsec_source = note.get("xsec_source", "pc_search")

            if not note_id:
                continue

            try:
                detail = self.xhs_client.get_note_detail(
                    note_id, xsec_token, xsec_source
                )
                if detail:
                    if detail.get("content"):
                        note["content"] = detail["content"]
                    if detail.get("tags"):
                        note["tags"] = detail["tags"]
                    if detail.get("ip_location"):
                        note["ip_location"] = detail["ip_location"]
                    if detail.get("image_list"):
                        note["image_list"] = detail["image_list"]
                    if detail.get("video_url"):
                        note["video_url"] = detail["video_url"]
                    enriched += 1

                # Rate limiting to avoid triggering anti-crawl
                _time.sleep(0.5)

            except XhsCookieExpiredError:
                raise
            except Exception:
                logger.warning(
                    f"Failed to enrich note content, note_id={note_id}, "
                    f"error: {traceback.format_exc()}"
                )
                continue

        logger.info(f"Enriched {enriched}/{len(notes)} notes with full content")

    def _analyze_notes(
        self,
        keyword: str,
        notes: List[Dict[str, Any]]
    ) -> str:
        """
        Use LLM to summarize search results

        :param keyword: Search keyword
        :param notes: List of note dicts
        :return: AI summary text, or fallback message on failure
        """
        if not notes:
            return "未找到相关笔记，无法生成分析总结。"

        try:
            # Build content for LLM
            notes_text = self._build_notes_text(notes)

            system_prompt = (
                "你是一位资深的小红书运营策略分析师，专注于研究头部账号的增长逻辑和获客策略。\n\n"
                "请对以下笔记进行深度拆解分析，输出一份**详尽的、不少于 2000 字**的竞争力分析报告：\n\n"
                "## 分析框架：\n\n"
                "### 1. 赛道概览（300字以上）\n"
                "- 该关键词/领域的内容竞争格局，当前处于什么阶段（蓝海/红海/细分机会）\n"
                "- 头部内容的共性特征（选题方向、内容形式、发布频率）\n"
                "- 主要玩家类型分析（个人博主/机构号/品牌号各占什么比例）\n\n"
                "### 2. 获客竞争力拆解（500字以上）\n"
                "- **选题策略**：逐条分析高互动笔记的选题切入点，为什么能吸引用户？解决了什么需求？\n"
                "- **标题公式**：列举 5-8 个高点击标题，逐一拆解其技巧（情绪词、数字、悬念、痛点、对比等），总结出可复用的标题模板\n"
                "- **内容结构**：拆解 2-3 篇代表性笔记的完整结构（开头钩子怎么写、正文如何分段、结尾如何引导互动）\n"
                "- **人设定位**：分析不同作者的人设类型，哪种人设在这个赛道最吃香\n"
                "- **视觉呈现**：封面风格、配图策略、排版特点\n\n"
                "### 3. 爆款密码（400字以上）\n"
                "- 列出互动数据 TOP3 的笔记，逐篇分析为什么能成为爆款\n"
                "- 点赞/收藏/评论各自的驱动因素是什么\n"
                "- 从数据反推：什么类型的内容收藏率高（实用干货）、什么类型点赞高（情绪共鸣）、什么类型评论多（争议话题）\n\n"
                "### 4. 可复制的增长策略（500字以上）\n"
                "- **账号定位建议**：如果从零开始做这个赛道，推荐什么定位？给出 2-3 个差异化方向\n"
                "- **内容矩阵规划**：\n"
                "  - 引流型内容（吸引新用户）：具体选题建议 3-5 个\n"
                "  - 涨粉型内容（建立信任）：具体选题建议 3-5 个\n"
                "  - 转化型内容（变现导流）：具体选题建议 3-5 个\n"
                "- **发布节奏建议**：频率、时间段、系列化策略\n"
                "- **差异化切入点**：现有内容的空白地带，别人没做但有需求的方向\n\n"
                "### 5. 30天冷启动计划\n"
                "- 第1周：做什么\n"
                "- 第2周：做什么\n"
                "- 第3-4周：做什么\n"
                "- 关键里程碑和数据目标\n\n"
                "### 6. 风险与注意事项\n"
                "- 该领域的内容红线和平台规则风险\n"
                "- 同质化严重的方向（建议避开）\n"
                "- 可能遇到的坑和应对策略\n\n"
                "要求：\n"
                "- **必须详细**，每个章节都要有充分的分析和具体案例，不要一笔带过\n"
                "- 引用原文中的具体标题、内容片段和数据来支撑每一个观点\n"
                "- 给出的建议必须具体到可以直接执行，不要空泛的方向性建议\n"
                "- 结构清晰，使用 Markdown 格式输出\n"
                "- 中文输出，语言专业但易懂\n"
                "- 总字数不少于 2000 字"
            )

            prompt = (
                f"以下是在小红书平台搜索\"{keyword}\"得到的{len(notes)}条笔记内容，"
                f"请从获客竞争力和账号运营的角度进行深度拆解，输出一份详尽的分析报告：\n\n"
                f"{notes_text}"
            )

            summary = self.llm_client.complete(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.5
            )

            logger.info(f"AI analysis completed, summary_length={len(summary)}")
            return summary

        except Exception:
            logger.error(
                f"AI analysis failed, keyword={keyword}, "
                f"error: {traceback.format_exc()}"
            )
            return "AI 分析暂不可用，请查看下方笔记列表获取详细内容。"

    def _build_notes_text(self, notes: List[Dict[str, Any]]) -> str:
        """
        Build text representation of notes for LLM input

        :param notes: List of note dicts
        :return: Formatted text string
        """
        parts = []
        for i, note in enumerate(notes, 1):
            title = note.get("title", "无标题")
            content = note.get("content", "")
            author = note.get("author", "未知")
            likes = note.get("likes", 0)
            collected = note.get("collected", 0)
            comments = note.get("comments", 0)
            tags = note.get("tags", [])
            tags_str = "、".join(tags[:5]) if tags else ""
            # Truncate long content to avoid token overflow
            if len(content) > 1500:
                content = content[:1500] + "..."
            parts.append(
                f"【{i}】{title}\n"
                f"作者: {author} | 点赞: {likes} | 收藏: {collected} | 评论: {comments}\n"
                f"{f'标签: {tags_str}\n' if tags_str else ''}"
                f"内容: {content}\n"
            )
        return "\n".join(parts)

    def _render_html(
        self,
        keyword: str,
        sort: str,
        notes: List[Dict[str, Any]],
        ai_summary: str
    ) -> str:
        """
        Render search results as HTML page

        :param keyword: Search keyword
        :param sort: Sort mode
        :param notes: List of note dicts
        :param ai_summary: AI summary text
        :return: HTML string
        """
        try:
            template_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "templates", "xhs_search_results.html"
            )
            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()
        except Exception:
            logger.warning("XHS HTML template not found, using fallback")
            template = self._get_fallback_template()

        # Build notes HTML
        notes_html = self._build_notes_html(notes)
        sort_display = SORT_DISPLAY.get(sort, sort)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Replace template placeholders
        html = template.format(
            keyword=keyword,
            current_time=current_time,
            sort_display=sort_display,
            note_count=len(notes),
            ai_summary=ai_summary.replace("\n", "<br>"),
            notes_html=notes_html,
        )
        return html

    def _build_notes_html(self, notes: List[Dict[str, Any]]) -> str:
        """
        Build HTML cards for each note

        :param notes: List of note dicts
        :return: HTML string of note cards
        """
        cards = []
        for note in notes:
            title = note.get("title", "无标题")
            content = note.get("content", "")
            author = note.get("author", "未知")
            likes = note.get("likes", 0)
            note_url = note.get("note_url", "#")

            # Truncate content for display
            if len(content) > 200:
                content = content[:200] + "..."

            cards.append(f"""
<div class="note-card">
  <div class="note-title">{title}</div>
  <div class="note-content">{content}</div>
  <div class="note-meta">
    <span class="author">👤 {author}</span>
    <span class="likes">❤️ {likes}</span>
    <a href="{note_url}" target="_blank" rel="noopener" class="note-link">查看原文 →</a>
  </div>
</div>""")

        return "\n".join(cards)

    def _upload_to_s3(self, keyword: str, html_content: str) -> Optional[str]:
        """
        Upload HTML to S3 and return presigned URL

        :param keyword: Search keyword (used in filename)
        :param html_content: HTML string to upload
        :return: Presigned URL or None
        """
        try:
            if not self.s3_util.enabled or not self.s3_util.s3_client:
                logger.warning("S3 not available, cannot upload XHS search HTML")
                return None

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.s3_util.log_prefix}xhs_search_{timestamp}.html"

            self.s3_util.s3_client.put_object(
                Bucket=self.s3_util.bucket_name,
                Key=filename,
                Body=html_content.encode("utf-8"),
                ContentType="text/html; charset=utf-8",
            )

            presigned_url = self.s3_util.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.s3_util.bucket_name, "Key": filename},
                ExpiresIn=7 * 24 * 3600,
            )

            logger.info(f"XHS search HTML uploaded to S3, filename={filename}")
            return presigned_url

        except Exception:
            logger.error(
                f"Failed to upload XHS search HTML, "
                f"keyword={keyword}, error: {traceback.format_exc()}"
            )
            return None

    def _get_fallback_template(self) -> str:
        """Minimal fallback HTML template"""
        return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>小红书搜索: {keyword}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:0;padding:20px;background:#f5f5f5;color:#333}}
.container{{max-width:900px;margin:0 auto}}
.header{{background:#fff;padding:24px;border-radius:12px;margin-bottom:20px;box-shadow:0 2px 8px rgba(0,0,0,0.06)}}
.header h1{{margin:0 0 8px;font-size:22px;color:#ff2442}}
.header .meta{{color:#666;font-size:14px}}
.ai-summary{{background:#fff;padding:24px;border-radius:12px;margin-bottom:20px;border-left:4px solid #ff2442;box-shadow:0 2px 8px rgba(0,0,0,0.06)}}
.ai-summary h2{{margin:0 0 12px;font-size:16px;color:#ff2442}}
.ai-summary .content{{font-size:14px;line-height:1.8;color:#444}}
.note-card{{background:#fff;padding:20px;border-radius:12px;margin-bottom:12px;box-shadow:0 2px 8px rgba(0,0,0,0.06)}}
.note-title{{font-weight:600;font-size:16px;margin-bottom:8px}}
.note-content{{font-size:14px;color:#555;line-height:1.6;margin-bottom:12px}}
.note-meta{{display:flex;align-items:center;gap:16px;font-size:13px;color:#888}}
.note-link{{color:#ff2442;text-decoration:none;margin-left:auto}}
.note-link:hover{{text-decoration:underline}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🔍 小红书搜索: {keyword}</h1>
    <div class="meta">搜索时间: {current_time} | {sort_display} | 共 {note_count} 条结果</div>
  </div>
  <div class="ai-summary">
    <h2>📊 AI 内容总结</h2>
    <div class="content">{ai_summary}</div>
  </div>
  {notes_html}
</div>
</body>
</html>"""
