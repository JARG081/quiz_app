import json
import time

from django.conf import settings


class ProviderNotConfigured(Exception):
    pass


class ProviderError(Exception):
    pass


class GeminiProvider:
    name = "Gemini"

    def __init__(self, api_key, model=None):
        from google import genai
        self.client = genai.Client(api_key=api_key)
        self.model = model or getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')

    def generate(self, prompt, schema):
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                'response_mime_type': 'application/json',
                'response_schema': schema,
            },
        )
        return json.loads(response.text)


class DeepSeekProvider:
    name = "DeepSeek"

    def __init__(self, api_key, model=None):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, base_url='https://api.deepseek.com', timeout=90)
        self.model = model or getattr(settings, 'DEEPSEEK_MODEL', 'deepseek-chat')

    def generate(self, prompt, schema):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{'role': 'user', 'content': prompt}],
            response_format={'type': 'json_object'},
            timeout=90,
        )
        return json.loads(response.choices[0].message.content)


class OpenAIProvider:
    name = "ChatGPT (OpenAI)"

    def __init__(self, api_key, model=None):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, timeout=90)
        self.model = model or getattr(settings, 'OPENAI_MODEL', 'gpt-4o-mini')

    def generate(self, prompt, schema):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{'role': 'user', 'content': prompt}],
            response_format={'type': 'json_object'},
            timeout=90,
        )
        return json.loads(response.choices[0].message.content)


class ClaudeProvider:
    name = "Claude (Anthropic)"

    def __init__(self, api_key, model=None):
        import urllib.request
        self.api_key = api_key
        self.model = model or getattr(settings, 'CLAUDE_MODEL', 'claude-3-5-haiku-20241022')

    def generate(self, prompt, schema):
        import urllib.request
        url = 'https://api.anthropic.com/v1/messages'
        headers = {
            'x-api-key': self.api_key,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json',
        }
        body = {
            'model': self.model,
            'max_tokens': 4000,
            'messages': [{'role': 'user', 'content': prompt}],
        }
        req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            text = data['content'][0]['text']
            if '```' in text:
                import re
                match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
                if match:
                    text = match.group(1).strip()
            return json.loads(text)


class MultiProviderCascade:
    name = "Multiproveedor Automático"

    def __init__(self, providers):
        self.providers = providers

    def generate(self, prompt, schema):
        errors = []
        for provider in self.providers:
            try:
                return provider.generate(prompt, schema)
            except Exception as exc:
                errors.append(f'{provider.name}: {exc}')
        raise ProviderError(f"Todos los proveedores de IA fallaron. Detalles: {'; '.join(errors)}")


def get_available_providers():
    available = []
    gemini_key = getattr(settings, 'GEMINI_API_KEY', None)
    if gemini_key:
        available.append(GeminiProvider(gemini_key, getattr(settings, 'GEMINI_MODEL', None)))

    deepseek_key = getattr(settings, 'DEEPSEEK_API_KEY', None)
    if deepseek_key:
        available.append(DeepSeekProvider(deepseek_key, getattr(settings, 'DEEPSEEK_MODEL', None)))

    openai_key = getattr(settings, 'OPENAI_API_KEY', None)
    if openai_key:
        available.append(OpenAIProvider(openai_key, getattr(settings, 'OPENAI_MODEL', None)))

    claude_key = getattr(settings, 'CLAUDE_API_KEY', None)
    if claude_key:
        available.append(ClaudeProvider(claude_key, getattr(settings, 'CLAUDE_MODEL', None)))

    return available


def get_provider(selected_name=None):
    provider_setting = getattr(settings, 'QUIZ_AI_PROVIDER', '').lower()
    if not selected_name and provider_setting:
        if provider_setting == 'gemini' and getattr(settings, 'GEMINI_API_KEY', None):
            return GeminiProvider(settings.GEMINI_API_KEY, settings.GEMINI_MODEL)
        if provider_setting == 'deepseek' and getattr(settings, 'DEEPSEEK_API_KEY', None):
            return DeepSeekProvider(settings.DEEPSEEK_API_KEY, settings.DEEPSEEK_MODEL)

    providers = get_available_providers()
    if selected_name:
        name_lower = selected_name.lower()
        for p in providers:
            if p.name.lower().startswith(name_lower) or name_lower in p.name.lower():
                return p

    if providers:
        if len(providers) == 1:
            return providers[0]
        return MultiProviderCascade(providers)

    raise ProviderNotConfigured('La generación con IA no está configurada o no hay llaves de API activas.')


def generate_with_retries(provider, prompt, schema):
    last_error = None
    for attempt in range(3):
        try:
            return provider.generate(prompt, schema)
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    message = str(last_error).lower()
    if '429' in message or 'quota' in message or 'rate limit' in message:
        raise ProviderError('Se agotó la cuota gratuita del proveedor; cambiando automáticamente al siguiente proveedor o intenta más tarde.')
    raise ProviderError(f'No se pudo generar el quiz: {last_error}')


