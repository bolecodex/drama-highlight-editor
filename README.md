# drama-highlight-editor

短剧投流高光剪辑 Skill + CLI，面向火山 ArkClaw/Codex 类智能体工作流。核心链路是：整夹跨集分析 → 自动预检/切点精修 → 一次 FFmpeg 合成 → 质检 → 多平台导出。

## 一键安装到 ArkClaw

在 ArkClaw 所在机器执行：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/bolecodex/drama-highlight-editor/main/scripts/setup-github.sh)
```

脚本会完成这些事情：

- 克隆本仓库到 `~/.arkclaw/drama-highlight-editor`
- 安装 Python CLI `drama-cut`
- 安装 Skill 到 `~/.arkclaw/skills/drama-highlight-editor`
- 创建命令包装器 `~/.arkclaw/bin/drama-cut`
- 如果不存在，则创建 ArkClaw 全局配置模板 `~/.arkclaw/.env`

如果命令行找不到 `drama-cut`，把 ArkClaw bin 加入 `PATH`：

```bash
export PATH="$HOME/.arkclaw/bin:$PATH"
```

## ArkClaw `.env` 配置

推荐把全局配置写在：

```text
~/.arkclaw/.env
```

安装脚本会自动创建模板。把其中占位值替换为你的火山 Ark 配置：

```bash
ARK_API_KEY=你的方舟_API_Key
ARK_MODEL_NAME=你的_Seed_或_Ark_Endpoint_ID
ARK_BASE_URL=https://ark.cn-beijing.volces.com
```

说明：

- `ARK_MODEL_NAME` 可以直接填写 Seed/Ark endpoint id，例如 `ep-xxxxxxxxxxxxxxxx-xxxxx`。
- `ARK_BASE_URL` 可以写 `https://ark.cn-beijing.volces.com`，CLI 会自动补齐 `/api/v3`。
- 兼容旧变量名 `TEXT_ENDPOINT`；如果同时存在，优先使用 `ARK_MODEL_NAME`。
- 不要把真实 `.env` 提交到 Git；仓库只提供 `.env.example`。

也可以在项目目录放一个局部 `.env`，CLI 会从输入视频所在目录向上查找 `.env`。查找优先级为：

1. `DRAMA_CUT_ENV` 指定的文件
2. 输入路径或当前目录向上的 `.env`
3. `~/.arkclaw/.env`
4. 当前 shell 环境变量

## ArkClaw 调用技能示例

在 ArkClaw 中可以直接这样请求：

```text
调用 drama-highlight-editor 技能，将 video 文件夹中的短剧分集剪辑为一条投流素材。
要求：使用 family 模板，输出到 video/output，先跨集分析，再预检/精修，最后合成成片。
```

技能会优先走整夹跨集分析，避免逐集产生多个 hook，并在合成前执行预检/精修，拦截重复 recap、黑/闪边界、对白截断和明显顺序问题。

## CLI 常用命令

```bash
# 查看帮助
drama-cut --help

# 一键生产：ASR/静音边界辅助 → 跨集分析 → 自动精修 → 预检 → 合成 → 评分/导出
drama-cut 生产 "video" --template family --name "老公的白月光" -o "video/output" --yes

# 分步执行
drama-cut 分析 "video" --template family --name "老公的白月光" -o "video/output"
drama-cut 预检 "video/output/highlights_老公的白月光.json" "video" -o "video/output"
drama-cut 精修 "video/output/highlights_老公的白月光.json" "video" -o "video/output/highlights_老公的白月光_refined.json"
drama-cut 合成 "video/output/highlights_老公的白月光_refined.json" "video" --name "老公的白月光" -o "video/output"

# 多平台导出
drama-cut 导出 "video/output/promo_老公的白月光.mp4" -o "video/output/exports" -p douyin -p wechat_video
```

英文命令别名也可用：`analyze`、`qa`、`refine`、`compose`、`produce`、`export`。

## 本地开发

```bash
python3 -m pip install --user -e .
python3 -m unittest discover -v
./bin/drama-cut --help
```

需要系统已安装 `ffmpeg` 和 `ffprobe`。
