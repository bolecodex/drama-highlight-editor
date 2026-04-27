# 排错指南

## 出现多个 Hook

原因：逐集分别分析了视频。

修复：对整夹目录只运行一次 `drama-cut analyze`，再用生成的顶层 JSON 运行一次 `drama-cut compose`。

## 找不到源文件

运行：

```bash
drama-cut validate "video/output/highlights_x.json" --video-dir "video/原片目录"
```

确认每个 `source_file` 都精确匹配原片目录中的文件名。

## 切断台词或切点不自然

分析前先跑 ASR，让模型参考台词边界：

```bash
drama-cut asr "video/原片目录" -o "video/output"
drama-cut analyze "video/原片目录" -o "video/output"
```

必要时手动调整 `start_time` / `end_time`，再重新合成。

也可以先让 CLI 自动精修：

```bash
drama-cut 精修 "video/output/highlights_x.json" "video/原片目录" -o "video/output/highlights_x_refined.json"
drama-cut 预检 "video/output/highlights_x_refined.json" "video/原片目录" -o "video/output"
```

## 重复镜头或集头前情回顾

症状：后续分集开头重复上一段尾部，或相邻片段出现同一事故/同一句对白。

修复：

```bash
drama-cut 预检 "video/output/highlights_x.json" "video/原片目录" -o "video/output"
drama-cut 精修 "video/output/highlights_x.json" "video/原片目录" -o "video/output/highlights_x_refined.json"
```

如果预检仍报 `recap_zero_start_risk`，人工检查该集开头，确认不是前情回顾后才使用 `--allow-risky`。

## 什么时候允许 --allow-risky

只在以下场景使用：

- 已人工确认非首个源分集的起点不是前情回顾。
- 预检误判相邻画面重复，但剧情确实连续且不影响观看。
- 需要保留平台可接受的风格化闪白或黑场，且不是片头片尾残留。

不要用 `--allow-risky` 跳过对白截断、源文件缺失、时间越界或明显重复 recap。

## FFmpeg 失败

- 确认 `ffmpeg` 和 `ffprobe` 在 PATH 中。
- 保持 `--reencode` 开启，以获得更精确切点。
- 只有音频滤镜失败时才使用 `--no-normalize`。
- 如果平台导出裁掉关键人脸，用 `--method scale` 重新导出。
