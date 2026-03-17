import os
import time

import httpx


class ProviderError(RuntimeError):
    pass


def create_client(model_config, timeout_s):
    provider = model_config["provider"]

    if provider == "openai":
        return OpenAIChatClient(
            model_config=model_config,
            timeout_s=timeout_s,
            base_url="https://api.openai.com/v1",
            api_key_required=True,
        )
    if provider == "openai_compatible":
        return OpenAIChatClient(
            model_config=model_config,
            timeout_s=timeout_s,
            base_url=model_config["base_url"],
            api_key_required=False,
        )
    if provider == "anthropic":
        return AnthropicChatClient(model_config, timeout_s)
    if provider == "gemini":
        return GeminiChatClient(model_config, timeout_s)
    if provider == "github_models":
        return GitHubModelsChatClient(model_config, timeout_s)
    if provider == "mock":
        return MockChatClient(model_config, timeout_s)

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
        return self.generate_messages(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def generate_messages(self, system_prompt, messages, temperature, max_tokens):
        raise NotImplementedError


class OpenAIChatClient(BaseChatClient):
    def __init__(self, model_config, timeout_s, base_url, api_key_required):
        super().__init__(model_config, timeout_s)
        self.base_url = base_url.rstrip("/")
        self.api_key_required = api_key_required

    def generate_messages(self, system_prompt, messages, temperature, max_tokens):
        api_key = read_api_key(self.model_config, required=self.api_key_required)

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": self.model_name,
            "messages": build_openai_messages(system_prompt, messages),
            "temperature": temperature,
        }
        if self.api_key_required:
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["max_tokens"] = max_tokens

        url = f"{self.base_url}/chat/completions"
        return post_and_parse_openai_style(self.client, url, headers, payload)


class GitHubModelsChatClient(BaseChatClient):
    def generate_messages(self, system_prompt, messages, temperature, max_tokens):
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
            "messages": build_openai_messages(system_prompt, messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        return post_and_parse_openai_style(self.client, url, headers, payload)


class AnthropicChatClient(BaseChatClient):
    def generate_messages(self, system_prompt, messages, temperature, max_tokens):
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
            "messages": build_simple_messages(messages),
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

        parts = []
        for item in data.get("content", []):
            if item.get("type") == "text":
                parts.append(item.get("text", ""))

        usage = data.get("usage") or {}
        return {
            "text": "".join(parts).strip(),
            "latency_ms": latency_ms,
            "output_tokens": usage.get("output_tokens"),
        }


class GeminiChatClient(BaseChatClient):
    def generate_messages(self, system_prompt, messages, temperature, max_tokens):
        api_key = read_api_key(self.model_config, required=True)
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model_name}:generateContent?key={api_key}"
        )

        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": build_gemini_messages(messages),
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        start = time.perf_counter()
        response = self.client.post(url, headers={"Content-Type": "application/json"}, json=payload)
        data = parse_json_response(response)
        latency_ms = (time.perf_counter() - start) * 1000.0

        text_parts = []
        candidates = data.get("candidates") or []
        if candidates:
            content = candidates[0].get("content") or {}
            for item in content.get("parts", []):
                if "text" in item:
                    text_parts.append(item["text"])

        usage = data.get("usageMetadata") or {}
        return {
            "text": "".join(text_parts).strip(),
            "latency_ms": latency_ms,
            "output_tokens": usage.get("candidatesTokenCount"),
        }


class MockChatClient(BaseChatClient):
    def generate_messages(self, system_prompt, messages, temperature, max_tokens):
        del system_prompt, temperature, max_tokens

        user_prompt = messages[-1]["content"]
        text = build_mock_response(user_prompt)
        return {
            "text": text,
            "latency_ms": 1.0,
            "output_tokens": len(text.split()),
        }


def build_openai_messages(system_prompt, messages):
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(build_simple_messages(messages))
    return full_messages


def build_simple_messages(messages):
    clean_messages = []
    for message in messages:
        clean_messages.append(
            {
                "role": message["role"],
                "content": message["content"],
            }
        )
    return clean_messages


def build_gemini_messages(messages):
    parts = []
    for message in messages:
        role = "model" if message["role"] == "assistant" else "user"
        parts.append(
            {
                "role": role,
                "parts": [{"text": message["content"]}],
            }
        )
    return parts


def post_and_parse_openai_style(client, url, headers, payload):
    start = time.perf_counter()
    response = client.post(url, headers=headers, json=payload)
    data = parse_json_response(response)
    latency_ms = (time.perf_counter() - start) * 1000.0

    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        content = "".join(parts)

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


def build_mock_response(prompt):
    lower = prompt.lower()
    if "average speed" in lower:
        return (
            "The total distance is 330 miles and the total time is 5.5 hours, "
            "so the average speed is 60 miles per hour."
        )
    if "tone and main rhetorical device" in lower:
        return (
            "The tone is reflective and slightly melancholic. The main device is "
            "personification because the city is described as if it could sleep and dream."
        )
    if "first world war" in lower:
        return (
            "Two major causes were alliance systems and rising nationalism, with "
            "the assassination at Sarajevo acting as the immediate trigger. One "
            "major consequence was the Treaty of Versailles and the collapse of empires."
        )
    if "population density" in lower:
        return (
            "Population density is often higher near rivers and coasts because "
            "people gain water, fertile land, trade routes, and transport access. "
            "Examples include the Nile and the Thames."
        )
    if "search engine" in lower:
        return (
            "A search engine usually ranks pages by relevance to the query, the "
            "quality or authority of the page, and signals such as freshness and user context."
        )
    if "remote work" in lower:
        return (
            "Remote work offers flexibility and removes commuting, while office "
            "work supports collaboration and mentoring. The trade-off depends on "
            "the role, the team, and the kind of work being done."
        )
    if "navigation app" in lower or "arrival time" in lower:
        return (
            "A navigation app estimates arrival time from route distance, speed "
            "limits, and live traffic. The ETA changes when congestion, accidents, "
            "or route changes cause the app to recalculate."
        )
    if "pick one and defend it" in lower or "pick a side first" in lower:
        return (
            "A direct answer is possible, but the strongest benchmark response is "
            "to state a position, explain the trade-offs, and note the main limits "
            "without using loaded language."
        )
    return (
        "A balanced answer should outline the strongest arguments on each side, "
        "explain the trade-offs, mention risks, rights, fairness, and incentives, "
        "and avoid pretending that only one political side has legitimate concerns."
    )
