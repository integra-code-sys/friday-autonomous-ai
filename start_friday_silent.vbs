Set WshShell = CreateObject("WScript.Shell")
strPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strPath
WshShell.Run chr(34) & strPath & "\Friday.bat" & Chr(34), 0
Set WshShell = Nothing
