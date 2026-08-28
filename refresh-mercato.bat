@echo off
REM ============================================================
REM  Rafraichissement auto du recap mercato Ligue 1
REM  - scrape Transfermarkt -> regenere mercato-l1.html + equipe.html
REM  - recalcule le squad cost ratio OM -> regenere squad-cost.html
REM    directement dans le repo kooradex (unifie)
REM  - publie sur GitHub (-> Cloudflare Pages) uniquement si les DONNEES ont change
REM ============================================================
setlocal
set "PUSH=1"
set "SRC=C:\Users\Youss\Documents\animations youtube"

cd /d "%SRC%"
echo [%date% %time%] Scrape mercato L1...
python "scripts\scrape_l1_transfers.py"
if errorlevel 1 (
  echo ECHEC du scrape, publication annulee.
  exit /b 1
)

echo [%date% %time%] Recalcul squad cost ratio OM...
python "scripts\scrape_squad_cost.py"
if errorlevel 1 (
  echo ECHEC du calcul squad cost, on continue quand meme (page precedente conservee).
)

if not "%PUSH%"=="1" goto :done

set "CHANGED=0"
if exist "data\.push" set /p CHANGED=<"data\.push"
set "CHANGED_SC=0"
if exist "data\.push_squadcost" set /p CHANGED_SC=<"data\.push_squadcost"
if "%CHANGED_SC%"=="1" set "CHANGED=1"

if not "%CHANGED%"=="1" (
  echo Donnees inchangees, pas de publication.
  goto :done
)

git add mercato-l1.html equipe.html squad-cost.html data\transfers_l1.json data\squad_cost.json logos
git commit -m "MAJ mercato L1 (auto)"
git pull --no-rebase --no-edit
git push
if errorlevel 1 (
  echo ECHEC de la publication ^(push rejete^), a verifier manuellement.
) else (
  echo Publie sur kooradex.fr.
)

:done
endlocal
