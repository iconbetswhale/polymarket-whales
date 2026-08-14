from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = Path.home() / "Desktop"
OUTPUT = ROOT / "docs" / "visual-qa"


def find_reference(stem: str) -> Path:
    matches = list(DESKTOP.glob(f"{stem}*AM.png"))
    if not matches:
        raise FileNotFoundError(stem)
    return matches[0]


def build_comparison(name: str, reference: Path, implementation: Path) -> None:
    height = 900
    reference_image = Image.open(reference).convert("RGB")
    implementation_image = Image.open(implementation).convert("RGB")
    reference_image = reference_image.resize(
        (round(reference_image.width * height / reference_image.height), height)
    )
    implementation_image = implementation_image.resize(
        (round(implementation_image.width * height / implementation_image.height), height)
    )
    canvas = Image.new(
        "RGB",
        (reference_image.width + implementation_image.width + 24, height + 48),
        "#05090d",
    )
    canvas.paste(reference_image, (0, 48))
    canvas.paste(implementation_image, (reference_image.width + 24, 48))
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 14), "REFERENCE", fill="#ffffff")
    draw.text(
        (reference_image.width + 36, 14),
        "ICONLABS IMPLEMENTATION",
        fill="#ffffff",
    )
    canvas.save(OUTPUT / f"compare-{name}.png")


OUTPUT.mkdir(parents=True, exist_ok=True)
build_comparison(
    "trades",
    find_reference("Screenshot 2026-07-24 at 11.15.48"),
    ROOT / "qa-after-trades-1920x1080.png",
)
build_comparison(
    "odds",
    find_reference("Screenshot 2026-07-24 at 11.17.51"),
    ROOT / "qa-after-odds-1920x1080.png",
)
