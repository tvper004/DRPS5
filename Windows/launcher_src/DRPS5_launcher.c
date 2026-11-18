#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>

// Firmas de la API de CPython 3.11
typedef void (*Py_SetProgramName_t)(const wchar_t *);
typedef void (*Py_SetPythonHome_t)(const wchar_t *);
typedef int (*Py_Main_t)(int argc, wchar_t **argv);

int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, PWSTR pCmdLine, int nCmdShow) {
    (void)hInstance;
    (void)hPrevInstance;
    (void)nCmdShow;

    // Obtener ruta del ejecutable DRPS5.exe
    wchar_t exePath[MAX_PATH];
    if (!GetModuleFileNameW(NULL, exePath, MAX_PATH)) {
        MessageBoxW(NULL, L"Error obteniendo ruta del ejecutable DRPS5.", L"Error DRPS5", MB_ICONERROR | MB_OK);
        return 1;
    }

    // Directorio base de la aplicación (donde reside DRPS5.exe)
    wchar_t baseDir[MAX_PATH];
    wcscpy(baseDir, exePath);
    wchar_t* lastSlash = wcsrchr(baseDir, L'\\');
    if (lastSlash) {
        *lastSlash = L'\0';
    }
    SetCurrentDirectoryW(baseDir);

    // Si se pasa --console, asignar consola estándar para depuración
    if (pCmdLine && wcsstr(pCmdLine, L"--console")) {
        AllocConsole();
        FILE* fp;
        _wfreopen_s(&fp, L"CONOUT$", L"w", stdout);
        _wfreopen_s(&fp, L"CONOUT$", L"w", stderr);
        _wfreopen_s(&fp, L"CONIN$", L"r", stdin);
        wprintf(L"=== Consola de Depuracion DRPS5 ===\n");
    }

    // Directorio de Python embebido (runtime o python)
    wchar_t runtimeDir[MAX_PATH];
    swprintf(runtimeDir, MAX_PATH, L"%ls\\runtime", baseDir);
    if (GetFileAttributesW(runtimeDir) == INVALID_FILE_ATTRIBUTES) {
        swprintf(runtimeDir, MAX_PATH, L"%ls\\python", baseDir);
    }

    if (GetFileAttributesW(runtimeDir) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"No se encontró el directorio de ejecución 'runtime'.\nPor favor reinstale DRPS5.", L"DRPS5 - Error de Componentes", MB_ICONERROR | MB_OK);
        return 1;
    }

    // Ruta de la librería principal python311.dll
    wchar_t pythonDllPath[MAX_PATH];
    swprintf(pythonDllPath, MAX_PATH, L"%ls\\python311.dll", runtimeDir);
    if (GetFileAttributesW(pythonDllPath) == INVALID_FILE_ATTRIBUTES) {
        swprintf(pythonDllPath, MAX_PATH, L"%ls\\python3.dll", runtimeDir);
    }

    // Configurar directorio DLL para que Windows resuelva dependencias embebidas (vcruntime, etc.)
    SetDllDirectoryW(runtimeDir);

    HMODULE hPython = LoadLibraryW(pythonDllPath);
    if (!hPython) {
        wchar_t errMsg[512];
        swprintf(errMsg, 512, L"No se pudo cargar la librería central de DRPS5 (%ls).\nCódigo de error Windows: %lu.\nVerifique que Microsoft Visual C++ 2015-2022 Redistributable esté instalado.", pythonDllPath, GetLastError());
        MessageBoxW(NULL, errMsg, L"DRPS5 - Error de Librerías", MB_ICONERROR | MB_OK);
        return 1;
    }

    // Obtener puntos de entrada de CPython
    Py_SetProgramName_t pPy_SetProgramName = (Py_SetProgramName_t)GetProcAddress(hPython, "Py_SetProgramName");
    Py_SetPythonHome_t  pPy_SetPythonHome  = (Py_SetPythonHome_t)GetProcAddress(hPython, "Py_SetPythonHome");
    Py_Main_t           pPy_Main           = (Py_Main_t)GetProcAddress(hPython, "Py_Main");

    if (!pPy_Main) {
        FreeLibrary(hPython);
        MessageBoxW(NULL, L"No se pudo inicializar el punto de entrada 'Py_Main'.", L"DRPS5 - Error de Inicialización", MB_ICONERROR | MB_OK);
        return 1;
    }

    // Indicar a Python que el programa es DRPS5.exe y su directorio base es runtime
    if (pPy_SetProgramName) {
        pPy_SetProgramName(exePath);
    }
    if (pPy_SetPythonHome) {
        pPy_SetPythonHome(runtimeDir);
    }

    // Script principal drps5.py
    wchar_t scriptPath[MAX_PATH];
    swprintf(scriptPath, MAX_PATH, L"%ls\\drps5.py", baseDir);

    // Preparar lista de argumentos wchar_t*
    // argv[0] = exePath, argv[1] = scriptPath, argv[2..n] = argumentos de pCmdLine
    int maxArgs = 64;
    wchar_t** pyArgv = (wchar_t**)malloc(sizeof(wchar_t*) * maxArgs);
    int pyArgc = 0;

    pyArgv[pyArgc++] = _wcsdup(exePath);
    pyArgv[pyArgc++] = _wcsdup(scriptPath);

    // Parsear pCmdLine si contiene argumentos adicionales
    if (pCmdLine && wcslen(pCmdLine) > 0) {
        int numParsed = 0;
        wchar_t** parsedArgs = CommandLineToArgvW(pCmdLine, &numParsed);
        if (parsedArgs) {
            for (int i = 0; i < numParsed && pyArgc < (maxArgs - 1); i++) {
                pyArgv[pyArgc++] = _wcsdup(parsedArgs[i]);
            }
            LocalFree(parsedArgs);
        }
    }
    pyArgv[pyArgc] = NULL;

    // Ejecutar Python directamente dentro del proceso DRPS5.exe
    int exitCode = pPy_Main(pyArgc, pyArgv);

    // Liberar memoria
    for (int i = 0; i < pyArgc; i++) {
        free(pyArgv[i]);
    }
    free(pyArgv);

    FreeLibrary(hPython);

    // Si falló con error, verificar si existe crash.log para mostrarlo
    if (exitCode != 0) {
        wchar_t crashPath[MAX_PATH];
        swprintf(crashPath, MAX_PATH, L"%ls\\crash.log", baseDir);

        DWORD attr = GetFileAttributesW(crashPath);
        if (attr != INVALID_FILE_ATTRIBUTES) {
            FILE* f = _wfopen(crashPath, L"rt");
            if (f) {
                char logBuf[1024] = {0};
                size_t readBytes = fread(logBuf, 1, 1000, f);
                fclose(f);
                logBuf[readBytes] = '\0';
                wchar_t errorMsg[2048];
                swprintf(errorMsg, 2048, L"DRPS5 finalizó con código de error (%d):\n\n%hs", exitCode, logBuf);
                MessageBoxW(NULL, errorMsg, L"DRPS5 - Error", MB_ICONERROR | MB_OK);
            }
        }
    }

    return exitCode;
}
