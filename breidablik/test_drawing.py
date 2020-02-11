from PIL import Image, ImageFont, ImageDraw
import os
import numpy as np
from vito import imutils
from vito import imvis

def load_font(font_size):
    fonts = ['xkcdext-Regular', 'xkcd-Regular']
    for fs in fonts:
        for ext in ['.otf', '.ttf']:
            try:
                font = ImageFont.truetype(os.path.join('..', 'assets', fs + ext), size=font_size, encoding="unic", index=0, layout_engine=ImageFont.LAYOUT_RAQM)
                return font
            except IOError as e:
                print(fs + ext, e)
                pass
    return None

def cvt_bw(img_pil):
    # Simply converting looks pretty ugly
    # bw_pil = img_pil.convert('1') 
    # bw_pil.show()
    img_np = np.asarray(img_pil)
    # gray = imutils.rgb2gray(img_np)
    # imvis.imshow(gray, 'gray np')
    # print(gray.dtype)
    mask_np = np.max(img_np, axis=2) > 128
    # imvis.imshow(masked)
    # import iminspect
    # iminspect.show(masked)
    bw = Image.fromarray(mask_np)
    bw.show()




def draw_xkcd_text():
    scale_factor = 2
    # Images look way nicer if text is drawn on 3-channel image
    width, height = 300, 400
    font_size = 36
    img = Image.new('RGB', (scale_factor * width, scale_factor * height), 'white') # 1: clear the frame
    draw = ImageDraw.Draw(img)

    font = load_font(scale_factor * font_size)
    draw.text((scale_factor * 10, scale_factor * 30), "Hello", font=font, fill=(0, 0, 0))
    draw.text((scale_factor * 10, scale_factor * 100), "Hello @\u03c0 3.14", font=font, fill=(0, 0, 0))
    draw.rectangle((200, 80, 360, 280), fill=0)

    # Default text rendering with PIL is ugly to say the least...
    # https://stackoverflow.com/questions/5414639/python-imaging-library-text-rendering
    img.show()
    img = img.resize((width, height), Image.BICUBIC)# Image.ANTIALIAS)
    # img.show()
    cvt_bw(img)

if __name__ == '__main__':
    draw_xkcd_text()