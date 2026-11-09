# -*- coding: utf-8 -*-
"""OfficeCLI runtime: the single execution substrate for this skill.

Every mutation this skill performs is an OfficeCLI command. This module owns the
process boundary, the JSON envelope contract, the resident lifecycle and the
DocumentSpec -> OfficeCLI path translation. Engines must not shell out to
``officecli`` or edit OOXML directly for mutation.

The adapter is written against OfficeCLI 1.0.160. Commands that were verified
against that build are documented on each method; anything newer is accepted
only when it keeps the same envelope shape.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

DEFAULT_TIMEOUT = 120
MIN_VERSION = (1, 0, 130)
VERIFIED_VERSION = "1.0.160"

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_SEGMENT_RE = re.compile(r"^([a-z_]+)\[([0-9]+)\]$")
_SECTION_RE = re.compile(r"^sec\[([0-9]+)\]$")

_SEGMENT_MAP = {
    "p": "p",
    "tbl": "tbl",
    "r": "tr",
    "tr": "tr",
    "row": "tr",
    "c": "tc",
    "tc": "tc",
    "cell": "tc",
}

_SECTION_STORIES = (
    ("header", "headerRef", "default"),
    ("first_page_header", "headerRef", "first"),
    ("even_page_header", "headerRef", "even"),
    ("footer", "footerRef", "default"),
    ("first_page_footer", "footerRef", "first"),
    ("even_page_footer", "footerRef", "even"),
)


class OfficecliError(RuntimeError):
    """Raised when OfficeCLI is missing, rejects a command, or returns bad JSON."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "OFFICECLI_ERROR",
        details: Optional[Dict[str, Any]] = None,
        exit_code: Optional[int] = None,
        warnings: Optional[Sequence[Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.exit_code = exit_code
        self.warnings = list(warnings or [])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "exit_code": self.exit_code,
        }


class OfficecliUnavailable(OfficecliError):
    """The binary is not installed, cannot be started, or cannot report a version."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("code", "OFFICECLI_UNAVAILABLE")
        super().__init__(message, **kwargs)


class OfficecliVersionError(OfficecliError):
    """The installed binary is older than the capability floor this skill needs."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("code", "OFFICECLI_VERSION_UNSUPPORTED")
        super().__init__(message, **kwargs)


class UnsupportedLocation(OfficecliError):
    """The DocumentSpec location cannot be expressed as an OfficeCLI path."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("code", "WRITER_LOCATION_UNSUPPORTED")
        super().__init__(message, **kwargs)


# ---------------------------------------------------------------------------
# binary discovery and version gate
# ---------------------------------------------------------------------------


def _candidate_binaries() -> List[str]:
    return [
        os.path.expandvars(r"%LOCALAPPDATA%\OfficeCLI\officecli.exe"),
        os.path.expanduser(r"~\AppData\Local\OfficeCLI\officecli.exe"),
        "/usr/local/bin/officecli",
        os.path.expanduser("~/.local/bin/officecli"),
        "/opt/officecli/officecli",
    ]


def find_binary() -> Optional[str]:
    """Return the OfficeCLI executable, or ``None`` when it is not installed.

    ``OFFICECLI_BINARY`` wins when set. An override that points at a missing
    file raises instead of silently falling back, because a half-configured
    environment must not produce a different document than the caller expects.
    """
    override = os.environ.get("OFFICECLI_BINARY", "").strip()
    if override:
        candidate = os.path.expandvars(os.path.expanduser(override))
        if os.path.isfile(candidate):
            return candidate
        raise OfficecliUnavailable(
            "OFFICECLI_BINARY points at a missing file: {}".format(candidate),
            details={"OFFICECLI_BINARY": override},
        )

    for name in ("officecli", "officecli.exe"):
        found = shutil.which(name)
        if found:
            return found

    for candidate in _candidate_binaries():
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def is_available() -> bool:
    try:
        return find_binary() is not None
    except OfficecliUnavailable:
        return False


def parse_version(text: str) -> Tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    if not match:
        raise OfficecliVersionError(
            "could not parse OfficeCLI version from {!r}".format(text)
        )
    return tuple(int(part) for part in match.groups())


def _parse_json_payload(stdout: Optional[str]) -> Dict[str, Any]:
    text = (stdout or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except ValueError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        value = json.loads(text[start : end + 1])
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _error_code(payload: Mapping[str, Any]) -> str:
    data = payload.get("data")
    if isinstance(data, dict):
        for result in data.get("results") or []:
            if isinstance(result, dict) and not result.get("success", True):
                return str(result.get("code") or "OFFICECLI_ITEM_FAILED")
    for key in ("code", "errorCode"):
        value = payload.get(key)
        if value:
            return str(value)
    error = payload.get("error")
    if isinstance(error, dict) and error.get("code"):
        return str(error["code"])
    return "OFFICECLI_ERROR"


def _failure_message(
    payload: Mapping[str, Any], run: Optional[subprocess.CompletedProcess]
) -> str:
    data = payload.get("data")
    if isinstance(data, dict):
        failures = [
            item
            for item in (data.get("results") or [])
            if isinstance(item, dict) and not item.get("success", True)
        ]
        if failures:
            first = failures[0]
            return "{} (code {})".format(
                str(first.get("error") or first.get("message") or "command failed")[:300],
                first.get("code") or "unknown",
            )
    message = payload.get("message") or payload.get("error")
    if isinstance(message, dict):
        message = message.get("message") or message.get("detail")
    if message:
        return str(message)[:300]
    warnings = payload.get("warnings")
    if isinstance(warnings, list):
        notes = [
            str(item.get("message"))
            for item in warnings
            if isinstance(item, dict) and item.get("message")
        ]
        if notes:
            return "; ".join(notes)[:500]
    if run is not None:
        stderr = (run.stderr or "").strip()
        if stderr:
            return stderr[:300]
    return "officecli command failed"


# ---------------------------------------------------------------------------
# path translation
# ---------------------------------------------------------------------------


def _append_segments(base: str, segments: Sequence[str]) -> str:
    path = base.rstrip("/")
    for segment in segments:
        match = _SEGMENT_RE.match(segment)
        if not match:
            raise UnsupportedLocation(
                "segment {!r} is not addressable (textbox/sdt/field containers "
                "need an explicit OfficeCLI path)".format(segment)
            )
        name, index = match.group(1), int(match.group(2))
        mapped = _SEGMENT_MAP.get(name)
        if mapped is None:
            raise UnsupportedLocation(
                "segment {!r} has no OfficeCLI equivalent".format(segment)
            )
        path += "/{0}[{1}]".format(mapped, index + 1)
    return path


def build_story_map(file_path: str, runtime: Optional["OfficecliRuntime"] = None) -> Dict[str, str]:
    """Map ``sec[i].<story>`` to the OfficeCLI container path for that story.

    OfficeCLI exposes headers and footers as ``/header[N]`` and ``/footer[N]``
    parts, while DocumentSpec addresses them per section. ``get /section[N]``
    returns ``headerRef.default`` / ``headerRef.first`` / ``headerRef.even``
    (and the footer equivalents), which is the authoritative crosswalk.
    """
    engine = runtime or OfficecliRuntime()
    mapping: Dict[str, str] = {}
    try:
        sections = engine.query(file_path, "section")
    except OfficecliError:
        return mapping
    finally:
        # `query` starts a resident; never leave the template locked for the
        # staging copy or the user's next program.
        close = getattr(engine, "close", None)
        if callable(close):
            close(file_path)

    for index, section in enumerate(sections):
        fmt = section.get("format")
        if not isinstance(fmt, dict):
            continue
        for story, ref_name, scope in _SECTION_STORIES:
            if scope == "default":
                container = fmt.get(ref_name) or fmt.get("{}.{}".format(ref_name, scope))
            else:
                container = fmt.get("{}.{}".format(ref_name, scope))
            if isinstance(container, str) and container.startswith("/"):
                mapping["sec[{}].{}".format(index, story)] = container
    return mapping


def location_to_path(
    location_id: str,
    story_map: Optional[Mapping[str, str]] = None,
) -> str:
    """Translate a DocumentSpec 4.0 location into an OfficeCLI DOM path.

    Supported roots:

    * ``body.*`` — ``/body/...``
    * ``sec[i].header|footer|first_page_*|even_page_*`` — resolved through
      ``build_story_map`` to ``/header[N]`` / ``/footer[N]``
    * ``footnotes.footnote[i].*`` — ``/footnotes/footnote[i+1]/...``
    * ``endnotes.endnote[i].*`` — ``/endnotes/endnote[i+1]/...``
    * ``comments.comment[i]`` / ``comments.p[i]`` — ``/comments/comment[i+1]``

    Native OfficeCLI paths (``/body/p[1]``) pass through unchanged.
    """
    if not isinstance(location_id, str) or not location_id.strip():
        raise UnsupportedLocation("empty location id")
    if location_id.startswith("/"):
        return location_id

    parts = location_id.split(".")
    head = parts[0]

    if head == "body":
        if len(parts) < 2:
            raise UnsupportedLocation("location {!r} has no addressable segment".format(location_id))
        return _append_segments("/body", parts[1:])

    section = _SECTION_RE.match(head)
    if section:
        if len(parts) < 3:
            raise UnsupportedLocation(
                "section location {!r} must name a story and a node".format(location_id)
            )
        key = "sec[{}].{}".format(section.group(1), parts[1])
        base = (story_map or {}).get(key)
        if not base:
            raise UnsupportedLocation(
                "section {!r} has no OfficeCLI header/footer reference "
                "(a linked-to-previous story is not a separate part)".format(key)
            )
        return _append_segments(base, parts[2:])

    if head == "footnotes":
        if len(parts) < 2 or not _SEGMENT_RE.match(parts[1]):
            raise UnsupportedLocation(
                "footnote location {!r} must use footnotes.footnote[i]".format(location_id)
            )
        match = _SEGMENT_RE.match(parts[1])
        name, index = match.group(1), int(match.group(2))
        if name not in ("footnote", "endnote"):
            raise UnsupportedLocation(
                "footnote location {!r} is ambiguous; use footnotes.footnote[i]".format(location_id)
            )
        return _append_segments(
            "/footnotes/footnote[{}]".format(index + 1), parts[2:]
        )

    if head == "endnotes":
        if len(parts) < 2 or not _SEGMENT_RE.match(parts[1]):
            raise UnsupportedLocation(
                "endnote location {!r} must use endnotes.endnote[i]".format(location_id)
            )
        match = _SEGMENT_RE.match(parts[1])
        name, index = match.group(1), int(match.group(2))
        if name not in ("endnote", "footnote"):
            raise UnsupportedLocation(
                "endnote location {!r} is ambiguous; use endnotes.endnote[i]".format(location_id)
            )
        return _append_segments(
            "/endnotes/endnote[{}]".format(index + 1), parts[2:]
        )

    if head == "comments":
        if len(parts) < 2 or not _SEGMENT_RE.match(parts[1]):
            raise UnsupportedLocation(
                "comment location {!r} must use comments.comment[i]".format(location_id)
            )
        match = _SEGMENT_RE.match(parts[1])
        name, index = match.group(1), int(match.group(2))
        if name not in ("comment", "p"):
            raise UnsupportedLocation(
                "comment location {!r} cannot address a nested node".format(location_id)
            )
        if len(parts) > 2:
            raise UnsupportedLocation(
                "comment location {!r} cannot address a nested node".format(location_id)
            )
        return "/comments/comment[{}]".format(index + 1)

    raise UnsupportedLocation(
        "story {!r} is not addressable by the OfficeCLI runtime".format(head)
    )


def build_set_command(path: str, find: str, replace: str) -> Dict[str, Any]:
    """One atomic ``set`` item: literal find/replace scoped to ``path``."""
    return {
        "command": "set",
        "path": path,
        "props": {"find": find, "replace": replace},
    }


# ---------------------------------------------------------------------------
# runtime
# ---------------------------------------------------------------------------


class OfficecliRuntime:
    """Thin, stateless wrapper around one OfficeCLI binary."""

    def __init__(
        self,
        binary: Optional[str] = None,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        env: Optional[Mapping[str, str]] = None,
        cwd: Optional[str] = None,
        check_version: bool = False,
    ) -> None:
        self._binary = binary
        self.timeout = timeout
        self.env = dict(env or {})
        self.cwd = cwd
        self._version: Optional[str] = None
        if check_version:
            self.preflight()

    # -- discovery -----------------------------------------------------

    def ensure(self) -> str:
        binary = self._binary or find_binary()
        if not binary:
            raise OfficecliUnavailable(
                "officecli is not installed; install OfficeCLI {} or set "
                "OFFICECLI_BINARY".format(VERIFIED_VERSION)
            )
        self._binary = binary
        return binary

    def version(self) -> str:
        if self._version is not None:
            return self._version
        run = self._invoke(["--version"])
        if run.returncode != 0:
            raise OfficecliUnavailable(
                "officecli --version failed with exit {}: {}".format(
                    run.returncode, (run.stderr or "").strip()[:300]
                )
            )
        self._version = (run.stdout or "").strip()
        return self._version

    def preflight(self) -> str:
        """Verify the binary exists, runs, and meets the capability floor."""
        text = self.version()
        parsed = parse_version(text)
        if parsed < MIN_VERSION:
            raise OfficecliVersionError(
                "officecli {} is older than the required {} (verified against {})".format(
                    text, ".".join(map(str, MIN_VERSION)), VERIFIED_VERSION
                ),
                details={"installed": text, "minimum": ".".join(map(str, MIN_VERSION))},
            )
        return text

    # -- process boundary ---------------------------------------------

    def _invoke(
        self, arguments: Sequence[str], timeout: Optional[int] = None
    ) -> subprocess.CompletedProcess:
        binary = self.ensure()
        command = [binary] + [str(item) for item in arguments]
        environment = dict(os.environ)
        # A deferred resident write is invisible to the next process; forcing
        # per-command flushes makes staging deterministic for QA and commits.
        environment.setdefault("OFFICECLI_RESIDENT_FLUSH", "each")
        environment.update(self.env)
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.timeout,
                env=environment,
                cwd=self.cwd,
                creationflags=_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as exc:
            raise OfficecliError(
                "officecli timed out after {}s: {}".format(
                    timeout or self.timeout, " ".join(command)
                ),
                code="OFFICECLI_TIMEOUT",
            ) from exc
        except OSError as exc:
            raise OfficecliUnavailable(
                "officecli could not be started: {}".format(exc),
                details={"command": command},
            ) from exc

    def call(
        self,
        arguments: Sequence[str],
        *,
        json_output: bool = True,
        timeout: Optional[int] = None,
        check: bool = True,
    ) -> Dict[str, Any]:
        argv = list(arguments)
        if json_output:
            argv.append("--json")
        run = self._invoke(argv, timeout=timeout)
        payload = _parse_json_payload(run.stdout) if json_output else {}
        if not check:
            return payload
        if run.returncode not in (0, 2) or payload.get("success") is False:
            raise OfficecliError(
                _failure_message(payload, run),
                code=_error_code(payload),
                exit_code=run.returncode,
                warnings=list(payload.get("warnings") or []),
                details={
                    "command": argv,
                    "stdout": (run.stdout or "")[:2000],
                    "stderr": (run.stderr or "")[:2000],
                },
            )
        return payload

    # -- read verbs ----------------------------------------------------

    def query(self, file_path: str, selector: str, *, timeout: Optional[int] = None) -> List[Dict[str, Any]]:
        payload = self.call(["query", file_path, selector], timeout=timeout)
        data = payload.get("data")
        if isinstance(data, dict):
            results = data.get("results")
            if isinstance(results, list):
                return [item for item in results if isinstance(item, dict)]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    def get(self, file_path: str, path: str, *, timeout: Optional[int] = None) -> Dict[str, Any]:
        payload = self.call(["get", file_path, path], timeout=timeout)
        data = payload.get("data")
        if isinstance(data, dict):
            results = data.get("results")
            if isinstance(results, list) and results:
                return results[0]
        raise OfficecliError(
            "officecli get {} returned no node".format(path),
            code="OFFICECLI_NODE_NOT_FOUND",
            details={"path": path},
        )

    def dump(self, file_path: str, path: str = "/", *, timeout: Optional[int] = None) -> List[Dict[str, Any]]:
        payload = self.call(["dump", file_path, path], timeout=timeout)
        data = payload.get("data")
        if not isinstance(data, list):
            raise OfficecliError(
                "officecli dump {} returned no command list".format(path),
                code="OFFICECLI_DUMP_EMPTY",
                details={"path": path},
            )
        return [item for item in data if isinstance(item, dict)]

    def paragraphs(self, file_path: str) -> List[Dict[str, Any]]:
        return self.query(file_path, "paragraph")

    def sections(self, file_path: str) -> List[Dict[str, Any]]:
        return self.query(file_path, "section")

    def story_map(self, file_path: str) -> Dict[str, str]:
        return build_story_map(file_path, runtime=self)

    # -- write verbs ---------------------------------------------------

    def batch(
        self,
        file_path: str,
        commands: Sequence[Mapping[str, Any]],
        *,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Apply ``commands`` atomically; OfficeCLI rolls the whole batch back."""
        handle, payload_path = tempfile.mkstemp(prefix="officecli-batch-", suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(list(commands), stream, ensure_ascii=False)
            return self.call(
                ["batch", file_path, "--input", payload_path], timeout=timeout
            )
        finally:
            try:
                os.unlink(payload_path)
            except OSError:
                pass

    def set_props(
        self,
        file_path: str,
        path: str,
        props: Mapping[str, Any],
        *,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        arguments = ["set", file_path, path]
        for key, value in props.items():
            arguments.extend(["--prop", "{}={}".format(key, value)])
        return self.call(arguments, timeout=timeout)

    def add(
        self,
        file_path: str,
        parent: str,
        element_type: str,
        props: Optional[Mapping[str, Any]] = None,
        *,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        arguments = ["add", file_path, parent, "--type", element_type]
        for key, value in (props or {}).items():
            arguments.extend(["--prop", "{}={}".format(key, value)])
        return self.call(arguments, timeout=timeout)

    def remove(self, file_path: str, path: str, *, timeout: Optional[int] = None) -> Dict[str, Any]:
        return self.call(["remove", file_path, path], timeout=timeout)

    def raw(self, file_path: str, part: str = "/document", *, timeout: Optional[int] = None) -> str:
        run = self._invoke(["raw", file_path, part], timeout=timeout)
        if run.returncode != 0:
            raise OfficecliError(
                (run.stderr or "").strip()[:300] or "officecli raw failed",
                code="OFFICECLI_RAW_FAILED",
                exit_code=run.returncode,
                details={"part": part},
            )
        return run.stdout or ""

    def raw_set(
        self,
        file_path: str,
        part: str,
        *,
        xpath: str,
        action: str,
        xml: str,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self.call(
            [
                "raw-set",
                file_path,
                part,
                "--xpath",
                xpath,
                "--action",
                action,
                "--xml",
                xml,
            ],
            timeout=timeout,
        )

    def validate(self, file_path: str, *, timeout: Optional[int] = None) -> Dict[str, Any]:
        # A schema-invalid package is a *verdict*, not a transport failure:
        # return the envelope so the QA layer can report PACKAGE_SCHEMA_INVALID
        # instead of degrading it to UNVERIFIED.
        return self.call(["validate", file_path], timeout=timeout, check=False)

    def create(self, file_path: str, *, force: bool = False, timeout: Optional[int] = None) -> Dict[str, Any]:
        arguments = ["create", file_path]
        if force:
            arguments.append("--force")
        return self.call(arguments, timeout=timeout)

    def refresh(self, file_path: str, *, timeout: Optional[int] = None) -> Dict[str, Any]:
        return self.call(["refresh", file_path], timeout=timeout)

    # -- resident lifecycle -------------------------------------------

    def open(self, file_path: str, *, timeout: Optional[int] = None) -> Dict[str, Any]:
        return self.call(["open", file_path], json_output=False, check=False, timeout=timeout)

    def save(self, file_path: str, *, timeout: Optional[int] = None) -> Dict[str, Any]:
        return self.call(["save", file_path], json_output=False, check=False, timeout=timeout)

    def close(self, file_path: str, *, timeout: int = 30) -> None:
        """Flush the resident and release the file. Safe when no resident exists."""
        try:
            binary = find_binary()
        except OfficecliUnavailable:
            return
        if not binary:
            return
        try:
            self._invoke(["close", file_path], timeout=timeout)
        except (OfficecliError, OSError):
            return


def get_runtime(**kwargs: Any) -> OfficecliRuntime:
    """Return a fresh runtime; callers may keep it for a whole workflow."""
    return OfficecliRuntime(**kwargs)


def validation_report(
    file_path: str, runtime: Optional[OfficecliRuntime] = None
) -> Dict[str, Any]:
    """Run ``officecli validate`` and fold it into a QA-friendly section.

    The result is one of PASSED / FAILED / UNVERIFIED. Unavailability is a
    coverage gap, never a pass: the skill's QA contract forbids reporting
    "not detected" as "ok".
    """
    engine = runtime or OfficecliRuntime()
    if not is_available():
        return {
            "status": "UNVERIFIED",
            "passed": False,
            "issues": [],
            "coverage_gaps": ["OFFICECLI_VALIDATION_UNAVAILABLE"],
            "detail": "officecli is not installed",
        }
    try:
        payload = engine.validate(file_path)
    except OfficecliError as exc:
        return {
            "status": "UNVERIFIED",
            "passed": False,
            "issues": [],
            "coverage_gaps": ["OFFICECLI_VALIDATION_FAILED_TO_RUN"],
            "detail": "{}: {}".format(exc.code, exc.message),
        }
    finally:
        engine.close(file_path)

    success = payload.get("success")
    data = payload.get("data")
    if success is False:
        detail = _failure_message(payload, None)
        return {
            "status": "FAILED",
            "passed": False,
            "issues": [
                {
                    "code": "PACKAGE_SCHEMA_INVALID",
                    "severity": "high",
                    "detail": detail,
                    "location": file_path,
                }
            ],
            "coverage_gaps": [],
            "detail": detail,
        }
    detail = "OpenXML schema validation passed"
    if isinstance(data, dict):
        detail = str(data.get("summary") or data.get("detail") or detail)
    return {
        "status": "PASSED",
        "passed": True,
        "issues": [],
        "coverage_gaps": [],
        "detail": detail,
    }


__all__ = [
    "DEFAULT_TIMEOUT",
    "MIN_VERSION",
    "VERIFIED_VERSION",
    "OfficecliError",
    "OfficecliRuntime",
    "OfficecliUnavailable",
    "OfficecliVersionError",
    "UnsupportedLocation",
    "build_set_command",
    "build_story_map",
    "find_binary",
    "get_runtime",
    "is_available",
    "location_to_path",
    "parse_version",
    "validation_report",
]
