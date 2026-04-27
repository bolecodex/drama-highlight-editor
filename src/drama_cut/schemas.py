from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .ffmpeg_utils import time_to_seconds
from .utils import read_json

TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?$")


def _validate_time_string(value: str) -> str:
    if not TIME_RE.match(value):
        raise ValueError("时间必须使用 HH:MM:SS 或 HH:MM:SS.mmm 格式")
    return value


class Hook(BaseModel):
    enabled: bool = False
    source_file: Optional[str] = None
    source_start: Optional[str] = None
    source_end: Optional[str] = None
    reason: Optional[str] = None
    reuse_at: Optional[Literal["ending", "original_position"]] = None

    @model_validator(mode="after")
    def validate_enabled_fields(self) -> "Hook":
        if not self.enabled:
            return self
        missing = [name for name in ("source_file", "source_start", "source_end") if getattr(self, name) is None]
        if missing:
            raise ValueError(f"启用 hook 时缺少字段：{', '.join(missing)}")
        _validate_time_string(self.source_start or "")
        _validate_time_string(self.source_end or "")
        if time_to_seconds(self.source_end or "0") <= time_to_seconds(self.source_start or "0"):
            raise ValueError("hook 的 source_end 必须晚于 source_start")
        return self


class Segment(BaseModel):
    id: int = Field(ge=1)
    source_file: str
    start_time: str
    end_time: str
    duration_seconds: Optional[float] = Field(default=None, gt=0)
    content: str = ""
    why_keep: str = ""

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        return _validate_time_string(value)

    @model_validator(mode="after")
    def validate_range(self) -> "Segment":
        if time_to_seconds(self.end_time) <= time_to_seconds(self.start_time):
            raise ValueError(f"片段 {self.id} 的 end_time 必须晚于 start_time")
        return self


class RemoveSegment(BaseModel):
    source_file: str
    start_time: str
    end_time: str
    reason: str

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        return _validate_time_string(value)


class SegmentOrderEntry(BaseModel):
    type: Literal["hook", "keep"]
    id: Optional[int] = None

    @model_validator(mode="after")
    def validate_id(self) -> "SegmentOrderEntry":
        if self.type == "keep" and self.id is None:
            raise ValueError("segment_order 中 type=keep 的条目必须包含 id")
        return self


class FinalStructure(BaseModel):
    description: str = ""
    estimated_duration_seconds: Optional[float] = Field(default=None, ge=0)
    segment_order: List[SegmentOrderEntry] = Field(default_factory=list)


class Version(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    segments_to_keep: List[Segment] = Field(default_factory=list)
    hook: Optional[Hook] = None
    final_structure: FinalStructure = Field(default_factory=FinalStructure)


class HighlightAnalysis(BaseModel):
    drama_name: str
    episodes: List[str] = Field(default_factory=list)
    total_source_duration_seconds: Optional[float] = Field(default=None, ge=0)
    summary: str = ""
    hook: Hook = Field(default_factory=Hook)
    segments_to_keep: List[Segment]
    segments_to_remove: List[RemoveSegment] = Field(default_factory=list)
    final_structure: FinalStructure = Field(default_factory=FinalStructure)
    versions: List[Version] = Field(default_factory=list)
    qa: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def validate_structure(self) -> "HighlightAnalysis":
        ids = [segment.id for segment in self.segments_to_keep]
        if len(ids) != len(set(ids)):
            raise ValueError("片段 id 必须唯一")
        if not self.final_structure.segment_order:
            order = []
            if self.hook.enabled:
                order.append(SegmentOrderEntry(type="hook"))
            order.extend(SegmentOrderEntry(type="keep", id=segment.id) for segment in self.segments_to_keep)
            self.final_structure.segment_order = order
        known = set(ids)
        hook_count = 0
        for entry in self.final_structure.segment_order:
            if entry.type == "hook":
                hook_count += 1
                if not self.hook.enabled:
                    raise ValueError("segment_order 引用了 hook，但 hook.enabled 为 false")
            elif entry.id not in known:
                raise ValueError(f"segment_order 引用了不存在的片段 id：{entry.id}")
        if hook_count > 1:
            raise ValueError("segment_order 最多只能包含一个 hook")
        return self


def load_analysis(path: Path) -> HighlightAnalysis:
    return HighlightAnalysis.model_validate(read_json(path))


def validate_analysis_file(path: Path, video_dir: Optional[Path] = None) -> HighlightAnalysis:
    try:
        analysis = load_analysis(path)
    except ValidationError:
        raise
    if video_dir is not None:
        missing = sorted({s.source_file for s in analysis.segments_to_keep if not (video_dir / s.source_file).exists()})
        hook_file = analysis.hook.source_file if analysis.hook.enabled else None
        if hook_file and not (video_dir / hook_file).exists():
            missing.append(hook_file)
        if missing:
            raise FileNotFoundError(f"在 {video_dir} 中找不到这些 source_file：{', '.join(sorted(set(missing)))}")
    return analysis
