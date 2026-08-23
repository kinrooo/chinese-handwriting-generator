#!/usr/bin/env python3
"""Offline Chinese handwriting renderer, batcher, page maker, and scan simulator."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import sys
import zipfile
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    from PIL import (
        Image,
        ImageChops,
        ImageDraw,
        ImageEnhance,
        ImageFilter,
        ImageFont,
        ImageOps,
        __version__ as PILLOW_VERSION,
    )
except ImportError as exc:  # pragma: no cover - depends on the caller's runtime
    raise SystemExit(
        "Pillow is required. Use a Python environment that already includes Pillow; "
        "do not install from the network without the user's approval."
    ) from exc


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
VENDOR_ROOT = SCRIPT_DIR / "vendor" / "handrightbeta"
BUNDLED_FONT_ROOT = SKILL_ROOT / "assets" / "fonts"
BUNDLED_FONT_MANIFEST = BUNDLED_FONT_ROOT / "fonts-manifest.json"
sys.path.insert(0, str(VENDOR_ROOT))

import handright  # noqa: E402
from handright import Template, handwrite  # noqa: E402


SCHEMA_VERSION = "1.1"
DEFAULT_SEED = 20260823
DEFAULT_CANVAS = (640, 190)
PROJECT_TESTED_PILLOW_COMPATIBILITY = ">=10,<13"
UPSTREAM_DECLARED_PILLOW_COMPATIBILITY = ">=8.3.2,<11"
MAX_CANVAS_PIXELS = 80_000_000
MAX_FONTS = 200
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}
UI_FONT_CANDIDATES = (
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("C:/Windows/Fonts/msyh.ttc"),
)


STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "subtle": {
        "render_scale": 2,
        "font_size": [72, 84],
        "word_spacing": [0, 4],
        "line_spacing_sigma": [0.4, 1.2],
        "font_size_sigma": [0.6, 1.8],
        "word_spacing_sigma": [0.4, 1.4],
        "perturb_x_sigma": [0.4, 1.2],
        "perturb_y_sigma": [0.4, 1.2],
        "perturb_theta_sigma": [0.008, 0.020],
        "angle": [0.3, 1.6],
        "width_scale": [0.97, 1.04],
        "height_scale": [0.98, 1.03],
        "x_jitter": [-8, 8],
        "y_jitter": [-4, 5],
        "ink_rgb": [[22, 36], [27, 43], [33, 53]],
        "ink_alpha": [242, 252],
        "ink_depth_sigma": [8.0, 18.0],
    },
    "natural": {
        "render_scale": 2,
        "font_size": [66, 88],
        "word_spacing": [-2, 6],
        "line_spacing_sigma": [0.7, 2.8],
        "font_size_sigma": [1.2, 4.2],
        "word_spacing_sigma": [0.8, 3.2],
        "perturb_x_sigma": [0.8, 2.6],
        "perturb_y_sigma": [0.8, 2.4],
        "perturb_theta_sigma": [0.014, 0.038],
        "angle": [0.8, 3.8],
        "width_scale": [0.93, 1.10],
        "height_scale": [0.95, 1.06],
        "x_jitter": [-18, 18],
        "y_jitter": [-7, 9],
        "ink_rgb": [[17, 39], [24, 47], [29, 59]],
        "ink_alpha": [238, 252],
        "ink_depth_sigma": [12.0, 30.0],
    },
    "strong": {
        "render_scale": 2,
        "font_size": [60, 94],
        "word_spacing": [-5, 10],
        "line_spacing_sigma": [1.0, 4.0],
        "font_size_sigma": [2.5, 6.0],
        "word_spacing_sigma": [1.5, 5.0],
        "perturb_x_sigma": [1.4, 4.0],
        "perturb_y_sigma": [1.4, 3.6],
        "perturb_theta_sigma": [0.025, 0.060],
        "angle": [0.5, 5.2],
        "width_scale": [0.88, 1.16],
        "height_scale": [0.92, 1.10],
        "x_jitter": [-24, 24],
        "y_jitter": [-11, 12],
        "ink_rgb": [[12, 48], [18, 54], [24, 66]],
        "ink_alpha": [228, 252],
        "ink_depth_sigma": [18.0, 38.0],
    },
    "note": {
        "render_scale": 1,
        "font_size": [78, 88],
        "word_spacing": [1, 5],
        "line_spacing_sigma": [0.5, 1.5],
        "font_size_sigma": [0.8, 2.2],
        "word_spacing_sigma": [0.6, 1.8],
        "perturb_x_sigma": [0.5, 1.5],
        "perturb_y_sigma": [0.6, 1.8],
        "perturb_theta_sigma": [0.010, 0.024],
        "angle": [0.0, 0.0],
        "width_scale": [1.0, 1.0],
        "height_scale": [1.0, 1.0],
        "x_jitter": [0, 0],
        "y_jitter": [0, 0],
        "ink_rgb": [[22, 34], [28, 44], [34, 56]],
        "ink_alpha": [242, 252],
        "ink_depth_sigma": [8.0, 18.0],
    },
}

SCAN_PRESETS: dict[str, dict[str, float]] = {
    "clean-scan": {
        "contrast": 1.08,
        "brightness": 1.02,
        "blur": 0.20,
        "noise": 0.010,
        "skew": 0.20,
        "vignette": 0.00,
        "jpeg_quality": 94,
    },
    "photocopy": {
        "contrast": 1.42,
        "brightness": 1.04,
        "blur": 0.45,
        "noise": 0.045,
        "skew": 0.65,
        "vignette": 0.05,
        "jpeg_quality": 80,
    },
    "phone-scan": {
        "contrast": 1.16,
        "brightness": 0.98,
        "blur": 0.28,
        "noise": 0.022,
        "skew": 1.10,
        "vignette": 0.18,
        "jpeg_quality": 86,
    },
}

STYLE_KEYS = set(STYLE_PRESETS["natural"])


class UserInputError(ValueError):
    """Raised for a clear, user-actionable input problem."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_seed(master_seed: int, *parts: object) -> int:
    payload = "\x1f".join([str(master_seed), *(str(part) for part in parts)])
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def parse_size(raw: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d+)\s*[xX×]\s*(\d+)\s*", raw)
    if not match:
        raise argparse.ArgumentTypeError("size must look like 640x190")
    width, height = int(match.group(1)), int(match.group(2))
    if width < 32 or height < 32:
        raise argparse.ArgumentTypeError("each size dimension must be at least 32 pixels")
    if width * height > MAX_CANVAS_PIXELS:
        raise argparse.ArgumentTypeError(
            f"canvas exceeds the {MAX_CANVAS_PIXELS:,}-pixel safety limit"
        )
    return width, height


def parse_range(raw: str) -> list[float]:
    parts = raw.split(":")
    if len(parts) == 1:
        try:
            value = float(parts[0])
        except ValueError as exc:
            raise argparse.ArgumentTypeError("range must be VALUE or MIN:MAX") from exc
        return [value, value]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("range must be VALUE or MIN:MAX")
    try:
        low, high = float(parts[0]), float(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("range must contain numbers") from exc
    if low > high:
        raise argparse.ArgumentTypeError("range minimum cannot exceed maximum")
    return [low, high]


def parse_color(raw: str) -> tuple[int, int, int]:
    value = raw.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(character * 2 for character in value)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        raise argparse.ArgumentTypeError("color must be #RRGGBB or #RGB")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def range_pair(value: Any, key: str) -> tuple[float, float]:
    if isinstance(value, (int, float)):
        return float(value), float(value)
    if isinstance(value, list) and len(value) == 2 and all(
        isinstance(item, (int, float)) for item in value
    ):
        low, high = float(value[0]), float(value[1])
        if low > high:
            raise UserInputError(f"style range {key!r} has min greater than max")
        return low, high
    raise UserInputError(f"style value {key!r} must be a number or [min, max]")


def draw_float(rng: random.Random, value: Any, key: str) -> float:
    low, high = range_pair(value, key)
    return rng.uniform(low, high)


def draw_int(rng: random.Random, value: Any, key: str) -> int:
    low, high = range_pair(value, key)
    return rng.randint(math.ceil(low), math.floor(high))


def resolve_style(args: argparse.Namespace, preset: str | None = None) -> dict[str, Any]:
    selected = preset or args.preset
    style = deepcopy(STYLE_PRESETS[selected])
    config_path = getattr(args, "style_config", None)
    if config_path:
        raw = json.loads(Path(config_path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise UserInputError("style config must be a JSON object")
        unknown = sorted(set(raw) - STYLE_KEYS)
        if unknown:
            raise UserInputError(f"unknown style keys: {', '.join(unknown)}")
        style.update(raw)
    if getattr(args, "angle", None) is not None:
        style["angle"] = args.angle
    if getattr(args, "ink", None) is not None:
        style["ink_rgb"] = [[value, value] for value in args.ink]
    for key in STYLE_KEYS - {"render_scale", "ink_rgb"}:
        range_pair(style[key], key)
    if not isinstance(style["render_scale"], int) or style["render_scale"] not in {1, 2, 3, 4}:
        raise UserInputError("render_scale must be one of 1, 2, 3, or 4")
    ink_rgb = style["ink_rgb"]
    if not isinstance(ink_rgb, list) or len(ink_rgb) != 3:
        raise UserInputError("ink_rgb must contain three channel ranges")
    for index, channel in enumerate(ink_rgb):
        low, high = range_pair(channel, f"ink_rgb[{index}]")
        if low < 0 or high > 255:
            raise UserInputError("ink_rgb channel values must be between 0 and 255")
    return style


def safe_text_filename(text: str, maximum: int = 36) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", text).strip().strip(".")
    cleaned = re.sub(r"\s+", "_", cleaned)
    return (cleaned or "text")[:maximum]


def prepare_output_directory(path: Path, overwrite: bool) -> Path:
    path = path.expanduser().resolve()
    if path.exists() and not path.is_dir():
        raise UserInputError(f"output exists and is not a directory: {path}")
    if path.exists() and any(path.iterdir()) and not overwrite:
        raise UserInputError(
            f"output directory is not empty: {path}; choose a new directory or pass --overwrite"
        )
    path.mkdir(parents=True, exist_ok=True)
    return path


def fit_inside(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    if image.width <= max_width and image.height <= max_height:
        return image
    ratio = min(max_width / image.width, max_height / image.height)
    return image.resize(
        (max(1, round(image.width * ratio)), max(1, round(image.height * ratio))),
        Image.Resampling.LANCZOS,
    )


def load_ui_font(size: int) -> ImageFont.ImageFont:
    for path in UI_FONT_CANDIDATES:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def glyph_fingerprint(font: ImageFont.FreeTypeFont, char: str) -> tuple[Any, ...]:
    mask = font.getmask(char, mode="L")
    return font.getbbox(char), mask.size, bytes(mask)


def missing_characters(font_path: Path, text: str) -> list[str]:
    font = ImageFont.truetype(str(font_path), size=64)
    missing_glyph = glyph_fingerprint(font, "\u0378")
    return [
        char
        for char in sorted(set(text))
        if not char.isspace() and glyph_fingerprint(font, char) == missing_glyph
    ]


def resolve_bundled_path(raw: object, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError(f"bundled font manifest has an invalid {label}")
    root = BUNDLED_FONT_ROOT.resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"bundled font manifest {label} escapes its asset directory") from exc
    return path


@lru_cache(maxsize=1)
def bundled_font_catalog() -> dict[Path, dict[str, Any]]:
    if not BUNDLED_FONT_MANIFEST.is_file():
        raise RuntimeError(f"bundled font manifest is missing: {BUNDLED_FONT_MANIFEST}")
    data = json.loads(BUNDLED_FONT_MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != "1.0":
        raise RuntimeError("unsupported bundled font manifest schema")
    entries = data.get("fonts")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("bundled font manifest must contain a non-empty fonts[] list")
    catalog: dict[Path, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    for index, raw_entry in enumerate(entries, 1):
        if not isinstance(raw_entry, dict):
            raise RuntimeError(f"bundled font entry {index} is not an object")
        entry = dict(raw_entry)
        font_id = entry.get("id")
        expected_hash = entry.get("sha256")
        required_strings = {
            "id": font_id,
            "family": entry.get("family"),
            "style_label_zh": entry.get("style_label_zh"),
            "license": entry.get("license"),
            "license_sha256": entry.get("license_sha256"),
            "upstream_repository": entry.get("upstream_repository"),
            "upstream_commit": entry.get("upstream_commit"),
        }
        invalid = [key for key, value in required_strings.items() if not isinstance(value, str) or not value]
        if invalid:
            raise RuntimeError(
                f"bundled font entry {index} has invalid fields: {', '.join(invalid)}"
            )
        if font_id in seen_ids:
            raise RuntimeError(f"bundled font manifest has duplicate id: {font_id}")
        if expected_hash in seen_hashes:
            raise RuntimeError(f"bundled font manifest has duplicate SHA-256: {expected_hash}")
        seen_ids.add(font_id)
        seen_hashes.add(expected_hash)
        path = resolve_bundled_path(entry.get("path"), f"fonts[{index}].path")
        license_path = resolve_bundled_path(
            entry.get("license_path"), f"fonts[{index}].license_path"
        )
        if not path.is_file():
            raise RuntimeError(f"bundled font file is missing: {path}")
        if path.suffix.lower() not in FONT_EXTENSIONS:
            raise RuntimeError(f"bundled font has an unsupported extension: {path}")
        if not license_path.is_file():
            raise RuntimeError(f"bundled font license is missing: {license_path}")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or sha256_file(path) != expected_hash:
            raise RuntimeError(f"bundled font SHA-256 mismatch: {path}")
        expected_license_hash = entry["license_sha256"]
        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected_license_hash)
            or sha256_file(license_path) != expected_license_hash
        ):
            raise RuntimeError(f"bundled font license SHA-256 mismatch: {license_path}")
        entry["resolved_license_path"] = license_path
        catalog[path] = entry
    if len(catalog) != len(entries):
        raise RuntimeError("bundled font manifest contains duplicate font paths")
    unregistered = {
        path.resolve()
        for path in BUNDLED_FONT_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in FONT_EXTENSIONS
    } - set(catalog)
    if unregistered:
        listed = ", ".join(str(path) for path in sorted(unregistered))
        raise RuntimeError(f"unregistered bundled font files found: {listed}")
    return catalog


def discover_fonts(
    font_files: Sequence[str],
    font_dirs: Sequence[str],
    include_bundled: bool = False,
) -> list[Path]:
    discovered: list[Path] = []
    explicit_requested = bool(font_files or font_dirs)
    for raw in font_files:
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            raise UserInputError(f"font file not found: {path}")
        if path.suffix.lower() not in FONT_EXTENSIONS:
            raise UserInputError(f"unsupported font extension: {path}")
        discovered.append(path)
    for raw in font_dirs:
        directory = Path(raw).expanduser().resolve()
        if not directory.is_dir():
            raise UserInputError(f"font directory not found: {directory}")
        discovered.extend(
            path.resolve()
            for path in sorted(directory.rglob("*"))
            if path.is_file() and path.suffix.lower() in FONT_EXTENSIONS
        )
    if include_bundled or not explicit_requested:
        discovered.extend(bundled_font_catalog())
    unique = list(dict.fromkeys(discovered))
    if not unique:
        raise UserInputError(
            "no supported fonts were found; omit font options to use the bundled OFL pool"
        )
    if len(unique) > MAX_FONTS:
        raise UserInputError(f"font pool exceeds the {MAX_FONTS}-font safety limit")
    return unique


def font_summary(path: Path, level: str) -> dict[str, Any]:
    path = path.resolve()
    bundled = bundled_font_catalog().get(path)
    if bundled:
        result: dict[str, Any] = {
            "id": bundled["id"],
            "name": path.name,
            "family": bundled["family"],
            "source": "bundled",
            "skill_relative_path": f"assets/fonts/{bundled['path']}",
            "style_label_zh": bundled["style_label_zh"],
            "license": bundled["license"],
            "license_sha256": bundled["license_sha256"],
            "license_relative_path": f"assets/fonts/{bundled['license_path']}",
            "sha256": bundled["sha256"],
            "upstream_repository": bundled["upstream_repository"],
            "upstream_commit": bundled["upstream_commit"],
        }
        if level == "full":
            result["path"] = str(path)
            result["license_path"] = str(bundled["resolved_license_path"])
        return result
    result = {
        "name": path.name,
        "source": "external",
        "license_status": "user-provided-or-unverified",
        "sha256": sha256_file(path),
    }
    if level == "full":
        result["path"] = str(path)
    return result


def read_records(path: Path, field: str | None) -> list[dict[str, str]]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise UserInputError(f"input file not found: {path}")
    suffix = path.suffix.lower()
    records: list[dict[str, str]] = []
    if suffix in {".txt", ".text"}:
        for index, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if line.strip():
                records.append({"id": str(index), "text": line.strip()})
    elif suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise UserInputError("CSV has no header row")
            selected_field = field or reader.fieldnames[0]
            if selected_field not in reader.fieldnames:
                raise UserInputError(f"CSV field not found: {selected_field}")
            for index, row in enumerate(reader, 1):
                value = row.get(selected_field)
                if value is not None and str(value).strip():
                    record_id = str(row.get("id") or index)
                    records.append({"id": record_id, "text": str(value).strip()})
    elif suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict) and isinstance(data.get("records"), list):
            data = data["records"]
        if not isinstance(data, list):
            raise UserInputError("JSON input must be a list or an object containing records[]")
        for index, item in enumerate(data, 1):
            if isinstance(item, str):
                value, record_id = item, str(index)
            elif isinstance(item, dict):
                selected_field = field
                if selected_field is None:
                    selected_field = next(
                        (candidate for candidate in ("text", "name", "value") if candidate in item),
                        None,
                    )
                if selected_field is None or selected_field not in item:
                    raise UserInputError(
                        "JSON object records require --field or a text/name/value key"
                    )
                value = item[selected_field]
                record_id = str(item.get("id") or index)
            else:
                raise UserInputError(f"unsupported JSON record at index {index}")
            if value is not None and str(value).strip():
                records.append({"id": record_id, "text": str(value).strip()})
    else:
        raise UserInputError("batch input must be TXT, JSON, or CSV")
    if not records:
        raise UserInputError("input contains no non-empty text records")
    return records


def validate_short_text(text: str) -> None:
    if not text or not text.strip():
        raise UserInputError("text cannot be empty")
    if "\n" in text or "\r" in text:
        raise UserInputError("render/batch text must be one line; use page for multiline text")
    if len(text) > 200:
        raise UserInputError("render/batch text is limited to 200 characters; use page")


def eligible_fonts(fonts: Sequence[Path], text: str) -> list[Path]:
    return [font for font in fonts if not missing_characters(font, text)]


def assign_fonts(
    jobs: Sequence[dict[str, Any]],
    fonts: Sequence[Path],
    policy: str,
    master_seed: int,
) -> list[Path]:
    usage: Counter[Path] = Counter()
    assigned: list[Path] = []
    previous: Path | None = None
    coverage_cache: dict[tuple[Path, str], bool] = {}
    for job in jobs:
        text = job["text"]
        candidates = []
        for font in fonts:
            key = (font, text)
            if key not in coverage_cache:
                coverage_cache[key] = not missing_characters(font, text)
            if coverage_cache[key]:
                candidates.append(font)
        if not candidates:
            raise UserInputError(
                f"no selected font covers record #{job.get('record_index', '?')}"
            )
        rng = random.Random(
            stable_seed(master_seed, "font", job["record_id"], text, job["variant"])
        )
        if policy == "fixed":
            selected = candidates[0]
        elif policy == "random":
            non_repeating = [font for font in candidates if font != previous]
            selected = rng.choice(non_repeating or candidates)
        else:
            least = min(usage[font] for font in candidates)
            least_used = [font for font in candidates if usage[font] == least]
            non_repeating = [font for font in least_used if font != previous]
            selected = rng.choice(non_repeating or least_used)
        usage[selected] += 1
        assigned.append(selected)
        previous = selected
    return assigned


def sample_ink(rng: random.Random, style: dict[str, Any]) -> tuple[int, int, int, int]:
    rgb = tuple(draw_int(rng, channel, "ink_rgb") for channel in style["ink_rgb"])
    alpha = draw_int(rng, style["ink_alpha"], "ink_alpha")
    return rgb + (alpha,)


def whole_angle(rng: random.Random, style: dict[str, Any], trend: str) -> float:
    low, high = range_pair(style["angle"], "angle")
    magnitude = rng.uniform(abs(low), abs(high))
    if trend == "up":
        return magnitude
    if trend == "down":
        return -magnitude
    flat_limit = max(abs(low), abs(high), 0.4)
    return rng.uniform(-min(flat_limit, 0.8), min(flat_limit, 0.8))


def background_rgba(raw: str) -> tuple[int, int, int, int]:
    if raw == "transparent":
        return 0, 0, 0, 0
    if raw == "white":
        return 255, 255, 255, 255
    return parse_color(raw) + (255,)


def foreground_bbox(image: Image.Image, background: str) -> tuple[int, int, int, int] | None:
    if background == "transparent":
        return image.convert("RGBA").getchannel("A").getbbox()
    color = background_rgba(background)[:3]
    rgb = image.convert("RGB")
    base = Image.new("RGB", rgb.size, color)
    return ImageChops.difference(rgb, base).getbbox()


def edge_is_clear(image: Image.Image, background: str) -> bool:
    rgba = image.convert("RGBA")
    expected = background_rgba(background)
    width, height = rgba.size
    points = (
        [(x, 0) for x in range(width)]
        + [(x, height - 1) for x in range(width)]
        + [(0, y) for y in range(height)]
        + [(width - 1, y) for y in range(height)]
    )
    return all(rgba.getpixel(point) == expected for point in points)


def render_short(
    text: str,
    font_path: Path,
    style: dict[str, Any],
    canvas_size: tuple[int, int],
    background: str,
    trend: str,
    seed: int,
    safe_margin: int,
) -> tuple[Image.Image, dict[str, Any]]:
    rng = random.Random(seed)
    scale = style["render_scale"]
    font_size = draw_int(rng, style["font_size"], "font_size")
    word_spacing = draw_int(rng, style["word_spacing"], "word_spacing")
    line_spacing_sigma = draw_float(rng, style["line_spacing_sigma"], "line_spacing_sigma")
    font_size_sigma = draw_float(rng, style["font_size_sigma"], "font_size_sigma")
    word_spacing_sigma = draw_float(rng, style["word_spacing_sigma"], "word_spacing_sigma")
    perturb_x_sigma = draw_float(rng, style["perturb_x_sigma"], "perturb_x_sigma")
    perturb_y_sigma = draw_float(rng, style["perturb_y_sigma"], "perturb_y_sigma")
    perturb_theta_sigma = draw_float(
        rng, style["perturb_theta_sigma"], "perturb_theta_sigma"
    )
    angle = whole_angle(rng, style, trend)
    width_scale = draw_float(rng, style["width_scale"], "width_scale")
    height_scale = draw_float(rng, style["height_scale"], "height_scale")
    x_jitter = draw_int(rng, style["x_jitter"], "x_jitter")
    y_jitter = draw_int(rng, style["y_jitter"], "y_jitter")
    ink = sample_ink(rng, style)
    ink_depth_sigma = draw_float(rng, style["ink_depth_sigma"], "ink_depth_sigma")

    font = ImageFont.truetype(str(font_path), size=font_size * scale)
    estimated_width = max(
        canvas_size[0] + 160,
        round((len(text) + 2) * (font_size + max(word_spacing, 0) + 18)),
    )
    estimated_height = max(canvas_size[1], round(font_size * 2.1))
    render_size = (estimated_width * scale, estimated_height * scale)
    if render_size[0] * render_size[1] > MAX_CANVAS_PIXELS:
        raise UserInputError("intermediate render canvas exceeds the safety limit")

    template = Template(
        background=Image.new("RGBA", render_size, (0, 0, 0, 0)),
        font=font,
        line_spacing=round(font_size * 1.45 * scale),
        fill=ink,
        left_margin=24 * scale,
        top_margin=1 * scale,
        right_margin=24 * scale,
        bottom_margin=1 * scale,
        word_spacing=word_spacing * scale,
        line_spacing_sigma=line_spacing_sigma * scale,
        font_size_sigma=font_size_sigma * scale,
        word_spacing_sigma=word_spacing_sigma * scale,
        perturb_x_sigma=perturb_x_sigma * scale,
        perturb_y_sigma=perturb_y_sigma * scale,
        perturb_theta_sigma=perturb_theta_sigma,
        strikethrough_probability=0,
        ink_depth_sigma=ink_depth_sigma,
    )
    pages = list(handwrite(text, template, seed=seed))
    if len(pages) != 1:
        raise RuntimeError(f"short text unexpectedly rendered to {len(pages)} pages")
    rendered = pages[0]
    if scale != 1:
        rendered = rendered.resize(
            (max(1, rendered.width // scale), max(1, rendered.height // scale)),
            Image.Resampling.LANCZOS,
        )
    alpha_bbox = rendered.getchannel("A").getbbox()
    if alpha_bbox is None:
        raise RuntimeError("renderer produced an empty image")
    left, top, right, bottom = alpha_bbox
    pad = 7
    rendered = rendered.crop(
        (
            max(0, left - pad),
            max(0, top - pad),
            min(rendered.width, right + pad),
            min(rendered.height, bottom + pad),
        )
    )
    rendered = rendered.resize(
        (
            max(1, round(rendered.width * width_scale)),
            max(1, round(rendered.height * height_scale)),
        ),
        Image.Resampling.LANCZOS,
    )
    rendered = rendered.rotate(
        angle,
        resample=Image.Resampling.BICUBIC,
        expand=True,
    )
    rendered = fit_inside(
        rendered,
        canvas_size[0] - safe_margin * 2,
        canvas_size[1] - safe_margin * 2,
    )

    canvas = Image.new("RGBA", canvas_size, background_rgba(background))
    centered_x = (canvas_size[0] - rendered.width) // 2 + x_jitter
    centered_y = (canvas_size[1] - rendered.height) // 2 + y_jitter
    x = min(max(safe_margin, centered_x), canvas_size[0] - safe_margin - rendered.width)
    y = min(max(safe_margin, centered_y), canvas_size[1] - safe_margin - rendered.height)
    canvas.alpha_composite(rendered, (x, y))
    image = canvas if background == "transparent" else canvas.convert("RGB")

    bbox = foreground_bbox(image, background)
    if bbox is None:
        raise RuntimeError("final image has no foreground")
    margins = [bbox[0], bbox[1], image.width - bbox[2], image.height - bbox[3]]
    if min(margins) < safe_margin:
        raise RuntimeError(f"foreground violates the {safe_margin}px safe margin")
    if not edge_is_clear(image, background):
        raise RuntimeError("foreground or antialiasing reached the outer edge")

    metadata = {
        "seed": seed,
        "font_size": font_size,
        "word_spacing": word_spacing,
        "line_spacing_sigma": round(line_spacing_sigma, 4),
        "font_size_sigma": round(font_size_sigma, 4),
        "word_spacing_sigma": round(word_spacing_sigma, 4),
        "perturb_x_sigma": round(perturb_x_sigma, 4),
        "perturb_y_sigma": round(perturb_y_sigma, 4),
        "perturb_theta_sigma": round(perturb_theta_sigma, 5),
        "whole_angle_degrees": round(angle, 4),
        "width_scale": round(width_scale, 4),
        "height_scale": round(height_scale, 4),
        "x_jitter": x_jitter,
        "y_jitter": y_jitter,
        "ink_rgba": list(ink),
        "ink_depth_sigma": round(ink_depth_sigma, 4),
        "foreground_bbox": list(bbox),
        "safe_margin": min(margins),
        "edge_clear": True,
    }
    return image, metadata


def build_contact_sheet(
    image_paths: Sequence[Path],
    labels: Sequence[str],
    output_path: Path,
    limit: int,
    title: str = "Chinese handwriting preview",
    show_labels: bool = True,
) -> Path | None:
    selected = list(zip(image_paths, labels))[:limit]
    if not selected:
        return None
    columns = min(4, len(selected))
    rows = math.ceil(len(selected) / columns)
    tile_width, tile_height, header = 560, 230, 72
    page = Image.new(
        "RGB",
        (columns * tile_width, header + rows * tile_height),
        (255, 255, 255),
    )
    draw = ImageDraw.Draw(page)
    label_font = load_ui_font(18)
    title_font = load_ui_font(26)
    draw.text((24, 22), title, font=title_font, fill=(45, 52, 58))
    for index, (path, label) in enumerate(selected):
        row, column = divmod(index, columns)
        left, top = column * tile_width, header + row * tile_height
        image = Image.open(path).convert("RGB")
        preview = fit_inside(image, tile_width - 44, tile_height - 48)
        page.paste(
            preview,
            (
                left + (tile_width - preview.width) // 2,
                top + (tile_height - preview.height) // 2 - 8,
            ),
        )
        if show_labels:
            draw.text(
                (left + 12, top + tile_height - 27),
                label,
                font=label_font,
                fill=(125, 125, 125),
            )
        draw.line(
            (left, top + tile_height - 1, left + tile_width, top + tile_height - 1),
            fill=(232, 232, 232),
        )
        if column:
            draw.line((left, top, left, top + tile_height), fill=(238, 238, 238))
    page.save(output_path, optimize=True)
    return output_path


def manifest_record_text(
    record: dict[str, str], level: str, public_id: str
) -> dict[str, Any]:
    result: dict[str, Any] = {"record_id": public_id}
    if level == "full":
        result["source_record_id"] = record["id"]
        result["text_sha256"] = sha256_bytes(record["text"].encode("utf-8"))
        result["text"] = record["text"]
    return result


def create_zip(output_dir: Path, files: Iterable[Path], overwrite: bool) -> Path:
    zip_path = output_dir.with_suffix(".zip")
    if zip_path.exists() and not overwrite:
        raise UserInputError(f"ZIP already exists: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            if path.exists() and path.is_file():
                archive.write(path, arcname=path.relative_to(output_dir))
    return zip_path


def save_manifest(output_dir: Path, manifest: dict[str, Any], level: str) -> Path | None:
    if level == "none":
        return None
    path = output_dir / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def common_manifest(
    mode: str,
    args: argparse.Namespace,
    fonts: Sequence[Path],
    output_count: int,
) -> dict[str, Any]:
    level = args.manifest_level
    catalog = bundled_font_catalog()
    bundled_ids = [catalog[font.resolve()]["id"] for font in fonts if font.resolve() in catalog]
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "mode": mode,
        "engine": {
            "name": "handrightbeta-vendored",
            "version": getattr(handright, "__version__", "8.7.0"),
            "pillow_version": PILLOW_VERSION,
            "upstream_declared_pillow_compatibility": UPSTREAM_DECLARED_PILLOW_COMPATIBILITY,
            "project_tested_pillow_compatibility": PROJECT_TESTED_PILLOW_COMPATIBILITY,
            "runtime_smoke_test_required": True,
        },
        "master_seed": args.seed,
        "manifest_level": level,
        "watermarked": False,
        "synthetic_test_data_declared": bool(args.synthetic_test_data),
        "font_catalog": {
            "schema_version": "1.0",
            "skill_relative_path": "assets/fonts/fonts-manifest.json",
            "sha256": sha256_file(BUNDLED_FONT_MANIFEST),
            "offline": True,
            "selected_font_ids": bundled_ids,
        },
        "fonts": [font_summary(font, level) for font in fonts],
        "expected_output_count": output_count,
        "outputs": [],
        "qa": {"hard_checks_passed": True, "visual_review_required": True},
    }


def run_short_generation(
    args: argparse.Namespace,
    records: Sequence[dict[str, str]],
    mode: str,
) -> dict[str, Any]:
    for record in records:
        validate_short_text(record["text"])
    record_ids = [record["id"] for record in records]
    if len(record_ids) != len(set(record_ids)):
        raise UserInputError("record IDs must be unique")
    fonts = discover_fonts(args.font, args.font_dir, args.include_bundled_fonts)
    output_dir = prepare_output_directory(Path(args.output), args.overwrite)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)
    canvas_size = args.canvas
    safe_margin = args.safe_margin or max(4, math.ceil(min(canvas_size) * 0.01))
    if safe_margin * 2 >= min(canvas_size):
        raise UserInputError("safe margin is too large for the canvas")
    style = resolve_style(args)

    jobs: list[dict[str, Any]] = []
    for record_index, record in enumerate(records, 1):
        for variant in range(1, args.variants + 1):
            jobs.append(
                {
                    "record_index": record_index,
                    "record_id": record["id"],
                    "text": record["text"],
                    "variant": variant,
                }
            )
    assigned_fonts = assign_fonts(jobs, fonts, args.font_policy, args.seed)
    manifest = common_manifest(mode, args, fonts, len(jobs))
    manifest.update(
        {
            "preset": args.preset,
            "resolved_style": style,
            "canvas": list(canvas_size),
            "background": args.background,
            "trend": args.trend,
            "font_policy": args.font_policy,
            "variants_per_record": args.variants,
        }
    )

    output_paths: list[Path] = []
    labels: list[str] = []
    for sequence, (job, font_path) in enumerate(zip(jobs, assigned_fonts), 1):
        seed = stable_seed(
            args.seed,
            mode,
            job["record_id"],
            job["text"],
            job["variant"],
            font_path.name,
            args.preset,
        )
        image, metadata = render_short(
            job["text"],
            font_path,
            style,
            canvas_size,
            args.background,
            args.trend,
            seed,
            safe_margin,
        )
        text_part = f"_{safe_text_filename(job['text'])}" if args.name_files else ""
        filename = f"{sequence:04d}{text_part}_v{job['variant']:02d}.png"
        path = images_dir / filename
        image.save(path, optimize=True)
        file_hash = sha256_file(path)
        record = next(item for item in records if item["id"] == job["record_id"])
        item = {
            **manifest_record_text(
                record,
                args.manifest_level,
                f"record-{job['record_index']:04d}",
            ),
            "variant": job["variant"],
            "file": str(path.relative_to(output_dir)),
            "sha256": file_hash,
            "size": list(image.size),
            "mode": image.mode,
            "font": font_summary(font_path, args.manifest_level),
            "parameters": metadata,
        }
        manifest["outputs"].append(item)
        output_paths.append(path)
        labels.append(
            f"{sequence:04d} v{job['variant']:02d} {font_path.stem[:26]} {metadata['whole_angle_degrees']:+.2f}deg"
        )

    by_record: defaultdict[str, list[str]] = defaultdict(list)
    for item in manifest["outputs"]:
        by_record[str(item["record_id"])].append(str(item["sha256"]))
    duplicates = [record_id for record_id, hashes in by_record.items() if len(hashes) != len(set(hashes))]
    if duplicates:
        raise RuntimeError(f"duplicate variants detected for record IDs: {', '.join(duplicates)}")

    preview_path = output_dir / "preview.png"
    build_contact_sheet(
        output_paths,
        labels,
        preview_path,
        args.preview_limit,
        args.preview_title,
        not args.hide_preview_labels,
    )
    manifest["preview"] = str(preview_path.relative_to(output_dir))
    manifest_path = save_manifest(output_dir, manifest, args.manifest_level)
    archive_files = [*output_paths, preview_path]
    if manifest_path:
        archive_files.append(manifest_path)
    zip_path = create_zip(output_dir, archive_files, args.overwrite) if args.zip else None
    return {
        "mode": mode,
        "count": len(output_paths),
        "output": str(output_dir),
        "preview": str(preview_path),
        "manifest": str(manifest_path) if manifest_path else None,
        "zip": str(zip_path) if zip_path else None,
        "font_distribution": dict(Counter(path.name for path in assigned_fonts)),
    }


def make_paper(
    size: tuple[int, int],
    paper: str,
    margin: int,
    line_spacing: int,
    background_image: str | None,
) -> Image.Image:
    if background_image:
        path = Path(background_image).expanduser().resolve()
        if not path.is_file():
            raise UserInputError(f"background image not found: {path}")
        return Image.open(path).convert("RGBA").resize(size, Image.Resampling.LANCZOS)
    page = Image.new("RGBA", size, (255, 255, 255, 255))
    draw = ImageDraw.Draw(page)
    if paper in {"lined", "grid"}:
        for y in range(margin + line_spacing, size[1] - margin, line_spacing):
            draw.line((margin, y, size[0] - margin, y), fill=(210, 224, 236, 255), width=2)
    if paper == "grid":
        for x in range(margin, size[0] - margin, line_spacing):
            draw.line((x, margin, x, size[1] - margin), fill=(226, 234, 241, 255), width=1)
    return page


def run_page(args: argparse.Namespace) -> dict[str, Any]:
    if bool(args.text) == bool(args.input):
        raise UserInputError("page requires exactly one of --text or --input")
    text = args.text if args.text else Path(args.input).read_text(encoding="utf-8-sig")
    if not text or not text.strip():
        raise UserInputError("page text cannot be empty")
    fonts = discover_fonts(args.font, args.font_dir, args.include_bundled_fonts)
    covering = eligible_fonts(fonts, text)
    if not covering:
        raise UserInputError("no selected font covers all page characters")
    font_path = covering[0]
    output_dir = prepare_output_directory(Path(args.output), args.overwrite)
    style = resolve_style(args, "note")
    page_size = args.page_size
    margin = args.margin
    font_size = args.font_size or round(sum(range_pair(style["font_size"], "font_size")) / 2)
    line_spacing = args.line_spacing or round(font_size * 1.55)
    seed = stable_seed(args.seed, "page", sha256_bytes(text.encode("utf-8")), font_path.name)
    rng = random.Random(seed)
    ink = sample_ink(rng, style)
    paper = make_paper(page_size, args.paper, margin, line_spacing, args.background_image)
    font = ImageFont.truetype(str(font_path), size=font_size)
    template = Template(
        background=paper,
        font=font,
        line_spacing=line_spacing,
        fill=ink,
        left_margin=margin,
        top_margin=margin,
        right_margin=margin,
        bottom_margin=margin,
        word_spacing=draw_int(rng, style["word_spacing"], "word_spacing"),
        line_spacing_sigma=draw_float(rng, style["line_spacing_sigma"], "line_spacing_sigma"),
        font_size_sigma=draw_float(rng, style["font_size_sigma"], "font_size_sigma"),
        word_spacing_sigma=draw_float(rng, style["word_spacing_sigma"], "word_spacing_sigma"),
        perturb_x_sigma=draw_float(rng, style["perturb_x_sigma"], "perturb_x_sigma"),
        perturb_y_sigma=draw_float(rng, style["perturb_y_sigma"], "perturb_y_sigma"),
        perturb_theta_sigma=draw_float(
            rng, style["perturb_theta_sigma"], "perturb_theta_sigma"
        ),
        strikethrough_probability=0,
        ink_depth_sigma=draw_float(rng, style["ink_depth_sigma"], "ink_depth_sigma"),
    )
    pages = [page.convert("RGB") for page in handwrite(text, template, seed=seed)]
    if not pages:
        raise RuntimeError("page renderer produced no pages")
    page_paths: list[Path] = []
    outputs: list[dict[str, Any]] = []
    for index, page in enumerate(pages, 1):
        path = output_dir / f"page_{index:03d}.png"
        page.save(path, optimize=True, dpi=(args.dpi, args.dpi))
        diff = ImageChops.difference(page, paper.convert("RGB"))
        bbox = diff.getbbox()
        if bbox is None:
            raise RuntimeError(f"page {index} contains no handwriting")
        page_paths.append(path)
        outputs.append(
            {
                "record_id": f"page-{index:03d}",
                "file": path.name,
                "sha256": sha256_file(path),
                "size": list(page.size),
                "mode": page.mode,
                "foreground_bbox": list(bbox),
            }
        )
    pdf_path: Path | None = None
    if args.pdf:
        pdf_path = output_dir / "document.pdf"
        pages[0].save(
            pdf_path,
            save_all=True,
            append_images=pages[1:],
            resolution=args.dpi,
        )
    preview_path = output_dir / "preview.png"
    build_contact_sheet(
        page_paths,
        [f"page {index:03d}" for index in range(1, len(pages) + 1)],
        preview_path,
        args.preview_limit,
        args.preview_title,
        not args.hide_preview_labels,
    )
    manifest = common_manifest("page", args, fonts, len(pages))
    manifest.update(
        {
            "text_sha256": (
                sha256_bytes(text.encode("utf-8"))
                if args.manifest_level == "full"
                else None
            ),
            "text": text if args.manifest_level == "full" else None,
            "font": font_summary(font_path, args.manifest_level),
            "page_size": list(page_size),
            "dpi": args.dpi,
            "paper": args.paper,
            "margin": margin,
            "font_size": font_size,
            "line_spacing": line_spacing,
            "outputs": outputs,
            "preview": preview_path.name,
            "pdf": pdf_path.name if pdf_path else None,
        }
    )
    if manifest["text"] is None:
        del manifest["text"]
    if manifest["text_sha256"] is None:
        del manifest["text_sha256"]
    manifest_path = save_manifest(output_dir, manifest, args.manifest_level)
    archive_files: list[Path] = [*page_paths, preview_path]
    if pdf_path:
        archive_files.append(pdf_path)
    if manifest_path:
        archive_files.append(manifest_path)
    zip_path = create_zip(output_dir, archive_files, args.overwrite) if args.zip else None
    return {
        "mode": "page",
        "count": len(pages),
        "output": str(output_dir),
        "preview": str(preview_path),
        "pdf": str(pdf_path) if pdf_path else None,
        "manifest": str(manifest_path) if manifest_path else None,
        "zip": str(zip_path) if zip_path else None,
    }


def run_compare(args: argparse.Namespace) -> dict[str, Any]:
    validate_short_text(args.text)
    fonts = discover_fonts(args.font, args.font_dir, args.include_bundled_fonts)
    covering = eligible_fonts(fonts, args.text)
    if not covering:
        raise UserInputError("no selected font covers the comparison text")
    if len(covering) > args.max_fonts:
        raise UserInputError(
            f"{len(covering)} fonts cover the text; narrow the pool or increase --max-fonts"
        )
    presets = [item.strip() for item in args.presets.split(",") if item.strip()]
    invalid = sorted(set(presets) - set(STYLE_PRESETS))
    if invalid:
        raise UserInputError(f"unknown presets: {', '.join(invalid)}")
    output_dir = prepare_output_directory(Path(args.output), args.overwrite)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)
    safe_margin = args.safe_margin or max(4, math.ceil(min(args.canvas) * 0.01))
    paths: list[Path] = []
    labels: list[str] = []
    outputs: list[dict[str, Any]] = []
    resolved_styles: dict[str, dict[str, Any]] = {}
    sequence = 0
    for preset in presets:
        style = resolve_style(args, preset)
        resolved_styles[preset] = style
        for font in covering:
            sequence += 1
            seed = stable_seed(args.seed, "compare", args.text, font.name, preset)
            image, metadata = render_short(
                args.text,
                font,
                style,
                args.canvas,
                args.background,
                args.trend,
                seed,
                safe_margin,
            )
            filename = f"{sequence:04d}_{safe_text_filename(font.stem)}_{preset}.png"
            path = images_dir / filename
            image.save(path, optimize=True)
            paths.append(path)
            labels.append(f"{preset} | {font.stem[:32]}")
            outputs.append(
                {
                    "record_id": f"compare-{sequence:04d}",
                    "text_sha256": (
                        sha256_bytes(args.text.encode("utf-8"))
                        if args.manifest_level == "full"
                        else None
                    ),
                    "text": args.text if args.manifest_level == "full" else None,
                    "preset": preset,
                    "font": font_summary(font, args.manifest_level),
                    "file": str(path.relative_to(output_dir)),
                    "sha256": sha256_file(path),
                    "size": list(image.size),
                    "mode": image.mode,
                    "parameters": metadata,
                }
            )
    for item in outputs:
        if item["text"] is None:
            del item["text"]
        if item["text_sha256"] is None:
            del item["text_sha256"]
    preview_path = output_dir / "preview.png"
    build_contact_sheet(
        paths,
        labels,
        preview_path,
        args.preview_limit,
        args.preview_title,
        not args.hide_preview_labels,
    )
    manifest = common_manifest("compare", args, fonts, len(outputs))
    manifest.update(
        {
            "presets": presets,
            "resolved_styles": resolved_styles,
            "canvas": list(args.canvas),
            "background": args.background,
            "trend": args.trend,
            "outputs": outputs,
            "preview": preview_path.name,
        }
    )
    manifest_path = save_manifest(output_dir, manifest, args.manifest_level)
    archive_files = [*paths, preview_path]
    if manifest_path:
        archive_files.append(manifest_path)
    zip_path = create_zip(output_dir, archive_files, args.overwrite) if args.zip else None
    return {
        "mode": "compare",
        "count": len(outputs),
        "output": str(output_dir),
        "preview": str(preview_path),
        "manifest": str(manifest_path) if manifest_path else None,
        "zip": str(zip_path) if zip_path else None,
    }


def apply_vignette(image: Image.Image, strength: float) -> Image.Image:
    if strength <= 0:
        return image
    radial = Image.radial_gradient("L").resize(image.size, Image.Resampling.BILINEAR)
    mask = radial.point(lambda value: round(value * min(strength, 1.0)))
    darker = ImageEnhance.Brightness(image).enhance(max(0.45, 1.0 - strength * 1.2))
    return Image.composite(darker, image, mask)


def add_deterministic_noise(image: Image.Image, strength: float, rng: random.Random) -> Image.Image:
    if strength <= 0:
        return image
    small_size = (max(8, image.width // 12), max(8, image.height // 12))
    noise = Image.new("L", small_size)
    noise.putdata([rng.randint(0, 255) for _ in range(small_size[0] * small_size[1])])
    noise = noise.resize(image.size, Image.Resampling.BILINEAR)
    return Image.blend(image, noise, min(strength, 0.25))


def scan_image(image: Image.Image, preset: str, seed: int) -> tuple[Image.Image, dict[str, Any]]:
    settings = SCAN_PRESETS[preset]
    rng = random.Random(seed)
    scanned = ImageOps.grayscale(image.convert("RGB"))
    scanned = ImageOps.autocontrast(scanned, cutoff=1)
    scanned = ImageEnhance.Contrast(scanned).enhance(settings["contrast"])
    scanned = ImageEnhance.Brightness(scanned).enhance(settings["brightness"])
    scanned = add_deterministic_noise(scanned, settings["noise"], rng)
    if settings["blur"] > 0:
        scanned = scanned.filter(ImageFilter.GaussianBlur(settings["blur"]))
    angle = rng.uniform(-settings["skew"], settings["skew"])
    scanned = scanned.rotate(
        angle,
        resample=Image.Resampling.BICUBIC,
        expand=False,
        fillcolor=255,
    )
    scanned = apply_vignette(scanned, settings["vignette"])
    return scanned, {**settings, "angle_degrees": round(angle, 4), "seed": seed}


def run_scan(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.input).expanduser().resolve()
    if not source.exists():
        raise UserInputError(f"scan input not found: {source}")
    if source.is_file():
        sources = [source]
    else:
        sources = [
            path
            for path in sorted(source.iterdir())
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ]
    if not sources:
        raise UserInputError("scan input contains no supported images")
    output_dir = prepare_output_directory(Path(args.output), args.overwrite)
    if source.is_dir() and output_dir == source:
        raise UserInputError("scan output directory must differ from the input directory")
    output_format = args.format
    if output_format == "auto":
        output_format = "png" if args.preset == "clean-scan" else "jpg"
    outputs: list[dict[str, Any]] = []
    output_paths: list[Path] = []
    for index, path in enumerate(sources, 1):
        seed = stable_seed(args.seed, "scan", path.name, sha256_file(path), args.preset)
        scanned, parameters = scan_image(Image.open(path), args.preset, seed)
        suffix = ".png" if output_format == "png" else ".jpg"
        destination = output_dir / f"{index:04d}_scan{suffix}"
        if output_format == "png":
            scanned.save(destination, optimize=True, dpi=(args.dpi, args.dpi))
        else:
            scanned.save(
                destination,
                quality=round(SCAN_PRESETS[args.preset]["jpeg_quality"]),
                optimize=True,
                dpi=(args.dpi, args.dpi),
            )
        output_paths.append(destination)
        outputs.append(
            {
                "record_id": f"scan-{index:04d}",
                "source_sha256": sha256_file(path),
                "file": destination.name,
                "sha256": sha256_file(destination),
                "size": list(scanned.size),
                "mode": scanned.mode,
                "parameters": parameters,
            }
        )
    preview_path = output_dir / "preview.png"
    build_contact_sheet(
        output_paths,
        [f"{args.preset} {index:04d}" for index in range(1, len(sources) + 1)],
        preview_path,
        args.preview_limit,
        args.preview_title,
        not args.hide_preview_labels,
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "mode": "scan",
        "pillow_version": PILLOW_VERSION,
        "master_seed": args.seed,
        "preset": args.preset,
        "clean_master_preserved": True,
        "watermarked": False,
        "expected_output_count": len(outputs),
        "outputs": outputs,
        "preview": preview_path.name,
        "qa": {"hard_checks_passed": True, "visual_review_required": True},
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    archive_files = [*output_paths, preview_path, manifest_path]
    zip_path = create_zip(output_dir, archive_files, args.overwrite) if args.zip else None
    return {
        "mode": "scan",
        "count": len(outputs),
        "output": str(output_dir),
        "preview": str(preview_path),
        "manifest": str(manifest_path),
        "zip": str(zip_path) if zip_path else None,
    }


def run_inspect_font(args: argparse.Namespace) -> dict[str, Any]:
    fonts = discover_fonts(args.font, args.font_dir, args.include_bundled_fonts)
    texts: list[str] = []
    if args.text:
        texts.append(args.text)
    if args.input:
        texts.extend(record["text"] for record in read_records(Path(args.input), args.field))
    if not texts:
        raise UserInputError("inspect-font requires --text or --input")
    combined = "".join(texts)
    results = []
    for font in fonts:
        missing = missing_characters(font, combined)
        results.append(
            {
                **font_summary(font, "full"),
                "font": str(font),
                "covers_all": not missing,
                "missing_characters": missing,
            }
        )
    return {
        "required_character_count": len({char for char in combined if not char.isspace()}),
        "font_count": len(fonts),
        "covering_font_count": sum(1 for result in results if result["covers_all"]),
        "fonts": results,
    }


def resolved_parameter_errors(
    parameters: dict[str, Any], style: dict[str, Any], trend: str
) -> list[str]:
    errors: list[str] = []
    key_map = {
        "font_size": "font_size",
        "word_spacing": "word_spacing",
        "line_spacing_sigma": "line_spacing_sigma",
        "font_size_sigma": "font_size_sigma",
        "word_spacing_sigma": "word_spacing_sigma",
        "perturb_x_sigma": "perturb_x_sigma",
        "perturb_y_sigma": "perturb_y_sigma",
        "perturb_theta_sigma": "perturb_theta_sigma",
        "width_scale": "width_scale",
        "height_scale": "height_scale",
        "x_jitter": "x_jitter",
        "y_jitter": "y_jitter",
        "ink_depth_sigma": "ink_depth_sigma",
    }
    for parameter_key, style_key in key_map.items():
        if parameter_key not in parameters or style_key not in style:
            errors.append(f"missing resolved parameter {parameter_key}")
            continue
        low, high = range_pair(style[style_key], style_key)
        value = float(parameters[parameter_key])
        if value < low - 1e-6 or value > high + 1e-6:
            errors.append(f"{parameter_key}={value} is outside [{low}, {high}]")
    rgba = parameters.get("ink_rgba")
    if not isinstance(rgba, list) or len(rgba) != 4:
        errors.append("ink_rgba is missing or malformed")
    else:
        for index, value in enumerate(rgba[:3]):
            low, high = range_pair(style["ink_rgb"][index], f"ink_rgb[{index}]")
            if float(value) < low or float(value) > high:
                errors.append(f"ink channel {index} is outside [{low}, {high}]")
        low, high = range_pair(style["ink_alpha"], "ink_alpha")
        if float(rgba[3]) < low or float(rgba[3]) > high:
            errors.append(f"ink alpha is outside [{low}, {high}]")
    if "whole_angle_degrees" not in parameters:
        errors.append("whole_angle_degrees is missing")
    else:
        angle = float(parameters["whole_angle_degrees"])
        low, high = range_pair(style["angle"], "angle")
        min_magnitude, max_magnitude = sorted((abs(low), abs(high)))
        if trend == "up" and angle < -1e-6:
            errors.append(f"up trend has a negative angle: {angle}")
        elif trend == "down" and angle > 1e-6:
            errors.append(f"down trend has a positive angle: {angle}")
        elif trend == "flat" and abs(angle) > min(max_magnitude, 0.8) + 1e-6:
            errors.append(f"flat trend angle is too large: {angle}")
        if trend != "flat" and not (
            min_magnitude - 1e-6 <= abs(angle) <= max_magnitude + 1e-6
        ):
            errors.append(
                f"angle magnitude {abs(angle)} is outside [{min_magnitude}, {max_magnitude}]"
            )
    return errors


def validate_font_reference(
    font_info: dict[str, Any],
    text: str | None,
    context: str,
    errors: list[str],
    cache: dict[tuple[str, str, str | None], list[str]],
) -> None:
    if font_info.get("source") == "bundled":
        font_id = font_info.get("id")
        matches = [
            (path, entry)
            for path, entry in bundled_font_catalog().items()
            if entry.get("id") == font_id
        ]
        if len(matches) != 1:
            errors.append(f"{context}: unknown bundled font id: {font_id!r}")
            return
        path, entry = matches[0]
        metadata_checks = {
            "name": path.name,
            "family": entry["family"],
            "style_label_zh": entry["style_label_zh"],
            "skill_relative_path": f"assets/fonts/{entry['path']}",
            "sha256": entry["sha256"],
            "license": entry["license"],
            "license_sha256": entry["license_sha256"],
            "license_relative_path": f"assets/fonts/{entry['license_path']}",
            "upstream_repository": entry["upstream_repository"],
            "upstream_commit": entry["upstream_commit"],
        }
        for key, expected in metadata_checks.items():
            if font_info.get(key) != expected:
                errors.append(
                    f"{context}: bundled font metadata mismatch for {font_id}.{key}"
                )
        key = (str(path), str(entry["sha256"]), text)
        if key not in cache:
            problems: list[str] = []
            if text is not None:
                missing = missing_characters(path, text)
                if missing:
                    problems.append(f"font is missing glyphs: {''.join(missing)}")
            cache[key] = problems
        errors.extend(f"{context}: {problem}" for problem in cache[key])
        return
    path_raw = font_info.get("path")
    expected_hash = font_info.get("sha256")
    if not isinstance(path_raw, str):
        return
    path = Path(path_raw).expanduser().resolve()
    key = (str(path), str(expected_hash), text)
    if key not in cache:
        problems: list[str] = []
        if not path.is_file():
            problems.append(f"font file is missing: {path}")
        else:
            if not isinstance(expected_hash, str) or sha256_file(path) != expected_hash:
                problems.append(f"font SHA-256 mismatch: {path}")
            if text is not None:
                missing = missing_characters(path, text)
                if missing:
                    problems.append(f"font is missing glyphs: {''.join(missing)}")
        cache[key] = problems
    errors.extend(f"{context}: {problem}" for problem in cache[key])


def run_validate(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest).expanduser().resolve()
    if not manifest_path.is_file():
        raise UserInputError(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent
    errors: list[str] = []
    warnings: list[str] = []
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise UserInputError("manifest outputs must be a list")
    expected = manifest.get("expected_output_count")
    if expected != len(outputs):
        errors.append(f"manifest expects {expected} outputs but lists {len(outputs)}")

    engine = manifest.get("engine")
    if isinstance(engine, dict):
        runtime_version = str(engine.get("pillow_version", ""))
        declared = str(
            engine.get("project_tested_pillow_compatibility")
            or engine.get("declared_pillow_compatibility", "")
        )
        match = re.match(r"(\d+)", runtime_version)
        lower_match = re.search(r">=(\d+)", declared)
        upper_match = re.search(r"<(\d+)", declared)
        major = int(match.group(1)) if match else None
        outside = major is not None and (
            (lower_match is not None and major < int(lower_match.group(1)))
            or (upper_match is not None and major >= int(upper_match.group(1)))
        )
        if outside:
            warnings.append(
                f"Pillow {runtime_version} is outside the project-tested range {declared}"
            )

    font_catalog = manifest.get("font_catalog")
    if isinstance(font_catalog, dict):
        if font_catalog.get("skill_relative_path") != "assets/fonts/fonts-manifest.json":
            errors.append("font catalog relative path is invalid")
        if font_catalog.get("sha256") != sha256_file(BUNDLED_FONT_MANIFEST):
            errors.append("bundled font catalog SHA-256 mismatch")
    elif manifest.get("schema_version") == "1.1" and manifest.get("mode") in {
        "render",
        "batch",
        "page",
        "compare",
    }:
        errors.append("font catalog metadata is missing")

    by_record: defaultdict[str, list[str]] = defaultdict(list)
    variants_by_record: defaultdict[str, list[int]] = defaultdict(list)
    font_counts: Counter[str] = Counter()
    ordered_fonts: list[str] = []
    font_cache: dict[tuple[str, str, str | None], list[str]] = {}
    manifest_fonts = manifest.get("fonts")
    if isinstance(manifest_fonts, list):
        for index, font_info in enumerate(manifest_fonts, 1):
            if isinstance(font_info, dict):
                validate_font_reference(
                    font_info,
                    None,
                    f"font pool entry {index}",
                    errors,
                    font_cache,
                )
            else:
                errors.append(f"font pool entry {index} is not an object")
        if isinstance(font_catalog, dict):
            expected_ids = [
                font_info.get("id")
                for font_info in manifest_fonts
                if isinstance(font_info, dict) and font_info.get("source") == "bundled"
            ]
            if font_catalog.get("selected_font_ids") != expected_ids:
                errors.append("font catalog selected_font_ids do not match the font pool")
    background = manifest.get("background")
    mode = str(manifest.get("mode", ""))
    for index, item in enumerate(outputs, 1):
        if not isinstance(item, dict):
            errors.append(f"output {index} is not an object")
            continue
        relative = item.get("file")
        if not isinstance(relative, str):
            errors.append(f"output {index} has no file path")
            continue
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            errors.append(f"output path escapes manifest directory: {relative}")
            continue
        if not path.is_file():
            errors.append(f"missing output file: {relative}")
            continue
        actual_hash = sha256_file(path)
        if item.get("sha256") != actual_hash:
            errors.append(f"SHA-256 mismatch: {relative}")
        try:
            image = Image.open(path)
            if item.get("size") and list(image.size) != list(item["size"]):
                errors.append(f"size mismatch: {relative}")
            if item.get("mode") and image.mode != item["mode"]:
                errors.append(f"mode mismatch: {relative}")
            if isinstance(background, str):
                if not edge_is_clear(image, background):
                    errors.append(f"outer edge is not clear: {relative}")
                bbox = foreground_bbox(image, background)
                if bbox is None:
                    errors.append(f"foreground is empty: {relative}")
                else:
                    minimum_margin = min(
                        bbox[0], bbox[1], image.width - bbox[2], image.height - bbox[3]
                    )
                    required_margin = max(4, math.ceil(min(image.size) * 0.01))
                    if minimum_margin < required_margin:
                        errors.append(
                            f"safe margin {minimum_margin}px is below {required_margin}px: {relative}"
                        )
                    parameters = item.get("parameters")
                    if isinstance(parameters, dict) and parameters.get("foreground_bbox") != list(bbox):
                        errors.append(f"foreground bbox differs from manifest: {relative}")
        except Exception as exc:
            errors.append(f"cannot inspect image {relative}: {exc}")

        record_id = str(item.get("record_id", index))
        by_record[record_id].append(actual_hash)
        variant = item.get("variant")
        if isinstance(variant, int):
            variants_by_record[record_id].append(variant)
        font = item.get("font")
        if isinstance(font, dict) and font.get("name"):
            font_name = str(font["name"])
            font_counts[font_name] += 1
            ordered_fonts.append(font_name)
            validate_font_reference(
                font,
                item.get("text") if isinstance(item.get("text"), str) else None,
                relative,
                errors,
                font_cache,
            )

        parameters = item.get("parameters")
        style: dict[str, Any] | None = None
        if mode in {"render", "batch"} and isinstance(manifest.get("resolved_style"), dict):
            style = manifest["resolved_style"]
        elif mode == "compare" and isinstance(manifest.get("resolved_styles"), dict):
            candidate = manifest["resolved_styles"].get(item.get("preset"))
            if isinstance(candidate, dict):
                style = candidate
        if isinstance(parameters, dict) and style is not None:
            trend = str(manifest.get("trend", "up"))
            errors.extend(
                f"{relative}: {problem}"
                for problem in resolved_parameter_errors(parameters, style, trend)
            )

    for record_id, hashes in by_record.items():
        if len(hashes) != len(set(hashes)):
            errors.append(f"duplicate output hashes for record {record_id}")
    variants_per_record = manifest.get("variants_per_record")
    if mode in {"render", "batch"} and isinstance(variants_per_record, int):
        expected_variants = list(range(1, variants_per_record + 1))
        for record_id in by_record:
            if sorted(variants_by_record[record_id]) != expected_variants:
                errors.append(
                    f"record {record_id} variants are {sorted(variants_by_record[record_id])}, "
                    f"expected {expected_variants}"
                )

    if len(set(ordered_fonts)) > 1:
        repeats = [
            index + 2
            for index, (previous, current) in enumerate(zip(ordered_fonts, ordered_fonts[1:]))
            if previous == current
        ]
        if repeats:
            warnings.append(f"adjacent outputs repeat a font at positions: {repeats}")
    if manifest.get("font_policy") == "balanced" and len(font_counts) > 1:
        spread = max(font_counts.values()) - min(font_counts.values())
        if spread > 1:
            warnings.append(
                "font usage differs by more than one; this can be valid when glyph coverage differs"
            )

    page_font = manifest.get("font")
    if mode == "page" and isinstance(page_font, dict):
        validate_font_reference(
            page_font,
            manifest.get("text") if isinstance(manifest.get("text"), str) else None,
            "page",
            errors,
            font_cache,
        )

    zip_path = root.with_suffix(".zip")
    if zip_path.is_file():
        expected_entries = {
            str(item["file"])
            for item in outputs
            if isinstance(item, dict) and isinstance(item.get("file"), str)
        }
        preview = manifest.get("preview")
        if isinstance(preview, str):
            expected_entries.add(preview)
        pdf = manifest.get("pdf")
        if isinstance(pdf, str):
            expected_entries.add(pdf)
        expected_entries.add(manifest_path.name)
        with zipfile.ZipFile(zip_path) as archive:
            actual_entries = set(archive.namelist())
            if actual_entries != expected_entries:
                missing = sorted(expected_entries - actual_entries)
                extra = sorted(actual_entries - expected_entries)
                errors.append(f"ZIP entry mismatch; missing={missing}, extra={extra}")
            elif archive.read(manifest_path.name) != manifest_path.read_bytes():
                errors.append("manifest inside ZIP differs from the on-disk manifest")
    return {
        "passed": not errors,
        "manifest": str(manifest_path),
        "checked_outputs": len(outputs),
        "errors": errors,
        "warnings": warnings,
        "font_distribution": dict(font_counts),
        "deep_font_checks": manifest.get("manifest_level") == "full",
    }


def add_font_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--font", action="append", default=[], help="font file; repeatable")
    parser.add_argument(
        "--font-dir", action="append", default=[], help="directory searched recursively; repeatable"
    )
    parser.add_argument(
        "--include-bundled-fonts",
        action="store_true",
        help="combine the bundled OFL font pool with explicit --font/--font-dir inputs",
    )


def add_output_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", required=True)
    parser.add_argument("--zip", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--preview-limit", type=int, default=60)
    parser.add_argument("--preview-title", default="Chinese handwriting preview")
    parser.add_argument("--hide-preview-labels", action="store_true")


def add_manifest_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--manifest-level", choices=("none", "minimal", "full"), default="minimal"
    )
    parser.add_argument("--synthetic-test-data", action="store_true")


def add_style_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--preset", choices=tuple(STYLE_PRESETS), default="natural")
    parser.add_argument("--style-config")
    parser.add_argument("--canvas", type=parse_size, default=DEFAULT_CANVAS)
    parser.add_argument("--background", default="white")
    parser.add_argument("--trend", choices=("up", "flat", "down"), default="up")
    parser.add_argument("--angle", type=parse_range)
    parser.add_argument("--ink", type=parse_color)
    parser.add_argument("--safe-margin", type=int)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline Chinese handwriting generation and scan simulation"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    render = subparsers.add_parser("render", help="one short text, N variants")
    render.add_argument("--text", required=True)
    render.add_argument("--variants", type=int, default=1)
    render.add_argument("--font-policy", choices=("balanced", "random", "fixed"), default="balanced")
    render.add_argument("--seed", type=int, default=DEFAULT_SEED)
    render.add_argument("--name-files", action="store_true")
    add_font_arguments(render)
    add_style_arguments(render)
    add_manifest_arguments(render)
    add_output_arguments(render)

    batch = subparsers.add_parser("batch", help="TXT, JSON, or CSV records")
    batch.add_argument("--input", required=True)
    batch.add_argument("--field")
    batch.add_argument("--variants", type=int, default=1)
    batch.add_argument("--font-policy", choices=("balanced", "random", "fixed"), default="balanced")
    batch.add_argument("--seed", type=int, default=DEFAULT_SEED)
    batch.add_argument("--name-files", action="store_true")
    add_font_arguments(batch)
    add_style_arguments(batch)
    add_manifest_arguments(batch)
    add_output_arguments(batch)

    page = subparsers.add_parser("page", help="long text with wrapping and pagination")
    page.add_argument("--text")
    page.add_argument("--input")
    page.add_argument("--paper", choices=("white", "lined", "grid"), default="white")
    page.add_argument("--background-image")
    page.add_argument("--page-size", type=parse_size, default=(2480, 3508))
    page.add_argument("--dpi", type=int, default=300)
    page.add_argument("--margin", type=int, default=180)
    page.add_argument("--font-size", type=int)
    page.add_argument("--line-spacing", type=int)
    page.add_argument("--pdf", action="store_true")
    page.add_argument("--seed", type=int, default=DEFAULT_SEED)
    page.add_argument("--preset", choices=tuple(STYLE_PRESETS), default="note")
    page.add_argument("--style-config")
    page.add_argument("--ink", type=parse_color)
    add_font_arguments(page)
    add_manifest_arguments(page)
    add_output_arguments(page)

    compare = subparsers.add_parser("compare", help="font and preset contact sheet")
    compare.add_argument("--text", required=True)
    compare.add_argument("--presets", default="subtle,natural,strong")
    compare.add_argument("--max-fonts", type=int, default=20)
    compare.add_argument("--seed", type=int, default=DEFAULT_SEED)
    compare.add_argument("--preset", choices=tuple(STYLE_PRESETS), default="natural")
    compare.add_argument("--style-config")
    compare.add_argument("--canvas", type=parse_size, default=DEFAULT_CANVAS)
    compare.add_argument("--background", default="white")
    compare.add_argument("--trend", choices=("up", "flat", "down"), default="up")
    compare.add_argument("--angle", type=parse_range)
    compare.add_argument("--ink", type=parse_color)
    compare.add_argument("--safe-margin", type=int)
    add_font_arguments(compare)
    add_manifest_arguments(compare)
    add_output_arguments(compare)

    scan = subparsers.add_parser("scan", help="scan/photocopy post-processing")
    scan.add_argument("--input", required=True)
    scan.add_argument("--preset", choices=tuple(SCAN_PRESETS), default="clean-scan")
    scan.add_argument("--format", choices=("auto", "png", "jpg"), default="auto")
    scan.add_argument("--dpi", type=int, default=300)
    scan.add_argument("--seed", type=int, default=DEFAULT_SEED)
    add_output_arguments(scan)

    inspect_font = subparsers.add_parser("inspect-font", help="font glyph coverage")
    inspect_font.add_argument("--text")
    inspect_font.add_argument("--input")
    inspect_font.add_argument("--field")
    add_font_arguments(inspect_font)

    validate = subparsers.add_parser("validate", help="verify a generated manifest")
    validate.add_argument("--manifest", required=True)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if hasattr(args, "variants") and args.variants < 1:
            raise UserInputError("variants must be at least 1")
        if hasattr(args, "preview_limit") and args.preview_limit < 1:
            raise UserInputError("preview-limit must be at least 1")
        if args.command == "render":
            result = run_short_generation(args, [{"id": "1", "text": args.text}], "render")
        elif args.command == "batch":
            result = run_short_generation(args, read_records(Path(args.input), args.field), "batch")
        elif args.command == "page":
            result = run_page(args)
        elif args.command == "compare":
            result = run_compare(args)
        elif args.command == "scan":
            result = run_scan(args)
        elif args.command == "inspect-font":
            result = run_inspect_font(args)
        else:
            result = run_validate(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "validate" and not result["passed"]:
            raise SystemExit(1)
    except (UserInputError, OSError, json.JSONDecodeError, argparse.ArgumentTypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
