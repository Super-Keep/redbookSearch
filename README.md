# AI Social Media Crawl Service

社交媒体内容搜索与AI分析服务（小红书 + 微信公众号）

## 功能概述

### 小红书 (Xiaohongshu)

- **关键词搜索笔记** — 支持综合/热门/最新排序
- **用户搜索** — 关键词搜索或 user_id 直接查找
- **用户笔记列表** — 获取指定用户发布的笔记
- **笔记详情** — 获取完整内容、图片、视频、标签
- **AI 总结分析** — LLM 对搜索结果进行归纳总结
- **SSE 流式进度** — 实时推送搜索和分析进度
- **导出 CSV** — 搜索结果导出为 CSV 文件
- **导出 ZIP** — 笔记内容 + 图片/视频打包下载

### 微信公众号 (WeChat Official Account)

- **搜索公众号** — 按关键词搜索公众号
- **获取文章列表** — 分页获取指定公众号的文章
- **AI 分析文章** — LLM 对文章摘要进行归纳总结
- **导出 ZIP** — 文章 Markdown 全文 + 摘要 CSV 打包下载

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.9+ |
| Web 框架 | Flask |
| AI | OpenAI GPT-4o mini (LangChain) |
| XHS 签名 | Node.js (crypto-js) |
| 存储 | AWS S3 (HTML 报告) |
| 日志 | JSON 结构化本地文件 |

## 项目结构

```
ai-py-social-media-crawl-service/
├── app/
│   └── app.py                      # Flask 应用入口 + 所有 API 路由
├── clients/
│   ├── dingtalk_client.py          # 钉钉 Webhook 客户端（备用）
│   ├── llm_client.py              # OpenAI LLM 客户端
│   ├── wechat_article_client.py   # 微信公众号文章 API 客户端
│   └── xhs_client.py             # 小红书搜索客户端（含签名算法）
├── config/
│   ├── config.py                  # 配置加载器
│   └── config.yaml               # 主配置文件
├── schema/
│   └── models.py                  # 数据模型
├── services/
│   └── xhs_search_service.py     # 小红书搜索编排服务
├── static/
│   ├── xhs_sign.js               # XHS x-s/x-t 签名算法
│   ├── xhs_rap.js                # XHS x-rap-param 生成
│   └── xhs_main_260411.js        # XHS 核心加密逻辑
├── templates/
│   └── xhs_search.html           # 小红书搜索前端页面
├── utils/
│   ├── klogger_util.py           # JSON 结构化日志
│   ├── retry_util.py             # 重试装饰器
│   ├── s3_util.py                # S3 上传工具
│   └── transform_namespace_util.py # YAML namespace 转换
├── Dockerfile.test
├── Jenkinsfile
├── package.json                   # Node.js 依赖（XHS 签名用）
└── requirements.txt               # Python 依赖
```

## 快速开始

### 环境要求

- Python 3.9+
- Node.js 16+ (小红书签名算法需要)
- Windows 10+ 或 Linux

### 安装

```bash
# 1. 克隆项目
git clone <repository-url>
cd ai-py-social-media-crawl-service

# 2. 创建虚拟环境
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux:
source venv/bin/activate

# 3. 安装 Python 依赖
pip install -r requirements.txt

# 4. 安装 Node.js 依赖（XHS 签名用）
npm install
```

### 环境变量

```bash
# 必需 — 小红书
export XHS_COOKIES="your_xhs_cookie_string"

# 必需 — LLM
export OPENAI_API_KEY="sk-..."

# 必需 — 微信公众号
export WECHAT_ARTICLE_API_KEY="your_api_key"

# 可选 — S3 (用于 HTML 报告上传)
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."

# 可选 — 钉钉 (备用)
export DINGTALK_WEBHOOK_URL="..."
export DINGTALK_SECRET="..."
```

### 运行

```bash
python app/app.py
```

服务启动后访问：
- 健康检查: `GET http://localhost:5060/health`
- 小红书搜索页面: `GET http://localhost:5060/xhs`

## API 文档

### 小红书

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/xhs/search` | 搜索笔记 → AI 分析 → S3 HTML |
| POST | `/api/xhs/search/json` | 搜索笔记 → 返回结构化 JSON |
| POST | `/api/xhs/search/stream` | 搜索笔记 → SSE 流式进度 |
| POST | `/api/xhs/search/users` | 搜索用户 |
| POST | `/api/xhs/user/notes` | 获取用户笔记 + AI 分析 |
| POST | `/api/xhs/user/notes/stream` | 获取用户笔记 → SSE 流式 |
| POST | `/api/xhs/export/zip` | 导出笔记 ZIP |
| GET  | `/api/xhs/export/csv` | 导出搜索结果 CSV |

### 微信公众号

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/wechat/search/accounts` | 搜索公众号 |
| POST | `/api/wechat/articles` | 获取文章列表 |
| POST | `/api/wechat/analyze` | AI 分析文章 |
| POST | `/api/wechat/export/zip` | 导出文章 ZIP |

## 日志

日志文件位于 `logs/app.log`，JSON 格式，包含 traceId、timestamp、level、message。

## 开发规范

- 所有函数必须有类型注解和 rST 风格文档字符串
- 异常处理使用 `traceback.format_exc()`

### Git 工作流

- 功能分支: `feature/版本_功能名_日期`
- Bug 修复: `bugfix/版本_问题名_日期`

## 许可证

内部项目
