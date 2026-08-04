"""
nicochannel_auth.py — Firefox localStorage JWT extraction for nicochannel.jp

Adapted from temp/firefox_utils.py. Extracts the JWT auth token from Firefox's
localStorage database, which is needed because nicochannel.jp migrated from
cookie-based auth to localStorage-based JWT auth.

The JWT is passed to yt-dlp via --extractor-args, and the yt-dlp plugin
(niconicochannelplus) handles token refresh internally via the cookie file.
"""

import contextlib
import json
import os
import re
import tempfile
import urllib.parse
from typing import Callable


class NicochannelAuthService:
    """Extracts nicochannel JWT auth tokens from Firefox localStorage.

    The token is cached in-memory for the session lifetime to avoid repeated
    reads of the Firefox sqlite database (which is expensive and may be locked).

    Usage:
        auth = NicochannelAuthService(log=my_log_function)
        token = auth.get_auth_token()  # returns JWT str or None
    """

    _NICOCHANNEL_URL = "https://nicochannel.jp"

    def __init__(self, log: Callable[[str, str], None]):
        self._log = log
        self._cached_token: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_auth_token(
        self,
        profile: str | None = None,
        container: str | None = None,
    ) -> str | None:
        """Extract the JWT auth token for nicochannel.jp from Firefox localStorage.

        Returns the JWT string on success, or None if extraction fails.
        The result is cached — subsequent calls return the cached token
        without re-reading the Firefox database.
        """
        if self._cached_token is not None:
            return self._cached_token

        try:
            # Lazy-import yt-dlp internals (private API — may break across versions)
            from yt_dlp.cookies import (
                _firefox_browser_dirs,
                _firefox_cookie_dbs,
                _is_path,
                _newest,
                _open_database_copy,
            )
            from yt_dlp.utils import try_call
        except ImportError as exc:
            self._log(f"[NicoChannel] yt-dlp 模块导入失败: {exc}", "warn")
            return None

        try:
            import cramjam
        except ImportError:
            self._log(
                "[NicoChannel] cramjam 未安装，无法解压 Firefox localStorage 数据",
                "warn",
            )
            return None

        import logging

        logger = logging.getLogger("nicochannel_auth")
        logger.setLevel(logging.DEBUG)

        try:
            # Step 1: locate Firefox profile and resolve container
            profile_path, container_id = self._locate_ff_profile(
                profile,
                container,
                _firefox_browser_dirs,
                _is_path,
                _firefox_cookie_dbs,
                _newest,
                try_call,
            )
            self._log(
                f'[NicoChannel] Firefox 配置目录: "{profile_path}"', "info"
            )

            # Step 2: extract localStorage items for nicochannel.jp
            items = self._extract_localstorage(
                profile_path,
                container_id,
                self._NICOCHANNEL_URL,
                _open_database_copy,
                cramjam,
                logger,
            )

            # Step 3: find the JWT token
            token = self._find_jwt(items)
            if token:
                self._cached_token = token
                self._log("[NicoChannel] JWT 令牌已从 Firefox 提取", "success")
            else:
                self._log(
                    "[NicoChannel] 未在 Firefox localStorage 中找到有效令牌，"
                    "请确保已在 Firefox 中登录 nicochannel.jp",
                    "warn",
                )

            return token

        except FileNotFoundError as exc:
            self._log(f"[NicoChannel] Firefox 配置未找到: {exc}", "warn")
            return None
        except ValueError as exc:
            self._log(f"[NicoChannel] Firefox 容器配置错误: {exc}", "warn")
            return None
        except Exception as exc:
            self._log(f"[NicoChannel] 提取 JWT 失败: {exc}", "warn")
            return None

    # ------------------------------------------------------------------
    # Firefox profile location (adapted from firefox_utils._locate_ff_path)
    # ------------------------------------------------------------------

    @staticmethod
    def _locate_ff_profile(
        profile,
        container,
        browser_dirs,
        is_path,
        cookie_dbs,
        newest,
        try_call,
    ) -> tuple[str, int | None]:
        """Locate the Firefox profile directory and resolve container ID.

        Returns (profile_path, container_id).  container_id is None when
        no container filtering is needed.
        """
        if profile is None:
            search_roots = list(browser_dirs())
        elif is_path(profile):
            search_roots = [profile]
        else:
            search_roots = [
                os.path.join(path, profile) for path in browser_dirs()
            ]
        search_root = ", ".join(map(repr, search_roots))

        cookie_database_path = newest(cookie_dbs(search_roots))
        if cookie_database_path is None:
            raise FileNotFoundError(
                f"could not find firefox profile in {search_root}"
            )

        profile_path = os.path.dirname(cookie_database_path)

        container_id: int | None = None
        if container not in (None, "none"):
            containers_path = os.path.join(profile_path, "containers.json")
            if not os.path.isfile(containers_path) or not os.access(
                containers_path, os.R_OK
            ):
                raise FileNotFoundError(
                    f"could not read containers.json in {search_root}"
                )
            with open(containers_path, encoding="utf8") as f:
                identities = json.load(f).get("identities", [])

            container_id = next(
                (
                    ctx.get("userContextId")
                    for ctx in identities
                    if container
                    in (
                        ctx.get("name"),
                        try_call(
                            lambda c=ctx: re.fullmatch(
                                r"userContext([^\.]+)\.label",
                                c["l10nID"],
                            ).group()
                        ),
                        try_call(
                            lambda c=ctx: re.fullmatch(
                                r"user-context-(\w+)", c["l10nId"]
                            ).group()
                        ),
                    )
                ),
                None,
            )
            if not isinstance(container_id, int):
                raise ValueError(
                    f'could not find firefox container "{container}" '
                    "in containers.json"
                )

        return profile_path, container_id

    # ------------------------------------------------------------------
    # localStorage extraction (adapted from firefox_utils)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_localstorage(
        profile_path: str,
        container_id: int | None,
        url: str,
        open_database_copy,
        cramjam,
        logger,
    ) -> dict[str, str]:
        """Extract all localStorage key-value pairs for the given URL.

        Reads the Firefox localStorage sqlite database, decompresses values
        that use Snappy compression, and returns them as a dict.
        """
        MAX_SUPPORTED_DB_SCHEMA_VERSION = 80

        parsed = urllib.parse.urlparse(url)
        scope = f"{parsed.scheme}+++{parsed.netloc}".replace(":", "+")
        if isinstance(container_id, int):
            scope = f"{scope}^userContextId={container_id}"

        db_file = os.path.join(
            profile_path, "storage", "default", scope, "ls", "data.sqlite"
        )

        logger.debug(
            f'Extracting localStorage from: "{profile_path}" for scope "{scope}"'
        )

        items: dict[str, str] = {}
        if not os.path.exists(db_file):
            logger.warning(f"localStorage does not exist for {url}")
            return items

        with tempfile.TemporaryDirectory() as tmpdir:
            cursor = open_database_copy(db_file, tmpdir)
            with contextlib.closing(cursor.connection):
                db_schema_version = cursor.execute(
                    "PRAGMA user_version;"
                ).fetchone()[0]
                if db_schema_version > MAX_SUPPORTED_DB_SCHEMA_VERSION:
                    logger.warning(
                        "Possibly unsupported firefox localStorage "
                        f"database version: {db_schema_version}"
                    )
                else:
                    logger.debug(
                        "Firefox localStorage database version: "
                        f"{db_schema_version}"
                    )

                cursor.execute(
                    "SELECT key, conversion_type, compression_type, value "
                    "FROM data"
                )
                for key, conversion, compression, value_bytes in cursor.fetchall():
                    assert isinstance(key, str) and isinstance(value_bytes, bytes)

                    if compression == 1:
                        value_bytes = bytes(
                            cramjam.snappy.decompress_raw(value_bytes)
                        )
                    value = value_bytes.decode(
                        "utf-8" if conversion == 1 else "utf-16"
                    )
                    items[key] = value

        return items

    # ------------------------------------------------------------------
    # JWT extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _find_jwt(items: dict[str, str]) -> str | None:
        """Find the JWT auth token in nicochannel's localStorage items.

        nicochannel uses Auth0 for authentication.  The JWT can appear in
        several structures depending on the localStorage key:

        1. Auth0 cache (most common):
           ``{"body": {"access_token": "<JWT>", "scope": "...", ...}}``
           → JWT is ``parsed["body"]["access_token"]``

        2. Legacy flat format:
           ``{"body": "<JWT>"}``
           → JWT is ``parsed["body"]`` directly

        3. Persisted auth state:
           ``{"totalUserInformation": "{\\"root\\":{\\"userInformation\\":{\\"accessToken\\":\\"<JWT>\\"}}}"}``
           → JWT is nested inside a string-encoded JSON
        """
        for value in items.values():
            if "access_token" not in value and "accessToken" not in value:
                continue
            try:
                parsed = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                continue

            # Pattern 1: Auth0 cache — body is a dict with access_token
            body = parsed.get("body")
            if isinstance(body, dict):
                token = body.get("access_token")
                if isinstance(token, str) and token.count(".") == 2:
                    return token

            # Pattern 2: Legacy — body is the JWT string directly
            if isinstance(body, str) and body.count(".") == 2:
                return body

            # Pattern 3: Persisted user info — nested string-encoded JSON
            total_info = parsed.get("totalUserInformation")
            if isinstance(total_info, str):
                try:
                    nested = json.loads(total_info)
                    token = (
                        nested.get("root", {})
                        .get("userInformation", {})
                        .get("accessToken")
                    )
                    if isinstance(token, str) and token.count(".") == 2:
                        return token
                except (json.JSONDecodeError, TypeError):
                    pass

        return None
