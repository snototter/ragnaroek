#!/usr/bin/python
# coding=utf-8
"""Basic drawing/plotting capabilities for temperature graphs, e-ink display, etc."""

#TODO remove this import once we've finished testing
import sys
sys.path.append('.')


import matplotlib
# matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# with plt.xkcd():
#    x = np.linspace(0, 10)
#    y1 = x * np.sin(x)
#    y2 = x * np.cos(x)
#    plt.fill(x, y1, 'red', alpha=0.4)
#    plt.fill(x, y2, 'blue', alpha=0.4)
#    plt.xlabel('x axis yo!')
#    plt.ylabel("I don't even know")
# plt.show()

# fig = plt.figure()
# with plt.xkcd():
#    ax = fig.add_subplot(1, 1, 1)
#    ax.fill(x, y1, 'red', alpha=0.4)
#    ax.fill(x, y2, 'blue', alpha=0.4)
#    plt.xlabel('x axis yo!')
#    plt.ylabel("I don't even know")
# fig.canvas.draw()
# plt.show()

from PIL import Image
import io

def curve_color(idx, colormap=plt.cm.jet, distinct_colors=10):
    lookup = np.linspace(0., 1., distinct_colors)
    c = colormap(lookup[idx % distinct_colors])
    return c[:3]

#from . import time_utils
def plot_temperature_curves(width_px, height_px, temperature_log, return_mem=True, xkcd=True):
    alpha = 0.9
    linewidth = 2.5
    dpi = 100
    ### Prepare the data
    # Get names and number of sensors
    sensor_names = set()
    for reading in temperature_log:
        _, sensors = reading
        if sensors is not None:
            sensor_names.update(sensors.keys())

    sensor_names = sorted(sensor_names)
    num_sensors = len(sensor_names)
    
    if num_sensors == 0:
        print('warning!!!') #TODO
        if return_mem:
            return None
        else:
            return

    # Prepare curve colors
    idx = 0
    colors = dict()
    for sn in sensor_names:
        colors[sn] = curve_color(idx, colormap=plt.cm.viridis, distinct_colors=num_sensors)
        idx += 1

    # Extract curves
    temperature_curves = {sn:list() for sn in sensor_names}
    x_tick_labels = list()
    for idx in range(len(temperature_log)):
        dt_local, sensors = temperature_log[idx]
        x_tick_labels.append(dt_local) # TODO dt_local.hour : dt_local.minute or timedelta (now-dt_local) in minutes!

        if sensors is None:
            continue

        for sn in sensors.keys():
            if sensors[sn] is None:
                continue
            temperature_curves[sn].append((idx, sensors[sn]))
    

    ### Now we're ready to plot
    # Prepare figure of proper size
    fig = plt.figure(figsize=(width_px/dpi, height_px/dpi))
    if xkcd:
        plt.xkcd(scale=1, length=100, randomness=2)
    ax = fig.gca()

    for sn in sensor_names:
        unzipped = tuple(zip(*temperature_curves[sn]))
        ax.plot(unzipped[0], unzipped[1], \
            color=colors[sn], alpha=alpha, linestyle='-', linewidth=linewidth, \
            label=sn, marker='x', markersize=5*linewidth, markeredgewidth=linewidth)

    ax.tick_params(axis ='x', rotation = 45) # See https://www.geeksforgeeks.org/python-matplotlib-pyplot-ticks/
    plt.xticks(range(len(x_tick_labels)), x_tick_labels)

    plt.xlabel('Zeit...')
    plt.ylabel('Temperatur °C')
    ax.grid(True, linewidth=linewidth-0.5)
    ax.legend(loc='best') # See https://matplotlib.org/3.1.1/api/_as_gen/matplotlib.pyplot.legend.html
        
    fig.tight_layout(pad=1.02) # pad=1.08 is default
    fig.canvas.draw()
    # with plt.xkcd(): # TODO install humor sans
    
    img_np = plt2img(fig, dpi=dpi)
    img_pil = np2pil(img_np)

    if return_mem:
        return pil2memfile(img_pil)
    else:
        img_pil.save('dummy-temperature.jpg')
        plt.show()


def pil2np(img_pil, flip_channels=False):
    """Convert Pillow.Image to numpy.array."""
    img_np = np.array(img_pil)
    if len(img_np.shape) == 3 and img_np.shape[2] == 3 and flip_channels:
        # Convert RGB to BGR or vice versa
        return img_np[:, :, ::-1]
    else:
        return img_np


def pil2memfile(img_pil, name='image.jpg'):
    """Write the image into a buffer kept in RAM."""
    memfile = io.BytesIO()
    memfile.name = name
    img_pil.save(memfile, 'jpeg') #'png')
    memfile.seek(0)
    return memfile


def np2pil(img_np):
    """Convert numpy.array to Pillow.Image."""
    return Image.fromarray(img_np)


def np2memfile(np_data):
    """Convert numpy (image) array to ByteIO stream"""
    # print('converting {}'.format(np_data.shape))
    # TODO handle grayvalue (call standard data.transpose)
    # if rotate:
    #     np_data = np.flip(np.transpose(np_data, (1,0,2)), axis=1)
    return pil2memfile(np2pil(img_np))


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
#   https://stackoverflow.com/questions/8931268/using-colormaps-to-set-color-of-line-in-matplotlib

if __name__ == '__main__':
    plot_temperature_curves(1024, 768, 
        [('a',{'K':23.5}), ('b',{'K':23.5, 'W':22}), ('c',{'K':25.5, 'W':24}),
        ('d', {'K':None, 'W':23}), ('e', {'K':22}), ('f', None), ('g', {'Foo':25}), ('h', {'Foo':25.2, 'K':22.3})], return_mem=False)
    if True:
        raise RuntimeError('stop')

    target_fig_size_px = [1024, 768]
    dpi = 100
    fig = plt.figure(figsize=tuple([t/dpi for t in target_fig_size_px]))
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

        plt.title('jabadabadoo')
        # # Change font, put labels, etc.
        # font = {'family': 'xkcd Script', #'serif',
        #     'color':  'darkred',
        #     'weight': 'normal',
        #     'size': 16,
        #     }
        # plt.title('Title Foo', fontdict=font)
        # plt.text(2, 0.65, r'$\cos(2 \pi t) \exp(-t)$', fontdict=font)
        # plt.xlabel('time (s)', fontdict=font)
        # plt.ylabel('voltage (mV)', fontdict=font)

    # After all axes have been added, we can remove the white space around the axes:
    fig.tight_layout()
    # If run headless, we must ensure that the figure canvas is populated:
    fig.canvas.draw()

    img_lowres = plt2img_lowres(fig)
    img_pil = np2pil(img_lowres)
    img_pil.save('dummy-lowres.jpg')

    img_highres = plt2img(fig, dpi=2*dpi)
    img_pil = np2pil(img_highres)
    img_pil.save('dummy-hires.jpg')

    plt.show()

    
