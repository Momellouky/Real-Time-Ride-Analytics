import httpx


class PinotQueryError(RuntimeError):
    """A failed or incomplete Broker response; never represents an empty table."""


class PinotClient:
    def __init__(self, broker_url: str, timeout: float = 3.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self._url = f"{broker_url.rstrip('/')}/query/sql"
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def close(self) -> None:
        await self._client.aclose()

    async def query(self, sql: str, *, options: dict[str, str] | None = None) -> list[dict]:
        try:
            body = {'sql': sql}
            if options:
                body['queryOptions'] = ';'.join(f'{key}={value}' for key, value in options.items())
            response = await self._client.post(self._url, json=body)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Broker response must be an object")
            if payload.get("exceptions") or payload.get("partialResult"):
                raise ValueError("Broker returned query exceptions or partial results")
            if any(payload.get(flag) for flag in ('numGroupsLimitReached', 'groupsTrimmed',
                                                  'maxRowsInJoinReached', 'maxRowsInWindowReached')):
                raise ValueError('Broker returned truncated analytical results')
            queried = payload.get("numServersQueried")
            responded = payload.get("numServersResponded")
            if queried is not None and responded is not None and queried != responded:
                raise ValueError("Some Pinot servers did not respond")
            table = payload["resultTable"]
            columns = table["dataSchema"]["columnNames"]
            rows = table["rows"]
            if (not isinstance(columns, list) or not columns
                    or not all(isinstance(c, str) for c in columns)
                    or len(set(columns)) != len(columns)
                    or not isinstance(rows, list)):
                raise ValueError("Invalid result table")
            if not all(isinstance(row, list) for row in rows):
                raise ValueError("Invalid result rows")
            return [dict(zip(columns, row, strict=True)) for row in rows]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise PinotQueryError("Unable to retrieve complete results from Pinot") from exc
