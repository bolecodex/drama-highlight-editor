#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${DRAMA_HIGHLIGHT_REPO_URL:-https://gitee.com/bolecodex/drama-highlight-editor.git}"
BRANCH="${DRAMA_HIGHLIGHT_BRANCH:-main}"
ARKCLAW_HOME="${ARKCLAW_HOME:-${CLAW_HOME:-$HOME/.arkclaw}}"
INSTALL_DIR="${DRAMA_HIGHLIGHT_INSTALL_DIR:-$ARKCLAW_HOME/drama-highlight-editor}"
SKILLS_DIR="${ARKCLAW_SKILLS_DIR:-$ARKCLAW_HOME/skills}"
BIN_DIR="${ARKCLAW_BIN_DIR:-$ARKCLAW_HOME/bin}"
ENV_FILE="${DRAMA_CUT_ENV:-$ARKCLAW_HOME/.env}"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "缺少依赖：$1" >&2
    exit 1
  fi
}

need_cmd git
need_cmd python3

mkdir -p "$ARKCLAW_HOME" "$SKILLS_DIR" "$BIN_DIR"

if [ -d "$INSTALL_DIR/.git" ]; then
  echo "更新 drama-highlight-editor：$INSTALL_DIR"
  git -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH"
  git -C "$INSTALL_DIR" checkout "$BRANCH"
  git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
else
  echo "安装 drama-highlight-editor：$INSTALL_DIR"
  rm -rf "$INSTALL_DIR"
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

echo "安装 Python CLI 依赖..."
python3 -m pip install --user -e "$INSTALL_DIR"

echo "安装 ArkClaw Skill..."
rm -rf "$SKILLS_DIR/drama-highlight-editor"
cp -R "$INSTALL_DIR/skills/drama-highlight-editor" "$SKILLS_DIR/drama-highlight-editor"

cat > "$BIN_DIR/drama-cut" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="$INSTALL_DIR/src\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m drama_cut.cli "\$@"
EOF
chmod +x "$BIN_DIR/drama-cut"

if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<'EOF'
# 火山 Ark / Seed OpenAI 兼容接口配置。
# 将占位值替换为你的真实配置；不要提交该文件。
ARK_API_KEY=你的方舟_API_Key
ARK_MODEL_NAME=你的_Seed_或_Ark_Endpoint_ID
ARK_BASE_URL=https://ark.cn-beijing.volces.com
EOF
  chmod 600 "$ENV_FILE" || true
  echo "已创建配置模板：$ENV_FILE"
else
  echo "保留已有配置文件：$ENV_FILE"
fi

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "提示：未检测到 ffmpeg/ffprobe。合成、预检和导出需要先安装 FFmpeg。" >&2
fi

echo
echo "安装完成。"
echo "Skill 目录：$SKILLS_DIR/drama-highlight-editor"
echo "CLI 命令：$BIN_DIR/drama-cut"
echo "配置文件：$ENV_FILE"
echo
echo "如果当前 shell 找不到 drama-cut，请执行："
echo "  export PATH=\"$BIN_DIR:\$PATH\""
echo
echo "验证："
echo "  $BIN_DIR/drama-cut --help"
