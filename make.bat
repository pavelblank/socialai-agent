@echo off
rem Quick content maker.  Examples:
rem   make.bat video "why the ocean calms the mind"
rem   make.bat image "3 signs you are healing"
rem   make.bat text  "a 2-minute breathing reset"
cd /d "%~dp0"
if "%~1"=="video" ( python scripts\make_video.py %2 --scenes 4 & goto :eof )
if "%~1"=="image" ( python scripts\make_post.py image %2 & goto :eof )
if "%~1"=="text"  ( python scripts\make_post.py text %2 & goto :eof )
echo usage: make.bat video^|image^|text "topic"
