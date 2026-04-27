# JSON 契约

分析文件必须能通过 `drama-cut validate` 校验。

顶层必填字段：

- `drama_name`：字符串，短剧名称。
- `episodes`：源视频文件名数组。
- `total_source_duration_seconds`：数字，原始总时长秒数。
- `summary`：字符串，跨集主线概括。
- `hook`：对象，包含 `enabled`；启用时必须包含 `source_file`、`source_start`、`source_end`、`reason`、`reuse_at`。
- `segments_to_keep`：按故事顺序排列的保留片段数组。
- `segments_to_remove`：删除的不安全或非剧情片段数组。
- `final_structure`：对象，包含 `description`、`estimated_duration_seconds`、`segment_order`。

片段字段：

- `id`：唯一整数。
- `source_file`：必须精确匹配输入目录中的源视频文件名。
- `start_time`、`end_time`：`HH:MM:SS`。
- `duration_seconds`：数字。
- `content`：简短剧情概要。
- `why_keep`：保留它推动主线的理由。

规则：

- `segment_order` 最多只能包含一个 `{"type": "hook"}`。
- 每个 `{"type": "keep", "id": N}` 必须引用已存在的保留片段。
- hook 和片段的结束时间必须晚于开始时间。
- 多集生产必须对整夹目录使用一个总 JSON。
