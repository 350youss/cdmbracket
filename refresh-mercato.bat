@echo off
REM ============================================================
REM  Rafraichissement auto du recap mercato Ligue 1
REM  - scrape Transfermarkt -> regenere mercato-l1-2026.html
REM  - publie sur GitHub Pages si PUSH=1
REM ============================================================
setlocal
set "PUSH=1"

cd /d "%~dp0"
echo [%date% %time%] Scrape mercato L1...
python "scripts\scrape_l1_transfers.py"
if errorlevel 1 (
  echo ECHEC du scrape, publication annulee.
  exit /b 1
)

if "%PUSH%"=="1" (
  git add mercato-l1-2026.html data\transfers_l1.json
  git diff --cached --quiet && (echo Aucun changement. ) || (
    git commit -m "MAJ mercato L1 (auto)"
    git push
    echo Publie sur GitHub Pages.
  )
)
endlocal
