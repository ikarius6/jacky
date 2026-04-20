# Routines

Routines let your pet fetch data from APIs, parse responses, evaluate conditions, and deliver results — all defined in a simple JSON file. No code required.

## Quick start

1. Create a `.json` file inside the `routines/` folder (next to `config.json`).
2. Restart the pet **or** open Settings and click Save to trigger a config reload.
3. Your routine will appear in the right-click context menu under **📋 Rutinas**.

> **Tip:** The included `routines/example_weather.json.disabled` is a working weather routine. Rename it to `example_weather.json` to try it out.

---

## Routine types

| Type | `schedule` | How it runs |
|---|---|---|
| **Manual** | `null` or omitted | Triggered by the user: keyword match, LLM intent, or context menu click. |
| **Automatic** | `{ "interval": <seconds> }` | Runs on a repeating timer. Shown as read-only in the context menu. |

---

## JSON schema

```jsonc
{
  "id":          "unique_id",           // Required. Unique identifier.
  "title":       "My Routine",          // Required. Display name in menus.
  "description": "What this does",      // Optional.
  "enabled":     true,                  // Optional (default true). Set false to disable without deleting.
  "schedule":    null,                  // null = manual. { "interval": 300 } = every 5 min.
  "triggers":    ["keyword1", "kw2"],   // Keywords that activate this routine from user input.
  "variables":   { "city": "Tokyo" },   // Predefined variables available in all steps/actions.
  "steps":       [ /* ... */ ],         // Sequential workflow steps (see below).
  "logic":       [ /* ... */ ],         // Conditional branching (see below).
  "actions":     { /* ... */ }          // Named final actions (see below).
}
```

### Required fields

Only `id` and `title` are required. Everything else is optional and has sensible defaults.

---

## Variables

Variables are the glue between steps. They live in a shared **context** dictionary that every step can read from and write to.

### Syntax

Use `{{variable_name}}` anywhere in string fields — URLs, headers, params, body values, queries, action messages, and LLM prompts. They are replaced at runtime with the current value from context.

### Built-in variables

These are always available, in addition to anything you define in `"variables"`:

| Variable | Value |
|---|---|
| `{{timestamp}}` | Current time in ISO format (`2024-01-15T14:30:00`) |
| `{{routine_id}}` | The routine's `id` |
| `{{routine_title}}` | The routine's `title` |

### Predefined variables

Use the top-level `"variables"` object to set defaults:

```json
"variables": {
  "city": "Queretaro",
  "api_key": "abc123"
}
```

These are loaded into context before any step runs and can be referenced as `{{city}}`, `{{api_key}}`, etc.

---

## Steps

Steps run **sequentially**, top to bottom. Each step is either a `request` (HTTP call) or a `parse` (extract data from text). If any step fails, the routine aborts and logs the error — the pet never crashes.

### `request` — HTTP call

```json
{
  "id": "fetch_data",
  "type": "request",
  "method": "GET",
  "url": "https://api.example.com/data?q={{query}}",
  "headers": {
    "Authorization": "Bearer {{api_key}}",
    "Accept": "application/json"
  },
  "params": {
    "lang": "es"
  },
  "body": null,
  "timeout": 10,
  "output_var": "raw_response"
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `id` | string | — | Unique step identifier (for logging). |
| `type` | string | — | Must be `"request"`. |
| `method` | string | `"GET"` | HTTP method: `GET`, `POST`, `PUT`, `DELETE`, etc. |
| `url` | string | — | Full URL. Supports `{{variables}}`. |
| `headers` | object | `{}` | HTTP headers. Values support `{{variables}}`. |
| `params` | object | `{}` | URL query parameters. Appended to the URL. |
| `body` | object | `null` | JSON body (for POST/PUT/DELETE). Sent as `Content-Type: application/json`. |
| `timeout` | integer | `10` | Request timeout in seconds. |
| `output_var` | string | `""` | Variable name to store the **raw response body** text. |

### `parse` — Extract data

```json
{
  "id": "get_temperature",
  "type": "parse",
  "input": "{{raw_response}}",
  "parser": "json",
  "query": "main.temp",
  "output_var": "temperature"
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `id` | string | — | Unique step identifier. |
| `type` | string | — | Must be `"parse"`. |
| `input` | string | — | The text to parse. Usually `{{some_var}}` from a previous step. |
| `parser` | string | — | Parser type: `"json"`, `"xml"`, or `"regex"`. |
| `query` | string | — | Parser-specific query (see below). |
| `output_var` | string | `""` | Variable name to store the extracted value. |

#### JSON parser

Uses **dot-path** navigation. Array indices are integers.

```
"query": "data.items.0.name"
```

Equivalent to: `response["data"]["items"][0]["name"]`

#### XML parser

Uses **tag path** compatible with `ElementTree.find()`.

```
"query": "channel/item/title"
```

If the root element matches the first segment of your query, it is handled automatically.

#### Regex parser

Uses a **regular expression** pattern. Returns the first captured group if present, otherwise the full match.

```
"query": "Price: (\\d+\\.\\d+)"
```

Would extract `"29.99"` from the text `"Price: 29.99 USD"`.

> **Note:** Backslashes in JSON must be escaped (`\\d` instead of `\d`).

---

## Logic

The `logic` block decides **which action** to run based on the current variable values. It is an array of rules evaluated in order — the first match wins.

```json
"logic": [
  {
    "if": { "var": "temp_c", "op": ">", "val": 35 },
    "then": "action_extreme",
    "else": null
  },
  {
    "if": { "var": "temp_c", "op": ">", "val": 30 },
    "then": "action_hot",
    "else": "action_normal"
  }
]
```

### Condition format

A leaf condition compares a variable against a value:

```json
{ "var": "temperature", "op": ">=", "val": 30 }
```

### Supported operators

| Operator | Description | Example |
|---|---|---|
| `>` | Greater than | `"op": ">"` |
| `<` | Less than | `"op": "<"` |
| `>=` | Greater or equal | `"op": ">="` |
| `<=` | Less or equal | `"op": "<="` |
| `==` | Equal | `"op": "=="` |
| `!=` | Not equal | `"op": "!="` |
| `contains` | String contains substring | `"op": "contains"` |

> Numeric comparisons (`>`, `<`, `>=`, `<=`) automatically convert string values to numbers when possible.

### Nesting with AND / OR

Combine multiple conditions using `"and"` or `"or"`:

```json
{
  "if": {
    "and": [
      { "var": "temp_c", "op": ">", "val": 30 },
      { "var": "humidity", "op": ">", "val": 80 }
    ]
  },
  "then": "action_hot_humid",
  "else": "action_default"
}
```

```json
{
  "if": {
    "or": [
      { "var": "status", "op": "==", "val": "rain" },
      { "var": "status", "op": "==", "val": "storm" }
    ]
  },
  "then": "action_rain",
  "else": "action_clear"
}
```

You can nest `"and"` inside `"or"` and vice versa to any depth.

### No logic block

If you omit `"logic"` entirely (or leave it empty), the engine will use the action named `"default"`. If there is no `"default"`, it uses the first action defined.

---

## Actions

Actions are the **final output** of a routine — what the pet does with the result. They are defined as named objects so the logic block can select between them.

```json
"actions": {
  "action_name": {
    "type": "say",
    "llm": "Prompt for the LLM with {{variables}}",
    "nollm": "Fallback text when LLM is disabled: {{temperature}}°C",
    "message": "Used by log and notification types"
  }
}
```

### Action types

#### `say` — Pet speaks the result

The pet says the result via speech bubble (and optionally TTS).

| Field | Used when | Description |
|---|---|---|
| `llm` | LLM is enabled | Sent as a prompt to the LLM. The LLM generates a natural response. |
| `nollm` | LLM is disabled | Displayed directly as-is. Also used as fallback if `llm` is empty. |

**Multilingual Support:** All text fields in an action (`llm`, `nollm`, and `message`) can be a simple string or a dictionary of language codes (like `"en"`, `"es"`). The engine will automatically pick the right translation based on Jacky's current language (falling back to `"en"` or the first available option if a translation is missing).

Both fields also support `{{variables}}`.

```json
{
  "type": "say",
  "llm": "The current temp is {{temp_c}}°C. Make a fun comment about it.",
  "nollm": {
    "es": "🌡️ Temperatura: {{temp_c}}°C",
    "en": "🌡️ Temperature: {{temp_c}}°C"
  }
}
```

#### `notification` — System tray notification

Shows an OS notification via the system tray.

```json
{
  "type": "notification",
  "message": "🌧️ It's going to rain in {{city}}!"
}
```

#### `log` — Silent log entry

Writes to the application log without any visible output. Useful for automatic routines that should run silently.

```json
{
  "type": "log",
  "message": "Routine check: {{status}} at {{timestamp}}"
}
```

---

## Triggering manual routines

Manual routines (no `schedule`) can be triggered in three ways:

### 1. Context menu

Right-click the pet → **📋 Rutinas** → click the routine. Manual routines show a ▶ icon and are clickable. Automatic routines are shown with a ⏱ icon and their interval for reference.

### 2. Keyword matching

If the user's question contains any word from the `"triggers"` array, the routine runs immediately — no LLM call needed. This is the fastest path.

```json
"triggers": ["clima", "weather", "tiempo"]
```

Asking the pet *"¿cómo está el clima?"* would match `"clima"` and run the routine.

### 3. LLM intent classification

If keyword matching doesn't fire, the question goes to the LLM for intent classification. The LLM receives a list of all available manual routines (IDs, titles, and triggers) and can decide to run one if it matches the user's intent.

This means the user doesn't need to use the exact trigger words — the LLM can understand paraphrased requests.

---

## Automatic routines

Set a schedule to have the routine run on a repeating timer:

```json
"schedule": {
  "interval": 1800
}
```

This runs every 1800 seconds (30 minutes). The timer starts when the pet launches.

- Automatic routines **pause** during Gamer Mode and **resume** when it's deactivated.
- They are shown in the context menu as read-only status items.
- A config reload (saving settings) re-reads all routine files and restarts timers.

---

## Error handling

- If an HTTP request fails (timeout, non-2xx status, network error), the routine **aborts** and logs the error.
- If a parse step fails (invalid JSON, missing key, regex no match), the routine **aborts** and logs the error.
- **The pet never crashes** — every routine runs inside a try/except. A failed routine simply stops and the pet continues normally.
- Check the debug log for detailed step-by-step output (enable debug logging in Settings).

---

## Complete example

A routine that checks Bitcoin price and reacts based on the value:

```json
{
  "id": "btc_price",
  "title": "Bitcoin Price",
  "description": "Checks the current BTC price from CoinGecko",
  "schedule": null,
  "triggers": ["bitcoin", "btc", "crypto"],
  "enabled": true,
  "steps": [
    {
      "id": "fetch_price",
      "type": "request",
      "method": "GET",
      "url": "https://api.coingecko.com/api/v3/simple/price",
      "params": {
        "ids": "bitcoin",
        "vs_currencies": "usd"
      },
      "timeout": 10,
      "output_var": "raw_price"
    },
    {
      "id": "parse_price",
      "type": "parse",
      "input": "{{raw_price}}",
      "parser": "json",
      "query": "bitcoin.usd",
      "output_var": "btc_usd"
    }
  ],
  "logic": [
    {
      "if": { "var": "btc_usd", "op": ">", "val": 100000 },
      "then": "moon",
      "else": "normal"
    }
  ],
  "actions": {
    "moon": {
      "type": "say",
      "llm": "Bitcoin is at ${{btc_usd}} USD! It's above 100k! React excited!",
      "nollm": "🚀 BTC: ${{btc_usd}} USD — To the moon!"
    },
    "normal": {
      "type": "say",
      "llm": "Bitcoin is currently at ${{btc_usd}} USD. Make a brief comment.",
      "nollm": "₿ BTC: ${{btc_usd}} USD"
    }
  },
  "variables": {}
}
```

---

## Tips

- **Start simple.** A single request step + a single `"default"` action is enough for a working routine.
- **Test your API first.** Try the URL in a browser or curl before putting it in a routine.
- **Use `output_var`** on every step — if you don't store the result, you can't use it later.
- **Disable without deleting.** Set `"enabled": false` or rename the file to `.json.disabled`.
- **Duplicate IDs are skipped.** If two files define the same `id`, only the first one (alphabetically by filename) is loaded.
- **No new dependencies.** Routines use only `requests` (already installed) and Python standard library modules.
