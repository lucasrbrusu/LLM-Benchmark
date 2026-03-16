import os
import time

import httpx


class ProviderError(RuntimeError):
    pass


def create_client(model_config, timeout_s):
    provider = model_config["provider"]

    if provider == "openai":
        return OpenAIChatClient(
            model_config,
            timeout_s,
            base_url="https://api.openai.com/v1",
            api_key_required=True,
        )
    if provider == "openai_compatible":
        return OpenAIChatClient(
            model_config,
            timeout_s,
            base_url=model_config["base_url"],
            api_key_required=False,
        )
    if provider == "anthropic":
        return AnthropicChatClient(model_config, timeout_s)
    if provider == "gemini":
        return GeminiChatClient(model_config, timeout_s)
    if provider == "github_models":
        return GitHubModelsChatClient(model_config, timeout_s)

    raise ProviderError(f"Unsupported provider: {provider}")


class BaseChatClient:
    def __init__(self, model_config, timeout_s):
        self.model_config = model_config
        self.model_name = model_config["model"]
        self.timeout_s = timeout_s
        self.client = httpx.Client(timeout=timeout_s)

    def close(self):
        self.client.close()

    def generate(self, system_prompt, user_prompt, temperature, max_tokens):
        raise NotImplementedError


class OpenAIChatClient(BaseChatClient):
    def __init__(self, model_config, timeout_s, base_url, api_key_required):
        super().__init__(model_config, timeout_s)
        self.base_url = base_url.rstrip("/")
        self.api_key_required = api_key_required

    def generate(self, system_prompt, user_prompt, temperature, max_tokens):
        api_key = read_api_key(
            self.model_config,
            required=self.api_key_required,
        )
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        if self.api_key_required:
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["max_tokens"] = max_tokens

        url = f"{self.base_url}/chat/completions"
        return post_and_parse_openai_style(self.client, url, headers, payload)


class GitHubModelsChatClient(BaseChatClient):
    def generate(self, system_prompt, user_prompt, temperature, max_tokens):
        api_key = read_api_key(self.model_config, required=True)
        api_version = self.model_config.get("api_version", "2022-11-28")
        org_name = self.model_config.get("organization")

        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {api_key}",
            "X-GitHub-Api-Version": api_version,
            "Content-Type": "application/json",
        }

        if org_name:
            url = f"https://models.github.ai/orgs/{org_name}/inference/chat/completions"
        else:
            url = "https://models.github.ai/inference/chat/completions"

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        return post_and_parse_openai_style(self.client, url, headers, payload)


class AnthropicChatClient(BaseChatClient):
    def generate(self, system_prompt, user_prompt, temperature, max_tokens):
        api_key = read_api_key(self.model_config, required=True)
        headers = {
            "x-api-key": api_key,
            "anthropic-version": self.model_config.get(
                "anthropic_version", "2023-06-01"
            ),
            "content-type": "application/json",
        }
        payload = {
            "model": self.model_name,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        start = time.perf_counter()
        response = self.client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
        )
        data = parse_json_response(response)
        latency_ms = (time.perf_counter() - start) * 1000.0

        text_parts = []
        for item in data.get("content", []):
            if item.get("type") == "text":
                text_parts.append(item.get("text", ""))

        usage = data.get("usage") or {}
        return {
            "text": "".join(text_parts).strip(),
            "latency_ms": latency_ms,
            "output_tokens": usage.get("output_tokens"),
        }


class GeminiChatClient(BaseChatClient):
    def generate(self, system_prompt, user_prompt, temperature, max_tokens):
        api_key = read_api_key(self.model_config, required=True)
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model_name}:generateContent?key={api_key}"
        )
        headers = {"Content-Type": "application/json"}
        payload = {
            "system_instruction": {
                "parts": [{"text": system_prompt}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        start = time.perf_counter()
        response = self.client.post(url, headers=headers, json=payload)
        data = parse_json_response(response)
        latency_ms = (time.perf_counter() - start) * 1000.0

        candidates = data.get("candidates") or []
        parts = []
        if candidates:
            content = candidates[0].get("content") or {}
            for item in content.get("parts", []):
                if "text" in item:
                    parts.append(item["text"])

        usage = data.get("usageMetadata") or {}
        return {
            "text": "".join(parts).strip(),
            "latency_ms": latency_ms,
            "output_tokens": usage.get("candidatesTokenCount"),
        }


def post_and_parse_openai_style(client, url, headers, payload):
    start = time.perf_counter()
    response = client.post(url, headers=headers, json=payload)
    data = parse_json_response(response)
    latency_ms = (time.perf_counter() - start) * 1000.0

    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content", "")
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        content = "".join(text_parts)

    usage = data.get("usage") or {}
    output_tokens = usage.get("completion_tokens") or usage.get("output_tokens")

    return {
        "text": str(content).strip(),
        "latency_ms": latency_ms,
        "output_tokens": output_tokens,
    }


def parse_json_response(response):
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = response.text.strip()
        if len(body) > 500:
            body = body[:500] + "..."
        raise ProviderError(f"{exc}. Response body: {body}") from exc

    try:
        return response.json()
    except ValueError as exc:
        body = response.text.strip()
        if len(body) > 500:
            body = body[:500] + "..."
        raise ProviderError(f"Provider returned invalid JSON: {body}") from exc


def read_api_key(model_config, required):
    env_name = model_config.get("api_key_env")
    if not env_name:
        if required:
            raise ProviderError(
                f"Model '{model_config['id']}' is missing api_key_env in config.yaml"
            )
        return None

    value = os.getenv(env_name)
    if value:
        return value

    if required:
        raise ProviderError(
            f"Environment variable '{env_name}' is not set for model '{model_config['id']}'"
        )
    return None
