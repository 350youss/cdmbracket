@echo off
REM ============================================================
REM  Rafraichissement auto des effectifs "Grands Clubs" europeens
REM  - scrape Transfermarkt -> regenere grands-clubs.html + equipe-europe.html
REM    directement dans le repo kooradex (unifie)
REM  - publie sur GitHub (-> Cloudflare Pages) uniquement si les DONNEES ont change
REM ============================================================
setlocal
set "PUSH=1"
set "SRC=C:\Users\Youss\Documents\animations youtube"

cd /d "%SRC%"
echo [%date% %time%] Scrape grands clubs...
python "scripts\scrape_big_clubs.py"
if errorlevel 1 (
  echo ECHEC du scrape, publication annulee.
  exit /b 1
)

if not "%PUSH%"=="1" goto :done

set "CHANGED=0"
if exist "data\.push_europe" set /p CHANGED=<"data\.push_europe"
if not "%CHANGED%"=="1" (
  echo Donnees inchangees, pas de publication.
  goto :done
)

if exist ".git\index.lock" (
  echo Verrou git detecte ^(autre commit en cours^), attente 15s...
  timeout /t 15 /nobreak >nul
)
if exist ".git\index.lock" (
  echo Verrou git toujours present, nouvelle attente 15s...
  timeout /t 15 /nobreak >nul
)
if exist ".git\index.lock" (
  echo Verrou git toujours present, nouvelle attente 15s...
  timeout /t 15 /nobreak >nul
)

git add grands-clubs.html equipe-europe.html data\squads.json logos
git commit -m "MAJ grands clubs (auto)"
if errorlevel 1 echo ECHEC du commit, a verifier manuellement.
git pull --no-rebase --no-edit
git push
if errorlevel 1 (
  echo ECHEC de la publication ^(push rejete^), a verifier manuellement.
) else (
  echo Publie sur kooradex.fr.
)

:done
endlocal
