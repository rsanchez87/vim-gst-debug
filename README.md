# vim-gst-debug

**Work in progress**

GStreamer log parsing, navigation, listing, and filtering utilities for Vim.

This plugin parses the standard GStreamer debug log line into fields, and installs a few convenience buffer-local mappings to easily navigate them along syntax highlighting.

To handle large files, this plugin will be built on [pabsan-0/vim-paginate](https://github.com/pabsan-0/vim-paginate)


## Requirements

- **Vim 9 or newer**, with `+eval`, `+syntax`, `+folding` and `+vim9script`.
    - **Not Neovim.** This plugin is written in `vim9script`, which Neovim does not support.
    - **Not `vim.tiny`.** It lacks `+eval` and `+syntax`, so the plugin does nothing.
      On Debian/Ubuntu install `vim`, `vim-nox` or `vim-gtk3`.
- [`rg`](https://github.com/BurntSushi/ripgrep) on your `$PATH` — used by every `:Filter*` command.
- GNU `awk` (`gawk`) on your `$PATH` — used by every `:List*` command (it relies on `\x1B` escapes).

Check inside Vim:

```vim
:echo has('eval') has('syntax') has('folding') has('vim9script')
:echo executable('rg') executable('awk')
```

## Getting a log

The plugin only reads plain text, so make GStreamer write plain text to a file:

```sh
GST_DEBUG=5 GST_DEBUG_NO_COLOR=1 GST_DEBUG_FILE=/tmp/pipeline.log gst-launch-1.0 ...
```

| Variable | Meaning |
|---|---|
| `GST_DEBUG` | Which messages to log. See the level table below. |
| `GST_DEBUG_FILE` | Write to this file instead of stderr. |
| `GST_DEBUG_NO_COLOR` | Set to `1` to disable ANSI colors (**recommended**). |
| `GST_DEBUG_COLOR_MODE` | `on`, `auto`, `off` or `disable` — alternative to the above. |

`GST_DEBUG` accepts a numeric level, or `category:level` to raise a single category:

| Number | Level |
|---|---|
| 0 | none |
| 1 | ERROR |
| 2 | WARN |
| 3 | FIXME |
| 4 | INFO |
| 5 | DEBUG |
| 6 | LOG |
| 7 | TRACE |
| 9 | MEMDUMP |

> Keep colors off. The parser does not understand ANSI escape codes
> (there is a `# FIXME escape codes` note in `autoload/gst_debug.vim`), so
> colored output can fail to parse.

## Install

Any plugin manager works, for example [vim-plug](https://github.com/junegunn/vim-plug):

```vim
Plug 'pabsan-0/vim-gst-debug'
```

Or use Vim's built-in package system (no plugin manager needed):

```sh
git clone https://github.com/pabsan-0/vim-gst-debug \
  ~/.vim/pack/gst-debug/start/vim-gst-debug
```

## Usage

Open a log. The `gstreamerlogs` filetype is detected when **all** of these hold:

- The file name ends in `.log`.
- At least 5 of the first 20 lines start with a GStreamer timestamp.
- No other filetype was claimed first.

Anything else stays undetected, so force it manually with `:GstLog`.

A parsed line looks like this:

```
0:00:00.000057928   203 0x613b6ef141e0 ERROR           GST_REGISTRY gstregistry.c:1605:priv_gst_get_relocated_libgstreamer: attempting to retrieve libgstreamer-1.0
```

### Quick start

1. Write a log to a file (see [Getting a log](#getting-a-log)).
2. Open it and confirm the filetype with `:set ft?`.
3. Put the cursor on any log line and press `g5` to jump to the category.
4. Press `<C-n>` to jump to the next line with the *same* category.
5. Run `:FilterCategory` to keep only that category, or `:ListElements` to list the elements.

If `:set ft?` does not say `gstreamerlogs`, none of the mappings or commands below
exist yet — run `:GstLog` first.

## Features

### Horizontal movement

`g1`-`g0` move the cursor to a specific field of the current line; the same keys
in Visual mode select that field.

| Key | Field | Meaning |
|---|---|---|
| `g1` | `timestamp` | time since the pipeline started |
| `g2` | `pid` | process id |
| `g3` | `thread` | thread id (`0x...`) |
| `g4` | `level` | severity, `ERROR` … `MEMDUMP` |
| `g5` | `category` | GStreamer debug category, e.g. `GST_REGISTRY` |
| `g6` | `file` | source file |
| `g7` | `lineno` | source line number |
| `g8` | `function` | source function name |
| `g9` | `element` | element name inside `<...>` |
| `g0` | `message` | the rest of the line |


### Vertical movement

While on a field, jump to the next line where that field is the same, or different:

| Map | Action |
|---|---|
| `<C-n>` | next line with the same field under the cursor |
| `<C-p>` | previous line with the same field under the cursor |
| `g<C-n>` | next line where the field under the cursor differs |
| `g<C-p>` | previous line where the field under the cursor differs |

The same is available as commands, for the fields `pid`, `thread`, `level`,
`category`, `file`, `lineno`, `function` and `element`:

```vim
:Next{Field}Same   :Prev{Field}Same
:Next{Field}Diff   :Prev{Field}Diff
```

For example `:NextCategorySame` or `:PrevPidDiff`. Give a value to look for a
specific one instead of the one under the cursor: `:NextCategorySame GST_REGISTRY`.

Every level also has its own pair of commands:

```vim
:NextLevelError   :PrevLevelError
:NextLevelWarn    :PrevLevelWarn
:NextLevelFixme   :PrevLevelFixme
:NextLevelInfo    :PrevLevelInfo
:NextLevelDebug   :PrevLevelDebug
:NextLevelLog     :PrevLevelLog
:NextLevelTrace   :PrevLevelTrace
:NextLevelMemdump :PrevLevelMemdump
```


### Filtering

Filter the buffer down to entries matching a field on the current line, using
`rg` under the hood for speed.

```vim
:FilterPID :FilterThread :FilterLevel :FilterCategory :FilterElement
:FilterSource :FilterElementName
```

`:FilterSource` matches the `file:lineno:function` triple, and
`:FilterElementName` matches just the element name inside `<...>`.

> **This rewrites the buffer in place.** `u` undoes it, but the log buffer is
> opened with `noundofile`, so **do not `:w` a filtered log** — you would lose the
> original. `:FilterReset` reloads the unfiltered file from disk.

### Listing

**experimental**

Open a scratch buffer tabulating all unique values for a field, with count, first, and last line where it appears (built via `awk`):

| Command          | Field                           |
|------------------|---------------------------------|
| `:ListElements`  | element names (`<...>`)         |
| `:ListLevels`    | levels                          |
| `:ListCategories`| categories                      |
| `:ListSources`   | `file:lineno:function` triplets |

In this buffer:
- `g1` jump to the first appearance of the value under the cursor in the original logs
- `g2` jump to the last appearance of the value under the cursor in the original logs

## Behavior on log buffers

To keep Vim responsive on huge files, `gstreamerlogs` buffers change a few settings:

- Copilot is disabled (`b:copilot_enabled = 0`).
- `:w` is rewritten to `:noautocmd w`.
- No swap file and no undo file — no crash recovery, no undo across sessions.
- Manual folding, `wrap` with `breakindent`, and `redrawtime` capped at 250ms
  (so highlighting may look incomplete while scrolling).

## Troubleshooting

| Symptom | Cause |
|---|---|
| No syntax highlighting, nothing happens | The filetype was not set. Run `:set ft?`, then `:GstLog`. |
| No mappings or commands at all | Same as above — they are defined by the `gstreamerlogs` filetype. |
| `:Filter*` fails | `rg` is missing from your `$PATH`. |
| `:List*` reports a parse failure | `awk` is missing, or it is not GNU `awk`. |
| `:echo exists('g:loaded_gst_debug')` prints `0` | The plugin did not load — see [Requirements](#requirements). |

Debug helpers are available (enabled by default through `g:gst_debug_debug`):

```vim
:DebugParseLine           " parsed fields and locations of the current line
:DebugParseMultiLine      " same, accounting for multi-line messages
:DebugSeekFieldBuildRegex " the search regex built for a field
```

## Not implemented yet

`FilterText()`, `FilterVisual()`, `FilterBuffer()` and `FilterLevelLower()` exist
as empty stubs with no commands wired up yet.
