; Installer for the native-ARM64 Deluge bundle produced by deploy.sh.
;
; Deluge ships no Windows packaging of its own (packaging/ holds only systemd
; units), so unlike the qBittorrent build there is no upstream .nsi to reuse.
; This installs the portable tree as-is and adds shortcuts, associations and an
; uninstaller. makensis itself emits an x86 installer - that is fine, it runs
; under emulation on ARM64 and the payload it lays down is native aarch64.

Unicode true
SetCompressor /SOLID lzma

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"

!define APPNAME      "Deluge"
!define APPVERSION   "2.2.0"
; Not "Deluge Team" alone: they wrote Deluge but did not publish this build.
!define PUBLISHER    "Unofficial ARM64 build (Deluge by the Deluge Team)"
!define WEBSITE      "https://deluge-torrent.org"
!define UNINSTKEY    "Software\Microsoft\Windows\CurrentVersion\Uninstall\Deluge"

; The bundle to package and where the setup goes. By default both are in dist/,
; where deploy.sh puts the bundle (paths are relative to this script). Override
; with: makensis /DSOURCEDIR=<bundle> /DOUTFILE=<setup.exe> deluge.nsi
!ifndef SOURCEDIR
	!define SOURCEDIR "..\dist\Deluge-${APPVERSION}-arm64"
!endif
!ifndef OUTFILE
	!define OUTFILE "..\dist\deluge_${APPVERSION}_arm64_setup.exe"
!endif

Name          "${APPNAME} ${APPVERSION} (ARM64)"
BrandingText  "${APPNAME} ${APPVERSION} - native Windows ARM64"
OutFile       "${OUTFILE}"
InstallDir    "$PROGRAMFILES64\${APPNAME}"
InstallDirRegKey HKLM "Software\${APPNAME}" "InstallDir"
RequestExecutionLevel admin

!define MUI_ICON   "deluge.ico"
!define MUI_UNICON "deluge.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\bin\Deluge.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Start Deluge"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE.txt"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Function .onInit
	; The installer is x86, so without this both the file writes and the
	; registry writes below would be redirected into the WOW64 views.
	${DisableX64FSRedirection}
	SetRegView 64
FunctionEnd

Function un.onInit
	${DisableX64FSRedirection}
	SetRegView 64
FunctionEnd

Section "Deluge (required)" SecCore
	SectionIn RO
	SetOutPath "$INSTDIR"
	File /r "${SOURCEDIR}\*.*"

	WriteRegStr HKLM "Software\${APPNAME}" "InstallDir" "$INSTDIR"
	WriteRegStr HKLM "Software\${APPNAME}" "Version" "${APPVERSION}"

	WriteUninstaller "$INSTDIR\uninstall.exe"

	WriteRegStr HKLM "${UNINSTKEY}" "DisplayName"     "${APPNAME} ${APPVERSION} (ARM64)"
	WriteRegStr HKLM "${UNINSTKEY}" "DisplayVersion"  "${APPVERSION}"
	WriteRegStr HKLM "${UNINSTKEY}" "DisplayIcon"     "$INSTDIR\bin\Deluge.exe"
	WriteRegStr HKLM "${UNINSTKEY}" "Publisher"       "${PUBLISHER}"
	WriteRegStr HKLM "${UNINSTKEY}" "URLInfoAbout"    "${WEBSITE}"
	WriteRegStr HKLM "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
	WriteRegStr HKLM "${UNINSTKEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
	WriteRegDWORD HKLM "${UNINSTKEY}" "NoModify" 1
	WriteRegDWORD HKLM "${UNINSTKEY}" "NoRepair" 1

	${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
	IntFmt $0 "0x%08X" $0
	WriteRegDWORD HKLM "${UNINSTKEY}" "EstimatedSize" "$0"
SectionEnd

Section "Start Menu shortcuts" SecStartMenu
	CreateDirectory "$SMPROGRAMS\${APPNAME}"
	CreateShortCut "$SMPROGRAMS\${APPNAME}\Deluge.lnk"          "$INSTDIR\bin\Deluge.exe"       "" "$INSTDIR\bin\Deluge.exe" 0
	CreateShortCut "$SMPROGRAMS\${APPNAME}\Deluge Daemon.lnk"   "$INSTDIR\bin\deluged.exe"      "" "$INSTDIR\bin\Deluge.exe" 0
	CreateShortCut "$SMPROGRAMS\${APPNAME}\Deluge Web UI.lnk"   "$INSTDIR\bin\deluge-web.exe"   "" "$INSTDIR\bin\Deluge.exe" 0
	CreateShortCut "$SMPROGRAMS\${APPNAME}\Uninstall Deluge.lnk" "$INSTDIR\uninstall.exe"
SectionEnd

Section "Desktop shortcut" SecDesktop
	CreateShortCut "$DESKTOP\Deluge.lnk" "$INSTDIR\bin\Deluge.exe" "" "$INSTDIR\bin\Deluge.exe" 0
SectionEnd

Section "Associate .torrent files and magnet links" SecAssoc
	WriteRegStr HKCR ".torrent" "" "Deluge.Torrent"
	WriteRegStr HKCR ".torrent" "Content Type" "application/x-bittorrent"
	WriteRegStr HKCR "Deluge.Torrent" "" "BitTorrent Torrent"
	WriteRegStr HKCR "Deluge.Torrent\DefaultIcon" "" "$INSTDIR\bin\Deluge.exe,0"
	WriteRegStr HKCR "Deluge.Torrent\shell\open\command" "" '"$INSTDIR\bin\Deluge.exe" "%1"'

	WriteRegStr HKCR "magnet" "" "URL:Magnet Link"
	WriteRegStr HKCR "magnet" "URL Protocol" ""
	WriteRegStr HKCR "magnet\DefaultIcon" "" "$INSTDIR\bin\Deluge.exe,0"
	WriteRegStr HKCR "magnet\shell\open\command" "" '"$INSTDIR\bin\Deluge.exe" "%1"'

	System::Call 'shell32::SHChangeNotify(i 0x8000000, i 0, i 0, i 0)'
SectionEnd

LangString DESC_SecCore      ${LANG_ENGLISH} "Deluge ${APPVERSION} with its bundled Python 3.14, GTK 3 and libtorrent 2.1.2 runtime. All native ARM64."
LangString DESC_SecStartMenu ${LANG_ENGLISH} "Add Deluge, the daemon and the Web UI to the Start Menu."
LangString DESC_SecDesktop   ${LANG_ENGLISH} "Put a Deluge shortcut on the desktop."
LangString DESC_SecAssoc     ${LANG_ENGLISH} "Open .torrent files and magnet: links with Deluge."

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
	!insertmacro MUI_DESCRIPTION_TEXT ${SecCore}      $(DESC_SecCore)
	!insertmacro MUI_DESCRIPTION_TEXT ${SecStartMenu} $(DESC_SecStartMenu)
	!insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop}   $(DESC_SecDesktop)
	!insertmacro MUI_DESCRIPTION_TEXT ${SecAssoc}     $(DESC_SecAssoc)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
	Delete "$DESKTOP\Deluge.lnk"
	RMDir /r "$SMPROGRAMS\${APPNAME}"

	; Only hand the associations back if they are still ours.
	ReadRegStr $0 HKCR ".torrent" ""
	StrCmp $0 "Deluge.Torrent" 0 +2
		DeleteRegKey HKCR ".torrent"
	DeleteRegKey HKCR "Deluge.Torrent"

	ReadRegStr $0 HKCR "magnet\shell\open\command" ""
	StrCmp $0 '"$INSTDIR\bin\Deluge.exe" "%1"' 0 +2
		DeleteRegKey HKCR "magnet"

	RMDir /r "$INSTDIR"

	DeleteRegKey HKLM "${UNINSTKEY}"
	DeleteRegKey HKLM "Software\${APPNAME}"
	System::Call 'shell32::SHChangeNotify(i 0x8000000, i 0, i 0, i 0)'
SectionEnd
