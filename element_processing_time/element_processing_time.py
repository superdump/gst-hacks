# element_processing_time.py
# A script to parse GStreamer 1.0 debug logs and produce graphs of element
# processing times
# Copyright (C) 2014-2015 Robert Swain <robert.swain@ericsson.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

import sys
import os.path
import re
import array
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import collections
import time
import networkx as nx

LINE_LIMIT = 1e6

CONST_NS = 1.0
CONST_US = 1000 * CONST_NS
CONST_MS = 1000 * CONST_US
CONST_SECOND = 1000 * CONST_MS
CONST_MINUTE = 60 * CONST_SECOND
CONST_HOUR = 60 * CONST_MINUTE

def gst_time_format_to_ns(string):
  pieces = re.split('[:\.]', string)
  if int(pieces[0]) == 99:
      return -1
  return int(CONST_HOUR * int(pieces[0]) + CONST_MINUTE * int(pieces[1]) + CONST_SECOND * int(pieces[2]) + int(pieces[3]))

file_path = sys.argv[1]
print 'Opening:', file_path

os.path.isfile(file_path)

f = open(file_path, 'r')
print "Counting lines..."
num_lines = sum(1 for line in f)
f.seek(0)
print "Input has %d lines" % (num_lines)
one_percent = num_lines // 100


# Process input
# This both gathers the timings and builds a pipeline graph

# compile the regexes for a bit better performance

regex_calling = re.compile(r"(\d+:\d+:\d+\.\d+)\s+(?:\d+)\s+(0x[a-fA-F0-9]+).*GST_SCHEDULING.*<(.*):.*> calling.*buffer.*(0x[a-fA-F0-9]+).*pts (\d+:\d+:\d+\.\d+)")

regex_called = re.compile(r"(\d+:\d+:\d+\.\d+)\s+(?:\d+)\s+(0x[a-fA-F0-9]+).*GST_SCHEDULING.*<(.*):.*> called.*buffer.*(0x[a-fA-F0-9]+)")

regex_element_link_pads = re.compile(r".*GST_ELEMENT_PADS.* linked pad (.*):.* to pad (.*):.*")

regex_element_link = re.compile(r".*GST_ELEMENT_PADS.* link element (.*):.* to element (.*):.*")

regex_pad_link = re.compile(r".*GST_PADS.* link (.*):.* and (.*):.*")

pipeline = nx.DiGraph()
d = collections.OrderedDict()
buffers = {}
line_num = 0
start = time.clock()
for line in f:
    if line_num % one_percent == 0:
        now = time.clock()
        print "[{0: 4.3f}s]\tProgress: {2:d}/{3:d} lines\t({1: 3.2%}\t\t{4:.2f} lines per second)\tETA {5: 4.3f}s".format((now - start), line_num / float(num_lines), line_num, num_lines, line_num / (now - start), 0.0 if line_num == 0 else ((now - start) * (num_lines - line_num) / line_num))
    line_num += 1
    if line_num >= LINE_LIMIT:
        print "Reached line limit (%d), continuing to analysis" % LINE_LIMIT
        break

    match = regex_calling.match(line)
    if match:
        message_time, thread, element_name, buffer_ptr, buffer_pts = match.group(1,2,3,4,5)

        buffer_ns = gst_time_format_to_ns(buffer_pts)
        if buffer_ns not in d:
            d[buffer_ns] = {}

        # store the most recent buffer_ns for a buffer_ptr
        # hopefully this is usable for looking up the buffer_ns when the chain functions return
        buffers[buffer_ptr] = buffer_ns

        message_ns = gst_time_format_to_ns(message_time)
        d[buffer_ns][element_name] = {'call_time': message_ns, 'buffer_ptr': buffer_ptr, 'thread': thread}

        continue

    match = regex_called.match(line)
    if match:
        message_time, thread, name, buffer_ptr = match.group(1,2,3,4)
        try:
            return_ns = buffers[buffer_ptr]
            if name in d[return_ns] and d[return_ns][name]['buffer_ptr'] == buffer_ptr:
                d[return_ns][name]['return_time'] = gst_time_format_to_ns(message_time)
            # for elem in elements:
            #     if elem['name'] == name and elem['buffer_ptr'] == buffer_ptr:
            #         elem['return_time'] = gst_time_format_to_ns(message_time)
        except KeyError:
            continue
        continue

    match = regex_pad_link.match(line)
    if match:
        left, right = match.group(1,2)
        pipeline.add_edge(left, right)
        continue
    match = regex_element_link_pads.match(line)
    if match:
        left, right = match.group(1,2)
        pipeline.add_edge(left, right)
        continue
    match = regex_element_link.match(line)
    if match:
        left, right = match.group(1,2)
        pipeline.add_edge(left, right)
        continue

print "\n\nTaken", len(d), "measurements"

figure = 0
def get_figure_number():
    global figure
    ret = figure
    figure += 1
    return ret

print "Plotting pipeline graph"
plt.figure(get_figure_number())
nx.draw_graphviz(pipeline)

# sources = []
# sinks = []
# for node in pipeline.nodes():
#     parents = nx.ancestors(pipeline, node)
#     children = nx.descendants(pipeline, node)
#     if len(children) == 0 and "sink" in node:
#         sinks.append(node)
#     elif len(parents) == 0 and ("source" in node or "src" in node):
#         sources.append(node)
#
# print sources
# print sinks


# Process results
def get_element_timing(timings, elem_name):
    try:
        return timings[elem_name]
    except KeyError:
        return None

def prepare_result_for_node(node, timings, results):
    element_name, children = node
    timing = get_element_timing(timings, element_name)

    if element_name not in results:
        results[element_name] = []

    if not timing:
        # we have to make entries for every single element for each buffer ts
        # to keep alignment in the arrays used when plotting
        results[element_name].append(0.0)
        return
    elif len(children) == 0:
        # node is a sink so we calculate the
        diff_ms = 0.0
        if 'return_time' in timing:
            diff_ms = (timing['return_time'] - timing['call_time']) / CONST_MS
            # results[element_name].append(diff_ms)
        results[element_name].append(diff_ms)
    else:
        # gather call_time for all children and take the max
        max_child_call_time = 0
        for child in children:
            next_timing = get_element_timing(timings, child)
            if next_timing and 'call_time' in next_timing and next_timing['call_time'] > max_child_call_time:
                max_child_call_time = next_timing['call_time']

        # add the time between when this element received a buffer and when the last
        # child received it
        diff_ms = 0.0
        if max_child_call_time > 0:
            diff_ms = (max_child_call_time - timing['call_time']) / CONST_MS
            # results[element_name].append(diff_ms)
        results[element_name].append(diff_ms)

    # FIXME - it would be awesome if this could be automated instead of hard-coded
    # it isn't easy when everything goes through rtpbin and we have rtp/rtcp nicesrc elements...
    # if element_name in sinks:
    #     diff_ms = 0.0
    #     if element_name == "local-videosink":
    #         source_name = 'video-source-color-space'
    #         result_name = 'video-self'
    #     elif element_name == "recv-videosink":
    #         source_name = 'video-dtls-srtp-decoder'
    #         result_name = 'video-remote'
    #     elif element_name == "nicesink0":
    #         source_name = 'video-source-color-space'
    #         result_name = 'video-send'
    #     elif element_name == "audio-sink":
    #         source_name = 'audio-dtls-srtp-decoder'
    #         result_name = 'audio-remote'
    #     elif element_name == "nicesink2":
    #         source_name = 'send-audio-volume'
    #         result_name = 'audio-send'
    #     else:
    #         source_name = 'unknown'
    #         result_name = 'fakesink-ignore'
    #
    #     source_timing = get_element_timing(timings, source_name)
    #     print "Got", element_name, "timing\ntiming:", timing, "\nsource-timing:", source_timing
    #     if timing and 'return_time' in timing and source_timing and 'call_time' in source_timing:
    #         diff_ms = (timing['return_time'] - source_timing['call_time']) / CONST_MS
    #     print "Appending", result_name, "timing:", diff_ms
    #     results[result_name].append(diff_ms)
    #     if timing:
    #         print source_name
    #         print timings

    return

# FIXME - horrible hack hardcoding elements in each thread
# to be fixed by proper pipeline graph to nx graph import
video_to_tee = ['videosource', 'video-source-color-space', 'videosrcfilter', 'local-video-rate', 'video-crop', 'video-flip', 'video-tee']
video_send = video_to_tee + ['send-video-enc-q', 'videoencoder', 'video-rtp-payloader', 'video-rtp-capsfilter', 'send-video-tp-q', 'rtpbin', 'video-dtls-srtp-encoder', 'nicesink0']
video_self_view = video_to_tee + ['send-video-selfview-q', 'video-sink-capsfilter', 'local-videosink']
video_receive = ['nicesrc0', 'video-recv-rtprtcp-demux', 'rtpbin', 'video-rtp-depay', 'videorepair0', 'videodecoder', 'recv-colorspace', 'video-recv-capsfilter', 'recv-video-remoteview-q', 'recv-videosink']
audio_send = ['audio-src', 'send-audio-volume', 'send-audio-convert', 'send-audio-resample', 'audio-channels-capsfilter', 'send-audio-end-q', 'audio-encode', 'audio-rtp-payloader', 'audio-rtp-capsfilter', 'send-audio-tp-q', 'rtpbin', 'audio-dtls-srtp-encoder', 'nicesink2']
audio_receive = ['nicesrc2', 'audio-recv-rtprtcp-demux', 'rtpbin', 'audio-rtp-depay', 'audio-decode', 'recv-audio-convert', 'audio-resample', 'audio-sink']

print "Processing results..."

results = collections.OrderedDict()
results['buffer_ts'] = []
# results['video-self'] = []
# results['video-send'] = []
# results['video-remote'] = []
# results['audio-send'] = []
# results['audio-remote'] = []
# results['fakesink-ignore'] = []
for buf_ts, timings in d.items():
    if buf_ts < 1 * CONST_MS:
        continue
    results['buffer_ts'].append(buf_ts)
    for node in pipeline.adjacency_iter():
        prepare_result_for_node(node, timings, results)

# For pipelines with multiple threads, each thread can process a a buffer with
# a specific timestamp in different orders. Therefore we want to sort the results
# by buffer timestamp

print "Sorting results by buffer timestamp..."

# order = [results['buffer_ts'].index(i) for i in sorted(results['buffer_ts'])]
order = sorted(range(len(results['buffer_ts'])), key=lambda i: results['buffer_ts'][i])
for key in results.keys():
    if key == 'buffer_ts':
        continue
    if len(results[key]) == 0:
        results.pop(key, None)
        continue
    results[key] = [results[key][i] for i in order]

# Prepare the list of lists for zipping
# lists = []
# for v in results.values():
#     lists.append(v)

# Unpack the list of lists to a list of arguments for zip() and sort
# This was supposed to be in-place but it does not seem to be
# tuples = zip(*lists)
# tuples.sort()
# lists = zip(*tuples)

# print lists

# Re-assign the lists to their rightful place in the results dictionary
# count = 0
# for k in results.keys():
#     results[k] = lists[count]
#     count += 1

# Code to check that the lists are sorted by buffer time
# def is_sorted(l):
#     for i in xrange(len(l)-1):
#         if l[i] > l[i+1]:
#             print l[i], ">", l[i+1]
#             return False
#     return True
#
# print "Results", "are" if is_sorted(results['buffer_ts']) else "are not", "sorted"

print "Sorting plots by relevance (mean + standard deviation)..."
# Try sorting by mean + standard deviation. Mean feels useful but also something about
# the spread seems useful. I decided mean + 1 standard deviation could be a useful
# combination
metric = {}
for element in results.keys():
    if element == 'buffer_ts':
        continue
    average = sum(results[element]) / len(results[element])
    stddev = np.std(results[element])
    metric[element] = average + stddev

import operator
sorted_elements = sorted(metric.iteritems(), key=operator.itemgetter(1), reverse=True)

# specials = ['video-self', 'video-send', 'video-remote', 'audio-send', 'audio-remote']

# BOX PLOTS
#
# plt.figure(get_figure_number())
# axes = plt.subplot()
# axes.set_title('Receiver Video Processing Elements')
# axes.set_xlabel('element')
# axes.set_ylabel('frame processing time (ms)')
# video_receive_results = []
# for element in video_receive:
#     if element in results:
#         video_receive_results.append(results[element])
#     else:
#         video_receive_results.append([])
#
#
# axes.boxplot(video_receive_results, vert=1)
# xtickNames = plt.setp(axes, xticklabels=video_receive)
# plt.setp(xtickNames, rotation=45, fontsize=8)
# axes.legend()
#
#
# plt.figure(get_figure_number())
# axes = plt.subplot()
# axes.set_title('Receiver Audio Processing Elements')
# axes.set_xlabel('element')
# axes.set_ylabel('frame processing time (ms)')
# audio_receive_results = []
# for element in audio_receive:
#     if element in results:
#         audio_receive_results.append(results[element])
#     else:
#         audio_receive_results.append([])
#
#
# axes.boxplot(audio_receive_results, vert=1)
# xtickNames = plt.setp(axes, xticklabels=audio_receive)
# plt.setp(xtickNames, rotation=45, fontsize=8)
# axes.legend()
#
# plt.show()
# sys.exit()

# Plot results
N_SERIES_PER_PLOT = 7
nplots = (len(sorted_elements) // N_SERIES_PER_PLOT) + 1
count = -1
for element, metric_value in sorted_elements:
    # if element == 'fakesink-ignore' or element in specials:
    #     continue
    if metric_value < 1.0:
        print "Not plotting", element, "as mean + stddev processing time is insignificant"
        continue
    print "Plotting", element
    count += 1
    if not count % N_SERIES_PER_PLOT:
        plt.figure(get_figure_number())
        # create a new subplot and plot the next N_SERIES_PER_PLOT plots to it
        axes = plt.subplot()
        axes.set_xlabel('buffer time (ns)')
        # Make the y-axis label and tick labels match the line color.
        axes.set_ylabel('frame processing time (ms)')
    axes.plot(results['buffer_ts'], results[element], '.', label=element)
    axes.legend()

# for element in specials:
#     plt.figure(get_figure_number())
#     # create a new subplot and plot the next N_SERIES_PER_PLOT plots to it
#     axes = plt.subplot()
#     axes.set_xlabel('buffer time (ns)')
#     # Make the y-axis label and tick labels match the line color.
#     axes.set_ylabel('frame processing time (ms)')
#     axes.plot(results['buffer_ts'], results[element], '.', label=element)
#     axes.legend()

print "Showing plots..."
plt.show()

f.close()
