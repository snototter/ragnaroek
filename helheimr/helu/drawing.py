#!/usr/bin/python
# coding=utf-8
"""Basic drawing/plotting capabilities for temperature graphs, e-ink display, etc."""

import matplotlib
# matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from PIL import Image
import io
# Save to numpy array: https://stackoverflow.com/questions/7821518/matplotlib-save-plot-to-numpy-array
# check resolution!

# otherwise, render to bytesio

# buf = io.BytesIO()
# ...
# image = Image.open(buf)


def pil2np(img_pil, flip_channels=False):
    img_np = np.array(img_pil)
    if len(img_np.shape) == 3 and img_np.shape[2] == 3 and flip_channels:
        # Convert RGB to BGR or vice versa
        return img_np[:, :, ::-1]
    else:
        return img_np

def np2pil(img_np):
    return Image.fromarray(img_np)

def plt2img(fig, dpi=180):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    buf.seek(0) #TODO is this necessary?
    # img_np = np.frombuffer(buf.getvalue(), dtype=np.uint8)
    img_pil = Image.open(io.BytesIO(buf.getvalue()))
    buf.close()
    # img = cv2.imdecode(img_arr, 1)
    # img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    # img_pil = Image.open(buf)
    # buf.close() #TODO is this necessary?
    img_np = pil2np(img_pil)
    if len(img_np.shape) == 3 and img_np.shape[2] == 4:
        img_np = img_np[:, :, :3]
    print(img_np.shape)
    return img_np
    # # return pil2np(img_pil)#TODO needs decoding?
    # print(img_np.shape)
    # img_pil = np2pil(img_np)
    # img_np = pil2np(img_pil)
    # print(img_np.shape)
    # return img_np

# # Make a random plot...
# fig = plt.figure()
# fig.add_subplot(111)

# # If we haven't already shown or saved the plot, then we need to
# # draw the figure first...
# fig.canvas.draw()

# # Now we can save it to a numpy array.

def plt2img_lowres(fig):
    #TODO check quality!
    img_np = np.fromstring(fig.canvas.tostring_rgb(), dtype=np.uint8, sep='')
    print(fig.canvas.get_width_height())
    img_np = img_np.reshape(fig.canvas.get_width_height()[::-1] + (3,))
    return img_np


def rgb2gray(rgb):
    r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
    gray = 0.2989 * r + 0.5870 * g + 0.1140 * b
    return gray.astype(rgb.dtype)

if __name__ == '__main__':
    target_fig_size = [1024, 768]
    default_dpi = 100
    fig = plt.figure(figsize=(target_fig_size[0]/default_dpi, target_fig_size[1]/default_dpi))
    plot = fig.add_subplot(111)

    x = np.arange(0., 5., 0.2)
    plot.plot(x, x, 'r--')
    plot.plot(x, x**2, 'bs')
    fig.canvas.draw()

    img_lowres = plt2img_lowres(fig)
    img_pil = np2pil(img_lowres)
    img_pil.save('dummy-lowres.jpg')

    img_highres = plt2img(fig, dpi=100)
    img_pil = np2pil(img_highres)
    img_pil.save('dummy-hires.jpg')

    plt.show()
