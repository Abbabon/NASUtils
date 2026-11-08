-- Custom macOS keyboard shortcuts for Hammerspoon.
-- Load from ~/.hammerspoon/init.lua:  dofile("/path/to/NASUtils/keyboard-shortcuts/shortcuts.lua")

local mods = { "ctrl", "alt", "cmd" }

-- Move focused window one Space in `dir` (1 = right, -1 = left) and follow it.
-- hs.spaces.moveWindowToSpace is broken since macOS 14.5, so: hold the title bar,
-- fire the system "Move left/right a space" shortcut (ctrl+Left/Right), release, restore cursor.
local function moveWindowBySpace(dir)
  local win = hs.window.focusedWindow()
  if not win or win:isFullScreen() then return end

  local spaces = hs.spaces.spacesForScreen(win:screen())
  local cur = hs.spaces.windowSpaces(win)
  if not spaces or not cur or not cur[1] then return end
  local idx
  for i, id in ipairs(spaces) do if id == cur[1] then idx = i end end
  local nxt = idx and idx + dir
  if not nxt or nxt < 1 or nxt > #spaces then return end -- first/last desktop: do nothing

  local f = win:frame()
  local grab = { x = f.x + f.w / 2, y = f.y + 12 } -- title bar, 12px below top edge
  local saved = hs.mouse.absolutePosition()
  local ev = hs.eventtap.event
  hs.mouse.absolutePosition(grab) -- the press must happen under the real cursor
  hs.timer.usleep(100000)
  -- empty modifiers: the hotkey's ctrl+alt+cmd may still be physically held
  ev.newMouseEvent(ev.types.leftMouseDown, grab, {}):post()
  hs.timer.usleep(100000)
  -- a plain press doesn't pick the window up; the real cursor has to move while held
  for i = 1, 5 do
    local p = { x = grab.x + i * 4, y = grab.y }
    hs.mouse.absolutePosition(p)
    ev.newMouseEvent(ev.types.leftMouseDragged, p, {}):post()
    hs.timer.usleep(30000)
  end
  -- arrow keys need the fn flag or the system ignores the synthetic ctrl+arrow
  for _, down in ipairs({ true, false }) do
    local k = ev.newKeyEvent(dir > 0 and "right" or "left", down)
    k:setFlags({ ctrl = true, fn = true })
    k:post()
  end
  hs.timer.doAfter(0.6, function() -- let the space switch animation finish
    ev.newMouseEvent(ev.types.leftMouseUp, grab, {}):post()
    hs.mouse.absolutePosition(saved)
  end)
end

hs.hotkey.bind(mods, "right", function() moveWindowBySpace(1) end)
hs.hotkey.bind(mods, "left", function() moveWindowBySpace(-1) end)
