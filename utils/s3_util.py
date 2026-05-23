#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@Time    : 2026-03-20
@Author  : Levi Fang 000592
@File    : s3_util.py
@Desc    : AWS S3 utility for briefing HTML upload
"""
import os
import sys
import json
import traceback
from datetime import datetime
from typing import Optional, List, Dict, Any

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
BOTO3_AVAILABLE = True

from utils.klogger_util import logger


class S3Util:
    """AWS S3 utility for uploading briefing HTML reports"""
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialize S3 utility
        
        :param config: S3 configuration dictionary
        """
        self.enabled = config.enabled
        self.bucket_name = config.bucket_name
        self.region = config.region
        self.log_prefix = config.log_prefix
        
        if not self.enabled:
            logger.info("S3 functionality disabled")
            self.s3_client = None
            return
        
        # Initialize S3 client
        self.s3_client = self._create_s3_client(
            config.access_key_id,
            config.secret_access_key
        )
        
        if self.s3_client:
            logger.info(
                f"S3Util initialized, "
                f"bucket={self.bucket_name}, "
                f"region={self.region}"
            )


    def _create_s3_client(
        self,
        access_key: Optional[str],
        secret_key: Optional[str]
    ) -> Optional[Any]:
        """
        Create S3 client with credentials
        
        :param access_key: AWS access key ID
        :param secret_key: AWS secret access key
        :return: S3 client or None
        """
        try:
            if not self.bucket_name:
                logger.warning("S3 bucket name not configured")
                return None
            
            if access_key and secret_key:
                return boto3.client(
                    's3',
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key,
                    region_name=self.region
                )
            else:
                # Use default credentials (IAM role, environment variables, etc.)
                return boto3.client('s3', region_name=self.region)
                
        except Exception as e:
            logger.error(
                f"Failed to create S3 client, "
                f"error: {traceback.format_exc()}"
            )
            return None


    def upload_category_html(
        self,
        source_events: List[Any],
        category_group: Any
    ) -> Optional[str]:
        """
        Upload per-source event details HTML to S3 for a CategoryGroup.

        :param source_events: List of SourceEvent objects
        :param category_group: CategoryGroup enum value
        :return: Presigned URL or None
        """
        if not self.enabled or not self.s3_client:
            return None

        try:
            group_value = category_group.value if hasattr(category_group, 'value') else str(category_group)
            html_content = self._generate_category_html(source_events, group_value)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{self.log_prefix}{group_value}_{timestamp}.html"

            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=filename,
                Body=html_content.encode('utf-8'),
                ContentType='text/html; charset=utf-8'
            )

            presigned_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': filename},
                ExpiresIn=7 * 24 * 3600
            )

            logger.info(
                f"Category HTML uploaded, group={group_value}, "
                f"events={len(source_events)}, filename={filename}"
            )
            return presigned_url

        except Exception:
            logger.error(
                f"upload_category_html failed, "
                f"error: {traceback.format_exc()}"
            )
            return None


    def _generate_category_html(self, source_events: List[Any], group_value: str) -> str:
        """
        Generate HTML page listing all per-source events grouped by source URL.

        :param source_events: List of SourceEvent objects
        :param group_value: CategoryGroup value string
        :return: HTML string
        """
        try:
            template_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'templates', 'category_events.html'
            )
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
        except Exception:
            template = self._get_category_fallback_template()

        # Group events by source_url
        from collections import defaultdict
        grouped: Dict[str, List[Any]] = defaultdict(list)
        for evt in source_events:
            grouped[evt.source_url].append(evt)

        sources_html_parts = []
        for source_url, events in grouped.items():
            event_cards = []
            for evt in events:
                event_cards.append(f"""
<div class="event-card">
  <div class="event-title">{evt.title}</div>
  <div class="event-section"><span class="label">主要内容</span><p>{evt.main_content}</p></div>
  <div class="event-section"><span class="label">关键数据</span><p>{evt.key_data_points}</p></div>
</div>""")

            sources_html_parts.append(f"""
<div class="source-block">
  <div class="source-url">🔗 <a href="{source_url}" target="_blank" rel="noopener">{source_url}</a></div>
  {''.join(event_cards)}
</div>""")

        category_display_map = {
            "material_watch": "全栈物料盯盘",
            "compliance_policy": "合规与政策预警",
            "logistics_supplier": "物流与供应商风险",
        }
        return template.format(
            category_display=category_display_map.get(group_value, group_value),
            current_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            total_events=len(source_events),
            total_sources=len(grouped),
            sources_html=''.join(sources_html_parts)
        )


    def _get_category_fallback_template(self) -> str:
        """Minimal fallback template for category events HTML."""
        return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>{category_display} — 事件明细</title>
  <style>
    body{{font-family:Arial,sans-serif;margin:20px;background:#f5f5f5;color:#333}}
    .header{{background:#fff;padding:20px;border-radius:8px;margin-bottom:20px}}
    .source-block{{background:#fff;border-radius:8px;padding:20px;margin-bottom:20px}}
    .source-url{{font-size:13px;color:#667eea;margin-bottom:12px;word-break:break-all}}
    .event-card{{border-left:3px solid #667eea;padding:12px 16px;margin-bottom:12px;background:#fafafa;border-radius:0 6px 6px 0}}
    .event-title{{font-weight:600;font-size:15px;margin-bottom:8px}}
    .label{{font-size:12px;font-weight:600;color:#667eea;display:block;margin-bottom:4px}}
    p{{margin:0;font-size:14px;line-height:1.7}}
  </style>
</head>
<body>
  <div class="header">
    <h1>{category_display} — 事件明细</h1>
    <p>生成时间: {current_time} | 事件数: {total_events} | 来源数: {total_sources}</p>
  </div>
  {sources_html}
</body>
</html>
"""

    def _get_category_display(self, category: Any) -> str:
        """Get category display name in Chinese"""
        category_names = {
            "component_pcn": "元器件变更通知",
            "component_leadtime": "元器件交期",
            "component_price": "元器件价格",
            "battery_material": "电池材料",
            "commodity": "大宗商品",
            "compliance": "合规风险",
            "logistics": "物流运输",
            "supplier_risk": "供应商风险",
            "competitor": "竞争对手",
            "other": "其他情报"
        }
        
        category_value = category.value if hasattr(category, 'value') else str(category)
        return category_names.get(category_value, "供应链情报")


    def _get_risk_level_text(self, risk_level: Any) -> str:
        """Get risk level text in Chinese"""
        risk_text = {
            "CRITICAL": "严重",
            "ATTENTION": "关注",
            "INFO": "信息"
        }
        
        risk_value = risk_level.value if hasattr(risk_level, 'value') else str(risk_level)
        return risk_text.get(risk_value.upper(), "未知")
