; VideoCaptioner Windows installer (NSIS 3.x, Unicode)
;
; Build with installer/build_installer.py -- do not call makensis by hand unless
; you define every required !define below.
;
; Required defines: SOURCE_DIR
; Optional defines: APP_VERSION, APP_VERSION_NUM, OUT_FILE, ICON_FILE, LICENSE_FILE, COMPRESSOR

Unicode true

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

; ---------------------------------------------------------------- defines ---

!ifndef APP_VERSION
  !define APP_VERSION "0.0.0"
!endif
!ifndef APP_VERSION_NUM
  !define APP_VERSION_NUM "0.0.0.0"
!endif
!ifndef SOURCE_DIR
  !error "SOURCE_DIR is required (path to the PyInstaller dist/VideoCaptioner folder)"
!endif
!ifndef OUT_FILE
  !define OUT_FILE "VideoCaptioner-${APP_VERSION}-windows-x64-setup.exe"
!endif
!ifndef ICON_FILE
  !define ICON_FILE ""
!endif
!ifndef LICENSE_FILE
  !define LICENSE_FILE ""
!endif
!ifndef COMPRESSOR
  !define COMPRESSOR "lzma"
!endif

!define APP_NAME "VideoCaptioner"
!define APP_PUBLISHER "WEIFENG2333"
!define APP_URL "https://github.com/WEIFENG2333/VideoCaptioner"

; The console build serves the CLI; prefer the windowed launcher for GUI users.
!if /FileExists "${SOURCE_DIR}\VideoCaptioner-GUI.exe"
  !define APP_LAUNCH_EXE "VideoCaptioner-GUI.exe"
!else
  !define APP_LAUNCH_EXE "VideoCaptioner.exe"
!endif

!define REG_UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
!define REG_APP "Software\${APP_NAME}"

; -------------------------------------------------------------- installer ---

Name "${APP_NAME} ${APP_VERSION}"
OutFile "${OUT_FILE}"

; Per-user install: no UAC prompt, works on locked-down machines.
InstallDir "$LOCALAPPDATA\Programs\${APP_NAME}"
InstallDirRegKey HKCU "${REG_APP}" "InstallDir"
RequestExecutionLevel user

SetCompressor /FINAL ${COMPRESSOR}
SetCompressorDictSize 64
SetDatablockOptimize on

ShowInstDetails show
ShowUninstDetails show

VIProductVersion "${APP_VERSION_NUM}"
VIAddVersionKey /LANG=2052 "ProductName"     "${APP_NAME}"
VIAddVersionKey /LANG=2052 "ProductVersion"  "${APP_VERSION}"
VIAddVersionKey /LANG=2052 "CompanyName"     "${APP_PUBLISHER}"
VIAddVersionKey /LANG=2052 "FileDescription" "${APP_NAME} Setup"
VIAddVersionKey /LANG=2052 "FileVersion"     "${APP_VERSION_NUM}"
VIAddVersionKey /LANG=2052 "OriginalFilename" "${OUT_FILE}"
VIAddVersionKey /LANG=2052 "LegalCopyright"  "GNU GPL v3.0"
VIAddVersionKey /LANG=0409 "ProductName"     "${APP_NAME}"
VIAddVersionKey /LANG=0409 "ProductVersion"  "${APP_VERSION}"
VIAddVersionKey /LANG=0409 "CompanyName"     "${APP_PUBLISHER}"
VIAddVersionKey /LANG=0409 "FileDescription" "${APP_NAME} Setup"
VIAddVersionKey /LANG=0409 "FileVersion"     "${APP_VERSION_NUM}"
VIAddVersionKey /LANG=0409 "OriginalFilename" "${OUT_FILE}"
VIAddVersionKey /LANG=0409 "LegalCopyright"  "GNU GPL v3.0"

!if /FileExists "${ICON_FILE}"
  !define MUI_ICON   "${ICON_FILE}"
  !define MUI_UNICON "${ICON_FILE}"
!endif

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_LAUNCH_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "运行 ${APP_NAME}"
!define MUI_FINISHPAGE_NOREBOOTSUPPORT

!define MUI_WELCOMEPAGE_TITLE "欢迎安装 ${APP_NAME} ${APP_VERSION}"
!define MUI_WELCOMEPAGE_TEXT "即将在你电脑上安装 ${APP_NAME}。$\r$\n$\r$\n这是一个 AI 视频字幕工具，集成语音识别、字幕优化、翻译与合成，内置 FFmpeg，无需额外配置环境。$\r$\n$\r$\n点击“下一步”继续。"

!insertmacro MUI_PAGE_WELCOME
!if /FileExists "${LICENSE_FILE}"
  !insertmacro MUI_PAGE_LICENSE "${LICENSE_FILE}"
!endif
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!define MUI_UNCONFIRMPAGE_TEXT_TOP "将从本机移除 ${APP_NAME}。$\r$\n$\r$\n个人配置、日志与缓存保存在用户数据目录，不会被删除。"
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

; -------------------------------------------------------------- behaviour ---

Function .onInit
  SetShellVarContext current
FunctionEnd

Function un.onInit
  SetShellVarContext current
FunctionEnd

; ---------------------------------------------------------------- sections ---

Section "!${APP_NAME} 主程序" SecMain
  SectionIn RO

  ; Make sure the target directory is writable / not a stray file.
  ClearErrors
  CreateDirectory "$INSTDIR"
  IfErrors 0 +2
    Abort "无法创建安装目录：$INSTDIR"

  SetOutPath "$INSTDIR"
  SetOverwrite on
  DetailPrint "正在解压程序文件到 $INSTDIR ..."
  File /r "${SOURCE_DIR}\*"

  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; --- registry: app + add/remove programs entry ---------------------------
  WriteRegStr HKCU "${REG_APP}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${REG_APP}" "Version" "${APP_VERSION}"

  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0

  WriteRegStr HKCU "${REG_UNINST}" "DisplayName"     "${APP_NAME}"
  WriteRegStr HKCU "${REG_UNINST}" "DisplayVersion"  "${APP_VERSION}"
  WriteRegStr HKCU "${REG_UNINST}" "Publisher"       "${APP_PUBLISHER}"
  WriteRegStr HKCU "${REG_UNINST}" "URLInfoAbout"    "${APP_URL}"
  WriteRegStr HKCU "${REG_UNINST}" "HelpLink"        "${APP_URL}/issues"
  WriteRegStr HKCU "${REG_UNINST}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${REG_UNINST}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${REG_UNINST}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegStr HKCU "${REG_UNINST}" "DisplayIcon"     "$INSTDIR\${APP_LAUNCH_EXE}"
  WriteRegDWORD HKCU "${REG_UNINST}" "NoModify" 1
  WriteRegDWORD HKCU "${REG_UNINST}" "NoRepair" 1
  WriteRegDWORD HKCU "${REG_UNINST}" "EstimatedSize" "$0"
SectionEnd

Section "开始菜单快捷方式" SecStartMenu
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_LAUNCH_EXE}" "" "$INSTDIR\${APP_LAUNCH_EXE}" 0
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME} 命令行.lnk" "$INSTDIR\VideoCaptioner.exe" "" "$INSTDIR\VideoCaptioner.exe" 0
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk" "$INSTDIR\Uninstall.exe" "" "$INSTDIR\Uninstall.exe" 0
SectionEnd

Section "桌面快捷方式" SecDesktop
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_LAUNCH_EXE}" "" "$INSTDIR\${APP_LAUNCH_EXE}" 0
SectionEnd

; ------------------------------------------------------------------- uninst ---

Section "Uninstall"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME} 命令行.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"

  RMDir /r "$INSTDIR"

  DeleteRegKey HKCU "${REG_UNINST}"
  DeleteRegKey HKCU "${REG_APP}"
SectionEnd

; ------------------------------------------------------------- descriptions ---

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain}      "核心程序文件：VideoCaptioner 主程序、内置 FFmpeg、字体与字幕样式资源。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStartMenu} "在开始菜单中创建启动与卸载快捷方式。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop}   "在桌面创建启动快捷方式。"
!insertmacro MUI_FUNCTION_DESCRIPTION_END
