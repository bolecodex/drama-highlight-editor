from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import click
import click.core
import click.decorators
import click.formatting
import typer
import typer.rich_utils
from pydantic import ValidationError

from . import __version__
from .analysis import analyze
from .asr import transcribe_input
from .compose import compose
from .export import PLATFORM_PRESETS, export_all
from .quality import score
from .review import has_blocking_issues, preflight_analysis, refine_analysis_file, report_summary
from .schemas import validate_analysis_file
from .templates import list_templates
from .utils import read_json


_CLICK_ZH = {
    "Usage:": "用法：",
    "Options": "选项",
    "Commands": "命令",
    "Arguments": "参数",
    "Show this message and exit.": "显示此帮助信息并退出。",
}


def _zh_gettext(message: str) -> str:
    return _CLICK_ZH.get(message, message)


click.core._ = _zh_gettext
click.decorators._ = _zh_gettext
click.formatting._ = _zh_gettext
typer.rich_utils.OPTIONS_PANEL_TITLE = "选项"
typer.rich_utils.COMMANDS_PANEL_TITLE = "命令"
typer.rich_utils.ARGUMENTS_PANEL_TITLE = "参数"

app = typer.Typer(
    help="短剧投流高光分析、切片合成、质检与多平台导出工具。",
    add_completion=False,
    options_metavar="[选项]",
    subcommand_metavar="命令 [参数]...",
)
templates_app = typer.Typer(
    help="查看内置剪辑提示词模板。",
    add_completion=False,
    options_metavar="[选项]",
    subcommand_metavar="命令 [参数]...",
)
app.add_typer(templates_app, name="templates")
app.add_typer(templates_app, name="模板")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"drama-cut {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", callback=version_callback, is_eager=True, help="显示版本号。"),
) -> None:
    return None


@templates_app.command("list")
@templates_app.command("列表")
def templates_list() -> None:
    """列出内置剪辑模板。"""
    for item in list_templates():
        typer.echo(f"{item['id']}\t{item['name']}\t{item['description']}")


@app.command()
@app.command("验证")
def validate(
    analysis_json: Path = typer.Argument(..., exists=True, dir_okay=False, help="高光分析 JSON 文件。"),
    video_dir: Optional[Path] = typer.Option(None, "--video-dir", "-v", help="可选：原始视频目录，用于校验 source_file。"),
) -> None:
    """校验高光分析 JSON 与可选 source_file 引用。"""
    try:
        analysis = validate_analysis_file(analysis_json, video_dir)
    except (ValidationError, FileNotFoundError, ValueError) as exc:
        typer.secho(f"校验失败：{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    typer.secho(
        f"校验通过：{analysis_json}（保留片段 {len(analysis.segments_to_keep)} 个，hook={analysis.hook.enabled}）",
        fg=typer.colors.GREEN,
    )


@app.command()
@app.command("转写")
def asr(
    input_path: Path = typer.Argument(..., exists=True, help="视频文件或短剧目录。"),
    output_dir: Path = typer.Option(Path("video/output"), "--output-dir", "-o", help="输出目录。"),
    method: str = typer.Option("auto", "--method", help="转写方式：auto、ark 或 silence。"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Ark 模型或 endpoint 覆盖值。"),
) -> None:
    """为单个视频或多集目录提取 ASR 台词时间戳。"""
    if method not in {"auto", "ark", "silence"}:
        typer.secho("--method 必须是 auto、ark 或 silence", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    outputs = transcribe_input(input_path, output_dir, method=method, model=model)
    typer.secho(f"ASR 完成：生成 {len(outputs)} 个文件", fg=typer.colors.GREEN)


@app.command("analyze")
@app.command("分析")
def analyze_cmd(
    input_dir: Path = typer.Argument(..., exists=True, help="短剧目录或单个视频。"),
    template: str = typer.Option("default", "--template", "-t", help="剪辑模板 id。"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="输出名称，不含 highlights_ 前缀。"),
    output_dir: Path = typer.Option(Path("video/output"), "--output-dir", "-o", help="输出目录。"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Ark 模型或 endpoint 覆盖值。"),
    multi_version: bool = typer.Option(False, "--multi-version", help="生成激进版、标准版、保守版多版本方案。"),
    auto_refine: bool = typer.Option(True, "--auto-refine/--no-auto-refine", help="分析后自动执行投流预检与切点精修。"),
) -> None:
    """跨集分析短剧高光，并输出一个 highlights JSON。"""
    path = analyze(
        input_dir,
        output_dir,
        template_id=template,
        name=name,
        model=model,
        multi_version=multi_version,
        auto_refine=auto_refine,
    )
    typer.secho(f"分析 JSON：{path}", fg=typer.colors.GREEN)


@app.command("qa")
@app.command("预检")
def qa_cmd(
    analysis_json: Path = typer.Argument(..., exists=True, dir_okay=False, help="高光分析 JSON 文件。"),
    video_dir: Path = typer.Argument(..., exists=True, file_okay=False, help="原始视频目录。"),
    output_dir: Path = typer.Option(Path("video/output"), "--output-dir", "-o", help="QA 报告输出目录。"),
    allow_risky: bool = typer.Option(False, "--allow-risky", help="即使存在严重问题也返回成功状态。"),
) -> None:
    """只做投流剪辑预检，不执行合成。"""
    report = preflight_analysis(analysis_json, video_dir, output_dir)
    color = typer.colors.GREEN if not has_blocking_issues(report) else typer.colors.RED
    typer.secho(report_summary(report), fg=color)
    if report.get("report_path"):
        typer.echo(f"QA 报告：{report['report_path']}")
    if has_blocking_issues(report) and not allow_risky:
        raise typer.Exit(1)


@app.command("refine")
@app.command("精修")
def refine_cmd(
    analysis_json: Path = typer.Argument(..., exists=True, dir_okay=False, help="待精修的高光分析 JSON 文件。"),
    video_dir: Path = typer.Argument(..., exists=True, file_okay=False, help="原始视频目录。"),
    output_json: Optional[Path] = typer.Option(None, "--output-json", "-o", help="修正版 JSON 路径；默认写到 *_refined.json。"),
) -> None:
    """根据预检规则自动精修切点，并写出修正版 JSON。"""
    output = refine_analysis_file(analysis_json, video_dir, output_json)
    data = read_json(output)
    report = data.get("qa") or preflight_analysis(output, video_dir, output.parent)
    color = typer.colors.GREEN if not has_blocking_issues(report) else typer.colors.YELLOW
    typer.secho(f"精修 JSON：{output}", fg=typer.colors.GREEN)
    typer.secho(report_summary(report), fg=color)


@app.command("compose")
@app.command("合成")
def compose_cmd(
    analysis_json: Path = typer.Argument(..., exists=True, dir_okay=False, help="高光分析 JSON 文件。"),
    video_dir: Path = typer.Argument(..., exists=True, file_okay=False, help="原始视频目录。"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="输出名称，不含 promo_ 前缀。"),
    output_dir: Path = typer.Option(Path("video/output"), "--output-dir", "-o", help="输出目录。"),
    crossfade: float = typer.Option(0.0, "--crossfade", min=0.0, help="片段间交叉淡化时长（秒）。"),
    reencode: bool = typer.Option(True, "--reencode/--no-reencode", help="重编码以获得帧级精确切点。"),
    normalize_audio: bool = typer.Option(True, "--normalize/--no-normalize", help="应用音频响度归一化。"),
    strict_preflight: bool = typer.Option(True, "--strict-preflight/--no-strict-preflight", help="合成前执行严格投流预检。"),
    allow_risky: bool = typer.Option(False, "--allow-risky", help="预检发现严重问题时仍继续合成。"),
) -> None:
    """根据一个跨集分析 JSON 切片并合成为一条投流素材。"""
    output = compose(
        analysis_json,
        video_dir,
        output_dir,
        name=name,
        reencode=reencode,
        crossfade=crossfade,
        normalize_audio=normalize_audio,
        strict_preflight=strict_preflight,
        allow_risky=allow_risky,
    )
    typer.secho(f"成片视频：{output}", fg=typer.colors.GREEN)


@app.command("score")
@app.command("评分")
def score_cmd(
    video: Path = typer.Argument(..., exists=True, dir_okay=False, help="待评分的投流成片。"),
    output_dir: Path = typer.Option(Path("video/output"), "--output-dir", "-o", help="输出目录。"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Ark 模型或 endpoint 覆盖值。"),
) -> None:
    """对已生成的投流素材做 AI 质量评分。"""
    out = score(video, output_dir, model=model)
    typer.secho(f"评分 JSON：{out}", fg=typer.colors.GREEN)


@app.command("export")
@app.command("导出")
def export_cmd(
    video: Path = typer.Argument(..., exists=True, dir_okay=False, help="待导出的投流成片。"),
    output_dir: Path = typer.Option(Path("video/output/exports"), "--output-dir", "-o", help="输出目录。"),
    platforms: Optional[List[str]] = typer.Option(None, "--platforms", "-p", help="平台 id 列表。"),
    method: str = typer.Option("crop", "--method", help="画面适配方式：crop、scale 或 stretch。"),
    list_platforms: bool = typer.Option(False, "--list-platforms", help="列出平台预设后退出。"),
) -> None:
    """按平台规格导出投流素材。"""
    if list_platforms:
        for pid, preset in PLATFORM_PRESETS.items():
            typer.echo(f"{pid}\t{preset['name']}\t{preset['width']}x{preset['height']}\t{preset['aspect']}")
        return
    if method not in {"crop", "scale", "stretch"}:
        typer.secho("--method 必须是 crop、scale 或 stretch", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    out = export_all(video, output_dir, platforms=platforms, method=method)
    typer.secho(f"导出清单：{out}", fg=typer.colors.GREEN)


@app.command()
@app.command("生产")
def produce(
    input_dir: Path = typer.Argument(..., exists=True, help="包含短剧分集的目录。"),
    template: str = typer.Option("default", "--template", "-t", help="剪辑模板 id。"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="输出名称。"),
    output_dir: Path = typer.Option(Path("video/output"), "--output-dir", "-o", help="输出目录。"),
    review: bool = typer.Option(True, "--review/--yes", help="合成前审核分析 JSON；--yes 表示跳过人工确认。"),
    platforms: Optional[List[str]] = typer.Option(None, "--platforms", "-p", help="导出平台 id 列表。"),
    skip_asr: bool = typer.Option(False, "--skip-asr", help="跳过 ASR 预处理。"),
    skip_score: bool = typer.Option(False, "--skip-score", help="跳过 AI 质量评分。"),
    skip_export: bool = typer.Option(False, "--skip-export", help="跳过平台规格导出。"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Ark 模型或 endpoint 覆盖值。"),
    auto_refine: bool = typer.Option(True, "--auto-refine/--no-auto-refine", help="分析后自动执行投流预检与切点精修。"),
    allow_risky: bool = typer.Option(False, "--allow-risky", help="预检发现严重问题时仍继续合成。"),
) -> None:
    """一键执行 ASR、跨集分析、自动精修、预检、合成、评分和平台导出。"""
    safe_name = name or input_dir.stem
    if not skip_asr:
        transcribe_input(input_dir, output_dir, method="auto", model=model)
    analysis_json = analyze(input_dir, output_dir, template_id=template, name=safe_name, model=model, auto_refine=auto_refine)
    report = preflight_analysis(analysis_json, input_dir, output_dir)
    typer.echo(report_summary(report))
    if has_blocking_issues(report) and not allow_risky:
        typer.secho("生产已停止：预检存在严重问题。请先运行 drama-cut 精修 或人工修正 JSON。", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    if review:
        if sys.stdin.isatty():
            typer.echo(f"请按需审核/修改分析 JSON：{analysis_json}")
            if not typer.confirm("继续合成吗？"):
                raise typer.Exit()
        else:
            typer.echo(f"当前为非交互会话，跳过人工审核并继续。JSON：{analysis_json}")
    promo = compose(analysis_json, input_dir, output_dir, name=safe_name, allow_risky=allow_risky)
    if not skip_score:
        try:
            score(promo, output_dir, model=model)
        except Exception as exc:
            typer.secho(f"评分失败，已跳过：{exc}", fg=typer.colors.YELLOW, err=True)
    if not skip_export:
        export_all(promo, output_dir / "exports", platforms=platforms or ["douyin", "wechat_video"])
    typer.secho(f"完成。分析 JSON：{analysis_json}\n成片视频：{promo}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
