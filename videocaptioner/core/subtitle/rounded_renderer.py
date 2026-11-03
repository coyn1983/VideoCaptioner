"""Rounded background subtitle renderer"""

import os
import re
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional, Tuple

from PIL import Image, ImageDraw

from videocaptioner.core.entities import SubtitleLayoutEnum
from videocaptioner.core.utils.logger import setup_logger

from .font_utils import FontType, get_font
from .styles import RoundedBgStyle
from .text_utils import hex_to_rgba, wrap_text

if TYPE_CHECKING:
    from videocaptioner.core.asr.asr_data import ASRData

logger = setup_logger("subtitle.rounded")


def _get_video_info(video_path: str) -> Tuple[int, int, float]:
    """获取视频分辨率和时长"""
    result = subprocess.run(
        ["ffmpeg", "-i", video_path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
    )

    # 解析分辨率
    width, height = 0, 0
    if match := re.search(r"Stream.*Video:.* (\d{2,5})x(\d{2,5})", result.stderr):
        width, height = int(match.group(1)), int(match.group(2))
    else:
        raise ValueError(f"Cannot get video resolution: {video_path}")

    # 解析时长
    duration = 0.0
    if match := re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr):
        h, m, s = match.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)

    return width, height, duration

CHUNK_SIZE = 50


def _run_ffmpeg(args):
    """执行 ffmpeg，失败时抛出带 stderr 的异常。"""
    result = subprocess.run(
        ["ffmpeg", *args],
        capture_output=True,
        text=True,
        # ffmpeg 会按 UTF-8 输出文件名等；显式指定编码，避免中文 Windows（GBK）
        # 下解码失败导致 stderr 变成 None（与 _get_video_info 同源问题）。
        encoding="utf-8",
        errors="replace",
        creationflags=(
            getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        ),
    )
    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg failed: ffmpeg "
            + " ".join(args[:12])
            + "\n\n"
            + (result.stderr or "")[-4000:]
        )


def _get_audio_codec(video_path: str) -> str:
    """返回音轨编码名（无音轨时返回空串）。"""
    result = subprocess.run(
        ["ffmpeg", "-i", video_path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=(
            getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        ),
    )
    match = re.search(r"Audio:\s*([A-Za-z0-9_]+)", result.stderr or "")
    return match.group(1).lower() if match else ""


def _plan_chunks(frames, duration: float, chunk_size: int):
    """把时间轴切成互不重叠、首尾相接的连续区间。

    切点只落在字幕之间的空档里，保证没有任何一条字幕被切成两半。
    返回 [(chunk_start, chunk_end, [(start, end, png_path), ...]), ...]，
    这些区间合起来正好覆盖 [0, duration]，因此拼接后与源视频等长。
    """
    chunks = []
    total = len(frames)
    idx = 0
    cur_start = 0.0

    while idx < total:
        last = min(idx + chunk_size - 1, total - 1)

        if last == total - 1:
            chunks.append((cur_start, duration, frames[idx:]))
            break

        boundary = None
        probe = last
        # 相邻字幕若有重叠，该处不能切分，向后顺延找下一个空档
        while probe < total - 1:
            gap_start = frames[probe][1]
            gap_end = frames[probe + 1][0]
            candidate = (
                (gap_start + gap_end) / 2.0 if gap_end > gap_start else gap_start
            )
            if candidate > cur_start:
                boundary = candidate
                last = probe
                break
            probe += 1

        if boundary is None:
            chunks.append((cur_start, duration, frames[idx:]))
            break

        chunks.append((cur_start, boundary, frames[idx : last + 1]))
        cur_start = boundary
        idx = last + 1

    return chunks



def render_text_block(
    draw: ImageDraw.ImageDraw,
    texts: List[str],
    font: FontType,
    center_x: int,
    top_y: float,
    style: RoundedBgStyle,
) -> float:
    """
    渲染多行文本块（共享圆角背景）

    Args:
        draw: PIL ImageDraw 对象
        texts: 文本行列表
        font: 字体对象
        center_x: 水平中心位置
        top_y: 顶部 y 坐标
        style: 样式配置

    Returns:
        背景框高度
    """
    if not texts:
        return 0

    bg_color = hex_to_rgba(style.bg_color)
    text_color = hex_to_rgba(style.text_color)

    # 计算All行的尺寸和垂直偏移
    line_sizes = []
    line_offsets = []
    for text in texts:
        bbox = font.getbbox(text)
        text_width = bbox[2] - bbox[0]
        # 如果有字符间距，需要加上额外的宽度
        if style.letter_spacing > 0 and len(text) > 1:
            text_width += style.letter_spacing * (len(text) - 1)
        line_sizes.append((text_width, bbox[3] - bbox[1]))
        line_offsets.append(bbox[1])  # 记录垂直偏移，用于居中对齐

    max_width = max(w for w, h in line_sizes)
    line_height = max(h for w, h in line_sizes)
    total_height = line_height * len(texts) + style.line_spacing * (len(texts) - 1)

    # 绘制共享背景
    bg_width = max_width + style.padding_h * 2
    bg_height = total_height + style.padding_v * 2
    bg_left = center_x - bg_width // 2
    bg_top = top_y

    draw.rounded_rectangle(
        [bg_left, bg_top, bg_left + bg_width, bg_top + bg_height],
        radius=style.corner_radius,
        fill=bg_color,
    )

    # 绘制文本（补偿字体垂直偏移）
    y = bg_top + style.padding_v
    for i, text in enumerate(texts):
        w, h = line_sizes[i]
        x = center_x - w // 2
        y_offset = line_offsets[i]
        text_y = y - y_offset  # 补偿垂直偏移，使文本视觉居中

        # 如果有字符间距，逐字符绘制
        if style.letter_spacing > 0 and len(text) > 1:
            current_x = x
            for char in text:
                draw.text((current_x, text_y), char, font=font, fill=text_color)
                char_width = font.getbbox(char)[2] - font.getbbox(char)[0]
                current_x += char_width + style.letter_spacing
        else:
            # 无字符间距，一次性绘制（性能更好）
            draw.text((x, text_y), text, font=font, fill=text_color)

        y += line_height + style.line_spacing

    return bg_height


def render_subtitle_image(
    primary_text: str,
    secondary_text: str,
    width: int,
    height: int,
    style: RoundedBgStyle,
) -> Image.Image:
    """
    渲染单帧字幕图像（透明背景）

    Args:
        primary_text: 主字幕文本
        secondary_text: 副字幕文本
        width: 图像宽度
        height: 图像高度
        style: 样式配置

    Returns:
        PIL Image 对象（RGBA 格式）
    """
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = get_font(style.font_size, style.font_name)

    # 换行处理（额外留 40px 边距防止文字贴边）
    extra_margin = int(width * 0.1)
    primary_lines = (
        wrap_text(primary_text, font, width, style.padding_h, extra_margin=extra_margin)
        if primary_text
        else []
    )
    secondary_lines = (
        wrap_text(secondary_text, font, width, style.padding_h, extra_margin=extra_margin)
        if secondary_text
        else []
    )

    center_x = width // 2

    # 计算总高度
    def calc_block_height(lines: List[str]) -> float:
        if not lines:
            return 0
        bbox = font.getbbox("测试Ag")
        line_h = bbox[3] - bbox[1]
        return line_h * len(lines) + style.line_spacing * (len(lines) - 1) + style.padding_v * 2

    primary_height = calc_block_height(primary_lines)
    secondary_height = calc_block_height(secondary_lines)
    gap = style.line_spacing if primary_lines and secondary_lines else 0
    total_height = primary_height + gap + secondary_height

    # 从底部计算起始位置
    bottom_y = height - style.margin_bottom
    start_y = bottom_y - total_height

    # 渲染文本块
    current_y = start_y
    if primary_lines:
        h = render_text_block(draw, primary_lines, font, center_x, current_y, style)
        current_y += h + gap
    if secondary_lines:
        render_text_block(draw, secondary_lines, font, center_x, current_y, style)

    return image


def render_preview(
    primary_text: str,
    secondary_text: str = "",
    width: Optional[int] = None,
    height: Optional[int] = None,
    style: Optional[RoundedBgStyle] = None,
    bg_image_path: Optional[str] = None,
    reference_height: int = 720,
) -> str:
    """
    渲染圆角背景字幕预览图

    Args:
        primary_text: 主字幕文本
        secondary_text: 副字幕文本
        width: 图片宽度（None=从bg_image_path自动获取）
        height: 图片高度（None=从bg_image_path自动获取）
        style: 圆角背景样式（包含reference_height，会根据height自动缩放）
        bg_image_path: 背景图片路径
        reference_height: 参考高度（固定720P）
    Returns:
        生成的预览图路径
    """
    if style is None:
        style = RoundedBgStyle()

    # 加载或创建背景
    if bg_image_path and Path(bg_image_path).exists():
        background = Image.open(bg_image_path).convert("RGB")
        # 如果未提供尺寸，从图片获取
        if width is None or height is None:
            width, height = background.size
    else:
        # 没有背景图片，使用默认尺寸或提供的尺寸
        if width is None:
            width = 1920
        if height is None:
            height = 1080
        background = Image.new("RGB", (width, height), (20, 20, 20))

    # 确保 width 和 height 不为 None（类型收窄）
    assert width is not None and height is not None

    # 从样式中获取参考高度，根据图片高度自动缩放样式
    scale_factor = height / reference_height

    if scale_factor != 1.0:
        style = replace(
            style,
            font_size=int(style.font_size * scale_factor),
            corner_radius=int(style.corner_radius * scale_factor),
            padding_h=int(style.padding_h * scale_factor),
            padding_v=int(style.padding_v * scale_factor),
            margin_bottom=int(style.margin_bottom * scale_factor),
            line_spacing=int(style.line_spacing * scale_factor),
            letter_spacing=int(style.letter_spacing * scale_factor),
        )

    # 渲染字幕并叠加
    subtitle_img = render_subtitle_image(primary_text, secondary_text, width, height, style)
    background.paste(subtitle_img, (0, 0), subtitle_img)

    # 保存到临时目录
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".png", delete=False) as tmp_file:
        background.save(tmp_file, "PNG")
        return tmp_file.name


def render_rounded_video(
    video_path: str,
    asr_data: "ASRData",
    output_path: str,
    rounded_style: Optional[dict] = None,
    layout: SubtitleLayoutEnum = SubtitleLayoutEnum.ONLY_ORIGINAL,
    crf: int = 23,
    preset: str = "medium",
    progress_callback: Optional[Callable] = None,
    reference_height: int = 720,
) -> None:
    """
    渲染圆角背景字幕到视频（时间分段编码方案）

    核心流程:
    1. 每条字幕渲染成一张透明 PNG
    2. 把时间轴切成首尾相接的连续区间（切点只落在字幕空档），每段只编码这一段、
       只叠加该段的字幕图，所有分段共用同一组编码参数
    3. 用 concat 无损拼接所有分段
    4. 挂回原始音轨（直接 copy）

    这样整部视频只完整编码一遍。旧实现是「每批都把整部视频重编码一遍」，代价是
    O(批次数 × 视频时长)，长视频下既极慢又会撑爆临时空间。

    Args:
        video_path: 输入视频路径
        asr_data: 字幕数据
        output_path: 输出视频路径
        rounded_style: 圆角背景样式配置字典
        layout: 字幕布局
        crf: 视频质量参数
        preset: FFmpeg编码预设
        progress_callback: 进度回调 (progress: int, message: str)
        reference_height: 参考高度（固定720P）
    """
    # 检查字幕数据
    if not asr_data or not asr_data.segments:
        raise ValueError("Empty subtitle data, cannot render video")

    # 检查布局合理性
    if layout == SubtitleLayoutEnum.ONLY_TRANSLATE:
        has_translation = any(
            seg.translated_text and seg.translated_text.strip() for seg in asr_data.segments
        )
        if not has_translation:
            layout = SubtitleLayoutEnum.ONLY_ORIGINAL
    elif (
        layout == SubtitleLayoutEnum.TRANSLATE_ON_TOP
        or layout == SubtitleLayoutEnum.ORIGINAL_ON_TOP
    ):
        has_translation = any(
            seg.translated_text and seg.translated_text.strip() for seg in asr_data.segments
        )
        if not has_translation:
            layout = SubtitleLayoutEnum.ONLY_ORIGINAL

    # 获取视频信息
    width, height, video_duration = _get_video_info(video_path)

    # 构建并缩放样式
    style_config = rounded_style or {}
    style_config["layout"] = layout
    style = RoundedBgStyle(**style_config)

    scale_factor = height / reference_height
    if scale_factor != 1.0:
        style = replace(
            style,
            font_size=int(style.font_size * scale_factor),
            corner_radius=int(style.corner_radius * scale_factor),
            padding_h=int(style.padding_h * scale_factor),
            padding_v=int(style.padding_v * scale_factor),
            margin_bottom=int(style.margin_bottom * scale_factor),
            line_spacing=int(style.line_spacing * scale_factor),
            letter_spacing=int(style.letter_spacing * scale_factor),
        )

    with tempfile.TemporaryDirectory(prefix="rounded_subtitle_") as temp_dir:
        temp_path = Path(temp_dir)

        # 步骤1: 生成All字幕PNG (0-30%)
        logger.debug(f"Generating subtitle PNGs图片（共{len(asr_data.segments)}个，布局: {layout.value}）")
        subtitle_frames = []

        for i, seg in enumerate(asr_data.segments):
            # 根据布局确定主副文本
            if layout == SubtitleLayoutEnum.ONLY_ORIGINAL:
                primary, secondary = seg.text, ""
            elif layout == SubtitleLayoutEnum.ONLY_TRANSLATE:
                primary, secondary = seg.translated_text or "", ""
            elif layout == SubtitleLayoutEnum.ORIGINAL_ON_TOP:
                primary, secondary = seg.text, seg.translated_text or ""
            else:  # TRANSLATE_ON_TOP
                primary, secondary = seg.translated_text or "", seg.text

            # 渲染字幕图片
            img = render_subtitle_image(primary, secondary, width, height, style)
            png_path = temp_path / f"subtitle_{i:06d}.png"
            img.save(png_path, "PNG")

            # 记录时间戳
            start_time = seg.start_time / 1000.0
            end_time = seg.end_time / 1000.0
            subtitle_frames.append((start_time, end_time, png_path))

            # 进度回调
            if progress_callback:
                progress = int((i + 1) / len(asr_data.segments) * 30)
                progress_callback(progress, f"生成字幕图片 {i + 1}/{len(asr_data.segments)}")

        if not subtitle_frames:
            raise ValueError("No valid subtitle images generated")

        # 步骤2: 按时间区间分段编码 (30-95%)
        #
        # 旧实现是「每批都把整部视频重编码一遍」：代价是 O(批次数 × 视频时长)，而且
        # 中间批次用 crf 0 会让每个中间文件膨胀到十几 GB。实测 4.7 小时 / 1394 条字幕
        # → 28 批，单批已写出 13 GB，全流程需要约 364 GB 临时空间，普通磁盘必然爆盘。
        #
        # 现在改为：把时间轴切成首尾相接的连续区间，每段只编码这一段、只叠加属于该段的
        # 字幕图，最后用 concat 无损拼接。整部视频只完整编码一遍。
        logger.debug("Encoding time-segmented chunks")

        ordered_frames = sorted(subtitle_frames, key=lambda f: f[0])
        chunks = _plan_chunks(ordered_frames, video_duration, CHUNK_SIZE)
        total_chunks = len(chunks)
        logger.debug(f"Split timeline into {total_chunks} segments")

        chunk_files: List[Path] = []
        for chunk_idx, (chunk_start, chunk_end, frames) in enumerate(chunks):
            span = chunk_end - chunk_start
            if span <= 0.02:
                continue

            input_args = [
                "-ss",
                f"{chunk_start:.3f}",
                "-t",
                f"{span:.3f}",
                "-i",
                video_path,
            ]
            filter_parts = []

            for local_idx, (start, end, png_path) in enumerate(frames):
                input_args.extend(["-i", str(png_path)])
                # 输入已用 -ss 重新定位，时间戳从 0 开始，字幕时间要减去段起点
                local_start = max(0.0, start - chunk_start)
                local_end = min(span, end - chunk_start)
                if local_end <= local_start:
                    continue
                prev = f"[v{local_idx - 1}]" if local_idx > 0 else "[0:v]"
                curr = f"[{local_idx + 1}:v]"
                out = f"[v{local_idx}]"
                filter_parts.append(
                    f"{prev}{curr}overlay=0:0:"
                    f"enable='between(t,{local_start:.3f},{local_end:.3f})'{out}"
                )

            if not filter_parts:
                filter_parts.append("[0:v]null[v0]")

            chunk_file = temp_path / f"chunk_{chunk_idx:04d}.mp4"
            logger.debug(
                f"Segment {chunk_idx + 1}/{total_chunks}"
                f"（{chunk_start:.0f}s-{chunk_end:.0f}s，{len(frames)} 条字幕）"
            )

            # 所有分段必须使用完全相同的编码参数，否则 concat 无法用 -c copy 直接拼接
            _run_ffmpeg(
                [
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    *input_args,
                    "-filter_complex",
                    ";".join(filter_parts),
                    "-map",
                    f"[v{len(filter_parts) - 1}]",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    preset,
                    "-crf",
                    str(crf),
                    "-pix_fmt",
                    "yuv420p",
                    str(chunk_file),
                ]
            )
            chunk_files.append(chunk_file)

            if progress_callback:
                progress = 30 + int((chunk_idx + 1) / total_chunks * 65)
                progress_callback(progress, f"合成视频 {chunk_idx + 1}/{total_chunks}")

        if not chunk_files:
            raise ValueError("No video chunk generated")

        # 步骤3: 无损拼接所有分段 (95-97%)
        logger.debug("Concatenating segments")
        concat_list = temp_path / "concat.txt"
        concat_list.write_text(
            "\n".join(f"file '{item.as_posix()}'" for item in chunk_files),
            encoding="utf-8",
        )
        merged_video = temp_path / "merged.mp4"
        _run_ffmpeg(
            [
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(merged_video),
            ]
        )
        if progress_callback:
            progress_callback(97, "合并分段...")

        # 步骤4: 挂回原始音轨 (97-100%)
        # 分段编码时用 -an 丢掉音频，最后直接 copy 原音轨：省掉 N 次音频重编码，
        # 也避免了每段 AAC 的 priming samples 造成累计偏移。
        audio_codec = _get_audio_codec(video_path)
        audio_args = ["-c:a", "copy"]
        if audio_codec in {"opus", "vorbis"}:
            # mp4 容器里放 opus/vorbis 兼容性差，转成 AAC
            audio_args = ["-c:a", "aac", "-b:a", "192k"]

        _run_ffmpeg(
            [
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(merged_video),
                "-i",
                video_path,
                "-map",
                "0:v:0",
                "-map",
                "1:a?",
                "-c:v",
                "copy",
                *audio_args,
                "-t",
                f"{video_duration:.3f}",
                str(output_path),
            ]
        )

        if progress_callback:
            progress_callback(100, "合成完成")

        logger.debug("Video synthesis complete")
