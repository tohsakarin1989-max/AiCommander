"""Graph identity contracts without database or application configuration imports."""
from dataclasses import dataclass


class RoadNetworkUnavailable(PermissionError):
    def __init__(self, code='road_network_unavailable'):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RoadNetworkBinding:
    network_id: str
    group_id: int
    policy_revision: int
    graph_sha256: str
    artifact_key: str
    engine_version: str
    cache_key: str
