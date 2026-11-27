"""isyvm agent - CLI entry point."""

from __future__ import annotations
import argparse
import asyncio
import sys
from pathlib import Path

from core.agent import (
    ProviderRegistry, PolicyEngine, RuntimeRegistry, SecretBroker,
    AgentContext, run_agent_once, DEFAULT_SYSTEM_PROMPT
)
from core.agent.chat import run_chat
from core.resident import ResidentRecorder
from core.mode import ModeController, MODES
from core.plan import PlanStore


def create_parser(prog: str = "isyvm agent") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="ISyCode IDE — cliente de terminal con autoridad compartida"
    )
    sub = parser.add_subparsers(dest="cmd", metavar="COMMAND")
    
    # Provider management
    p_prov = sub.add_parser("provider", help="Manage providers")
    p_prov_sub = p_prov.add_subparsers(dest="prov_cmd")
    
    p_add = p_prov_sub.add_parser("add", help="Add provider")
    p_add.add_argument("name", help="Provider name (e.g., nvidia, openai, anthropic)")
    p_add.add_argument("--provider", "-p", choices=["openai", "openai-compatible", "anthropic", "google", "ollama", "nvidia", "codex-subscription", "claude-subscription", "grok-subscription"], required=True)
    p_add.add_argument("--model", "-m", required=True, help="Model name")
    p_add.add_argument("--endpoint", "-e", help="API endpoint")
    p_add.add_argument("--api-key", help="API key (will be stored securely)")
    p_add.add_argument("--auth", choices=["api_key", "none", "subscription"], default=None)
    p_add.add_argument("--timeout", type=float, default=30.0)
    p_add.add_argument("--max-tokens", type=int, default=4096)
    p_add.add_argument("--temperature", type=float, default=0.7)
    
    p_prov_sub.add_parser("list", help="List configured providers")
    p_prov_sub.add_parser("remove", help="Remove provider").add_argument("name")
    p_prov_sub.add_parser("show", help="Show provider config").add_argument("name")
    
    # Secret management
    p_secret = sub.add_parser("secret", help="Manage API keys (secure)")
    p_secret_sub = p_secret.add_subparsers(dest="secret_cmd")
    p_secret_sub.add_parser("list", help="List providers with keys")
    p_secret_sub.add_parser("set", help="Set API key (interactive)").add_argument("provider")
    p_secret_sub.add_parser("remove", help="Remove API key").add_argument("provider")
    p_import = p_secret_sub.add_parser(
        "import-opencode",
        help="Import API keys from opencode's auth.json"
    )
    p_import.add_argument(
        "--path", "-p",
        help="Path to auth.json (default: ~/.local/share/opencode/auth.json)"
    )
    
    # Chat (interactive TUI)
    p_chat = sub.add_parser("chat", help="Interactive chat (TUI)")
    p_chat.add_argument("--provider", "-p", default="openai")
    p_chat.add_argument("--model", "-m", default="gpt-4o")
    p_chat.add_argument("--dir", "-d", default=".", help="Working directory")
    p_chat.add_argument("--max-turns", type=int, default=20)
    
    # Run (non-interactive)
    p_run = sub.add_parser("run", help="Run agent once with prompt")
    p_run.add_argument("prompt", nargs="+", help="Prompt for the agent")
    p_run.add_argument("--provider", "-p", default="openai")
    p_run.add_argument("--model", "-m", default="gpt-4o")
    p_run.add_argument("--dir", "-d", default=".", help="Working directory")
    p_run.add_argument("--max-turns", type=int, default=20)
    p_run.add_argument("--mode", choices=sorted(MODES), help="Override the persisted PLAN/CODER mode")
    p_run.add_argument("--system", help="Custom system prompt")
    p_run.add_argument("--no-stream", action="store_true", help="Disable streaming output")
    
    # Policy
    p_policy = sub.add_parser("policy", help="Show policy rules")
    
    # Config
    p_config = sub.add_parser("config", help="Show config paths")
    
    return parser


def get_components():
    """Get core components."""
    secret_broker = SecretBroker()
    provider_registry = ProviderRegistry(secret_broker)
    policy_engine = PolicyEngine()
    runtime_registry = RuntimeRegistry(Path.cwd())
    return secret_broker, provider_registry, policy_engine, runtime_registry


def cmd_provider(args) -> int:
    secret_broker, provider_registry, _, _ = get_components()
    
    if args.prov_cmd == "add":
        provider_registry.add(
            args.name,
            args.provider,
            args.model,
            endpoint=args.endpoint,
            api_key=args.api_key,
            auth=args.auth or ("subscription" if args.provider.endswith("-subscription") else "none" if args.provider == "ollama" else "api_key"),
            timeout=args.timeout,
            max_tokens=args.max_tokens,
            temperature=args.temperature
        )
        print(f"✅ Provider '{args.name}' added")
        if args.api_key:
            print("✅ API key stored securely")
        return 0
    
    elif args.prov_cmd == "list":
        providers = provider_registry.list()
        if not providers:
            print("No providers configured")
            return 0
        for name, cfg in providers.items():
            has_key = "✅" if provider_registry.has_key(name) else "❌"
            print(f"  {has_key} {name}: {cfg['provider']}/{cfg['model']} ({cfg['endpoint']})")
        return 0
    
    elif args.prov_cmd == "remove":
        if provider_registry.remove(args.name):
            print(f"✅ Provider '{args.name}' removed")
        else:
            print(f"❌ Provider '{args.name}' not found")
        return 0
    
    elif args.prov_cmd == "show":
        providers = provider_registry.list()
        if args.name in providers:
            cfg = providers[args.name]
            has_key = "✅" if provider_registry.has_key(args.name) else "❌"
            print(f"Name: {args.name}")
            print(f"  Provider: {cfg['provider']}")
            print(f"  Model: {cfg['model']}")
            print(f"  Endpoint: {cfg['endpoint']}")
            print(f"  Timeout: {cfg['timeout']}s")
            print(f"  Max tokens: {cfg['max_tokens']}")
            print(f"  Temperature: {cfg['temperature']}")
            print(f"  API Key: {has_key}")
        else:
            print(f"❌ Provider '{args.name}' not found")
        return 0
    
    print("Use: isyvm agent provider [add|list|remove|show]")
    return 1


def cmd_secret(args) -> int:
    secret_broker = SecretBroker()
    
    if args.secret_cmd == "list":
        providers = secret_broker.list_providers()
        if not providers:
            print("No API keys stored")
            return 0
        for p in providers:
            print(f"  ✅ {p}")
        return 0
    
    elif args.secret_cmd == "set":
        if secret_broker.prompt_and_store(args.provider):
            return 0
        return 1
    
    elif args.secret_cmd == "remove":
        if secret_broker.remove(args.provider):
            print(f"✅ API key for '{args.provider}' removed")
        else:
            print(f"❌ No key found for '{args.provider}'")
        return 0
    
    elif args.secret_cmd == "import-opencode":
        try:
            imported = secret_broker.import_from_opencode(
                Path(args.path) if args.path else None
            )
        except FileNotFoundError as e:
            print(f"❌ {e}")
            return 1
        if not imported:
            print("❌ No API keys found in opencode auth.json")
            return 1
        print(f"✅ Imported keys for: {', '.join(imported)}")
        print("   (keyring when available; otherwise memory for this session)")
        return 0
    
    print("Use: isyvm agent secret [list|set|remove|import-opencode]")
    return 1


async def cmd_run_async(args) -> int:
    prompt = " ".join(args.prompt)
    working_dir = Path(args.dir).resolve()
    
    secret_broker, provider_registry, policy_engine, runtime_registry = get_components()
    runtime_registry = RuntimeRegistry(working_dir)
    mode = args.mode or ModeController(working_dir).current()
    plan_context = PlanStore(working_dir).context()
    
    context = AgentContext(
        provider_name=args.provider,
        model=args.model,
        system_prompt=args.system or DEFAULT_SYSTEM_PROMPT,
        working_dir=str(working_dir),
        max_turns=args.max_turns
    )
    
    try:
        async for chunk in run_agent_once(
            prompt=prompt,
            provider=args.provider,
            model=args.model,
            working_dir=str(working_dir),
            max_turns=args.max_turns,
            resident_recorder=ResidentRecorder(working_dir) if (working_dir / ".iesyroot").exists() else None,
            mode=mode,
            plan_context=plan_context,
        ):
            if not args.no_stream:
                print(chunk, end="", flush=True)
            else:
                # Collect and print at end
                pass
        print()  # Final newline
        return 0
    except Exception:
        print("No se pudo completar el turno. Revisa el provider, las credenciales y el modelo.", file=sys.stderr)
        return 1


def cmd_run(args) -> int:
    return asyncio.run(cmd_run_async(args))


def cmd_chat(args) -> int:
    run_chat(
        provider=args.provider,
        model=args.model,
        working_dir=args.dir,
        max_turns=args.max_turns
    )
    return 0


def cmd_policy(args) -> int:
    _, _, policy_engine, _ = get_components()
    rules = policy_engine.get_rules_summary()
    print("[Policy Rules]")
    for i, r in enumerate(rules):
        status = "[ALLOW]" if r["allowed"] else "[DENY]"
        verify = " [verify]" if r["requires_verification"] else ""
        print(f"  {i+1}. {r['action']} -> {r['runtime']} ({status}){verify}")
        print(f"      Condition: {r['condition']}")
        print(f"      Reason: {r['reason']}")
    return 0


def cmd_config(args) -> int:
    from pathlib import Path
    from core.ide_state import state_home
    config_dir = state_home()
    print(f"Config directory: {config_dir}")
    print(f"  Config: {config_dir / 'config.yaml'}")
    print("  Secrets: OS keyring, or memory for this session only")
    print(f"  OS Keyring: {SecretBroker.SERVICE}")
    return 0


def main(argv: list[str] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if argv and argv[0] == "agent":
        argv = argv[1:]
    parser = create_parser(prog="isycode-ide tui" if Path(sys.argv[0]).stem.lower().startswith("isycode") else "isyvm agent")
    args = parser.parse_args(argv)
    
    if not args.cmd:
        parser.print_help()
        return 0
    
    if args.cmd == "provider":
        return cmd_provider(args)
    elif args.cmd == "secret":
        return cmd_secret(args)
    elif args.cmd == "run":
        return cmd_run(args)
    elif args.cmd == "chat":
        return cmd_chat(args)
    elif args.cmd == "policy":
        return cmd_policy(args)
    elif args.cmd == "config":
        return cmd_config(args)
    
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
