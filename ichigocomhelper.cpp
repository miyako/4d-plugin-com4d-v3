//
// Copyright (c) 2016 The Ichigopack Project (http://ichigopack.net/).
//

#include "ichigocomhelper.h"

HRESULT
suppLogFileAppendW(LPCWSTR pszFileNameW, const void* pv, ULONG cb,
	ULONG* pcbWritten) throw()
{
	DWORD   cbWrittenTemp;
	if (pcbWritten == NULL) {
		pcbWritten = &cbWrittenTemp;
	}
	*pcbWritten = 0;
	HANDLE hFile = CreateFileW(
		pszFileNameW, GENERIC_READ |
		GENERIC_WRITE, FILE_SHARE_READ, NULL,
		OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
	if (hFile == INVALID_HANDLE_VALUE) {
		return E_FAIL;
	}
	LARGE_INTEGER liDist;
	liDist.QuadPart = 0;
	if (SetFilePointerEx(hFile, liDist, NULL, FILE_END)) {
		WriteFile(hFile, pv, cb, pcbWritten, NULL);
	}
	CloseHandle(hFile);
	return (*pcbWritten == cb) ? S_OK : E_FAIL;
}

std::wstring
suppGetModuleFileName(HINSTANCE hinst)
{
	WCHAR   wszBuf[MAX_PATH + 1];
	DWORD   dw;
	dw = GetModuleFileNameW((HMODULE)hinst, wszBuf, MAX_PATH + 1);
	if (dw > 0 && dw <= MAX_PATH) {
		return std::wstring(wszBuf);
	}
	return std::wstring();
}

// L"xxxxxxxx-xxxx-...xx"
std::wstring
suppGuidToString(const GUID& rguid, bool brackets_flag)
{
	std::wstring    ret;
	RPC_WSTR wstr = NULL;
	if (RPC_S_OK == UuidToStringW(&rguid, &wstr)) {
		if (brackets_flag) {
			ret += L'{';
		}
		ret += (WCHAR*)wstr;
		if (brackets_flag) {
			ret += L'}';
		}
		RpcStringFreeW(&wstr);
	}
	return ret;
}

bool
suppIsPerUserRequest(LPCWSTR pwszCmdline) throw()
{
	if (pwszCmdline == NULL) {
		return false;
	}
	if ((pwszCmdline[0] == L'U' || pwszCmdline[0] == L'u') &&
		(pwszCmdline[1] == L'S' || pwszCmdline[1] == L's') &&
		(pwszCmdline[2] == L'E' || pwszCmdline[2] == L'e') &&
		(pwszCmdline[3] == L'R' || pwszCmdline[3] == L'r')) {
		return true;
	}
	return false;
}

std::wstring
suppGetRegKey(HKEY* phkeyRoot, bool per_user_flag)
{
	*phkeyRoot = per_user_flag ? HKEY_CURRENT_USER : HKEY_LOCAL_MACHINE;
	return std::wstring(L"SOFTWARE\\Classes");
}

std::wstring
suppGetRegKeyGUID(HKEY* phkeyRoot, bool per_user_flag, const GUID& rguid,
	LPCWSTR pwszGUIDType, LPCWSTR pwszSubkey)
{
	std::wostringstream wos;
	std::wstring    wstrGUID;
	std::wstring    wstrKeyRoot;
	wstrKeyRoot = suppGetRegKey(phkeyRoot, per_user_flag);
	wstrGUID = suppGuidToString(rguid, true);
	if (!wstrKeyRoot.empty() && !wstrGUID.empty()) {
		wos << wstrKeyRoot << L'\\' << pwszGUIDType << L'\\' << wstrGUID;
		if (pwszSubkey != NULL) {
			wos << L'\\' << pwszSubkey;
		}
		return wos.str();
	}
	return std::wstring();
}

std::wstring
suppGetRegKeyProgID(HKEY* phkeyRoot, bool per_user_flag,
	LPCWSTR pwszProgID, LPCWSTR pwszSubkey)
{
	std::wostringstream wos;
	std::wstring    wstrKeyRoot;
	wstrKeyRoot = suppGetRegKey(phkeyRoot, per_user_flag);
	if (!wstrKeyRoot.empty()) {
		wos << wstrKeyRoot << L'\\' << pwszProgID;
		if (pwszSubkey != NULL) {
			wos << L'\\' << pwszSubkey;
		}
		return wos.str();
	}
	return std::wstring();
}

std::wstring
suppGetRegKeyAppID(HKEY* phkeyRoot, bool per_user_flag,
	const CLSID& rappid, LPCWSTR pwszSubkey)
{
	return suppGetRegKeyGUID(phkeyRoot, per_user_flag, rappid, L"AppID",
		pwszSubkey);
}

std::wstring
suppGetRegKeyCLSID(HKEY* phkeyRoot, bool per_user_flag,
	const CLSID& rclsid, LPCWSTR pwszSubkey)
{
	return suppGetRegKeyGUID(phkeyRoot, per_user_flag, rclsid, L"CLSID",
		pwszSubkey);
}

std::wstring
suppGetRegKeyInterface(HKEY* phkeyRoot, bool per_user_flag,
	const IID& riid, LPCWSTR pwszSubkey)
{
	return suppGetRegKeyGUID(phkeyRoot, per_user_flag, riid, L"Interface",
		pwszSubkey);
}

LONG
suppRegSetStringW(HKEY hkeyRoot, LPCWSTR pwszSubkey,
	LPCWSTR pwszValueName, LPCWSTR pwszValue)
{
	LONG    ret = ERROR_SUCCESS;
	HKEY    hkeySub = hkeyRoot;
	if (pwszSubkey != NULL) {
		ret = RegCreateKeyExW(
			hkeyRoot, pwszSubkey, 0, NULL, REG_OPTION_NON_VOLATILE,
			KEY_READ | KEY_WRITE, NULL, &hkeySub, NULL);
	}
	if (ret == ERROR_SUCCESS) {
		DWORD  cbData = sizeof(pwszValue[0]) * (lstrlenW(pwszValue) + 1);
		ret = RegSetValueExW(
			hkeySub, pwszValueName, 0, REG_SZ,
			(const BYTE*)(pwszValue), cbData);
		if (pwszSubkey != NULL) {
			RegCloseKey(hkeySub);
		}
	}
	return ret;
}

LONG
suppRegRemoveKeyW(HKEY hkeyRoot, LPCWSTR pwszKey) throw()
{
	const int   KEYNAME_MAX =
		256; // full key name limit = 255 characters (MSDN)
	LONG    ret = ERROR_SUCCESS;
	WCHAR   wszSubkey[KEYNAME_MAX];
	DWORD   cSubkey;
	HKEY    hkeySub;
	ret = RegOpenKeyExW(hkeyRoot, pwszKey, 0, KEY_READ, &hkeySub);
	if (ret == ERROR_FILE_NOT_FOUND) {
		return ERROR_SUCCESS;
	}
	if (ret != ERROR_SUCCESS) {
		return ret;
	}
	while (1) {
		cSubkey = KEYNAME_MAX;
		ret = RegEnumKeyExW(hkeySub, 0, wszSubkey,
			&cSubkey, NULL, NULL, NULL, NULL);
		if (ret == ERROR_NO_MORE_ITEMS) {
			break;
		}
		if (ret != ERROR_SUCCESS) {
			break;
		}
		ret = suppRegRemoveKeyW(hkeySub, wszSubkey);
		if (ret != ERROR_SUCCESS) {
			break;
		}
	}
	RegCloseKey(hkeySub);
	if (ret != ERROR_NO_MORE_ITEMS) {
		return ret;
	}
	return RegDeleteKeyW(hkeyRoot, pwszKey);
}

