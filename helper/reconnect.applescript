property targetName : ""
property hideSettingsAfterAttempt : false

on reportResult(resultText)
    if hideSettingsAfterAttempt and resultText is not "starting" then
        try
            tell application "System Events"
                tell process "System Settings"
                    if not frontmost then set visible to false
                    delay 0.25
                end tell
            end tell
        end try
    end if
    set resultPath to (POSIX path of (path to home folder)) & "Library/Application Support/UCReconnect/logs/reconnect-result"
    do shell script "/usr/bin/printf '%s\\n' " & quoted form of resultText & " > " & quoted form of resultPath
end reportResult

on run
    set hideSettingsAfterAttempt to false
    try
        set targetPath to (POSIX path of (path to home folder)) & "Library/Application Support/UCReconnect/target-name.txt"
        set targetName to read POSIX file targetPath as «class utf8»
        my reportResult("starting")
        with timeout of 12 seconds
            set needsOpen to true
            set needsReveal to true
            tell application "System Events"
                if exists process "System Settings" then
                    if frontmost of process "System Settings" then
                        my reportResult("settings-in-use")
                        return
                    end if
                    tell process "System Settings"
                        if exists window 1 then
                            set needsOpen to false
                            set paneTitle to name of window 1
                            set needsReveal to paneTitle is not "显示器" and paneTitle is not "Displays"
                        end if
                    end tell
                end if
            end tell
            set hideSettingsAfterAttempt to true
            if needsOpen then do shell script "/usr/bin/open -g -a 'System Settings'"
            tell application "System Events" to set visible of process "System Settings" to true
            if needsReveal then
                tell application "System Settings" to reveal pane id "com.apple.Displays-Settings.extension"
            end if
            tell application "System Events"
                tell process "System Settings"
                    set plusControl to missing value
                    set deadline to (current date) + 6
                    repeat while (current date) <= deadline
                        if exists window 1 then
                            try
                                set allControls to entire contents of group 3 of splitter group 1 of group 1 of window 1
                            on error
                                set allControls to {}
                            end try
                            repeat with itemRef in allControls
                                if (current date) > deadline then exit repeat
                                with timeout of 2 seconds
                                    try
                                        if role of itemRef is "AXMenuButton" then
                                            set itemID to ""
                                            try
                                                set itemID to value of attribute "AXIdentifier" of itemRef
                                            end try
                                            if itemID is "plus" then
                                                set plusControl to itemRef
                                                exit repeat
                                            end if
                                            try
                                                if description of itemRef contains "显示器设置" then
                                                    set plusControl to itemRef
                                                    exit repeat
                                                end if
                                            end try
                                        end if
                                    end try
                                end timeout
                            end repeat
                            if plusControl is not missing value then exit repeat
                        end if
                        if (current date) > deadline then exit repeat
                        delay 0.25
                    end repeat
                    if plusControl is missing value then
                        my reportResult("add-menu-not-found")
                        return
                    end if
                    click plusControl
                    set deviceMenu to missing value
                    repeat 12 times
                        if exists menu 1 of plusControl then
                            set deviceMenu to menu 1 of plusControl
                            exit repeat
                        end if
                        delay 0.15
                    end repeat
                    if deviceMenu is missing value then
                        my reportResult("device-menu-not-found")
                        return
                    end if
                    set inKeyboardSection to false
                    set targetItem to missing value
                    repeat with menuEntry in menu items of deviceMenu
                        set entryName to name of menuEntry
                        if entryName is "连接键盘和鼠标至" or entryName is "Link Keyboard and Mouse to" then
                            set inKeyboardSection to true
                        else if entryName is "镜像或扩展至" or entryName is "Mirror or Extend to" then
                            set inKeyboardSection to false
                        else if inKeyboardSection and entryName is my targetName then
                            set targetItem to menuEntry
                            exit repeat
                        end if
                    end repeat
                    if targetItem is missing value then
                        perform action "AXCancel" of deviceMenu
                        my reportResult("target-not-available")
                        return
                    end if
                    -- A checked menu item would disconnect the working session.
                    try
                        set itemMark to value of attribute "AXMenuItemMarkChar" of targetItem
                        if itemMark is not missing value and itemMark is not "" then
                            perform action "AXCancel" of deviceMenu
                            my reportResult("already-selected")
                            return
                        end if
                    on error
                        perform action "AXCancel" of deviceMenu
                        my reportResult("selection-state-unknown")
                        return
                    end try
                    click targetItem
                    my reportResult("connection-requested")
                end tell
            end tell
        end timeout
    on error errorText number errorNumber
        my reportResult("error:" & errorNumber)
    end try
end run
