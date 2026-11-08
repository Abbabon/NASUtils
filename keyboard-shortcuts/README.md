# Keyboard Shortcuts

Custom macOS keyboard shortcuts, implemented with [Hammerspoon](https://www.hammerspoon.org/). All shortcuts live in `shortcuts.lua`.

## Shortcuts

| Hotkey | Action |
| --- | --- |
| `ctrl+alt+cmd+Right` | Move the focused window to the next desktop (Space) and follow it. Does nothing on the last desktop or for full-screen windows. |
| `ctrl+alt+cmd+Left` | Same, to the previous desktop. Does nothing on the first desktop. |

## Install

1. Install Hammerspoon and grant it Accessibility permission (System Settings -> Privacy & Security -> Accessibility).
2. Add one line to `~/.hammerspoon/init.lua`, using the path to your clone:
   ```lua
   dofile("/path/to/NASUtils/keyboard-shortcuts/shortcuts.lua")
   ```
3. Reload the Hammerspoon config.

## Prerequisites

- System Settings -> Keyboard -> Keyboard Shortcuts -> Mission Control: enable **Move left a space** (`ctrl+Left`) and **Move right a space** (`ctrl+Right`). The script triggers these system shortcuts.
- You need at least two desktops.

## How it works

`hs.spaces.moveWindowToSpace` returns true but silently does nothing since macOS 14.5. Instead the script moves the cursor to the window's title bar, presses and drags a few pixels (a bare press doesn't pick the window up), sends `ctrl+Left`/`ctrl+Right`, releases, and restores the cursor. The `ctrl+Left`/`ctrl+Right` event must carry the `fn` flag (arrow keys do on a real keyboard) or the system ignores it. The cursor visibly jumps for about a second. Windows without a normal title bar at the top may not move. At either end (first desktop going left, last going right) the hotkey does nothing.

## Adding a shortcut

Add a function and an `hs.hotkey.bind` call to `shortcuts.lua`, and a row to the table above.
