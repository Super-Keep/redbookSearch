#!/bin/bash
# ============================================================
# 社交媒体内容搜索分析服务 - 一键启动脚本 (macOS)
# 双击此文件即可启动服务
# ============================================================

# 切换到脚本所在目录
cd "$(dirname "$0")"

echo "============================================"
echo "  社交媒体内容搜索分析服务"
echo "  正在检查环境..."
echo "============================================"
echo ""

# ── 检测并安装 Homebrew ──────────────────────────────────────
if ! command -v brew &> /dev/null; then
    echo "📦 正在安装 Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for Apple Silicon
    if [ -f "/opt/homebrew/bin/brew" ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
        echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    fi
    echo "✅ Homebrew 安装完成"
else
    echo "✅ Homebrew 已安装"
fi

# ── 检测并安装 Python ────────────────────────────────────────
if ! command -v python3 &> /dev/null || [[ $(python3 -c "import sys; print(sys.version_info >= (3,9))") != "True" ]]; then
    echo "📦 正在安装 Python 3.11..."
    brew install python@3.11
    echo "✅ Python 安装完成"
else
    echo "✅ Python $(python3 --version | cut -d' ' -f2) 已安装"
fi

# ── 检测并安装 Node.js ───────────────────────────────────────
if ! command -v node &> /dev/null; then
    echo "📦 正在安装 Node.js 20..."
    brew install node@20
    brew link node@20 --force
    echo "✅ Node.js 安装完成"
else
    NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
    if [ "$NODE_VERSION" -lt 18 ]; then
        echo "📦 Node.js 版本过低，正在升级到 20..."
        brew install node@20
        brew link node@20 --force --overwrite
        echo "✅ Node.js 升级完成"
    else
        echo "✅ Node.js $(node -v) 已安装"
    fi
fi

# ── 创建 Python 虚拟环境 ─────────────────────────────────────
if [ ! -d "venv" ]; then
    echo "📦 正在创建 Python 虚拟环境..."
    python3 -m venv venv
    echo "✅ 虚拟环境创建完成"
fi

# 激活虚拟环境
source venv/bin/activate

# ── 安装 Python 依赖 ─────────────────────────────────────────
if [ ! -f "venv/.deps_installed" ]; then
    echo "📦 正在安装 Python 依赖（首次运行，可能需要几分钟）..."
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
    touch venv/.deps_installed
    echo "✅ Python 依赖安装完成"
else
    echo "✅ Python 依赖已安装"
fi

# ── 安装 Node.js 依赖 ────────────────────────────────────────
if [ ! -d "node_modules" ]; then
    echo "📦 正在安装 Node.js 依赖..."
    npm install --production --silent
    echo "✅ Node.js 依赖安装完成（根目录）"
fi

if [ ! -d "static/node_modules" ]; then
    echo "📦 正在安装 static Node.js 依赖..."
    cd static && npm install --production --silent && cd ..
    echo "✅ Node.js 依赖安装完成（static）"
fi

# ── 创建日志目录 ─────────────────────────────────────────────
mkdir -p logs

# ── 启动服务 ─────────────────────────────────────────────────
echo ""
echo "============================================"
echo "  🚀 服务启动中..."
echo "  访问地址: http://localhost:5081/xhs"
echo "  首次使用请点击页面上的 ⚙️ 设置按钮"
echo "  配置小红书 Cookie 和微信 API Key"
echo "  关闭此窗口即可停止服务"
echo "============================================"
echo ""

# 延迟 1 秒后打开浏览器
(sleep 2 && open "http://localhost:5081/xhs") &

# 启动 Flask 服务
python app/app.py
