#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@Time    : 2026-05-18
@Author  : AI Assistant
@File    : feishu_doc_client.py
@Desc    : Feishu (Lark) Document API client for syncing AI analysis to Feishu Docs
"""
import os
import sys
import time
import traceback
from typing import Dict, Any, Optional, List

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from utils.klogger_util import logger


class FeishuDocClient:
    """Client for Feishu Open Platform Document API"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        folder_token: str = "",
        wiki_space_id: str = "",
        timeout: int = 15
    ) -> None:
        """
        Initialize Feishu Document client.

        :param app_id: Feishu app ID (from open platform)
        :param app_secret: Feishu app secret
        :param folder_token: Default folder token or parent wiki node token
        :param wiki_space_id: Wiki space ID (if using wiki mode)
        :param timeout: Request timeout in seconds
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.folder_token = folder_token
        self.wiki_space_id = wiki_space_id
        self.timeout = timeout
        self.base_url = "https://open.feishu.cn/open-apis"

        # Token cache
        self._tenant_access_token = ""
        self._token_expires_at = 0

        mode = "wiki" if wiki_space_id else "drive"
        logger.info(
            f"FeishuDocClient initialized, app_id={app_id[:6]}***, "
            f"mode={mode}, folder_token={folder_token or 'root'}"
        )

    def _get_tenant_access_token(self) -> str:
        """
        Get or refresh tenant_access_token.
        Token is cached and auto-refreshed when expired.

        :return: Valid tenant_access_token
        :raises RuntimeError: If token fetch fails
        """
        # Return cached token if still valid (with 60s buffer)
        if self._tenant_access_token and time.time() < self._token_expires_at - 60:
            return self._tenant_access_token

        try:
            resp = requests.post(
                f"{self.base_url}/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self.app_id,
                    "app_secret": self.app_secret,
                },
                timeout=self.timeout
            )
            data = resp.json()

            if data.get("code") != 0:
                raise RuntimeError(
                    f"Failed to get tenant_access_token: {data.get('msg', 'unknown error')}"
                )

            self._tenant_access_token = data["tenant_access_token"]
            self._token_expires_at = time.time() + data.get("expire", 7200)

            logger.info("Feishu tenant_access_token refreshed")
            return self._tenant_access_token

        except requests.RequestException as e:
            logger.error(f"Feishu token request failed: {traceback.format_exc()}")
            raise RuntimeError(f"Failed to connect to Feishu API: {e}")

    def _headers(self) -> Dict[str, str]:
        """Get request headers with valid token."""
        token = self._get_tenant_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def create_document(self, title: str, folder_token: str = "") -> Dict[str, str]:
        """
        Create a new document. Supports both:
        - Wiki mode: if wiki_space_id is configured, creates a wiki node
        - Drive mode: creates a regular doc in cloud drive folder

        :param title: Document title
        :param folder_token: Folder/parent node token override
        :return: Dict with document_id, url, title
        :raises RuntimeError: If creation fails
        """
        # If wiki space is configured, use wiki API
        if self.wiki_space_id:
            return self._create_wiki_node(title, folder_token)

        # Otherwise use regular docx API
        return self._create_drive_doc(title, folder_token)

    def _create_wiki_node(self, title: str, parent_node_token: str = "") -> Dict[str, str]:
        """
        Create a docx node in a Wiki space.

        :param title: Document title
        :param parent_node_token: Parent node token (optional)
        :return: Dict with document_id, url, title
        """
        payload = {
            "obj_type": "docx",
            "node_type": "origin",
            "title": title,
        }
        parent = parent_node_token or self.folder_token
        if parent:
            payload["parent_node_token"] = parent

        try:
            resp = requests.post(
                f"{self.base_url}/wiki/v2/spaces/{self.wiki_space_id}/nodes",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout
            )
            data = resp.json()

            if data.get("code") != 0:
                raise RuntimeError(
                    f"Failed to create wiki node: {data.get('msg', 'unknown error')} "
                    f"(code: {data.get('code')})"
                )

            node = data["data"]["node"]
            obj_token = node.get("obj_token", "")
            node_token = node.get("node_token", "")

            logger.info(
                f"Feishu wiki node created, "
                f"node_token={node_token}, obj_token={obj_token}, title={title}"
            )
            return {
                "document_id": obj_token,
                "node_token": node_token,
                "revision_id": 1,
                "title": title,
                "url": f"https://my.feishu.cn/wiki/{node_token}",
            }

        except requests.RequestException as e:
            logger.error(f"Feishu create wiki node failed: {traceback.format_exc()}")
            raise RuntimeError(f"Failed to create Feishu wiki node: {e}")

    def _create_drive_doc(self, title: str, folder_token: str = "") -> Dict[str, str]:
        """
        Create a new document in cloud drive.

        :param title: Document title
        :param folder_token: Folder to create in
        :return: Dict with document_id, url, title
        """
        payload = {"title": title}
        folder = folder_token or self.folder_token
        if folder:
            payload["folder_token"] = folder

        try:
            resp = requests.post(
                f"{self.base_url}/docx/v1/documents",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout
            )
            data = resp.json()

            if data.get("code") != 0:
                raise RuntimeError(
                    f"Failed to create document: {data.get('msg', 'unknown error')} "
                    f"(code: {data.get('code')})"
                )

            doc_info = data["data"]["document"]
            logger.info(
                f"Feishu document created, "
                f"document_id={doc_info['document_id']}, title={title}"
            )
            return {
                "document_id": doc_info["document_id"],
                "revision_id": doc_info.get("revision_id", 1),
                "title": title,
                "url": f"https://bytedance.larkoffice.com/docx/{doc_info['document_id']}",
            }

        except requests.RequestException as e:
            logger.error(f"Feishu create document failed: {traceback.format_exc()}")
            raise RuntimeError(f"Failed to create Feishu document: {e}")

    def get_document_blocks(self, document_id: str) -> List[Dict[str, Any]]:
        """
        Get all blocks in a document (needed to find the page block ID).

        :param document_id: Document ID
        :return: List of block dicts
        """
        try:
            resp = requests.get(
                f"{self.base_url}/docx/v1/documents/{document_id}/blocks",
                headers=self._headers(),
                params={"page_size": 500},
                timeout=self.timeout
            )
            data = resp.json()

            if data.get("code") != 0:
                logger.warning(
                    f"Failed to get document blocks: {data.get('msg', '')}"
                )
                return []

            return data.get("data", {}).get("items", [])

        except Exception:
            logger.error(f"Get document blocks failed: {traceback.format_exc()}")
            return []

    def append_blocks(
        self,
        document_id: str,
        block_id: str,
        children: List[Dict[str, Any]]
    ) -> bool:
        """
        Append child blocks to a specified block in the document.

        :param document_id: Document ID
        :param block_id: Parent block ID to append children to
        :param children: List of block definitions to append
        :return: True if successful
        """
        try:
            resp = requests.post(
                f"{self.base_url}/docx/v1/documents/{document_id}/blocks/{block_id}/children",
                headers=self._headers(),
                json={"children": children},
                timeout=30  # Writing may take longer
            )
            data = resp.json()

            if data.get("code") != 0:
                logger.error(
                    f"Failed to append blocks: {data.get('msg', '')} "
                    f"(code: {data.get('code')})"
                )
                return False

            logger.info(
                f"Appended {len(children)} blocks to document {document_id}"
            )
            return True

        except Exception:
            logger.error(f"Append blocks failed: {traceback.format_exc()}")
            return False

    def write_markdown_to_doc(
        self,
        document_id: str,
        markdown_content: str
    ) -> bool:
        """
        Write markdown content to a Feishu document by converting to blocks.
        Feishu doesn't support direct markdown, so we convert to text blocks.

        :param document_id: Document ID
        :param markdown_content: Markdown formatted text
        :return: True if successful
        """
        # Get the page block (root block) of the document
        blocks = self.get_document_blocks(document_id)
        if not blocks:
            logger.error(f"Cannot find page block for document {document_id}")
            return False

        # The first block is the page block (document root)
        page_block_id = blocks[0].get("block_id", document_id)

        # Convert markdown to Feishu block format
        children = self._markdown_to_blocks(markdown_content)

        if not children:
            logger.warning("No blocks generated from markdown content")
            return False

        # Feishu API limits batch size, send in chunks of 50
        chunk_size = 50
        for i in range(0, len(children), chunk_size):
            chunk = children[i:i + chunk_size]
            success = self.append_blocks(document_id, page_block_id, chunk)
            if not success:
                logger.error(
                    f"Failed to append block chunk {i // chunk_size + 1}"
                )
                return False
            # Rate limiting
            if i + chunk_size < len(children):
                time.sleep(0.5)

        return True

    def _markdown_to_blocks(self, markdown: str) -> List[Dict[str, Any]]:
        """
        Convert markdown text to Feishu document block format.
        Supports: headings (h1-h3), paragraphs, bullet lists, bold text.

        :param markdown: Markdown content
        :return: List of Feishu block dicts
        """
        blocks = []
        lines = markdown.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]

            # Skip empty lines
            if not line.strip():
                i += 1
                continue

            # Heading 1: # Title
            if line.startswith("# ") and not line.startswith("## "):
                blocks.append(self._make_heading_block(line[2:].strip(), 1))
            # Heading 2: ## Title
            elif line.startswith("## "):
                blocks.append(self._make_heading_block(line[3:].strip(), 2))
            # Heading 3: ### Title
            elif line.startswith("### "):
                blocks.append(self._make_heading_block(line[4:].strip(), 3))
            # Heading 4+: #### Title
            elif line.startswith("#### "):
                blocks.append(self._make_heading_block(line[5:].strip(), 4))
            # Bullet list: - item or * item
            elif line.strip().startswith("- ") or line.strip().startswith("* "):
                text = line.strip()[2:]
                blocks.append(self._make_bullet_block(text))
            # Numbered list: 1. item
            elif len(line.strip()) > 2 and line.strip()[0].isdigit() and ". " in line.strip()[:4]:
                text = line.strip().split(". ", 1)[1] if ". " in line.strip() else line.strip()
                blocks.append(self._make_ordered_block(text))
            # Horizontal rule: ---
            elif line.strip() in ("---", "***", "___"):
                blocks.append(self._make_divider_block())
            # Regular paragraph
            else:
                blocks.append(self._make_paragraph_block(line.strip()))

            i += 1

        return blocks

    def _parse_inline_styles(self, text: str) -> List[Dict[str, Any]]:
        """
        Parse inline markdown styles (bold, italic) into Feishu text elements.

        :param text: Text with possible **bold** or *italic* markers
        :return: List of text element dicts
        """
        elements = []
        import re

        # Split by bold markers **text**
        parts = re.split(r'(\*\*[^*]+\*\*)', text)

        for part in parts:
            if not part:
                continue
            if part.startswith("**") and part.endswith("**"):
                # Bold text
                content = part[2:-2]
                elements.append({
                    "text_run": {
                        "content": content,
                        "text_element_style": {"bold": True}
                    }
                })
            else:
                # Normal text
                elements.append({
                    "text_run": {
                        "content": part,
                        "text_element_style": {}
                    }
                })

        if not elements:
            elements.append({
                "text_run": {
                    "content": text,
                    "text_element_style": {}
                }
            })

        return elements

    def _make_heading_block(self, text: str, level: int) -> Dict[str, Any]:
        """Create a heading block. Feishu uses block_type 3-9 for heading1-heading7."""
        # level 1 -> block_type 3, heading1
        # level 2 -> block_type 4, heading2
        # level 3 -> block_type 5, heading3
        # level 4 -> block_type 6, heading4
        block_type = level + 2
        heading_key = f"heading{level}"

        return {
            "block_type": block_type,
            heading_key: {
                "elements": self._parse_inline_styles(text),
            }
        }

    def _make_paragraph_block(self, text: str) -> Dict[str, Any]:
        """Create a paragraph (text) block."""
        return {
            "block_type": 2,  # text
            "text": {
                "elements": self._parse_inline_styles(text),
            }
        }

    def _make_bullet_block(self, text: str) -> Dict[str, Any]:
        """Create a bullet list block."""
        return {
            "block_type": 12,  # bullet
            "bullet": {
                "elements": self._parse_inline_styles(text),
            }
        }

    def _make_ordered_block(self, text: str) -> Dict[str, Any]:
        """Create an ordered list block."""
        return {
            "block_type": 13,  # ordered
            "ordered": {
                "elements": self._parse_inline_styles(text),
            }
        }

    def _make_divider_block(self) -> Dict[str, Any]:
        """Create a divider (horizontal rule) block."""
        return {
            "block_type": 22,  # divider
            "divider": {}
        }

    def sync_analysis_to_doc(
        self,
        title: str,
        content: str,
        folder_token: str = ""
    ) -> Dict[str, Any]:
        """
        High-level method: Create a new Feishu doc and write AI analysis content.

        :param title: Document title
        :param content: Markdown formatted AI analysis content
        :param folder_token: Optional folder token
        :return: Dict with document_id, url, success status
        """
        try:
            # Step 1: Create document
            doc_info = self.create_document(title, folder_token)
            document_id = doc_info["document_id"]

            # Step 2: Write content
            success = self.write_markdown_to_doc(document_id, content)

            # Step 3: Set document permission to "anyone with link can read"
            self._set_public_permission(document_id)

            if success:
                logger.info(
                    f"AI analysis synced to Feishu doc, "
                    f"document_id={document_id}, title={title}"
                )
            else:
                logger.warning(
                    f"Feishu doc created but content write partially failed, "
                    f"document_id={document_id}"
                )

            return {
                "success": success,
                "document_id": document_id,
                "url": doc_info["url"],
                "title": title,
            }

        except Exception as e:
            logger.error(f"Sync to Feishu failed: {traceback.format_exc()}")
            return {
                "success": False,
                "error": str(e),
                "document_id": "",
                "url": "",
                "title": title,
            }

    def _set_public_permission(self, document_id: str) -> None:
        """
        Set document permission so that anyone in the org with the link can edit.
        This makes the doc visible to the app creator.

        :param document_id: Document ID (obj_token)
        """
        try:
            # First, enable link sharing for the document
            resp = requests.patch(
                f"{self.base_url}/drive/v1/permissions/{document_id}/public",
                headers=self._headers(),
                params={"type": "docx"},
                json={
                    "external_access_entity": "open",
                    "security_entity": "anyone_can_view",
                    "comment_entity": "anyone_can_view",
                    "share_entity": "anyone",
                    "link_share_entity": "tenant_editable",
                },
                timeout=self.timeout
            )
            data = resp.json()
            if data.get("code") == 0:
                logger.info(f"Document permission set to org-editable, doc={document_id}")
            else:
                logger.warning(
                    f"Set document permission failed: {data.get('msg', '')} "
                    f"(code: {data.get('code')})"
                )
        except Exception:
            logger.warning(f"Set document permission error: {traceback.format_exc()}")
