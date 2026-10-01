vim9script

# FIXME GST_DEBUG parsing
# FIXME escape codes

# Because user may not be comfortable with switching buffer views
# b:buffer_single = get(g:, gst_debug_buffer_single, true)
g:gst_debug_debug = get(g:, 'gst_debug_debug', v:true)
g:gst_debug_multiline_scan_len = 50

const s_level_map = {
      \ 'none': 0, 'ERROR': 1, 'WARN': 2, 'FIXME': 3,
      \ 'INFO': 4, 'DEBUG': 5, 'LOG': 6, 'TRACE': 7, 'MEMDUMP': 9,
      \ }

# Flat schema: Every physical token in the log is a primary column.
const s_schema = [
    {name: 'timestamp', parser: '\d\+:\d\+:\d\+\.\d\+', sep: '\s\+', },
    {name: 'pid',       parser: '\d\+',                 sep: '\s\+', },
    {name: 'thread',    parser: '0x\x\+',               sep: '\s\+', },
    {name: 'level',     parser: '[A-Z]\+',              sep: '\s\+', },
    {name: 'category',  parser: '\S\+',                 sep: '\s\+', },
    {name: 'file',      parser: '[^:]\+',               sep: ':',    },
    {name: 'lineno',    parser: '\d\+',                 sep: ':',    },
    {name: 'function',  parser: '[^:]\+',               sep: ':',    },
    {name: 'element',   parser: '\%(<[^>]\+>\)\=',      sep: '\s*',  },
    {name: 'message',   parser: '.*',                   sep: '',     }
]

# Derived schema: Expressions and combinations.
const s_derived_schema = {
    _source:       { parent: 'level',   expr: (ctx) => $"{ctx.file}:{ctx.lineno}:{ctx.function}"},
    _element_name: { parent: 'element', expr: (ctx) => substitute(ctx.element, '^<\([^@>]*\).*$', '\1', '')},
    _levelnum:     { parent: 'level',   expr: (ctx) => s_level_map[ctx.level] },
    _findexpr:     { parent: 'file',    expr: (ctx) => "^" .. ctx.timestamp .. '\s\+' .. ctx.pid .. '\s\+' .. ctx.thread}
}

# Derived fields are not physical tokens: they are anchored right after the
# physical field named in `anchor` and matched as a literal at that position.
# NOTE: keep these suffixes free of `\|` alternation, which VimRegexToPCRE
# does not translate to PCRE. Character classes are safe.
const s_derived_position = {
    _source:       { anchor: 'category', prefix: '',     suffix: ':' },
    _element_name: { anchor: 'function', prefix: '\s*<', suffix: '[@>]' },
}

# Yields a list of regexes to parse a line.
# Each regex captures 8 groups and packs the rest of the line in the 9th.
# This allows chained parsing to overcome Vim's 9 capture groups limitation.
def BuildRegexChain(): list<string>
    var regex_chain = []
    var current_regex = '^'
    var group_count = 0

    for field in s_schema
        # If we'd need a 9th capture group, capture the rest of the line
        # and initiate a new pattern
        if group_count == 8
            # Close the current pattern and append it to the output list
            current_regex ..= '\(.*\)'
            add(regex_chain, current_regex)

            # Initiate a new pattern
            current_regex = '^'
            group_count = 0
        endif

        current_regex ..= '\(' .. field.parser .. '\)' .. field.sep
        group_count += 1
    endfor

    # Add the ongoing pattern to the output list
    if current_regex != '^'
        add(regex_chain, current_regex)
    endif

    return regex_chain
enddef
const s_regex_chain: list<string> = BuildRegexChain()


###################################################
##  Parsing anf seeking
###################################################

export def ParseLine(a_lnum: number = -1): list<any>
    const target_lnum = a_lnum == -1 ? line('.') : a_lnum

    # Outcomes
    var fields: dict<any> = {}
    var locs: dict<any> = {}

    # Helpers
    const original_line = getline(target_lnum)
    var to_parse = original_line
    var field_idx = 0
    var offset = 0

    # Base schema extraction
    for regex in s_regex_chain
        var matches = matchlist(to_parse, regex)
        if empty(matches)
            return [fields, locs, target_lnum]
        endif

        var remaining_fields = min([8, len(s_schema) - field_idx])
        for i in range(remaining_fields)
            var field_name = s_schema[field_idx].name
            var val = matches[i + 1]

            # Store the field value
            fields[field_name] = val

            # And its location if not null
            if val != ''
                var match_idx = stridx(original_line, val, offset)
                if match_idx >= 0
                    locs[field_name] = {line: target_lnum, col: match_idx + 1}
                    offset = match_idx + len(val)
                endif
            endif
            field_idx += 1
        endfor

        if len(s_regex_chain) > 1 && field_idx < len(s_schema)
            to_parse = matches[9]
        endif
    endfor

    # Derived Extraction
    for [new_field, rule] in items(s_derived_schema)
        fields[new_field] = rule.expr(fields)
        if has_key(locs, rule.parent)
            locs[new_field] = copy(locs[rule.parent])
        endif
    endfor

    return [fields, locs, target_lnum]
enddef


export def ParseMultiLine(a_lnum: number = -1): list<any>
    const lnum_scan_start = a_lnum == -1 ? line('.') : a_lnum

    var fields: dict<any> = {}
    var locs: dict<any> = {}
    var line_log_start: number = -1

    # Upward scan: aims to find a schema-matching log line
    for line_offset in range(g:gst_debug_multiline_scan_len)
        var lnum = lnum_scan_start - line_offset
        if lnum <= 0
            break
        endif

        [fields, locs, line_log_start] = ParseLine(lnum)
        if !empty(fields) && !empty(locs)
            break
        endif
    endfor

    # Downward scan: if log line was found, append further lines to last field
    const eof_lnum = line('$')
    const last_field_name = s_schema[-1].name
    if !empty(fields)
        for line_offset in range(g:gst_debug_multiline_scan_len)
            var lnum = line_log_start + line_offset + 1

            if !empty(ParseLine(lnum)[0]) || lnum > eof_lnum
                break
            endif

            fields[last_field_name] ..= "\n" .. getline(lnum)
        endfor
    endif

    return [fields, locs, line_log_start]
enddef


export def SearchFieldValueBuildRegex(target_field: string, target_value: string, inverse: bool = false): string
    var regex = '^'
    const target_value_safe = escape(target_value, '.\*$^~[]')

    # Derived fields: consume the physical fields up to the anchor, then match
    # the derived value as a literal where it appears.
    if has_key(s_derived_position, target_field)
        const pos = s_derived_position[target_field]

        for field in s_schema
            regex ..= field.parser .. field.sep
            if field.name == pos.anchor
                break
            endif
        endfor

        if inverse
            return regex .. '\%(' .. pos.prefix .. target_value_safe .. pos.suffix .. '\)\@!'
        endif
        return regex .. pos.prefix .. target_value_safe .. pos.suffix
    endif

    var field_found = false

    for field in s_schema
        if field.name == target_field
            field_found = true

            if inverse
                regex ..= '\%(' .. target_value_safe .. '\)\@!' .. field.parser
            else
                regex ..= target_value_safe
            endif
            break
        else
            regex ..= field.parser .. field.sep
        endif
    endfor

    if !field_found
        echoerr "Unknown log field: " .. target_field
        return ""
    endif

    return regex
enddef


export def SearchFieldValue(fieldname: string, value: string, backwards: bool = false, inverse: bool = false): bool
    var regex = SearchFieldValueBuildRegex(fieldname, value, inverse)
    echom regex

    if empty(regex)
        return false
    endif

    var original_pos = getpos('.')
    var original_search = @/

    execute "normal! m`"

    # If searching backwards, jump to column 1 so we don't match the current line
    if backwards
        execute "normal! 0"
    endif

    var search_flags = backwards ? 'bW' : 'W'
    var found_lnum = search(regex, search_flags)
    @/ = original_search

    if found_lnum > 0
        CursorToField(fieldname)
        return true
    else
        setpos('.', original_pos)
        return false
    endif
enddef

###################################################
## Navigation - Horizontal
###################################################

def GetFieldUnderCursor(): list<string>
    const [fields, locs, lnum] = ParseMultiLine(line('.'))
    if empty(fields) | return ['', ''] | endif

    var fieldname = ''
    var fieldvalue = ''

    # Continuation line of a multiline block
    if line('.') > lnum
        fieldname = s_schema[-1].name
        fieldvalue = get(fields, fieldname, '')
    else
        for fieldschema in s_schema
            if has_key(locs, fieldschema.name) && locs[fieldschema.name].col <= col('.')
                fieldname = fieldschema.name
                fieldvalue = get(fields, fieldname, '')
            else
                break
            endif
        endfor
    endif

    return [fieldname, fieldvalue]
enddef


export def CursorToField(fieldname: string, do_visual_select: bool = false)
    var [fields, locs, lnum] = ParseMultiLine(line('.'))
    if empty(fields) || !has_key(locs, fieldname)
        return
    endif

    execute "normal! m`"
    cursor(locs[fieldname].line, locs[fieldname].col)
enddef


export def CursorToFieldVisual(fieldname: string)
    var [fields, locs, lnum] = ParseMultiLine(line('.'))
    if empty(fields) || !has_key(locs, fieldname)
        return
    endif
    execute "normal! m`"

    var end_line = -1
    var end_col  = -1

    var val_lines = split(fields[fieldname], '\n', true)
    if len(val_lines) > 1
        end_line = locs[fieldname].line + len(val_lines) - 1
        end_col  = max([1, len(val_lines[-1])])
    else
        end_line = locs[fieldname].line
        end_col  = locs[fieldname].col + len(fields[fieldname]) - 1
    endif

    cursor(locs[fieldname].line, locs[fieldname].col)
    execute "normal! \<Esc>v"
    cursor(end_line, end_col)
enddef


###################################################
## Navigation - Vertical
###################################################

export def SearchFieldUnderCursor(backwards: bool = false, inverse: bool = false)
    var [target_field, target_value] = GetFieldUnderCursor()

    if empty(target_field)
        echom "Could not identify field under cursor."
        return
    endif

    var search_value = split(target_value, '\n', true)[0]
    SearchFieldValue(target_field, search_value, backwards, inverse)
enddef


export def SearchFieldFromCurrentLine(target_field: string, backwards: bool = false, inverse: bool = false)
    const [fields, locs, line_log_start] = ParseMultiLine()
    if empty(fields)
        echom $"Could not identify field {target_field}"
        return
    endif

    var target_value = get(fields, target_field, '')
    var search_value = split(target_value, '\n', true)[0]
    SearchFieldValue(target_field, search_value, backwards, inverse)
enddef


export def SearchFieldCommand(target_field: string, target_value: string = "", backwards: bool = false, inverse: bool = false)
    if target_value == ""
        SearchFieldFromCurrentLine(target_field, backwards, inverse)
    else
        SearchFieldValue(target_field, target_value, backwards, inverse)
    endif
enddef


###################################################
##  Lists
###################################################

# FIXME clean up.
# jump_type is either "first" or "last" (not enforced)
def JumpToAppearance(jump_type: string)
    var line_text = getline('.')
    const target_field = b:target_field

    if line_text =~ '^[-|[:space:]]\+$' || line_text =~ 'Count'
        return
    endif

    var parts = split(line_text, '\s*|\s*')
    if len(parts) < 4
        return
    endif

    # Extract and trim the padding from the scratch buffer table
    var target_val = trim(jump_type == 'first' ? parts[2] : parts[3])
    var target_buf = get(b:, 'gst_log_bufnr', -1)

    if target_buf == -1 || !bufexists(target_buf)
        echom "Original log buffer not found or closed."
        return
    endif

    var winid = bufwinid(target_buf)
    if winid != -1
        win_gotoid(winid)
    else
        execute 'sbuffer ' .. target_buf
    endif

    cursor(1, 1)

    # \V enables "very nomagic", making all characters literal.
    # We include the ^ anchor to ensure we only match the start of the line.
    var search_pattern = '\V\^' .. escape(target_val, '\')

    if search(search_pattern, 'cw') > 0
        normal! zz
        CursorToField(target_field)
    else
        echom "Could not find appearance: " .. target_val
    endif
enddef

# FIXME have awk script files as assets. Try to regularize for regex single-source-of-truth
def ListField(target_field: string)
    const log_bufnr = bufnr('%')
    echom $"Scanning buffer for {target_field}s via awk..."

    const awk_script =<< trim CODE
        BEGIN {
            num_unique = 0
        }
        {
            # 1. Enforce strict log conformance.
            # Matches: timestamp + spaces + PID + spaces + thread (0xHEX)
            if (!match($0, /^[0-9]+:[0-9]+:[0-9]+\.[0-9]+[ \t]+[0-9]+[ \t]+0x[0-9a-fA-F]+/)) {
                next
            }

            # Capture the exact literal prefix string for Vim to jump to later
            jump_str = substr($0, RSTART, RLENGTH)

            # Strip ANSI escape codes
            gsub(/\x1B\\[[0-9;]*[a-zA-Z]/, "")

            val = ""
            if (target == "element") {
                if (match($6, /<[^>]+>/)) {
                    val = substr($6, RSTART + 1, RLENGTH - 2)
                }
            } else if (target == "level") {
                val = $4
            } else if (target == "category") {
                val = $5
            } else if (target == "source") {
                split($6, a, ":")
                val = a[1] ":" a[2] ":" a[3]
            }

            if (val != "") {
                if (!(val in count)) {
                    order[++num_unique] = val
                    first_jump[val] = jump_str
                }
                count[val]++
                last_jump[val] = jump_str
            }
        }
        END {
            if (num_unique == 0) {
                print "No matching log entries found."
                exit
            }

            # 1. Establish baseline widths using the text lengths of the headers
            max_v = length("Value")
            max_c = length("Count")
            max_f = length("First Appearance")
            max_l = length("Last Appearance")

            # 2. Iterate through values to calculate true maximum column widths
            for (i = 1; i <= num_unique; i++) {
                v = order[i]
                if (length(v) > max_v) max_v = length(v)
                if (length(count[v]) > max_c) max_c = length(count[v])
                if (length(first_jump[v]) > max_f) max_f = length(first_jump[v])
                if (length(last_jump[v]) > max_l) max_l = length(last_jump[v])
            }

            # 3. Dynamically construct format string templates based on computed widths
            # (Using '%%' outputs a literal '%' character into the final format template string)
            fmt_header = sprintf("%%-%ds | %%-%ds | %%-%ds | %%-%ds\n", max_v, max_c, max_f, max_l)
            fmt_row    = sprintf("%%-%ds | %%-%dd | %%-%ds | %%-%ds\n", max_v, max_c, max_f, max_l)

            # 4. Generate a completely responsive divider line matching the widths
            sep_v = ""; for (j = 1; j <= max_v; j++) sep_v = sep_v "-"
            sep_c = ""; for (j = 1; j <= max_c; j++) sep_c = sep_c "-"
            sep_f = ""; for (j = 1; j <= max_f; j++) sep_f = sep_f "-"
            sep_l = ""; for (j = 1; j <= max_l; j++) sep_l = sep_l "-"
            sep_line = sep_v "-+-" sep_c "-+-" sep_f "-+-" sep_l

            # 5. Output the calculated table structures
            printf fmt_header, "Value", "Count", "First Appearance", "Last Appearance"
            print sep_line

            for (i = 1; i <= num_unique; i++) {
                v = order[i]
                printf fmt_row, v, count[v], first_jump[v], last_jump[v]
            }
        }
    CODE

    const temp_awk = tempname()
    writefile(awk_script, temp_awk)

    var output: list<string>
    const clean_target = tolower(target_field)

    if !&modified && !empty(expand('%'))
        const cmd = 'awk -v target=' .. shellescape(clean_target) .. ' -f ' .. shellescape(temp_awk) .. ' ' .. shellescape(expand('%'))
        output = systemlist(cmd)
    else
        const cmd = 'awk -v target=' .. shellescape(clean_target) .. ' -f ' .. shellescape(temp_awk)
        output = systemlist(cmd, getline(1, '$'))
    endif

    delete(temp_awk)

    if v:shell_error != 0
        echoerr "Failed to parse logs using awk."
        return
    endif

    execute 'new'
    setlocal buftype=nofile bufhidden=wipe nobuflisted noswapfile
    setlocal cursorline

    var title = toupper(clean_target[0]) .. clean_target[1 : ] .. 's'
    execute 'silent! file [GStreamer ' .. title .. ']'

    setline(1, output)

    b:gst_log_bufnr = log_bufnr
    b:target_field = target_field


    syntax match TableDimmed /\.\d\+\s\+\d\+\s\+0x\x\+/
    syntax match TableStructure /[\|]/
    syntax match TableDivider /^-\++\+.\+$/
    hi def link TableDimmed NonText
    hi def link TableStructure Special
    hi def link TableDivider Comment

    nnoremap <buffer> <silent> g1 <ScriptCmd>JumpToAppearance("first")<CR>
    nnoremap <buffer> <silent> g2 <ScriptCmd>JumpToAppearance("last")<CR>

    setlocal nomodifiable
enddef


command! ListElements   ListField('element')
command! ListLevels     ListField('level')
command! ListCategories ListField('category')
command! ListSources    ListField('source')

###################################################
##  Filters
###################################################

def FilterLevelLower()
    # Similar to modifying GST_DEBUG= but after log is printed
enddef
def FilterBuffer()
    # Opens a buffer with all unique ids for relevant fields, lets you delete to filter out
enddef
def FilterText()
    # Arbitary grep from input
enddef
def FilterVisual()
    # Arbitrary grep from visual selection
enddef

def VimRegexToPCRE(vim_regex: string): string
    var pcre = vim_regex
    pcre = substitute(pcre, '\\%(\(.\{-}\)\\)\\@!', '(?!\1)', 'g') # Negative Lookahead: \%(X\)\@! -> (?!X)
    pcre = substitute(pcre, '\\%(', '(?:', 'g')                    # Non-capturing groups: \%(X\) -> (?:X)
    pcre = substitute(pcre, '\\)', ')', 'g')                       # Escaped parenthesis: \) -> )
    pcre = substitute(pcre, '\\x', '[0-9a-fA-F]', 'g')             # Hexadecimal character class: \x -> [0-9a-fA-F]
    pcre = substitute(pcre, '\\+', '+', 'g')                       # One or more: \+ -> +
    pcre = substitute(pcre, '\\=', '?', 'g')                       # Zero or one: \= -> ?
    return pcre
enddef

export def FilterField(fieldname: string, inverse: bool = false)
    const cur_pos = getcurpos()
    const fields = ParseMultiLine(cur_pos[1])[0]
    const value = get(fields, fieldname, '')

    if value == ''
        echom "Cannot parse " .. fieldname .. " field from current line. Must be in schema."
        return
    endif

    const vim_regex = SearchFieldValueBuildRegex(fieldname, value, inverse)
    const pcre_regex = VimRegexToPCRE(vim_regex)
    execute $":%!rg -P '{pcre_regex}'"

    # Attempt to restore cursor safely
    cursor(1, 1)
    if !search(fields._findexpr, 'cw')
        echom "Filter applied. Original line was filtered out."
    else
        cursor(0, cur_pos[2])
    endif
enddef

def FilterReset()
enddef

###################################################
##  Filetype
###################################################

export def FTypeDetectGstreamerlogs()
    # If the filetype is already set to something, bail out
    if &filetype != '' | return | endif

    # Count how many lines start with the GStreamer timestamp format
    # If 5 or more lines match, assign the filetype
    var lines = getline(1, 20)
    var match_count = 0
    for line in lines
        if line =~# '^\d\+:\d\+:\d\+\.\d\+'
            match_count += 1
        endif
    endfor

    if match_count >= 5
        setlocal filetype=gstreamerlogs
    endif
enddef
