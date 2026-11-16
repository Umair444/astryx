# Harness and Keys (owner 11-16)

## Intent
One place in the Agents tab where the owner adds what agents can run on, and connects any agent to any of it. The
owner's words: "Harness in astryx is just cli; like claude code, codex … if a person wants to use login with claude
code it will be a key; he can also use some api like deepseek with claude code, it will be a key too … think like an
OpenRouter developer … it is just the start … base should be perfect."

## The model (three nouns)
- **Harness**: a CLI an agent's body runs in (Claude Code; later Codex, Gemini CLI). A row of
  `src/astryx/data/cli_adapters.json`: how to launch it, which API formats it `speaks`, which provider logins it takes,
  and how a key plugs into it (`connect`: the env vars it reads).
- **Provider**: a row of `src/astryx/data/providers.json`: who serves the tokens (Anthropic, DeepSeek, OpenRouter,
  OpenAI, Google, a custom endpoint), whether you sign in (`login`) or paste a `key`, the formats it speaks at which
  endpoint, its key's shape, where to get one, how to check one, and its models (with the default per tier).
- **Key**: a provider + a secret, named by the owner. credentials.json holds the name and provider; the value lives
  only in .env under ASTRYX_CRED_<SLUG>. A Claude Code login is a key; a DeepSeek API key is a key.
- **Connection**: agent → (harness, key, model). runtime.json `{harness, credential, model, effort}`; the entry `*` is
  "everyone else" (the org default). No key = the org's own login (CLAUDE_CODE_OAUTH_TOKEN) or the machine's.

Fit is computed from the two tables, never written in the UI: a key fits a harness when its provider is one of the
harness's logins, or they share a format. A new provider is one catalog row; a new harness is one adapter row.

## Approaches
- A. Restyle the current screen. Rejected: it keeps three overlapping editors.
- **B. One catalog + keys + connections (chosen by the owner).**
- C. Dynamic routing now. Premature: B's connection is the seam a router fills later (a connection naming a list).

## Rules kept
- Values never leave .env (no response, page, step or log); the server derives the env key; one .env writer.
- A login is proved before it is stored (the sign-in flow is kept).
- An API key is metered spend: it can be stored and checked now. CONNECTING one stays refused until its daily cap is
  enforced (local.md Economy; medic 12468). Next: a metering gateway, one local proxy that counts tokens per key,
  refuses at the cap, and is where routing and fallback land.
- A harness without a launcher is listed as coming: its keys can be stored, not connected.

## UI (Agents tab, owner only)
Section "Harness and Keys":
- harness chips (ready / coming);
- the keys: provider mark, name, provider, which harness it fits, its status (signed in / checked / waiting on the
  spend cap), live energy for a login, the faces of the agents on it;
- "+ Add a key": provider tiles (sign in: Claude Code; API keys: Anthropic, DeepSeek, OpenRouter, OpenAI, Gemini,
  custom), then one short form;
- connections: "Everyone else" first, then each agent, each with one picker (harness → a key that fits → model), and
  "Restart now" once it changed.

The agent drawer's Runtime tab shows the same picker. The raw base_url / token_env fields leave the UI (runtime_env
still honours old entries).
