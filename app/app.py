# -*- encoding: utf-8 -*-
"""
@Time      :    2026-05-08
@Author    :    Levi Fang 000592
@File      :    app.py
@Desc      :    Flask API application for social media search and analysis (XHS + WeChat)
"""

import os
import sys
import traceback
from http import HTTPStatus

import requests
from dotenv import load_dotenv

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))

# Load .env file before importing config
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from flask import Flask, jsonify, render_template, request
from config.config import CONFIG
from clients.xhs_client import XhsClient, XhsCookieExpiredError
from clients.llm_client import LLMClient
from clients.wechat_article_client import WechatArticleClient
from clients.feishu_doc_client import FeishuDocClient
from services.xhs_search_service import XhsSearchService
from utils.s3_util import S3Util
from utils.klogger_util import logger

app = Flask(
    __name__,
    template_folder=os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates')),
    static_folder=os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static')),
    static_url_path='/static'
)

_xhs_search_service: XhsSearchService = None
_wechat_article_client: WechatArticleClient = None
_feishu_doc_client: FeishuDocClient = None

# Path to local settings file (user-configured via browser)
_LOCAL_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'config', 'local_settings.json'
)


def _load_local_settings() -> dict:
    """Load local_settings.json if it exists."""
    import json
    if os.path.exists(_LOCAL_SETTINGS_PATH):
        try:
            with open(_LOCAL_SETTINGS_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_local_settings(settings: dict) -> None:
    """Save settings to local_settings.json."""
    import json
    os.makedirs(os.path.dirname(_LOCAL_SETTINGS_PATH), exist_ok=True)
    with open(_LOCAL_SETTINGS_PATH, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def _get_xhs_cookies() -> str:
    """Get XHS cookies: local_settings > config.yaml"""
    local = _load_local_settings()
    cookies = local.get("xhs_cookies", "")
    if cookies:
        return cookies
    xhs_config = getattr(CONFIG, "XHS_CONFIG", None)
    if xhs_config:
        c = getattr(xhs_config, "cookies", "")
        if c and not c.startswith("${"):
            return c
    return ""


def _get_wechat_api_key() -> str:
    """Get WeChat API key: local_settings > config.yaml"""
    local = _load_local_settings()
    key = local.get("wechat_api_key", "")
    if key:
        return key
    wechat_config = getattr(CONFIG, "WECHAT_ARTICLE_CONFIG", None)
    if wechat_config:
        k = getattr(wechat_config, "api_key", "")
        if k and not k.startswith("${"):
            return k
    return ""


# ── XHS Service ───────────────────────────────────────────────────────────────


def get_xhs_search_service() -> XhsSearchService:
    """
    Lazy-initialize the XhsSearchService singleton.
    Re-creates if cookies changed.

    :return: XhsSearchService instance
    """
    global _xhs_search_service

    cookies = _get_xhs_cookies()
    if not cookies:
        raise RuntimeError(
            "XHS cookies not configured. "
            "Please go to Settings page to configure."
        )

    # Re-create service if cookies changed
    if _xhs_search_service is not None:
        if _xhs_search_service.xhs_client.cookies != cookies:
            _xhs_search_service = None

    if _xhs_search_service is None:
        xhs_config = getattr(CONFIG, "XHS_CONFIG", None)
        node_path = getattr(xhs_config, "node_path", "node") if xhs_config else "node"
        timeout = int(getattr(xhs_config, "search_timeout", 30)) if xhs_config else 30

        xhs_client = XhsClient(
            cookies=cookies,
            node_path=node_path,
            timeout=timeout
        )

        llm_client = LLMClient(
            api_key=CONFIG.LLM_CONFIG.API_KEY,
            api_url=CONFIG.LLM_CONFIG.API_URL,
            model=CONFIG.LLM_CONFIG.MODEL
        )

        s3_util = S3Util(config=CONFIG.S3_CONFIG)

        _xhs_search_service = XhsSearchService(
            xhs_client=xhs_client,
            llm_client=llm_client,
            s3_util=s3_util
        )

    return _xhs_search_service


# ── WeChat Service ────────────────────────────────────────────────────────────


def get_wechat_article_client() -> WechatArticleClient:
    """Lazy-initialize the WechatArticleClient singleton. Re-creates if key changed."""
    global _wechat_article_client

    api_key = _get_wechat_api_key()
    if not api_key:
        raise RuntimeError(
            "WeChat Article API key not configured. "
            "Please go to Settings page to configure."
        )

    # Re-create if key changed
    if _wechat_article_client is not None:
        if _wechat_article_client.api_key != api_key:
            _wechat_article_client = None

    if _wechat_article_client is None:
        wechat_config = getattr(CONFIG, "WECHAT_ARTICLE_CONFIG", None)
        _wechat_article_client = WechatArticleClient(
            api_base_url=getattr(wechat_config, "api_base_url", "https://down.mptext.top") if wechat_config else "https://down.mptext.top",
            api_key=api_key,
            timeout=int(getattr(wechat_config, "timeout", 15)) if wechat_config else 15
        )
    return _wechat_article_client


# ── Health ────────────────────────────────────────────────────────────────────


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"}), 200


# ── Settings API ──────────────────────────────────────────────────────────────


@app.route("/api/settings", methods=["GET"])
def get_settings():
    """
    Get current settings (masked for security).

    :return: JSON with configured status for each key
    """
    local = _load_local_settings()
    xhs_cookies = local.get("xhs_cookies", "") or _get_xhs_cookies()
    wechat_key = local.get("wechat_api_key", "") or _get_wechat_api_key()

    return jsonify({
        "code": 200,
        "data": {
            "xhs_cookies": _mask_value(xhs_cookies),
            "xhs_cookies_configured": bool(xhs_cookies),
            "wechat_api_key": _mask_value(wechat_key),
            "wechat_api_key_configured": bool(wechat_key),
        }
    }), 200


@app.route("/api/settings", methods=["POST"])
def save_settings():
    """
    Save user settings (XHS cookies, WeChat API key).

    Request JSON:
        xhs_cookies (str): XHS cookie string (optional)
        wechat_api_key (str): WeChat article API key (optional)

    :return: JSON with save result
    """
    try:
        data = request.get_json(force=True) or {}
        local = _load_local_settings()

        if "xhs_cookies" in data and data["xhs_cookies"].strip():
            local["xhs_cookies"] = data["xhs_cookies"].strip()

        if "wechat_api_key" in data and data["wechat_api_key"].strip():
            local["wechat_api_key"] = data["wechat_api_key"].strip()

        _save_local_settings(local)

        # Reset service instances so they pick up new config
        global _xhs_search_service, _wechat_article_client
        _xhs_search_service = None
        _wechat_article_client = None

        logger.info("Settings saved successfully")
        return jsonify({"code": 200, "message": "设置保存成功"}), 200

    except Exception:
        logger.error(f"Save settings failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "保存失败"}), 400


def _mask_value(value: str) -> str:
    """Mask a sensitive value for display, showing first 10 and last 6 chars."""
    if not value:
        return ""
    if len(value) <= 20:
        return value[:4] + "****"
    return value[:10] + "****" + value[-6:]


# ── XHS Search Page ───────────────────────────────────────────────────────────


@app.route("/xhs", methods=["GET"])
def xhs_search_page():
    """Serve the XHS search frontend page."""
    return render_template("xhs_search.html")


# ── XHS API Endpoints ─────────────────────────────────────────────────────────


@app.route("/api/xhs/search", methods=["POST"])
def xhs_search():
    """
    Search Xiaohongshu notes by keyword, analyze with AI, return S3 HTML link.

    Request JSON:
        keyword (str): Search keyword (required)
        num (int): Number of results, default 20, max 50
        sort (str): Sort mode - general / hot / latest

    :return: JSON with html_url, keyword, note_count, search_time
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"code": 400, "message": "Request body is required"}), 400

        keyword = data.get("keyword", "").strip()
        if not keyword:
            return jsonify({"code": 400, "message": "keyword is required"}), 400

        num = min(int(data.get("num", 20)), 50)
        sort = data.get("sort", "general")
        if sort not in ("general", "hot", "latest"):
            return jsonify({"code": 400, "message": "sort must be one of: general, hot, latest"}), 400

        service = get_xhs_search_service()
        result = service.search_and_analyze(keyword=keyword, num=num, sort=sort)

        return jsonify({"code": 200, "data": result}), 200

    except XhsCookieExpiredError:
        logger.error("XHS cookie expired during search")
        return jsonify({"code": 400, "message": "小红书Cookie已过期，请更新XHS_COOKIES环境变量"}), 400
    except RuntimeError as e:
        logger.error(f"XHS search config error: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": str(e)}), 400
    except Exception:
        logger.error(f"XHS search failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "搜索服务异常，请稍后重试"}), 400


@app.route("/api/xhs/search/stream", methods=["POST"])
def xhs_search_stream():
    """SSE stream endpoint for XHS search with real-time progress."""
    import json as _json
    from flask import Response, stream_with_context

    try:
        data = request.get_json(force=True) or {}
        keyword = data.get("keyword", "")
        if isinstance(keyword, str):
            keyword = keyword.strip()
        if not keyword:
            return jsonify({"code": 400, "message": "keyword is required"}), 400
        if len(keyword) > 100:
            keyword = keyword[:100]

        num = max(5, min(int(data.get("num", 20)), 50))
        sort = data.get("sort", "general")
        if sort not in ("general", "hot", "latest"):
            sort = "general"

        service = get_xhs_search_service()

        def generate():
            for event in service.search_and_analyze_stream(keyword, num, sort):
                # Auto-sync to Feishu when analysis is done
                if event.get("stage") == "done" and event.get("data", {}).get("ai_summary"):
                    _auto_sync_to_feishu(
                        keyword=keyword,
                        ai_summary=event["data"]["ai_summary"],
                        note_count=event["data"].get("note_count", 0),
                        source="xhs_search"
                    )
                yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    except Exception:
        logger.error(f"XHS stream search failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "搜索服务异常"}), 400


@app.route("/api/xhs/search/json", methods=["POST"])
def xhs_search_json():
    """Search XHS notes and return structured JSON for frontend rendering."""
    try:
        data = request.get_json(force=True) or {}
        keyword = data.get("keyword", "")
        if isinstance(keyword, str):
            keyword = keyword.strip()
        if not keyword:
            return jsonify({"code": 400, "message": "keyword is required"}), 400
        if len(keyword) > 100:
            keyword = keyword[:100]

        num = max(5, min(int(data.get("num", 20)), 50))
        sort = data.get("sort", "general")
        if sort not in ("general", "hot", "latest"):
            return jsonify({"code": 400, "message": "sort must be one of: general, hot, latest"}), 400

        service = get_xhs_search_service()
        result = service.search_and_analyze_json(keyword=keyword, num=num, sort=sort)

        # Auto-sync to Feishu
        if result.get("ai_summary"):
            _auto_sync_to_feishu(
                keyword=keyword,
                ai_summary=result["ai_summary"],
                note_count=result.get("note_count", 0),
                source="xhs_search"
            )

        return jsonify({"code": 200, "data": result}), 200

    except XhsCookieExpiredError:
        logger.error("XHS cookie expired during JSON search")
        return jsonify({"code": 400, "message": "小红书Cookie已过期，请更新XHS_COOKIES环境变量"}), 400
    except requests.Timeout:
        return jsonify({"code": 400, "message": "搜索超时，请稍后重试"}), 400
    except Exception:
        logger.error(f"XHS JSON search failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "搜索服务异常，请稍后重试"}), 400


@app.route("/api/xhs/search/users", methods=["POST"])
def xhs_search_users():
    """Search XHS users by keyword or user_id (smart detection)."""
    try:
        data = request.get_json(force=True) or {}
        keyword = data.get("keyword", "")
        if isinstance(keyword, str):
            keyword = keyword.strip()
        if not keyword:
            return jsonify({"code": 400, "message": "keyword is required"}), 400
        if len(keyword) > 100:
            keyword = keyword[:100]

        num = max(1, min(int(data.get("num", 15)), 30))

        service = get_xhs_search_service()
        result = service.search_users(keyword=keyword, num=num)

        return jsonify({"code": 200, "data": result}), 200

    except XhsCookieExpiredError:
        logger.error("XHS cookie expired during user search")
        return jsonify({"code": 400, "message": "小红书Cookie已过期，请更新XHS_COOKIES环境变量"}), 400
    except Exception:
        logger.error(f"XHS user search failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "用户搜索服务异常，请稍后重试"}), 400


@app.route("/api/xhs/user/notes", methods=["POST"])
def xhs_user_notes():
    """Get notes published by a specific user with AI analysis."""
    try:
        data = request.get_json(force=True) or {}
        user_id = data.get("user_id", "")
        if isinstance(user_id, str):
            user_id = user_id.strip()
        if not user_id:
            return jsonify({"code": 400, "message": "user_id is required"}), 400

        xsec_token = data.get("xsec_token", "")
        num = max(1, min(int(data.get("num", 30)), 50))

        service = get_xhs_search_service()
        result = service.get_user_notes_and_analyze(
            user_id=user_id, xsec_token=xsec_token, num=num
        )

        return jsonify({"code": 200, "data": result}), 200

    except XhsCookieExpiredError:
        logger.error("XHS cookie expired during user notes fetch")
        return jsonify({"code": 400, "message": "小红书Cookie已过期，请更新XHS_COOKIES环境变量"}), 400
    except Exception:
        logger.error(f"XHS user notes failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "获取用户笔记失败，请稍后重试"}), 400


@app.route("/api/xhs/user/notes/stream", methods=["POST"])
def xhs_user_notes_stream():
    """SSE stream endpoint for user notes with real-time progress."""
    import json as _json
    from flask import Response, stream_with_context

    try:
        data = request.get_json(force=True) or {}
        user_id = data.get("user_id", "")
        if isinstance(user_id, str):
            user_id = user_id.strip()
        if not user_id:
            return jsonify({"code": 400, "message": "user_id is required"}), 400

        xsec_token = data.get("xsec_token", "")
        num = max(5, min(int(data.get("num", 20)), 50))

        service = get_xhs_search_service()

        def generate():
            for event in service.get_user_notes_stream(
                user_id=user_id, xsec_token=xsec_token, num=num
            ):
                # Auto-sync to Feishu when analysis is done
                if event.get("stage") == "done" and event.get("data", {}).get("ai_summary"):
                    _auto_sync_to_feishu(
                        keyword=f"用户 {user_id}",
                        ai_summary=event["data"]["ai_summary"],
                        note_count=event["data"].get("note_count", 0),
                        source="xhs_user"
                    )
                yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    except Exception:
        logger.error(f"XHS user notes stream failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "获取用户笔记失败"}), 400


@app.route("/api/xhs/export/zip", methods=["POST"])
def xhs_export_zip():
    """Export notes as ZIP with per-note folders and summary CSV."""
    from flask import Response
    from datetime import datetime as dt
    from urllib.parse import quote

    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"code": 400, "message": "Request body required"}), 400

        notes = data.get("notes", [])
        if not notes:
            return jsonify({"code": 400, "message": "No notes to export"}), 400

        name_prefix = data.get("name", "xhs_export")
        service = get_xhs_search_service()
        zip_bytes = service.export_zip(notes, name_prefix)

        filename = f"{name_prefix}_{dt.now().strftime('%Y%m%d_%H%M%S')}.zip"
        encoded_filename = quote(filename)

        return Response(
            zip_bytes,
            mimetype="application/zip",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"}
        )

    except Exception:
        logger.error(f"XHS ZIP export failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "导出失败，请稍后重试"}), 400


@app.route("/api/xhs/export/csv", methods=["GET"])
def xhs_export_csv():
    """Export search results as CSV file download."""
    from flask import Response
    from datetime import datetime as dt
    from urllib.parse import quote

    try:
        source = request.args.get("source", "search")
        num = max(1, min(int(request.args.get("num", "20")), 50))
        service = get_xhs_search_service()

        if source == "user":
            user_id = request.args.get("user_id", "").strip()
            if not user_id:
                return jsonify({"code": 400, "message": "user_id is required for user export"}), 400
            xsec_token = request.args.get("xsec_token", "")
            result = service.get_user_notes_and_analyze(user_id=user_id, xsec_token=xsec_token, num=num)
            filename = f"xhs_user_{user_id}_{dt.now().strftime('%Y%m%d')}.csv"
        else:
            keyword = request.args.get("keyword", "").strip()
            if not keyword:
                return jsonify({"code": 400, "message": "keyword is required for search export"}), 400
            sort = request.args.get("sort", "general")
            if sort not in ("general", "hot", "latest"):
                sort = "general"
            result = service.search_and_analyze_json(keyword=keyword, num=num, sort=sort)
            filename = f"xhs_search_{keyword}_{dt.now().strftime('%Y%m%d')}.csv"

        notes = result.get("notes", [])
        csv_content = service.export_csv(notes)
        encoded_filename = quote(filename)

        return Response(
            csv_content,
            mimetype="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"}
        )

    except XhsCookieExpiredError:
        return jsonify({"code": 400, "message": "小红书Cookie已过期，请更新XHS_COOKIES环境变量"}), 400
    except Exception:
        logger.error(f"XHS CSV export failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "导出失败，请稍后重试"}), 400

@app.route("/api/xhs/image/proxy", methods=["GET"])
def xhs_image_proxy():
    """
    Proxy XHS images to bypass Referer anti-hotlinking.

    Query params:
        url (str): Original image URL from xhscdn.com
    """
    from flask import Response

    image_url = request.args.get("url", "")
    if not image_url:
        return jsonify({"code": 400, "message": "url is required"}), 400

    try:
        resp = requests.get(
            image_url,
            timeout=15,
            headers={
                "Referer": "https://www.xiaohongshu.com/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/121.0.0.0 Safari/537.36"
                ),
            },
            stream=True
        )

        if resp.status_code != 200:
            return Response("Image not found", status=404)

        content_type = resp.headers.get("Content-Type", "image/webp")

        return Response(
            resp.content,
            content_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"}
        )

    except Exception:
        return Response("Image fetch failed", status=502)

@app.route("/api/xhs/note/analyze", methods=["POST"])
def xhs_note_analyze():
    """
    AI analysis for a single XHS note (social media / sentiment direction).

    Request JSON:
        title (str): Note title
        content (str): Note full text
        author (str): Author nickname
        likes (int): Like count
        collected (int): Collect count
        comments (int): Comment count
        tags (list): Tag list

    Response 200:
        { "code": 200, "data": { "analysis": "..." } }
    """
    try:
        data = request.get_json(force=True) or {}
        title = data.get("title", "").strip()
        content = data.get("content", "").strip()
        author = data.get("author", "")
        likes = data.get("likes", 0)
        collected = data.get("collected", 0)
        comments = data.get("comments", 0)
        tags = data.get("tags", [])

        if not content and not title:
            return jsonify({"code": 400, "message": "需要提供笔记标题或内容"}), 400

        # Truncate content to avoid token overflow
        if len(content) > 4000:
            content = content[:4000] + "\n\n...(内容已截断)"

        tags_str = "、".join(tags[:10]) if tags else "无"
        stats_str = f"点赞 {likes} | 收藏 {collected} | 评论 {comments}"

        system_prompt = (
            "你是一位顶级的小红书内容创作教练和爆款拆解专家。\n"
            "请对以下笔记进行深度作品拆解，像一个资深操盘手一样分析这篇内容做得好和不好的地方，"
            "帮助我学习和借鉴。\n\n"
            "## 分析框架：\n\n"
            "### 1. 整体评分（满分 10 分）\n"
            "给出综合评分，并用一句话概括这篇笔记的核心竞争力或核心问题。\n\n"
            "### 2. 做得好的地方 ✅\n"
            "逐条分析亮点，每条说清楚「好在哪 + 为什么好 + 带来什么效果」：\n"
            "- **选题**：切入角度是否精准？是否踩中用户痛点/痒点/爽点？\n"
            "- **标题**：是否有吸引力？用了什么技巧（数字、悬念、情绪、对比）？\n"
            "- **开头**：前 3 行是否有钩子？能否留住用户继续看？\n"
            "- **内容价值**：是否提供了实用信息/情绪价值/社交货币？\n"
            "- **结构节奏**：信息密度是否合理？是否有层次感？\n"
            "- **人设表达**：是否有鲜明的个人风格和记忆点？\n"
            "- **互动引导**：是否有效引导点赞/收藏/评论？\n"
            "- **标签/话题**：SEO 布局是否合理？\n\n"
            "### 3. 做得不好的地方 ❌\n"
            "逐条指出问题，每条说清楚「问题是什么 + 为什么是问题 + 怎么改更好」：\n"
            "- 内容上的不足（逻辑、深度、可读性）\n"
            "- 表达上的问题（啰嗦、无重点、缺乏感染力）\n"
            "- 运营上的缺失（缺少 CTA、标签不精准、没有系列化思维）\n"
            "- 差异化不足（和同类内容相比没有独特性）\n\n"
            "### 4. 数据表现诊断\n"
            "基于互动数据（点赞/收藏/评论比例）判断：\n"
            "- 收藏高 → 内容实用性强\n"
            "- 点赞高 → 情绪共鸣强\n"
            "- 评论高 → 话题争议性/互动性强\n"
            "- 数据异常低 → 可能的原因分析\n\n"
            "### 5. 如果我来写，怎么做得更好\n"
            "给出具体的优化方案：\n"
            "- 标题怎么改（给出 2-3 个改写版本）\n"
            "- 开头怎么改（给出钩子示例）\n"
            "- 内容结构怎么调整\n"
            "- 差异化方向建议\n\n"
            "要求：\n"
            "- 像一个严格但有建设性的导师，既指出问题也给解决方案\n"
            "- 分析要具体，引用原文内容来支撑观点，不要空泛\n"
            "- 结构清晰，使用 Markdown 格式\n"
            "- 中文输出"
        )

        prompt = (
            f"笔记标题：{title}\n"
            f"作者：{author}\n"
            f"互动数据：{stats_str}\n"
            f"标签：{tags_str}\n\n"
            f"笔记全文：\n{content}"
        )

        service = get_xhs_search_service()
        analysis = service.llm_client.complete(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.5
        )

        return jsonify({"code": 200, "data": {"analysis": analysis}}), 200

    except Exception:
        logger.error(f"XHS note analyze failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "AI 分析失败，请稍后重试"}), 400

# ── WeChat API Endpoints ──────────────────────────────────────────────────────


@app.route("/api/wechat/search/accounts", methods=["POST"])
def wechat_search_accounts():
    """Search WeChat official accounts by keyword."""
    try:
        data = request.get_json(force=True) or {}
        keyword = data.get("keyword", "").strip()
        if not keyword:
            return jsonify({"code": 400, "message": "keyword is required"}), 400

        client = get_wechat_article_client()
        accounts = client.search_accounts(keyword)

        return jsonify({"code": 200, "data": {"accounts": accounts, "keyword": keyword}}), 200

    except RuntimeError as e:
        return jsonify({"code": 400, "message": str(e)}), 400
    except Exception:
        logger.error(f"WeChat account search failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "搜索失败，请稍后重试"}), 400


@app.route("/api/wechat/articles", methods=["POST"])
def wechat_get_articles():
    """Get article list for a WeChat official account."""
    try:
        data = request.get_json(force=True) or {}
        fakeid = data.get("fakeid", "").strip()
        if not fakeid:
            return jsonify({"code": 400, "message": "fakeid is required"}), 400

        begin = int(data.get("begin", 0))
        size = int(data.get("size", 20))
        keyword = data.get("keyword", "").strip()

        client = get_wechat_article_client()
        result = client.get_articles(fakeid, begin, size, keyword)

        return jsonify({"code": 200, "data": result}), 200

    except RuntimeError as e:
        return jsonify({"code": 400, "message": str(e)}), 400
    except Exception:
        logger.error(f"WeChat article list failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "获取文章列表失败"}), 400


@app.route("/api/wechat/analyze", methods=["POST"])
def wechat_analyze():
    """AI analyze WeChat articles (using digests)."""
    try:
        data = request.get_json(force=True) or {}
        articles = data.get("articles", [])
        account_name = data.get("account_name", "公众号")

        if not articles:
            return jsonify({"code": 400, "message": "No articles to analyze"}), 400

        import re as _re
        parts = []
        for i, art in enumerate(articles[:100], 1):
            title = _re.sub(r'<[^>]+>', '', art.get("title", "无标题"))
            digest = art.get("digest", "")
            parts.append(f"【{i}】{title}\n摘要: {digest}")

        notes_text = "\n\n".join(parts)

        system_prompt = (
            "你是一位信息分析助手。请对以下内容进行归纳总结：\n"
            "1. 提炼主要话题和观点（合并相似内容）\n"
            "2. 标注值得关注的信息点\n"
            "3. 如果内容之间有矛盾或争议，指出分歧\n\n"
            "要求：简洁、客观、中文输出。"
        )

        prompt = (
            f"以下是微信公众号「{account_name}」的{len(parts)}篇文章摘要：\n\n"
            f"{notes_text}"
        )

        service = get_xhs_search_service()
        summary = service.llm_client.complete(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.3
        )

        return jsonify({"code": 200, "data": {"summary": summary}}), 200

    except Exception:
        logger.error(f"WeChat analyze failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "AI 分析失败，请稍后重试"}), 400


@app.route("/api/wechat/export/zip", methods=["POST"])
def wechat_export_zip():
    """Export WeChat articles as ZIP with full markdown content."""
    from flask import Response
    from datetime import datetime as dt
    from urllib.parse import quote
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import zipfile
    import io
    import json as _json
    import re as _re
    import csv as _csv

    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"code": 400, "message": "Request body required"}), 400

        articles = data.get("articles", [])
        if not articles:
            return jsonify({"code": 400, "message": "No articles to export"}), 400

        name_prefix = data.get("name", "wechat_export")
        client = get_wechat_article_client()

        def download_article(art):
            link = art.get("link", "")
            if not link:
                return art, None
            content = client.get_article_content(link, "markdown")
            return art, content

        results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(download_article, art) for art in articles]
            for future in as_completed(futures):
                results.append(future.result())

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            csv_buf = io.StringIO()
            csv_buf.write('\ufeff')
            writer = _csv.writer(csv_buf)
            writer.writerow(['标题', '摘要', '作者', '发表时间', '链接'])
            for art, _ in results:
                title = _re.sub(r'<[^>]+>', '', art.get("title", ""))
                time_str = ""
                if art.get("update_time"):
                    time_str = dt.fromtimestamp(art["update_time"]).strftime("%Y-%m-%d")
                writer.writerow([title, art.get("digest", ""), art.get("author_name", ""), time_str, art.get("link", "")])
            zf.writestr("summary.csv", csv_buf.getvalue().encode('utf-8-sig'))

            for idx, (art, content) in enumerate(results, 1):
                title = _re.sub(r'<[^>]+>', '', art.get("title", "无标题"))
                safe_title = _re.sub(r'[\\/:*?"<>|\n\r]+', '', title)[:30].strip()
                folder = f"{idx:02d}_{safe_title}"

                info = {
                    "title": title,
                    "digest": art.get("digest", ""),
                    "author_name": art.get("author_name", ""),
                    "link": art.get("link", ""),
                }
                zf.writestr(f"{folder}/info.json", _json.dumps(info, ensure_ascii=False, indent=2).encode('utf-8'))

                if content:
                    zf.writestr(f"{folder}/article.md", content.encode('utf-8'))

        zip_buffer.seek(0)
        filename = f"{name_prefix}_{dt.now().strftime('%Y%m%d_%H%M%S')}.zip"
        encoded_filename = quote(filename)

        return Response(
            zip_buffer.getvalue(),
            mimetype="application/zip",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"}
        )

    except Exception:
        logger.error(f"WeChat ZIP export failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "导出失败，请稍后重试"}), 400

@app.route("/api/wechat/article/content", methods=["POST"])
def wechat_get_article_content():
    """
    Get article content by URL.

    Request JSON:
        url (str): WeChat article URL (required)
        format (str): Output format: markdown (default) / html / text

    Response 200:
        { "code": 200, "data": { "content": "..." } }
    """
    try:
        data = request.get_json(force=True) or {}
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"code": 400, "message": "url is required"}), 400

        fmt = data.get("format", "markdown")
        if fmt not in ("markdown", "html", "text", "json"):
            fmt = "markdown"

        client = get_wechat_article_client()
        content = client.get_article_content(url, fmt)

        if content is None:
            return jsonify({"code": 400, "message": "获取文章内容失败"}), 400

        return jsonify({"code": 200, "data": {"content": content}}), 200

    except RuntimeError as e:
        return jsonify({"code": 400, "message": str(e)}), 400
    except Exception:
        logger.error(f"WeChat article content failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "获取文章内容失败"}), 400

@app.route("/api/wechat/article/analyze", methods=["POST"])
def wechat_article_deep_analyze():
    """
    AI deep analysis for a single WeChat article (using full content).

    Request JSON:
        url (str): WeChat article URL (used to fetch content if content not provided)
        title (str): Article title
        content (str): Article full markdown content (optional, will fetch if empty)
        account_name (str): Account name for context

    Response 200:
        { "code": 200, "data": { "analysis": "..." } }
    """
    try:
        data = request.get_json(force=True) or {}
        url = data.get("url", "").strip()
        title = data.get("title", "").strip()
        content = data.get("content", "").strip()
        account_name = data.get("account_name", "公众号")

        if not title and not content and not url:
            return jsonify({"code": 400, "message": "需要提供文章标题或内容"}), 400

        # If content not provided, fetch it
        if not content and url:
            client = get_wechat_article_client()
            content = client.get_article_content(url, "markdown") or ""

        if not content:
            return jsonify({"code": 400, "message": "无法获取文章内容"}), 400

        # Truncate content to avoid token overflow (keep first ~6000 chars)
        if len(content) > 6000:
            content = content[:6000] + "\n\n...(内容已截断)"

        system_prompt = (
            "你是一位专业的内容分析师。请对以下微信公众号文章进行深度分析，输出结构化的分析报告：\n\n"
            "请从以下维度进行分析：\n"
            "1. **核心观点**：提炼文章的主要论点和结论\n"
            "2. **关键信息**：标注重要的数据、事实、引用\n"
            "3. **行业洞察**：分析文章对行业/领域的启示\n"
            "4. **风险提示**：如有潜在风险或值得警惕的信息，请指出\n"
            "5. **总结建议**：给出简洁的行动建议\n\n"
            "要求：专业、客观、结构清晰、中文输出。使用 Markdown 格式。"
        )

        prompt = f"文章标题：{title}\n来源公众号：{account_name}\n\n文章全文：\n{content}"

        # Reuse existing LLM client
        service = get_xhs_search_service()
        analysis = service.llm_client.complete(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.3
        )

        return jsonify({"code": 200, "data": {"analysis": analysis}}), 200

    except Exception:
        logger.error(f"WeChat article deep analyze failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "AI 深度分析失败，请稍后重试"}), 400

@app.route("/api/wechat/image/proxy", methods=["GET"])
def wechat_image_proxy():
    """
    Proxy WeChat CDN images to bypass anti-hotlink protection.

    Query params:
        url (str): Original WeChat image URL (mmbiz.qpic.cn)

    Response: Image binary with appropriate content-type
    """
    from flask import Response

    try:
        url = request.args.get("url", "").strip()
        if not url:
            return "Missing url parameter", 400

        # Only allow proxying qpic.cn images (WeChat CDN domains)
        if "qpic.cn" not in url:
            return "Only WeChat images are allowed", 403

        # Fetch image with WeChat-compatible headers
        resp = requests.get(
            url,
            headers={
                "Referer": "https://mp.weixin.qq.com/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
            timeout=15,
            stream=True,
        )

        if resp.status_code != 200:
            return "Image fetch failed", 502

        # Forward the image with caching headers
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        return Response(
            resp.content,
            mimetype=content_type,
            headers={
                "Cache-Control": "public, max-age=86400",
                "Access-Control-Allow-Origin": "*",
            },
        )

    except Exception:
        logger.error(f"Image proxy failed: {traceback.format_exc()}")
        return "Image proxy error", 502


# ── Feishu Document Sync API ──────────────────────────────────────────────────


def _auto_sync_to_feishu(
    keyword: str,
    ai_summary: str,
    note_count: int = 0,
    source: str = "xhs_search"
) -> None:
    """
    Auto-sync AI analysis to Feishu document (non-blocking, fail-silent).

    :param keyword: Search keyword (used in document title)
    :param ai_summary: AI generated summary content (markdown)
    :param note_count: Number of notes analyzed
    :param source: Source identifier (xhs_search / xhs_user / wechat)
    """
    import threading
    from datetime import datetime as dt

    def _sync():
        try:
            config = _get_feishu_config()
            if not config["app_id"] or not config["app_secret"]:
                return  # Feishu not configured, skip silently

            client = get_feishu_doc_client()

            # Build document title
            timestamp = dt.now().strftime("%m-%d %H:%M")
            if source == "xhs_search":
                title = f"小红书分析｜{keyword}｜{note_count}篇｜{timestamp}"
            elif source == "xhs_user":
                title = f"用户分析｜{keyword}｜{note_count}篇｜{timestamp}"
            else:
                title = f"内容分析｜{keyword}｜{timestamp}"

            result = client.sync_analysis_to_doc(title=title, content=ai_summary)

            if result["success"]:
                logger.info(
                    f"Auto-synced to Feishu, keyword={keyword}, "
                    f"url={result['url']}"
                )
            else:
                logger.warning(
                    f"Auto-sync to Feishu failed, keyword={keyword}, "
                    f"error={result.get('error', 'unknown')}"
                )

        except Exception:
            logger.warning(f"Auto-sync to Feishu error: {traceback.format_exc()}")

    # Run in background thread to not block the response
    thread = threading.Thread(target=_sync, daemon=True)
    thread.start()


def _get_feishu_config() -> dict:
    """Get Feishu config from local_settings or environment."""
    local = _load_local_settings()
    return {
        "app_id": local.get("feishu_app_id", "") or os.environ.get("FEISHU_APP_ID", ""),
        "app_secret": local.get("feishu_app_secret", "") or os.environ.get("FEISHU_APP_SECRET", ""),
        "folder_token": local.get("feishu_folder_token", "") or os.environ.get("FEISHU_FOLDER_TOKEN", ""),
        "wiki_space_id": local.get("feishu_wiki_space_id", "") or os.environ.get("FEISHU_WIKI_SPACE_ID", ""),
    }


def get_feishu_doc_client() -> FeishuDocClient:
    """Lazy-initialize the FeishuDocClient singleton."""
    global _feishu_doc_client

    config = _get_feishu_config()
    if not config["app_id"] or not config["app_secret"]:
        raise RuntimeError(
            "飞书应用未配置。请在设置页面或 .env 文件中配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET"
        )

    # Re-create if config changed
    if _feishu_doc_client is not None:
        if _feishu_doc_client.app_id != config["app_id"]:
            _feishu_doc_client = None

    if _feishu_doc_client is None:
        _feishu_doc_client = FeishuDocClient(
            app_id=config["app_id"],
            app_secret=config["app_secret"],
            folder_token=config["folder_token"],
            wiki_space_id=config["wiki_space_id"],
        )

    return _feishu_doc_client


@app.route("/api/feishu/sync", methods=["POST"])
def feishu_sync_analysis():
    """
    Sync AI analysis content to a new Feishu document.

    Request JSON:
        title (str): Document title (required)
        content (str): Markdown content to write (required)
        folder_token (str): Optional folder token override

    Response 200:
        { "code": 200, "data": { "document_id": "...", "url": "...", "title": "..." } }
    """
    try:
        data = request.get_json(force=True) or {}
        title = data.get("title", "").strip()
        content = data.get("content", "").strip()
        folder_token = data.get("folder_token", "")

        if not title:
            return jsonify({"code": 400, "message": "title is required"}), 400
        if not content:
            return jsonify({"code": 400, "message": "content is required"}), 400

        client = get_feishu_doc_client()
        result = client.sync_analysis_to_doc(
            title=title,
            content=content,
            folder_token=folder_token
        )

        if result["success"]:
            return jsonify({"code": 200, "data": result}), 200
        else:
            return jsonify({
                "code": 400,
                "message": result.get("error", "同步到飞书文档失败"),
                "data": result
            }), 400

    except RuntimeError as e:
        return jsonify({"code": 400, "message": str(e)}), 400
    except Exception:
        logger.error(f"Feishu sync failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "同步到飞书失败，请稍后重试"}), 400


@app.route("/api/feishu/config", methods=["GET"])
def feishu_get_config():
    """Get Feishu configuration status (masked)."""
    config = _get_feishu_config()
    return jsonify({
        "code": 200,
        "data": {
            "configured": bool(config["app_id"] and config["app_secret"]),
            "app_id": _mask_value(config["app_id"]),
            "folder_token": config["folder_token"] or "(根目录)",
        }
    }), 200


@app.route("/api/feishu/config", methods=["POST"])
def feishu_save_config():
    """
    Save Feishu configuration.

    Request JSON:
        feishu_app_id (str): Feishu app ID
        feishu_app_secret (str): Feishu app secret
        feishu_folder_token (str): Optional folder token
    """
    try:
        data = request.get_json(force=True) or {}
        local = _load_local_settings()

        if "feishu_app_id" in data and data["feishu_app_id"].strip():
            local["feishu_app_id"] = data["feishu_app_id"].strip()
        if "feishu_app_secret" in data and data["feishu_app_secret"].strip():
            local["feishu_app_secret"] = data["feishu_app_secret"].strip()
        if "feishu_folder_token" in data:
            local["feishu_folder_token"] = data["feishu_folder_token"].strip()

        _save_local_settings(local)

        # Reset client
        global _feishu_doc_client
        _feishu_doc_client = None

        logger.info("Feishu config saved successfully")
        return jsonify({"code": 200, "message": "飞书配置保存成功"}), 200

    except Exception:
        logger.error(f"Save Feishu config failed: {traceback.format_exc()}")
        return jsonify({"code": 400, "message": "保存失败"}), 400


# ── Entry Point ───────────────────────────────────────────────────────────────


if __name__ == "__main__":
    logger.info("Starting social media crawl service")
    app.run(host="0.0.0.0", port=5090, debug=False)
