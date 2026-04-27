---
name: drama-highlight-editor
description: >
  用于制作短剧投流素材：跨集高光分析、全局唯一 hook、结构化高光 JSON、FFmpeg 切片合成、
  质量评分和多平台导出。当用户提出短剧投流、高光剪辑、信息流广告素材、跨集剪辑、
  高光提取、按时间戳剪视频、成片合成等需求时使用。
allowed-tools: Read, Grep, Bash, Agent, Task
---

# 短剧投流高光剪辑

把多集短剧制作成一条连贯、可投放的信息流广告素材。

## 核心规则

多集输入必须对整夹目录做一次跨集分析，生成一个 `highlights_*.json`。
不要逐集分别分析，否则会变成每集一个 hook，剧情也会断裂。
分析后必须先做预检/精修，再合成；不要把模型原始 JSON 直接送进 FFmpeg。
非首个源分集如果从起点开始，默认视为前情回顾高风险，必须通过预检或人工确认。
对白短剧默认不用 crossfade，只有音乐蒙太奇或无关键对白的转场才考虑。

## 工作流

1. 确认目录中包含原始分集；如果切点依赖台词，先跑 ASR：
   ```bash
   drama-cut asr "video/某短剧" -o "video/output"
   ```
2. 使用合适模板做跨集分析：
   ```bash
   drama-cut analyze "video/某短剧" --template default --name 某短剧 -o "video/output"
   ```
3. 对分析 JSON 做投流预检；如失败，先精修：
   ```bash
   drama-cut 预检 "video/output/highlights_某短剧.json" "video/某短剧" -o "video/output"
   drama-cut 精修 "video/output/highlights_某短剧.json" "video/某短剧" -o "video/output/highlights_某短剧_refined.json"
   ```
4. 用预检通过的同一个 JSON 和原片目录合成一次：
   ```bash
   drama-cut compose "video/output/highlights_某短剧.json" "video/某短剧" --name 某短剧 -o "video/output"
   ```
5. 按需评分和导出，或直接使用一键生产命令：
   ```bash
   drama-cut produce "video/某短剧" --template default --name 某短剧 -o "video/output" --yes
   ```

收尾回复必须明确写出最终 `highlights_*.json`、`qa_*.json` 和 `promo_*.mp4` 路径。

## 并行策略

可对彼此独立、偏阅读分析的步骤使用 spawn 并行；切片前必须 fan-in 汇总：

- 可并行：逐集 ASR、场景/切点检查、合规预检、模板适配判断。
- 必须串行汇总：跨集主线分析、唯一 hook 选择、JSON 校验、预检、切点精修。
- 必须串行生产：FFmpeg 合成和平台导出，因为它们依赖最终 JSON。

## 参考文件

- 剪辑标准：`references/editing-criteria.md`
- JSON 契约：`references/json-schema.md`
- 模板选择：`references/template-guide.md`
- 排错指南：`references/troubleshooting.md`
