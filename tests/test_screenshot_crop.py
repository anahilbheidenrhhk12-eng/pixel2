import io
import unittest
from unittest.mock import MagicMock,patch
from PIL import Image
from screenshot_crop import crop_stage_six
import google_automation as automation

class CropTests(unittest.TestCase):
    def image(self):
        img=Image.new('RGB',(1280,900),'white')
        for y in range(850,900):
            for x in range(1280):img.putpixel((x,y),(255,0,0))
        out=io.BytesIO();img.save(out,format='PNG');return out.getvalue()
    def test_bottom_strip_removed(self):
        cropped=Image.open(io.BytesIO(crop_stage_six(self.image())))
        self.assertEqual(cropped.size,(1280,828))
        self.assertEqual(cropped.getpixel((1279,827)),(255,255,255))
    def test_other_stages_not_cropped(self):
        d=MagicMock();payload=self.image();d.get_screenshot_as_png.return_value=payload
        cb=MagicMock();automation._report(cb,'Step 2/6',d)
        self.assertEqual(cb.call_args.args[1],payload)
    def test_each_stage_six_report_and_final_photo_cropped(self):
        d=MagicMock();d.get_screenshot_as_png.return_value=self.image();seen=[]
        def stages(driver,url,progress,final_photo):
            progress('Step 6/6 — Annual billing selected.',driver)
            progress('Clicked Get Google AI Pro (Annual)',driver)
            return 'https://example.com/'
        def card(driver,progress,timeout):progress('Card form opened',driver);return True
        with patch.object(automation,'open_annual_ai_pro_checkout',side_effect=stages),patch.object(automation,'open_add_card_dialog',side_effect=card):
            automation._navigate_google_one(d,cb=lambda message,payload:seen.append(payload),interactive=True)
        self.assertEqual(len(seen),4)
        for payload in seen:self.assertEqual(Image.open(io.BytesIO(payload)).height,828)
