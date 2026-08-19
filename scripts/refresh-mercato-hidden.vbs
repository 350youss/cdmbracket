' Lance refresh-mercato.bat sans fenetre visible (pour la tache planifiee)
' Attend la fin du script (bWaitOnReturn=True) : un run bloque (reseau, etc.)
' reste visible comme "toujours en cours" au lieu de laisser un zombie silencieux
' et de fausser le resultat de la tache planifiee.
Set sh = CreateObject("WScript.Shell")
root = "C:\Users\Youss\Documents\animations youtube"
sh.CurrentDirectory = root
sh.Run "cmd /c """ & root & "\refresh-mercato.bat""", 0, True
