from __future__ import annotations

from pathlib import Path

import qrcode


ROOT = Path(__file__).resolve().parent
QR_TARGETS = {
    "qr-site": "https://www.checkupauto.fr/app?src=qr-site",
    "qr-centre": "https://www.checkupauto.fr/app?src=qr-centre",
}
QR_PRINT_SIZE_MM = 37


def payload(name: str) -> str:
    try:
        return QR_TARGETS[name]
    except KeyError as exc:
        raise ValueError("QR de distribution inconnu") from exc


def render_svg(name: str) -> bytes:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=4,
    )
    qr.add_data(payload(name))
    qr.make(fit=True)
    matrix = qr.get_matrix()
    size = len(matrix)
    path = "".join(
        f"M{x},{y}H{x + 1}V{y + 1}H{x}z"
        for y, row in enumerate(matrix)
        for x, dark in enumerate(row)
        if dark
    )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        f'<svg width="{QR_PRINT_SIZE_MM}mm" height="{QR_PRINT_SIZE_MM}mm" version="1.1" '
        f'viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg">'
        f'<rect x="0" y="0" width="{size}" height="{size}" fill="#ffffff"/>'
        f'<path d="{path}" id="qr-path" fill="#000000" fill-opacity="1" '
        'fill-rule="nonzero" stroke="none" /></svg>\n'
    ).encode("utf-8")


def asset_path(name: str) -> Path:
    if name not in QR_TARGETS:
        raise ValueError("QR de distribution inconnu")
    return ROOT / "assets" / "app" / f"{name}.svg"


def check_assets() -> dict[str, bool]:
    return {
        name: asset_path(name).read_bytes() == render_svg(name)
        for name in QR_TARGETS
    }


def write_assets() -> None:
    for name in QR_TARGETS:
        asset_path(name).write_bytes(render_svg(name))


if __name__ == "__main__":
    state = check_assets()
    if not all(state.values()):
        stale = ", ".join(name for name, valid in state.items() if not valid)
        raise SystemExit(f"QR assets out of date: {stale}")
    print("QR distribution assets verified")
