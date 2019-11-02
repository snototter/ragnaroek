#!/usr/bin/python
# coding=utf-8
"""Basic drawing/plotting capabilities for temperature graphs, e-ink display, etc."""

#TODO remove this import once we've finished testing
import sys
sys.path.append('.')


# uninstall humor sans
# rm .local/share/fonts/Humor-Sans-1.0.ttf
# delete cache
# rm .cache/matplotlib/fontlist-v310.json
# edit xkcd font, http://www.glyphrstudio.com/online/
# name it Humor Sans, add degree sign, etc
# install it
# rebuild font cache
# fc-cache -f -v


# #What works:
# replace xkcd font by my extension with circ + other extended glyphs (or replace rcParams directly after plt.xkcd() call)
#
#
# # #https://matplotlib.org/3.1.1/api/font_manager_api.html
# # #http://jakevdp.github.io/blog/2012/10/07/xkcd-style-plots-in-matplotlib/
# # sudo fc-cache -fv
# # rm -fr ~/.cache/matplotlib
# import matplotlib
# import matplotlib.pyplot as plt
# import numpy as np
# # Change all the fonts to humor-sans.
# with plt.xkcd():
#     fig = plt.figure()
#     # ax = fig.gca()
#     ax = fig.add_subplot(1,1,1)
#     # plt.rcParams['font.family'] = 'sans-serif'
#     # plt.rcParams['font.sans-serif'] = 'xkcdext'
#     x = np.arange(0, 3, 0.2)
#     ax.plot(x, x**2)
#     plt.xlabel('x °C $^\circ$Circ')
#     plt.ylabel('y °C $^\circ$Circ')
#     plt.title('Foo bla °C $^\circ$Circ')
#     plt.show()

# # fig = plt.figure()
# # # ax = fig.gca()
# # ax = fig.add_subplot(1,1,1)
# # plt.rcParams['font.family'] = 'sans-serif'
# # plt.rcParams['font.sans-serif'] = 'xkcdext'
# # plt.rcParams['font.size'] = 20
# # x = np.arange(0, 3, 0.2)
# # ax.plot(x, x**2)
# # plt.xlabel('x °C $^\circ$Circ')
# # plt.ylabel('y °C $^\circ$Circ')
# # plt.title('Foo bla °C $^\circ$Circ')
# # plt.show()

# with plt.xkcd():
#     plt.rcParams['font.family'] = 'sans-serif'
#     plt.rcParams['font.sans-serif'] = 'Humor Sans'
#     fig = plt.figure()
#     ax = fig.add_subplot(1,1,1)
#     x = np.arange(0, 3, 0.2)
#     ax.plot(x, x**2)
#     ax.tick_params(axis='x', direction='in')
#     plt.xlabel('x °C $^\circ$Circ')
#     plt.ylabel('y °C $^\circ$Circ')
#     plt.title('Foo bla °C $^\circ$Circ')
#     plt.show()




import matplotlib
# matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import logging

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

from . import time_utils

def curve_color(idx, colormap=plt.cm.jet, distinct_colors=10):
    lookup = np.linspace(0., 1., distinct_colors)
    c = colormap(lookup[idx % distinct_colors])
    return c[:3]


#from . import time_utils
def plot_temperature_curves(width_px, height_px, temperature_log, 
    return_mem=True, xkcd=True, reverse=True, name_mapping=None):
    """
    return_mem: save plot into a BytesIO buffer and return it, otherwise shows the plot (blocking, for debug)
    xkcd: :-)
    reverse: reverse the temperature readings (if temperature_log[0] is the most recent reading)
    name_mapping: provide a dictionary if you want to rename the curves
    """
    #TODO params
    alpha = 0.9
    linewidth = 2.5
    dpi = 100
    every_nth_tick = 3 # show every n-th tick label
    target_temperature_span = 10
    ### Prepare the data
    if reverse:
        temperature_log = temperature_log[::-1]

    # Get names and number of sensors
    sensor_names = set()
    for reading in temperature_log:
        _, sensors = reading
        if sensors is not None:
            sensor_names.update(sensors.keys())

    # Sort sensor names to ensure consistent colors
    sensor_names = sorted(sensor_names)
    num_sensors = len(sensor_names)
    
    if num_sensors == 0:
        logging.getLogger().warning('plot_temperature_curves() called with empty list!')
        if return_mem:
            return None
        else:
            return

    # Prepare curve colors and names
    idx = 0
    colors = dict()
    plot_labels = dict()
    for sn in sensor_names:
        colors[sn] = curve_color(idx, colormap=plt.cm.winter, distinct_colors=num_sensors)
        plot_labels[sn] = sn if name_mapping is None else name_mapping[sn]
        idx += 1

    # Extract curves
    temperature_curves = {sn:list() for sn in sensor_names}
    x_tick_labels = list()
    for idx in range(len(temperature_log)):
        dt_local, sensors = temperature_log[idx]
        # x_tick_labels.append(dt_local) # TODO dt_local.hour : dt_local.minute or timedelta (now-dt_local) in minutes!

        #time_utils.dt_now_local()
        #TODO adjust every_nth_tick (if plotting the full day) + h instead of minutes

        if idx % every_nth_tick == 0:
            x_tick_labels.append('{:d}:{:d}'.format(dt_local.hour, dt_local.minute)) # TODO dt_local.hour : dt_local.minute or timedelta (now-dt_local) in minutes!
        else:
            x_tick_labels.append('')

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
    plt.rcParams.update({'font.size': 22})
    ax = fig.gca()

    for sn in sensor_names:
        unzipped = tuple(zip(*temperature_curves[sn]))
        ax.plot(unzipped[0], unzipped[1], \
            color=colors[sn], alpha=alpha, linestyle='-', linewidth=linewidth, \
            label=plot_labels[sn], marker='.', markersize=5*linewidth, markeredgewidth=linewidth)

    # Adjust x axis
    ax.tick_params(axis ='x', rotation=45, direction='in') # See https://www.geeksforgeeks.org/python-matplotlib-pyplot-ticks/
    plt.xticks(range(len(x_tick_labels)), x_tick_labels)

    # Adjust y axis
    ymin, ymax = plt.ylim()
    span = ymax - ymin
    delta = np.ceil(target_temperature_span - span)
    if delta > 0:
        ymin = ymin - delta * 0.7
        ymax = ymax + delta * 0.3
        plt.ylim(ymin, ymax)
    
    # Adjust y ticks
    yminc = np.ceil(ymin)
    if yminc - ymin < 0.5:
        yminc += 1
    
    y_ticks = range(yminc.astype(np.int32), ymax.astype(np.int32), 2)
    y_tick_labels = ['{:d}°'.format(t) for t in y_ticks]
    ax.tick_params(axis='y', direction='in')
    plt.yticks(y_ticks, y_tick_labels)
    # TODO increase font size: legend, title, label
    
    plt.title('Temperaturverlauf [°C]')
    ax.grid(True, linewidth=linewidth-0.5, alpha=0.3)
    ax.legend(loc='lower center', fancybox=True, frameon=False, ncol=3) #framealpha=0.3 See https://matplotlib.org/3.1.1/api/_as_gen/matplotlib.pyplot.legend.html
        
    fig.tight_layout(pad=1.02) # pad=1.08 is default
    fig.canvas.draw()
    
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
    import collections
    dt = collections.namedtuple('dt', ['hour', 'minute'])
    plot_temperature_curves(1024, 768, 
        [(dt(0,5),{'K':23.5}), (dt(0,10),{'K':23.5, 'W':22}), (dt(0,15),{'K':25.5, 'W':24}),
        (dt(0,20), {'K':None, 'W':23}), (dt(0,25), {'K':22}), (dt(0,30), None), (dt(0,35), {'Foo':25}), 
        (dt(0,40), {'Foo':25.2, 'K':22.3})], return_mem=False, name_mapping={'K':'KiZi', 'W':'Wohnen', 'Foo':'xkcd:-)'}, reverse=False)
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

    
