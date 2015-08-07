# element_processing_time.py

## What is it?

A Python script for parsing GStreamer 1.0 debug logs (written with hardcoded stuff for OpenWebRTC at some point in time) to print pretty graphs of how long each buffer is spending in each element in the pipeline.

## Dependencies

* numpy
* matplotlib
* networkx

## Usage

* Modify `element_processing_time.py` to hard code the names of the elements in the different threads in your pipeline (...yeah, this needs to be automated but it was tricky to make reliable for OpenWebRTC's complicated chains of elements going through rtpbin)
* Run your program and collect the appropriate debug logs: `GST_DEBUG=GST_ELEMENT_PADS:6,GST_PADS:6,GST_SCHEDULING:7 [your GStreamer program] > /path/to/debug.log 2>&1`
* Process the logs:
`python ./element_processing_time.py /path/to/debug.log`
* Look at the pretty graphs
  * the x axis is the buffer timestamp (s)
  * the y axis is the buffer processing time (ms)
  * each graph series then shows the amount of time each buffer is spending in a particular element as running time progresses
  * NOTE: buffers can spend time waiting in queues for the downstream thread to become idle
