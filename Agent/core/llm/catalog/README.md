# Bundled model metadata

`model_prices_and_context_window.json` is an unmodified snapshot of the public
[LiteLLM catalog](https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json).
The source URL, retrieval timestamp and SHA256 are recorded in `snapshot.json`.
The upstream license is included in `LICENSE.litellm.txt`.

This is data only. Loading it does not install or import LiteLLM, contact its
services, change the model list, select an endpoint, or enable protocol bridging.
This release updates the snapshot with the application package. There is no
automatic download during startup, settings reads, or model requests.

## Matching and overrides

- Match the configured provider and exact model ID. The application channels
  `glm` and `bailian` map to upstream identifiers `zai` and `dashscope`.
- Unknown/private gateway names are not guessed. A model entry in
  `models_config.json` may set `metadata_key` to an exact catalog key, e.g.
  `{"id": "private-alias", "metadata_key": "deepseek/deepseek-chat"}`.
  This mapping never changes the model ID sent to the API.
- Explicit provider `limits`/`capabilities` override catalog fields; explicit
  model settings override provider fields. Missing fields remain unknown.
- Input/output limits retain their source meanings. Legacy `max_tokens` is
  not a context window; input and output limits are not added together. The
  catalog's `max_input_tokens` feeds existing input budget checks and
  `max_output_tokens` feeds existing output caps. No fixed window is invented.
- Prices are retained in the raw snapshot but are not used for billing. A
  model catalog is not evidence of account access or a gateway's actual limits.

## Future user-managed updates

`DELTACONVERGE_MODEL_METADATA_PATH` can point to a user-managed JSON file in the
same upstream format. It replaces the bundled catalog; an unreadable/invalid
file falls back to the bundled copy. Restart after changing the file (the
catalog is cached in memory). The application does not write into the package.
Automatic fetching into a per-user directory and settings controls are deferred.
