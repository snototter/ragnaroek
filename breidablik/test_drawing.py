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
                font = ImageFont.truetype(os.path.join('..', 'assets', fs + ext), font_size, encoding="unic")
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
    gray = imutils.rgb2gray(img_np)
    imvis.imshow(gray, 'gray np')
    print(gray.dtype)
    mask_np = gray > 196
    # imvis.imshow(masked)
    # import iminspect
    # iminspect.show(masked)
    bw = Image.fromarray(mask_np)
    bw.show()




def draw_xkcd_text():
    # Images look way nicer if text is drawn on 3-channel image
    width, height = 400, 300
    img = Image.new('RGB', (width, height), 'white') # 1: clear the frame
    draw = ImageDraw.Draw(img)

    font = load_font(36)
    draw.text((10, 30), "Hello", font=font, fill=(80, 80, 80))
    draw.text((10, 100), "Hello @\u03c0 3.14", font=font, fill=(80, 80, 80))
    draw.rectangle((200, 80, 360, 280), fill=0)
    # img.show()
    cvt_bw(img)

if __name__ == '__main__':
    draw_xkcd_text()