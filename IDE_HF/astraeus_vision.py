# ==========================================
# Copyright (c) 2026 Gabriela Berger AI Oberland
# All Rights Reserved.
# This code is subject to the custom NON-COMMERCIAL 
# & ANTI-CORPORATE LICENSE (Maximum 20 PCs) found in the LICENSE file.
# ==========================================
"""astraeus_vision.py — File-to-image pipeline for vision models.

Converts any file type to a base64-encoded PNG/JPEG so a vision LLM can see it.

Supported inputs:
  Images      : jpg, png, gif, bmp, webp, svg, tiff, ico
  Videos      : mp4, avi, mkv, mov, webm, flv, wmv (frame via ffmpeg)
  PDFs        : first/any page via poppler or pymupdf
  3D / CAD    : stl, obj, fbx, step, iges, blend (Blender headless)
  UE5 assets  : uasset, umap (extracts embedded thumbnail PNG)
  Documents   : docx, odt (LibreOffice headless → image)
  Screenshots : full screen or window via scrot / gnome-screenshot
  URLs        : YouTube, Twitch, direct image/video URLs via yt-dlp
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# ── File type sets ────────────────────────────────────────────────────────────

IMAGE_EXTS    = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
                 ".tiff", ".tif", ".ico", ".avif", ".heic"}
SVG_EXTS      = {".svg", ".svgz"}
VIDEO_EXTS    = {".mp4", ".avi", ".mkv", ".mov", ".webm",
                 ".flv", ".wmv", ".ts", ".m4v", ".3gp"}
PDF_EXTS      = {".pdf"}
CAD_3D_EXTS   = {".stl", ".obj", ".fbx", ".step", ".stp",
                  ".iges", ".igs", ".blend", ".3mf", ".ply", ".glb", ".gltf"}
SOLIDWORKS_EXTS = {".sldprt", ".sldasm", ".slddrw"}
UE_EXTS       = {".uasset", ".umap"}
OFFICE_EXTS   = {".docx", ".odt", ".pptx", ".odp", ".xlsx", ".ods"}
ALL_VISUAL    = (IMAGE_EXTS | SVG_EXTS | VIDEO_EXTS | PDF_EXTS |
                 CAD_3D_EXTS | SOLIDWORKS_EXTS | UE_EXTS | OFFICE_EXTS)


# ── Public API ────────────────────────────────────────────────────────────────

def file_to_base64(path: str, timestamp: float = 5.0, page: int = 1) -> tuple[str, str]:
    """
    Convert any supported file to (mime_type, base64_data).
    Returns ("image/png", "...base64...").
    Raises ValueError if the file cannot be converted.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ValueError(f"File not found: {path}")

    ext = p.suffix.lower()

    if ext in IMAGE_EXTS:
        return _image_to_b64(p)
    if ext in SVG_EXTS:
        return _svg_to_b64(p)
    if ext in VIDEO_EXTS:
        return _video_frame_to_b64(p, timestamp)
    if ext in PDF_EXTS:
        return _pdf_to_b64(p, page)
    if ext in UE_EXTS:
        return _ue_thumbnail_to_b64(p)
    if ext in CAD_3D_EXTS:
        return _3d_to_b64(p)
    if ext in SOLIDWORKS_EXTS:
        return _solidworks_to_b64(p)
    if ext in OFFICE_EXTS:
        return _office_to_b64(p)

    raise ValueError(f"Unsupported file type for vision: {ext}")


def url_to_base64(url: str, timestamp: float = 5.0) -> tuple[str, str]:
    """
    Download a URL (YouTube, Twitch, direct image/video, etc.) and
    return (mime_type, base64_data) for a representative frame/image.
    Requires yt-dlp and ffmpeg.
    """
    if _is_streaming_url(url):
        return _stream_url_to_b64(url, timestamp)
    # Direct URL — try wget then treat as image/video
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "download")
        r = subprocess.run(
            f"wget -q -O '{out}' '{url}'",
            shell=True, timeout=60,
        )
        if r != 0 or not Path(out).exists():
            raise ValueError(f"Could not download URL: {url}")
        # Guess type by content
        mime_r = subprocess.run(
            f"file --mime-type -b '{out}'",
            shell=True, capture_output=True, text=True,
        )
        mime = mime_r.stdout.strip()
        if "video" in mime:
            return _video_frame_to_b64(Path(out), timestamp)
        else:
            return _image_to_b64(Path(out))


def screenshot_to_base64(region: str | None = None, window_title: str | None = None) -> tuple[str, str]:
    """Take a screenshot. region = 'x,y,w,h'. Returns (mime, base64)."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    try:
        if window_title and shutil.which("scrot"):
            cmd = f"scrot -u '{tmp}'"
        elif region and shutil.which("scrot"):
            x, y, w, h = region.split(",")
            cmd = f"scrot -a {x},{y},{w},{h} '{tmp}'"
        elif shutil.which("scrot"):
            cmd = f"scrot '{tmp}'"
        elif shutil.which("gnome-screenshot"):
            cmd = f"gnome-screenshot -f '{tmp}'"
        elif shutil.which("import"):  # ImageMagick
            cmd = f"import -window root '{tmp}'"
        else:
            raise ValueError("No screenshot tool found (install scrot: sudo apt install scrot)")

        subprocess.run(cmd, shell=True, timeout=10, check=True)
        return _image_to_b64(Path(tmp))
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


# ── Converters ────────────────────────────────────────────────────────────────

def _image_to_b64(p: Path) -> tuple[str, str]:
    """Read an image file and return as base64. Normalizes to JPEG for large files."""
    data = p.read_bytes()
    ext = p.suffix.lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    # Try to resize very large images with ffmpeg to keep tokens low
    size = len(data)
    if size > 2_000_000 and shutil.which("ffmpeg"):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            tmp = f.name
        try:
            subprocess.run(
                f"ffmpeg -y -i '{p}' -vf 'scale=1280:-1' '{tmp}'",
                shell=True, capture_output=True, timeout=15,
            )
            if Path(tmp).exists() and Path(tmp).stat().st_size > 0:
                data = Path(tmp).read_bytes()
                mime = "image/jpeg"
        except Exception:
            pass
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass
    return mime, base64.b64encode(data).decode()


def _svg_to_b64(p: Path) -> tuple[str, str]:
    """Convert SVG to PNG via inkscape or cairosvg or rsvg-convert."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    try:
        if shutil.which("inkscape"):
            subprocess.run(
                f"inkscape '{p}' --export-png='{tmp}' --export-width=1024",
                shell=True, timeout=20, capture_output=True,
            )
        elif shutil.which("rsvg-convert"):
            subprocess.run(
                f"rsvg-convert -w 1024 '{p}' -o '{tmp}'",
                shell=True, timeout=20, capture_output=True,
            )
        else:
            # Fallback: read SVG as text and render via cairosvg python package
            import importlib
            if importlib.util.find_spec("cairosvg"):
                import cairosvg
                cairosvg.svg2png(url=str(p), write_to=tmp, output_width=1024)
            else:
                raise ValueError("No SVG converter found (install: sudo apt install inkscape)")
        if Path(tmp).exists() and Path(tmp).stat().st_size > 0:
            return "image/png", base64.b64encode(Path(tmp).read_bytes()).decode()
        raise ValueError("SVG conversion produced empty output")
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def _video_frame_to_b64(p: Path, timestamp: float = 5.0) -> tuple[str, str]:
    """Extract a frame from a video at timestamp seconds using ffmpeg."""
    if not shutil.which("ffmpeg"):
        raise ValueError("ffmpeg not found. Install: sudo apt install ffmpeg")
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        tmp = f.name
    try:
        r = subprocess.run(
            f"ffmpeg -y -ss {timestamp} -i '{p}' -vframes 1 -q:v 2 '{tmp}'",
            shell=True, capture_output=True, timeout=30,
        )
        if r.returncode != 0 or not Path(tmp).exists() or Path(tmp).stat().st_size == 0:
            # Try from beginning if timestamp too far
            subprocess.run(
                f"ffmpeg -y -i '{p}' -vframes 1 -q:v 2 '{tmp}'",
                shell=True, capture_output=True, timeout=30,
            )
        if not Path(tmp).exists() or Path(tmp).stat().st_size == 0:
            raise ValueError(f"ffmpeg could not extract frame from {p.name}")
        return "image/jpeg", base64.b64encode(Path(tmp).read_bytes()).decode()
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def _pdf_to_b64(p: Path, page: int = 1) -> tuple[str, str]:
    """Convert a PDF page to image using pdftoppm or pymupdf."""
    with tempfile.TemporaryDirectory() as tmp:
        out_prefix = os.path.join(tmp, "page")
        # Try pdftoppm (poppler)
        if shutil.which("pdftoppm"):
            r = subprocess.run(
                f"pdftoppm -r 150 -f {page} -l {page} -jpeg '{p}' '{out_prefix}'",
                shell=True, capture_output=True, timeout=30,
            )
            images = sorted(Path(tmp).glob("*.jpg"))
            if images:
                return "image/jpeg", base64.b64encode(images[0].read_bytes()).decode()
        # Try pymupdf
        try:
            import fitz
            doc = fitz.open(str(p))
            pg = doc[min(page - 1, len(doc) - 1)]
            mat = fitz.Matrix(1.5, 1.5)
            pix = pg.get_pixmap(matrix=mat)
            png_data = pix.tobytes("png")
            return "image/png", base64.b64encode(png_data).decode()
        except ImportError:
            pass
        raise ValueError("No PDF converter found. Install: sudo apt install poppler-utils")


def _ue_thumbnail_to_b64(p: Path) -> tuple[str, str]:
    """Extract the embedded thumbnail PNG from a UE4/5 uasset or umap file."""
    data = p.read_bytes()
    # UE assets embed PNG thumbnails — find the PNG magic bytes
    PNG_SIG = b'\x89PNG\r\n\x1a\n'
    IEND_SIG = b'IEND\xaeB`\x82'
    idx = data.find(PNG_SIG)
    if idx >= 0:
        end_idx = data.find(IEND_SIG, idx)
        if end_idx > idx:
            png_data = data[idx:end_idx + 8]
            return "image/png", base64.b64encode(png_data).decode()

    # No embedded PNG: render a placeholder with file metadata
    return _text_card_to_b64(
        title=p.name,
        lines=[
            f"Type: {p.suffix.upper()} (Unreal Engine Asset)",
            f"Size: {p.stat().st_size:,} bytes",
            "No embedded thumbnail found.",
            "Open in UE5 to view.",
        ],
    )


def _3d_to_b64(p: Path) -> tuple[str, str]:
    """Render a 3D file using Blender headless, or produce a metadata card."""
    blender = shutil.which("blender")
    if blender:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "render")
            script = _blender_render_script(str(p), out_path)
            script_path = os.path.join(tmp, "render.py")
            Path(script_path).write_text(script)
            r = subprocess.run(
                f"'{blender}' --background --python '{script_path}'",
                shell=True, capture_output=True, timeout=60,
            )
            # Blender appends .png to the output path
            candidates = list(Path(tmp).glob("render*.png"))
            if candidates:
                return "image/png", base64.b64encode(candidates[0].read_bytes()).decode()

    # Fallback: read STL/OBJ stats and produce a card
    try:
        text = p.read_text(errors="replace")[:2000]
        line_count = text.count("\n")
    except Exception:
        text = ""
        line_count = 0

    suffix = p.suffix.upper().lstrip(".")
    return _text_card_to_b64(
        title=p.name,
        lines=[
            f"Type: {suffix} 3D file",
            f"Size: {p.stat().st_size:,} bytes",
            f"Lines: {line_count:,}",
            "Install Blender for visual preview: sudo apt install blender",
        ],
    )


def _solidworks_to_b64(p: Path) -> tuple[str, str]:
    """Try FreeCAD headless for SolidWorks files, otherwise metadata card."""
    freecad = shutil.which("FreeCAD") or shutil.which("freecad") or shutil.which("freecadcmd")
    if freecad:
        with tempfile.TemporaryDirectory() as tmp:
            out_png = os.path.join(tmp, "preview.png")
            script = f"""
import FreeCAD, FreeCADGui, sys
FreeCADGui.showMainWindow()
doc = FreeCAD.open("{p}")
FreeCADGui.activeDocument().activeView().saveImage("{out_png}", 1024, 768, "White")
sys.exit(0)
"""
            script_path = os.path.join(tmp, "preview.py")
            Path(script_path).write_text(script)
            subprocess.run(
                f"'{freecad}' --run-script '{script_path}'",
                shell=True, capture_output=True, timeout=30,
            )
            if Path(out_png).exists():
                return "image/png", base64.b64encode(Path(out_png).read_bytes()).decode()

    return _text_card_to_b64(
        title=p.name,
        lines=[
            f"Type: SolidWorks {p.suffix.upper()} file",
            f"Size: {p.stat().st_size:,} bytes",
            "Install FreeCAD for visual preview: sudo apt install freecad",
            "Or export from SolidWorks to STEP/STL for open-source viewing.",
        ],
    )


def _office_to_b64(p: Path) -> tuple[str, str]:
    """Convert Office document to image via LibreOffice headless."""
    if not shutil.which("libreoffice"):
        raise ValueError("LibreOffice not found. Install: sudo apt install libreoffice")
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run(
            f"libreoffice --headless --convert-to png --outdir '{tmp}' '{p}'",
            shell=True, capture_output=True, timeout=30,
        )
        images = sorted(Path(tmp).glob("*.png"))
        if images:
            return "image/png", base64.b64encode(images[0].read_bytes()).decode()
    raise ValueError("LibreOffice conversion failed")


def _stream_url_to_b64(url: str, timestamp: float = 5.0) -> tuple[str, str]:
    """Download a video stream URL and extract a frame using yt-dlp + ffmpeg."""
    if not shutil.which("yt-dlp"):
        raise ValueError("yt-dlp not found. Install: sudo pip3 install yt-dlp")
    if not shutil.which("ffmpeg"):
        raise ValueError("ffmpeg not found. Install: sudo apt install ffmpeg")
    with tempfile.TemporaryDirectory() as tmp:
        video_path = os.path.join(tmp, "video.%(ext)s")
        r = subprocess.run(
            f"yt-dlp -o '{video_path}' --format 'best[height<=720]' '{url}'",
            shell=True, capture_output=True, timeout=120,
        )
        videos = [f for f in Path(tmp).iterdir() if f.name.startswith("video.")]
        if not videos:
            raise ValueError(f"yt-dlp could not download: {url}")
        return _video_frame_to_b64(videos[0], timestamp)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_streaming_url(url: str) -> bool:
    streaming = ["youtube.com", "youtu.be", "vimeo.com", "twitch.tv",
                 "dailymotion.com", "tiktok.com", "instagram.com/reel"]
    return any(s in url.lower() for s in streaming)


def _blender_render_script(input_path: str, output_path: str) -> str:
    return f"""
import bpy, sys

bpy.ops.wm.read_factory_settings(use_empty=True)

ext = "{Path(input_path).suffix.lower()}"
if ext == ".stl":
    bpy.ops.import_mesh.stl(filepath="{input_path}")
elif ext == ".obj":
    bpy.ops.wm.obj_import(filepath="{input_path}")
elif ext == ".fbx":
    bpy.ops.import_scene.fbx(filepath="{input_path}")
elif ext in (".glb", ".gltf"):
    bpy.ops.import_scene.gltf(filepath="{input_path}")
elif ext == ".blend":
    bpy.ops.wm.open_mainfile(filepath="{input_path}")

bpy.ops.object.select_all(action='SELECT')
bpy.ops.view3d.camera_to_view_selected()

scene = bpy.context.scene
scene.render.filepath = "{output_path}"
scene.render.resolution_x = 1024
scene.render.resolution_y = 768
scene.render.image_settings.file_format = 'PNG'
bpy.ops.render.render(write_still=True)
sys.exit(0)
"""


def _text_card_to_b64(title: str, lines: list[str]) -> tuple[str, str]:
    """Generate a simple text-card PNG using PIL or ImageMagick as fallback."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (800, 400), color=(30, 30, 40))
        draw = ImageDraw.Draw(img)
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
            font_body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        except Exception:
            font_title = ImageFont.load_default()
            font_body = font_title
        draw.text((20, 20), title, fill=(200, 220, 255), font=font_title)
        y = 70
        for line in lines:
            draw.text((20, y), line, fill=(180, 180, 200), font=font_body)
            y += 30
        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "image/png", base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        pass

    # PIL not available — use ImageMagick
    if shutil.which("convert"):
        text = title + "\n" + "\n".join(lines)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp = f.name
        try:
            subprocess.run(
                f"convert -size 800x400 xc:'#1E1E28' -fill white "
                f"-font DejaVu-Sans -pointsize 20 "
                f"-annotate +20+40 '{text}' '{tmp}'",
                shell=True, capture_output=True, timeout=10,
            )
            if Path(tmp).exists():
                return "image/png", base64.b64encode(Path(tmp).read_bytes()).decode()
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    raise ValueError("No image library available for text card (install Pillow: pip3 install Pillow)")
