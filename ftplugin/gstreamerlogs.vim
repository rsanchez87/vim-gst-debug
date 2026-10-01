vim9script

# Line wrapping
setlocal wrap
setlocal breakindent
setlocal breakindentopt=shift:4

setlocal noswapfile
setlocal noundofile
setlocal foldmethod=manual
setlocal nofoldenable
if &redrawtime > 250
    &redrawtime = 250
endif

if get(g:, "gst_debug_debug", v:false) == v:true
    command! DebugParseLine           echom gst_debug#ParseLine(-1)
    command! DebugParseMultiLine      echom gst_debug#ParseMultiLine(-1)
    command! DebugSeekFieldBuildRegex echom gst_debug#SearchFieldValueBuildRegex("category", "GST_INIT", 0)
endif

nnoremap <buffer> g1 <Cmd>call gst_debug#CursorToField('timestamp')<CR>
nnoremap <buffer> g2 <Cmd>call gst_debug#CursorToField('pid')<CR>
nnoremap <buffer> g3 <Cmd>call gst_debug#CursorToField('thread')<CR>
nnoremap <buffer> g4 <Cmd>call gst_debug#CursorToField('level')<CR>
nnoremap <buffer> g5 <Cmd>call gst_debug#CursorToField('category')<CR>
nnoremap <buffer> g6 <Cmd>call gst_debug#CursorToField('file')<CR>
nnoremap <buffer> g7 <Cmd>call gst_debug#CursorToField('lineno')<CR>
nnoremap <buffer> g8 <Cmd>call gst_debug#CursorToField('function')<CR>
nnoremap <buffer> g9 <Cmd>call gst_debug#CursorToField('element')<CR>
nnoremap <buffer> g0 <Cmd>call gst_debug#CursorToField('message')<CR>

xnoremap <buffer> g1 <Cmd>call gst_debug#CursorToFieldVisual('timestamp')<CR>
xnoremap <buffer> g2 <Cmd>call gst_debug#CursorToFieldVisual('pid')<CR>
xnoremap <buffer> g3 <Cmd>call gst_debug#CursorToFieldVisual('thread')<CR>
xnoremap <buffer> g4 <Cmd>call gst_debug#CursorToFieldVisual('level')<CR>
xnoremap <buffer> g5 <Cmd>call gst_debug#CursorToFieldVisual('category')<CR>
xnoremap <buffer> g6 <Cmd>call gst_debug#CursorToFieldVisual('file')<CR>
xnoremap <buffer> g7 <Cmd>call gst_debug#CursorToFieldVisual('lineno')<CR>
xnoremap <buffer> g8 <Cmd>call gst_debug#CursorToFieldVisual('function')<CR>
xnoremap <buffer> g9 <Cmd>call gst_debug#CursorToFieldVisual('element')<CR>
xnoremap <buffer> g0 <Cmd>call gst_debug#CursorToFieldVisual('message')<CR>

nnoremap <buffer> <C-n>  <Cmd>call gst_debug#SearchFieldUnderCursor(0, 0)<CR>
nnoremap <buffer> <C-p>  <Cmd>call gst_debug#SearchFieldUnderCursor(1, 0) <CR>
nnoremap <buffer> g<C-n> <Cmd>call gst_debug#SearchFieldUnderCursor(0, 1)<CR>
nnoremap <buffer> g<C-p> <Cmd>call gst_debug#SearchFieldUnderCursor(1, 1)<CR>


for level in ['error', 'warn', 'fixme', 'info', 'debug', 'log', 'trace', 'memdump']
    var cmd_name = toupper(level[0]) .. tolower(level[1 : ])

    execute $'command! -buffer NextLevel{cmd_name} gst_debug#SearchFieldValue("level", "{toupper(level)}", 0, 0)'
    execute $'command! -buffer PrevLevel{cmd_name} gst_debug#SearchFieldValue("level", "{toupper(level)}", 1, 0)'
endfor


for field in ['pid', 'thread', 'level', 'category', 'file', 'lineno', 'function', 'element']
    var cmd_name = toupper(field[0]) .. tolower(field[1 : ])

    execute $'command! -buffer -nargs=? Next{cmd_name}Same gst_debug#SearchFieldCommand("{field}", <q-args>, 0, 0)'
    execute $'command! -buffer -nargs=? Prev{cmd_name}Same gst_debug#SearchFieldCommand("{field}", <q-args>, 1, 0)'
    execute $'command! -buffer -nargs=? Next{cmd_name}Diff gst_debug#SearchFieldCommand("{field}", <q-args>, 0, 1)'
    execute $'command! -buffer -nargs=? Prev{cmd_name}Diff gst_debug#SearchFieldCommand("{field}", <q-args>, 1, 1)'
endfor

# Basic field filtering
# FIXME default to current line's, but allow argument
command! -buffer FilterPID         gst_debug#FilterField("pid")
command! -buffer FilterThread      gst_debug#FilterField("thread")
command! -buffer FilterLevel       gst_debug#FilterField("level")
command! -buffer FilterCategory    gst_debug#FilterField("category")
command! -buffer FilterSource      gst_debug#FilterField("_source")
command! -buffer FilterElement     gst_debug#FilterField("element")
command! -buffer FilterElementName gst_debug#FilterField("_element_name")
command! -buffer FilterReset       gst_debug#FilterReset()


# Faster saving for large files: :w is now :noautocmd w
cnoreabbrev <expr> <buffer> w (getcmdtype() == ':' && getcmdline() == 'w') ? 'noautocmd w' : 'w'

# User UX
# nnoremap ]l
# nnoremap [l
# nnoremap <leader>ll  # level lower than
# nnoremap <leader>lh  # level higher than
# nnoremap <leader>le  # level equal to
# nnoremap <C-n>
# nnoremap <C-p>


# Disable copilot on the current buffer
# Proven to slow writing a LOT
b:copilot_enabled = 0
