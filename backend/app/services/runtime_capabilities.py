"""One switch contract shared by API, Worker and Beat. No model activation."""


def query_creation_enabled(config):
    explicit = getattr(config, 'ENABLE_INTELLIGENT_QUERY', None)
    if explicit is not None:
        return explicit
    # Unconfigured upgrades preserve the previous deployment's disabled state.
    return bool(config.ENABLE_AGENT_LAB and config.AGENT_MODE != 'off')
