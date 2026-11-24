"""Phase 56-02: raea 合成管線、BodyVista GLB 解量化與 raea check 強制品管閘門。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple

from src.visual.reel_script import DEFAULT_REEL_DISCLAIMER, generate_reel_script

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE_DIR = PROJECT_ROOT / "templates" / "raea"
DEFAULT_VIDEO_DIR = PROJECT_ROOT / "data" / "videos"
DEFAULT_REEL_DIR = DEFAULT_VIDEO_DIR / "reels"

DEFAULT_CLINIC = {
    "name": "緻妍外科診所",
    "phone": "04-2382-0888",
}

QualityType = Literal["draft", "high", "master"]


def _raea_env() -> dict[str, str]:
    env = os.environ.copy()
    local_bin = str(Path.home() / ".local" / "bin")
    raea_bin = str(Path.home() / ".raea" / "bin")
    env["PATH"] = f"{local_bin}:{raea_bin}:{env.get('PATH', '')}"
    return env


def is_raea_available() -> bool:
    """檢查 raea CLI 是否已安裝於 PATH 或 ~/.local/bin。"""
    env = _raea_env()
    return shutil.which("raea", path=env["PATH"]) is not None


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _probe_video(mp4_path: Path) -> Tuple[int, float]:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate,duration",
            "-of",
            "json",
            str(mp4_path),
        ],
        text=True,
    )
    info = json.loads(out)["streams"][0]
    num, den = info["r_frame_rate"].split("/")
    fps = round(float(num) / float(den))
    dur = float(info.get("duration", 10.0))
    return fps, dur


def _fetch_clinic_info(conn: sqlite3.Connection, topic_key: str) -> Tuple[str, str]:
    row = conn.execute(
        "SELECT clinic_id FROM visual_assets WHERE topic_key = ?",
        (topic_key,),
    ).fetchone()
    c_name, c_phone = DEFAULT_CLINIC["name"], DEFAULT_CLINIC["phone"]
    if row and row[0]:
        crow = conn.execute(
            "SELECT name, phone FROM clinic_info WHERE clinic_id = ?",
            (row[0],),
        ).fetchone()
        if crow:
            c_name = crow[0] or c_name
            c_phone = crow[1] or c_phone
    return c_name, c_phone


def prepare_bevy_glb(src_glb: Path, dst_glb: Path) -> Path:
    """以 @gltf-transform/cli 執行 copy + dequantize，產生無 meshopt/quantization 的 Bevy 相容 GLB。"""
    src_glb = Path(src_glb)
    dst_glb = Path(dst_glb)
    if not src_glb.is_file():
        raise FileNotFoundError(f"找不到原始 GLB: {src_glb}")
    dst_glb.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="glb_deq_") as tmpdir:
        plain_glb = Path(tmpdir) / "plain.glb"
        subprocess.run(
            ["npx", "--yes", "@gltf-transform/cli", "copy", str(src_glb), str(plain_glb)],
            check=True,
        )
        subprocess.run(
            ["npx", "--yes", "@gltf-transform/cli", "dequantize", str(plain_glb), str(dst_glb)],
            check=True,
        )
    return dst_glb


def run_raea_check(mp4_path: Path, manifest_path: Optional[Path] = None) -> Dict[str, Any]:
    """執行 raea check 並解析結果，作為強制品管閘門。"""
    cmd = ["raea", "check", str(mp4_path)]
    if manifest_path and manifest_path.is_file():
        cmd.extend(["--manifest", str(manifest_path)])
    proc = subprocess.run(
        cmd,
        env=_raea_env(),
        capture_output=True,
        text=True,
    )
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    errors = [ln.strip() for ln in output.splitlines() if ln.strip().startswith("error ")]
    warns = [ln.strip() for ln in output.splitlines() if ln.strip().startswith("warn ")]
    summary_line = ""
    for ln in reversed(output.splitlines()):
        if ln.strip().startswith("raea check:"):
            summary_line = ln.strip()
            break
    return {
        "passed": proc.returncode == 0,
        "returncode": proc.returncode,
        "errors": errors,
        "warns": warns,
        "summary": summary_line or f"exit={proc.returncode}",
        "raw_output": output.strip(),
    }


def _generate_bgm_wav(out_wav: Path, duration_sec: float) -> None:
    fade_out_st = max(0.5, duration_sec - 1.5)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_sec}",
            "-f", "lavfi", "-i", f"sine=frequency=554.37:duration={duration_sec}",
            "-filter_complex",
            f"[0:a][1:a]amix=inputs=2:duration=shortest,afade=t=in:st=0:d=0.5,afade=t=out:st={fade_out_st}:d=1.5,volume=0.15",
            str(out_wav),
        ],
        check=True,
    )


def render_reel_with_raea(
    conn: sqlite3.Connection,
    topic_key: str,
    output_dir: Optional[Path] = None,
    video_dir: Optional[Path] = None,
    use_llm: bool = True,
    quality: QualityType = "high",
    max_sec: Optional[float] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """整合 Ornith 腳本 + 既有 portrait 母片 + raea 模板渲染並通過 raea check。"""
    src_video_dir = Path(video_dir) if video_dir else DEFAULT_VIDEO_DIR
    out_dir = Path(output_dir) if output_dir else DEFAULT_REEL_DIR
    src_mp4 = src_video_dir / f"{topic_key}_portrait.mp4"
    if not src_mp4.is_file():
        raise FileNotFoundError(f"找不到豎屏母片（請先執行 video_queue）: {src_mp4}")

    template_tsx = TEMPLATE_DIR / "reel_template.tsx"
    if not template_tsx.is_file():
        raise FileNotFoundError(f"找不到 raea 短影音模板: {template_tsx}")

    script = generate_reel_script(conn, topic_key, use_llm=use_llm)
    c_name, c_phone = _fetch_clinic_info(conn, topic_key)
    fps, dur = _probe_video(src_mp4)
    if max_sec and dur > max_sec:
        dur = max_sec
    duration_frames = max(24, int(round(dur * fps)))

    # 計算複合 SHA-256 快取鍵
    cache_payload = json.dumps(
        {
            "src_sha256": _file_sha256(src_mp4),
            "tmpl_sha256": _file_sha256(template_tsx),
            "script": script.model_dump(),
            "clinic": [c_name, c_phone],
            "duration_frames": duration_frames,
            "quality": quality,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    cache_sha = hashlib.sha256(cache_payload.encode("utf-8")).hexdigest()

    out_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = out_dir / f"{topic_key}_reel.mp4"
    meta_path = out_dir / f"{topic_key}_reel.meta.json"

    if not force and out_mp4.is_file() and meta_path.is_file():
        try:
            old_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if old_meta.get("sha256") == cache_sha:
                return {
                    "topic_key": topic_key,
                    "status": "cached",
                    "out_mp4": str(out_mp4),
                    "sha256": cache_sha,
                    "script_source": script.source,
                }
        except Exception:
            pass

    if not is_raea_available():
        raise RuntimeError("找不到 raea CLI，請先安裝 raea 至 ~/.local/bin")

    with tempfile.TemporaryDirectory(prefix=f"raea_reel_{topic_key}_") as tmp:
        work = Path(tmp)
        media = work / "media"
        media.mkdir(parents=True, exist_ok=True)
        shutil.copy2(template_tsx, work / "reel_template.tsx")
        shutil.copy2(src_mp4, media / "active_video.mp4")
        _generate_bgm_wav(media / "bgm.wav", dur)

        cfg = {
            **script.model_dump(),
            "clinic_name": c_name,
            "clinic_phone": c_phone,
            "video_file": "active_video.mp4",
            "audio_file": "bgm.wav",
            "fps": fps,
            "duration_frames": duration_frames,
        }
        (work / "reel_config.json").write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        tmp_mp4 = work / "out.mp4"
        manifest = work / "render.json"
        t0 = time.monotonic()
        subprocess.run(
            [
                "raea", "render", "reel_template.tsx",
                "-o", str(tmp_mp4),
                "--manifest", str(manifest),
                "--quality", quality,
            ],
            cwd=str(work),
            env=_raea_env(),
            check=True,
        )
        render_sec = round(time.monotonic() - t0, 2)

        chk = run_raea_check(tmp_mp4, manifest)
        if not chk["passed"]:
            raise RuntimeError(f"raea check 未通過: {chk['errors']}")

        shutil.move(str(tmp_mp4), str(out_mp4))
        meta = {
            "topic_key": topic_key,
            "sha256": cache_sha,
            "fps": fps,
            "frames": duration_frames,
            "duration_sec": dur,
            "quality": quality,
            "render_sec": render_sec,
            "script_source": script.source,
            "check": chk["summary"],
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "topic_key": topic_key,
        "status": "rendered",
        "out_mp4": str(out_mp4),
        "sha256": cache_sha,
        "render_sec": render_sec,
        "script_source": script.source,
        "check_passed": True,
        "check_summary": chk["summary"],
    }


def render_3d_with_raea(
    core_glb: Path,
    overlay_glb: Optional[Path],
    out_mp4: Path,
    title: str,
    subtitle: str = "Phase 41 · BodyVista 3D 解剖可視化",
    legend: str = "圖例：半透明骨質（core）／ 橘紅發光（神經血管束）",
    disclaimer: str = DEFAULT_REEL_DISCLAIMER,
    quality: QualityType = "master",
    duration_frames: int = 120,
    fps: int = 24,
    camera_radius_start: float = 26.0,
    camera_radius_end: float = 21.5,
) -> Dict[str, Any]:
    """使用 anatomy_3d_template.tsx 渲染 BodyVista 3D 解剖運鏡影片並通過 raea check。"""
    if not is_raea_available():
        raise RuntimeError("找不到 raea CLI，請先安裝 raea 至 ~/.local/bin")

    template_tsx = TEMPLATE_DIR / "anatomy_3d_template.tsx"
    if not template_tsx.is_file():
        raise FileNotFoundError(f"找不到 raea 3D 模板: {template_tsx}")

    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="raea_3d_") as tmp:
        work = Path(tmp)
        media = work / "media"
        media.mkdir(parents=True, exist_ok=True)
        shutil.copy2(template_tsx, work / "anatomy_3d_template.tsx")
        shutil.copy2(core_glb, media / "core.glb")
        overlay_name = ""
        if overlay_glb and Path(overlay_glb).is_file():
            shutil.copy2(overlay_glb, media / "overlay.glb")
            overlay_name = "overlay.glb"

        cfg = {
            "title": title,
            "subtitle": subtitle,
            "legend": legend,
            "disclaimer": disclaimer,
            "core_glb": "core.glb",
            "overlay_glb": overlay_name,
            "fps": fps,
            "duration_frames": duration_frames,
            "camera_radius_start": camera_radius_start,
            "camera_radius_end": camera_radius_end,
        }
        (work / "scene3d_config.json").write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        tmp_mp4 = work / "out3d.mp4"
        manifest = work / "render3d.json"
        t0 = time.monotonic()
        subprocess.run(
            [
                "raea", "render", "anatomy_3d_template.tsx",
                "-o", str(tmp_mp4),
                "--manifest", str(manifest),
                "--quality", quality,
            ],
            cwd=str(work),
            env=_raea_env(),
            check=True,
        )
        render_sec = round(time.monotonic() - t0, 2)

        chk = run_raea_check(tmp_mp4, manifest)
        if not chk["passed"]:
            raise RuntimeError(f"3D raea check 未通過: {chk['errors']}")

        shutil.move(str(tmp_mp4), str(out_mp4))

    return {
        "status": "rendered",
        "out_mp4": str(out_mp4),
        "frames": duration_frames,
        "fps": fps,
        "quality": quality,
        "render_sec": render_sec,
        "check_passed": True,
        "check_summary": chk["summary"],
    }
