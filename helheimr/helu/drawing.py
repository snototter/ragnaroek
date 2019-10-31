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
    """Convert Pillow.Image to numpy.array."""
    img_np = np.array(img_pil)
    if len(img_np.shape) == 3 and img_np.shape[2] == 3 and flip_channels:
        # Convert RGB to BGR or vice versa
        return img_np[:, :, ::-1]
    else:
        return img_np


def np2pil(img_np):
    """Convert numpy.array to Pillow.Image."""
    return Image.fromarray(img_np)


def plt2img(fig, dpi=180):
    # Save plot to buffer...
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    # ... decode the buffer
    buf.seek(0)
    img_pil = Image.open(io.BytesIO(buf.getvalue()))
    buf.close()
    # ... return as numpy array (and remove alpha channel)
    img_np = pil2np(img_pil)
    if len(img_np.shape) == 3 and img_np.shape[2] == 4:
        img_np = img_np[:, :, :3]
    return img_np

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

##### matplotlib:
# * Lookup
#   https://matplotlib.org/api/_as_gen/matplotlib.pyplot.html#module-matplotlib.pyplot
# * Reduce margins/white borders:
#   https://stackoverflow.com/questions/4042192/reduce-left-and-right-margins-in-matplotlib-plot
# * Change font properties:
#   https://matplotlib.org/3.1.1/gallery/text_labels_and_annotations/text_fontdict.html
# * Grid 
#   https://stackoverflow.com/questions/8209568/how-do-i-draw-a-grid-onto-a-plot-in-python
# * Colormaps
#   https://matplotlib.org/3.1.0/tutorials/colors/colormaps.html
if __name__ == '__main__':
    target_fig_size = [1024, 768]
    default_dpi = 100
    fig = plt.figure(figsize=(target_fig_size[0]/default_dpi, target_fig_size[1]/default_dpi))
    axes = fig.add_subplot(111)
    # axes = fig.gca()

    with plt.xkcd():
        x = np.arange(0., 5., 0.2)
        axes.plot(x, x, 'r--')
        axes.plot(x, x**2, 'bs')
        

#     ax = fig.gca()
    axes.set_xticks(np.arange(0, 5, 0.5))
    axes.set_yticks(np.arange(0, 20, 2))
# plt.scatter(x, y)
    plt.xlim(-1, 4.4)
    plt.ylim(0.25, 20)
    # axes.grid()
    plt.grid()
# plt.show()

    # Change font, put labels, etc.
    font = {'family': 'xkcd Script', #'serif',
        'color':  'darkred',
        'weight': 'normal',
        'size': 16,
        }
    plt.title('Title Foo', fontdict=font)
    plt.text(2, 0.65, r'$\cos(2 \pi t) \exp(-t)$', fontdict=font)
    plt.xlabel('time (s)', fontdict=font)
    plt.ylabel('voltage (mV)', fontdict=font)

    # After all axes have been added, we can remove the white space around the axes:
    fig.tight_layout()
    # If run headless, we must ensure that the figure canvas is populated:
    fig.canvas.draw()

    img_lowres = plt2img_lowres(fig)
    img_pil = np2pil(img_lowres)
    img_pil.save('dummy-lowres.jpg')

    img_highres = plt2img(fig, dpi=2*default_dpi)
    img_pil = np2pil(img_highres)
    img_pil.save('dummy-hires.jpg')

    plt.show()
