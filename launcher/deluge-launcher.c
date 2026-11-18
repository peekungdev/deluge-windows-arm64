/*
 * Portable launcher for the Deluge native-ARM64 bundle.
 *
 * The console/gui scripts pip generates embed an absolute path to the
 * interpreter that built them, so they break the moment the bundle is moved.
 * This launcher resolves its own location at run time, points the Python and
 * GTK/GLib environment at the surrounding bundle, and runs a Deluge entry point.
 *
 * Layout it assumes (mirrors an MSYS2 prefix, so GLib's own relocation works):
 *   <root>/bin/     this .exe, python.exe/pythonw.exe, every bundled DLL
 *   <root>/lib/     python3.14/, girepository-1.0/, gdk-pixbuf-2.0/
 *   <root>/share/   glib-2.0/schemas/, icons/, themes/
 *   <root>/etc/     gtk-3.0/
 *
 * Paths are built with forward slashes throughout - every Win32 and GLib call
 * used here accepts them - and the one place a literal backslash is needed
 * (splitting the path GetModuleFileNameW returns) uses BSL below.
 *
 * Build (see deploy.sh):
 *   clang -municode -DDELUGE_CONSOLE -DDELUGE_SCRIPT='L"deluge-console"'
 *   clang -municode -Wl,--subsystem,windows -DDELUGE_SCRIPT='L"deluge"' 
 */

#include <windows.h>
#include <wchar.h>

/* Name of the script under <root>/lib/deluge-scripts to run. Running a real
 * file rather than `python -c ...` is what makes sys.argv[0] - and therefore
 * the program name Deluge prints in --version and --help - come out right. */
#ifndef DELUGE_SCRIPT
#define DELUGE_SCRIPT L"deluge"
#endif

/* Console builds keep a terminal and propagate the child's exit code; GUI
 * builds use pythonw.exe so no console window ever flashes up. */
#ifdef DELUGE_CONSOLE
#define PY_EXE L"/python.exe"
#else
#define PY_EXE L"/pythonw.exe"
#endif

#define BUFSZ 4096
#define BSL ((wchar_t)92) /* backslash */
#define FSL ((wchar_t)47) /* forward slash */

static void join(wchar_t *out, size_t n, const wchar_t *a, const wchar_t *b) {
	_snwprintf(out, n, L"%s%s", a, b);
	out[n - 1] = L'\0';
}

static void set_sub_path(const wchar_t *name, const wchar_t *root, const wchar_t *tail) {
	wchar_t buf[BUFSZ];
	join(buf, BUFSZ, root, tail);
	SetEnvironmentVariableW(name, buf);
}

/* Strip the last path component in place, accepting either separator. */
static int strip_component(wchar_t *path) {
	wchar_t *b = wcsrchr(path, BSL);
	wchar_t *f = wcsrchr(path, FSL);
	wchar_t *cut = (b > f) ? b : f;
	if (!cut) return 0;
	*cut = L'\0';
	return 1;
}

/* Return the raw command line with argv[0] removed, respecting quoting. */
static const wchar_t *skip_argv0(const wchar_t *cl) {
	if (*cl == L'"') {
		cl++;
		while (*cl && *cl != L'"') cl++;
		if (*cl == L'"') cl++;
	} else {
		while (*cl && *cl != L' ' && *cl != L'\t') cl++;
	}
	while (*cl == L' ' || *cl == L'\t') cl++;
	return cl;
}

static int run(void) {
	wchar_t exe[BUFSZ], root[BUFSZ], bin[BUFSZ], py[BUFSZ], script[BUFSZ];
	wchar_t oldpath[BUFSZ], newpath[BUFSZ * 2], cmd[BUFSZ * 2];
	STARTUPINFOW si;
	PROCESS_INFORMATION pi;
	DWORD n;

	n = GetModuleFileNameW(NULL, exe, BUFSZ);
	if (n == 0 || n >= BUFSZ) return 1;

	/* This .exe lives in <root>/bin, so strip two components. */
	wcscpy(root, exe);
	if (!strip_component(root)) return 1;
	wcscpy(bin, root);
	if (!strip_component(root)) return 1;

	join(py, BUFSZ, bin, PY_EXE);

	/* Bundled DLLs must win over anything already on PATH. */
	oldpath[0] = L'\0';
	GetEnvironmentVariableW(L"PATH", oldpath, BUFSZ);
	_snwprintf(newpath, BUFSZ * 2, L"%s;%s", bin, oldpath);
	newpath[BUFSZ * 2 - 1] = L'\0';
	SetEnvironmentVariableW(L"PATH", newpath);

	SetEnvironmentVariableW(L"PYTHONHOME", root);
	set_sub_path(L"GI_TYPELIB_PATH", root, L"/lib/girepository-1.0");
	set_sub_path(L"GDK_PIXBUF_MODULE_FILE", root, L"/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache");
	set_sub_path(L"GDK_PIXBUF_MODULEDIR", root, L"/lib/gdk-pixbuf-2.0/2.10.0/loaders");
	set_sub_path(L"XDG_DATA_DIRS", root, L"/share");
	set_sub_path(L"GSETTINGS_SCHEMA_DIR", root, L"/share/glib-2.0/schemas");

	/* Without these OpenSSL cannot find its provider modules and warns on
	 * every start that the legacy provider failed to load. */
	set_sub_path(L"OPENSSL_MODULES", root, L"/lib/ossl-modules");
	set_sub_path(L"OPENSSL_CONF", root, L"/etc/ssl/openssl.cnf");
	set_sub_path(L"SSL_CERT_FILE", root, L"/etc/ssl/cert.pem");

	join(script, BUFSZ, root, L"/lib/deluge-scripts/" DELUGE_SCRIPT);
	_snwprintf(cmd, BUFSZ * 2, L"\"%s\" \"%s\" %s",
	           py, script, skip_argv0(GetCommandLineW()));
	cmd[BUFSZ * 2 - 1] = L'\0';

	ZeroMemory(&si, sizeof(si));
	si.cb = sizeof(si);
	ZeroMemory(&pi, sizeof(pi));

	if (!CreateProcessW(py, cmd, NULL, NULL, TRUE, 0, NULL, bin, &si, &pi)) {
		wchar_t msg[BUFSZ];
		_snwprintf(msg, BUFSZ, L"Failed to start:%c%s%c%cError %lu",
		           (wchar_t)10, py, (wchar_t)10, (wchar_t)10, GetLastError());
#ifdef DELUGE_CONSOLE
		{
			DWORD w;
			WriteConsoleW(GetStdHandle(STD_ERROR_HANDLE), msg, (DWORD)wcslen(msg), &w, NULL);
		}
#else
		MessageBoxW(NULL, msg, L"Deluge", MB_ICONERROR | MB_OK);
#endif
		return 1;
	}

#ifdef DELUGE_CONSOLE
	{
		DWORD code = 1;
		WaitForSingleObject(pi.hProcess, INFINITE);
		GetExitCodeProcess(pi.hProcess, &code);
		CloseHandle(pi.hProcess);
		CloseHandle(pi.hThread);
		return (int)code;
	}
#else
	CloseHandle(pi.hProcess);
	CloseHandle(pi.hThread);
	return 0;
#endif
}

#ifdef DELUGE_CONSOLE
int wmain(void) {
	return run();
}
#else
int WINAPI wWinMain(HINSTANCE h, HINSTANCE hp, LPWSTR cl, int show) {
	(void)h; (void)hp; (void)cl; (void)show;
	return run();
}
#endif
