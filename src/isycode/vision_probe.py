"""Owned vision probes: a visual challenge, not a model's self-reported OK."""
import asyncio
import base64
import json
import secrets
from isycode.action_runtime import ProviderNetworkOwner
from isycode.chat_transport import provider_complete
from isycode.capability_observations import record, observed
from isycode.provider_errors import classify_provider_error


def challenge():
    from PIL import Image, ImageDraw, ImageFont
    from io import BytesIO
    answer = "".join(secrets.choice("23456789ABCDEFGHJKMNPQRSTUVWXYZ") for _ in range(6))
    image = Image.new("RGB", (640, 180), "white")
    font = ImageFont.truetype("DejaVuSans.ttf", 64)
    ImageDraw.Draw(image).text((35, 45), answer, font=font, fill="black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return answer, buffer.getvalue()


async def availability(root, authority, provider, timeout_s=30):
    messages = [{"role": "user", "content": "Reply OK only."}]
    material = dict(operation="chat.completions", messages=messages, max_tokens=256,
                    tools=None, token_limit_field=provider.token_limit_field,
                    reasoning_effort=provider.reasoning_effort, temperature_supported=provider.temperature_supported)
    result = dict(provider=provider.name, model=provider.model, test="availability", outcome="NOT_DEMONSTRATED")
    try:
        response, receipt = await asyncio.wait_for(ProviderNetworkOwner(root, authority).execute(
            provider, material, lambda: provider_complete(provider, messages, max_tokens=256)), timeout_s)
        if receipt.decision == "ALLOW" and receipt.receipt and isinstance(response, dict):
            result.update(outcome="AVAILABLE", receipt_id=receipt.receipt.receipt_id)
            result["saved"] = record(provider.name, provider.model, "chat_available", True)
    except Exception as exc:
        diagnostic = classify_provider_error(exc)
        result.update(diagnostic)
        if diagnostic["http_status"] == 404:
            result["outcome"] = "ENDPOINT_UNAVAILABLE"
            result["saved"] = record(provider.name, provider.model, "chat_available", False)
    return result


async def probe(root, authority, provider, timeout_s=45):
    answer, data = challenge()
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "Read the six characters printed in this image. Reply only with those characters. If you cannot read the image, reply NO."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode("ascii")}}]}]
    material = dict(operation="chat.completions", messages=messages, max_tokens=256,
                    tools=None, token_limit_field=provider.token_limit_field,
                    reasoning_effort=provider.reasoning_effort, temperature_supported=provider.temperature_supported)
    result = dict(provider=provider.name, model=provider.model, test="vision", outcome="NOT_DEMONSTRATED")
    try:
        response, receipt = await asyncio.wait_for(ProviderNetworkOwner(root, authority).execute(
            provider, material, lambda: provider_complete(provider, messages, max_tokens=256)), timeout_s)
        result["decision"] = receipt.decision
        if receipt.receipt:
            result["receipt_id"] = receipt.receipt.receipt_id
        if receipt.decision == "ALLOW" and isinstance(response, dict):
            output = str(response.get("text", "")).strip()
            result["response"] = output[:120]
            result["expected"] = answer
            if output == answer:
                result["outcome"] = "DEMONSTRATED"
                result["saved"] = record(provider.name, provider.model, "images", True)
            else:
                result["outcome"] = "CHALLENGE_FAILED" # NO or an OCR error is not proof of unsupported vision.
    except Exception as exc:
        diagnostic = classify_provider_error(exc)
        result.update(diagnostic)
        if diagnostic["error_kind"] == "IMAGES":
            result["outcome"] = "EXPLICITLY_UNSUPPORTED"
            result["saved"] = record(provider.name, provider.model, "images", False)
    return result


async def run_catalog(workspace, provider_name, output, models_filter=(), timeout=45, availability_only=False):
    from pathlib import Path
    from isycode.headless import _register_saved_key_reader
    from isycode.providers import Provider, load_provider_key
    from isycode.workspace_authority import WorkspaceAuthority
    root = Path(workspace).resolve(strict=True)
    _register_saved_key_reader(root)
    authority = WorkspaceAuthority(root)
    provider = Provider(name=provider_name, api_key=load_provider_key(provider_name) or None)
    models, outcome = await ProviderNetworkOwner(root, authority).execute(provider,
        {"operation": "models.list", "provider": provider.name, "model": provider.model},
        lambda: asyncio.to_thread(provider.models))
    if outcome.decision != "ALLOW" or not outcome.receipt or models is None:
        raise RuntimeError("Catalog denied or unverifiable; existing provider network grant required")
    selected = [m for m in models if not models_filter or m in models_filter]
    print(json.dumps({"catalog_count": len(models), "selected_count": len(selected)}), flush=True)
    with Path(output).open("x") as stream:
        for model in selected:
            current = Provider(name=provider_name, model=model, api_key=load_provider_key(provider_name) or None)
            health = await availability(root, authority, current, timeout)
            stream.write(json.dumps(health) + "\n")
            stream.flush()
            print(json.dumps(health), flush=True)
            if not availability_only and health["outcome"] == "AVAILABLE":
                result = await probe(root, authority, current, timeout)
                stream.write(json.dumps(result) + "\n")
                stream.flush()
                print(json.dumps(result), flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--provider", default="nvidia")
    parser.add_argument("--model", action="append", default=[])
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--availability-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(run_catalog(args.workspace, args.provider, args.output, args.model, args.timeout, args.availability_only))
