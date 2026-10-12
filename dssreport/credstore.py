"""Secrets (R365 password, Microsoft 365 sign-in token) live ONLY in the operating
system's credential store on this computer. Never in a file, never in the repo,
never in a log. If no secure store is available we refuse to store anything.

  * Windows: Credential Manager (via ctypes, nothing to install)
  * Linux:   `secret-tool` (libsecret) when installed; the secret goes in on stdin
  * other:   not supported -> CredentialStoreError
"""

import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from typing import Optional

from .errors import DssError

SERVICE = "DssReport"


class CredentialStoreError(DssError):
    pass


class CredentialStore(ABC):
    @abstractmethod
    def get(self, name: str) -> Optional[str]: ...

    @abstractmethod
    def set(self, name: str, secret: str) -> None: ...

    @abstractmethod
    def delete(self, name: str) -> None: ...


class WindowsCredentialStore(CredentialStore):
    """Windows Credential Manager, generic credentials, kept on this PC only."""

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wintypes = ctypes, wintypes
        self.adv = ctypes.WinDLL("advapi32", use_last_error=True)

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                        ("LastWritten", wintypes.FILETIME),
                        ("CredentialBlobSize", wintypes.DWORD),
                        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                        ("UserName", wintypes.LPWSTR)]
        self.CREDENTIAL = CREDENTIAL
        self.adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
        self.adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                       ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
        self.adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.adv.CredFree.argtypes = [ctypes.c_void_p]

    @staticmethod
    def _target(name):
        return f"{SERVICE}:{name}"

    def set(self, name, secret):
        c = self.ctypes
        blob = secret.encode("utf-16-le")
        buf = (c.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = self.CREDENTIAL()
        cred.Type = self.CRED_TYPE_GENERIC
        cred.TargetName = self._target(name)
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = c.cast(buf, c.POINTER(c.c_ubyte))
        cred.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = SERVICE
        if not self.adv.CredWriteW(c.byref(cred), 0):
            raise CredentialStoreError("Windows would not save the sign-in to its credential store.")

    def get(self, name):
        c = self.ctypes
        ptr = c.POINTER(self.CREDENTIAL)()
        if not self.adv.CredReadW(self._target(name), self.CRED_TYPE_GENERIC, 0, c.byref(ptr)):
            return None
        try:
            size = ptr.contents.CredentialBlobSize
            raw = c.string_at(ptr.contents.CredentialBlob, size)
            return raw.decode("utf-16-le")
        finally:
            self.adv.CredFree(ptr)

    def delete(self, name):
        self.adv.CredDeleteW(self._target(name), self.CRED_TYPE_GENERIC, 0)


class SecretToolStore(CredentialStore):
    """Linux desktop keyring through `secret-tool`. The secret never appears on a command line."""

    def __init__(self, exe="secret-tool"):
        self.exe = exe

    def _attrs(self, name):
        return ["service", SERVICE, "account", name]

    def set(self, name, secret):
        r = subprocess.run([self.exe, "store", f"--label={SERVICE} {name}"] + self._attrs(name),
                           input=secret.encode(), capture_output=True)
        if r.returncode != 0:
            raise CredentialStoreError("The system keyring would not save the sign-in.")

    def get(self, name):
        r = subprocess.run([self.exe, "lookup"] + self._attrs(name), capture_output=True)
        if r.returncode != 0 or not r.stdout:
            return None
        return r.stdout.decode()

    def delete(self, name):
        subprocess.run([self.exe, "clear"] + self._attrs(name), capture_output=True)


class InMemoryStoreForTests(CredentialStore):
    """Only for tests. Holds secrets in memory and forgets them when the program ends."""

    def __init__(self):
        self.items = {}

    def get(self, name):
        return self.items.get(name)

    def set(self, name, secret):
        self.items[name] = secret

    def delete(self, name):
        self.items.pop(name, None)


def default_store() -> CredentialStore:
    if sys.platform == "win32":
        return WindowsCredentialStore()
    if sys.platform.startswith("linux") and shutil.which("secret-tool"):
        return SecretToolStore()
    raise CredentialStoreError(
        "No secure place to keep the password was found on this computer, so nothing was saved. "
        "On Windows this is built in.")


def redact(text: str, *secrets: Optional[str]) -> str:
    """Remove any known secret from text before it is shown or logged."""
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text
