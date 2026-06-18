#!/bin/bash
# 服务器端一键配置 git bare repo 部署
# 用法：bash setup-git-deploy.sh
# 在服务器上执行一次即可

set -e

BACKEND_BARE=/opt/git/trader-analysis.git
BACKEND_WORK=/opt/trader-analysis

FRONTEND_BARE=/opt/git/trader-frontend.git
FRONTEND_WORK=/opt/trader-frontend

echo "======================================"
echo " 配置 Git 自动部署"
echo "======================================"

# ── 后端 ──────────────────────────────────
echo ""
echo "[1/4] 创建后端裸仓库..."
mkdir -p "$BACKEND_BARE"
git init --bare "$BACKEND_BARE"

echo "[2/4] 写入后端 post-receive hook..."
cat > "$BACKEND_BARE/hooks/post-receive" << 'HOOK'
#!/bin/bash
while read oldrev newrev refname; do
    branch=$(git rev-parse --symbolic --abbrev-ref "$refname")
    if [ "$branch" = "main" ]; then
        echo "==> [后端] 收到推送，开始部署..."
        GIT_WORK_TREE=/opt/trader-analysis git checkout -f main
        systemctl restart trader-api
        echo "✅ [后端] 部署完成"
    fi
done
HOOK
chmod +x "$BACKEND_BARE/hooks/post-receive"

# ── 前端 ──────────────────────────────────
echo "[3/4] 创建前端裸仓库..."
mkdir -p "$FRONTEND_BARE"
git init --bare "$FRONTEND_BARE"
mkdir -p "$FRONTEND_WORK"

echo "[4/4] 写入前端 post-receive hook..."
cat > "$FRONTEND_BARE/hooks/post-receive" << 'HOOK'
#!/bin/bash
export PATH=$PATH:/usr/local/bin:/usr/bin
while read oldrev newrev refname; do
    branch=$(git rev-parse --symbolic --abbrev-ref "$refname")
    if [ "$branch" = "main" ]; then
        echo "==> [前端] 收到推送，开始构建..."
        GIT_WORK_TREE=/opt/trader-frontend git checkout -f main
        cd /opt/trader-frontend
        npm ci --silent
        npm run build
        rm -rf /var/www/trader-frontend/*
        cp -r dist/* /var/www/trader-frontend/
        echo "✅ [前端] 部署完成"
    fi
done
HOOK
chmod +x "$FRONTEND_BARE/hooks/post-receive"

echo ""
echo "======================================"
echo " 服务器配置完成！"
echo ""
echo " 现在在本地执行以下命令添加 remote："
echo ""
echo " # 后端"
echo " cd /f/TraderAnalysis"
echo " git remote set-url --add --push origin git@github.com:Chunxia-zzz/TraderAnalysis.git"
echo " git remote set-url --add --push origin root@47.106.175.84:/opt/git/trader-analysis.git"
echo ""
echo " # 前端"
echo " cd /f/TraderAnalysisFrontend"
echo " git remote set-url --add --push origin git@github.com:Chunxia-zzz/TraderAnalysisFrontend.git"
echo " git remote set-url --add --push origin root@47.106.175.84:/opt/git/trader-frontend.git"
echo "======================================"
