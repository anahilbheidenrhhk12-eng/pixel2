"""Crop only the bottom strip of step-six Telegram screenshots."""
import io
from PIL import Image


def crop_stage_six(payload):
    if not payload:
        return None
    with Image.open(io.BytesIO(payload)) as source:
        # 8% removes the bottom overlay across the desktop/mobile viewport sizes.
        height=max(1,source.height-max(32,round(source.height*.08)))
        cropped=source.crop((0,0,source.width,height))
        out=io.BytesIO();cropped.save(out,format='PNG');return out.getvalue()
