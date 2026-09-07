Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
project = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = project
shell.Run "pyw -3.12 """ & project & "\main.py""", 0, False
