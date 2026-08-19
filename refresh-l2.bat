@echo off
REM ============================================================
REM  Rafraichissement auto du recap mercato Ligue 2
REM  - scrape Transfermarkt -> regenere mercato-l2.html + equipe-l2.html
REM    directement dans le repo kooradex (unifie)
REM  - publie sur GitHub (-> Cloudflare Pages) uniquement si les DONNEES ont change
REM ============================================================
setlocal
set "PUSH=1"
set "SRC=C:\Users\Youss\Documents\animations youtube"

cd /d "%SRC%"
echo [%date% %time%] Scrape mercato L2...
python "scripts\scrape_l2_transfers.py"
if errorlevel 1 (
  echo ECHEC du scrape, publication annulee.
  exit /b 1
)

if not "%PUSH%"=="1" goto :done

set "CHANGED=0"
if exist "data\.push_l2" set /p CHANGED=<"data\.push_l2"
if not "%CHANGED%"=="1" (
  echo Donnees inchangees, pas de publication.
  goto :done
)

git add mercato-l2.html equipe-l2.html data\transfers_l2.json logos
git commit -m "MAJ mercato L2 (auto)"
git push
echo Publie sur kooradex.fr.

:done
endlocal
