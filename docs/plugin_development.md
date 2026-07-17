# Plugin Development

The workflow discovers installed Python plugins through standard package entry
points. Plugins run in the Workbench process and are trusted code; install only
packages you trust.

## Inspect Installed Plugins

```bash
literature-review plugins
literature-review doctor
```

Restart the Workbench after installing or removing a plugin. Provider choices
in the new-run dialog are generated from the active registry. Built-in
providers are selected by default; third-party providers require an explicit
user selection for each new run.

## Provider Plugin

A provider entry point name is its stable provider ID. IDs must begin with a
lowercase letter and contain only lowercase letters, digits, and underscores.

```toml
[project.entry-points."literature_review.providers"]
crossref = "my_review_plugin:build_crossref"
```

```python
from src.literature_review.plugins import ProviderContext


class CrossrefProvider:
    provider_id = "crossref"
    artifact_extension = "json"

    def __init__(self, context: ProviderContext) -> None:
        self.transport = context.transport
        self.cache = context.cache
        self.environment = context.environment

    def search(self, query):
        # Return ProviderSearchResult with normalized ProviderPaper records.
        ...

    def fetch_details(self, provider_id):
        # Return one normalized ProviderPaper.
        ...


def build_crossref(context: ProviderContext):
    return CrossrefProvider(context)


build_crossref.plugin_label = "Crossref"
```

Provider results must use the existing `ProviderPaper` and
`ProviderSearchResult` contracts. Every paper needs a stable DOI, arXiv ID, or
Semantic Scholar ID. The registry rejects duplicate IDs, mismatched
`provider_id` values, missing methods, and unsafe artifact extensions.

## Agent Plugin

Agent plugins replace one named role through the
`literature_review.agents` entry-point group:

```toml
[project.entry-points."literature_review.agents"]
writer = "my_review_plugin:build_writer"
```

```python
class CustomWriter:
    def __init__(self, runtime_config, api_client):
        self.runtime_config = runtime_config
        self.api_client = api_client

    def run(self, search_report, review_feedback=None):
        # Return the complete survey draft as Markdown.
        ...


def build_writer(runtime_config, api_client):
    return CustomWriter(runtime_config, api_client)
```

Replaceable roles:

- `writer`
- `domain_expert`
- `structure_mentor`
- `review_synthesizer`
- `polish`
- `evaluation_reflection`

Protected roles cannot be replaced:

- `search`
- `reviewer`
- `final_verification`

The protected roles preserve corpus normalization, citation auditing, and the
post-polish verification gate. Replaceable agents must keep their role's
method contract. Only one installed plugin may provide a role; conflicts fail
fast instead of depending on package discovery order.

## Lifecycle And Reproducibility

Each run stores its selected provider plugins and active Agent manifest in its
runtime configuration artifact, including installed distribution names and versions.
A plugin version change therefore invalidates affected checkpoint fingerprints.
Resuming a discovery run requires its selected provider plugin to remain
installed. If it is unavailable, resume fails with a clear
`plugin_configuration_error` instead of silently using another source.

Plugins cannot disable human corpus approval, the citation auditor, final
verification, checkpoint hashing, or the persistent quality gate. API-backed
plugins should return the same structured artifacts as deterministic agents
and must not store credentials in artifacts or public errors.

The bundled protected review rubric is currently aligned with the
memory-augmented LLM agent profile. Replacing Writer alone does not make the
whole pipeline domain-general because protected Citation Auditor and Final
Verification contracts still apply. Cross-domain support should use a future
versioned ReviewProfile rather than weakening or bypassing protected roles.
