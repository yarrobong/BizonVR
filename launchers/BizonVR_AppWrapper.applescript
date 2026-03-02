on run argv
	if (count of argv) < 2 then
		display dialog "Usage: BizonVR_AppWrapper <script_path> <title>" buttons {"OK"} default button "OK" with icon stop
		return
	end if
	
	set targetScript to item 1 of argv
	set appTitle to item 2 of argv
	
	try
		do shell script "/bin/test -x " & quoted form of targetScript
	on error
		display dialog appTitle & return & return & "Файл не найден или не является исполняемым:" & return & targetScript buttons {"OK"} default button "OK" with icon stop
		return
	end try
	
	try
		do shell script "/usr/bin/open " & quoted form of targetScript
	on error errMsg number errNum
		display dialog appTitle & return & return & "Не удалось запустить:" & return & targetScript & return & return & "Ошибка " & errNum & ": " & errMsg buttons {"OK"} default button "OK" with icon stop
	end try
end run
