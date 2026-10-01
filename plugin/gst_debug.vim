vim9script

if exists('g:loaded_gst_debug')
    finish
endif
g:loaded_gst_debug = 1

# TODO
# g:gst_debug__indent_on_load = 1
# g:gst_debug__large_file_threshold = 1

# Parse environment here
# TODO VIM_GST_DEBUG_SRC

# Enable the :Debug* commands in gstreamerlogs buffers
g:gst_debug_debug = get(g:, 'gst_debug_debug', v:true)


# NOTE: a vim9script `def` function cannot be invoked with `:call` from a
# command, so set the filetype inline instead of calling a helper.
command! GstLog setlocal filetype=gstreamerlogs
